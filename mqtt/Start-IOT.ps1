param([switch]$BrokerOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskRuntime = Join-Path $PSScriptRoot 'runtime'
$taskPython = Join-Path $taskRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $taskRuntime 'connection.json'))) {
    & (Join-Path $PSScriptRoot 'Setup.ps1')
}
$taskBroker = Join-Path $taskRoot '.tools\mosquitto\mosquitto.exe'
$taskConfig = Join-Path $taskRuntime 'mosquitto.conf'
$taskConnection = Get-Content -LiteralPath (Join-Path $taskRuntime 'connection.json') -Raw | ConvertFrom-Json
$taskPidFile = Join-Path $taskRuntime 'processes.json'
$taskSaved = @{}
if (Test-Path -LiteralPath $taskPidFile) {
    $taskPrior = Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json
    foreach ($taskName in @('broker', 'backend')) {
        $taskId = $taskPrior.$taskName
        if ($taskId) {
            $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskId"
            if ($taskProcess -and $taskProcess.CommandLine -and $taskProcess.CommandLine.Contains($taskRoot)) {
                $taskSaved[$taskName] = [int]$taskId
            }
        }
    }
}
if (-not $taskSaved.ContainsKey('broker')) {
    # DHCP can change the computer's LAN IP between Run sessions. Binding to the
    # old address makes Mosquitto exit with "address is not valid in its context".
    $taskAddresses = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.AddressState -eq 'Preferred' -and $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*'
    })
    if ($taskConnection.host -ne '127.0.0.1' -and $taskConnection.host -notin $taskAddresses.IPAddress) {
        $taskInterfaces = @(Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.ConnectionState -eq 'Connected' })
        $taskRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 |
            Where-Object { $_.NextHop -ne '0.0.0.0' -and $_.InterfaceIndex -in $taskAddresses.InterfaceIndex } |
            Sort-Object @{ Expression = {
                $taskRouteIndex = $_.InterfaceIndex
                $taskMetric = ($taskInterfaces | Where-Object InterfaceIndex -eq $taskRouteIndex | Select-Object -First 1).InterfaceMetric
                $_.RouteMetric + $taskMetric
            } } | Select-Object -First 1
        if (-not $taskRoute) {
            throw 'Configured MQTT IP is no longer on this computer. Connect to Wi-Fi/LAN and retry.'
        }
        $taskAddress = $taskAddresses | Where-Object InterfaceIndex -eq $taskRoute.InterfaceIndex | Select-Object -First 1
        & $taskPython (Join-Path $PSScriptRoot 'sync_network.py') --host $taskAddress.IPAddress
        if ($LASTEXITCODE -ne 0) { throw 'Could not update the local MQTT address.' }
        $taskConnection = Get-Content -LiteralPath (Join-Path $taskRuntime 'connection.json') -Raw | ConvertFrom-Json
    }
    & $taskPython (Join-Path $PSScriptRoot 'sync_network.py') --roaming-listener
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the MQTT listener for LAN IP changes.' }
    if (Get-NetTCPConnection -State Listen -LocalPort $taskConnection.port -ErrorAction SilentlyContinue) {
        throw ("Port {0} is already in use by another process." -f $taskConnection.port)
    }
    $taskBrokerProcess = Start-Process -FilePath $taskBroker -ArgumentList @('-c', ('"' + $taskConfig + '"')) `
        -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskRuntime 'broker.stdout.log') `
        -RedirectStandardError (Join-Path $taskRuntime 'broker.stderr.log')
    $taskSaved['broker'] = $taskBrokerProcess.Id
    $taskSaved | ConvertTo-Json | Set-Content -LiteralPath $taskPidFile
    Start-Sleep -Milliseconds 700
    if ($taskBrokerProcess.HasExited) {
        $taskSaved.Remove('broker')
        $taskSaved | ConvertTo-Json | Set-Content -LiteralPath $taskPidFile
        foreach ($taskLogName in @('broker.stdout.log', 'broker.stderr.log')) {
            Get-Content -LiteralPath (Join-Path $taskRuntime $taskLogName) -Tail 20 | ForEach-Object { Write-Host $_ }
        }
        throw 'Broker failed. Read mqtt/runtime/broker.stdout.log and broker.stderr.log.'
    }
}
if ($BrokerOnly) {
    Write-Host ("MQTT broker ready: {0}:{1}" -f $taskConnection.host, $taskConnection.port)
    return
}
if (-not $taskSaved.ContainsKey('backend')) {
    if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
        throw 'Port 8000 is already in use by another process.'
    }
    $taskBackendProcess = Start-Process -FilePath $taskPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--no-access-log',
            '--env-file', ('"' + (Join-Path $taskRuntime 'backend.env') + '"')) `
        -WorkingDirectory (Join-Path $taskRoot 'backend') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskRuntime 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $taskRuntime 'backend.stderr.log')
    $taskSaved['backend'] = $taskBackendProcess.Id
    $taskSaved | ConvertTo-Json | Set-Content -LiteralPath $taskPidFile
}
$taskReady = $false
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    try {
        $taskHealth = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($taskHealth.mqtt_subscribed) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 400
}
if (-not $taskReady) { throw 'Backend/MQTT not ready. Read mqtt/runtime/backend.stderr.log.' }
$taskConnection = Get-Content -LiteralPath (Join-Path $taskRuntime 'connection.json') -Raw | ConvertFrom-Json
Write-Host ("MQTT ready: {0}:{1}" -f $taskConnection.host, $taskConnection.port)
Write-Host 'Dashboard ready: http://127.0.0.1:8000/'
Write-Host 'API documentation: http://127.0.0.1:8000/docs'
Write-Host 'Receive live readings: .\mqtt\Monitor.ps1'
Write-Host 'Credentials: mqtt/runtime/THONG_TIN_DANG_NHAP.txt'
