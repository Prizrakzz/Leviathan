param(
    [string]$InstanceId = "i-012f869a03d7247fa",
    [string]$Region = "us-east-1",
    [int]$LocalPort = 5000,
    [int]$RemotePort = 5000
)

$ErrorActionPreference = "Stop"

$existing = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Port $LocalPort is already listening. Health check:"
    try {
        Invoke-WebRequest "http://127.0.0.1:$LocalPort/health" -UseBasicParsing -TimeoutSec 5 |
            Select-Object StatusCode, Content
    } catch {
        Write-Host "Port is occupied, but MLflow health check failed: $($_.Exception.Message)"
    }
    exit 0
}

Write-Host "Starting MLflow SSM tunnel: http://127.0.0.1:$LocalPort"
aws ssm start-session `
    --region $Region `
    --target $InstanceId `
    --document-name AWS-StartPortForwardingSession `
    --parameters "portNumber=$RemotePort,localPortNumber=$LocalPort"
