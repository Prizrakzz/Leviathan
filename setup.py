"""Build shim: bundle the SILVER-F010 contract configs into the wheel.

The Glue Python Shell family installs leviathan as a wheel with no repo tree beside it, and
``leviathan.silver.registry`` needs ``configs/silver/{table_contract.schema.json, known_drift.yaml,
tables/*}`` -- the first-ever run of the retrofitted bronze_to_silver_faostat script died on
exactly that gap (2026-08-26). This hook copies those files into
``src/leviathan/silver/_contract_configs/`` at BUILD TIME (the in-tree copy is gitignored, so the
tracked ``configs/`` tree stays the single source of truth), and pyproject's package-data ships
them; registry.py falls back to the bundled copy only when the repo tree is absent. The wheel
preflight (the bake step) asserts the bundled copy is byte-identical to the tree before upload.
"""
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class build_py_with_contract_configs(build_py):
    def run(self):
        root = Path(__file__).resolve().parent
        src = root / "configs" / "silver"
        dst = root / "src" / "leviathan" / "silver" / "_contract_configs"
        if dst.exists():
            shutil.rmtree(dst)
        (dst / "tables").mkdir(parents=True)
        shutil.copy2(src / "table_contract.schema.json", dst / "table_contract.schema.json")
        shutil.copy2(src / "known_drift.yaml", dst / "known_drift.yaml")
        for p in sorted((src / "tables").glob("*.yaml")):
            shutil.copy2(p, dst / "tables" / p.name)
        super().run()


setup(cmdclass={"build_py": build_py_with_contract_configs})
