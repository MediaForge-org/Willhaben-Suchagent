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
. (Join-Path $PSScriptRoot "windows-path-utils.ps1")
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
    # Native messaging is a binary framing protocol (4-byte little-endian
    # length prefix + UTF-8 JSON). PowerShell's object pipeline and
    # "$var = external-command" capture both convert output through text
    # encoding, which corrupts arbitrary bytes. This section therefore never
    # pipes through the host process or captures its output as text - it
    # talks to the raw, redirected stdin/stdout streams directly via .NET
    # Process/Stream APIs, which is fully binary-safe under PowerShell 7.
    $env:WILLHABEN_API_PORT = "$port"
    # Agent is stopped by now; the host only needs to prove it speaks the
    # framed protocol and stamps protocolVersion - a transport error from the
    # (now-stopped) agent is an expected, well-formed "ok: false" response.
    $agentProcess2 = Start-Process -FilePath $agentExe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2
    try {
        $requestJson = '{"requestId":"1","request":{"type":"api.status"}}'
        $requestBytes = [System.Text.Encoding]::UTF8.GetBytes($requestJson)
        $requestFrame = [System.BitConverter]::GetBytes([uint32]$requestBytes.Length) + $requestBytes

        $startInfo = [System.Diagnostics.ProcessStartInfo]::new($hostExe)
        $startInfo.RedirectStandardInput = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.UseShellExecute = $false

        $hostProcess = [System.Diagnostics.Process]::new()
        $hostProcess.StartInfo = $startInfo
        $hostProcess.Start() | Out-Null

        $stdin = $hostProcess.StandardInput.BaseStream
        $stdin.Write($requestFrame, 0, $requestFrame.Length)
        $stdin.Flush()
        $hostProcess.StandardInput.Close()

        # Read exactly the 4-byte length prefix, then exactly that many JSON
        # bytes - never "read until EOF", so a subsequent stray byte on
        # stdout is still detectable as an assertion failure below.
        $stdout = $hostProcess.StandardOutput.BaseStream
        $lengthPrefix = New-Object byte[] 4
        $prefixRead = $stdout.Read($lengthPrefix, 0, 4)
        Assert-True ($prefixRead -eq 4) "Host wrote a 4-byte length prefix"
        $responseLength = [System.BitConverter]::ToUInt32($lengthPrefix, 0)

        $jsonBytes = New-Object byte[] $responseLength
        $totalRead = 0
        while ($totalRead -lt $responseLength) {
            $chunkRead = $stdout.Read($jsonBytes, $totalRead, $responseLength - $totalRead)
            if ($chunkRead -eq 0) { break }
            $totalRead += $chunkRead
        }
        Assert-True ($totalRead -eq $responseLength) "Host wrote the full JSON payload ($totalRead of $responseLength bytes)"

        # Exactly one framed message on stdout - no extra stray protocol
        # bytes/logging: one more byte-read attempt must hit EOF (0 bytes).
        $extraByte = New-Object byte[] 1
        $extraRead = $stdout.Read($extraByte, 0, 1)
        Assert-True ($extraRead -eq 0) "stdout contains exactly one framed message, nothing else"

        # stderr may contain log output - read it (also binary-safe) purely
        # so the process can exit cleanly; content is not asserted.
        $stderrText = $hostProcess.StandardError.ReadToEnd()
        $hostProcess.WaitForExit(5000) | Out-Null
        if ($stderrText) { Write-Host "Host stderr (log output, expected): $stderrText" }

        $response = [System.Text.Encoding]::UTF8.GetString($jsonBytes) | ConvertFrom-Json
        Assert-True ($response.protocolVersion -eq 1) "protocolVersion is 1 (was: $($response.protocolVersion))"
        Assert-True ($response.requestId -eq "1") "requestId echoed correctly"
        Assert-True ($null -ne $response.response) "Response body present"
    } finally {
        if ($agentProcess2 -and -not $agentProcess2.HasExited) {
            Stop-Process -Id $agentProcess2.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "=== 6: Native-messaging setup / registry (relocation-safe) ==="
    $registryKeyPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\at.willhaben_suchagent.bridge"

    # The release setup executable derives its own root deterministically
    # from where it physically sits on disk (parent of the runtime/ folder
    # containing it) - never from cwd, and never by trusting a possibly
    # shell-mangled --project-root argument (see run_setup.py's
    # _release_root()). So a real test of "relocation works" MUST invoke the
    # copy of the executable that actually lives at the path under test -
    # reusing a setup-exe handle captured from a different location would
    # not exercise the relocation logic at all.
    function Test-SetupPointsAtCurrentPath {
        param(
            [string]$ProjectRoot,
            [string]$InvokeFromDirectory = $null,
            [switch]$OmitProjectRootArgument
        )
        $currentSetupExe = Join-Path $ProjectRoot "runtime\willhaben-suchagent-setup.exe"
        Assert-True (Test-Path $currentSetupExe) "Setup executable present at $ProjectRoot"

        $previousLocation = Get-Location
        if ($InvokeFromDirectory) { Set-Location $InvokeFromDirectory }
        try {
            if ($OmitProjectRootArgument) {
                & $currentSetupExe install-windows | Out-Null
            } else {
                & $currentSetupExe install-windows --project-root $ProjectRoot | Out-Null
            }
        } finally {
            Set-Location $previousLocation
        }

        Assert-True (Test-Path $registryKeyPath) "Registry key exists after install"
        $manifestPath = (Get-ItemProperty -Path $registryKeyPath -Name "(default)").("(default)")
        $manifestContent = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $launcherContent = Get-Content $manifestContent.path -Raw

        # Always visible in the log (pass or fail) - makes a future
        # regression immediately diagnosable without re-running CI blind.
        Write-Host "Expected release root:     $ProjectRoot"
        Write-Host "Actual registry manifest path: $manifestPath"
        Write-Host "Actual manifest host path:     $($manifestContent.path)"
        Write-Host "Actual launcher content:       $launcherContent"

        Assert-True (Test-WindowsPathIsUnderRoot $manifestPath $ProjectRoot) "Registry value points inside current project root ($ProjectRoot)"
        Assert-True (Test-WindowsPathIsUnderRoot $manifestContent.path $ProjectRoot) "Manifest launcher path points inside current project root"
        Assert-True (Test-TextContainsWindowsPath $launcherContent $ProjectRoot) "Launcher wraps the bundled host executable at the current path"

        & $currentSetupExe uninstall-windows --project-root $ProjectRoot | Out-Null
        Assert-True (-not (Test-Path $registryKeyPath)) "Registry key removed after uninstall"
    }

    Test-SetupPointsAtCurrentPath -ProjectRoot $StageDir

    Write-Host "=== 7: Relocation with a path containing a space ==="
    $relocatedRoot = "C:\temp\Willhaben Test\Willhaben-Suchagent-1.0.0"
    New-Item -ItemType Directory -Force -Path (Split-Path $relocatedRoot -Parent) | Out-Null
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $relocatedRoot
    Copy-Item -Recurse -Path $StageDir -Destination $relocatedRoot

    # cwd is deliberately something else entirely, and --project-root is
    # deliberately omitted: the setup executable must still resolve its own
    # location correctly, proving relocation doesn't depend on either.
    Test-SetupPointsAtCurrentPath -ProjectRoot $relocatedRoot -InvokeFromDirectory $env:TEMP -OmitProjectRootArgument

    Write-Host "=== 8: Old build path must not leak into any generated artifact ==="
    $currentSetupExe = Join-Path $relocatedRoot "runtime\willhaben-suchagent-setup.exe"
    & $currentSetupExe install-windows --project-root $relocatedRoot | Out-Null
    $manifestPath = (Get-ItemProperty -Path $registryKeyPath -Name "(default)").("(default)")
    $manifestContent = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $launcherContent = Get-Content $manifestContent.path -Raw
    Assert-True (-not (Test-TextContainsWindowsPath $manifestPath $StageDir)) "Registry manifest path has no trace of the original build path"
    Assert-True (-not (Test-TextContainsWindowsPath $manifestContent.path $StageDir)) "Manifest host path has no trace of the original build path"
    Assert-True (-not (Test-TextContainsWindowsPath $launcherContent $StageDir)) "Launcher content has no trace of the original build path"
    & $currentSetupExe uninstall-windows --project-root $relocatedRoot | Out-Null

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
