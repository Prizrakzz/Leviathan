"""LANE A pass 4 -- named-family census over the zero-routed mass + config cross-check + alias probes."""
import io, json, os, re, sys, random, collections

sys.path.insert(0, r"C:/Users/User/Desktop/Leviathan/src")
from leviathan.graphrag import evidence as ev, harvest as hv, extract as ex

S = r"C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad"

CFG_FORMS = json.load(io.open(os.path.join(S, "laneA_config_forms.json"), "r", encoding="utf-8"))
CFG_M = hv.build_matcher(CFG_FORMS)

zero = []
with io.open(os.path.join(S, "laneA_zero_routed.jsonl"), "r", encoding="utf-8") as f:
    for line in f:
        zero.append(json.loads(line))
allp = []
with io.open(os.path.join(S, "chunk_cache_props.jsonl"), "r", encoding="utf-8") as f:
    for line in f:
        allp.append(json.loads(line))
ALL_NF = None

FAM = {
 "F01_peanut_groundnut": ["peanut", "peanuts", "groundnut", "groundnuts"],
 "F02_cottonseed": ["cottonseed", "cotton seed", "cottonseed oil", "cottonseed meal"],
 "F03_coconut_copra": ["copra", "coconut", "coconuts", "cno", "coconut oil", "desiccated coconut", "copra meal"],
 "F04_palm_kernel": ["palm kernel", "pko", "pkm", "palm kernel oil", "palm kernel meal", "oleochemical", "oleochemicals"],
 "F05_sesame_safflower_camellia_flax": ["sesame", "safflower", "camellia", "flaxseed", "linseed", "castor", "niger seed", "mustard seed", "tea seed oil"],
 "F06_olive_oil": ["olive", "olives", "olive oil", "extra virgin", "evoo", "pomace"],
 "F07_vegoil_aggregate": ["vegetable oil", "vegetable oils", "edible oil", "edible oils", "fats and oils", "oils and fats", "oilmeal", "oilmeals", "oil meals", "cooking oil", "veg oil"],
 "F08_minor_cereals": ["rye", "oats", "oat", "millet", "durum", "triticale", "buckwheat", "sorghum grain", "fonio", "quinoa"],
 "F09_pulses": ["pulses", "pulse", "lentil", "lentils", "chickpea", "chickpeas", "garbanzo", "garbanzos", "mung bean", "mung beans", "dry beans", "dry bean", "pigeon pea", "pigeon peas", "kabuli", "lupines", "cowpea", "black gram", "urad", "tur dal"],
 "F10_fresh_citrus": ["fresh oranges", "navel", "grapefruit", "pomelo", "lemon", "lemons", "lime", "limes", "tangerine", "tangerines", "mandarin", "mandarins", "clementine", "satsuma", "fresh fruit market", "citrus fresh"],
 "F11_fx_producer_currencies": ["exchange rate", "foreign exchange", "devaluation", "devalued", "peso", "pesos", "baht", "lira", "hryvnia", "ruble", "rouble", "zloty", "forint", "australian dollar", "canadian dollar", "new zealand dollar", "rand", "yuan", "renminbi", "rmb", "euro exchange", "dong", "taka", "naira", "birr", "shilling", "colombian peso", "sol"],
 "F12_macro_income_urbanization": ["gross domestic product", "gdp", "per capita consumption", "per capita expenditure", "urban residents", "urbanization", "disposable income", "middle class", "remittances", "tourism", "tourists", "restaurant sales", "food service", "foodservice", "catering", "bakery revenue", "consumer price index", "cpi", "economic growth", "recession", "unemployment"],
 "F13_processing_capacity": ["crushing capacity", "crush capacity", "milling capacity", "storage capacity", "crushing facilities", "crushing plant", "crush plant", "refining capacity", "refinery capacity", "installed capacity", "capacity utilization", "idle capacity", "silos", "grain elevator", "warehouse capacity"],
 "F14_inland_logistics": ["railway", "rail transport", "truck", "trucking", "highway", "inland transport", "transportation system", "port capacity", "port infrastructure", "loading rate", "throughput", "barge", "terminal", "cargo handling", "grain handling", "drying capacity"],
 "F15_flour_milling_bread": ["flour", "flour mill", "flour mills", "bread", "baladi", "pasta", "semolina", "bulgur", "noodle", "noodles", "bakery", "biscuit", "wheat milling", "milling industry", "extraction rate"],
 "F16_sweeteners_hfcs": ["hfcs", "high fructose", "fructose syrup", "glucose syrup", "isoglucose", "molasses", "panela", "gur", "jaggery", "sweetener", "sweeteners", "artificial sweetener", "stevia", "beverage industry"],
 "F17_opec_energy_supply": ["opec", "opec+", "barrels per day", "crude inventories", "oecd inventories", "refinery", "gasoline demand", "gasoline blending", "fuel subsidy", "pump price"],
 "F18_biotech_seed_phyto": ["biotech", "genetically modified", "genetically engineered", "gmo", "gm event", "bollgard", "seed variety", "hybrid seed", "plant protection", "phytosanitary", "quarantine", "pest risk", "import protocol", "market access protocol", "approval of biotech"],
 "F19_trade_agreements": ["free trade agreement", "fta", "cptpp", "tpp", "rcep", "asean", "cepa", "association agreement", "customs union", "accession", "preferential access", "duty free access", "trade negotiations", "trade deal"],
 "F20_producer_support_nonus": ["proagro", "sagarpa", "aserca", "plano safra", "minimum support price", "procurement price", "state procurement", "mortgage scheme", "paddy pledging", "tmo", "turkish grain board", "bulog", "nafed", "conab minimum price", "support program", "farm credit", "credit line", "gsm-102", "gsm 102", "public stockholding", "buffer stock"],
 "F21_elections_political": ["election", "elections", "presidential election", "new government", "coup", "political crisis", "president signed", "congress approved", "parliament approved", "referendum", "cabinet reshuffle"],
 "F22_water_irrigation": ["irrigation", "irrigated", "reservoir", "reservoirs", "dam", "water availability", "water allocation", "water rights", "aquifer", "groundwater", "canal water", "water storage"],
 "F23_labor_strike": ["strike", "strikes", "labor dispute", "union", "protest", "roadblock", "blockade", "worker shortage", "labour shortage", "labor shortage", "truckers"],
 "F24_quant_weather_obs": ["rainfall", "precipitation", "millimeters", "temperature", "temperatures", "degrees celsius", "soil moisture", "normal rainfall", "above normal", "below normal", "cumulative rainfall", "weather conditions"],
 "F25_crop_progress": ["sowing", "planting progress", "planting pace", "seeded", "emergence", "flowering", "vegetative", "abandonment", "replanting", "harvest progress", "harvest delay", "digging"],
 "F26_aquafeed": ["aquaculture", "shrimp", "catfish", "farmed fish", "fish feed", "aquafeed", "tilapia", "pangasius", "hatchery", "seafood"],
 "F27_textile_midchain": ["power loom", "power looms", "handloom", "handlooms", "hosiery", "weaving", "spinning mill", "man-made fiber", "manmade fiber", "chemical fiber", "synthetic fiber", "viscose", "jute", "kenaf", "ginning", "ginners"],
 "F28_food_security_pds": ["food security", "public distribution", "ration", "subsidized bread", "food subsidy", "safety net", "school feeding", "wfp", "humanitarian", "refugees"],
 "F29_standards_ntm": ["fortification", "labeling", "food safety", "standards", "aqsiq", "maximum residue", "mrl", "certification", "traceability", "halal", "registration requirement", "value added tax", "vat", "excise tax"],
 "F30_carbon_climate_policy": ["carbon tax", "carbon price", "greenhouse gas", "emissions", "deforestation", "sustainability certification", "carbon credit", "net zero", "land use change"],
 "F31_nonag_wbcmo": ["coal", "steel", "gold", "silver", "tin", "copper price", "bauxite", "logs", "sawnwood", "timber", "plywood", "tobacco", "tea", "bananas", "wool", "phosphate rock", "iron ore"],
 "F32_hs_codes_marketing_year": ["hs code", "tariff code", "code had", "oct sept", "apr mar", "jan dec", "market year beginning"],
 "F33_local_crop_names": ["paddy", "palay", "milho", "trigo", "maiz", "soja", "colza", "cebada", "arroz", "azucar", "cana", "safra", "zafra", "kharif", "rabi", "safrinha"],
}

def count(term_list, corpus):
    m = hv.build_matcher(term_list)
    n = 0
    hits = collections.Counter()
    idx = []
    for i, p in enumerate(corpus):
        nf = p.get("nf") or ex._normalize(p["t"])
        if m._rx and m._rx.search(nf):
            n += 1
            idx.append(i)
            for f in m._rx.findall(nf):
                hits[m._idx.get(f, f)] += 1
    return n, hits, idx

rnd = random.Random(5)
out = {}
for fam, terms in FAM.items():
    nz, hz, idz = count(terms, zero)
    na, ha, _ = count(terms, allp)
    cfg = {t: CFG_M.findall(t) for t in terms}
    unrep = [t for t, h in cfg.items() if not h]
    srcs = collections.Counter(zero[i].get("src") or "?" for i in idz)
    samples = [{"t": zero[i]["t"], "src": zero[i].get("src"), "d": zero[i].get("d"),
                "s": zero[i].get("s")} for i in (idz[:1] + rnd.sample(idz, min(6, len(idz))))] if idz else []
    seen, sm = set(), []
    for x in samples:
        if x["t"] not in seen:
            seen.add(x["t"]); sm.append(x)
    out[fam] = {"terms": terms, "zero_routed_props": nz, "all_props_mentioning": na,
                "pct_of_zero": round(100.0 * nz / len(zero), 2),
                "share_of_mentions_that_zero_route": round(100.0 * nz / na, 1) if na else None,
                "term_hits_in_zero": hz.most_common(18),
                "config_forms_firing": {t: v for t, v in cfg.items() if v},
                "terms_with_no_config_form": unrep,
                "sources": srcs.most_common(6), "samples": sm[:5]}
    print("%-34s zero=%6d  (%.2f%% of zero)  corpus_mentions=%6d  zero_share=%s%%  unrep_terms=%d/%d"
          % (fam, nz, out[fam]["pct_of_zero"], na, out[fam]["share_of_mentions_that_zero_route"],
             len(unrep), len(terms)))

json.dump(out, io.open(os.path.join(S, "laneA_family_census.json"), "w", encoding="utf-8"), indent=1)

# ── alias probes: does an EXISTING node's own matcher fire on words the corpus uses? ──
probes = {
 "rice": ["paddy", "palay", "rough rice", "milled rice", "broken rice", "basmati", "parboiled"],
 "cotton": ["cottonseed", "lint", "seed cotton", "ginned"],
 "palm_oil": ["palm kernel oil", "pko", "cpo", "crude palm oil", "palm olein", "palm stearin", "rbd palm"],
 "soybean_meal": ["sbm", "soymeal", "soybean cake", "meal"],
 "soybean_oil": ["sbo", "soyoil", "degummed"],
 "corn": ["maize", "palay corn", "yellow corn", "white corn", "grain corn", "milho"],
 "raw_sugar": ["cane sugar", "centrifugal sugar", "sugarcane", "beet sugar", "sugar beet"],
 "white_sugar": ["refined sugar", "plantation white"],
 "rapeseed": ["canola", "mustard", "colza", "double zero"],
 "orange_juice": ["fcoj", "nfc", "frozen concentrated", "orange", "oranges", "citrus"],
 "cocoa": ["cacao", "cocoa beans", "cocoa butter", "chocolate", "grindings"],
 "arabica_coffee": ["coffee", "green coffee", "cherry"],
 "hrw_wheat": ["wheat", "durum", "flour"],
}
probe_out = {}
for node, words in probes.items():
    m = hv.build_matcher(ev.match_forms(node))
    probe_out[node] = {"match_forms": ev.match_forms(node),
                       "fires": {w: bool(m.search(w)) for w in words}}
    miss = [w for w, ok in probe_out[node]["fires"].items() if not ok]
    print("PROBE %-16s misses: %s" % (node, miss))
json.dump(probe_out, io.open(os.path.join(S, "laneA_alias_probe.json"), "w", encoding="utf-8"), indent=1)

# ── currency-by-currency count in the zero-routed mass ──
CUR = {"argentine_peso": ["argentine peso", "peso", "pesos"], "mexican_peso": ["mexican peso"],
       "ukrainian_hryvnia": ["hryvnia", "hryvnias", "uah"], "russian_ruble": ["ruble", "rouble", "rubles"],
       "thai_baht": ["baht"], "turkish_lira": ["lira", "turkish lira"], "australian_dollar": ["australian dollar", "aud"],
       "canadian_dollar": ["canadian dollar", "cad", "usd/cad"], "chinese_yuan": ["yuan", "renminbi", "rmb"],
       "south_african_rand": ["rand", "zar"], "philippine_peso": ["philippine peso"],
       "vietnamese_dong": ["dong"], "euro_fx": ["euro", "eur/usd"], "brazilian_real_CFG": ["brazilian real", "real depreciat"],
       "indian_rupee_CFG": ["rupee", "indian rupee"], "indonesian_rupiah_CFG": ["rupiah", "idr"],
       "malaysian_ringgit_CFG": ["ringgit", "myr"]}
cur_out = {}
for k, terms in CUR.items():
    n, h, _ = count(terms, zero)
    cur_out[k] = {"zero_routed_props": n, "hits": h.most_common(5),
                  "config_forms_firing": {t: CFG_M.findall(t) for t in terms if CFG_M.findall(t)}}
    print("CUR %-24s zero=%5d cfg=%s" % (k, n, list(cur_out[k]["config_forms_firing"])))
json.dump(cur_out, io.open(os.path.join(S, "laneA_currency_census.json"), "w", encoding="utf-8"), indent=1)
print("done")
