"""Show gid candidates for the 3 missing bulletins."""
import json
from pathlib import Path

gids = json.loads(Path("data/conab/conab_joomla_gids.json").read_text())
missing = [(2022, 3), (2022, 4), (2019, 1)]
for y, l in missing:
    candidates = [e for e in gids if e["safra_year"] == y and e["levantamento"] == l]
    print(f"{l}o/{y}: {len(candidates)} gid(s)")
    for c in candidates:
        gid = c["gid_hash"]
        snap = c.get("wayback_snap_ts")
        print(f"  gid={gid}  snap_ts={snap}")
        # Check Wayback availability
        wb_url = f"https://web.archive.org/web/{snap}if_/https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{gid}"
        print(f"  wb_url={wb_url}")
