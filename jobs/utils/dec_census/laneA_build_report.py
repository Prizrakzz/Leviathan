# -*- coding: utf-8 -*-
"""LANE A -- build data/dec_p0/zero_route_clusters.{json,md} from the measured passes."""
import io, json, os, sys, random, collections, datetime

sys.path.insert(0, r"C:/Users/User/Desktop/Leviathan/src")
from leviathan.graphrag import evidence as ev, harvest as hv, extract as ex

S = r"C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad"
OUT = r"C:/Users/User/Desktop/Leviathan/data/dec_p0"

zero = [json.loads(l) for l in io.open(os.path.join(S, "laneA_zero_routed.jsonl"), "r", encoding="utf-8")]
summ = json.load(io.open(os.path.join(S, "laneA_route_summary.json"), "r", encoding="utf-8"))
famc = json.load(io.open(os.path.join(S, "laneA_family_census.json"), "r", encoding="utf-8"))
alias = json.load(io.open(os.path.join(S, "laneA_alias_mass.json"), "r", encoding="utf-8"))
probe = json.load(io.open(os.path.join(S, "laneA_alias_probe.json"), "r", encoding="utf-8"))
curc = json.load(io.open(os.path.join(S, "laneA_currency_census.json"), "r", encoding="utf-8"))
srcd = json.load(io.open(os.path.join(S, "laneA_source_dark.json"), "r", encoding="utf-8"))
CFG_M = hv.build_matcher(json.load(io.open(os.path.join(S, "laneA_config_forms.json"), "r", encoding="utf-8")))
NZ = len(zero)

# id, name, verdict, terms, note, fix
C = [
 ("Z01", "Aggregate & complex-level commodity nodes (oilseed / vegetable oil / coarse grains / protein meal / compound feed)", "a",
  ['oilseed','oilseeds','coarse grain','coarse grains','feed grain','feed grains','compound feed','vegetable oil','vegetable oils','edible oil','edible oils','fats and oils','oils and fats','oilmeal','oilmeals','oil meals','protein meal','protein meals','grains and oilseeds'],
  "The corpus reasons at the AGGREGATE level constantly -- 'India's edible oil imports', 'world coarse grains production', "
  "'German compound feed production' -- and the graph has no node at that altitude. commodity_hierarchy.yaml ALREADY declares "
  "these exact objects (groups: grains / food_grains / oilseeds / oilseed_meals / vegetable_oils / soft_commodities / tropicals; "
  "complexes: soy_complex / rapeseed_complex / veg_oil_complex / maize_complex / feed_grains / wheat / sugar / coffee / palm_complex), "
  "but ev.all_nodes() returns ONLY the 24 contract nodes, so no group or complex ever gets match_forms and no evidence slice exists "
  "for one. The vocabulary is declared and unrouted -- this is the single largest structural blindness in the dark mass, larger than "
  "the livestock layer by 1.9x.",
  "Give every commodity_hierarchy group/complex a routable identity: extend all_nodes()/match_forms with group ids + their surface "
  "forms ('edible oil', 'vegetable oils', 'coarse grains', 'oilmeal', 'compound feed'), or add them as driver slices if a node is too "
  "heavy. Costs no new chunking -- the props are already in chunks/."),
 ("Z02", "Peanut / groundnut complex", "a",
  ['peanut','peanuts','groundnut','groundnuts'],
  "9,041 props in the cache name peanut or groundnut and 88.2% of them route NOWHERE. The props are full balance-sheet shape "
  "(area, production, crush, meal, oil, exports, MSP) -- structurally identical to soybeans, which IS a node. Peanut oil and peanut "
  "meal are direct substitutes inside the veg-oil and protein-meal complexes the graph already models, and India/China/Argentina "
  "peanut is a first-order swing in both. ZERO peanut/groundnut surface form appears anywhere in any config.",
  "New node `peanut` (aliases: groundnut, groundnuts, peanuts, shelled peanut, peanut meal, peanut oil) inside the oilseeds group, "
  "with crush edges to peanut_oil / peanut_meal and substitution edges into veg_oil_complex + protein_meal."),
 ("Z03", "Coconut / copra / CNO complex", "a",
  ['copra','coconut','coconuts','cno','coconut oil','desiccated coconut','copra meal'],
  "6,565 mentions, 86.4% dark. Copra crush -> CNO (coconut oil) + copra meal is a complete crush chain the graph does not know "
  "exists, and it is the lauric-oil twin of palm kernel oil -- the palm complex IS modelled. Philippines/Indonesia/India supply "
  "shocks (typhoon, coconut scale insect, replanting age profile) move lauric prices and spill into palm.",
  "New node `coconut_oil` (+ copra as the seed) in the vegetable_oils group with a lauric-oil substitution edge to palm_kernel_oil "
  "and palm_oil."),
 ("Z04", "Minor cereals: rye, oats, millet, durum, triticale, buckwheat", "a",
  ['rye','oats','oat','millet','durum','triticale','buckwheat','fonio','quinoa'],
  "5,126 mentions, 69.5% dark. These are the FEED and FOOD substitutes that clear at the margin of the wheat/corn balance -- and "
  "durum is a wheat CLASS with its own price, its own exporters (Canada, Algeria's import book) and no node, while the graph carries "
  "four other wheat classes. Note this is NOT the known barley/sorghum gap: barley and sorghum are already on the ranked list and are "
  "excluded from these counts' framing below.",
  "Either one `minor_cereals` group node or individual nodes for durum (wheat complex) + rye/oats/millet (feed_grains group). Durum "
  "is the highest-value single addition: it trades, it has a distinct balance sheet, and it is invisible to every wheat class matcher."),
 ("Z05", "Fresh citrus: oranges, grapefruit, lemons/limes, tangerines/mandarins, pomelo", "a",
  ['fresh oranges','navel','grapefruit','pomelo','lemon','lemons','lime','limes','tangerine','tangerines','mandarin','mandarins','clementine','satsuma'],
  "3,808 mentions, 85.5% dark, and 3,245 of the 3,254 dark props come from usda_gain_orange_juice -- the node's OWN source. The "
  "fresh-vs-processing diversion decision IS the FCOJ supply mechanism (a grower who ships fresh does not deliver to the juice plant), "
  "and the graph models only the juice end. This is the mechanical reason the orange_juice node has nothing to walk to: half of its own "
  "corpus is about a fruit-market layer that does not exist. (Distinct from the already-known 'FCOJ is isolated in the graph' finding "
  "-- this names WHY.)",
  "Add a `fresh_citrus` node (or per-fruit nodes: fresh_orange, lemon_lime, grapefruit, mandarin) with a fresh/processing diversion "
  "edge into orange_juice, and give orange_juice the alias 'oranges' (see the alias register: 1,031 dark props on the plural alone)."),
 ("Z06", "Cottonseed (seed / oil / meal) -- the cotton co-product chain", "a",
  ['cottonseed','cotton seed','cottonseed oil','cottonseed meal'],
  "3,613 mentions, 81.8% dark. cotton IS a node but word-boundary matching means its matcher can never fire inside 'cottonseed': "
  "the co-product chain that turns a fibre crop into the world's 5th-largest protein meal and a top-6 vegetable oil is fully outside "
  "the graph. India's cottonseed meal alone is 4.4 MMT/yr in these props.",
  "New nodes cottonseed / cottonseed_oil / cottonseed_meal hung off cotton with a crush edge, PLUS the extra_terms alias fix on cotton "
  "so 'cottonseed', 'lint' and 'ginning' at least route to the fibre node."),
 ("Z07", "Sugarcane (the raw agricultural stage of the sugar complex)", "b",
  ['sugarcane','sugar cane','cane'],
  "2,875 dark props. raw_sugar and white_sugar are nodes; neither matcher fires on the word 'sugarcane' (or bare 'cane'). Every "
  "Brazilian/Thai/Indian cane-supply fact -- crush start, TRS/ATR quality, cane diversion to ethanol, new mill projects, ratoon age -- "
  "is dark. sugar_ethanol_parity holds 'cane to ethanol'/'cana mix'/'cane diversion' as PHRASES, so only the ethanol-parity framing "
  "routes; plain cane agronomy does not. Note evidence.bare_name_warnings() cannot catch this class: it only tests tokens OF THE NODE ID, "
  "and 'sugarcane' is not a token of 'raw_sugar'.",
  "One line in evidence_windows.yaml extra_terms for raw_sugar/white_sugar ('sugarcane', 'sugar cane', 'cane'), or a `sugarcane` node "
  "if the agronomic stage deserves its own walkable object. Cheapest high-mass fix on the board."),
 ("Z08", "Marketing-year frame + HS/tariff-code props (numbers-lane content minted as propositions)", "d",
  ['hs code','tariff code','code had','oct sept','apr mar','jan dec','market year beginning'],
  "6,189 mentions, 2,067 dark. These props carry no causal content -- they are table rows ('Rye (HS Code 100290) had zero import duties "
  "in Turkey for January-April 2023 with an MFN rate of 130%', 'market year beginning 07/2000 was 637,000 hectares'). They belong to the "
  "numbers/cards lane, not the proposition store; they inflate the chunk cache and the 60k truncation pressure without ever being walkable.",
  "Classify at chunk time: a prop whose only content is a code + a marketing-year frame should be routed to the numbers lane or dropped, "
  "not written to chunks/. This is a X2-cost lever as much as a graph lever."),
 ("Z09", "Flour milling, bread, pasta, bulgur, noodles -- the wheat FIRST-PROCESSING layer", "a",
  ['flour','flour mill','flour mills','bread','baladi','pasta','semolina','bulgur','noodle','noodles','bakery','biscuit','extraction rate'],
  "5,664 mentions, 1,993 dark. Wheat demand does not reach a consumer as wheat: it reaches them as flour, bread and pasta, and the "
  "policy that moves import demand is set at that stage (Egypt's baladi subsidy, Turkey's TMO/pasta export machine, Ukraine's bread "
  "price controls). The graph ends at the grain. Four wheat class nodes and not one of them fires on 'flour'.",
  "Add a `wheat_milling` / `flour` node between the wheat classes and demand, carrying bread-subsidy and milling-margin drivers."),
 ("Z10", "Producer-currency FX (13 currencies with no slice)", "b",
  ['exchange rate','foreign exchange','devaluation','devalued','peso','pesos','baht','lira','hryvnia','ruble','rouble','australian dollar','canadian dollar','yuan','renminbi','rmb','rand','dong','zloty','forint'],
  "6,131 mentions, 1,876 dark. The FX layer exists but is keyed on exactly four currencies (brl_fx, idr_fx, inr_fx, myr_fx) plus "
  "us_dollar_index. Measured dark mass by currency: Argentine peso 634, Thai baht 338, Russian ruble 199, Chinese yuan/RMB 195, "
  "Turkish lira 70, Australian dollar 62, Ukrainian hryvnia 61, Canadian dollar 50, South African rand 48, Philippine peso 21, "
  "Mexican peso 17, Vietnamese dong 14, euro 14. The four configured currencies show ZERO dark props -- proof the mechanism works and "
  "the roster is simply too short. FX is the pass-through that decides farmer selling in every one of these origins.",
  "Add ars_fx, thb_fx, rub_fx, cny_fx, try_fx, aud_fx, uah_fx, cad_fx, zar_fx slices on the existing pattern, plus a generic "
  "'exchange rate / devaluation / foreign exchange' term set so an unnamed-currency prop still lands somewhere."),
 ("Z11", "Non-agricultural World Bank CMO commodities (coal, steel, gold, tin, timber, tea, jute, bananas)", "c",
  ['coal','steel','gold','silver','tin','bauxite','logs','sawnwood','timber','plywood','tobacco','tea','bananas','wool','iron ore'],
  "2,159 mentions, 80% dark, overwhelmingly from wb_cmo_outlook -- which is the darkest source in the corpus at 52.6%. These are price "
  "table rows for commodities outside the mandate ('Logs from Cameroon were priced at 421.5 $/cum in 2009'). Legitimately out of scope as "
  "graph nodes, but they are being CHUNKED and stored as propositions, which is a cost and cap defect, not a coverage one.",
  "Filter wb_cmo_outlook chunking to the in-scope commodity table rows (or route the rest to the numbers lane). Half of that source's "
  "props are currently paid for and unwalkable."),
 ("Z12", "Pulses & legumes (chickpea, lentil, mung bean, dry bean, pigeon pea, kharif/rabi pulses)", "a",
  ['pulses','pulse','lentil','lentils','chickpea','chickpeas','garbanzo','garbanzos','mung bean','mung beans','dry beans','dry bean','pigeon pea','pigeon peas','kabuli','cowpea','black gram'],
  "2,039 mentions, 82.1% dark. Pulses compete for the SAME acres as oilseeds and wheat in India, Canada, Australia and Turkey, they "
  "carry their own MSP/import-duty policy cycle, and they are the protein substitute that shows up when meal is expensive. India's rabi "
  "pulse acreage is a direct upstream of Indian edible-oil import demand -- the exact channel the graph exists to trace.",
  "A `pulses` group node with acreage-competition edges to wheat/rapeseed/chana and a policy driver for India's pulse import duty cycle."),
 ("Z13", "Quantitative weather observation (the graph sees weather only when someone calls it a disaster)", "b",
  ['rainfall','precipitation','millimeters','temperature','temperatures','degrees celsius','above normal','below normal','cumulative rainfall','weather conditions'],
  "4,674 mentions, 1,435 dark. Every climate slice is keyed on a NAMED extreme (drought, flood, frost, heat wave, el nino). A prop that "
  "reports the measurement itself -- 'cumulative precipitation between January and February 2023 was 80 percent above normal', 'absence of "
  "rainfall in Pakistan during December and January' -- fires nothing. The graph therefore cannot see a developing anomaly, only a declared "
  "one, which is a systematic LATENESS bias in the weather layer.",
  "Add a `weather_observation` slice (rainfall, precipitation, mm, degrees, above/below normal, cumulative rainfall, dry spell, "
  "weather conditions) so the quantitative record is walkable ahead of the named-event framing."),
 ("Z14", "Income growth, urbanization and food-service demand -- the demand-GROWTH channel", "a",
  ['gross domestic product','gdp','per capita consumption','per capita expenditure','urban residents','urbanization','disposable income','middle class','remittances','tourism','tourists','restaurant sales','food service','foodservice','catering','bakery revenue','economic growth'],
  "2,189 mentions, 54.6% dark. The `macro` slice covers shocks (recession, inflation, covid, interest rate) but nothing about the SECULAR "
  "demand channel the corpus talks about constantly: per-capita vegetable-oil consumption, urban vs rural diets, restaurant and catering "
  "revenue, remittances, tourist arrivals. That channel is why Asian veg-oil and meal demand grows; without it every demand-side answer "
  "must be minted from price alone.",
  "A `consumption_growth_demand` slice (per capita consumption, urbanization, disposable income, food service, catering, restaurant, "
  "tourism, remittances) and, ideally, a demand-center node per major importer."),
 ("Z15", "Processing / crush / milling / storage CAPACITY", "a",
  ['crushing capacity','crush capacity','milling capacity','storage capacity','crushing facilities','crushing plant','crush plant','refining capacity','refinery capacity','installed capacity','capacity utilization','idle capacity','silos','grain elevator','warehouse capacity'],
  "2,237 mentions, 46.3% dark, and NOT ONE of the 15 capacity surface forms appears anywhere in any config. The graph models FLOWS and "
  "has no concept of the constraint on them: whether a country can crush what it grows, store what it harvests, or mill what it imports. "
  "Capacity is the standing explanation for why a supply shock does or does not transmit ('534 active flour factories in Turkey with an "
  "annual milling capacity of about 33 MMT').",
  "A `processing_capacity` slice now (cheap), and a capacity attribute on the crush/mill edges later."),
 ("Z16", "Caloric-sweetener substitution: HFCS, glucose/fructose syrup, molasses, panela, gur", "a",
  ['hfcs','high fructose','fructose syrup','glucose syrup','isoglucose','molasses','panela','gur','jaggery','sweetener','sweeteners','stevia'],
  "1,671 mentions, 60.5% dark. HFCS is corn's demand channel INTO the sugar market and the reason Mexican sugar policy is a corn story; "
  "molasses is the cane co-product that clears into ethanol and feed; panela/gur is a third of the sweetener volume in Colombia and India. "
  "The graph has corn and two sugar nodes and no edge or vocabulary connecting them through the sweetener market.",
  "A `caloric_sweetener_substitution` slice (hfcs, high fructose, isoglucose, molasses, panela, gur, jaggery) plus a corn->hfcs->sugar "
  "substitution edge."),
 ("Z17", "Olive oil", "a",
  ['olive','olives','olive oil','extra virgin','evoo','pomace'],
  "820 mentions and 92.6% dark -- the highest dark share of any family measured. A top-5 edible oil by value, appearing inside "
  "usda_gain_rapeseed and soybean_meal reports (i.e. the corpus files it WITH the oils the graph models), with no surface form anywhere "
  "in any config.",
  "Add olive_oil to the vegetable_oils group with a substitution edge into the veg-oil complex."),
 ("Z18", "Biotech approvals, seed varieties and phytosanitary market access", "a",
  ['biotech','genetically modified','genetically engineered','gmo','bollgard','seed variety','hybrid seed','plant protection','quarantine','pest risk','import protocol','market access protocol'],
  "2,473 mentions, 711 dark. Biotech event approval and phytosanitary protocol are the gates that decide WHETHER a trade flow can exist "
  "at all (China's GMO approvals for soybeans and corn; Vietnam's quarantine pest list; India's Bt cotton varieties). The policy layer "
  "models tariffs, quotas, bans and levies and has nothing for the non-tariff gate that is usually the binding one.",
  "A `biotech_phytosanitary_access` slice (biotech, GE/GM event, approval, quarantine pest list, phytosanitary protocol, MRL, "
  "market access protocol)."),
 ("Z19", "Non-US producer support and state procurement (TMO, PROAGRO/SAGARPA, BULOG, paddy pledging, Plano Safra)", "b",
  ['proagro','sagarpa','aserca','plano safra','procurement price','state procurement','mortgage scheme','paddy pledging','tmo','turkish grain board','bulog','nafed','support program','farm credit','credit line','gsm-102','public stockholding'],
  "2,604 mentions, 690 dark. us_farm_program covers the US in depth; china_reserve_auctions covers China; msp covers India's headline "
  "price. Everything else -- Turkey's TMO procurement and export tenders, Thailand's paddy pledging/mortgage scheme, Mexico's "
  "PROAGRO/ASERCA, Indonesia's BULOG, Brazil's Plano Safra credit line -- has no lever. These are the state balance sheets that absorb or "
  "release supply in exactly the origins the graph cares about.",
  "One `state_procurement_support` slice with the agency names as terms, or per-country levers on the us_farm_program pattern."),
 ("Z20", "Domestic standards, NTMs, VAT/excise and food-safety rules", "b",
  ['fortification','labeling','food safety','aqsiq','maximum residue','mrl','certification','traceability','halal','value added tax','vat','excise tax','registration requirement'],
  "1,603 mentions, 594 dark. The trade-policy layer is tariff-shaped. The corpus's actual friction is often a VAT rate on edible oils, a "
  "fortification mandate, an AQSIQ decree, a halal or traceability requirement. None of these surface forms exists in any config.",
  "Extend the `tariff` slice or add `non_tariff_measures` (vat, excise, labeling, fortification, certification, traceability, MRL, "
  "registration)."),
 ("Z21", "Water, irrigation and reservoir infrastructure", "a",
  ['irrigation','irrigated','reservoir','reservoirs','dam','water availability','water allocation','water rights','aquifer','groundwater','canal water','water storage'],
  "1,837 mentions, 557 dark, none of the 12 forms in any config. This is structurally different from `drought`: drought is an event, "
  "irrigation capacity is the standing state that decides whether the event matters ('Water storage levels in the Murray-Darling Basin "
  "were at 69 percent of total capacity'). Pakistan, Thailand, India, Australia and Brazil all reason this way in the corpus.",
  "An `irrigation_water_resources` slice; longer term a water-availability attribute on producing regions."),
 ("Z22", "Minor oilseeds: sesame, safflower, camellia/tea-seed, flax/linseed, castor, mustard", "a",
  ['sesame','safflower','camellia','flaxseed','linseed','castor','niger seed','mustard seed','tea seed oil'],
  "796 mentions, 70% dark. China's camellia (woody oil-tree) program is an explicit state substitution for imported edible oil; India's "
  "mustard is half the domestic oilseed crush; sesame is a major African/Indian export earner. All invisible. Note the rapeseed node does "
  "not fire on 'mustard' either (76 dark props) even though rapeseed-mustard is a single Indian complex.",
  "Fold into a `minor_oilseeds` group node, and add 'mustard' to rapeseed's extra_terms."),
 ("Z23", "Aquaculture / aquafeed demand", "a",
  ['aquaculture','shrimp','catfish','farmed fish','fish feed','aquafeed','tilapia','pangasius','hatchery','seafood'],
  "945 mentions, 57.7% dark. marine_protein_fishmeal covers fishmeal as a SUPPLY substitute; nothing covers aquaculture as a soybean-meal "
  "DEMAND center, which is the fastest-growing meal demand channel in Asia ('China's aquaculture production reached 60.6 MMT in 2024, up "
  "4.4 percent'). This is the same class of miss as the livestock layer the owner found -- a demand animal the graph cannot see -- but a "
  "different animal.",
  "An `aquafeed_demand` slice (aquaculture, shrimp, pangasius, tilapia, fish feed, aquafeed, hatchery) feeding the meal complex."),
 ("Z24", "Crop progress and phenology (sowing, emergence, flowering, abandonment, replanting)", "b",
  ['sowing','planting progress','planting pace','seeded','emergence','flowering','vegetative','abandonment','replanting','harvest progress','harvest delay','digging'],
  "1,759 mentions, 494 dark. us_drought_monitor carries 'crop progress' and 'good-to-excellent' for the US only; the rest of the world's "
  "progress reporting ('area seeded to barley in Canada', 'winter grain replanting need in Ukraine', NDVI vegetative development) has no "
  "home. Progress is the earliest observable of a yield outcome.",
  "Widen us_drought_monitor into a `crop_progress` slice with the international vocabulary, or add a second slice keyed on sowing/"
  "emergence/flowering/abandonment/replanting."),
 ("Z25", "OPEC and crude-supply policy", "b",
  ['opec','opec+','barrels per day','crude inventories','oecd inventories','refinery','spare capacity','oil quota'],
  "686 mentions, 68.7% dark. `crude` carries 'crude oil, brent, wti, petroleum, oil prices' -- prices, not the SUPPLY DECISION that sets "
  "them. OPEC quota and spare-capacity props ('OPEC output has tumbled 7 percent (2.7 mb/d)') are dark, and crude is the upstream of every "
  "biofuel-parity edge the graph already models.",
  "Add opec, opec+, quota, spare capacity, mb/d, barrels per day, OECD inventories, refinery runs to the `crude` slice."),
 ("Z26", "Palm kernel oil / meal and oleochemicals", "b",
  ['palm kernel','pko','pkm','palm kernel oil','palm kernel meal','oleochemical','oleochemicals'],
  "3,553 mentions, 410 dark -- lower dark share because the word 'palm' rescues most of them into palm_oil, which is precisely the defect: "
  "PKO/PKM props are being mis-attributed to the CPO node rather than routed to a lauric co-product of their own. The abbreviations PKO "
  "(178) and PKM (102) route nowhere at all, and 'oleochemical' -- the entire downstream industrial demand for lauric oils, and the bulk of "
  "the mpob source -- has no config form.",
  "Split palm_kernel_oil / palm_kernel_meal off palm_oil as their own nodes (with PKO/PKM abbreviations) and add an `oleochemical_demand` "
  "slice."),
 ("Z27", "Inland logistics: rail, trucking, terminals, grain handling, drying", "a",
  ['railway','rail transport','trucking','inland transport','transportation system','port capacity','port infrastructure','loading rate','throughput','barge','terminal','cargo handling','grain handling','drying capacity'],
  "644 mentions, 60.4% dark, zero config forms. Every logistics slice in the config is a named CHOKEPOINT (Black Sea, Panama, Mississippi, "
  "Parana, Suez, vessel lineups). The everyday inland cost stack -- rail tariffs, truck availability, elevator throughput, drying capacity -- "
  "is the thing that actually sets origin basis in Ukraine, Brazil, Canada and Argentina, and it is invisible between chokepoint events.",
  "An `inland_logistics_cost` slice (rail, truck, terminal, elevator, handling, drying, throughput, loading rate)."),
 ("Z28", "Trade agreements, accession and preferential access (FTA / CPTPP / ASEAN / CEPA / customs union)", "b",
  ['free trade agreement','fta','cptpp','tpp','rcep','asean','cepa','association agreement','customs union','accession','preferential access','duty free access','trade negotiations'],
  "1,443 mentions, 393 dark. `tariff` names NAFTA/USMCA/Mercosur/WTO/Uruguay Round but not the agreement class the corpus actually reports "
  "-- AFTA/ASEAN, CPTPP, RCEP, Canada-Indonesia CEPA, the EU-Ukraine association agreement, CTPA. These change duty-free access for whole "
  "origins at a stroke.",
  "Extend the `tariff` slice terms with the agreement vocabulary (free trade agreement, FTA, CPTPP, RCEP, ASEAN, CEPA, accession, "
  "duty-free access)."),
 ("Z29", "Labor disputes, strikes, blockades and road/rail disruption", "a",
  ['strike','strikes','labor dispute','union','protest','roadblock','blockade','truckers','worker shortage','labour shortage'],
  "1,252 mentions, 340 dark. Rosario crush strikes, Brazilian trucker blockades, CP Rail/Teamsters arbitration -- a recurring, high-impact, "
  "SUPPLY-INTERRUPTING class with no slice of any kind. `sanctions_payment_rails` covers geopolitical interruption; labor interruption has "
  "nothing.",
  "A `labor_disruption` slice (strike, work stoppage, union, blockade, roadblock, truckers, port labor, arbitration)."),
 ("Z30", "Textile mid-chain: looms, spinning, man-made fibre, ginning, jute", "b",
  ['power loom','power looms','handloom','handlooms','hosiery','weaving','man-made fiber','manmade fiber','chemical fiber','synthetic fiber','viscose','jute','kenaf','ginning','ginners'],
  "569 mentions, 49.6% dark. textile_apparel_demand and cotton_polyester_competition stop at 'textile/yarn/spinning/polyester'. The mill "
  "stage the corpus reports -- power looms, handlooms, hosiery units, chemical-fibre imports, ginning capacity -- is where cotton demand is "
  "actually determined in India, Pakistan and China.",
  "Extend textile_apparel_demand with the mill vocabulary; add ginning to the cotton node's extra_terms."),
 ("Z31", "Food security, public distribution and refugee/humanitarian demand", "b",
  ['food security','public distribution','ration','subsidized bread','safety net','school feeding','wfp','humanitarian','refugees'],
  "848 mentions, 249 dark. India's PDS and Food Security Bill, Egypt's baladi ration, Turkey hosting three million refugees, WFP purchases "
  "-- a demand class that is administratively set rather than price-cleared, and therefore behaves differently from every demand channel the "
  "graph does model.",
  "A `public_food_distribution` slice (PDS, ration, food security bill, school feeding, WFP, humanitarian, refugees)."),
 ("Z32", "Elections and political transitions", "a",
  ['election','elections','presidential election','new government','coup','political crisis','referendum','parliament approved','congress approved'],
  "278 mentions, 68.7% dark. Small mass, high leverage: the geopolitics slices are all event-specific (Argentina export policy, Russia export "
  "tax, sanctions) and none of them anticipates the political event that CAUSES the policy change. 'As of April 2, Brazil enters election mode, "
  "a period in which intentional support for a specific sector cannot be provided' is exactly the kind of forward-looking constraint a "
  "decision desk wants and the graph cannot reach.",
  "A `political_transition` slice (election, presidential election, new government, referendum, parliament/congress approved, political crisis)."),
 ("Z33", "Carbon, emissions and deforestation policy on agriculture", "b",
  ['carbon tax','carbon price','greenhouse gas','emissions','deforestation','sustainability certification','carbon credit','net zero','land use change'],
  "143 mentions, 54.5% dark. EUDR is inside eu_crop_and_policy; nothing else. Canada's federal carbon tax on farm inputs, IMO 2020 marine "
  "sulfur limits (a freight-cost driver), Paraguay/Amazon deforestation criticism of biofuel projects, New Zealand agricultural emissions -- "
  "a young but structurally growing driver class with almost no vocabulary.",
  "A `carbon_deforestation_policy` slice (carbon tax/price, emissions, greenhouse gas, deforestation, EUDR, sustainability certification)."),
 ("Z34", "Vernacular and local-language crop names (paddy/palay, kharif/rabi, safra/zafra, Portuguese-language props)", "b",
  ['paddy','palay','kharif','rabi','safra','zafra'],
  "2,452 mentions, 496 dark. The rice node fires on neither 'paddy' (283 dark props) nor 'palay' (39); 'kharif'/'rabi' -- the season names "
  "that frame every Indian acreage statement -- have no config form. Separately, 649 dark props are Portuguese/Spanish-language text "
  "(conab, sao paulo sugar/citrus reports): the matchers are ASCII-normalized but English-vocabulary only, so a whole language of the corpus "
  "is structurally unroutable.",
  "extra_terms for rice ('paddy', 'palay', 'rough rice'); a season vocabulary (kharif, rabi, safra, safrinha, zafra); and a decision on "
  "whether non-English props should be translated at chunk time or excluded (today they are paid for and dark)."),
 ("Z35", "Livestock / dairy / poultry demand layer -- ALREADY KNOWN, measured here for calibration only", "known",
  ['cattle','hog','hogs','swine','pig','pigs','poultry','broiler','broilers','chicken','beef','pork','egg','eggs','sow','heifer','slaughter','feedlot','milk','dairy','cheese','butter','whey','livestock','meat and bone meal','mbm'],
  "The gap the owner found by reading a market commentary is 4,981 props = 5.26% of the dark mass. That number is the point of this lane: "
  "the finding that triggered the whole wave is one twentieth of what the production matchers cannot route, and it is only the THIRD largest "
  "single family after the aggregate-node gap (9,599) and peanut (7,975). Excluded from the ranking above; listed so the register states its "
  "own calibration.",
  "(already on the wave's list)"),
]

FXW = {"argentine_peso": ["argentine peso", "pesos"], "mexican_peso": ["mexican peso"],
       "ukrainian_hryvnia": ["hryvnia"], "russian_ruble": ["ruble", "rubles"], "thai_baht": ["baht"],
       "turkish_lira": ["turkish lira"], "australian_dollar": ["australian dollar"],
       "canadian_dollar": ["canadian dollar"], "chinese_yuan": ["yuan", "renminbi"],
       "south_african_rand": ["rand"], "philippine_peso": ["philippine peso"], "vietnamese_dong": ["dong"],
       "euro_fx": ["euro"], "brazilian_real_CFG": ["brazilian real"], "indian_rupee_CFG": ["rupee"],
       "indonesian_rupiah_CFG": ["rupiah"], "malaysian_ringgit_CFG": ["ringgit"]}

rnd = random.Random(17)
clusters = []
for cid, name, verdict, terms, note, fix in C:
    m = hv.build_matcher(terms)
    idx = [i for i, p in enumerate(zero) if m._rx and m._rx.search(p["nf"])]
    hits = collections.Counter()
    for i in idx:
        for f in m._rx.findall(zero[i]["nf"]):
            hits[m._idx.get(f, f)] += 1
    srcs = collections.Counter(zero[i].get("src") or "?" for i in idx)
    yrs = sorted(set((zero[i].get("d") or "????")[:4] for i in idx) - {"????"})
    pick = (idx[:1] + rnd.sample(idx, min(8, len(idx)))) if idx else []
    seen, sm = set(), []
    for i in pick:
        t = zero[i]["t"]
        if t in seen or len(t) < 40:
            continue
        seen.add(t)
        sm.append({"text": t, "source": zero[i].get("src"), "date": zero[i].get("d"), "source_key": zero[i].get("s")})
        if len(sm) == 3:
            break
    cfg_fire = {t: CFG_M.findall(t) for t in terms}
    clusters.append({
        "id": cid, "name": name, "verdict": verdict,
        "verdict_label": {"a": "missing NODE", "b": "missing SLICE/vocabulary", "c": "out of scope",
                          "d": "numbers-lane content", "known": "ALREADY KNOWN (calibration)"}[verdict],
        "zero_routed_props": len(idx), "pct_of_zero_mass": round(100.0 * len(idx) / NZ, 2),
        "top_terms": hits.most_common(12),
        "top_sources": srcs.most_common(5),
        "year_span": [yrs[0], yrs[-1]] if yrs else None,
        "config_cross_check": {
            "terms_with_NO_config_form": [t for t, v in cfg_fire.items() if not v],
            "terms_a_config_form_fires_on": {t: v for t, v in cfg_fire.items() if v},
            "genuinely_unrepresented": all(not v for v in cfg_fire.values()),
        },
        "samples": sm, "why_it_matters": note, "proposed_fix": fix,
    })

ranked = sorted([c for c in clusters if c["verdict"] != "known"], key=lambda c: -c["zero_routed_props"])
known = [c for c in clusters if c["verdict"] == "known"]
for i, c in enumerate(ranked, 1):
    c["rank"] = i

doc = {
    "lane": "A -- read the zero-routed mass",
    "generated_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    "method": {
        "corpus": "graphrag_evidence/chunks/ -- 2,815 objects, 345,870 propositions (local copy in scratch; zero GETs this pass)",
        "matchers": "the EXACT production pair from evidence_batch.rebuild_slices: "
                    "{n: harvest.build_matcher(evidence.match_forms(n)) for n in evidence.all_nodes()} (24 nodes, 112 normalized forms) "
                    "for commodity_hit, and evidence.driver_slices_for -> evidence.driver_matchers() (113 slices, 646 normalized forms) "
                    "for driver_hit. ZERO-ROUTED == the production 'neither' bucket (dark at birth).",
        "optimization": "_Matcher.search(t) == _rx.search(extract._normalize(t)); text normalized once and the same compiled "
                        "regexes run against it, with a union regex answering 'any hit'. Equivalence VERIFIED against the full "
                        "137-matcher loop on a 20,000-prop random sample: 0 mismatches.",
        "clustering": "no LLM. n-grams 1-3 over the normalized text (n-grams starting/ending on a stopword dropped), document "
                      "frequency, then a greedy highest-remaining-df cover with a mild phrase-length bonus. Two passes: one raw "
                      "(seeds on the balance-sheet frame) and one with a frame+geography stoplist (seeds on subject nouns). "
                      "The named families below were then measured directly with term-set matchers, which is what the counts report.",
        "cross_check": "every family's terms were run against a matcher built over the WHOLE config vocabulary (24 node match_forms + "
                       "113 driver-slice term sets + entity_vocabulary nodes/edges/aliases + commodity_hierarchy contracts/groups/"
                       "complexes/context + policy_levers + all 33 causal/*.yaml driver ids/names/aliases + regions.yaml + geography.yaml "
                       "= 2,134 normalized forms). A family is (a) missing-node when nothing in that vocabulary fires; (b) missing-slice "
                       "when the concept exists somewhere in config but not in the ROUTING vocabulary (driver_slices terms / node forms).",
    },
    "totals": {
        "props_total": summ["total"],
        "commodity_only": summ["counts"]["commodity_only"],
        "driver_only": summ["counts"]["driver_only"],
        "both": summ["counts"]["both"],
        "ZERO_ROUTED": summ["counts"]["neither"],
        "zero_routed_pct": round(100.0 * summ["counts"]["neither"] / summ["total"], 2),
        "named_coverage_of_zero_mass_pct": 61.6,
        "known_livestock_share_of_zero_mass_pct": 5.26,
    },
    "per_source_dark_rate": [{"source": r[0], "props": r[1], "zero_routed": r[2], "dark_pct": r[3]} for r in srcd],
    "clusters": ranked,
    "known_gap_calibration": known,
    "alias_defect_register": {
        "what": "An EXISTING node whose own matcher (build_matcher(match_forms(node))) does not fire on a word the corpus uses for it. "
                "Each is a one-line evidence_windows.yaml extra_terms fix. evidence.bare_name_warnings() cannot catch this class: it only "
                "tests tokens OF THE NODE ID, so 'sugarcane' (raw_sugar), 'oranges' (orange_juice) and 'paddy' (rice) are invisible to it.",
        "rows": [{"defect": k, **v} for k, v in sorted(alias.items(), key=lambda kv: -kv[1]["zero_routed_props"])],
        "node_probes": probe,
    },
    "currency_census": {k: {**v, "routes_to_a_driver_slice": bool(ev.driver_slices_for(" ".join(FXW[k])))}
                        for k, v in curc.items()},
    "excluded_as_already_known": [
        "livestock/dairy/poultry demand layer (measured above for calibration only)",
        "palm_oil ~ palm_olein", "rapeseed crush chain", "MATIF ~ US wheat",
        "barley / sorghum / sunflower_oil DAGs", "ethanol edges",
        "the ~130 ranked structural edge candidates", "the 139 dark drivers",
        "cocoa / FCOJ isolation (Z05 names the MECHANISM behind FCOJ isolation, which is new)",
        "COT / rates numbers-bindings",
    ],
}

io.open(os.path.join(OUT, "zero_route_clusters.json"), "w", encoding="utf-8").write(json.dumps(doc, indent=1, ensure_ascii=False))

# ── markdown ──
L = []
A = L.append
A("# Zero-route clusters -- what the production matchers cannot see")
A("")
A("**Lane A of the outside-in census.** Every proposition in the chunk cache was run through the *exact* production "
  "matcher pair and split into routed vs zero-routed; the zero-routed mass was then clustered without an LLM and named.")
A("")
A("| | props | share |")
A("|---|---:|---:|")
A("| propositions in `graphrag_evidence/chunks/` | %d | 100%% |" % doc["totals"]["props_total"])
A("| routed to a commodity node only | %d | %.1f%% |" % (doc["totals"]["commodity_only"], 100.0*doc["totals"]["commodity_only"]/doc["totals"]["props_total"]))
A("| routed to a driver slice only | %d | %.1f%% |" % (doc["totals"]["driver_only"], 100.0*doc["totals"]["driver_only"]/doc["totals"]["props_total"]))
A("| routed to both | %d | %.1f%% |" % (doc["totals"]["both"], 100.0*doc["totals"]["both"]/doc["totals"]["props_total"]))
A("| **ZERO-ROUTED (dark at birth)** | **%d** | **%.2f%%** |" % (doc["totals"]["ZERO_ROUTED"], doc["totals"]["zero_routed_pct"]))
A("")
A("**The calibration fact this lane exists to produce:** the livestock/dairy/poultry layer the owner found by reading a "
  "market commentary is **4,981 props -- 5.26% of the dark mass**. It is the *third* largest family, behind the missing "
  "aggregate-node layer (9,599) and peanut/groundnut (7,975). Ninety-five percent of what the graph cannot route is "
  "something nobody has named yet.")
A("")
A("### Method (reproducible, no LLM in the clustering)")
A("")
A("- Matchers: `{n: harvest.build_matcher(evidence.match_forms(n)) for n in evidence.all_nodes()}` (24 nodes / 112 normalized "
  "forms) for `commodity_hit`; `evidence.driver_slices_for` -> `evidence.driver_matchers()` (113 slices / 646 normalized forms) "
  "for `driver_hit`. Zero-routed == the production `neither` bucket in `evidence_batch.rebuild_slices`.")
A("- Speed without semantic drift: `_Matcher.search(t)` *is* `_rx.search(extract._normalize(t))`, so the text is normalized once "
  "and a union regex answers *any hit*. Verified against the full 137-matcher loop on 20,000 random props: **0 mismatches**.")
A("- Clustering: n-grams 1-3 over normalized text, document frequency, greedy highest-remaining-df cover (two passes -- raw, then "
  "with a balance-sheet + geography stoplist so seeds land on subject nouns). Families were then measured directly with term-set "
  "matchers; those direct counts are what the table reports.")
A("- Cross-check: each family's terms were tested against a matcher over the **whole** config vocabulary -- node match_forms, "
  "driver-slice terms, `entity_vocabulary.yaml`, `commodity_hierarchy.yaml` (contracts/groups/complexes/context), `policy_levers.yaml`, "
  "all 33 `causal/*.yaml` driver ids/names/aliases, `regions.yaml`, `geography.yaml` = **2,134 normalized forms**.")
A("- Verdicts: **(a) missing NODE** -- nothing in the config vocabulary fires and the props have balance-sheet/walkable shape; "
  "**(b) missing SLICE/vocabulary** -- the concept exists somewhere in config but not in the *routing* vocabulary; "
  "**(c) out of scope**; **(d) numbers-lane content**.")
A("")
A("### Where the darkness lives (per-source dark rate)")
A("")
A("| source | props | zero-routed | dark % |")
A("|---|---:|---:|---:|")
for r in srcd:
    if r[1] >= 900:
        A("| `%s` | %d | %d | %.1f%% |" % (r[0], r[1], r[2], r[3]))
A("")
A("`wb_cmo_outlook` (52.6%) and `usda_gain_orange_juice` (47.8%) are the two darkest sources in the corpus -- and for the "
  "orange-juice source the dark half is *its own subject matter* (fresh citrus, Z05).")
A("")
A("---")
A("")
A("## Ranked gap register")
A("")
A("| # | cluster | verdict | props | % of dark mass |")
A("|---:|---|---|---:|---:|")
for c in ranked:
    A("| %d | %s | **(%s)** %s | %d | %.2f%% |" % (c["rank"], c["id"] + " " + c["name"].split(" -- ")[0], c["verdict"], c["verdict_label"], c["zero_routed_props"], c["pct_of_zero_mass"]))
A("")
A("---")
A("")
for c in ranked:
    A("### %d. `%s` %s" % (c["rank"], c["id"], c["name"]))
    A("")
    A("**Verdict (%s) %s** &nbsp;|&nbsp; **%d props** (%.2f%% of the dark mass) &nbsp;|&nbsp; years %s-%s"
      % (c["verdict"], c["verdict_label"], c["zero_routed_props"], c["pct_of_zero_mass"],
         c["year_span"][0] if c["year_span"] else "?", c["year_span"][1] if c["year_span"] else "?"))
    A("")
    A("- **Top terms in the dark props:** " + ", ".join("`%s` x%d" % (t, n) for t, n in c["top_terms"][:8]))
    A("- **Top sources:** " + ", ".join("`%s` %d" % (s, n) for s, n in c["top_sources"][:4]))
    cc = c["config_cross_check"]
    if cc["genuinely_unrepresented"]:
        A("- **Config cross-check:** NOT ONE of the %d surface forms appears anywhere in the 2,134-form config vocabulary. "
          "Genuinely unrepresented." % len(cc["terms_with_NO_config_form"]))
    else:
        A("- **Config cross-check:** %d/%d forms have no config presence at all; the exceptions are %s -- and none of them is a "
          "*routing* form for this concept." % (len(cc["terms_with_NO_config_form"]),
          len(cc["terms_with_NO_config_form"]) + len(cc["terms_a_config_form_fires_on"]),
          ", ".join("`%s` (fires `%s`)" % (k, v[0]) for k, v in list(cc["terms_a_config_form_fires_on"].items())[:4])))
    A("")
    A("**Evidence (verbatim, dark):**")
    A("")
    for s in c["samples"]:
        A("> %s" % s["text"].replace("\n", " "))
        A("> <br/>&mdash; `%s` %s" % (s["source"], s["date"]))
        A("")
    A("**Why it matters.** " + c["why_it_matters"])
    A("")
    A("**Fix.** " + c["proposed_fix"])
    A("")
    A("---")
    A("")

A("## Cross-cutting: the node-alias defect register")
A("")
A(doc["alias_defect_register"]["what"])
A("")
A("| defect | dark props | dominant term |")
A("|---|---:|---|")
for r in doc["alias_defect_register"]["rows"]:
    A("| %s | %d | %s |" % (r["defect"], r["zero_routed_props"], ("`%s` x%d" % tuple(r["hits"][0])) if r["hits"] else "-"))
A("")
A("Node-matcher probes (does the node's own matcher fire on the word?):")
A("")
A("| node | words its own matcher MISSES |")
A("|---|---|")
for n, v in probe.items():
    miss = [w for w, ok in v["fires"].items() if not ok]
    if miss:
        A("| `%s` | %s |" % (n, ", ".join("`%s`" % w for w in miss)))
A("")
A("---")
A("")
A("## Cross-cutting: the FX roster")
A("")
A("| currency | dark props | routes to a driver slice? |")
A("|---|---:|---|")
for k, v in sorted(curc.items(), key=lambda kv: -kv[1]["zero_routed_props"]):
    A("| %s | %d | %s |" % (k.replace("_CFG", "").replace("_", " "), v["zero_routed_props"],
                            "YES" if ev.driver_slices_for(" ".join(FXW[k])) else "no"))
A("")
A("The four currencies that *do* have slices (BRL, INR, IDR, MYR) show **zero** dark props. The mechanism works; the roster is "
  "thirteen currencies short.")
A("")
A("---")
A("")
A("## Already-known, measured here only for calibration")
A("")
for c in known:
    A("**%s** -- %d props, %.2f%% of the dark mass. %s" % (c["name"], c["zero_routed_props"], c["pct_of_zero_mass"], c["why_it_matters"]))
    A("")
A("Deliberately **not** re-reported: palm_oil~palm_olein, the rapeseed crush chain, MATIF~US wheat, the barley/sorghum/"
  "sunflower_oil DAGs, ethanol edges, the ~130 ranked structural edge candidates, the 139 dark drivers, cocoa/FCOJ isolation, "
  "COT/rates numbers-bindings. (Z05 does name the *mechanism* behind FCOJ isolation, which is new: the fresh-fruit layer its own "
  "source is half made of.)")
A("")
A("## Coverage honesty")
A("")
A("The named families above account for **61.6%%** of the %d zero-routed props. The remaining ~38%% is a genuine long tail: "
  "one-off country facts, report boilerplate (`This report was prepared by PECAD`), methodology notes, and props whose only "
  "content is the balance-sheet frame itself. A 300-prop random sample of the uncovered residual was read and contains no "
  "further family above ~40 props." % NZ)
A("")

io.open(os.path.join(OUT, "zero_route_clusters.md"), "w", encoding="utf-8").write("\n".join(L))
print("wrote", os.path.join(OUT, "zero_route_clusters.json"))
print("wrote", os.path.join(OUT, "zero_route_clusters.md"))
print("ranked clusters:", len(ranked))
for c in ranked[:12]:
    print("  %2d %-5s %-6s %6d  %s" % (c["rank"], c["id"], c["verdict"], c["zero_routed_props"], c["name"][:70]))
