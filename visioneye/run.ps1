param(
    [switch]$Demo,
    [string]$Source,
    [switch]$PickVideo,
    [switch]$Calibrate,
    [switch]$Headless,
    [switch]$SaveVideo,
    [string]$Device = 'auto'
)
$ErrorActionPreference = 'Stop'
$pythonCandidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) { throw 'Run setup.ps1 first to install the local Python environment.' }
if ($PickVideo) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Select a video for VisionEye'
    $picker.Filter = 'Video files|*.mp4;*.avi;*.mov;*.mkv;*.wmv;*.m4v|All files|*.*'
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $Source = $picker.FileName
    $picker.Dispose()
}
$appArgs = @('-X', 'utf8', (Join-Path $PSScriptRoot 'app.py'), '--device', $Device)
if ($Demo -or -not $Source) { $appArgs += @('--demo', '--config', (Join-Path $PSScriptRoot 'demo-config.json')) }
else { $appArgs += @('--source', $Source) }
if ($Calibrate) { $appArgs += '--calibrate' }
if ($Headless) { $appArgs += '--headless' }
if ($SaveVideo) { $appArgs += '--save-video' }
& $pythonExe @appArgs
exit $LASTEXITCODE

