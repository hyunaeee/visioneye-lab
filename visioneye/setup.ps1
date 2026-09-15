param([string]$PythonPath = 'python', [switch]$CPU)
$ErrorActionPreference = 'Stop'
$venvDir = Join-Path $PSScriptRoot '.venv'
& $PythonPath -m venv $venvDir
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is recommended. Supply -PythonPath with its full path.' }
$pythonExe = Join-Path $venvDir 'Scripts\python.exe'
$indexUrl = if ($CPU) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu128' }
& $pythonExe -m pip install 'torch==2.11.0' 'torchvision==0.26.0' --index-url $indexUrl
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
& $pythonExe -m pip install -r (Join-Path $PSScriptRoot '..\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'VisionEye dependencies failed to install.' }
Write-Output 'Ready. Open Start Demo.cmd or Select Video.cmd.'

