$ErrorActionPreference = 'Stop'
$taskScript = Join-Path $PSScriptRoot 'Enable-Firewall.ps1'
$taskArguments = '-NoProfile -ExecutionPolicy Bypass -NoExit -File "{0}"' -f $taskScript
# User launches this helper explicitly; keep the admin console visible for results.
Start-Process powershell.exe -Verb RunAs -ArgumentList $taskArguments -WindowStyle Normal
