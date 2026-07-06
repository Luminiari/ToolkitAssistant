[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

function Get-PythonValue {
    param([Parameter(Mandatory = $true)][string]$Code)

    $value = & $Python -c $Code
    if ($LASTEXITCODE -ne 0) {
        throw "Python query failed with exit code $LASTEXITCODE."
    }
    return ($value | Select-Object -First 1).Trim()
}

if (-not $SkipInstall) {
    Invoke-CheckedPython -m pip install -r requirements-build.txt
}

$pythonRoot = Get-PythonValue "import sys; print(sys.base_prefix)"
$dllRoot = Join-Path $pythonRoot "DLLs"
$tclRoot = Join-Path $pythonRoot "tcl"
$hookRoot = Join-Path (Get-Location).Path "pyinstaller-hooks"
$assetRoot = Join-Path (Get-Location).Path "assets"
$iconPath = Join-Path (Get-Location).Path "assets\ToolkitAssistant.ico"
$versionInfoPath = Join-Path (Get-Location).Path "version_info.txt"

$buildArgs = @(
    "--clean",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name",
    "ToolkitAssistant",
    "--distpath",
    "dist",
    "--workpath",
    "build",
    "--specpath",
    "build",
    "--additional-hooks-dir",
    $hookRoot,
    "--hidden-import",
    "tkinter",
    "--hidden-import",
    "tkinter.ttk",
    "--hidden-import",
    "tkinter.filedialog",
    "--hidden-import",
    "tkinter.messagebox",
    "--hidden-import",
    "_tkinter"
)

if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
    $buildArgs += @("--icon", $iconPath)
}

if (Test-Path -LiteralPath $versionInfoPath -PathType Leaf) {
    $buildArgs += @("--version-file", $versionInfoPath)
    $buildArgs += @("--add-data", "$versionInfoPath;.")
}

if (Test-Path -LiteralPath $assetRoot -PathType Container) {
    $buildArgs += @("--add-data", "$assetRoot;assets")
}

if (Test-Path -LiteralPath $tclRoot) {
    $tclDir = Get-ChildItem -LiteralPath $tclRoot -Directory -Filter "tcl*" |
        Where-Object { $_.Name -match "^tcl\d" } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    $tkDir = Get-ChildItem -LiteralPath $tclRoot -Directory -Filter "tk*" |
        Where-Object { $_.Name -match "^tk\d" } |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if ($tclDir -and $tkDir) {
        $buildArgs += @("--add-data", "$($tclDir.FullName);_tcl_data")
        $buildArgs += @("--add-data", "$($tkDir.FullName);_tk_data")
    }
}

foreach ($binaryName in @("_tkinter*.pyd", "tcl*.dll", "tk*.dll")) {
    if (-not (Test-Path -LiteralPath $dllRoot)) {
        continue
    }

    $binary = Get-ChildItem -LiteralPath $dllRoot -File -Filter $binaryName | Select-Object -First 1
    if ($binary) {
        $destination = if ($binary.Extension -eq ".pyd") { "DLLs" } else { "." }
        $buildArgs += @("--add-binary", "$($binary.FullName);$destination")
    }
}

$buildArgs += "ToolkitAssistant.pyw"

Invoke-CheckedPython -c "import PyInstaller.__main__, sys; PyInstaller.__main__.run(sys.argv[1:])" @buildArgs

Write-Host "Built dist\ToolkitAssistant.exe"
