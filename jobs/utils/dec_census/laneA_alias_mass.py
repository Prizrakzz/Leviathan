import io, json, os, sys, collections, random
sys.path.insert(0, r"C:/Users/User/Desktop/Leviathan/src")
from leviathan.graphrag import evidence as ev, harvest as hv, extract as ex
S = r"C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad"

zero = [json.loads(l) for l in io.open(os.path.join(S, "laneA_zero_routed.jsonl"), "r", encoding="utf-8")]
summ = json.load(io.open(os.path.join(S, "laneA_route_summary.json"), "r", encoding="utf-8"))

# ── per-source dark rate ──
rows = []
for src, n in sorted(summ["src_all"].items(), key=lambda kv: -kv[1]):
    z = summ["src_zero"].get(src, 0)
    rows.append((src, n, z, round(100.0 * z / n, 1)))
print("%-28s %8s %8s %7s" % ("source", "props", "zero", "dark%"))
for r in rows:
    print("%-28s %8d %8d %6.1f%%" % r)
json.dump(rows, io.open(os.path.join(S, "laneA_source_dark.json"), "w", encoding="utf-8"), indent=1)

# ── single-word alias defects: mass in the zero-routed pile ──
AL = {"sugarcane -> raw_sugar/white_sugar": ["sugarcane", "sugar cane", "cane"],
      "cottonseed/lint -> cotton": ["cottonseed", "cotton seed", "lint", "ginning", "ginned"],
      "oranges/citrus -> orange_juice": ["oranges", "orange", "citrus", "frozen concentrated", "nfc"],
      "paddy/palay -> rice": ["paddy", "palay"],
      "sbm/soymeal -> soybean_meal": ["sbm", "soymeal", "soya meal", "soybean cake"],
      "sbo/soyoil -> soybean_oil": ["sbo", "soyoil", "soya oil", "degummed"],
      "chocolate/grindings -> cocoa": ["chocolate", "grindings", "cocoa butter", "cacao"],
      "durum -> wheat classes": ["durum"],
      "flour -> wheat classes": ["flour"],
      "pko/pkm/palm kernel -> palm_oil": ["palm kernel", "pko", "pkm"],
      "mustard -> rapeseed": ["mustard"],
      "compound feed / feed grain aggregate": ["compound feed", "feed grain", "feed grains", "coarse grain", "coarse grains"],
      "oilseed aggregate": ["oilseed", "oilseeds"],
      }
alias_out = {}
for k, terms in AL.items():
    m = hv.build_matcher(terms)
    idx = [i for i, p in enumerate(zero) if m._rx and m._rx.search(p["nf"])]
    hits = collections.Counter()
    for i in idx:
        for f in m._rx.findall(zero[i]["nf"]):
            hits[m._idx.get(f, f)] += 1
    rnd = random.Random(3)
    sm = [zero[i]["t"] for i in (idx[:1] + rnd.sample(idx, min(4, len(idx))))] if idx else []
    alias_out[k] = {"terms": terms, "zero_routed_props": len(idx), "hits": hits.most_common(6),
                    "samples": list(dict.fromkeys(sm))[:4]}
    print("%-42s zero=%6d  %s" % (k, len(idx), hits.most_common(4)))
json.dump(alias_out, io.open(os.path.join(S, "laneA_alias_mass.json"), "w", encoding="utf-8"), indent=1)

# ── the already-known livestock layer, for context only ──
LS = ["cattle", "hog", "hogs", "swine", "pig", "pigs", "poultry", "broiler", "broilers", "chicken", "beef",
      "pork", "egg", "eggs", "sow", "sows", "heifer", "slaughter", "feedlot", "milk", "dairy", "cheese",
      "butter", "whey", "turkey poults", "livestock", "meat and bone meal", "mbm", "layer flock"]
m = hv.build_matcher(LS)
ls_idx = [i for i, p in enumerate(zero) if m._rx and m._rx.search(p["nf"])]
print("KNOWN livestock/dairy/poultry mass in zero-routed: %d (%.2f%%)" % (len(ls_idx), 100.0 * len(ls_idx) / len(zero)))
json.dump({"n": len(ls_idx), "pct": round(100.0 * len(ls_idx) / len(zero), 2)},
          io.open(os.path.join(S, "laneA_known_livestock.json"), "w", encoding="utf-8"), indent=1)

# ── year distribution of the zero-routed mass ──
yr = collections.Counter((p.get("d") or "????")[:4] for p in zero)
print("years:", sorted(yr.items())[:3], "...", sorted(yr.items())[-3:])
json.dump(sorted(yr.items()), io.open(os.path.join(S, "laneA_zero_years.json"), "w", encoding="utf-8"), indent=1)
