"""Best-effort STS caller-identity resolver shared across the batch-task family (DRY).

WHY THIS EXISTS
---------------
Roughly seventeen ``jobs/batch/*.py`` tasks plus
``jobs/batch/_sb_producer_publish.publish_flat_silver`` and
``leviathan.silver.flat_producer`` each re-rolled the identical best-effort idiom: resolve the
canonical publish target's ``(account_id, role_arn)`` via ``sts.get_caller_identity()``, falling
back to empty strings when no live credentials are available. Empty identity is deliberate --
:func:`leviathan.common.publish_guard.check_environment` then FAILS CLOSED on the canonical path,
while dry-run / shadow (which never reach that check) stay fully offline. This is that single
implementation so no task re-implements it.

``boto3`` is imported lazily so importing this module never pulls it, which keeps PIT-safe unit
runs and readiness identities AWS-free. Tests that need a deterministic identity monkeypatch the
CALLER's own seam (``flat_producer._resolve_caller_identity`` or a task's ``_caller_identity``),
which is why those thin wrappers are preserved rather than removed.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_caller_identity(aws_region: str | None = None) -> tuple[str, str]:
    """Best-effort live STS identity for a canonical publish target: ``(account_id, role_arn)``.

    Returns empty strings on ANY failure (missing credentials, network, throttle). An empty
    identity makes the publish guard's :func:`~leviathan.common.publish_guard.check_environment`
    fail closed on the canonical path; dry-run / shadow never reach it and stay authorized offline.

    ``aws_region`` pins the STS regional endpoint when supplied (``None`` uses boto3's default
    region resolution); STS is global, so it never changes the resolved identity -- it only
    selects which endpoint is contacted, preserving each caller's prior behavior.
    """
    try:
        import boto3

        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- best-effort; empty identity => guard fails closed
        logger.debug("STS identity unavailable (%s); using empty target (dry-run/shadow only)", exc)
        return "", ""
