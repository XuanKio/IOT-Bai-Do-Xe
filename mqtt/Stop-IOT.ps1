$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPidFile = Join-Path $PSScriptRoot 'runtime\processes.json'
if (Test-Path -LiteralPath $taskPidFile) {
    $taskSaved = Get-Content -LiteralPath $taskPidFile -Raw | ConvertFrom-Json
    foreach ($taskName in @('backend', 'broker')) {
        $taskId = $taskSaved.$taskName
        if (-not $taskId) { continue }
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskId"
        if ($taskProcess -and $taskProcess.CommandLine -and $taskProcess.CommandLine.Contains($taskRoot)) {
            Stop-Process -Id $taskId
            Write-Host ("Stopped {0}." -f $taskName)
        }
    }
    Remove-Item -LiteralPath $taskPidFile
}
