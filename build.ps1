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

function Get-VersionInfoValue {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $match = [regex]::Match($Text, "StringStruct\(`"$Name`",\s*`"([^`"]+)`"\)")
    if ($match.Success) {
        return $match.Groups[1].Value
    }

    return $null
}

if (-not $SkipInstall) {
    Invoke-CheckedPython -m pip install -r requirements-build.txt
}

$pythonExecutable = Get-PythonValue "import sys; print(sys.executable)"
if ($pythonExecutable -like "*\WindowsApps\*") {
    Write-Warning "py2exe says Windows Store Python is unsupported. If this falls over, try Python from python.org."
}

Invoke-CheckedPython py2exe_build.py

$outputFolder = Join-Path (Get-Location).Path "dist\ToolkitAssistant"
$outputExe = Join-Path $outputFolder "ToolkitAssistant.exe"
$versionInfoPath = Join-Path (Get-Location).Path "version_info.txt"
$versionInfoText = Get-Content -Raw -LiteralPath $versionInfoPath
$version = Get-VersionInfoValue -Text $versionInfoText -Name "ProductVersion"
if (-not $version) {
    $version = Get-VersionInfoValue -Text $versionInfoText -Name "FileVersion"
}
if (-not $version) {
    throw "Could not read ProductVersion or FileVersion from version_info.txt."
}
$zipPath = Join-Path (Get-Location).Path "dist\ToolkitAssistant-v$version.zip"

if (-not (Test-Path -LiteralPath $outputExe -PathType Leaf)) {
    throw "py2exe finished, but the exe was not found at $outputExe."
}

Compress-Archive -LiteralPath $outputFolder -DestinationPath $zipPath -Force

Write-Host "Built $outputExe"
Write-Host "Zipped $zipPath"
Write-Host "Release folder layout: ToolkitAssistant.exe, python312.dll, lib\, runtime\"
