"""Wave-3 regression: the WAP Table 01 silver Batch task must ACCEPT ``--publish-mode``.

The retrofit defect: ``wap_silver_task._parse_args`` declared only --bucket / --aws-region /
--force-overwrite / --dry-run, so argparse fired FIRST and rejected the flag ::

    wap_silver_task.py: error: unrecognized arguments: --publish-mode shadow   (exit 2)

The publish guard reads the mode from ``sys.argv`` (threaded via ``publish_flat_silver(argv=...)``),
but the run never reached it -- argparse aborted the process. The minimal fix mirrors the proven
siblings (frankfurter_fx_task / noaa_iod_task): register ``--publish-mode`` (default None) so the flag
is accepted and passes through to the guard. This test locks that acceptance.

Pure/hermetic: no env, no S3, no network -- ``_parse_args()`` is driven directly over a patched argv.
"""
from __future__ import annotations

import sys

from jobs.batch import wap_silver_task as task


def test_argparse_accepts_publish_mode_shadow(monkeypatch):
    """The retrofit: ``--publish-mode shadow`` parses instead of exiting 2."""
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "shadow"])
    args = task._parse_args()
    assert args.publish_mode == "shadow"
    assert args.bucket == "leviathan-test"


def test_publish_mode_default_is_none(monkeypatch):
    """Absent --publish-mode -> None (the guard then applies its dry-run default)."""
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test"])
    args = task._parse_args()
    assert args.publish_mode is None


def test_publish_mode_coexists_with_existing_flags(monkeypatch):
    """The new flag does not disturb the pre-existing argparse surface."""
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--aws-region", "us-east-1",
                                      "--force-overwrite", "--dry-run",
                                      "--publish-mode", "canonical"])
    args = task._parse_args()
    assert args.publish_mode == "canonical"
    assert args.bucket == "leviathan-test"
    assert args.aws_region == "us-east-1"
    assert args.force_overwrite is True
    assert args.dry_run is True
