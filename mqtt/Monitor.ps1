$taskRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $taskRoot 'backend\.venv\Scripts\python.exe') -u (Join-Path $PSScriptRoot 'monitor.py')
