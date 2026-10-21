param([Parameter(Mandatory=$true, Position=0)][string]$Command)
$ErrorActionPreference = 'Stop'
$Controller = Join-Path $PSScriptRoot 'labctl.py'
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    & python3 $Controller $Command
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Controller $Command
} else {
    throw 'Install Python 3 for the cross-platform scenario controller.'
}
exit $LASTEXITCODE
