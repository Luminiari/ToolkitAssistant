from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk

from luminiari_ui import (
    FAILURE,
    SUCCESS,
    LumiApp as BaseLumiApp,
    LumiColourButton,
    LumiIconButton,
    LumiListBox,
    LumiPngIcon,
    LumiScrollbar,
    LumiScrollableFrame,
    LumiStyle,
    LumiTextBox,
    LumiWindow as BaseLumiWindow,
    appearance_colour,
    mono_font,
)

from . import app as legacy
from .constants import (
    ACCENT_COLOR,
    ABOUT_LINKS,
    APP_HEADING,
    APP_ICON_PATH,
    APP_TITLE,
    INTRO_DISMISSED_KEY,
    RESOURCE_DIR,
)
from .divine import find_default_divine
from .lumi_widgets import ttk as lumi_ttk
from .project_tools import find_toolkit_project_names
from .settings import load_settings
from .ui_theme import (
    ACCENT_COLOR_SETTING_KEY,
    UI_THEME_DARK,
    UI_THEME_LIGHT,
    UI_THEME_SETTING_KEY,
    normalize_accent_color,
    normalize_ui_theme_name,
)


legacy.load_tk()
legacy.ttk = lumi_ttk


class SafeDelayedFocusMixin:

    def after(self, ms, func=None, *args):
        target = getattr(func, "__self__", None)
        method = getattr(func, "__func__", None)
        if isinstance(target, tk.Misc) and method in (tk.Misc.focus_set, tk.Misc.focus_force):
            original = func

            def restore_focus(*callback_args):
                if target.winfo_exists():
                    return original(*callback_args)

            func = restore_focus
        return super().after(ms, func, *args)


class LumiApp(SafeDelayedFocusMixin, BaseLumiApp):
    pass


class LumiWindow(SafeDelayedFocusMixin, BaseLumiWindow):
    pass


class ToolkitAssistantApp(legacy.ToolkitAssistantApp):

    def __init__(self) -> None:
        self.settings = load_settings()
        self.ui_theme_name = normalize_ui_theme_name(
            self.settings.get(UI_THEME_SETTING_KEY, UI_THEME_LIGHT)
        )
        self._set_accent_palette(
            self.settings.get(ACCENT_COLOR_SETTING_KEY, ACCENT_COLOR)
        )
        self.root = LumiApp(
            title=APP_TITLE,
            heading=APP_HEADING,
            style=LumiStyle(accent=self.accent_color, mode=self.ui_theme_name),
            geometry="760x560",
            minimum_size=(760, 560),
            app_id="ToolkitAssistant.ToolkitAssistant",
            icon_path=APP_ICON_PATH,
        )
        self.lumi_theme_loaded = True

        tk = legacy.tk
        self.mesh_file_path = tk.StringVar(master=self.root)
        self.auto_bounds_mode = tk.StringVar(master=self.root, value="batch")
        self.auto_selected_lsf_summary = tk.StringVar(
            master=self.root, value="No files selected"
        )
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
        self.project_backup_selection_text = tk.StringVar(
            master=self.root, value="No projects selected"
        )
        self.project_backup_selected_projects: list[str] = []
        self.project_picker_window = None
        self.show_intro_on_startup = tk.BooleanVar(
            master=self.root,
            value=self.settings.get(INTRO_DISMISSED_KEY) != "1",
        )
        self.dark_mode = tk.BooleanVar(
            master=self.root, value=self.ui_theme_name == UI_THEME_DARK
        )

        self.messages: queue.Queue[tuple[str, str | int]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.run_buttons: list[object] = []
        self.active_output_name = ""
        self.active_status_label = None
        self.about_link_icons: list[object] = []
        self.about_link_icon_labels: list[tuple[object, str]] = []
        self.console_icon = None
        self.console_output_text = None
        self.console_toggle_buttons: list[object] = []
        self.console_window = None
        self.intro_window = None
        self.experimental_tab = None
        self.latest_mesh_bounds_xml = ""
        self.pending_theme_after = None
        self.accent_bar = self.root.accent_bar
        self.accent_swatch = None
        self.direct_accent_labels: list[object] = []
        self.tinted_icon_cache: dict[tuple[str, str, int | None], object] = {}

        self._build_ui()
        self._restore_experimental_features()
        self._apply_plain_widget_theme()
        self.root.after_idle(self._refresh_app_styles)
        if self.settings.get(INTRO_DISMISSED_KEY) != "1":
            self.root.after(250, self._show_intro_dialog)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_messages)

    def _build_ui(self) -> None:
        self._build_console_toggle(self.root.header_actions).grid(
            row=0, column=0, sticky="e"
        )

        self.main_notebook = self.root.tabs
        self.bounds_tab = self.root.add_tab(
            "Bounds Patcher", self._build_bounds_patcher_tab
        )
        self.import_tab = self.root.add_tab(
            "Import Repair", self._build_import_repair_page
        )
        self.project_backup_tab = self.root.add_tab(
            "Project Tools", self._build_project_tools_page
        )
        self.settings_tab = self.root.add_tab("Settings", self._build_settings_page)

        self.active_output_name = "One-Click Patcher"
        self.active_status_label = self.auto_status_label

    def _build_bounds_patcher_tab(self, tab) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        bounds_modes = lumi_ttk.Notebook(tab)
        self.bounds_modes = bounds_modes
        bounds_modes.grid(row=0, column=0, sticky="nsew")

        auto_tab = lumi_ttk.Frame(bounds_modes, padding=8)
        patch_tab = lumi_ttk.Frame(bounds_modes, padding=8)
        mesh_bounds_tab = lumi_ttk.Frame(bounds_modes, padding=8)
        bounds_modes.add(auto_tab, text="One-Click Patcher")
        bounds_modes.add(patch_tab, text="LSF Patcher")
        bounds_modes.add(mesh_bounds_tab, text="Bounds Calculator")

        self._build_auto_bounds_tab(auto_tab)
        self._build_patch_lsf_tab(patch_tab)
        self._build_mesh_bounds_tab(mesh_bounds_tab)

    def _build_import_repair_page(self, tab) -> None:
        self._build_import_repair_tab(tab)

    def _build_project_tools_page(self, tab) -> None:
        self._build_project_backup_tab(tab)

    def _build_settings_page(self, tab) -> None:
        tab.columnconfigure(1, weight=1)
        self._build_settings_tab(tab)

    def _build_auto_bounds_tab(self, tab) -> None:
        super()._build_auto_bounds_tab(tab)
        old_list = self.auto_selected_lsf_listbox
        parent = old_list.master
        old_list.destroy()
        for child in tuple(parent.winfo_children()):
            if isinstance(child, LumiScrollbar):
                child.destroy()
        self.auto_selected_lsf_listbox = LumiListBox(
            parent,
            accent=self.accent_color,
            height=92,
        )
        self.auto_selected_lsf_listbox.grid(row=0, column=0, sticky="ew")
        self._update_auto_selected_lsf_summary()

    def _build_patch_lsf_tab(self, tab) -> None:
        super()._build_patch_lsf_tab(tab)

        old_uuid_text = self.patch_uuid_text
        uuid_parent = old_uuid_text.master
        old_uuid_text.destroy()
        for child in tuple(uuid_parent.winfo_children()):
            if isinstance(child, LumiScrollbar):
                child.destroy()
        self.patch_uuid_text = LumiTextBox(
            uuid_parent,
            accent=self.accent_color,
            height=82,
            wrap="word",
            undo=True,
            font=mono_font(),
        )
        self.patch_uuid_text.grid(row=0, column=0, sticky="ew")

        old_bounds_text = self.patch_bounds_text
        bounds_parent = old_bounds_text.master
        old_bounds_text.destroy()
        self.patch_bounds_text = LumiTextBox(
            bounds_parent,
            accent=self.accent_color,
            height=82,
            wrap="none",
            undo=True,
            font=mono_font(),
        )
        self.patch_bounds_text.grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(12, 0),
        )

    def _configure_styles(self) -> None:
        pass

    def _apply_ui_theme(self) -> None:
        self.root.set_appearance_mode(self.ui_theme_name)
        self._refresh_app_styles()

    def _refresh_app_styles(self) -> None:
        self._apply_plain_widget_theme()
        self._update_accent_widgets()

    def _apply_plain_widget_theme(self) -> None:
        pass

    def _update_accent_widgets(self) -> None:
        if self.accent_swatch is not None:
            self.accent_swatch.set_colour(self.accent_color)
        for label in self.direct_accent_labels:
            try:
                if label.winfo_exists():
                    label.configure(foreground=self.accent_color)
            except legacy.tk.TclError:
                pass
        if self.console_output_text is not None:
            self.console_output_text.tag_configure(
                "section", foreground=self.accent_light_color
            )
            self.console_output_text.tag_configure(
                "complete",
                foreground=appearance_colour(SUCCESS, self.ui_theme_name),
            )
            self.console_output_text.tag_configure(
                "error",
                foreground=appearance_colour(FAILURE, self.ui_theme_name),
            )

    def _set_accent_color(self, accent_color: object, *, save: bool = True) -> None:
        normalized_color = normalize_accent_color(accent_color)
        if normalized_color == self.accent_color:
            return
        self._set_accent_palette(normalized_color)
        self.settings[ACCENT_COLOR_SETTING_KEY] = self.accent_color
        self.root.set_accent(self.accent_color)
        self._refresh_tinted_icons()
        self._refresh_app_styles()
        if save:
            self._save_accent_preference()

    def _refresh_tinted_icons(self) -> None:
        for icon in tuple(self.tinted_icon_cache.values()):
            setter = getattr(icon, "set_accent", None)
            if callable(setter):
                setter(self.accent_color)

    def _load_tinted_icon(self, filename: str, *, target_size: int | None = None):
        size = target_size or 32
        cache_key = (filename, "lumi", size)
        cached_icon = self.tinted_icon_cache.get(cache_key)
        if cached_icon is not None:
            return cached_icon
        path = RESOURCE_DIR / "assets" / filename
        if not path.is_file():
            return None
        try:
            icon = LumiPngIcon(
                self.root,
                path,
                self.accent_color,
                size=(size, size),
            )
        except (OSError, ValueError):
            return None
        self.tinted_icon_cache[cache_key] = icon
        return icon

    def _show_intro_dialog(self) -> None:
        if self.intro_window is not None and self.intro_window.winfo_exists():
            self.intro_window.lift()
            return

        dialog = LumiWindow(
            self.root,
            title="generic startup message (:",
            icon_path=APP_ICON_PATH,
            resizable=(False, False),
        )
        self.intro_window = dialog
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        dismiss_intro = legacy.tk.BooleanVar(master=dialog, value=False)

        content = lumi_ttk.Frame(dialog, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        lumi_ttk.Label(content, text="hOI!", style="SplashTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
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

        button_row = lumi_ttk.Frame(content)
        button_row.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        button_row.columnconfigure(0, weight=1)
        lumi_ttk.Checkbutton(
            button_row,
            text="Don't show this again",
            variable=dismiss_intro,
        ).grid(row=0, column=0, sticky="w")
        lumi_ttk.Button(
            button_row,
            text="Wiki",
            command=lambda: self._open_about_link(legacy.TOOLKIT_ASSISTANT_WIKI_URL),
        ).grid(row=0, column=1, sticky="e", padx=(0, 8))
        lumi_ttk.Button(
            button_row,
            text="Download LsLib",
            command=lambda: self._open_about_link(legacy.LSLIB_RELEASES_URL),
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))
        lumi_ttk.Button(
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
                    legacy.save_settings(self.settings)
                except OSError as exc:
                    legacy.messagebox.showwarning(
                        APP_TITLE, f"Could not save intro preference: {exc}"
                    )
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

    def _ensure_console_window(self) -> None:
        if self.console_window is not None and self.console_window.winfo_exists():
            return

        window = LumiWindow(
            self.root,
            title="Toolkit Assistant Log",
            geometry="720x360",
            minimum_size=(520, 240),
            icon_path=APP_ICON_PATH,
        )
        self.console_window = window
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        window.protocol("WM_DELETE_WINDOW", self._hide_console_window)

        toolbar = lumi_ttk.Frame(window, padding=(10, 10, 10, 0))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        lumi_ttk.Button(
            toolbar,
            text="Clear",
            command=self._clear_console_output,
        ).grid(row=0, column=1, sticky="e")

        log_frame = lumi_ttk.Frame(window, padding=(10, 8, 10, 10))
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        output_text = LumiTextBox(
            log_frame,
            accent=self.accent_color,
            wrap="word",
            font=mono_font(),
            state="disabled",
        )
        output_text.grid(row=0, column=0, sticky="nsew")
        output_text.tag_configure("section", foreground=self.accent_light_color)
        output_text.tag_configure(
            "complete",
            foreground=appearance_colour(SUCCESS, self.ui_theme_name),
        )
        output_text.tag_configure(
            "error",
            foreground=appearance_colour(FAILURE, self.ui_theme_name),
        )
        self.console_output_text = output_text
        window.withdraw()

    def _build_console_toggle(self, parent):
        icon = self._load_console_icon()
        if icon is None:
            return lumi_ttk.Button(
                parent, text="Log", command=self._toggle_console_window
            )
        toggle = LumiIconButton(
            parent,
            icon=icon,
            command=self._toggle_console_window,
            tooltip="Show or hide log",
            accent=self.accent_color,
            size=(32, 32),
        )
        self.console_toggle_buttons.append(toggle)
        return toggle

    def _build_settings_tab(self, settings_tab) -> None:
        super()._build_settings_tab(settings_tab)
        old_swatch = self.accent_swatch
        parent = old_swatch.master
        old_swatch.destroy()
        self.accent_swatch = LumiColourButton(
            parent,
            colour=self.accent_color,
            command=self._choose_accent_color,
            tooltip="Choose accent colour",
            width=40,
            height=28,
        )
        self.accent_swatch.grid(row=0, column=0, sticky="w", padx=(0, 8))

        about_links = {
            icon_name: (label_text, url)
            for label_text, url, icon_name in ABOUT_LINKS
        }
        replacements: list[tuple[object, str]] = []
        replacement_icons: list[object] = []
        for column, (old_label, icon_name) in enumerate(
            list(self.about_link_icon_labels), start=1
        ):
            label_text, url = about_links[icon_name]
            parent = old_label.master
            old_label.destroy()
            for cache_key in tuple(self.tinted_icon_cache):
                if cache_key[0] == icon_name:
                    self.tinted_icon_cache.pop(cache_key, None)
            icon = LumiPngIcon(
                self.root,
                RESOURCE_DIR / "assets" / icon_name,
                self.accent_color,
                size=(32, 32),
            )
            link = LumiIconButton(
                parent,
                icon=icon,
                command=lambda target=url: self._open_about_link(target),
                tooltip=label_text,
                accent=self.accent_color,
                size=(36, 36),
            )
            link.grid(row=0, column=column, padx=5)
            self.tinted_icon_cache[(icon_name, "about-button", 32)] = icon
            replacement_icons.append(icon)
            replacements.append((link, icon_name))
        self.about_link_icons = replacement_icons
        self.about_link_icon_labels = replacements

    def _add_experimental_tab(self, *, select: bool = False) -> None:
        if self.experimental_tab is None:
            self.experimental_tab = self.root.add_tab(
                "Experimental", self._build_experimental_tab
            )
        if select:
            self.main_notebook.select(self.experimental_tab)

    def _open_project_backup_picker(self) -> None:
        if self._is_busy():
            return
        if (
            self.project_picker_window is not None
            and self.project_picker_window.winfo_exists()
        ):
            self.project_picker_window.lift()
            return

        game_folder = self.game_folder_path.get().strip()
        if not game_folder:
            legacy.messagebox.showwarning(
                APP_TITLE, "Choose the Game folder in Settings first."
            )
            return
        game_folder_error = legacy.get_game_folder_error(game_folder)
        if game_folder_error:
            legacy.messagebox.showwarning(APP_TITLE, game_folder_error)
            return

        projects_dir = Path(game_folder) / "Data" / "Projects"
        if not projects_dir.is_dir():
            legacy.messagebox.showwarning(
                APP_TITLE, f"Could not find Projects folder: {projects_dir}"
            )
            return
        try:
            project_names = find_toolkit_project_names(projects_dir)
        except OSError as exc:
            legacy.messagebox.showwarning(
                APP_TITLE, f"Could not read Projects folder: {exc}"
            )
            return
        if not project_names:
            self._log_no_project_selection()
            return

        dialog = LumiWindow(
            self.root,
            title="Select Projects",
            geometry="460x320",
            minimum_size=(460, 320),
            icon_path=APP_ICON_PATH,
            resizable=(True, True),
        )
        self.project_picker_window = dialog
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        content = lumi_ttk.Frame(dialog, padding=12)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        project_list = LumiScrollableFrame(
            content,
            accent=self.accent_color,
            height=min(260, max(130, len(project_names) * 26)),
        )
        project_list.grid(row=0, column=0, sticky="nsew")
        project_list.grid_columnconfigure(0, weight=1)

        selected_names = {
            project_name.lower()
            for project_name in self.project_backup_selected_projects
        }
        project_vars: list[tuple[str, object]] = []
        for index, project_name in enumerate(project_names):
            selected_var = legacy.tk.BooleanVar(
                master=dialog,
                value=project_name.lower() in selected_names,
            )
            project_vars.append((project_name, selected_var))
            lumi_ttk.Checkbutton(
                project_list,
                text=project_name,
                variable=selected_var,
            ).grid(row=index, column=0, sticky="w", pady=1)

        button_row = lumi_ttk.Frame(content)
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
            selected_projects = [
                project_name
                for project_name, selected_var in project_vars
                if selected_var.get()
            ]
            if not selected_projects:
                close_picker()
                self._log_no_project_selection()
                return
            self.project_backup_selected_projects = selected_projects
            self._update_project_backup_selection_summary()
            self._log_project_backup_selection(selected_projects)
            self._set_status(
                self.project_backup_status_label,
                self.project_backup_selection_text.get(),
            )
            close_picker()

        lumi_ttk.Button(
            button_row,
            text="Select All",
            command=select_all_projects,
        ).grid(row=0, column=0, sticky="w")
        lumi_ttk.Button(
            button_row,
            text="Select None",
            command=clear_project_selection,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        lumi_ttk.Button(
            button_row,
            text="Cancel",
            command=close_picker,
        ).grid(row=0, column=3, sticky="e", padx=(0, 8))
        lumi_ttk.Button(
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

    def _apply_and_save_ui_theme(self) -> None:
        self.pending_theme_after = None
        self._apply_ui_theme()
        self.root.after(50, self._save_theme_preference)


def main() -> int:
    app = ToolkitAssistantApp()
    app.mainloop()
    return 0


__all__ = ["ToolkitAssistantApp", "main"]
