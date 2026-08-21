"""LANE A pass 3 -- SUBJECT-FIRST clustering of the zero-routed props + config cross-check.

Pass 2's greedy cover seeded on the balance-sheet frame ('production', 'tons', 'exports'), which names the
SHAPE of a GAIN sentence, not its subject. This pass adds a FRAME + GEOGRAPHY stoplist so the seeds land on
subject nouns, and cross-checks every seed against the WHOLE config vocabulary (24 node match_forms + 113
driver-slice terms + entity_vocabulary aliases/nodes + causal/*.yaml driver ids/names/aliases + policy_levers
+ regions/geography) so a cluster can be graded (a) missing node / (b) missing vocabulary / (c) out of scope /
(d) numbers-lane.
"""
import io, json, os, random, re, sys, collections, yaml

sys.path.insert(0, r"C:/Users/User/Desktop/Leviathan/src")
from leviathan.graphrag import evidence as ev, harvest as hv, extract as ex

S = r"C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad"
CFG = ex._CFG

# ── the whole config vocabulary, one matcher ─────────────────────────────────────────
forms = []
for n in ev.all_nodes():
    forms += ev.match_forms(n)
for d, spec in ev.driver_specs().items():
    forms += [str(t) for t in (spec.get("terms") or [])]
    forms.append(d.replace("_", " "))
v = ex._vocab()
for k in ("nodes", "edges", "arbitration"):
    x = v.get(k)
    if isinstance(x, dict):
        for kk, vv in x.items():
            forms.append(str(kk))
            if isinstance(vv, list):
                forms += [str(i) for i in vv]
    elif isinstance(x, list):
        forms += [str(i) for i in x]
for k, al in (v.get("aliases") or {}).items():
    forms.append(str(k))
    forms += [str(a) for a in (al or [])]
hier = yaml.safe_load((CFG / "commodity_hierarchy.yaml").read_text(encoding="utf-8")) or {}
for k in ("contracts", "groups", "complexes", "context_commodities"):
    x = hier.get(k)
    if isinstance(x, dict):
        for kk, vv in x.items():
            forms.append(str(kk).replace("_", " "))
            if isinstance(vv, dict):
                forms += [str(i).replace("_", " ") for i in vv.get("members", []) or []]
                forms.append(str(vv.get("node") or "").replace("_", " "))
            elif isinstance(vv, list):
                forms += [str(i).replace("_", " ") for i in vv]
    elif isinstance(x, list):
        forms += [str(i).replace("_", " ") for i in x]
pl = yaml.safe_load((CFG / "policy_levers.yaml").read_text(encoding="utf-8")) or {}
_lv = pl.get("levers") or []
if isinstance(_lv, dict):
    _lv = [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in _lv.items()]
for lev in _lv:
    if isinstance(lev, str):
        forms.append(lev.replace("_", " "))
        continue
    for kk in ("id", "name", "lever", "label"):
        if lev.get(kk):
            forms.append(str(lev[kk]).replace("_", " "))
    for kk in ("terms", "aliases", "keywords", "patterns"):
        forms += [str(t) for t in (lev.get(kk) or [])]
from leviathan.causal import schema as cs
for p in sorted((CFG / "causal").glob("*.yaml")):
    try:
        c = cs.load(p)
    except Exception:
        continue
    forms += [str(a) for a in getattr(c, "aliases", []) or []]
    for d in getattr(c, "drivers", []) or []:
        forms.append(str(getattr(d, "id", "")).replace("_", " "))
        forms.append(str(getattr(d, "name", "") or ""))
        forms += [str(a) for a in (getattr(d, "aliases", []) or [])]
for f in ("regions.yaml", "geography.yaml"):
    p = CFG / f
    if not p.exists():
        continue
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    def walk(o):
        if isinstance(o, dict):
            for k, vv in o.items():
                forms.append(str(k).replace("_", " "))
                walk(vv)
        elif isinstance(o, list):
            for i in o:
                walk(i)
        elif isinstance(o, str):
            forms.append(o)
    walk(raw)
forms = [f for f in forms if f and isinstance(f, str)]
CFG_M = hv.build_matcher(forms)
print("config vocabulary forms: %d raw, %d normalized" % (len(forms), len(CFG_M._idx)))
json.dump(sorted(CFG_M._idx.keys()), io.open(os.path.join(S, "laneA_config_forms.json"), "w", encoding="utf-8"), indent=0)

# geography stoplist: every region/geography surface form, single tokens only
GEO = set()
for f in ("regions.yaml", "geography.yaml"):
    p = CFG / f
    if p.exists():
        raw = p.read_text(encoding="utf-8")
        for w in re.findall(r"[A-Za-z][A-Za-z'\- ]+", raw):
            for t in re.findall(r"[a-z]+", ex._normalize(w)):
                if len(t) > 2:
                    GEO.add(t)
EXTRA_GEO = set("""ukraine ukrainian russia russian china chinese india indian brazil brazilian argentina argentine
mexico mexican canada canadian australia australian thailand thai indonesia indonesian vietnam vietnamese
philippines philippine malaysia malaysian japan japanese turkey turkish egypt egyptian pakistan pakistani
colombia colombian peru peruvian paraguay paraguayan uruguay chile chilean bolivia ecuador ecuadorian
france french germany german spain spanish italy italian poland polish romania romanian hungary bulgaria
netherlands belgium portugal greece sweden denmark finland norway ireland britain england scotland
korea korean taiwan singapore bangladesh burma myanmar cambodia laos nepal lanka srilanka
nigeria nigerian ghana ghanaian ivory kenya ethiopia tanzania uganda zambia zimbabwe mozambique malawi
morocco algeria tunisia libya sudan senegal cameroon angola congo
israel jordan lebanon syria iraq iran saudi arabia emirates kuwait qatar oman yemen
kazakhstan uzbekistan azerbaijan georgia armenia belarus moldova serbia croatia slovakia czech austria swiss
guatemala honduras nicaragua salvador panama costa rica cuba dominican haiti jamaica venezuela
states united america american europe european african asia asian world global domestic international
moscow kiev kyiv beijing delhi jakarta manila hanoi bangkok ottawa canberra brasilia buenos aires
paulo minas gerais parana catarina grande rio janeiro mato grosso goias bahia
sindh punjab luzon mindanao visayas nsw wales queensland victoria tasmania alberta saskatchewan manitoba
ontario quebec texas kansas iowa illinois nebraska california florida dakota missouri ohio indiana
michoacan colima veracruz sinaloa sonora jalisco chihuahua tamaulipas
south north east west southern northern eastern western central region regions country countries state
province provinces city area areas district local national""".split())
GEO |= EXTRA_GEO

FRAME = set("""production produced produce produces producing tons ton tonnes metric mmt tmt thousand million
billion bushels bushel hectares hectare acres acre kilograms kilogram kilos kilo pounds bales bags liters
litres exports export exported exporting exporter exporters imports import imported importing importer
importers consumption consume consumed consuming use used uses using area planted harvested harvest
harvesting yield yields stocks stock supply supplies demand price prices priced cost costs value values
estimate estimated estimates forecast forecasts forecasted projection projections projected revised revision
increase increased increases increasing decrease decreased decline declined declining higher lower high low
rise rose risen fall fell fallen growth grew grow expected expects expect anticipated market marketing year
years season seasonal crop crops total average marketing year beginning previous compared compare data
official usda post report reported reports level levels number numbers rate rates share percent share
mmt tmt approximately estimated volume volumes quantity quantities amount amounts remain remains remained
continue continues continued reach reached record ending beginning current recent last next prior
january february march april may june july august september october november december
first second third fourth quarter half period time times week weeks month months day days annual annually
according based likely due significant significantly slightly relatively strong weak good poor better worse
large larger small smaller major minor main primary additional overall respectively including
sector industry sectors industries company companies firms business businesses government governments
million metric tons thousand metric tons""".split())

STOP = GEO | FRAME | set("""a an the and or but if then than that this these those of in on at to for from by
with without into over under about as is are was were be been being it its their his her they them we our
you your not no which who whom whose where when while during after before between within per each both all
any some most more less least other others such same own so very can could may might will would shall should
must have has had also only just too much many few one two three four five six seven eight nine ten new
including included include includes due because however although though up down out off again further once
here there why how what said says say reported reports report according total percent pct mln thou usd usda
fas gain mid end early late still yet even ever never make made makes making take taken takes put set
part parts within toward towards through across around above below near close far since until upon
non pre post inter intra multi""".split())

props = []
with io.open(os.path.join(S, "laneA_zero_routed.jsonl"), "r", encoding="utf-8") as f:
    for line in f:
        props.append(json.loads(line))
print("zero-routed props:", len(props))

TOK = re.compile(r"[a-z]+")

def ngrams(nf):
    toks = [t for t in TOK.findall(nf) if len(t) > 2]
    out = set()
    for i, t in enumerate(toks):
        if t not in STOP:
            out.add(t)
        for n in (2, 3):
            if i + n <= len(toks):
                g = toks[i:i + n]
                if g[0] in STOP or g[-1] in STOP:
                    continue
                out.add(" ".join(g))
    return out

grams = []
df = collections.Counter()
for p in props:
    g = ngrams(p["nf"])
    grams.append(g)
    df.update(g)
df = collections.Counter({g: c for g, c in df.items() if c >= 30})
print("subject n-grams df>=30:", len(df))
inv = collections.defaultdict(list)
for i, g in enumerate(grams):
    for x in (g & df.keys()):
        inv[x].append(i)

covered = [False] * len(props)
clusters = []
remaining = len(props)
while len(clusters) < 220 and remaining > len(props) * 0.02:
    best, best_score, best_members = None, 0, None
    for g, idxs in inv.items():
        n = sum(1 for i in idxs if not covered[i])
        if n < 30:
            continue
        score = n * (1.0 + 0.22 * (g.count(" ")))
        if score > best_score:
            best, best_score, best_members = g, score, [i for i in idxs if not covered[i]]
    if not best:
        break
    for i in best_members:
        covered[i] = True
    remaining -= len(best_members)
    clusters.append({"seed": best, "n": len(best_members), "members": best_members})
    del inv[best]
print("clusters:", len(clusters), "covered:", len(props) - remaining, "residual:", remaining)

rnd = random.Random(11)
out = []
for c in clusters:
    mem = c["members"]
    co, srcs, docs, yrs = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for i in mem:
        co.update(grams[i])
        srcs[props[i].get("src") or "?"] += 1
        yrs[(props[i].get("d") or "????")[:4]] += 1
        m = re.search(r"document=([^/]+)", props[i].get("s") or "")
        if m:
            docs[re.sub(r"[-_ ]?\d.*$", "", m.group(1))[:55] or m.group(1)[:55]] += 1
    top = [g for g, n in co.most_common(45) if g != c["seed"]][:16]
    idxs = mem[:2] + rnd.sample(mem, min(8, len(mem)))
    seen, sm = set(), []
    for i in idxs:
        t = props[i]["t"]
        if t not in seen:
            seen.add(t)
            sm.append({"t": t, "src": props[i].get("src"), "d": props[i].get("d"), "s": props[i].get("s")})
    out.append({"seed": c["seed"], "n": c["n"],
                "config_fires_on_seed": CFG_M.findall(c["seed"]),
                "top_terms": [{"term": t, "config_hit": CFG_M.findall(t)} for t in top],
                "sources": srcs.most_common(6), "doc_slugs": docs.most_common(4),
                "years": sorted(yrs.items())[:1] + sorted(yrs.items())[-1:],
                "samples": sm[:6]})

json.dump(out, io.open(os.path.join(S, "laneA_clusters2.json"), "w", encoding="utf-8"), indent=1)
resid = [i for i, c in enumerate(covered) if not c]
json.dump([{"t": props[i]["t"], "src": props[i].get("src")} for i in rnd.sample(resid, min(300, len(resid)))],
          io.open(os.path.join(S, "laneA_residual2.json"), "w", encoding="utf-8"), indent=1)

with io.open(os.path.join(S, "laneA_clusters2.txt"), "w", encoding="utf-8") as f:
    for k, c in enumerate(out):
        f.write("[%d] SEED=%s  N=%d  CFGHIT=%s\n" % (k, c["seed"], c["n"], c["config_fires_on_seed"]))
        f.write("    terms: %s\n" % ", ".join("%s%s" % (t["term"], "*" if t["config_hit"] else "") for t in c["top_terms"]))
        f.write("    src: %s\n" % [s for s in c["sources"][:4]])
        for s in c["samples"][:4]:
            f.write("    | %s\n" % s["t"][:220])
        f.write("\n")
print("wrote laneA_clusters2.{json,txt}; residual", len(resid))
