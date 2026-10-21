param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('jam', 'normal')][string]$Scenario
)
$ErrorActionPreference = 'Stop'
$Helper = Join-Path $PSScriptRoot 'demo_screenshots.py'
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    & python3 $Helper $Scenario
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Helper $Scenario
} else {
    throw 'Install Python 3 for the demo preparation helper.'
}
exit $LASTEXITCODE
