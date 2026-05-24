# PowerShell 脚本测试 OpenClaw API
Write-Host "=" * 60
Write-Host "Testing OpenClaw APIs"
Write-Host "=" * 60

$base = "http://127.0.0.1:18789"

$paths = @(
    "/health",
    "/",
    "/api"
)

foreach ($path in $paths) {
    $url = $base + $path
    try {
        Write-Host "`nGET $url"
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec 5
        Write-Host "  Status: $($resp.StatusCode)"
        Write-Host "  Response: $($resp.Content.Substring(0, [Math]::Min(300, $resp.Content.Length)))"
    } catch {
        Write-Host "  Error: $_"
    }
}

Write-Host "`n`nTesting POST endpoints"
Write-Host "=" * 60
$postTests = @(
    @{ path="/run-task"; body='{"task_id": "test1", "task_content": "test"}' },
    @{ path="/api/task"; body='{"task": "test", "task_type": "coding"}' }
)

foreach ($test in $postTests) {
    $url = $base + $test.path
    try {
        Write-Host "`nPOST $url"
        Write-Host "  Body: $($test.body)"
        $resp = Invoke-WebRequest -Uri $url -Method Post -Body $test.body -ContentType "application/json" -TimeoutSec 10
        Write-Host "  Status: $($resp.StatusCode)"
        Write-Host "  Response: $($resp.Content.Substring(0, [Math]::Min(400, $resp.Content.Length)))"
    } catch {
        Write-Host "  Error: $($_.Exception.Message)"
        if ($_.Exception.Response) {
            Write-Host "  Status Code: $($_.Exception.Response.StatusCode.value__)"
        }
    }
}
