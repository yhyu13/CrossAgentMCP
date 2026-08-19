# Start the CrossAgentMCP A2A stack in the background: pool (:9100) + the three
# agent A2A servers (writer :9101, critic :9102, lead :9103).
#
# These processes must be running for the `a2a-*` MCP bridges (Kilo / Claude Code
# / Codex) to reach the pool and the agent data-plane endpoints.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/start-servers.ps1
# Stop:   powershell -ExecutionPolicy Bypass -File scripts/stop-servers.ps1
param(
    [int]$PoolPort = 9100,
    [switch]$WithDemoAuth
)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root ".a2a"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Start-A2aProcess([string]$Label, [string[]]$CmdArgs, [string]$Log) {
    $p = Start-Process -FilePath "uv" `
        -ArgumentList $CmdArgs `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtime "$Log.out.log") `
        -RedirectStandardError (Join-Path $runtime "$Log.err.log") `
        -PassThru
    $p.Id | Set-Content -Path (Join-Path $runtime "$Label.pid")
    Write-Host "[a2a] $Label started (pid $($p.Id))"
    return $p
}

Write-Host "[a2a] starting pool on 127.0.0.1:$PoolPort"
$poolArgs = @("run", "python", "-m", "crossagent.pool",
              "--host", "127.0.0.1", "--port", "$PoolPort")
if ($WithDemoAuth) {
    $poolArgs += @("--agents",
        '{"writer":"demo-writer-token","critic":"demo-critic-token","lead":"demo-lead-token"}',
        "--orchestrator-token", "demo-orchestrator-token")
}
Start-A2aProcess "pool" $poolArgs "pool" | Out-Null

Write-Host "[a2a] starting agent A2A servers"
Start-A2aProcess "writer" @("run", "python", "agents/writer/server.py") "writer" | Out-Null
Start-A2aProcess "critic" @("run", "python", "agents/critic/server.py") "critic" | Out-Null
Start-A2aProcess "lead"   @("run", "python", "agents/lead/server.py")   "lead"   | Out-Null

Write-Host "[a2a] waiting for pool health..."
$health = "http://127.0.0.1:$PoolPort/health"
for ($i = 0; $i -lt 40; $i++) {
    try {
        Invoke-RestMethod -Uri $health -TimeoutSec 2 | Out-Null
        Write-Host "[a2a] pool healthy at $health"
        Write-Host "[a2a] ready. logs + pids under $runtime"
        exit 0
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
Write-Host "[a2a] ERROR: pool did not become healthy; see $runtime\pool.err.log"
exit 1
