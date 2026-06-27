"""Verify that a logged MLflow model artifact reproduces its replay sample."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.training.mlflow_replay import verify_mlflow_run_replay  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tracking-uri", default=None)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    result = verify_mlflow_run_replay(
        args.run_id,
        tracking_uri=args.tracking_uri,
        tolerance=args.tolerance,
    )
    payload = result.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if args.fail_on_error and not result.passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
