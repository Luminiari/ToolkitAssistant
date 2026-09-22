# Lumi's Toolkit Assistant

A small Windows helper for Baldur's Gate 3 Toolkit chores I got tired of doing by hand. Larian why are you like this.

If you just want to use the thing and do not care how it works:

* Download the latest build from the [Releases page](https://github.com/Luminiari/ToolkitAssistant/releases).
* Read the [project Wiki](https://github.com/Luminiari/ToolkitAssistant/wiki) for instructions on tool operation, though I did try to make it as simple as possible.

If you are here to look at the source or build it yourself, I am sorry for what I am about to do to your eyeballs.

## What It Does

* Patches VisualBank LSF bounds from related GR2 meshes
* Calculates bounds XML from `.gr2` or `.dae` meshes
* Supports manual bounds patching when you need direct control
* Repairs import settings XML paths that got rewritten to absolute `Data/ASSETS` paths
* Renames Toolkit mod folders while preserving UUID suffixes
* Backs up Toolkit project folders before you do something adventurous
* Other secret fun stuff ( ͡° ͜ʖ ͡°)

## Requirements

To run from source or build the app:

* Windows
* Python 3.11 or newer
* [LumiUI](https://github.com/Luminiari/LumiUI) downloaded beside Toolkit Assistant
* [LSLib](https://github.com/Norbyte/lslib), including `Divine.exe`

## Running From Source

```powershell
python -m pip install -r requirements-build.txt
python ToolkitAssistant.pyw
```

## Building

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Python python
```
The finished release zip will be placed in `dist`.

## Thanks

* [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) by Tom Schimansky, which LumiUI is built on.
* [LSLib](https://github.com/Norbyte/lslib) by Norbyte, for `Divine.exe`.
* [py2exe](https://github.com/py2exe/py2exe) for making the standalone Windows build possible.

## Licence

Lumi's Toolkit Assistant uses a proprietary source-available licence. Source may be viewed and built for personal use, but reuse, redistribution, or forks require permission. See `LICENSE.md`.

This is an unofficial fan project and is not endorsed by Larian Studios or Wizards of the Coast.

<h1 align="center">🏳️‍⚧️ Support your local trans creators please and thank you. 🏳️‍⚧️</h1>
