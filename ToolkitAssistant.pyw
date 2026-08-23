"""Toolkit Assistant launcher."""

from __future__ import annotations

from pathlib import Path
import sys


if getattr(sys, "frozen", False):
    sys.dont_write_bytecode = True
    bundled_lib = Path(sys.executable).resolve().parent / "lib"
    if bundled_lib.is_dir():
        sys.path.insert(0, str(bundled_lib))

from toolkit_assistant.lumi_app import main


if __name__ == "__main__":
    raise SystemExit(main())
