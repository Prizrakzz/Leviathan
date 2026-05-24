from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[3]  # fallback to previous behaviour


PROJECT_ROOT: Path = _find_project_root()

def load_env() -> None:
    load_dotenv(PROJECT_ROOT / '.env')


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value

def load_yaml(path: str | Path) -> dict[str, Any]:
    full_path = Path(path)

    if not full_path.is_absolute():
        full_path = PROJECT_ROOT / full_path

    if not full_path.exists():
        raise FileNotFoundError(f"YAML config not found: {full_path}")

    with full_path.open("r", encoding = "utf-8") as file:
        data = yaml.safe_load(file)

    return data or {}
