"""LANE A pass 2 -- cheap, transparent clustering of the ZERO-ROUTED props.

Method (no LLM, fully reproducible):
  1. tokenize the production-normalized text (ex._normalize output) into alpha tokens
  2. n-grams 1..3, dropping any n-gram that starts or ends on a stopword; drop pure-number tokens
  3. document frequency per n-gram over the zero-routed corpus
  4. GREEDY COVER: repeatedly take the highest-scoring uncovered n-gram (score = remaining df, mild
     length bonus so a real phrase beats its own head word), claim every prop still uncovered that
     contains it, emit that as one cluster. Ranked by prop mass by construction.
  5. per cluster: count, top co-occurring terms, source mix, document-slug mix, sample props.
"""
import io, json, os, random, re, collections

S = r"C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad"

STOP = set("""a an the and or but if then than that this these those of in on at to for from by with without
into over under about as is are was were be been being it its their his her they them we our you your not no
which who whom whose where when while during after before between within per each both all any some most more
less least other others such same own so very can could may might will would shall should must have has had
also only just too much many few one two three four five six seven eight nine ten first second third new
including included include includes due because however although though up down out off again further once
here there why how what said says say reported reports report according total year years month months week
weeks day days percent pct""".split())

t0 = os.path.getsize(os.path.join(S, "laneA_zero_routed.jsonl"))
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
print("distinct n-grams:", len(df))

# prune the tail hard: an n-gram under 40 props can never head a cluster we would report
df = collections.Counter({g: c for g, c in df.items() if c >= 40})
print("n-grams with df>=40:", len(df))

inv = collections.defaultdict(list)          # ngram -> prop indices
for i, g in enumerate(grams):
    for x in (g & df.keys()):
        inv[x].append(i)

covered = [False] * len(props)
clusters = []
remaining = len(props)
while len(clusters) < 140 and remaining > len(props) * 0.002:
    best, best_score, best_members = None, 0, None
    for g, idxs in inv.items():
        n = sum(1 for i in idxs if not covered[i])
        if n < 40:
            continue
        score = n * (1.0 + 0.18 * (g.count(" ")))
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
    co = collections.Counter()
    srcs = collections.Counter()
    docs = collections.Counter()
    for i in mem:
        co.update(grams[i])
        srcs[props[i].get("src") or "?"] += 1
        sk = props[i].get("s") or ""
        m = re.search(r"document=([^/]+)", sk)
        if m:
            slug = re.sub(r"[-_ ]?\d.*$", "", m.group(1))[:60]
            docs[slug or m.group(1)[:60]] += 1
    top = [g for g, n in co.most_common(40) if g != c["seed"]][:14]
    samples = [props[i]["t"] for i in (mem[:2] + rnd.sample(mem, min(6, len(mem))))]
    seen, sm = set(), []
    for s in samples:
        if s not in seen:
            seen.add(s)
            sm.append(s)
    out.append({"seed": c["seed"], "n": c["n"], "top_terms": top,
                "sources": srcs.most_common(6), "doc_slugs": docs.most_common(5),
                "samples": sm[:6]})

json.dump(out, io.open(os.path.join(S, "laneA_clusters_raw.json"), "w", encoding="utf-8"), indent=1)

# residual sample so nothing hides in the uncovered tail
resid = [i for i, c in enumerate(covered) if not c]
json.dump([props[i]["t"] for i in rnd.sample(resid, min(200, len(resid)))],
          io.open(os.path.join(S, "laneA_residual_sample.json"), "w", encoding="utf-8"), indent=1)
print("residual props:", len(resid))

with io.open(os.path.join(S, "laneA_clusters_raw.txt"), "w", encoding="utf-8") as f:
    for k, c in enumerate(out):
        f.write("[%d] SEED=%s  N=%d\n" % (k, c["seed"], c["n"]))
        f.write("    terms: %s\n" % ", ".join(c["top_terms"]))
        f.write("    src: %s\n" % c["sources"])
        f.write("    docs: %s\n" % c["doc_slugs"])
        for s in c["samples"][:4]:
            f.write("    | %s\n" % s[:230])
        f.write("\n")
print("wrote laneA_clusters_raw.{json,txt}")
