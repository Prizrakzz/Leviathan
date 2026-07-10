"""Small SSM Run Command wrapper used by ML platform operations."""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import boto3

TERMINAL_STATUSES = {"Success", "Failed", "Cancelled", "TimedOut", "Cancelling"}


def encoded_python_command(script: str, payload: dict[str, Any]) -> str:
    """Build a shell command that executes Python without fragile shell quoting."""
    script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    return (
        "tmp_script=$(mktemp /tmp/leviathan-ops-XXXXXX.py); "
        f"printf '%s' '{script_b64}' | base64 -d > \"$tmp_script\"; "
        f"python3 \"$tmp_script\" '{payload_b64}'; "
        "status=$?; rm -f \"$tmp_script\"; exit $status"
    )


def run_ssm_command(
    *,
    instance_id: str,
    command: str,
    aws_region: str,
    timeout_seconds: int = 300,
    poll_seconds: float = 2.0,
    ssm_client=None,
) -> dict[str, Any]:
    """Run a command through SSM and return its terminal invocation response."""
    client = ssm_client or boto3.client("ssm", region_name=aws_region)
    response = client.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=timeout_seconds,
    )
    command_id = response["Command"]["CommandId"]
    deadline = time.monotonic() + timeout_seconds + 30
    while time.monotonic() < deadline:
        try:
            result = client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
        except client.exceptions.InvocationDoesNotExist:
            time.sleep(poll_seconds)
            continue
        if result["Status"] in TERMINAL_STATUSES:
            if result["Status"] != "Success":
                raise RuntimeError(
                    f"SSM command {command_id} ended with {result['Status']}: "
                    f"{result.get('StandardErrorContent', '').strip()}"
                )
            return result
        time.sleep(poll_seconds)
    raise TimeoutError(f"SSM command {command_id} did not finish within timeout")


def parse_json_output(result: dict[str, Any]) -> dict[str, Any]:
    """Parse the last non-empty stdout line as JSON."""
    lines = [
        line.strip()
        for line in result.get("StandardOutputContent", "").splitlines()
        if line.strip()
    ]
    if not lines:
        raise ValueError("SSM command returned no stdout")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"SSM command did not end with JSON: {lines[-1]!r}") from exc

