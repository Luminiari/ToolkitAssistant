package require Tk 8.6-

source [file join [file dirname [info script]] theme light.tcl]
source [file join [file dirname [info script]] theme dark.tcl]


if {[tk windowingsystem] == "win32"} {
  set static ""
} else {
  set static " static"
}

font create LumiSunValleyCaptionFont -family "Segoe UI Variable$static Small" -size -11
font create LumiSunValleyBodyFont -family "Segoe UI Variable$static Text" -size -12
font create LumiSunValleyBodyStrongFont -family "Segoe UI Variable$static Text Semibold" -size -12
font create LumiSunValleyBodyLargeFont -family "Segoe UI Variable$static Text" -size -16
font create LumiSunValleySubtitleFont -family "Segoe UI Variable$static Display Semibold" -size -18
font create LumiSunValleyTitleFont -family "Segoe UI Variable$static Display Semibold" -size -24
font create LumiSunValleyTitleLargeFont -family "Segoe UI Variable$static Display Semibold" -size -34
font create LumiSunValleyDisplayFont -family "Segoe UI Variable$static Display Semibold" -size -56


proc config_entry_font {w} {
  set font_config [$w config -font]
  if {[lindex $font_config 3] != [lindex $font_config 4]} {
    return
  }
  if {[ttk::style theme use] in {"lumi-sun-valley-dark" "lumi-sun-valley-light"}} {
    $w configure -font LumiSunValleyBodyFont
  }
}


proc config_menus {w} {
  if {[tk windowingsystem] == "aqua" || [tk windowingsystem] == "win32"} {
    return
  }

  set theme [ttk::style theme use]
  if {$theme == "lumi-sun-valley-dark"} {
    $w configure \
      -relief solid \
      -borderwidth 1 \
      -activeborderwidth 0 \
      -background "#292929" \
      -activebackground $ttk::theme::lumi_sv_dark::colors(-selbg) \
      -activeforeground $ttk::theme::lumi_sv_dark::colors(-selfg) \
      -selectcolor $ttk::theme::lumi_sv_dark::colors(-selfg)
  } elseif {$theme == "lumi-sun-valley-light"} {
    $w configure \
      -relief solid \
      -borderwidth 1 \
      -activeborderwidth 0 \
      -background "#e7e7e7" \
      -activebackground $ttk::theme::lumi_sv_light::colors(-selbg) \
      -activeforeground $ttk::theme::lumi_sv_light::colors(-selfg) \
      -selectcolor $ttk::theme::lumi_sv_light::colors(-selfg)
  }

  if {[[winfo toplevel $w] cget -menu] != $w} {
    if {$theme == "lumi-sun-valley-dark"} {
      $w configure -borderwidth 0 -background $ttk::theme::lumi_sv_dark::colors(-bg)
    } elseif {$theme == "lumi-sun-valley-light"} {
      $w configure -borderwidth 0 -background $ttk::theme::lumi_sv_light::colors(-bg)
    }
  }
}


proc configure_colors {} {
  set theme [ttk::style theme use]
  if {$theme == "lumi-sun-valley-dark"} {
    ttk::style configure . \
      -background $ttk::theme::lumi_sv_dark::colors(-bg) \
      -foreground $ttk::theme::lumi_sv_dark::colors(-fg) \
      -troughcolor $ttk::theme::lumi_sv_dark::colors(-bg) \
      -focuscolor $ttk::theme::lumi_sv_dark::colors(-selbg) \
      -selectbackground $ttk::theme::lumi_sv_dark::colors(-selbg) \
      -selectforeground $ttk::theme::lumi_sv_dark::colors(-selfg) \
      -insertwidth 1 \
      -insertcolor $ttk::theme::lumi_sv_dark::colors(-fg) \
      -fieldbackground $ttk::theme::lumi_sv_dark::colors(-bg) \
      -font LumiSunValleyBodyFont \
      -borderwidth 0 \
      -relief flat

    tk_setPalette \
      background $ttk::theme::lumi_sv_dark::colors(-bg) \
      foreground $ttk::theme::lumi_sv_dark::colors(-fg) \
      highlightColor $ttk::theme::lumi_sv_dark::colors(-selbg) \
      selectBackground $ttk::theme::lumi_sv_dark::colors(-selbg) \
      selectForeground $ttk::theme::lumi_sv_dark::colors(-selfg) \
      activeBackground $ttk::theme::lumi_sv_dark::colors(-selbg) \
      activeForeground $ttk::theme::lumi_sv_dark::colors(-selfg)

    ttk::style map . -foreground [list disabled $ttk::theme::lumi_sv_dark::colors(-disfg)]
  } elseif {$theme == "lumi-sun-valley-light"} {
    ttk::style configure . \
      -background $ttk::theme::lumi_sv_light::colors(-bg) \
      -foreground $ttk::theme::lumi_sv_light::colors(-fg) \
      -troughcolor $ttk::theme::lumi_sv_light::colors(-bg) \
      -focuscolor $ttk::theme::lumi_sv_light::colors(-selbg) \
      -selectbackground $ttk::theme::lumi_sv_light::colors(-selbg) \
      -selectforeground $ttk::theme::lumi_sv_light::colors(-selfg) \
      -insertwidth 1 \
      -insertcolor $ttk::theme::lumi_sv_light::colors(-fg) \
      -fieldbackground $ttk::theme::lumi_sv_light::colors(-bg) \
      -font LumiSunValleyBodyFont \
      -borderwidth 0 \
      -relief flat

    tk_setPalette \
      background $ttk::theme::lumi_sv_light::colors(-bg) \
      foreground $ttk::theme::lumi_sv_light::colors(-fg) \
      highlightColor $ttk::theme::lumi_sv_light::colors(-selbg) \
      selectBackground $ttk::theme::lumi_sv_light::colors(-selbg) \
      selectForeground $ttk::theme::lumi_sv_light::colors(-selfg) \
      activeBackground $ttk::theme::lumi_sv_light::colors(-selbg) \
      activeForeground $ttk::theme::lumi_sv_light::colors(-selfg)

    ttk::style map . -foreground [list disabled $ttk::theme::lumi_sv_light::colors(-disfg)]
  }
}


bind [winfo class .] <<ThemeChanged>> {+configure_colors}
bind TEntry <<ThemeChanged>> {+config_entry_font %W}
bind TCombobox <<ThemeChanged>> {+config_entry_font %W}
bind TSpinbox <<ThemeChanged>> {+config_entry_font %W}
bind Menu <<ThemeChanged>> {+config_menus %W}
