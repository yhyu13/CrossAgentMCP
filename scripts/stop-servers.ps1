# Stop the background CrossAgentMCP A2A stack started by start-servers.ps1.
$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root ".a2a"

Get-ChildItem -Path $runtime -Filter "*.pid" | ForEach-Object {
    $procId = Get-Content -Path $_.FullName
    if ($procId) {
        # taskkill /T /F kills the whole tree (uv shim + python child).
        & taskkill /PID $procId /T /F | Out-Null
        Write-Host "[a2a] stopped $($_.BaseName) (pid $procId)"
    }
    Remove-Item -Path $_.FullName
}
Write-Host "[a2a] done"
