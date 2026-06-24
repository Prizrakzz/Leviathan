"""Generate every managed Athena DDL from the authoritative dataset registry."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.catalog.ddl import write_registry_ddls  # noqa: E402
from leviathan.catalog.registry import load_dataset_registry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("sql/athena/ddl"),
    )
    args = parser.parse_args()
    registry = load_dataset_registry(args.registry)
    paths = write_registry_ddls(registry, args.output_dir)
    print(
        f"wrote {len(paths)} DDLs from registry {registry.content_sha256} "
        f"to {args.output_dir}"
    )


if __name__ == "__main__":
    main()
