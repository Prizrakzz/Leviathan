"""Deprecated entrypoint for Athena catalog deployment.

Use the reviewed registry-driven workflow under ``scripts/catalog``.
"""
from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "jobs/run_athena_ddl.py is retired; use scripts/catalog/plan_catalog.py "
        "and scripts/catalog/apply_catalog.py"
    )


if __name__ == "__main__":
    main()
