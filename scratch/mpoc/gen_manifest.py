"""Generate configs/sources/mpoc_archive.yaml from probe JSON output files."""
import json
import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

trade_lines = []
for year in range(2009, 2024):
    trade_lines.append("  - release_type: trade_statistics")
    trade_lines.append(f"    year: {year}")
    trade_lines.append(f"    stat_url: \"https://mpoc.org.my/monthly-palm-oil-trade-statistics-{year}/\"")

stock_lines = [
    "  - release_type: stock_comparison",
    "    stat_url: \"https://mpoc.org.my/market-insight/stock-comparison/\"",
]

price_lines = [
    "  - release_type: competitive_prices",
    "    stat_url: \"https://mpoc.org.my/market-insight/daily-palm-oil-prices/\"",
]

with open(ROOT / "data/mpoc/market_highlights_index.json", encoding="utf-8") as f:
    articles = json.load(f)

article_lines = []
for art in articles:
    article_lines.append("  - release_type: market_highlights")
    article_lines.append(f"    slug: \"{art['slug']}\"")
    article_lines.append(f"    stat_url: \"{art['url']}\"")

today = str(datetime.date.today())
n_articles = len(articles)

content = (
    "# MPOC (Malaysian Palm Oil Council) - market intelligence and trade statistics\n"
    "# Source : Malaysian Palm Oil Council\n"
    "# URL    : https://mpoc.org.my\n"
    "# CMS    : WordPress; no WAF; standard requests with Chrome UA works\n"
    "#\n"
    "# Four series:\n"
    "#   trade_statistics   - Monthly Palm Oil Trade Statistics (2009-2023, 15 pages)\n"
    "#   stock_comparison   - Stock Comparison single live page (multi-country oils & fats)\n"
    "#   competitive_prices - Daily Palm Oil Prices single live page (CPO vs SBO vs SFO)\n"
    f"#   market_highlights  - Individual market analysis articles ({n_articles} articles)\n"
    "\n"
    "releases:\n"
    "\n"
    "  # ---------------------------------------------------------------------------\n"
    "  # trade_statistics: 2009-2023 (15 entries)\n"
    "  # URL pattern: https://mpoc.org.my/monthly-palm-oil-trade-statistics-{YYYY}/\n"
    "  # Validation marker: EXPORTS TO MAJOR COUNTRIES\n"
    "  # ---------------------------------------------------------------------------\n"
    + "\n".join(trade_lines) + "\n"
    "\n"
    "  # ---------------------------------------------------------------------------\n"
    "  # stock_comparison: single live page; re-run without --skip-existing-s3 to refresh\n"
    "  # Validation marker: OILS AND FATS ENDING STOCKS\n"
    "  # ---------------------------------------------------------------------------\n"
    + "\n".join(stock_lines) + "\n"
    "\n"
    "  # ---------------------------------------------------------------------------\n"
    "  # competitive_prices: single live page; re-run without --skip-existing-s3 to refresh\n"
    "  # Validation markers: CPO and SBO\n"
    "  # ---------------------------------------------------------------------------\n"
    + "\n".join(price_lines) + "\n"
    "\n"
    f"  # ---------------------------------------------------------------------------\n"
    f"  # market_highlights: {n_articles} articles (spidered {today})\n"
    f"  # Validation: min-size guard only (no structural marker)\n"
    f"  # ---------------------------------------------------------------------------\n"
    + "\n".join(article_lines) + "\n"
)

out_path = ROOT / "configs/sources/mpoc_archive.yaml"
out_path.write_text(content, encoding="utf-8")
print(f"Written: {out_path}")
print(f"  trade_statistics:    15")
print(f"  stock_comparison:     1")
print(f"  competitive_prices:   1")
print(f"  market_highlights:  {n_articles}")
print(f"  total:              {15 + 1 + 1 + n_articles}")
