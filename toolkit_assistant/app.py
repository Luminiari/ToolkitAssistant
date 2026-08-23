from __future__ import annotations

import os
from pathlib import Path
import queue
import sys
import threading
import webbrowser

from luminiari_ui import LumiToolTip

from .bounds_patcher import (
    parse_uuid_values,
    patch_all_visualbank_lsf_files,
    patch_lsf_file,
    patch_lsf_files_by_uuid,
    patch_lsf_from_related_mesh,
    patch_visualbank_lsf_files_from_related_mesh,
)
from .constants import (
    ABOUT_LINKS,
    ACCENT_COLOR,
    APP_TITLE,
    APP_VERSION,
    CONSOLE_ICON_PATH,
    EXPERIMENTAL_FEATURES_UNLOCKED_KEY,
    INTRO_DISMISSED_KEY,
    RESOURCE_DIR,
    SETTINGS_PATH,
    TEMPORARY_FILES_ROOT,
    TEMPORARY_RENAME_BACKUP_RETENTION_DAYS,
    TEMPORARY_RENAME_BACKUP_ROOT,
)
from .divine import resolve_divine
from .import_repair import repair_import_settings_sources
from .mesh_bounds import calculate_mesh_bounds, format_mesh_bounds_xml
from .pak_finalisation import default_finalised_pak_path, finalise_pak
from .paths import get_game_folder_error
from .project_tools import backup_toolkit_projects, rename_toolkit_mod_project
from .settings import save_settings
from .temp_files import delete_temp_folder_contents
from .ui_theme import (
    ACCENT_COLOR_SETTING_KEY,
    UI_THEME_DARK,
    UI_THEME_LIGHT,
    UI_THEME_SETTING_KEY,
    derive_accent_palette,
    normalize_accent_color,
)


tk = None
colorchooser = None
filedialog = None
messagebox = None
ttk = None


def load_tk() -> None:
    global tk, colorchooser, filedialog, messagebox, ttk
    if tk is not None:
        return

    tcl_dir = RESOURCE_DIR / "lib" / "tcl"
    tk_dir = RESOURCE_DIR / "lib" / "tk"
    if tcl_dir.is_dir():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
    if tk_dir.is_dir():
        os.environ.setdefault("TK_LIBRARY", str(tk_dir))

    import tkinter as tk_module
    from tkinter import colorchooser as colorchooser_module
    from tkinter import filedialog as filedialog_module
    from tkinter import messagebox as messagebox_module
    from tkinter import ttk as ttk_module

    tk = tk_module
    colorchooser = colorchooser_module
    filedialog = filedialog_module
    messagebox = messagebox_module
    ttk = ttk_module

class ToolkitAssistantApp:

    def mainloop(self) -> None:
        self.root.mainloop()

    def _set_accent_palette(self, accent_color: object) -> None:
        palette = derive_accent_palette(normalize_accent_color(accent_color))
        self.accent_color = palette["accent"]
        self.accent_dark_color = palette["dark"]
        self.accent_light_color = palette["light"]
        self.accent_foreground_color = palette["foreground"]

    def _choose_accent_color(self) -> None:
        _rgb, selected_color = colorchooser.askcolor(
            color=self.accent_color,
            parent=self.root,
            title="Choose accent colour",
        )
        if selected_color:
            self._set_accent_color(selected_color)
            if hasattr(self, "settings_status_label"):
                self._set_status(self.settings_status_label, "Accent colour updated")

    def _reset_accent_color(self) -> None:
        self._set_accent_color(ACCENT_COLOR)
        if hasattr(self, "settings_status_label"):
            self._set_status(self.settings_status_label, "Accent colour reset")

    def _save_accent_preference(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not save accent colour: {exc}")

    def _add_wrapping_label(self, parent, text: str, *, row: int = 0, pady: tuple[int, int] | None = None, style: str | None = None):
        label_options = {
            "text": text,
            "justify": "left",
            "wraplength": 1,
        }
        if style:
            label_options["style"] = style

        label = ttk.Label(parent, **label_options)
        grid_options = {
            "row": row,
            "column": 0,
            "sticky": "ew",
        }
        if pady is not None:
            grid_options["pady"] = pady
        label.grid(**grid_options)

        def update_wrap(event=None) -> None:
            width = event.width if event is not None else parent.winfo_width()
            label.configure(wraplength=max(width - 24, 120))

        parent.bind("<Configure>", update_wrap, add="+")
        label.after_idle(update_wrap)
        return label

    def _build_spacer_row(self, tab, row: int, *, columnspan: int = 3):
        spacer = ttk.Frame(tab)
        spacer.grid(row=row, column=0, columnspan=columnspan, sticky="nsew")
        return spacer

    def _build_tab_footer(self, tab, row: int, *, columnspan: int = 3):
        footer = ttk.Frame(tab)
        footer.grid(row=row, column=0, columnspan=columnspan, sticky="sew")
        footer.columnconfigure(0, weight=1)
        footer.rowconfigure(0, weight=1)

        status_label = ttk.Label(footer, text="", style="Accent.TLabel")
        status_label.grid(row=0, column=0, sticky="sw")

        return status_label

    def _set_status(
        self,
        status_label,
        text: str,
        *,
        clear_after_ms: int | None = 5000,
    ) -> None:
        timers = getattr(self, "status_clear_timers", None)
        if timers is None:
            timers = {}
            self.status_clear_timers = timers

        existing_timer = timers.pop(status_label, None)
        if existing_timer is not None:
            try:
                self.root.after_cancel(existing_timer)
            except tk.TclError:
                pass

        status_label.configure(text=text)
        if not text or clear_after_ms is None:
            return

        timer_id = None

        def clear_status() -> None:
            if timers.get(status_label) != timer_id:
                return
            timers.pop(status_label, None)
            try:
                if status_label.winfo_exists():
                    status_label.configure(text="")
            except tk.TclError:
                pass

        timer_id = self.root.after(clear_after_ms, clear_status)
        timers[status_label] = timer_id

    def _load_console_icon(self):
        if self.console_icon is not None:
            return self.console_icon
        self.console_icon = self._load_tinted_icon(CONSOLE_ICON_PATH.name, target_size=16)
        return self.console_icon

    def _toggle_console_window(self) -> None:
        self._ensure_console_window()
        if self.console_window.state() == "withdrawn":
            self._show_console_window()
        else:
            self._hide_console_window()

    def _show_console_window(self) -> None:
        self._ensure_console_window()
        self.console_window.deiconify()
        self.console_window.lift()
        self.console_window.focus_set()

    def _hide_console_window(self) -> None:
        if self.console_window is not None and self.console_window.winfo_exists():
            self.console_window.withdraw()

    def _clear_console_output(self) -> None:
        self._ensure_console_window()
        output = self.console_output_text
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.configure(state="disabled")

    def _start_console_section(self) -> None:
        self._ensure_console_window()
        existing_text = self.console_output_text.get("1.0", "end-1c")
        prefix = "\n\n" if existing_text else ""
        section_name = self.active_output_name or "Run"
        self._append_output(f"{prefix}[{section_name}]\n", "section")

    def _build_mesh_bounds_tab(self, tab) -> None:
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)

        ttk.Label(tab, text="Mesh file").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(tab, textvariable=self.mesh_file_path).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(tab, text="Browse", command=self._browse_mesh_file).grid(row=0, column=2, sticky="ew")

        note_box = ttk.LabelFrame(tab, text="Info", padding=10, style="Accent.TLabelframe")
        note_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            (
                "Legacy manual helper. Calculate bounds XML from a .gr2 or .dae mesh."
            ),
        )

        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        self.mesh_bounds_run_button = ttk.Button(
            actions,
            text="Get Bounds",
            command=self._start_mesh_bounds,
            style="Accent.TButton",
        )
        self.mesh_bounds_run_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.run_buttons.append(self.mesh_bounds_run_button)
        ttk.Button(
            actions,
            text="Copy Bounds",
            command=self._copy_mesh_bounds,
            style="Accent.TButton",
        ).grid(row=0, column=2, sticky="e")

        self._build_spacer_row(tab, 3)
        self.mesh_bounds_status_label = self._build_tab_footer(tab, 4)

    def _build_patch_lsf_tab(self, tab) -> None:
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(5, weight=1)

        note_box = ttk.LabelFrame(tab, text="Info", padding=10, style="Accent.TLabelframe")
        note_box.grid(row=0, column=0, columnspan=3, sticky="ew")
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            (
                "Legacy manual patcher. Paste bounds XML, choose a single LSF or UUID batch target, then patch."
            ),
        )

        ttk.Label(tab, text="Mode").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(12, 0))
        mode_frame = ttk.Frame(tab)
        mode_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Single file",
            value="single",
            variable=self.patch_lsf_mode,
            command=self._update_patch_lsf_mode,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Radiobutton(
            mode_frame,
            text="UUID batch",
            value="uuid",
            variable=self.patch_lsf_mode,
            command=self._update_patch_lsf_mode,
        ).grid(row=0, column=1, sticky="w")

        self.patch_single_target_frame = ttk.Frame(tab)
        self.patch_single_target_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.patch_single_target_frame.columnconfigure(1, weight=1)
        ttk.Label(self.patch_single_target_frame, text="LSF file").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(self.patch_single_target_frame, textvariable=self.patch_single_lsf_path).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        ttk.Button(self.patch_single_target_frame, text="Browse", command=self._browse_patch_single_lsf).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        self.patch_batch_target_frame = ttk.Frame(tab)
        self.patch_batch_target_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.patch_batch_target_frame.columnconfigure(1, weight=1)
        ttk.Label(self.patch_batch_target_frame, text="Content folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        patch_batch_root_controls = ttk.Frame(self.patch_batch_target_frame)
        patch_batch_root_controls.grid(row=0, column=1, sticky="ew")
        patch_batch_root_controls.columnconfigure(0, weight=1)
        ttk.Entry(patch_batch_root_controls, textvariable=self.patch_batch_root_path).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 8),
        )
        ttk.Button(patch_batch_root_controls, text="Browse", command=self._browse_patch_lsf_root).grid(
            row=0,
            column=1,
            sticky="ew",
        )

        ttk.Label(self.patch_batch_target_frame, text="UUIDs").grid(
            row=1,
            column=0,
            sticky="nw",
            padx=(0, 8),
            pady=(12, 0),
        )
        patch_uuid_controls = ttk.Frame(self.patch_batch_target_frame)
        patch_uuid_controls.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        patch_uuid_controls.columnconfigure(0, weight=1)
        self.patch_uuid_text = tk.Text(
            patch_uuid_controls,
            height=4,
            wrap="word",
            font=("Consolas", 10),
            undo=True,
        )
        self.patch_uuid_text.grid(row=0, column=0, sticky="ew")
        uuid_scrollbar = ttk.Scrollbar(patch_uuid_controls, command=self.patch_uuid_text.yview)
        uuid_scrollbar.grid(row=0, column=1, sticky="ns")
        self.patch_uuid_text.configure(yscrollcommand=uuid_scrollbar.set)

        ttk.Label(tab, text="Bounds").grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=(12, 0))
        self.patch_bounds_text = tk.Text(
            tab,
            height=4,
            wrap="none",
            font=("Consolas", 10),
            undo=True,
        )
        self.patch_bounds_text.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(12, 0))

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Checkbutton(actions, text="Keep edited LSX", variable=self.patch_lsf_keep_lsx).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(0, 16),
        )
        ttk.Checkbutton(actions, text="Backup original", variable=self.patch_lsf_backup_original).grid(
            row=0,
            column=2,
            sticky="e",
            padx=(0, 16),
        )
        self.patch_lsf_run_button = ttk.Button(
            actions,
            text="Patch LSF(s)",
            command=self._start_patch_lsf_run,
            style="Accent.TButton",
        )
        self.patch_lsf_run_button.grid(row=0, column=3, sticky="e")
        self.run_buttons.append(self.patch_lsf_run_button)

        self._build_spacer_row(tab, 5)
        self.patch_status_label = self._build_tab_footer(tab, 6)

        self._update_patch_lsf_mode()

    def _build_auto_bounds_tab(self, tab) -> None:
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(4, weight=1)

        ttk.Label(tab, text="Mode").grid(row=0, column=0, sticky="w", padx=(0, 8))
        mode_frame = ttk.Frame(tab)
        mode_frame.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(
            mode_frame,
            text="Batch",
            value="batch",
            variable=self.auto_bounds_mode,
            command=self._update_auto_bounds_mode,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Radiobutton(
            mode_frame,
            text="Whole Folder",
            value="whole_folder",
            variable=self.auto_bounds_mode,
            command=self._update_auto_bounds_mode,
        ).grid(row=0, column=1, sticky="w")

        self.auto_selected_target_frame = ttk.Frame(tab)
        self.auto_selected_target_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.auto_selected_target_frame.columnconfigure(1, weight=1)
        ttk.Label(self.auto_selected_target_frame, text="LSF file(s)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(self.auto_selected_target_frame, textvariable=self.auto_selected_lsf_summary).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 8),
        )
        ttk.Button(self.auto_selected_target_frame, text="Select File(s)", command=self._browse_auto_selected_lsfs).grid(
            row=0,
            column=2,
            sticky="ew",
        )
        selected_list_frame = ttk.Frame(self.auto_selected_target_frame)
        selected_list_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        selected_list_frame.columnconfigure(0, weight=1)
        self.auto_selected_lsf_listbox = tk.Listbox(
            selected_list_frame,
            height=4,
            font=("Consolas", 9),
            activestyle="none",
            exportselection=False,
        )
        self.auto_selected_lsf_listbox.grid(row=0, column=0, sticky="ew")
        selected_list_scrollbar = ttk.Scrollbar(selected_list_frame, command=self.auto_selected_lsf_listbox.yview)
        selected_list_scrollbar.grid(row=0, column=1, sticky="ns")
        self.auto_selected_lsf_listbox.configure(yscrollcommand=selected_list_scrollbar.set)

        self.auto_batch_target_frame = ttk.Frame(tab)
        self.auto_batch_target_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.auto_batch_target_frame.columnconfigure(1, weight=1)
        ttk.Label(self.auto_batch_target_frame, text="Content folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(self.auto_batch_target_frame, textvariable=self.auto_content_folder_path).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        ttk.Button(self.auto_batch_target_frame, text="Browse", command=self._browse_auto_content_folder).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        note_box = ttk.LabelFrame(tab, text="Info", padding=10, style="Accent.TLabelframe")
        note_box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            (
                "Patch VisualBank bounds from related GR2 meshes. Batch mode patches one or more selected LSF files; "
                "Whole Folder mode scans every valid LSF under a folder."
            ),
        )

        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Checkbutton(actions, text="Keep edited LSX", variable=self.auto_keep_lsx).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(0, 16),
        )
        ttk.Checkbutton(actions, text="Backup original", variable=self.auto_backup_original).grid(
            row=0,
            column=2,
            sticky="e",
            padx=(0, 16),
        )
        self.auto_run_button = ttk.Button(
            actions,
            text="Patch",
            command=self._start_auto_bounds_run,
            style="Accent.TButton",
        )
        self.auto_run_button.grid(row=0, column=3, sticky="e")
        self.run_buttons.append(self.auto_run_button)

        self._build_spacer_row(tab, 4)
        self.auto_status_label = self._build_tab_footer(tab, 5)
        self._update_auto_bounds_mode()

    def _build_import_repair_tab(self, tab) -> None:
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)

        ttk.Label(tab, text="XML root").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(tab, textvariable=self.import_root_path).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(tab, text="Browse", command=self._browse_import_root).grid(row=0, column=2, sticky="ew")

        note_box = ttk.LabelFrame(tab, text="Info", padding=10, style="Accent.TLabelframe")
        note_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            (
                "Repair import settings XML files that point at absolute Data/ASSETS paths."
            ),
        )

        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Checkbutton(actions, text="Backup XML", variable=self.import_backup_original).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(0, 16),
        )
        self.import_run_button = ttk.Button(
            actions,
            text="Repair Imports",
            command=self._start_import_repair,
            style="Accent.TButton",
        )
        self.import_run_button.grid(row=0, column=2, sticky="e")
        self.run_buttons.append(self.import_run_button)

        self._build_spacer_row(tab, 3)
        self.import_status_label = self._build_tab_footer(tab, 4)

    def _build_project_backup_tab(self, tab) -> None:
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(10, weight=1)

        rename_heading = ttk.Label(tab, text="Rename Mod", style="AboutTitle.TLabel", foreground=self.accent_color)
        self.direct_accent_labels.append(rename_heading)
        rename_heading.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="w",
        )

        rename_note = ttk.LabelFrame(tab, text="Info", padding=10, style="Accent.TLabelframe")
        rename_note.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        rename_note.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            rename_note,
            (
                "Enter names with or without the trailing UUID. Existing UUIDs are preserved."
            ),
        )

        ttk.Label(tab, text="Old folder").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(tab, textvariable=self.rename_old_folder).grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Label(tab, text="New folder").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(tab, textvariable=self.rename_new_folder).grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        rename_actions = ttk.Frame(tab)
        rename_actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        rename_actions.columnconfigure(0, weight=1)
        self.project_rename_run_button = ttk.Button(
            rename_actions,
            text="Rename Mod",
            command=self._start_project_rename,
            style="Accent.TButton",
        )
        self.project_rename_run_button.grid(row=0, column=1, sticky="e")
        self.run_buttons.append(self.project_rename_run_button)

        ttk.Separator(tab, orient="horizontal").grid(
            row=5,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(14, 12),
        )

        backup_heading = ttk.Label(tab, text="Project Backup", style="AboutTitle.TLabel", foreground=self.accent_color)
        self.direct_accent_labels.append(backup_heading)
        backup_heading.grid(
            row=6,
            column=0,
            columnspan=3,
            sticky="w",
        )

        ttk.Label(tab, text="Backup destination").grid(
            row=8,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=(8, 0),
        )
        ttk.Entry(tab, textvariable=self.project_backup_path).grid(
            row=8,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=(8, 0),
        )
        ttk.Button(tab, text="Browse", command=self._browse_project_backup_destination).grid(
            row=8,
            column=2,
            sticky="ew",
            pady=(8, 0),
        )

        note_box = ttk.LabelFrame(tab, text="Info", padding=10, style="Accent.TLabelframe")
        note_box.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            (
                "Select Toolkit projects and copy their related Data folders to a backup location."
            ),
        )

        actions = ttk.Frame(tab)
        actions.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.project_backup_selection_text).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.project_backup_select_button = ttk.Button(
            actions,
            text="Select Projects",
            command=self._open_project_backup_picker,
        )
        self.project_backup_select_button.grid(row=0, column=1, sticky="e", padx=(0, 16))
        self.run_buttons.append(self.project_backup_select_button)
        self.project_backup_run_button = ttk.Button(
            actions,
            text="Back Up Projects",
            command=self._start_project_backup,
            style="Accent.TButton",
        )
        self.project_backup_run_button.grid(row=0, column=2, sticky="e")
        self.run_buttons.append(self.project_backup_run_button)

        self._build_spacer_row(tab, 10)
        self.project_backup_status_label = self._build_tab_footer(tab, 11)

    def _build_settings_tab(self, settings_tab) -> None:
        settings_tab.rowconfigure(6, weight=1)

        ttk.Label(settings_tab, text="Game folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(settings_tab, textvariable=self.game_folder_path).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        ttk.Button(settings_tab, text="Browse", command=self._browse_game_folder).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        ttk.Label(settings_tab, text="Divine.exe").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Entry(settings_tab, textvariable=self.divine_path).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=(10, 0),
        )
        ttk.Button(settings_tab, text="Browse", command=self._browse_divine).grid(
            row=1,
            column=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Checkbutton(
            settings_tab,
            text="Show intro on startup",
            variable=self.show_intro_on_startup,
            command=self._save_intro_preference,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 0))

        ttk.Checkbutton(
            settings_tab,
            text="Dark mode",
            variable=self.dark_mode,
            command=self._toggle_dark_mode,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        ttk.Label(settings_tab, text="Accent colour").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        accent_controls = ttk.Frame(settings_tab)
        accent_controls.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(10, 0))
        accent_controls.columnconfigure(2, weight=1)
        self.accent_swatch = tk.Frame(
            accent_controls,
            width=24,
            height=18,
            bg=self.accent_color,
            cursor="hand2",
            highlightbackground=self.accent_dark_color,
            highlightthickness=1,
        )
        self.accent_swatch.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.accent_swatch.grid_propagate(False)
        self.accent_swatch.bind("<Button-1>", lambda _event: self._choose_accent_color())
        LumiToolTip(self.accent_swatch, "Choose accent colour")
        ttk.Button(accent_controls, text="Reset", command=self._reset_accent_color).grid(row=0, column=1, sticky="w")

        settings_footer = ttk.Frame(settings_tab)
        settings_footer.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        settings_footer.columnconfigure(2, weight=1)

        ttk.Button(
            settings_footer,
            text="Open Settings Folder",
            command=self._open_settings_folder_clicked,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
        )
        self.delete_temp_files_button = ttk.Button(
            settings_footer,
            text="Delete Temp Files",
            command=self._delete_temp_files_clicked,
        )
        self.delete_temp_files_button.grid(
            row=0,
            column=1,
            sticky="w",
        )
        self.run_buttons.append(self.delete_temp_files_button)
        ttk.Button(
            settings_footer,
            text="Save Settings",
            command=self._save_settings_clicked,
            style="Accent.TButton",
        ).grid(
            row=0,
            column=3,
            sticky="e",
        )

        self._build_spacer_row(settings_tab, 6)

        about_box = ttk.LabelFrame(settings_tab, text="About", padding=10, style="Accent.TLabelframe")
        about_box.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        about_box.columnconfigure(0, weight=1)

        about_heading_row = ttk.Frame(about_box)
        about_heading_row.grid(row=0, column=0, sticky="w")
        about_heading = ttk.Label(
            about_heading_row,
            text="Developed by Luminiari, powered by coffee and bagels",
            style="AboutTitle.TLabel",
            foreground=self.accent_color,
        )
        self.direct_accent_labels.append(about_heading)
        about_heading.grid(row=0, column=0, sticky="w")
        period = ttk.Label(
            about_heading_row,
            text=".",
            style="AboutTitle.TLabel",
            foreground=self.accent_color,
        )
        self.direct_accent_labels.append(period)
        period.grid(row=0, column=1, sticky="w")
        period.bind("<Button-1>", lambda _event: self._experimental_entry_clicked())

        ttk.Label(about_box, text=f"Version number {APP_VERSION}", style="AboutVersion.TLabel").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(6, 0),
        )
        self._add_wrapping_label(
            about_box,
            (
                "Copyright © 2026 Luminiari. All rights reserved.\n"
                "Lumi's Toolkit Assistant is an unofficial fan project. It is not endorsed "
                "or approved by Larian Studios or Wizards of the Coast."
            ),
            row=2,
            pady=(6, 0),
        )

        link_row = ttk.Frame(about_box)
        link_row.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        link_row.columnconfigure(0, weight=1)
        link_row.columnconfigure(len(ABOUT_LINKS) + 1, weight=1)
        for index, (label, url, icon_name) in enumerate(ABOUT_LINKS):
            icon = self._load_about_icon(icon_name)
            if icon is None:
                link = ttk.Label(link_row, text=label, cursor="hand2", padding=(4, 2))
            else:
                link = ttk.Label(link_row, image=icon, cursor="hand2", padding=2)
                self.about_link_icon_labels.append((link, icon_name))

            link.grid(row=0, column=index + 1, padx=5)
            link.bind("<Button-1>", lambda _event, target=url: self._open_about_link(target))
            LumiToolTip(link, label)

        self.settings_status_label = self._build_tab_footer(settings_tab, 8)

    def _build_experimental_tab(self, experimental_tab) -> None:
        experimental_tab.columnconfigure(0, weight=1)
        experimental_tab.rowconfigure(2, weight=1)

        self.pak_source_path = tk.StringVar(master=self.root)
        self.pak_output_path = tk.StringVar(master=self.root)

        heading = ttk.Label(
            experimental_tab,
            text="Experimental Features",
            style="AboutTitle.TLabel",
            foreground=self.accent_color,
        )
        self.direct_accent_labels.append(heading)
        heading.grid(row=0, column=0, sticky="w")

        finalisation_box = ttk.LabelFrame(
            experimental_tab,
            text="PAK Finalisation",
            padding=10,
            style="Accent.TLabelframe",
        )
        finalisation_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        finalisation_box.columnconfigure(1, weight=1)

        ttk.Label(finalisation_box, text="Source package").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(finalisation_box, textvariable=self.pak_source_path).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            finalisation_box,
            text="Browse",
            command=self._browse_pak_source,
        ).grid(row=0, column=2, sticky="ew")

        ttk.Label(finalisation_box, text="Output package").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0)
        )
        ttk.Entry(finalisation_box, textvariable=self.pak_output_path).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=(10, 0),
        )
        ttk.Button(
            finalisation_box,
            text="Browse",
            command=self._browse_pak_output,
        ).grid(row=1, column=2, sticky="ew", pady=(10, 0))

        note_box = ttk.LabelFrame(
            finalisation_box,
            text="Important",
            padding=10,
            style="Warning.TLabelframe",
        )
        note_box.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(12, 0),
        )
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            (
                "Creates a separate V16 package using an experimental finalisation "
                "pass. Keep the original source package in a safe place."
            ),
        )

        actions = ttk.Frame(finalisation_box)
        actions.grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(12, 0),
        )
        actions.columnconfigure(0, weight=1)
        self.pak_finalise_run_button = ttk.Button(
            actions,
            text="Finalise Copy",
            command=self._start_pak_finalisation,
            style="Accent.TButton",
        )
        self.pak_finalise_run_button.grid(row=0, column=1, sticky="e")
        self.run_buttons.append(self.pak_finalise_run_button)

        self._build_spacer_row(experimental_tab, 2, columnspan=1)
        self.experimental_status_label = self._build_tab_footer(
            experimental_tab, 3, columnspan=1
        )

    def _restore_experimental_features(self) -> None:
        experimental_setting = self.settings.get(
            EXPERIMENTAL_FEATURES_UNLOCKED_KEY
        )
        if experimental_setting == "1":
            self._add_experimental_tab()
            return
        if experimental_setting is not None:
            return

        self.settings[EXPERIMENTAL_FEATURES_UNLOCKED_KEY] = "0"
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.settings.pop(EXPERIMENTAL_FEATURES_UNLOCKED_KEY, None)
            messagebox.showwarning(
                APP_TITLE,
                f"Could not initialise the experimental feature setting: {exc}",
                parent=self.root,
            )

    def _experimental_entry_clicked(self) -> None:
        if self.experimental_tab is not None:
            confirmed = messagebox.askyesno(
                "Experimental Features",
                (
                    "Experimental features are currently enabled. Do you want to "
                    "disable them the next time the app starts?"
                ),
                parent=self.root,
            )
            if not confirmed:
                return

            previous_value = self.settings.get(
                EXPERIMENTAL_FEATURES_UNLOCKED_KEY
            )
            self.settings[EXPERIMENTAL_FEATURES_UNLOCKED_KEY] = "0"
            try:
                save_settings(self.settings)
            except OSError as exc:
                if previous_value is None:
                    self.settings.pop(EXPERIMENTAL_FEATURES_UNLOCKED_KEY, None)
                else:
                    self.settings[
                        EXPERIMENTAL_FEATURES_UNLOCKED_KEY
                    ] = previous_value
                messagebox.showwarning(
                    APP_TITLE,
                    f"Could not save the experimental feature setting: {exc}",
                    parent=self.root,
                )
                return

            self._set_status(
                self.settings_status_label,
                "Experimental features will be disabled after restart",
            )
            return

        confirmed = messagebox.askyesno(
            "Experimental Features",
            (
                "Hey, you clicked this. Are you sure you want to unlock "
                "experimental features?"
            ),
            parent=self.root,
        )
        if not confirmed:
            return

        self.settings[EXPERIMENTAL_FEATURES_UNLOCKED_KEY] = "1"
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(
                APP_TITLE,
                (
                    "Experimental features were unlocked for this session, but "
                    f"the setting could not be saved: {exc}"
                ),
                parent=self.root,
            )
        self._add_experimental_tab(select=True)
        self._set_status(
            self.settings_status_label, "Experimental features unlocked"
        )

    def _browse_mesh_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose mesh file",
            filetypes=(("Mesh files", "*.gr2 *.dae"), ("GR2 files", "*.gr2"), ("DAE files", "*.dae"), ("All files", "*.*")),
        )
        if path:
            self.mesh_file_path.set(path)

    def _browse_pak_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose source package",
            filetypes=(("BG3 packages", "*.pak"), ("All files", "*.*")),
        )
        if not path:
            return
        self.pak_source_path.set(path)
        self.pak_output_path.set(str(default_finalised_pak_path(path)))

    def _browse_pak_output(self) -> None:
        source_text = self.pak_source_path.get().strip()
        suggested = (
            default_finalised_pak_path(source_text).name
            if source_text
            else "finalised.pak"
        )
        path = filedialog.asksaveasfilename(
            title="Choose output package",
            defaultextension=".pak",
            initialfile=suggested,
            filetypes=(("BG3 packages", "*.pak"), ("All files", "*.*")),
        )
        if path:
            self.pak_output_path.set(path)

    def _browse_auto_selected_lsfs(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose LSF files",
            filetypes=(("LSF files", "*.lsf"), ("All files", "*.*")),
        )
        if not paths:
            return

        selected_paths: list[str] = []
        seen: set[str] = set()
        for path in paths:
            key = str(Path(path).resolve()).lower()
            if key in seen:
                continue

            seen.add(key)
            selected_paths.append(path)

        self.auto_selected_lsf_paths = selected_paths
        self._update_auto_selected_lsf_summary()

    def _browse_auto_content_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose Content folder")
        if path:
            self.auto_content_folder_path.set(path)

    def _browse_patch_single_lsf(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose LSF file",
            filetypes=(("LSF files", "*.lsf"), ("All files", "*.*")),
        )
        if path:
            self.patch_single_lsf_path.set(path)

    def _browse_patch_lsf_root(self) -> None:
        path = filedialog.askdirectory(title="Choose Content folder")
        if path:
            self.patch_batch_root_path.set(path)

    def _browse_import_root(self) -> None:
        path = filedialog.askdirectory(title="Choose import settings XML root")
        if path:
            self.import_root_path.set(path)

    def _browse_divine(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose Divine.exe",
            filetypes=(("Divine.exe", "Divine.exe"), ("Executable files", "*.exe"), ("All files", "*.*")),
        )
        if path:
            self.divine_path.set(path)
            self._save_current_settings()

    def _browse_game_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose Baldurs Gate 3 game folder")
        if path:
            game_folder_error = get_game_folder_error(path)
            if game_folder_error:
                messagebox.showwarning(APP_TITLE, game_folder_error)
                return

            self.game_folder_path.set(path)
            self._save_current_settings()

    def _browse_project_backup_destination(self) -> None:
        path = filedialog.askdirectory(title="Choose project backup destination")
        if path:
            self.project_backup_path.set(path)
            self._save_setting_value("project_backup_path", path)

    def _update_project_backup_selection_summary(self) -> None:
        count = len(self.project_backup_selected_projects)
        if count == 0:
            self.project_backup_selection_text.set("No projects selected")
        elif count == 1:
            self.project_backup_selection_text.set("1 project selected")
        else:
            self.project_backup_selection_text.set(f"{count} projects selected")

    def _log_no_project_selection(self) -> None:
        self._activate_project_backup_output()
        self._append_output("No projects selected.\n")
        self._set_status(
            self.project_backup_status_label, "No projects selected"
        )

    def _log_project_backup_selection(self, project_names: list[str]) -> None:
        self._activate_project_backup_output()
        heading = "Selected project:" if len(project_names) == 1 else "Selected projects:"
        self._append_output(f"{heading}\n")
        for project_name in project_names:
            self._append_output(f"- {project_name}\n")
        self._append_output("\n")

    def _save_current_settings(self) -> bool:
        divine = self.divine_path.get().strip()
        game_folder = self.game_folder_path.get().strip()
        previous_game_folder = self.settings.get("game_folder_path", "")
        if divine and not Path(divine).is_file():
            messagebox.showwarning(APP_TITLE, "Choose a valid Divine.exe path.")
            return False
        if game_folder:
            game_folder_error = get_game_folder_error(game_folder)
        else:
            game_folder_error = None
        if game_folder_error:
            messagebox.showwarning(APP_TITLE, game_folder_error)
            return False

        self.settings["divine_path"] = divine
        self.settings["game_folder_path"] = game_folder
        self.settings[UI_THEME_SETTING_KEY] = self.ui_theme_name
        self.settings[ACCENT_COLOR_SETTING_KEY] = self.accent_color
        if game_folder != previous_game_folder:
            self.project_backup_selected_projects = []
            self._update_project_backup_selection_summary()
        self._set_intro_preference_in_settings()
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not save settings: {exc}")
            return False

        return True

    def _toggle_dark_mode(self) -> None:
        self.ui_theme_name = UI_THEME_DARK if self.dark_mode.get() else UI_THEME_LIGHT
        self.settings[UI_THEME_SETTING_KEY] = self.ui_theme_name
        if self.pending_theme_after is not None:
            self.root.after_cancel(self.pending_theme_after)
        self.pending_theme_after = self.root.after_idle(self._apply_and_save_ui_theme)

    def _save_theme_preference(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not save theme preference: {exc}")

    def _save_settings_clicked(self) -> None:
        if self._save_current_settings():
            self._set_status(self.settings_status_label, "Settings saved")

    def _open_settings_folder_clicked(self) -> None:
        settings_folder = SETTINGS_PATH.parent
        try:
            settings_folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(settings_folder))
            else:
                webbrowser.open(settings_folder.as_uri())
            self._set_status(self.settings_status_label, "Settings folder opened")
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, f"Could not open settings folder: {exc}")

    def _delete_temp_files_clicked(self) -> None:
        if self._is_busy():
            return

        confirmed = messagebox.askyesno(
            APP_TITLE,
            (
                "Delete all temporary files now?\n\n"
                "This is a destructive action. Only do this if you are sure you no longer need "
                f"anything held in:\n{TEMPORARY_FILES_ROOT}"
            ),
        )
        if not confirmed:
            return

        try:
            deleted = delete_temp_folder_contents(TEMPORARY_FILES_ROOT)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not delete temporary files: {exc}")
            return

        messagebox.showinfo(APP_TITLE, f"Deleted {deleted} temporary item(s).")
        self._set_status(
            self.settings_status_label,
            f"Deleted {deleted} temporary item(s)",
        )

    def _set_intro_preference_in_settings(self) -> None:
        self.settings[INTRO_DISMISSED_KEY] = "0" if self.show_intro_on_startup.get() else "1"

    def _save_intro_preference(self) -> None:
        self._set_intro_preference_in_settings()
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not save intro preference: {exc}")

    def _save_setting_value(self, key: str, value: str) -> None:
        self.settings[key] = value
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not save settings: {exc}")

    def _open_about_link(self, url: str) -> None:
        try:
            webbrowser.open_new_tab(url)
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, f"Could not open link: {exc}")

    def _load_about_icon(self, filename: str):
        icon = self._load_tinted_icon(filename)
        if icon is None:
            return None
        self.about_link_icons.append(icon)
        return icon

    def _get_divine_path_for_run(self) -> str:
        divine = self.divine_path.get().strip()
        if divine:
            if not Path(divine).is_file():
                raise FileNotFoundError("Choose a valid Divine.exe path in Settings.")
            return divine

        try:
            divine = str(resolve_divine())
        except FileNotFoundError as exc:
            raise FileNotFoundError("Choose Divine.exe in Settings before patching.") from exc

        self.divine_path.set(divine)
        self._save_current_settings()
        return divine

    def _is_busy(self) -> bool:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(APP_TITLE, "A run is already in progress.")
            return True

        return False

    def _activate_patch_lsf_output(self) -> None:
        self.active_output_name = "LSF Patcher"
        self.active_status_label = self.patch_status_label

    def _activate_mesh_bounds_output(self) -> None:
        self.active_output_name = "Bounds Calculator"
        self.active_status_label = self.mesh_bounds_status_label

    def _activate_auto_bounds_output(self) -> None:
        self.active_output_name = "One-Click Patcher"
        self.active_status_label = self.auto_status_label

    def _activate_import_output(self) -> None:
        self.active_output_name = "Import Repair"
        self.active_status_label = self.import_status_label

    def _activate_project_backup_output(self) -> None:
        self.active_output_name = "Project Tools"
        self.active_status_label = self.project_backup_status_label

    def _activate_experimental_output(self) -> None:
        self.active_output_name = "PAK Finalisation"
        self.active_status_label = self.experimental_status_label

    def _update_auto_selected_lsf_summary(self) -> None:
        count = len(self.auto_selected_lsf_paths)
        if count == 0:
            self.auto_selected_lsf_summary.set("No files selected")
        elif count == 1:
            self.auto_selected_lsf_summary.set("1 file selected")
        else:
            self.auto_selected_lsf_summary.set(f"{count} files selected")

        listbox = getattr(self, "auto_selected_lsf_listbox", None)
        if listbox is not None:
            listbox.delete(0, "end")
            for path in self.auto_selected_lsf_paths:
                listbox.insert("end", Path(path).name)

    def _update_auto_bounds_mode(self) -> None:
        mode = self.auto_bounds_mode.get()
        if mode == "whole_folder":
            self.auto_selected_target_frame.grid_remove()
            self.auto_batch_target_frame.grid()
        else:
            self.auto_batch_target_frame.grid_remove()
            self.auto_selected_target_frame.grid()

    def _update_patch_lsf_mode(self) -> None:
        if self.patch_lsf_mode.get() == "uuid":
            self.patch_single_target_frame.grid_remove()
            self.patch_batch_target_frame.grid()
        else:
            self.patch_batch_target_frame.grid_remove()
            self.patch_single_target_frame.grid()

    def _start_mesh_bounds(self) -> None:
        if self._is_busy():
            return

        self._activate_mesh_bounds_output()
        mesh_file = self.mesh_file_path.get().strip()

        if not mesh_file or not Path(mesh_file).is_file():
            messagebox.showwarning(APP_TITLE, "Choose a valid .gr2 or .dae mesh file.")
            return
        if Path(mesh_file).suffix.lower() not in {".gr2", ".dae"}:
            messagebox.showwarning(APP_TITLE, "The selected file must be a .gr2 or .dae file.")
            return

        divine = ""
        if Path(mesh_file).suffix.lower() == ".gr2":
            try:
                divine = self._get_divine_path_for_run()
            except FileNotFoundError as exc:
                messagebox.showwarning(APP_TITLE, str(exc))
                return

        self.latest_mesh_bounds_xml = ""
        self._clear_output()
        self._set_running(True)

        self.worker = threading.Thread(
            target=self._run_mesh_bounds,
            args=(
                mesh_file,
                divine,
            ),
            daemon=True,
        )
        self.worker.start()

    def _start_pak_finalisation(self) -> None:
        if self._is_busy():
            return

        self._activate_experimental_output()
        source_text = self.pak_source_path.get().strip()
        output_text = self.pak_output_path.get().strip()
        source = Path(source_text) if source_text else None
        destination = Path(output_text) if output_text else None
        if source is None or not source.is_file():
            messagebox.showwarning(APP_TITLE, "Choose a valid source .pak file.")
            return
        if source.suffix.lower() != ".pak":
            messagebox.showwarning(APP_TITLE, "The source must be a .pak file.")
            return
        if destination is None:
            destination = default_finalised_pak_path(source)
            self.pak_output_path.set(str(destination))
        if destination.suffix.lower() != ".pak":
            messagebox.showwarning(
                APP_TITLE, "The output package must use the .pak extension."
            )
            return
        if os.path.normcase(str(source.resolve())) == os.path.normcase(
            str(destination.resolve())
        ):
            messagebox.showwarning(
                APP_TITLE, "The output package cannot overwrite the source package."
            )
            return

        overwrite = destination.exists()
        overwrite_note = (
            "\n\nThe existing output package will be replaced."
            if overwrite
            else ""
        )
        confirmed = messagebox.askyesno(
            "Experimental PAK Finalisation",
            (
                "Create the finalised package copy now?\n\n"
                "This experimental pass may affect compatibility. Retain the "
                f"original source package.{overwrite_note}"
            ),
            parent=self.root,
        )
        if not confirmed:
            return

        self._clear_output()
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._run_pak_finalisation,
            args=(str(source), str(destination), overwrite),
            daemon=True,
        )
        self.worker.start()

    def _start_auto_bounds_run(self) -> None:
        if self._is_busy():
            return

        self._activate_auto_bounds_output()
        mode = self.auto_bounds_mode.get()
        game_folder = self.game_folder_path.get().strip()

        if not game_folder:
            messagebox.showwarning(APP_TITLE, "Choose the Game folder in Settings first.")
            return
        game_folder_error = get_game_folder_error(game_folder)
        if game_folder_error:
            messagebox.showwarning(APP_TITLE, game_folder_error)
            return
        if not (Path(game_folder) / "Data").is_dir():
            messagebox.showwarning(APP_TITLE, "Could not find a Data folder inside the saved game folder.")
            return
        try:
            divine = self._get_divine_path_for_run()
        except FileNotFoundError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return

        if mode != "whole_folder":
            selected_files = [path for path in self.auto_selected_lsf_paths if path.strip()]
            if not selected_files:
                messagebox.showwarning(APP_TITLE, "Select one or more .lsf files.")
                return
            invalid_file = next((path for path in selected_files if not Path(path).is_file()), None)
            if invalid_file is not None:
                messagebox.showwarning(APP_TITLE, f"Selected file no longer exists: {invalid_file}")
                return
            invalid_lsf = next((path for path in selected_files if Path(path).suffix.lower() != ".lsf"), None)
            if invalid_lsf is not None:
                messagebox.showwarning(APP_TITLE, f"Selected file must be an .lsf file: {invalid_lsf}")
                return
            confirmed = messagebox.askyesno(
                APP_TITLE,
                f"Patch {len(selected_files)} selected LSF file(s) now?",
            )
            if not confirmed:
                return

            self._clear_output()
            self._set_running(True)
            self.worker = threading.Thread(
                target=self._run_auto_bounds_selected_patcher,
                args=(
                    selected_files,
                    game_folder,
                    divine,
                    self.auto_keep_lsx.get(),
                    self.auto_backup_original.get(),
                ),
                daemon=True,
            )
            self.worker.start()
            return

        if mode == "whole_folder":
            content_folder = self.auto_content_folder_path.get().strip()
            if not content_folder or not Path(content_folder).is_dir():
                messagebox.showwarning(APP_TITLE, "Choose a valid Content folder.")
                return
            confirmed = messagebox.askyesno(
                APP_TITLE,
                "Patch every valid VisualBank LSF in this Content folder now?",
            )
            if not confirmed:
                return

            self._clear_output()
            self._set_running(True)
            self.worker = threading.Thread(
                target=self._run_auto_bounds_batch_patcher,
                args=(
                    content_folder,
                    game_folder,
                    divine,
                    self.auto_keep_lsx.get(),
                    self.auto_backup_original.get(),
                ),
                daemon=True,
            )
            self.worker.start()
            return

    def _start_patch_lsf_run(self) -> None:
        if self._is_busy():
            return

        self._activate_patch_lsf_output()
        mode = self.patch_lsf_mode.get()
        bounds = self.patch_bounds_text.get("1.0", "end").strip()

        if mode == "uuid":
            root_path = self.patch_batch_root_path.get().strip()
            uuid_values = parse_uuid_values(self.patch_uuid_text.get("1.0", "end"))

            if not root_path or not Path(root_path).is_dir():
                messagebox.showwarning(APP_TITLE, "Choose a valid Content folder.")
                return
            if not bounds:
                messagebox.showwarning(APP_TITLE, "Paste the bounds XML first.")
                return
            patch_all_visualbanks = False
            if not uuid_values:
                patch_all_visualbanks = messagebox.askyesno(
                    APP_TITLE,
                    (
                        "You have not specified any UUIDs- would you like to apply the bounds "
                        "to every valid VisualBank entry in this folder?"
                    ),
                )
                if not patch_all_visualbanks:
                    return
            confirm_message = (
                "Patch every valid VisualBank LSF now?"
                if patch_all_visualbanks
                else "Patch matched LSF files now?"
            )
            confirmed = messagebox.askyesno(APP_TITLE, confirm_message)
            if not confirmed:
                return

            try:
                divine = self._get_divine_path_for_run()
            except FileNotFoundError as exc:
                messagebox.showwarning(APP_TITLE, str(exc))
                return

            self._clear_output()
            self._set_running(True)
            if patch_all_visualbanks:
                self.worker = threading.Thread(
                    target=self._run_visualbank_batch_patcher,
                    args=(
                        root_path,
                        bounds,
                        divine,
                        self.patch_lsf_keep_lsx.get(),
                        self.patch_lsf_backup_original.get(),
                    ),
                    daemon=True,
                )
                self.worker.start()
                return

            self.worker = threading.Thread(
                target=self._run_batch_patcher,
                args=(
                    root_path,
                    uuid_values,
                    bounds,
                    divine,
                    self.patch_lsf_keep_lsx.get(),
                    self.patch_lsf_backup_original.get(),
                ),
                daemon=True,
            )
            self.worker.start()
            return

        lsf_file = self.patch_single_lsf_path.get().strip()
        if not lsf_file or not Path(lsf_file).is_file():
            messagebox.showwarning(APP_TITLE, "Choose a valid .lsf file.")
            return
        if Path(lsf_file).suffix.lower() != ".lsf":
            messagebox.showwarning(APP_TITLE, "The selected file must be an .lsf file.")
            return
        if not bounds:
            messagebox.showwarning(APP_TITLE, "Paste the bounds XML first.")
            return

        try:
            divine = self._get_divine_path_for_run()
        except FileNotFoundError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return

        self._clear_output()
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._run_single_patcher,
            args=(
                lsf_file,
                bounds,
                divine,
                self.patch_lsf_keep_lsx.get(),
                self.patch_lsf_backup_original.get(),
            ),
            daemon=True,
        )
        self.worker.start()

    def _start_import_repair(self) -> None:
        if self._is_busy():
            return

        self._activate_import_output()
        root_path = self.import_root_path.get().strip()

        if not root_path or not Path(root_path).is_dir():
            messagebox.showwarning(APP_TITLE, "Choose a valid XML root folder.")
            return
        confirmed = messagebox.askyesno(APP_TITLE, "Repair import settings XML now?")
        if not confirmed:
            return

        self._clear_output()
        self._set_running(True)

        self.worker = threading.Thread(
            target=self._run_import_repair,
            args=(
                root_path,
                self.import_backup_original.get(),
            ),
            daemon=True,
        )
        self.worker.start()

    def _start_project_rename(self) -> None:
        if self._is_busy():
            return

        self._activate_project_backup_output()
        game_folder = self.game_folder_path.get().strip()
        old_folder = self.rename_old_folder.get().strip()
        new_folder = self.rename_new_folder.get().strip()

        if not game_folder:
            messagebox.showwarning(APP_TITLE, "Choose the Game folder in Settings first.")
            return
        game_folder_error = get_game_folder_error(game_folder)
        if game_folder_error:
            messagebox.showwarning(APP_TITLE, game_folder_error)
            return
        if not (Path(game_folder) / "Data").is_dir():
            messagebox.showwarning(APP_TITLE, "Could not find a Data folder inside the saved game folder.")
            return
        if not old_folder:
            messagebox.showwarning(APP_TITLE, "Enter the old mod folder name.")
            return
        if not new_folder:
            messagebox.showwarning(APP_TITLE, "Enter the new mod folder name.")
            return
        confirmed = messagebox.askyesno(
            APP_TITLE,
            "Rename this Toolkit mod now?\n\nA temporary backup will be kept for one month.",
        )
        if not confirmed:
            return

        self._clear_output()
        self._set_running(True)

        self.worker = threading.Thread(
            target=self._run_project_rename,
            args=(
                game_folder,
                old_folder,
                new_folder,
            ),
            daemon=True,
        )
        self.worker.start()

    def _start_project_backup(self) -> None:
        if self._is_busy():
            return

        self._activate_project_backup_output()
        game_folder = self.game_folder_path.get().strip()
        backup_root = self.project_backup_path.get().strip()
        selected_projects = list(self.project_backup_selected_projects)

        if not selected_projects:
            self._clear_output()
            self._log_no_project_selection()
            return

        if not game_folder:
            messagebox.showwarning(APP_TITLE, "Choose the Game folder in Settings first.")
            return
        game_folder_error = get_game_folder_error(game_folder)
        if game_folder_error:
            messagebox.showwarning(APP_TITLE, game_folder_error)
            return
        if not (Path(game_folder) / "Data").is_dir():
            messagebox.showwarning(APP_TITLE, "Could not find a Data folder inside the saved game folder.")
            return
        if not backup_root:
            messagebox.showwarning(APP_TITLE, "Choose a backup destination folder.")
            return
        backup_path = Path(backup_root)
        if backup_path.exists() and not backup_path.is_dir():
            messagebox.showwarning(APP_TITLE, "Backup destination must be a folder.")
            return
        confirmed = messagebox.askyesno(APP_TITLE, "Back up selected Toolkit projects now?")
        if not confirmed:
            return

        self._save_setting_value("project_backup_path", backup_root)
        self._clear_output()
        self._set_running(True)

        self.worker = threading.Thread(
            target=self._run_project_backup,
            args=(
                game_folder,
                backup_root,
                selected_projects,
            ),
            daemon=True,
        )
        self.worker.start()

    def _run_mesh_bounds(
        self,
        mesh_file: str,
        divine: str,
    ) -> None:
        try:
            bounds = calculate_mesh_bounds(
                mesh_file,
                divine or None,
                progress=lambda message: self.messages.put(("log", message)),
            )
            bounds_xml = format_mesh_bounds_xml(bounds)
            self.messages.put(("log", f"Vertex count: {bounds.vertex_count}\n"))
            self.messages.put(("mesh_bounds", bounds_xml))
            self.messages.put(("done", 1))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_pak_finalisation(
        self,
        source: str,
        destination: str,
        overwrite: bool,
    ) -> None:
        try:
            result = finalise_pak(
                source,
                destination,
                overwrite=overwrite,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(
                ("log", f"Processed internal path: {result.processed_path}\n")
            )
            self.messages.put(("done", 1))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_single_patcher(
        self,
        lsf_file: str,
        bounds: str,
        divine: str,
        keep_lsx: bool,
        backup_original: bool,
    ) -> None:
        try:
            updated = patch_lsf_file(
                lsf_file,
                bounds,
                divine or None,
                keep_lsx=keep_lsx,
                backup_original=backup_original,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", updated))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_auto_bounds_selected_patcher(
        self,
        lsf_files: list[str],
        game_folder: str,
        divine: str,
        keep_lsx: bool,
        backup_original: bool,
    ) -> None:
        updated = 0
        failed = 0
        total = len(lsf_files)
        self.messages.put(("log", f"Selected file count: {total}\n"))
        for index, lsf_file in enumerate(lsf_files, start=1):
            self.messages.put(("log", f"\nSelected file {index}/{total}: {lsf_file}\n"))
            try:
                updated += patch_lsf_from_related_mesh(
                    lsf_file,
                    game_folder,
                    divine or None,
                    keep_lsx=keep_lsx,
                    backup_original=backup_original,
                    progress=lambda message: self.messages.put(("log", message)),
                )
            except Exception as exc:
                failed += 1
                self.messages.put(("log", f"Warning: Failed '{lsf_file}': {exc}\n"))

        self.messages.put(("log", f"\nDone. Updated {updated} file(s). Failed {failed} file(s).\n"))
        if updated == 0 and failed:
            self.messages.put(("error", f"Failed to patch {failed} selected file(s). See log for details."))
        else:
            self.messages.put(("done", updated))

    def _run_auto_bounds_batch_patcher(
        self,
        content_folder: str,
        game_folder: str,
        divine: str,
        keep_lsx: bool,
        backup_original: bool,
    ) -> None:
        try:
            updated = patch_visualbank_lsf_files_from_related_mesh(
                content_folder,
                game_folder,
                divine or None,
                keep_lsx=keep_lsx,
                backup_original=backup_original,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", updated))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_project_rename(
        self,
        game_folder: str,
        old_folder: str,
        new_folder: str,
    ) -> None:
        try:
            changed = rename_toolkit_mod_project(
                game_folder,
                old_folder,
                new_folder,
                temporary_backup_root=TEMPORARY_RENAME_BACKUP_ROOT,
                temporary_backup_retention_days=TEMPORARY_RENAME_BACKUP_RETENTION_DAYS,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", changed))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_project_backup(
        self,
        game_folder: str,
        backup_root: str,
        selected_projects: list[str],
    ) -> None:
        try:
            backed_up = backup_toolkit_projects(
                game_folder,
                backup_root,
                project_names=selected_projects,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", backed_up))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_batch_patcher(
        self,
        root_path: str,
        uuid_values: list[str],
        bounds: str,
        divine: str,
        keep_lsx: bool,
        backup_original: bool,
    ) -> None:
        try:
            updated = patch_lsf_files_by_uuid(
                root_path,
                uuid_values,
                bounds,
                divine or None,
                keep_lsx=keep_lsx,
                backup_original=backup_original,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", updated))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_visualbank_batch_patcher(
        self,
        root_path: str,
        bounds: str,
        divine: str,
        keep_lsx: bool,
        backup_original: bool,
    ) -> None:
        try:
            updated = patch_all_visualbank_lsf_files(
                root_path,
                bounds,
                divine or None,
                keep_lsx=keep_lsx,
                backup_original=backup_original,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", updated))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _run_import_repair(
        self,
        root_path: str,
        backup_original: bool,
    ) -> None:
        try:
            repaired = repair_import_settings_sources(
                root_path,
                backup_original=backup_original,
                progress=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", repaired))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    self._append_output(str(value))
                elif kind == "mesh_bounds":
                    self.latest_mesh_bounds_xml = str(value)
                    self._append_output(f"\nGenerated bounds XML:\n{value}\n")
                elif kind == "done":
                    self._set_running(False)
                    self._append_output("\nComplete.\n", "complete")
                    self._set_status(self._current_status_label(), "Complete")
                elif kind == "error":
                    self._append_output(f"Error: {value}\n", "error")
                    self._set_running(False)
                    self._set_status(self._current_status_label(), "Failed")
        except queue.Empty:
            pass

        self.root.after(100, self._poll_messages)

    def _append_output(self, text: str, tag: str | None = None) -> None:
        self._ensure_console_window()
        output = self.console_output_text
        output.configure(state="normal")
        if tag is None:
            output.insert("end", text)
        else:
            output.insert("end", text, tag)
        output.see("end")
        output.configure(state="disabled")

    def _clear_output(self) -> None:
        self._start_console_section()

    def _set_running(self, running: bool) -> None:
        for button in self.run_buttons:
            button.configure(state="disabled" if running else "normal")
        if running:
            self._set_status(
                self._current_status_label(),
                "Running...",
                clear_after_ms=None,
            )

    def _current_status_label(self):
        return self.active_status_label

    def _copy_mesh_bounds(self) -> None:
        self._activate_mesh_bounds_output()
        if not self.latest_mesh_bounds_xml:
            messagebox.showwarning(APP_TITLE, "Generate bounds first.")
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(self.latest_mesh_bounds_xml)
        self.root.update()
        self._set_status(self._current_status_label(), "Copied bounds XML")

    def _on_close(self) -> None:
        self.root.destroy()
