from __future__ import annotations

from types import SimpleNamespace

import customtkinter as ctk

from luminiari_ui import (
    DEFAULT_ACCENT,
    MUTED,
    TEXT,
    LumiButton,
    LumiCheckBox,
    LumiEntry,
    LumiFieldset,
    LumiLabel,
    LumiNotebook,
    LumiRadioButton,
    LumiScrollbar,
    LumiSeparator,
    body_font,
    display_font,
)


def _actual_master(master):
    return getattr(master, "_lumi_child_master", master)


def _app(master):
    current = master
    while current is not None:
        if hasattr(current, "register_accent_target"):
            return current
        current = getattr(current, "master", None)
    return None


def _accent(master) -> str:
    app = _app(master)
    return getattr(app, "accent", DEFAULT_ACCENT)


def _padding_values(padding) -> tuple[tuple[int, int], tuple[int, int]]:
    if padding is None:
        return (0, 0), (0, 0)
    if isinstance(padding, int):
        return (padding, padding), (padding, padding)
    values = tuple(int(value) for value in padding)
    if len(values) == 2:
        return (values[0], values[0]), (values[1], values[1])
    if len(values) == 4:
        return (values[0], values[2]), (values[1], values[3])
    return (0, 0), (0, 0)


class Frame(ctk.CTkFrame):
    def __init__(self, master, *args, padding=None, **kwargs) -> None:
        kwargs.pop("style", None)
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("corner_radius", 0)
        self._lumi_grid_padx, self._lumi_grid_pady = _padding_values(padding)
        super().__init__(_actual_master(master), *args, **kwargs)

    def grid(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        if self._lumi_grid_padx != (0, 0) and "padx" not in kwargs:
            kwargs["padx"] = self._lumi_grid_padx
        if self._lumi_grid_pady != (0, 0) and "pady" not in kwargs:
            kwargs["pady"] = self._lumi_grid_pady
        return super().grid(**kwargs)

    def pack(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        if self._lumi_grid_padx != (0, 0) and "padx" not in kwargs:
            kwargs["padx"] = self._lumi_grid_padx
        if self._lumi_grid_pady != (0, 0) and "pady" not in kwargs:
            kwargs["pady"] = self._lumi_grid_pady
        return super().pack(**kwargs)


class Label(LumiLabel):
    _ACCENT_STYLES = {
        "Accent.TLabel",
        "Title.TLabel",
        "SplashTitle.TLabel",
        "AboutTitle.TLabel",
    }

    def __init__(self, master, *args, style=None, foreground=None, padding=None, **kwargs) -> None:
        kwargs.pop("relief", None)
        kwargs.pop("borderwidth", None)
        self._lumi_style = style
        self._lumi_accent_role = style in self._ACCENT_STYLES
        if foreground is not None:
            kwargs["text_color"] = foreground
        elif self._lumi_accent_role:
            kwargs["text_color"] = _accent(master)
        elif style == "SplashSubtitle.TLabel":
            kwargs["text_color"] = MUTED
        else:
            kwargs.setdefault("text_color", TEXT)
        if style == "Title.TLabel":
            kwargs.setdefault("font", display_font())
        elif style == "SplashTitle.TLabel":
            kwargs.setdefault("font", display_font(24))
        elif style in {"AboutTitle.TLabel", "AboutVersion.TLabel"}:
            kwargs.setdefault("font", body_font(strong=True))
        elif style == "SplashSubtitle.TLabel":
            kwargs.setdefault("font", body_font())
        else:
            kwargs.setdefault("font", body_font())
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("height", 0)
        if "image" in kwargs:
            kwargs.setdefault("text", "")
        if padding is not None:
            padx, pady = _padding_values(padding)
            kwargs.setdefault("width", max(1, padx[0] + padx[1]))
            if pady != (0, 0):
                kwargs["height"] = pady[0] + pady[1]
        super().__init__(_actual_master(master), *args, **kwargs)
        app = _app(master)
        if self._lumi_accent_role and app is not None:
            app.register_accent_target(self)

    def set_accent(self, accent: str) -> None:
        if self._lumi_accent_role:
            super().configure(text_color=accent)

    def configure(self, require_redraw=False, **kwargs):
        if "foreground" in kwargs:
            kwargs["text_color"] = kwargs.pop("foreground")
        kwargs.pop("style", None)
        kwargs.pop("padding", None)
        return super().configure(require_redraw=require_redraw, **kwargs)

    config = configure


class Button(LumiButton):
    def __init__(self, master, *args, style=None, padding=None, **kwargs) -> None:
        text = str(kwargs.pop("text", ""))
        command = kwargs.pop("command", None)
        width = kwargs.pop("width", max(78, len(text) * 7 + 24))
        kwargs.pop("takefocus", None)
        super().__init__(
            _actual_master(master),
            text=text,
            command=command,
            variant="primary" if style == "Accent.TButton" else "secondary",
            accent=_accent(master),
            width=width,
            **kwargs,
        )


class Entry(LumiEntry):
    def __init__(self, master, *args, **kwargs) -> None:
        kwargs.pop("style", None)
        super().__init__(_actual_master(master), *args, **kwargs)


class Checkbutton(LumiCheckBox):
    def __init__(self, master, *args, **kwargs) -> None:
        kwargs.pop("style", None)
        super().__init__(_actual_master(master), *args, accent=_accent(master), **kwargs)


class Radiobutton(LumiRadioButton):
    def __init__(self, master, *args, **kwargs) -> None:
        kwargs.pop("style", None)
        super().__init__(_actual_master(master), *args, accent=_accent(master), **kwargs)


class Scrollbar(LumiScrollbar):
    def __init__(self, master, *args, orient="vertical", **kwargs) -> None:
        kwargs.pop("style", None)
        orientation = kwargs.pop("orientation", orient)
        command = kwargs.pop("command", None)
        super().__init__(
            _actual_master(master),
            orientation=orientation,
            command=command,
            accent=_accent(master),
            **kwargs,
        )


class Separator(LumiSeparator):
    def __init__(self, master, *args, orient="horizontal", **kwargs) -> None:
        super().__init__(_actual_master(master), *args, orient=orient, **kwargs)


class LabelFrame(LumiFieldset):
    def __init__(self, master, *args, text="", padding=None, style=None, **kwargs) -> None:
        super().__init__(_actual_master(master), text=text, accent=_accent(master), **kwargs)
        self._lumi_child_master = self.body

    def columnconfigure(self, index, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        return self.body.columnconfigure(index, **kwargs)

    def rowconfigure(self, index, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        return self.body.rowconfigure(index, **kwargs)


class Notebook(LumiNotebook):
    def __init__(self, master, *args, **kwargs) -> None:
        super().__init__(_actual_master(master), accent=_accent(master))
        self._lumi_child_master = self.content

    def add(self, child, **kwargs) -> None:
        self.add_existing(str(kwargs.get("text", "Tab")), child)


class Style:

    def __init__(self, master=None) -> None:
        self.master = master

    def configure(self, *args, **kwargs) -> None:
        return None

    def map(self, *args, **kwargs) -> None:
        return None


ttk = SimpleNamespace(
    Button=Button,
    Checkbutton=Checkbutton,
    Entry=Entry,
    Frame=Frame,
    Label=Label,
    LabelFrame=LabelFrame,
    Notebook=Notebook,
    Radiobutton=Radiobutton,
    Scrollbar=Scrollbar,
    Separator=Separator,
    Style=Style,
)


__all__ = ["ttk"]
