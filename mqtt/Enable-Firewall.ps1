# Requires an Administrator PowerShell. Only opens MQTT from the local subnet.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskBroker = Join-Path $taskRoot '.tools\mosquitto\mosquitto.exe'
$taskConnection = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime\connection.json') -Raw | ConvertFrom-Json
$taskRuleName = 'IOT-ESP32-MQTT-' + $taskConnection.port
if (Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $taskRuleName -Enabled True -Profile Any -Action Allow
    Get-NetFirewallRule -Name $taskRuleName | Get-NetFirewallAddressFilter |
        Set-NetFirewallAddressFilter -LocalAddress Any -RemoteAddress LocalSubnet
} else {
    New-NetFirewallRule -Name $taskRuleName -DisplayName 'IoT ESP32 MQTT (local subnet)' `
        -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol TCP -LocalPort $taskConnection.port `
        -LocalAddress Any -RemoteAddress LocalSubnet -Program $taskBroker | Out-Null
}
$taskPython = Join-Path $taskRoot 'backend\.venv\Scripts\python.exe'
# Windows venv python.exe is a launcher; firewall rules must match the actual
# base interpreter process that owns the mDNS socket.
$taskMdnsProgram = & $taskPython -c 'import sys; print(sys._base_executable or sys.executable)'
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskMdnsProgram)) {
    throw 'Could not find the Python interpreter used for MQTT discovery.'
}
# mDNS advertisements and queries stay on the local subnet and follow DHCP.
$taskMdnsRule = 'IOT-ESP32-MDNS'
if (Get-NetFirewallRule -Name $taskMdnsRule -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $taskMdnsRule -Enabled True -Profile Any -Action Allow
    Get-NetFirewallRule -Name $taskMdnsRule | Get-NetFirewallAddressFilter |
        Set-NetFirewallAddressFilter -LocalAddress Any -RemoteAddress LocalSubnet
    Get-NetFirewallRule -Name $taskMdnsRule | Get-NetFirewallApplicationFilter |
        Set-NetFirewallApplicationFilter -Program $taskMdnsProgram
} else {
    New-NetFirewallRule -Name $taskMdnsRule -DisplayName 'IoT MQTT discovery (local subnet)' `
        -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol UDP -LocalPort 5353 `
        -LocalAddress Any -RemoteAddress LocalSubnet -Program $taskMdnsProgram | Out-Null
}
Write-Host 'MQTT firewall rule enabled for the local subnet only.'
