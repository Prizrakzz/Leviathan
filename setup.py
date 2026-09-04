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
        # A-R9. Both of these resolve through registry.CONFIGS_SILVER_DIR, so in a wheel install
        # -- where that falls back to the bundled copy -- a file left out here does not raise: it
        # RESOLVES TO ABSENT, and both readers treat an absent file as "nothing declared". A
        # silently empty venue calendar puts the session floor back to the arithmetic that lost
        # the 08:00Z chain its gate, and a silently empty gap ledger un-excuses every declared
        # gap. No futures_eod leg runs from a wheel today (Batch runs from /app, where the tracked
        # tree is COPYed in), so this is a latent exposure being closed rather than a live bug --
        # and futures_gaps.yaml has carried it since it was written.
        for extra in ("venue_holidays.yaml", "futures_gaps.yaml"):
            if (src / extra).exists():
                shutil.copy2(src / extra, dst / extra)
        for p in sorted((src / "tables").glob("*.yaml")):
            shutil.copy2(p, dst / "tables" / p.name)
        super().run()


setup(cmdclass={"build_py": build_py_with_contract_configs})
