"""Tkinter user interface for Toolkit Assistant."""

from __future__ import annotations

import os
from pathlib import Path
import queue
import sys
import threading
import webbrowser

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
    ACCENT_DARK_COLOR,
    ACCENT_LIGHT_COLOR,
    APP_HEADING,
    APP_ICON_PATH,
    APP_TITLE,
    APP_VERSION,
    CONSOLE_ICON_PATH,
    INTRO_DISMISSED_KEY,
    LSLIB_RELEASES_URL,
    RESOURCE_DIR,
    SETTINGS_PATH,
    TEMPORARY_FILES_ROOT,
    TEMPORARY_RENAME_BACKUP_RETENTION_DAYS,
    TEMPORARY_RENAME_BACKUP_ROOT,
    TOOLKIT_ASSISTANT_WIKI_URL,
)
from .divine import find_default_divine, resolve_divine
from .import_repair import repair_import_settings_sources
from .mesh_bounds import calculate_mesh_bounds, format_mesh_bounds_xml
from .paths import get_game_folder_error
from .project_tools import backup_toolkit_projects, find_toolkit_project_names, rename_toolkit_mod_project
from .settings import load_settings, save_settings
from .temp_files import delete_temp_folder_contents


tk = None
filedialog = None
messagebox = None
ttk = None


def load_tk() -> None:
    # Lazy import keeps module loading boring when tests only need the helpers.
    global tk, filedialog, messagebox, ttk
    if tk is not None:
        return

    tcl_dir = RESOURCE_DIR / "lib" / "tcl"
    tk_dir = RESOURCE_DIR / "lib" / "tk"
    if tcl_dir.is_dir():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
    if tk_dir.is_dir():
        os.environ.setdefault("TK_LIBRARY", str(tk_dir))

    import tkinter as tk_module
    from tkinter import filedialog as filedialog_module
    from tkinter import messagebox as messagebox_module
    from tkinter import ttk as ttk_module

    tk = tk_module
    filedialog = filedialog_module
    messagebox = messagebox_module
    ttk = ttk_module

def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        # Stop whining and do the thing.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ToolkitAssistant.ToolkitAssistant")
    except Exception:
        pass

class ToolTip:
    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def show(self, _event=None) -> None:
        if self.window is not None or not self.text:
            return

        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(self.window, text=self.text, padding=(6, 3), relief="solid", borderwidth=1)
        label.pack()

    def hide(self, _event=None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None

class ToolkitAssistantApp:
    def __init__(self) -> None:
        set_windows_app_user_model_id()
        load_tk()
        self.root = tk.Tk()

        self.root.title(APP_TITLE)
        self._set_window_icon()
        self.root.geometry("760x560")
        self.root.minsize(760, 560)
        self._configure_styles()

        self.settings = load_settings()
        self.mesh_file_path = tk.StringVar(master=self.root)
        self.auto_bounds_mode = tk.StringVar(master=self.root, value="batch")
        self.auto_selected_lsf_summary = tk.StringVar(master=self.root, value="No files selected")
        self.auto_selected_lsf_paths: list[str] = []
        self.auto_content_folder_path = tk.StringVar(master=self.root)
        self.patch_lsf_mode = tk.StringVar(master=self.root, value="single")
        self.patch_single_lsf_path = tk.StringVar(master=self.root)
        self.patch_batch_root_path = tk.StringVar(master=self.root)
        self.divine_path = tk.StringVar(
            master=self.root,
            value=self.settings.get("divine_path") or find_default_divine(),
        )
        self.game_folder_path = tk.StringVar(
            master=self.root,
            value=self.settings.get("game_folder_path", ""),
        )
        self.auto_keep_lsx = tk.BooleanVar(master=self.root, value=True)
        self.auto_backup_original = tk.BooleanVar(master=self.root, value=True)
        self.patch_lsf_keep_lsx = tk.BooleanVar(master=self.root, value=True)
        self.patch_lsf_backup_original = tk.BooleanVar(master=self.root, value=True)
        self.import_root_path = tk.StringVar(master=self.root)
        self.import_backup_original = tk.BooleanVar(master=self.root, value=True)
        self.rename_old_folder = tk.StringVar(master=self.root)
        self.rename_new_folder = tk.StringVar(master=self.root)
        self.project_backup_path = tk.StringVar(
            master=self.root,
            value=self.settings.get("project_backup_path", ""),
        )
        self.project_backup_selection_text = tk.StringVar(master=self.root, value="No projects selected")
        self.project_backup_selected_projects: list[str] = []
        self.project_picker_window = None
        self.show_intro_on_startup = tk.BooleanVar(
            master=self.root,
            value=self.settings.get(INTRO_DISMISSED_KEY) != "1",
        )

        self.messages: queue.Queue[tuple[str, str | int]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.run_buttons: list[object] = []
        self.active_output_name = ""
        self.active_status_label = None
        self.about_link_icons: list[object] = []
        self.console_icon = None
        self.console_output_text = None
        self.console_toggle_buttons: list[object] = []
        self.console_window = None
        self.intro_window = None
        self.latest_mesh_bounds_xml = ""

        self._build_ui()
        if self.settings.get(INTRO_DISMISSED_KEY) != "1":
            self.root.after(250, self._show_intro_dialog)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_messages)

    def mainloop(self) -> None:
        self.root.mainloop()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Accent.TLabel", foreground=ACCENT_COLOR)
        style.configure("Title.TLabel", foreground=ACCENT_COLOR, font=("", 15, "bold"))
        style.configure("SplashTitle.TLabel", foreground=ACCENT_COLOR, font=("", 18, "bold"))
        style.configure("SplashSubtitle.TLabel", foreground="#444444", font=("", 10))
        style.configure("AboutTitle.TLabel", foreground=ACCENT_COLOR, font=("", 10, "bold"))
        style.configure("AboutVersion.TLabel", font=("", 9, "bold"))
        style.configure("Accent.TLabelframe.Label", foreground=ACCENT_COLOR)
        style.configure("Warning.TLabelframe.Label", foreground=ACCENT_COLOR, font=("", 9, "bold"))
        style.configure("Accent.TButton", foreground=ACCENT_COLOR)
        style.map("Accent.TButton", foreground=[("active", ACCENT_DARK_COLOR), ("disabled", "#808080")])

        try:
            style.configure("TNotebook.Tab", padding=(12, 5))
            style.map(
                "TNotebook.Tab",
                foreground=[("selected", ACCENT_COLOR)],
                background=[("selected", ACCENT_LIGHT_COLOR)],
            )
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text=APP_HEADING, style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")
        self._build_console_toggle(header).grid(row=0, column=1, sticky="e")

        accent_bar = tk.Frame(outer, height=3, bg=ACCENT_COLOR)
        accent_bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        notebook = ttk.Notebook(outer)
        notebook.grid(row=2, column=0, sticky="nsew")
        self.main_notebook = notebook

        bounds_tab = ttk.Frame(notebook, padding=10)
        import_tab = ttk.Frame(notebook, padding=10)
        project_backup_tab = ttk.Frame(notebook, padding=10)
        settings_tab = ttk.Frame(notebook, padding=10)
        notebook.add(bounds_tab, text="Bounds Patcher")
        notebook.add(import_tab, text="Import Repair")
        notebook.add(project_backup_tab, text="Project Tools")
        notebook.add(settings_tab, text="Settings")
        self.bounds_tab = bounds_tab
        self.import_tab = import_tab
        self.project_backup_tab = project_backup_tab
        self.settings_tab = settings_tab

        bounds_tab.columnconfigure(0, weight=1)
        bounds_tab.rowconfigure(0, weight=1)
        settings_tab.columnconfigure(1, weight=1)

        bounds_modes = ttk.Notebook(bounds_tab)
        bounds_modes.grid(row=0, column=0, sticky="nsew")

        patch_tab = ttk.Frame(bounds_modes, padding=8)
        auto_tab = ttk.Frame(bounds_modes, padding=8)
        mesh_bounds_tab = ttk.Frame(bounds_modes, padding=8)
        bounds_modes.add(auto_tab, text="One-Click Patcher")
        bounds_modes.add(patch_tab, text="LSF Patcher")
        bounds_modes.add(mesh_bounds_tab, text="Bounds Calculator")

        self._build_patch_lsf_tab(patch_tab)
        self._build_mesh_bounds_tab(mesh_bounds_tab)
        self._build_auto_bounds_tab(auto_tab)

        self._build_import_repair_tab(import_tab)
        self._build_project_backup_tab(project_backup_tab)
        self._build_settings_tab(settings_tab)
        self.active_output_name = "One-Click Patcher"
        self.active_status_label = self.auto_status_label

    def _show_intro_dialog(self) -> None:
        if self.intro_window is not None and self.intro_window.winfo_exists():
            self.intro_window.lift()
            return

        dialog = tk.Toplevel(self.root)
        self.intro_window = dialog
        dialog.title("generic startup message (:")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        dismiss_intro = tk.BooleanVar(master=dialog, value=False)

        content = ttk.Frame(dialog, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="hOI!", style="SplashTitle.TLabel").grid(row=0, column=0, sticky="w")
        intro_label = self._add_wrapping_label(
            content,
            (
                "Just a little tool I made for myself to assist with my modding workflow and "
                "to help with issues I come across.\n\n"
                "Please make sure you have LsLib installed.\n\n"
                "To get started, go to the Settings tab and set the directory to the BG3 folder "
                "and Divine.exe (found in LsLib)."
            ),
            row=1,
            pady=(10, 0),
            style="SplashSubtitle.TLabel",
        )

        button_row = ttk.Frame(content)
        button_row.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        button_row.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            button_row,
            text="Don't show this again",
            variable=dismiss_intro,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            button_row,
            text="Wiki",
            command=lambda: self._open_about_link(TOOLKIT_ASSISTANT_WIKI_URL),
        ).grid(row=0, column=1, sticky="e", padx=(0, 8))
        ttk.Button(
            button_row,
            text="Download LsLib",
            command=lambda: self._open_about_link(LSLIB_RELEASES_URL),
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))
        ttk.Button(
            button_row,
            text="Go to Settings",
            command=lambda: close_intro(self.settings_tab),
            style="Accent.TButton",
        ).grid(row=0, column=3, sticky="e")

        def close_intro(target_tab=None) -> None:
            if dismiss_intro.get():
                self.settings[INTRO_DISMISSED_KEY] = "1"
                self.show_intro_on_startup.set(False)
                try:
                    save_settings(self.settings)
                except OSError as exc:
                    messagebox.showwarning(APP_TITLE, f"Could not save intro preference: {exc}")

            if target_tab is not None:
                self.main_notebook.select(target_tab)

            dialog.grab_release()
            dialog.destroy()
            self.intro_window = None

        dialog.protocol("WM_DELETE_WINDOW", close_intro)
        desired_width = 520
        intro_label.configure(wraplength=desired_width - 56)
        dialog.update_idletasks()
        width = max(dialog.winfo_width(), desired_width)
        intro_label.configure(wraplength=width - 56)
        dialog.update_idletasks()
        height = dialog.winfo_height()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = max(self.root.winfo_width(), width)
        root_height = max(self.root.winfo_height(), height)
        x = root_x + (root_width - width) // 2
        y = root_y + (root_height - height) // 2
        dialog.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()
        dialog.focus_set()

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

    def _build_console_toggle(self, parent):
        icon = self._load_console_icon()
        if icon is None:
            console_toggle = ttk.Label(parent, text="Log", cursor="hand2", padding=(4, 2))
        else:
            console_toggle = ttk.Label(parent, image=icon, cursor="hand2", padding=0)

        console_toggle.bind("<Button-1>", lambda _event: self._toggle_console_window())
        self.console_toggle_buttons.append(console_toggle)
        ToolTip(console_toggle, "Show or hide log")
        return console_toggle

    def _build_tab_footer(self, tab, row: int, *, columnspan: int = 3):
        footer = ttk.Frame(tab)
        footer.grid(row=row, column=0, columnspan=columnspan, sticky="sew")
        footer.columnconfigure(0, weight=1)
        footer.rowconfigure(0, weight=1)

        status_label = ttk.Label(footer, text="", style="Accent.TLabel")
        status_label.grid(row=0, column=0, sticky="sw")

        return status_label

    def _load_console_icon(self):
        if self.console_icon is not None:
            return self.console_icon
        if not CONSOLE_ICON_PATH.is_file():
            return None

        try:
            icon = tk.PhotoImage(file=str(CONSOLE_ICON_PATH))
        except tk.TclError:
            return None

        target_size = 16
        factor = max(icon.width() // target_size, icon.height() // target_size, 1)
        if factor > 1:
            icon = icon.subsample(factor, factor)
        self.console_icon = icon
        return self.console_icon

    def _ensure_console_window(self) -> None:
        if self.console_window is not None and self.console_window.winfo_exists():
            return

        window = tk.Toplevel(self.root)
        self.console_window = window
        window.title("Toolkit Assistant Log")
        self._set_window_icon(window)
        window.geometry("720x360")
        window.minsize(520, 240)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        window.protocol("WM_DELETE_WINDOW", self._hide_console_window)

        toolbar = ttk.Frame(window, padding=(10, 10, 10, 0))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Button(toolbar, text="Clear", command=self._clear_console_output).grid(row=0, column=1, sticky="e")

        log_frame = tk.Frame(window, bg="#15181f", highlightbackground="#343a46", highlightthickness=1)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        output_text = tk.Text(
            log_frame,
            background="#15181f",
            borderwidth=0,
            foreground="#e7eaf0",
            wrap="word",
            font=("Consolas", 9),
            highlightthickness=0,
            insertbackground="#e7eaf0",
            padx=12,
            pady=10,
            relief="flat",
            selectbackground="#3d4554",
            selectforeground="#ffffff",
            state="disabled",
        )
        output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=output_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        output_text.configure(yscrollcommand=scrollbar.set)
        output_text.tag_configure("section", foreground="#d6a8ff")
        output_text.tag_configure("complete", foreground="#96f2b2")
        output_text.tag_configure("error", foreground="#ff8f9a")
        self.console_output_text = output_text

        window.withdraw()

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

        ttk.Label(tab, text="Rename Mod", style="AboutTitle.TLabel").grid(
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

        ttk.Label(tab, text="Project Backup", style="AboutTitle.TLabel").grid(
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
        settings_tab.rowconfigure(5, weight=1)

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

        note_box = ttk.LabelFrame(settings_tab, text="Info", padding=10, style="Accent.TLabelframe")
        note_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        note_box.columnconfigure(0, weight=1)
        self._add_wrapping_label(
            note_box,
            "Select the folder named Baldurs Gate 3, not its Data folder.",
        )

        ttk.Label(settings_tab, text="Divine.exe").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Entry(settings_tab, textvariable=self.divine_path).grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=(10, 0),
        )
        ttk.Button(settings_tab, text="Browse", command=self._browse_divine).grid(
            row=2,
            column=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Checkbutton(
            settings_tab,
            text="Show intro on startup",
            variable=self.show_intro_on_startup,
            command=self._save_intro_preference,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))

        settings_footer = ttk.Frame(settings_tab)
        settings_footer.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 0))
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

        self._build_spacer_row(settings_tab, 5)

        about_box = ttk.LabelFrame(settings_tab, text="About", padding=10, style="Accent.TLabelframe")
        about_box.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        about_box.columnconfigure(0, weight=1)

        ttk.Label(about_box, text="Developed by Luminiari, powered by coffee and bagels.", style="AboutTitle.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
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

            link.grid(row=0, column=index + 1, padx=5)
            link.bind("<Button-1>", lambda _event, target=url: self._open_about_link(target))
            ToolTip(link, label)

        self.settings_status_label = self._build_tab_footer(settings_tab, 7)

    def _browse_mesh_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose mesh file",
            filetypes=(("Mesh files", "*.gr2 *.dae"), ("GR2 files", "*.gr2"), ("DAE files", "*.dae"), ("All files", "*.*")),
        )
        if path:
            self.mesh_file_path.set(path)

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

    def _set_window_icon(self, window=None) -> None:
        if not APP_ICON_PATH.is_file():
            return

        target = window or self.root
        try:
            target.iconbitmap(default=str(APP_ICON_PATH))
        except tk.TclError:
            pass

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
        self.project_backup_status_label.configure(text="No projects selected")

    def _log_project_backup_selection(self, project_names: list[str]) -> None:
        self._activate_project_backup_output()
        heading = "Selected project:" if len(project_names) == 1 else "Selected projects:"
        self._append_output(f"{heading}\n")
        for project_name in project_names:
            self._append_output(f"- {project_name}\n")
        self._append_output("\n")

    def _open_project_backup_picker(self) -> None:
        if self._is_busy():
            return

        if self.project_picker_window is not None and self.project_picker_window.winfo_exists():
            self.project_picker_window.lift()
            return

        game_folder = self.game_folder_path.get().strip()
        if not game_folder:
            messagebox.showwarning(APP_TITLE, "Choose the Game folder in Settings first.")
            return
        game_folder_error = get_game_folder_error(game_folder)
        if game_folder_error:
            messagebox.showwarning(APP_TITLE, game_folder_error)
            return

        projects_dir = Path(game_folder) / "Data" / "Projects"
        if not projects_dir.is_dir():
            messagebox.showwarning(APP_TITLE, f"Could not find Projects folder: {projects_dir}")
            return

        try:
            project_names = find_toolkit_project_names(projects_dir)
        except OSError as exc:
            messagebox.showwarning(APP_TITLE, f"Could not read Projects folder: {exc}")
            return

        if not project_names:
            self._log_no_project_selection()
            return

        dialog = tk.Toplevel(self.root)
        self.project_picker_window = dialog
        dialog.title("Select Projects")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        content = ttk.Frame(dialog, padding=12)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        list_frame = ttk.Frame(content)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        project_canvas = tk.Canvas(
            list_frame,
            height=min(260, max(130, len(project_names) * 26)),
            highlightthickness=0,
            borderwidth=0,
        )
        project_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, command=project_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        project_canvas.configure(yscrollcommand=scrollbar.set)

        checkbox_frame = ttk.Frame(project_canvas)
        checkbox_window = project_canvas.create_window((0, 0), window=checkbox_frame, anchor="nw")

        def update_checkbox_scroll_region(_event=None) -> None:
            project_canvas.configure(scrollregion=project_canvas.bbox("all"))

        def resize_checkbox_frame(event) -> None:
            project_canvas.itemconfigure(checkbox_window, width=event.width)

        checkbox_frame.bind("<Configure>", update_checkbox_scroll_region)
        project_canvas.bind("<Configure>", resize_checkbox_frame)

        selected_names = {project_name.lower() for project_name in self.project_backup_selected_projects}
        project_vars: list[tuple[str, tk.BooleanVar]] = []
        for index, project_name in enumerate(project_names):
            selected = project_name.lower() in selected_names
            selected_var = tk.BooleanVar(master=dialog, value=selected)
            project_vars.append((project_name, selected_var))
            ttk.Checkbutton(
                checkbox_frame,
                text=project_name,
                variable=selected_var,
            ).grid(row=index, column=0, sticky="w", pady=1)

        button_row = ttk.Frame(content)
        button_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        button_row.columnconfigure(2, weight=1)

        def close_picker() -> None:
            dialog.grab_release()
            dialog.destroy()
            self.project_picker_window = None

        def select_all_projects() -> None:
            for _project_name, selected_var in project_vars:
                selected_var.set(True)

        def clear_project_selection() -> None:
            for _project_name, selected_var in project_vars:
                selected_var.set(False)

        def save_project_selection() -> None:
            selected_projects = [project_name for project_name, selected_var in project_vars if selected_var.get()]
            if not selected_projects:
                close_picker()
                self._log_no_project_selection()
                return

            self.project_backup_selected_projects = selected_projects
            self._update_project_backup_selection_summary()
            self._log_project_backup_selection(selected_projects)
            self.project_backup_status_label.configure(text=self.project_backup_selection_text.get())
            close_picker()

        ttk.Button(button_row, text="Select All", command=select_all_projects).grid(row=0, column=0, sticky="w")
        ttk.Button(button_row, text="Select None", command=clear_project_selection).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(8, 0),
        )
        ttk.Button(button_row, text="Cancel", command=close_picker).grid(row=0, column=3, sticky="e", padx=(0, 8))
        ttk.Button(
            button_row,
            text="Save Selection",
            command=save_project_selection,
            style="Accent.TButton",
        ).grid(row=0, column=4, sticky="e")

        dialog.protocol("WM_DELETE_WINDOW", close_picker)
        dialog.update_idletasks()
        width = max(dialog.winfo_width(), 460)
        height = max(dialog.winfo_height(), 320)
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_width = max(self.root.winfo_width(), width)
        root_height = max(self.root.winfo_height(), height)
        x = root_x + (root_width - width) // 2
        y = root_y + (root_height - height) // 2
        dialog.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()
        dialog.focus_set()

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

    def _save_settings_clicked(self) -> None:
        if self._save_current_settings():
            self.settings_status_label.configure(text="Settings saved")

    def _open_settings_folder_clicked(self) -> None:
        settings_folder = SETTINGS_PATH.parent
        try:
            settings_folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                # Python knows this exists on Windows, but apparently needs me to say it.
                os.startfile(str(settings_folder))  # type: ignore[attr-defined]
            else:
                webbrowser.open(settings_folder.as_uri())
            self.settings_status_label.configure(text="Settings folder opened")
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
        self.settings_status_label.configure(text=f"Deleted {deleted} temporary item(s)")

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
        path = RESOURCE_DIR / "assets" / filename
        if not path.is_file():
            return None

        try:
            icon = tk.PhotoImage(file=str(path))
        except tk.TclError:
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
                    self._current_status_label().configure(text="Complete")
                elif kind == "error":
                    self._append_output(f"Error: {value}\n", "error")
                    self._set_running(False)
                    self._current_status_label().configure(text="Failed")
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
            self._current_status_label().configure(text="Running...")

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
        self._current_status_label().configure(text="Copied bounds XML")

    def _on_close(self) -> None:
        self.root.destroy()

def main() -> int:
    app = ToolkitAssistantApp()
    app.mainloop()
    return 0
