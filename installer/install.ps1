param(
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $InstallerDir
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = $RepoRoot
}

$Python = $null
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    $Python = $py.Source
    $PythonArgs = @("-3")
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $Python = $pythonCmd.Source
        $PythonArgs = @()
    }
}

if (-not $Python) {
    Write-Error "Python 3 was not found. Install it from https://www.python.org/downloads/ and run this installer again."
}

& $Python @PythonArgs (Join-Path $RepoRoot "installer\install.py") --root $InstallRoot
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Host "`nMARK is installed. The desktop shortcut is ready." -ForegroundColor Cyan
