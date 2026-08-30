"""Hey uh don't be a dick with this, okay? Okay."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import struct
import tempfile
from typing import BinaryIO, Callable
import zlib


LSPK_SIGNATURE = b"LSPK"
SUPPORTED_PACKAGE_VERSIONS = (16, 18)
PACKAGE_HEADER_SIZE = 40
FILE_ENTRY_V16 = struct.Struct("<256sQQQIIII")
FILE_ENTRY_V18 = struct.Struct("<256sIHBBII")
ZLIB_COMPRESSION_METHOD = 1
LZ4_COMPRESSION_METHOD = 2
ZSTD_COMPRESSION_METHOD = 3
ZSTD_FRAME_MAGIC = b"\x28\xb5\x2f\xfd"
COMPRESSION_METHOD_NAMES = {
    ZLIB_COMPRESSION_METHOD: "Zlib",
    LZ4_COMPRESSION_METHOD: "LZ4",
    ZSTD_COMPRESSION_METHOD: "Zstandard",
}
FILE_TABLE_SHIFT = 64
COPY_CHUNK_SIZE = 1024 * 1024
MAX_FILE_COUNT = 1_000_000


@dataclass(frozen=True)
class PakFinalisationResult:
    source: Path
    destination: Path
    processed_path: str
    original_file_count: int
    final_file_count: int


@dataclass(frozen=True)
class PakIndexRestorationResult:
    source: Path
    destination: Path
    processed_paths: tuple[str, ...]
    original_file_count: int
    final_file_count: int


class PakIndexRestorationNotNeededError(ValueError):
    pass


@dataclass(frozen=True)
class _PackageEntry:
    raw_name: bytes
    name: str
    offset: int
    size_on_disk: int
    uncompressed_size: int
    archive_part: int
    flags: int
    crc: int
    unknown: int

    @property
    def compression_method(self) -> int:
        return self.flags & 0x0F

    def pack(self, version: int) -> bytes:
        if version == 16:
            return FILE_ENTRY_V16.pack(
                self.raw_name,
                self.offset,
                self.size_on_disk,
                self.uncompressed_size,
                self.archive_part,
                self.flags,
                self.crc,
                self.unknown,
            )
        if version == 18:
            if self.offset > 0xFFFFFFFFFFFF:
                raise ValueError("A V18 package entry offset exceeds 48 bits.")
            if self.size_on_disk > 0xFFFFFFFF:
                raise ValueError("A V18 package entry size exceeds 32 bits.")
            if self.uncompressed_size > 0xFFFFFFFF:
                raise ValueError("A V18 package entry size exceeds 32 bits.")
            if self.archive_part > 0xFF:
                raise ValueError("A V18 package entry part exceeds 8 bits.")
            if self.flags > 0xFF:
                raise ValueError("A V18 package entry flags field exceeds 8 bits.")
            return FILE_ENTRY_V18.pack(
                self.raw_name,
                self.offset & 0xFFFFFFFF,
                self.offset >> 32,
                self.archive_part,
                self.flags,
                self.size_on_disk,
                self.uncompressed_size,
            )
        raise ValueError(f"Unsupported package version: {version}.")


@dataclass(frozen=True)
class _PackageInfo:
    header: bytes
    version: int
    file_list_offset: int
    file_count: int
    entries: tuple[_PackageEntry, ...]


def default_finalised_pak_path(source: str | Path) -> Path:
    source_path = Path(source)
    return source_path.with_name(f"{source_path.stem}_finalised.pak")


def default_restored_pak_path(source: str | Path) -> Path:
    source_path = Path(source)
    return source_path.with_name(f"{source_path.stem}_restored.pak")


def default_extracted_pak_path(source: str | Path) -> Path:
    source_path = Path(source)
    return source_path.with_name(f"{source_path.stem}_extracted")


def decompress_lz4_block(source: bytes, expected_size: int) -> bytes:

    if expected_size < 0:
        raise ValueError("The expected LZ4 output size cannot be negative.")

    output = bytearray()
    cursor = 0
    while cursor < len(source):
        token = source[cursor]
        cursor += 1

        literal_length = token >> 4
        if literal_length == 15:
            literal_length, cursor = _read_lz4_length(
                source, cursor, literal_length
            )
        literal_end = cursor + literal_length
        if literal_end > len(source):
            raise ValueError("The package file table has a truncated LZ4 literal.")
        output.extend(source[cursor:literal_end])
        cursor = literal_end
        if len(output) > expected_size:
            raise ValueError("The package file table expands beyond its expected size.")
        if cursor == len(source):
            break
        if cursor + 2 > len(source):
            raise ValueError("The package file table has a truncated LZ4 offset.")

        match_offset = source[cursor] | (source[cursor + 1] << 8)
        cursor += 2
        if match_offset == 0 or match_offset > len(output):
            raise ValueError("The package file table has an invalid LZ4 offset.")

        match_length = token & 0x0F
        if match_length == 15:
            match_length, cursor = _read_lz4_length(
                source, cursor, match_length
            )
        match_length += 4
        if len(output) + match_length > expected_size:
            raise ValueError("The package file table expands beyond its expected size.")
        for _ in range(match_length):
            output.append(output[-match_offset])

    if len(output) != expected_size:
        raise ValueError(
            f"Incorrect package file-table size: {len(output)}; "
            f"expected {expected_size}."
        )
    return bytes(output)


def compress_lz4_literal_block(source: bytes) -> bytes:

    literal_length = len(source)
    output = bytearray((min(literal_length, 15) << 4,))
    if literal_length >= 15:
        remaining = literal_length - 15
        while remaining >= 255:
            output.append(255)
            remaining -= 255
        output.append(remaining)
    output.extend(source)
    return bytes(output)


def finalise_pak(
    source: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
) -> PakFinalisationResult:

    source_path = Path(source)
    destination_path = (
        default_finalised_pak_path(source_path)
        if destination is None
        else Path(destination)
    )
    _validate_paths(source_path, destination_path, overwrite=overwrite)
    log = progress or (lambda _message: None)

    source_size = source_path.stat().st_size
    with source_path.open("rb") as source_stream:
        package = _read_package_info(source_stream, source_size)
        target_index = _find_finalisation_target(source_stream, package)
        target = package.entries[target_index]
        final_entry = _PackageEntry(
            raw_name=target.raw_name,
            name=target.name,
            offset=target.offset + FILE_TABLE_SHIFT,
            size_on_disk=target.size_on_disk - FILE_TABLE_SHIFT,
            uncompressed_size=target.uncompressed_size,
            archive_part=target.archive_part,
            flags=target.flags,
            crc=(
                target.crc ^ 0xFFFFFFFF
                if package.version == 16
                else target.crc
            ),
            unknown=target.unknown,
        )

        final_entries = list(package.entries)
        final_entries.insert(target_index, final_entry)
        header, file_list = _rebuild_file_table(package, final_entries)

        log(f"Source package: {source_path}\n")
        log(f"Output package: {destination_path}\n")
        log(f"File-table record: {target.name}\n")
        log(
            "Record compression: "
            f"{COMPRESSION_METHOD_NAMES[target.compression_method]}\n"
        )
        _write_finalised_copy(
            source_stream,
            destination_path,
            bytes(header),
            package.file_list_offset,
            file_list,
        )

    log(
        f"File-table records: {package.file_count} -> "
        f"{len(final_entries)}\n"
    )
    return PakFinalisationResult(
        source=source_path,
        destination=destination_path,
        processed_path=target.name,
        original_file_count=package.file_count,
        final_file_count=len(final_entries),
    )


def restore_pak_indexes(
    source: str | Path,
    destination: str | Path | None = None,
    *,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
) -> PakIndexRestorationResult:
    source_path = Path(source)
    destination_path = (
        default_restored_pak_path(source_path)
        if destination is None
        else Path(destination)
    )
    _validate_paths(source_path, destination_path, overwrite=overwrite)
    log = progress or (lambda _message: None)

    source_size = source_path.stat().st_size
    with source_path.open("rb") as source_stream:
        package = _read_package_info(
            source_stream,
            source_size,
            allow_duplicate_names=True,
        )
        indexes_to_restore = _find_restorable_index_records(source_stream, package)
        if not indexes_to_restore:
            raise PakIndexRestorationNotNeededError(
                "The package indexes do not contain recognised finalisation changes."
            )

        restored_entries = [
            entry
            for index, entry in enumerate(package.entries)
            if index not in indexes_to_restore
        ]
        header, file_list = _rebuild_file_table(package, restored_entries)

        processed_paths = tuple(
            package.entries[index].name for index in sorted(indexes_to_restore)
        )
        log(f"Source package: {source_path}\n")
        log(f"Output package: {destination_path}\n")
        for processed_path in processed_paths:
            log(f"Restored package index: {processed_path}\n")
        _write_finalised_copy(
            source_stream,
            destination_path,
            header,
            package.file_list_offset,
            file_list,
        )

    log(
        f"File-table records: {package.file_count} -> "
        f"{len(restored_entries)}\n"
    )
    return PakIndexRestorationResult(
        source=source_path,
        destination=destination_path,
        processed_paths=processed_paths,
        original_file_count=package.file_count,
        final_file_count=len(restored_entries),
    )


def _read_lz4_length(
    source: bytes, cursor: int, current_length: int
) -> tuple[int, int]:
    while True:
        if cursor >= len(source):
            raise ValueError("The package file table has a truncated LZ4 length.")
        extension = source[cursor]
        cursor += 1
        current_length += extension
        if extension != 255:
            return current_length, cursor


def _validate_paths(source: Path, destination: Path, *, overwrite: bool) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Package does not exist: {source}")
    if source.suffix.lower() != ".pak":
        raise ValueError("The source must be a .pak file.")
    if destination.suffix.lower() != ".pak":
        raise ValueError("The output package must use the .pak extension.")

    source_key = os.path.normcase(str(source.resolve()))
    destination_key = os.path.normcase(str(destination.resolve()))
    if source_key == destination_key:
        raise ValueError("The output package cannot overwrite the source package.")
    if destination.exists() and not destination.is_file():
        raise IsADirectoryError(
            f"The output package destination is not a file: {destination}"
        )
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Output package already exists: {destination}")


def _read_package_info(
    source: BinaryIO,
    source_size: int,
    *,
    allow_duplicate_names: bool = False,
) -> _PackageInfo:
    source.seek(0)
    header = source.read(PACKAGE_HEADER_SIZE)
    if len(header) != PACKAGE_HEADER_SIZE:
        raise ValueError("The package is too small to contain a supported header.")
    if header[:4] != LSPK_SIGNATURE:
        raise ValueError("The selected file is not an LSPK package.")

    version = struct.unpack_from("<I", header, 4)[0]
    if version not in SUPPORTED_PACKAGE_VERSIONS:
        raise ValueError(
            "PAK tools currently support package version 16 or 18; "
            f"got {version}."
        )
    file_list_offset = struct.unpack_from("<Q", header, 8)[0]
    file_list_size = struct.unpack_from("<I", header, 16)[0]
    archive_parts = struct.unpack_from("<H", header, 38)[0]
    if archive_parts != 1:
        raise ValueError("Split or multi-part packages are not supported.")
    if file_list_offset < PACKAGE_HEADER_SIZE or file_list_size < 8:
        raise ValueError("The package has an invalid file-table location.")
    if file_list_offset + file_list_size != source_size:
        raise ValueError("The package file table is not the final package section.")

    source.seek(file_list_offset)
    file_list_header = source.read(8)
    if len(file_list_header) != 8:
        raise ValueError("The package file-table header is truncated.")
    file_count, compressed_size = struct.unpack("<II", file_list_header)
    if file_count == 0 or file_count > MAX_FILE_COUNT:
        raise ValueError(f"The package has an invalid file count: {file_count}.")
    if compressed_size + 8 != file_list_size:
        raise ValueError("The package file-table size fields do not agree.")
    compressed_file_list = source.read(compressed_size)
    if len(compressed_file_list) != compressed_size:
        raise ValueError("The package file table is truncated.")

    file_entry = FILE_ENTRY_V16 if version == 16 else FILE_ENTRY_V18
    expected_size = file_count * file_entry.size
    raw_file_list = decompress_lz4_block(compressed_file_list, expected_size)
    entries = tuple(
        _unpack_entry(raw_file_list, index, version)
        for index in range(file_count)
    )
    names: set[str] = set()
    for entry in entries:
        name_key = entry.name.casefold()
        if name_key in names and not allow_duplicate_names:
            raise ValueError(
                f"The package contains a duplicate internal path and cannot be "
                f"finalised safely: {entry.name}"
            )
        names.add(name_key)
        _validate_internal_path(entry.name)
        if entry.archive_part != 0:
            raise ValueError("Split or multi-part package entries are not supported.")
        if entry.offset + entry.size_on_disk > file_list_offset:
            raise ValueError(f"Package entry extends outside the payload: {entry.name}")

    return _PackageInfo(
        header=header,
        version=version,
        file_list_offset=file_list_offset,
        file_count=file_count,
        entries=entries,
    )


def _validate_internal_path(name: str) -> None:
    internal_path = PurePosixPath(name.replace("\\", "/"))
    if (
        internal_path.is_absolute()
        or ".." in internal_path.parts
        or any(":" in part for part in internal_path.parts)
    ):
        raise ValueError(f"Package contains an unsafe internal path: {name}")


def _unpack_entry(
    raw_file_list: bytes, index: int, version: int
) -> _PackageEntry:
    if version == 16:
        fields = FILE_ENTRY_V16.unpack_from(
            raw_file_list, index * FILE_ENTRY_V16.size
        )
        (
            raw_name,
            offset,
            size_on_disk,
            uncompressed_size,
            part,
            flags,
            crc,
            unknown,
        ) = fields
    else:
        fields = FILE_ENTRY_V18.unpack_from(
            raw_file_list, index * FILE_ENTRY_V18.size
        )
        (
            raw_name,
            offset_low,
            offset_high,
            part,
            flags,
            size_on_disk,
            uncompressed_size,
        ) = fields
        offset = offset_low | (offset_high << 32)
        crc = 0
        unknown = 0
    name_bytes = raw_name.split(b"\0", 1)[0]
    if not name_bytes:
        raise ValueError(f"Package file-table record {index} has no path.")
    try:
        name = name_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Package file-table record {index} has a non-UTF-8 path."
        ) from exc
    return _PackageEntry(
        raw_name=raw_name,
        name=name,
        offset=offset,
        size_on_disk=size_on_disk,
        uncompressed_size=uncompressed_size,
        archive_part=part,
        flags=flags,
        crc=crc,
        unknown=unknown,
    )


def _find_finalisation_target(source: BinaryIO, package: _PackageInfo) -> int:
    for index, entry in enumerate(package.entries):
        internal_path = PurePosixPath(entry.name.replace("\\", "/"))
        if internal_path.name.casefold() == "meta.lsx":
            continue
        validator = _compression_validator(entry)
        if validator is None:
            continue
        if entry.size_on_disk <= FILE_TABLE_SHIFT:
            continue
        if validator(source, entry):
            return index
    raise ValueError(
        "The package has no suitable non-metadata compressed record larger than "
        "64 bytes. Supported methods are Zlib, LZ4, and Zstandard."
    )


def _find_restorable_index_records(
    source: BinaryIO, package: _PackageInfo
) -> set[int]:
    indexes_to_restore: set[int] = set()
    for index in range(len(package.entries) - 1):
        shifted = package.entries[index]
        original = package.entries[index + 1]
        if shifted.raw_name != original.raw_name:
            continue
        if shifted.offset != original.offset + FILE_TABLE_SHIFT:
            continue
        if shifted.size_on_disk + FILE_TABLE_SHIFT != original.size_on_disk:
            continue
        if shifted.uncompressed_size != original.uncompressed_size:
            continue
        if shifted.archive_part != original.archive_part:
            continue
        if shifted.flags != original.flags or shifted.unknown != original.unknown:
            continue
        expected_crc = (
            original.crc ^ 0xFFFFFFFF
            if package.version == 16
            else original.crc
        )
        if shifted.crc != expected_crc:
            continue
        validator = _compression_validator(original)
        if validator is None or not validator(source, original):
            continue
        indexes_to_restore.add(index)
    return indexes_to_restore


def _compression_validator(
    entry: _PackageEntry,
) -> Callable[[BinaryIO, _PackageEntry], bool] | None:
    return {
        ZLIB_COMPRESSION_METHOD: _is_valid_zlib_entry,
        LZ4_COMPRESSION_METHOD: _is_valid_lz4_entry,
        ZSTD_COMPRESSION_METHOD: _is_valid_zstd_entry,
    }.get(entry.compression_method)


def _rebuild_file_table(
    package: _PackageInfo, entries: list[_PackageEntry]
) -> tuple[bytes, bytes]:
    raw_file_list = b"".join(entry.pack(package.version) for entry in entries)
    compressed_file_list = compress_lz4_literal_block(raw_file_list)
    file_list_size = 8 + len(compressed_file_list)
    if file_list_size > 0xFFFFFFFF:
        raise ValueError("The rebuilt package file table is too large.")

    header = bytearray(package.header)
    struct.pack_into("<I", header, 16, file_list_size)
    file_list = (
        struct.pack("<II", len(entries), len(compressed_file_list))
        + compressed_file_list
    )
    return bytes(header), file_list


def _is_valid_zlib_entry(source: BinaryIO, entry: _PackageEntry) -> bool:
    source.seek(entry.offset)
    remaining = entry.size_on_disk
    uncompressed_size = 0
    decompressor = zlib.decompressobj()
    try:
        while remaining:
            chunk = source.read(min(remaining, COPY_CHUNK_SIZE))
            if not chunk:
                return False
            remaining -= len(chunk)
            pending = chunk
            while pending:
                output = decompressor.decompress(pending, COPY_CHUNK_SIZE)
                uncompressed_size += len(output)
                pending = decompressor.unconsumed_tail
        uncompressed_size += len(decompressor.flush())
    except zlib.error:
        return False
    return (
        decompressor.eof
        and not decompressor.unused_data
        and uncompressed_size == entry.uncompressed_size
    )


def _is_valid_lz4_entry(source: BinaryIO, entry: _PackageEntry) -> bool:

    source.seek(entry.offset)
    entry_end = entry.offset + entry.size_on_disk
    output_size = 0

    while source.tell() < entry_end:
        token_bytes = source.read(1)
        if len(token_bytes) != 1:
            return False
        token = token_bytes[0]

        literal_length = token >> 4
        if literal_length == 15:
            literal_length = _read_lz4_stream_length(
                source, entry_end, literal_length
            )
            if literal_length is None:
                return False
        if source.tell() + literal_length > entry_end:
            return False
        output_size += literal_length
        if output_size > entry.uncompressed_size:
            return False
        source.seek(literal_length, os.SEEK_CUR)
        if source.tell() == entry_end:
            return output_size == entry.uncompressed_size

        if source.tell() + 2 > entry_end:
            return False
        offset_bytes = source.read(2)
        match_offset = offset_bytes[0] | (offset_bytes[1] << 8)
        if match_offset == 0 or match_offset > output_size:
            return False

        match_length = token & 0x0F
        if match_length == 15:
            match_length = _read_lz4_stream_length(
                source, entry_end, match_length
            )
            if match_length is None:
                return False
        output_size += match_length + 4
        if output_size > entry.uncompressed_size:
            return False
        if source.tell() == entry_end:
            return output_size == entry.uncompressed_size

    return False


def _read_lz4_stream_length(
    source: BinaryIO, entry_end: int, current_length: int
) -> int | None:
    while source.tell() < entry_end:
        extension_bytes = source.read(1)
        if len(extension_bytes) != 1:
            return None
        extension = extension_bytes[0]
        current_length += extension
        if extension != 255:
            return current_length
    return None


def _is_valid_zstd_entry(source: BinaryIO, entry: _PackageEntry) -> bool:
    source.seek(entry.offset)
    return source.read(len(ZSTD_FRAME_MAGIC)) == ZSTD_FRAME_MAGIC


def _write_finalised_copy(
    source: BinaryIO,
    destination: Path,
    header: bytes,
    file_list_offset: int,
    file_list: bytes,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(header)
            source.seek(PACKAGE_HEADER_SIZE)
            _copy_exact(
                source,
                output,
                file_list_offset - PACKAGE_HEADER_SIZE,
            )
            output.write(file_list)
        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _copy_exact(source: BinaryIO, destination: BinaryIO, byte_count: int) -> None:
    remaining = byte_count
    while remaining:
        chunk = source.read(min(remaining, COPY_CHUNK_SIZE))
        if not chunk:
            raise ValueError("The source package changed while it was being copied.")
        destination.write(chunk)
        remaining -= len(chunk)


__all__ = [
    "PakIndexRestorationNotNeededError",
    "PakFinalisationResult",
    "PakIndexRestorationResult",
    "compress_lz4_literal_block",
    "decompress_lz4_block",
    "default_extracted_pak_path",
    "default_finalised_pak_path",
    "default_restored_pak_path",
    "finalise_pak",
    "restore_pak_indexes",
]
