"""Build a Python .zip file for the leviathan package.

AWS Glue Python Shell 3.0 supports only .zip (not .egg) for --extra-py-files.
The zip must have the package directory at the archive root so that
zipimport can find it: leviathan/__init__.py, leviathan/common/..., etc.

Run from the project root:
    python scripts/build_glue_egg.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

SRC = Path("src/leviathan")
ZIP_NAME = "leviathan.zip"


def build_zip(src: Path, zip_name: str) -> Path:
    out = Path(zip_name)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if (
                p.is_file()
                and "__pycache__" not in p.parts
                and p.suffix != ".pyc"
            ):
                # Forward-slash paths required; package at archive root.
                arcname = "leviathan/" + p.relative_to(src).as_posix()
                zf.write(str(p), arcname)

    entries = zf.namelist()
    print(f"Created {out}  ({len(entries)} files)")
    return out


if __name__ == "__main__":
    build_zip(SRC, ZIP_NAME)
