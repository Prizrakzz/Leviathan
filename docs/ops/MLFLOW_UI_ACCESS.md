# MLflow UI Access

MLflow runs on the private EC2 instance `leviathan-dev-mlflow-server`. The
browser URL works only while a local SSM port-forward tunnel is active.

Use:

```powershell
.\scripts\ops\start_mlflow_tunnel.ps1
```

Then open:

```text
http://127.0.0.1:5000
```

`localhost` usually works too, but `127.0.0.1` avoids Windows IPv6/name
resolution surprises.

## Health Checks

Check the local tunnel:

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health -UseBasicParsing
```

Expected response body:

```text
OK
```

If it fails, rerun:

```powershell
.\scripts\ops\start_mlflow_tunnel.ps1
```

## Why It Stops Opening

The common failure is the SSM tunnel, not the MLflow service. The tunnel can
drop when the laptop sleeps, the network changes, AWS credentials expire, or
Session Manager reaches its idle timeout.

Do not expose port 5000 publicly unless authentication and tighter network
controls are added first.

## Remote Service Check

If the tunnel restarts but the UI still does not open, verify the EC2 service:

```powershell
aws ssm send-command `
  --region us-east-1 `
  --instance-ids i-012f869a03d7247fa `
  --document-name AWS-RunShellScript `
  --parameters commands='["systemctl is-active mlflow", "curl -s -i http://localhost:5000/health"]'
```
