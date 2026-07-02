"""AWS Batch entrypoint for the Phase 2 WASDE snapshot feature-density audit."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jobs.utils.audit_wasde_snapshot_feature_density import main  # noqa: E402


if __name__ == "__main__":
    main()
