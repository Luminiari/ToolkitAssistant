# Lumi's Toolkit Assistant
A small Windows helper for Baldur's Gate 3 Toolkit chores I got tired of doing by hand. Larian why are you like this.

If you just want to use the thing and do not care how it works:

* Download the latest build from the [Releases page](https://github.com/Luminiari/ToolkitAssistant/releases).
* Read the [project Wiki](https://github.com/Luminiari/ToolkitAssistant/wiki) for instructions on tool operation, though I did try to make it as simple as possible ~~lol. lmao even~~.

If you are here to look at the source or build it yourself, I am sorry for what I am about to do to your eyeballs.

## What It Do

* Patches VisualBank LSF bounds from related GR2 meshes
* Calculates bounds XML from `.gr2` or `.dae` meshes
* Supports manual bounds patching when you need direct control
* Repairs import settings XML paths that got rewritten to absolute `Data/ASSETS` paths
* Renames Toolkit mod folders while preserving UUID suffixes
* Backs up Toolkit project folders before you do something adventurous

## What's In It

The app entry point is:

```text
ToolkitAssistant.pyw
```

The launcher stays small; the actual code lives in:

```text
toolkit_assistant/
```

Useful starting points:

* `toolkit_assistant/app.py` - Tkinter UI
* `toolkit_assistant/bounds_patcher.py` - LSF and VisualBank patching workflows
* `toolkit_assistant/mesh_bounds.py` - GR2/DAE bounds calculation
* `toolkit_assistant/import_repair.py` - import settings XML repair
* `toolkit_assistant/project_tools.py` - project rename and backup tools
* `toolkit_assistant/divine.py` - Divine.exe integration
* `toolkit_assistant/settings.py` - local settings file handling

## Requirements

For running from source:

* Windows
* Python 3.11 or newer
* `Divine.exe` from Norbyte's LSLib
* A Baldur's Gate 3 install folder

For building the EXE:

* Everything above
* py2exe, installed by `build.ps1` from `requirements-build.txt`

`Divine.exe` can be selected in the app's Settings tab, or exposed with:

```powershell
$env:LSLIB_DIVINE = "C:\Tools\ExportTool\Tools\Divine.exe"
```

## Run From Source

```powershell
py -3 ToolkitAssistant.pyw
```

If the Windows Python launcher is not available:

```powershell
python ToolkitAssistant.pyw
```

## Build The EXE

From this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Python py
```

If you use `python` instead of the Windows launcher:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Python python
```

The finished app is written to:

```text
dist\ToolkitAssistant.exe
```

with a release zip written to:

```text
dist\ToolkitAssistant-v[VERSION].zip
```
where [VERSION] comes from `version_info.txt`, so ideally I only have to remember one thing.

## Local Settings

Settings are saved per Windows user at:

```text
%APPDATA%\ToolkitAssistant\settings.json
```

This stores paths like the selected `Divine.exe`, the selected BG3 folder, and the project backup destination.

## Safety Notes

Do not run Toolkit Assistant while the BG3 Toolkit is open. The Toolkit can overwrite project files when it saves or exits, because of course it can.

Backups are enabled by default for file replacement workflows. Keep them on unless you like to live dangerously.

## Documentation

How-to documentation belongs in the [Wiki](https://github.com/Luminiari/ToolkitAssistant/wiki). It's already a meme that I like writing documentation but I also write too much so whatever.

## Licence

Lumi's Toolkit Assistant uses a proprietary source-available licence. Source may be viewed and built for personal use, but reuse, redistribution, or forks require permission. See `LICENSE.md`.

This is an unofficial fan project and is not endorsed by Larian Studios or Wizards of the Coast.

**Support your local trans creators please and thank you.**
