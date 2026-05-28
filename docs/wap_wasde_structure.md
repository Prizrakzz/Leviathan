# WAP & WASDE Source Structure
## Findings from `scratch/probe_wap_wasde.py` — May 2026

> **Active ETL scope — May 2026:** WASDE and WAP are the only active extraction tasks. All other sources (GAIN, CONAB, FNC, WMT, MPOC, etc.) have a defined architecture but no active jobs yet.

---

## Summary of Findings

| Section | Source | Files | Era | Format | Text extractable? | pdfplumber tables? |
|---|---|---|---|---|---|---|
| A | WAP direct S3 | 285 | 2002–2026 | Digital PDF | Yes — ~58k chars/report | **Yes — page 6 has `World Crop Production Summary`** |
| B | WAP archive.org | 163 | 1988–2002 | Digital PDF (NOT scanned) | Yes — ~15k chars/report | Partial — narrative pages yes; table page has reversed text |
| C | WAP Wayback HTML | 67 | 1996–2002 | HTML (multi-page) | Yes — BeautifulSoup | No — HTML layout tables only, not data tables |
| D | WASDE digital S3 | 314 | 2000–2026 | Digital PDF | Yes — ~83k chars/report | No — ASCII fixed-width tables (colon-delimited), not PDF tables |
| E | WASDE TXT S3 | 60 | 1995–1999 | Plain text | Direct decode | N/A |
| F | WASDE scanned S3 | 251 | 1973–1994 | Scanned PDF | **No — 0 chars extracted** | No — Textract required |

---

## Output Architecture

Every WAP and WASDE raw file produces output in one or two layers. No other layers exist for these sources.

```
s3://leviathan-dev-shahem-001/
├── raw/     ← source files as downloaded (already complete)
├── bronze/  ← structured numbers only — Parquet, Glue catalog, Athena-queryable
│              WAP only: Table 01 production estimates (schema in Section A)
│              WASDE: nothing — PSD CSV already has all WASDE monthly vintages
├── silver/  ← tidy long ML features — derived from bronze
│              WAP: wap_nonUS_production_revision (commodity × country × release_month)
└── text/    ← extracted narrative — JSON, one file per source document
               Accepts: pdfplumber output, decoded TXT, Textract-parsed text
               No chunking. No embeddings. Text as-is.
```

### S3 key patterns

| Source | Bronze | Text |
|---|---|---|
| WAP direct (A) | `bronze/production/source=usda_wap/release_month={YYYY-MM}/table01.parquet` | `text/source=usda_wap/release_month={YYYY-MM}/document.json` |
| WAP archive.org (B) | `bronze/production/source=usda_wap/release_month={YYYY-MM}/table01.parquet` | `text/source=usda_wap/release_month={YYYY-MM}/document.json` |
| WAP Wayback HTML (C) | — | `text/source=usda_wap/release_month={YYYY-MM}/document.json` |
| WASDE digital (D) | — | `text/source=usda_wasde/release_date={YYYY-MM-DD}/document.json` |
| WASDE TXT (E) | — | `text/source=usda_wasde/release_date={YYYY-MM-DD}/document.json` |
| WASDE scanned (F) | — | `text/source=usda_wasde/release_date={YYYY-MM-DD}/document.json` |

All three WAP eras (A/B/C) share the same `release_month` partition — one `document.json` per issue regardless of which era the file came from. The `extraction_method` field inside distinguishes them.

### `document.json` schema

```json
{
  "source": "usda_wasde",
  "raw_key": "raw/production/source=usda_wasde/release_date=2026-05-12/wasde0526.pdf",
  "extraction_method": "pdfplumber",
  "extracted_at": "2026-05-28T14:00:00Z",
  "sections": [
    {"name": "wheat", "text": "WHEAT: U.S. wheat ending stocks..."},
    {"name": "coarse_grains", "text": "COARSE GRAINS: ..."}
  ],
  "full_text": "WHEAT: ... COARSE GRAINS: ..."
}
```

- `sections` populated when section structure is cleanly known (WASDE all eras, WAP narrative). Omit for sources without reliable breaks; use `full_text` only.
- `raw_key` provides full lineage back to the source file in `raw/`.
- **Idempotency rule**: check `s3.head_object(text_key)` before extracting — covers pdfplumber, TXT decode, and Textract uniformly. If `document.json` exists, skip.
- Textract raw JSON is **not stored separately**. `text/` is uniform across all extraction methods. ~$4 re-run cost is acceptable if ever needed.
- Chunking, embeddings, and entity extraction are deferred. `text/` is immutable once written.

---

## Section A — WAP Direct PDFs (2002–2026)

**285 reports · S3 · ~24–25 pages · ~58k non-whitespace chars each**

### Structure
- **Page 0**: Cover (Department of Agriculture / FAS / "World Agricultural Production" banner)
- **Pages 1–5**: Narrative production briefs by country/commodity (2,000–3,500 chars/page)
  - Country-specific briefs: "India Soybean: ...", "Canada Wheat: ...", "Brazil Corn: ..."
  - Explicit revision language: "Production is revised downward based on...", "up 1.0 million or 6 percent from last month"
- **Page 5**: Methodology statement + reference to corresponding WASDE issue number (e.g. "WASDE-460, July 2008")
- **Page 6**: **`Table 01 — World Crop Production Summary`** (1,000 Metric Tons)
  - **Extractable via pdfplumber** on 2008+ reports
  - 20 columns: Commodity · World · Total Foreign · US · Canada · Mexico · EU-27 · Russia · Ukraine · China · India · Indonesia · Pakistan · Thailand · Argentina · Brazil · Australia · South Africa · Turkey · All Others
  - Row structure: 5 rows per commodity — prior 2 crop years (prelim), current year (prior month estimate), current year (this month estimate). The last two rows are labelled by month name (e.g. "Jun" / "Jul"), giving **the month-over-month revision within a single PDF**.
  - Commodities covered: Wheat · Coarse Grains · Rice · Total Grains · Oilseeds · Cotton

### Key parser decisions
- Commodity sections found in narrative: `WHEAT`, `COARSE GRAINS`, `RICE`, `COTTON` (OILSEEDS on a separate page not in keyword scan)
- No explicit revision column in tables — revisions are embedded in narrative text AND computable from the Jun/Jul rows in Table 01 within a single PDF
- Table 01 detection requires pdfplumber on page index 6 with `extract_table()`
- 2002 era reports: pdfplumber shows 0 tables on page 6 (older PDF encoding) — may need `extract_table(table_settings={...})` with explicit bounding box or vertical line hints
- 2008+ era reports: Table 01 detected cleanly, full 3×20 structure returned

### Critical ML finding
**Table 01 contains the current-month vs prior-month production estimates side by side.** You do NOT need to diff two consecutive monthly PDFs to get revisions — a single PDF gives you both the `Jun` and `Jul` row for the same commodity/country. This simplifies the extraction pipeline significantly.

---

## Section B — WAP Archive.org PDFs (1988–2002)

**163 reports · archive.org HTTP · ~25 pages · digital text layer (NOT scanned)**

### Structure — critical finding
- **Pages 2–5**: Full digital text — 3,000–4,700 chars per page. pdfplumber extracts cleanly.
- **Page 6 (table page)**: Text is present but **reversed/mirrored** — pdfplumber reads it as `"1 ELBAT"`, `"yrammuS"`, `"noitcudorP"` (= TABLE 1, Summary, Production backwards). This is a PDF artifact from the FAS publication process in this era.
- **Page 1**: Single char — likely cover scan embedded as image
- Commodity sections found: `WHEAT`, `COARSE GRAINS`, `RICE`, `COTTON`
- Revision language confirmed: "India: Wheat Production Revised Downward"

### Parser decisions
- Narrative pages (0–5): standard pdfplumber, works cleanly
- Table page (6): two options:
  1. Reverse each line's character order after pdfplumber extraction: `line[::-1]`
  2. Textract on page 6 only (~1 page per report × 163 = 163 pages → ~$0.25 at $1.50/1000 pages)
- **Eliminates ~$41 Textract estimate** that assumed all archive.org PDFs were scanned

### Rate limiting
- archive.org enforces rate limits — use `ThreadPoolExecutor(max_workers=6)` with a `threading.Semaphore(6)` and 0.5s delay between requests

---

## Section C — WAP Wayback HTML (1996–2002)

**67 manifest entries · Wayback Machine HTTP · HTML format**

### Structure
- Reports are **multi-page**: TOC page links to `wap1.htm`, `wap2.htm` sub-pages with actual content
- TOC pages (most entries in manifest): contain only navigation, download links (Lotus 123), and a date stamp — no production data
- `key_briefs.html` pages (2002 era): contain commodity brief headers directly inline
- HTML tables are layout-only (no data in `<td>` cells except navigation links)
- Commodity text found only in `key_briefs` pages: `WHEAT`, `RICE`, `COTTON`

### Parser decisions
- **Must follow pagination links** from TOC to `wap1.htm`, `wap2.htm` to reach actual production data
- Sub-page text is plain narrative (no HTML tables with data) — extract with `soup.get_text()`
- 1996–1998 reports: single-page HTML, entire report in one document
- 1999–2002 reports: TOC + 2 sub-pages (wap1.htm = grains/rice, wap2.htm = oilseeds/cotton/sugar)
- Sub-pages are NOT in the current manifest — the fetcher must discover and follow links dynamically

---

## Section D — WASDE Digital PDFs (2000–2026)

**314 reports · S3 · 36–40 pages · ~74k–91k non-whitespace chars**

### Structure
- **Page 0**: Cover + first commodity narrative (starts directly: `WHEAT: U.S. wheat ending stocks...`)
- **Pages 1–4**: Remaining commodity narratives (Coarse Grains, Rice, Oilseeds/Sugar, Cotton/Livestock)
- **Page 5**: Interagency Commodity Estimates Committees (chair names + contact emails)
- **Page 6**: Table of Contents (page numbers for each commodity/region supply-use table)
- **Pages 7–39**: Supply-and-use data tables (ASCII fixed-width, colon-delimited — NOT PDF table objects)
- All 6 commodity sections present: `WHEAT` · `COARSE GRAINS` · `RICE` · `OILSEEDS` · `COTTON` · `SUGAR`
- Section markers: `WHEAT:`, `COARSE GRAINS:` (commodity name + colon) — NOT `OUTLOOK FOR WHEAT`
- Report numbered: `WASDE-358` (2000) through `WASDE-671` (May 2026)
- WASDE issue number on page 0 ties WAP to WASDE: "This report reflects estimates released in WASDE-460"

### Parser decisions
- pdfplumber `extract_text()` works cleanly on all pages
- **For GraphRAG: extract pages 0–6 only** (narrative highlights + committee contacts)
- Pages 7+ are fixed-width ASCII supply-use tables — skip entirely (PSD CSV has this data)
- pdfplumber `extract_tables()` returns 0 tables on all pages — the data tables use colon/space alignment, not PDF table structure
- One file missing from S3: `wasde0706.pdf` (2006-07-12) — NoSuchKey error, manifest entry stale

---

## Section E — WASDE TXT (1995–1999)

**60 reports · S3 · 108k–129k chars**

### Structure
- Plain text, no form-feed (`\x0c`) page breaks
- 1995 vintage: starts with `HDR` header line (`HDR101380000002          WASDE - NARRATIVE`)
- 1996 onwards: starts directly with `WASDE-313 - April 11, 1996` date line
- Section structure: commodity name as direct prefix (`WHEAT:  Projected U.S. 1994/95...`)
- **Does NOT use `OUTLOOK FOR` as a section delimiter** — split on `WHEAT:|COARSE GRAINS:|RICE:|OILSEEDS:|COTTON:|SUGAR:` instead
- ~480–510 lines with numeric data per file (both narrative sentences and ASCII table rows)
- Encoding: latin-1 (1990s USDA TXT convention) — decode as `latin-1` before any processing

### Parser decisions
```python
SECTION_RE = re.compile(
    r"(?m)^(WHEAT|COARSE GRAINS|RICE|OILSEEDS|COTTON|SUGAR|LIVESTOCK):"
)
sections = SECTION_RE.split(text)
```
- For GraphRAG: extract text before first data table (identified by lines with `===` or heavy `:` usage)

---

## Section F — WASDE Scanned PDFs (1973–1994)

**251 reports · S3 · 6–32 pages · 0 chars extracted**

### Structure
- **Confirmed image-only** across all 4 sampled eras — pdfplumber returns 0 non-whitespace chars
- Page counts grow with era: 1973 = 6 pages, 1979 = 16 pages, 1984 = 26 pages, 1994 = 32 pages
- Average: ~19 pages/report → 251 × 19 = **~4,750 total pages**
- One S3 read timeout observed (1989-10-12) — retry with larger `read_timeout` in botocore config

### Parser decision
- **AWS Textract `StartDocumentTextDetection`** (async, text-only)
- For GraphRAG: submit only pages 0–7 (narrative highlights) — skip table-heavy tail pages
- Skip pages: reduces billable pages ~40% (4,750 → ~2,850)

---

## ML vs GraphRAG Usage Summary

| Source | ML use | GraphRAG use |
|---|---|---|
| WAP direct PDFs (A) | **Primary** — Table 01 gives month-over-month country production revisions directly | Secondary — narrative country briefs |
| WAP archive.org (B) | **Primary** — extends revision time series to 1988 (drought, FSU collapse era) | Secondary — narrative |
| WAP Wayback HTML (C) | Secondary — if WAP leading-indicator feature proves valuable post-2002 validation | Low — narrative only |
| WASDE digital (D) | **None** — PSD CSV already has all WASDE monthly vintages via `Month` column | **Primary** — commodity outlook narrative |
| WASDE TXT (E) | **None** — PSD CSV covers 1995–1999 | **Primary** — commodity outlook narrative |
| WASDE scanned (F) | **None** — PSD CSV covers pre-1995 | Secondary — historical narrative, Textract required |

### Build order (WAP + WASDE only — all other sources deferred)

**Text extraction (WASDE → `text/source=usda_wasde/`):**
1. WASDE digital PDFs (D, 2000–2026) — pdfplumber pages 0–6, section split on commodity names
2. WASDE TXT (E, 1995–1999) — latin-1 decode, strip HDR header, regex section split
3. WASDE scanned (F, 1973–1994) — Textract async, pages 0–7 only (~$4)

**ML + text extraction (WAP → `bronze/production/source=usda_wap/` + `text/source=usda_wap/`):**
4. WAP direct PDFs (A, 2002–2026) — pdfplumber Table 01 to bronze; pdfplumber narrative to text
5. WAP archive.org (B, 1988–2002) — reversed-text handling for Table 01; pdfplumber narrative to text
6. WAP Wayback HTML (C, 1996–2002) — BeautifulSoup + pagination follower to text only

**Deferred (separate tasks, not current scope):**
- USDA GAIN reports (~3,700 PDFs) → `text/source=usda_gain_{commodity}/...`
- CONAB PDFs, FNC monthly PDFs, USDA FAS WMT, WB CMO Outlook, MPOC highlights

---

## Processing Strategy

### Concurrency plan

| Phase | Files | Method | Est. time |
|---|---|---|---|
| WAP direct + WASDE digital | ~660 files | `ThreadPoolExecutor(30)` in a single script | 3–5 min |
| WAP archive.org | ~163 files | `ThreadPoolExecutor(6)` with semaphore | 15 min |
| WASDE scanned | 251 files | Textract async (100 concurrent) | 10–15 min OCR |
| Wayback HTML TOC + sub-pages | ~84 + N | `ThreadPoolExecutor(6)` | 10 min |

### Why serial is too slow
- S3 GETs are pure network I/O — blocked waiting on each response before starting the next
- pdfplumber holds the GIL during PDF parsing — no concurrency benefit within a single thread
- archive.org HTTP has 1.5s politeness delay per request — serial = 163 × 2s = 5+ min wall time even ignoring parse time

### ThreadPoolExecutor pattern for S3 sources
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_and_parse(s3_client, key: str) -> dict:
    data = s3_client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    return parse_wap_pdf(data, key)   # pdfplumber work runs in thread

with ThreadPoolExecutor(max_workers=30) as pool:
    futures = {pool.submit(fetch_and_parse, s3, key): key for key in all_keys}
    for fut in as_completed(futures):
        results.append(fut.result())
```
- 30 workers saturates S3 bandwidth without throttling for ~1–3 MB PDFs
- pdfplumber CPU work overlaps with next S3 download in a different thread

### Textract async pattern for scanned WASDE
```python
import boto3, time

textract = boto3.client("textract", region_name="us-east-1")

# Submit all jobs (non-blocking)
job_ids = {}
for key in scanned_keys:
    resp = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": BUCKET, "Name": key}}
    )
    job_ids[resp["JobId"]] = key

# Poll until all complete
while job_ids:
    for job_id in list(job_ids):
        resp = textract.get_document_text_detection(JobId=job_id)
        if resp["JobStatus"] in ("SUCCEEDED", "FAILED"):
            process_result(resp, job_ids.pop(job_id))
    time.sleep(5)
```

---

## Textract Cost Estimate (Section F Only)

**~$7 total** for all 251 WASDE scanned PDFs using `StartDocumentTextDetection`.

| API | Rate | All 251 reports (~4,750 pages) | Pages 0–7 only (~2,850 pages) |
|---|---|---|---|
| `StartDocumentTextDetection` (text) | $1.50 / 1,000 pages | **~$7.15** | **~$4.30** |
| `AnalyzeDocument` (tables) — **do not use** | $15.00 / 1,000 pages | ~$71.25 | ~$42.75 |

### Cost mitigation strategies

**1. Skip non-narrative pages (biggest lever)**

The early WASDE scanned reports (1973–1984) are 6–26 pages. Pages 0–7 contain all narrative highlights; the tail pages are supply-use data tables redundant with PSD CSV. Skipping tail pages saves ~40% of billable pages:

```python
# Split PDF, submit only first 8 pages to Textract
import pypdf
writer = pypdf.PdfWriter()
reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
for i in range(min(8, len(reader.pages))):
    writer.add_page(reader.pages[i])
buf = io.BytesIO()
writer.write(buf)
# Submit buf.getvalue() to Textract
```
Rough saving: 4,750 → 2,850 pages → **cost drops from $7 to $4**

**3. Use `DetectDocumentText`, never `AnalyzeDocument`**

`AnalyzeDocument` (tables + forms) costs 10× more and is only warranted for structured table extraction. For GraphRAG text chunks, `StartDocumentTextDetection` returns identical raw text. Using `AnalyzeDocument` would cost ~$71 instead of ~$7 — a $64 avoidable overspend.

**4. Cache OCR output aggressively — never re-process**

Write the parsed `document.json` to `text/` immediately after each Textract job completes:

```
text/source=usda_wasde/release_date={date}/document.json
```

The extraction job checks for this key (`s3.head_object`) before submitting to Textract. This is the same idempotency check used by pdfplumber and TXT extraction — if `document.json` exists, the file is skipped regardless of method.

**5. AWS free tier**

`DetectDocumentText` includes 1,000 free pages/month for the first 3 months on new accounts. If the account qualifies, the ~1,000 highest-priority pages (1988–1994 era, ~56 reports) could be OCR'd for free. Stage the 1973–1988 era last.

---

## Known Issues & Edge Cases

| Issue | Section | Details |
|---|---|---|
| Missing S3 key | D | `wasde0706.pdf` (2006-07-12) returns `NoSuchKey` — manifest entry stale |
| S3 read timeout | F | `wasde1089.pdf` (1989-10-12) timed out — retry with `read_timeout=120` in `botocore.config.Config` |
| Reversed table text | B | Page 6 of archive.org PDFs — table text read right-to-left; reverse each line or use Textract on that page only |
| WAP table undetected on 2002 era | A | pdfplumber returns 0 tables on 2002-08 page 6 despite 2008+ working — try `extract_table(table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"})` |
| Wayback TOC-only pages | C | Most manifest entries point to TOC pages with no data — follow `wap1.htm`, `wap2.htm` links for actual content |
| HDR header line | E | 1995 TXT files begin with `HDR101380000002          WASDE - NARRATIVE` — strip before parsing |
| pdfplumber gray color warning | A/B/D | `Cannot set gray non-stroke color because /'P0' is an invalid float value` — cosmetic stderr warning, does not affect text extraction |
