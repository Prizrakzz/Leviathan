# Leviathan
<p align="center">
  <img src="assets/Leviathan-Banner.png" alt="Leviathan Banner" width="100%">
</p>
Leviathan is an AWS-native commodity alternative-data platform that ingests weather, LME warehouse stocks, USDA WASDE, Arabic news sentiment, and other market-relevant datasets into a reproducible S3/Snowflake research lakehouse for ensemble ML and quant research.

## Setup

1. Clone the repo
2. Create a virtual environment: `python -m venv .venv`
3. Activate it: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Mac/Linux)
4. Install the package: `pip install -e .`
5. Copy `.env.example` to `.env` and fill in your values