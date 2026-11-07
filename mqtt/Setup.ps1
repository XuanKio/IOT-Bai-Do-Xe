param([string]$BrokerIP, [int]$MqttPort = 1884)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTools = Join-Path $taskRoot '.tools'
$taskPython = Join-Path $taskRoot 'backend\.venv\Scripts\python.exe'

if (-not $BrokerIP) {
    $taskRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 |
        Where-Object { $_.NextHop -ne '0.0.0.0' } | Sort-Object RouteMetric | Select-Object -First 1
    if (-not $taskRoute) { throw 'No LAN route found. Connect the computer to Wi-Fi first.' }
    $BrokerIP = (Get-NetIPAddress -InterfaceIndex $taskRoute.InterfaceIndex -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress
}
$taskParsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BrokerIP, [ref]$taskParsedIP) -or
    $taskParsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'BrokerIP must be an IPv4 address of this computer.'
}
New-Item -ItemType Directory -Path $taskTools, (Join-Path $PSScriptRoot 'runtime') -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $taskTools 'mosquitto\mosquitto.exe'))) {
    $task7zr = Join-Path $taskTools '7zr.exe'
    if (-not (Test-Path -LiteralPath $task7zr)) {
        Invoke-WebRequest 'https://www.7-zip.org/a/7zr.exe' -OutFile $task7zr
    }
    $task7zInstaller = Join-Path $taskTools '7z-installer.exe'
    if (-not (Test-Path -LiteralPath $task7zInstaller)) {
        Invoke-WebRequest 'https://github.com/ip7z/7zip/releases/download/26.05/7z2605-x64.exe' -OutFile $task7zInstaller
    }
    & $task7zr x $task7zInstaller ('-o' + (Join-Path $taskTools '7zip')) -y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract 7-Zip.' }
    $taskMosquittoInstaller = Join-Path $taskTools 'mosquitto-installer.exe'
    if (-not (Test-Path -LiteralPath $taskMosquittoInstaller)) {
        Invoke-WebRequest 'https://mosquitto.org/files/binary/win64/mosquitto-2.1.2-install-windows-x64.exe' -OutFile $taskMosquittoInstaller
    }
    & (Join-Path $taskTools '7zip\7z.exe') x $taskMosquittoInstaller ('-o' + (Join-Path $taskTools 'mosquitto')) -y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract Mosquitto.' }
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    python -m venv (Join-Path $taskRoot 'backend\.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
}
& $taskPython -m pip install -r (Join-Path $taskRoot 'backend\requirements-dev.txt') --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
& $taskPython (Join-Path $PSScriptRoot 'configure.py') --host $BrokerIP --port $MqttPort
if ($LASTEXITCODE -ne 0) { throw 'MQTT configuration failed.' }
& $taskPython (Join-Path $PSScriptRoot 'bootstrap_backend.py')
if ($LASTEXITCODE -ne 0) { throw 'Backend setup failed.' }
Write-Host 'Setup complete. Run mqtt\Start-IOT.ps1, then mqtt\Monitor.ps1.'
