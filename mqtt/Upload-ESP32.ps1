param([string]$Port, [string]$Fqbn = 'esp32:esp32:esp32', [switch]$CompileOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskCli = Join-Path $env:LOCALAPPDATA 'Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe'
if (-not (Test-Path -LiteralPath $taskCli)) {
    $taskCommand = Get-Command arduino-cli -ErrorAction SilentlyContinue
    if (-not $taskCommand) { throw 'Install Arduino IDE or arduino-cli first.' }
    $taskCli = $taskCommand.Source
}
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'esp32_core\config.local.h'))) {
    throw 'Run mqtt\Setup.ps1 first.'
}
& $taskCli lib install 'PubSubClient@2.8.0' 'WiFiManager@2.0.17' 'ArduinoJson@7.4.2'
if ($LASTEXITCODE -ne 0) { throw 'Arduino library installation failed.' }
$taskSketch = Join-Path $taskRoot 'esp32_core'
$taskBuild = Join-Path $taskSketch 'build'
& $taskCli compile --fqbn $Fqbn --output-dir $taskBuild $taskSketch
if ($LASTEXITCODE -ne 0) { throw 'ESP32 compilation failed.' }
if ($CompileOnly) { return }
if (-not $Port) {
    & $taskCli board list
    throw 'Choose the ESP32 USB port, then run: .\mqtt\Upload-ESP32.ps1 -Port COM5 (replace COM5).'
}
& $taskCli upload --fqbn $Fqbn --port $Port --input-dir $taskBuild $taskSketch
if ($LASTEXITCODE -ne 0) { throw 'ESP32 upload failed. Check USB cable, port and BOOT button.' }
Write-Host 'Uploaded. Open Serial Monitor at 115200 baud to configure Wi-Fi.'
