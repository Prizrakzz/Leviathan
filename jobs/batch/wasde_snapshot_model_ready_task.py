"""AWS Batch entrypoint for WASDE release-date snapshot model-ready builds."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jobs.utils.build_wasde_snapshot_model_ready_dataset import main  # noqa: E402


if __name__ == "__main__":
    main()
