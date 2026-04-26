<#
.SYNOPSIS
    PowerShell wrapper for ml/train.sh.

.DESCRIPTION
    Delegates to bash so PowerShell users on Windows can invoke the trainer
    without dropping into Git Bash. All flags pass through unchanged.

.EXAMPLE
    .\train.ps1 --dry-run
    .\train.ps1 0
    .\train.ps1 from 2 --fast
    .\train.ps1 all --fast --n-parallel 12
#>

[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Args
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BashScript = Join-Path $ScriptDir 'train.sh'

if (-not (Test-Path -LiteralPath $BashScript)) {
    Write-Error "train.sh not found next to train.ps1 (looked at $BashScript)"
    exit 1
}

# Resolve a bash executable. Prefer one already on PATH; fall back to the
# Git for Windows install path.
$BashExe = (Get-Command bash -ErrorAction SilentlyContinue).Source
if (-not $BashExe) {
    $candidates = @(
        'C:\Program Files\Git\bin\bash.exe',
        'C:\Program Files (x86)\Git\bin\bash.exe',
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { $BashExe = $c; break }
    }
}

if (-not $BashExe) {
    Write-Error 'bash not found. Install Git for Windows (https://git-scm.com/download/win) or run this script under WSL.'
    exit 1
}

# Convert C:\foo\bar to /c/foo/bar so Git Bash on Windows resolves the path.
$drive = $BashScript.Substring(0, 1).ToLower()
$rest = $BashScript.Substring(2) -replace '\\', '/'
$BashScriptUnix = "/$drive$rest"

& $BashExe $BashScriptUnix @Args
exit $LASTEXITCODE
