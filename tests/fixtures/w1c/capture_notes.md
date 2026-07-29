# W1c LIVE CAPTURE NOTES -- 2026-07-29, headless Playwright (S1/S2 probe session)

Everything below was captured LIVE through a headless Chromium session on 2026-07-29 ~16:40Z.
These are the producer contracts; the fixture files beside this note carry the raw bodies.

## DCE (Dalian) -- palm olein + 4 soy contracts
- Ruishu WAF: the JS challenge SETTLES in headless (~5-10s of redirect dance, then content).
  Plain requests = 412 from BOTH residential and Fargate (S2: no datacenter discrimination).
- Daily quote API (after challenge): GET /dcereport/quote/delay/futureData?variety={v}
  -> JSON {success, code:200, data:[per-contract]}. Fields per contract: contractId ("p2608"
  = variety + YYMM), openPrice/highPrice/lowPrice/lastPrice, volume, openInterest,
  closePrice, settlePrice, preClosePrice, preSettlePrice, tradeDate, quoteTime, tradeTime.
  INTRADAY settlePrice/closePrice are 0.0 -- they populate AFTER the session close; the
  producer must fire post-close (>=15:30 Beijing) and treat 0.0 as the UNDEF sentinel,
  never a price. preSettlePrice is the PRIOR session settle (nonzero intraday).
- HISTORY: GET /dcereport/quote/history/download?type=1&year={YYYY}&variety={v}
  -> VERIFIED 200, content-disposition attachment;filename={v}_ftr.xlsx. **FORMAT DECODED**
  (fixture dce_history_2016_p.xlsx, 188,440 B, 2,928 data rows): xlsx workbook, ONE sheet,
  EVERY cell t="inlineStr" (sharedStrings empty; all values are STRINGS with comma
  thousands-separators, e.g. "4,580" / "118,203,200"). Header row (Chinese, col A..O):
  商品名称=commodity name, 合约名称=contract (e.g. p1601), 交易日期=trade date YYYYMMDD,
  开盘价=open, 最高价=high, 最低价=low, 收盘价=close, 前结算价=prev settle, 结算价=settle,
  涨跌=change, 涨跌1=change1, 成交量=volume, 持仓量=open interest, 持仓量变化=OI change,
  成交额=turnover. UNTRADED days print open/high/low/volume as "0" while close/settle still
  print real values -- same 0-sentinel rule as the daily API. Parse with openpyxl (or
  stdlib zipfile+regex on inlineStr); pin the header row EXACTLY, fail closed on drift.
- Varieties: p (palm olein), a (soybeans no.1), b (soybeans no.2), m (soybean meal),
  y (soybean oil) -- match CONTRACT_MAP's five dce slugs.

## Euronext (MATIF) -- milling wheat / maize / rapeseed
- NO WAF. Fargate plain-requests GET of the product page = 200 (247KB) but the QUOTE TABLE
  is client-rendered (the AES {ct,iv,s} payload) -- the table exists only in a BROWSER DOM.
- Headless renders it fully: table#future-prices-table with a thead ("Delivery", Bid,
  Ask(hidden), Last, Time, +/-, Day Vol., Open, High, Low, Settl., O.I) and all expiries.
  Fixture: euronext_ebm_table.html (complete table outerHTML, whitespace-normalized).
  Two row shapes: traded expiries carry Last/Time/Vol/OHL; untraded back months
  (data-lasttradesdate="-") carry only Bid/Ask/Settl./O.I with "-" sentinels. Settl.
  prints for EVERY row. Delivery month is parsed from the row's anchor href md=DD-MM-YYYY
  (preferred, unambiguous) or the "Sep 2026" anchor text.
- Products ALL VERIFIED LIVE 2026-07-29 at
  https://live.euronext.com/en/product/commodities-futures/{SLUG}:
  EBM-DPAR "Milling Wheat" (12 rows), EMA-DPAR "Corn / Mais" (10 rows),
  ECO-DPAR "Rapeseed / Colza" (10 rows) -- identical table shape and id on all three.

## Bursa Malaysia -- FCPO (the flagship palm leg)
- Cloudflare: 403 + Cf-Mitigated: challenge for plain requests EVERYWHERE (both IP classes),
  BUT the challenge CLEARS in headless Chromium (no Turnstile presented; a real page loads).
- The recon-era prices path is DEAD (404): /market/derivatives/derivatives_prices.
  LIVE route: https://www.bursamalaysia.com/market_information/derivatives_prices
- DATA API (session-cookied; call in-page or with the cleared cookie jar):
  GET /api/v1/derivatives_prices/derivatives_prices?code=FCPO&ses=day&per_page=50&page=1
  -> {recordsTotal: 24, data: [[13 positional elements], ...]}, 24 delivery months.
  **COLUMN MAPPING RESOLVED** against the rendered thead (verified cell-by-cell vs the
  rendered first row, OI 9,202 == the anchor text):
    0=NO(rank int), 1=NAME(html div, "FCPO"), 2=MONTH("Aug 2026"), 3=OPEN, 4=BID, 5=ASK,
    6=LAST DONE, 7=CHANGE(html span, "+11.0000"), 8=HIGH, 9=LOW, 10=VOL,
    11=OI(html anchor carrying stock_id + OI as anchor text WHEN traded; plain "-" or a
    plain number on quiet back months -- parser must handle all three), 12=SETT. PRICE.
  Numbers are strings w/ comma separators + 4dp; "-" is the untraded sentinel; SETT. PRICE
  prints for ALL 24 months. Still pin the rendered thead per run (JSE precedent, fail
  closed on drift). Fixtures: bursa_fcpo_api_sample.json (day) +
  bursa_fcpo_api_night_sample.json.
- ses RESOLVED from the page's own selector: day="Day (T)", night="After-Hours (T+1)",
  all="All". EOD producer uses **ses=day** (the T session settle is THE daily settle);
  night rows label "FCPO (T+1)". code selector also offers FPKO/FSOY/FEPO/FPOL etc. for
  later legs. History depth: the API serves current prices only -- no date param observed;
  Bursa is a FORWARD-ACCUMULATION leg (no backfill), like CEPEA daily.

## Fixture inventory (all captured live 2026-07-29, all parse-validated)
- dce_futureData_p.json          -- daily quote API body, 12 contracts p2608..p2707.
  NOTE: captured DURING the night session -- tradeDate had already rolled to 20260730 and
  settlePrice/closePrice are 0.0 everywhere. This is the NOT_READY shape: the EOD producer
  fires after the DAY close (>=15:30 Beijing, BEFORE 21:00 night open) and must treat
  "settlePrice==0.0 across the board" as not-ready (abort/retry), never as prices.
- dce_history_2016_p.xlsx        -- real vendor xlsx, 2,928 rows, format decoded above.
- euronext_ebm_table.html        -- complete rendered table outerHTML (EBM, 12 expiries).
- bursa_fcpo_api_sample.json     -- ses=day, 24 months, 13-col mapping above.
- bursa_fcpo_api_night_sample.json -- ses=night (T+1) variant for the parser's label guard.

## Session/runtime implications for the producers
- One browser context per venue-fetch; DCE + Bursa need the challenge dance before their
  API calls; Euronext needs plain DOM scrape. All three run headless (S1 PASS).
- The residual S2 question (do the challenges SOLVE from a datacenter IP) is answered by
  running these producers once on Fargate with the browser image -- design for a clean
  CHALLENGE_FAILED exit code so that first run IS the probe.
