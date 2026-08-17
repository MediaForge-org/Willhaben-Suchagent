# Windows release smoke tests, run on a real GitHub-hosted Windows runner
# right after deployment/build-release-windows.ps1 has produced a release
# stage directory. Verifies the package is structurally complete, the
# bundled agent actually starts and answers /health, the single-instance
# guard works, the native-messaging host speaks the framed protocol
# correctly, and that native-messaging/registry setup is relocation-safe
# (including a path containing a space) — cleaning up any registry state it
# creates on this ephemeral runner afterwards.
#
# Uses only local/fake configuration - no real Discord webhooks, ntfy
# secrets, or SMTP credentials are ever involved.

param(
    [Parameter(Mandatory = $true)]
    [string]$StageDir,

    [Parameter(Mandatory = $false)]
    [string]$LogPath = "windows-smoke-test.log"
)

$ErrorActionPreference = "Stop"
Start-Transcript -Path $LogPath -Force | Out-Null

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "SMOKE TEST FAILED: $Message"
    }
    Write-Host "OK: $Message"
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

try {
    Write-Host "=== 1: Release directory structure ==="
    Assert-True (Test-Path $StageDir) "Release directory exists: $StageDir"
    $agentExe = Join-Path $StageDir "runtime\willhaben-suchagent.exe"
    $hostExe = Join-Path $StageDir "runtime\willhaben-suchagent-host.exe"
    $setupExe = Join-Path $StageDir "runtime\willhaben-suchagent-setup.exe"
    $startBat = Join-Path $StageDir "Willhaben-Suchagent starten.bat"
    $setupBat = Join-Path $StageDir "Einrichtung.bat"
    $xpiPath = Join-Path $StageDir "extension\willhaben-suchagent.xpi"
    Assert-True (Test-Path $agentExe) "Agent executable exists"
    Assert-True (Test-Path $hostExe) "Native-messaging host executable exists"
    Assert-True (Test-Path $setupExe) "Setup executable exists"
    Assert-True (Test-Path $startBat) "Start script exists"
    Assert-True (Test-Path $setupBat) "Setup script exists"
    Assert-True (Test-Path $xpiPath) "Extension .xpi exists"

    Write-Host "=== 2: Extension manifest ==="
    $manifestExtractDir = Join-Path $env:TEMP "willhaben-xpi-check"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $manifestExtractDir
    Expand-Archive -Path $xpiPath -DestinationPath $manifestExtractDir
    $manifest = Get-Content (Join-Path $manifestExtractDir "manifest.json") -Raw | ConvertFrom-Json
    Assert-True ($manifest.version -eq "1.0.0") "Manifest version is 1.0.0 (was: $($manifest.version))"
    Assert-True ($manifest.browser_specific_settings.gecko.id -eq "willhaben-suchagent@local") "Gecko id correct"
    Assert-True ($manifest.permissions -contains "nativeMessaging") "nativeMessaging permission present"
    $hostPermissions = $manifest.PSObject.Properties["host_permissions"]
    Assert-True ((-not $hostPermissions) -or ($hostPermissions.Value.Count -eq 0)) "No host_permissions (no localhost fetch)"

    Write-Host "=== 3: Agent starts and answers /health ==="
    $dataDir = Join-Path $env:TEMP "willhaben-smoke-data"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $dataDir
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $port = Get-FreePort
    $env:WILLHABEN_API_PORT = "$port"
    $env:WILLHABEN_DATABASE_PATH = Join-Path $dataDir "agent.db"
    $env:WILLHABEN_SECRET_STORE_PATH = Join-Path $dataDir "secrets.json"

    $agentProcess = Start-Process -FilePath $agentExe -PassThru -WindowStyle Hidden
    try {
        $health = $null
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
                break
            } catch { Start-Sleep -Milliseconds 200 }
        }
        Assert-True ($null -ne $health) "Agent /health responded"
        Assert-True ($health.status -eq "ok") "Health status is ok"

        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/status" -TimeoutSec 5
        Assert-True ($status.app_version -eq "1.0.0") "app_version is 1.0.0 (was: $($status.app_version))"

        Write-Host "=== 4: Single-instance guard ==="
        $secondProcess = Start-Process -FilePath $agentExe -PassThru -WindowStyle Hidden -Wait
        Assert-True ($secondProcess.ExitCode -eq 0) "Second instance exited cleanly instead of crashing"
        $stillOneAgent = (Get-Process -Id $agentProcess.Id -ErrorAction SilentlyContinue) -ne $null
        Assert-True $stillOneAgent "Original agent instance is still the one running"
        $health2 = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
        Assert-True ($health2.status -eq "ok") "Original instance still answers after second-start attempt"
    } finally {
        if ($agentProcess -and -not $agentProcess.HasExited) {
            Stop-Process -Id $agentProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "=== 5: Native-messaging framed protocol ==="
    $pyScript = @"
import struct, sys
msg = b'{"type":"api.status"}'
env = b'{"requestId":"1","request":' + msg + b'}'
sys.stdout.buffer.write(struct.pack('<I', len(env)))
sys.stdout.buffer.write(env)
"@
    $requestBytes = python -c $pyScript
    $env:WILLHABEN_API_PORT = "$port"
    # Agent is stopped by now; the host only needs to prove it speaks the
    # framed protocol and stamps protocolVersion - a transport error from the
    # (now-stopped) agent is an expected, well-formed "ok: false" response.
    $agentProcess2 = Start-Process -FilePath $agentExe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2
    try {
        $requestBytes | & $hostExe | Set-Content -Path "$env:TEMP\host-response.bin" -Encoding Byte
        $rawBytes = [System.IO.File]::ReadAllBytes("$env:TEMP\host-response.bin")
        Assert-True ($rawBytes.Length -gt 4) "Host produced framed output"
        $length = [System.BitConverter]::ToUInt32($rawBytes, 0)
        $jsonBytes = $rawBytes[4..(4 + $length - 1)]
        $response = [System.Text.Encoding]::UTF8.GetString($jsonBytes) | ConvertFrom-Json
        Assert-True ($response.protocolVersion -eq 1) "protocolVersion is 1 (was: $($response.protocolVersion))"
        Assert-True ($response.requestId -eq "1") "requestId echoed correctly"
        Assert-True ($null -ne $response.response) "Response body present"
        # Exactly one framed message on stdout - no extra stray protocol logging.
        $expectedTotalLength = 4 + $length
        Assert-True ($rawBytes.Length -eq $expectedTotalLength) "stdout contains exactly one framed message, nothing else"
    } finally {
        if ($agentProcess2 -and -not $agentProcess2.HasExited) {
            Stop-Process -Id $agentProcess2.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "=== 6: Native-messaging setup / registry (relocation-safe) ==="
    $registryKeyPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\at.willhaben_suchagent.bridge"

    function Test-SetupPointsAtCurrentPath {
        param([string]$ProjectRoot)
        & $setupExe install-windows --project-root $ProjectRoot | Out-Null
        Assert-True (Test-Path $registryKeyPath) "Registry key exists after install"
        $manifestPath = (Get-ItemProperty -Path $registryKeyPath -Name "(default)").( "(default)" )
        Assert-True ($manifestPath.StartsWith($ProjectRoot)) "Registry value points inside current project root ($ProjectRoot)"
        $manifestContent = Get-Content $manifestPath -Raw | ConvertFrom-Json
        Assert-True ($manifestContent.path.StartsWith($ProjectRoot)) "Manifest launcher path points inside current project root"
        $launcherContent = Get-Content $manifestContent.path -Raw
        Assert-True ($launcherContent.Contains($ProjectRoot)) "Launcher wraps the bundled host executable at the current path"
        & $setupExe uninstall-windows --project-root $ProjectRoot | Out-Null
        Assert-True (-not (Test-Path $registryKeyPath)) "Registry key removed after uninstall"
    }

    Test-SetupPointsAtCurrentPath -ProjectRoot $StageDir

    Write-Host "=== 7: Relocation with a path containing a space ==="
    $relocatedRoot = "C:\temp\Willhaben Test\Willhaben-Suchagent-1.0.0"
    New-Item -ItemType Directory -Force -Path (Split-Path $relocatedRoot -Parent) | Out-Null
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $relocatedRoot
    Copy-Item -Recurse -Path $StageDir -Destination $relocatedRoot

    Test-SetupPointsAtCurrentPath -ProjectRoot $relocatedRoot

    Write-Host ""
    Write-Host "ALL WINDOWS SMOKE TESTS PASSED"
    exit 0
} catch {
    Write-Host $_.Exception.Message
    Write-Host $_.ScriptStackTrace
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
