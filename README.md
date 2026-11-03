# SEC Financial Analyst

Current release: **v1.0.0** (`VERSION`). Downloadable Windows distribution
includes a separate [release guide](./RELEASE_README.md); the project README
remains the detailed reference for development, data handling, and analysis
methodology.

A local-first Python/SQL workflow for retrieving SEC 10-K/10-Q filings, mapping
SEC CompanyFacts XBRL into normalized financial statements, calculating key
ratios, and producing evidence-linked company financial-health writeups.

The workflow combines the SEC analyst and portfolio-risk projects. Retrieval,
statement normalization, ratio analysis, public-equity market-risk calculations,
optional web research, and synthesis are coordinated as explicit analysis
agents. It is intentionally deterministic: filings and statement values are
never sent to a language-model provider or web-search API. Web search receives
only the company name. It is not affiliated with Binance. The analysis is a
research aid, not investment advice.

## Features

- Retrieves company submissions and standardized XBRL facts from the SEC EDGAR
  APIs using a user-supplied contact email in the required `User-Agent`.
- Selects recent 10-K/10-Q accessions and maps balance-sheet instant facts and
  income/cash-flow duration facts to the matching accession and period.
- Stores filing metadata, normalized statement line items, and ratios in
  SQLite, and saves raw SEC responses and JSON reports in a user-selected folder.
- Calculates liquidity, solvency, profitability, and cash-flow ratios. Missing
  values and zero denominators are reported as unavailable, not fabricated.
- Produces a financial-health writeup with evidence-linked findings and
  potential operational solutions; saves JSON and Markdown reports.
- Integrates portfolio-risk VaR/CVaR, seeded Monte Carlo, and stress analysis
  for read-only public-equity daily price history. This is market-price risk,
  not company solvency risk.
- Supports optional Brave Search API web research and read-only Yahoo Finance
  quote/history lookups. Search snippets are unverified research leads.
- Accepts user-supplied multi-period CSV statements for private companies,
  research labs, and organizations without standardized SEC filings.
- Provides a Streamlit UI for the SEC workflow, a chosen local workspace, and
  offline JSON uploads.
- Includes synthetic SEC-shaped sample data and offline edge-case tests.

## Quick start (Windows)

Double-click `start_analyst.bat`. It creates a project virtual environment if
needed, installs the declared dependencies, starts the local web server, and
opens the page after the server reports ready. Keep the launcher window open
while using the app; press Ctrl+C in that window to stop it.

The batch file requires Python 3.12 or later. For a manual setup, use:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\generate_samples.py
streamlit run app.py
```

In the sidebar, enter a contact email for SEC requests and choose a folder the
application is allowed to manage. Enter a company alias, ticker, or CIK to analyze recent filings; NVIDIA and the
common misspelling “Nividia” resolve to NVDA. A real email is required for
SEC requests. Set `BRAVE_SEARCH_API_KEY` to enable optional public web research.
Public equity-price history is fetched read-only when a ticker is available.
Alternatively, upload both a SEC submissions JSON file and a Company
Facts JSON file, save them into the selected folder, and run offline analysis.
The bundled samples are synthetic and can be copied/uploaded to try the offline
workflow. `samples/edge_cases.json` documents zero-denominator, missing-input,
and derived-margin examples covered by the tests.

For private or non-SEC organizations, upload a UTF-8 CSV with one row per
reporting period to **Private or non-SEC company financials**. Required columns
are `period_end` and `currency`; other supported statement columns may be blank,
and blank values stay unavailable rather than becoming zero. Provide an explicit
three-letter currency code on every row. Reports clearly label these
as user-supplied data. The analyzer does not invent SEC filings for Votee AI,
Wonderful, or PwC; use verified company statements. “Wonderful” may refer to
more than one entity and needs disambiguation. Company names sent to Brave are
search queries only; uploaded financial statement values remain local.

To run tests without contacting EDGAR:

```powershell
python -m unittest discover -s tests -v
```

## Workspace and data handling

The selected folder is the boundary for application-managed data. The app
creates `incoming`, `sec_cache`, `reports`, and `financials.sqlite3` there.
Uploaded files are stored under `incoming`; downloaded SEC payloads go under
`sec_cache`; analysis output goes under `reports`. JSON discovery for offline
analysis is limited to the selected folder and its descendants. File names
from uploads are reduced to safe basenames.

SEC filings and reports are not uploaded to any AI service. SEC API access
requires an identifiable `User-Agent`, including a valid contact email; the
application asks for that value at runtime rather than shipping a fake identity.
Market data requests contain only the selected ticker. Optional web search
requests contain only the company name and a general financial-context query.
Search snippets are not treated as verified evidence; follow links to original
sources and corroborate material claims against filings.

The market-risk section uses one year of daily Yahoo Finance closes to calculate
historical/parametric VaR and CVaR, seeded Monte Carlo, and an illustrative
single-stock shock. It describes historical equity-price variability only; it
is not a forecast, issuer credit assessment, valuation, or the company's
balance-sheet risk.

## Ratio definitions and limitations

The ratios use the selected filing's reported values, in the filing's reported
currency and period. The quick ratio subtracts reported inventory and prepaid
expenses from current assets when those line items are available. Liabilities
to equity is a broad balance-sheet leverage proxy, not interest-bearing
debt-to-equity. Free cash flow is operating cash flow less the absolute value
of reported capital expenditures. Ratios are omitted when required source
facts are missing or a denominator is zero. SEC CompanyFacts only exposes
standardized facts; issuer-specific custom XBRL tags may not be represented.

## Project layout

```text
app.py
start_analyst.bat   Double-click local Windows launcher
launch.py           Waits for server health, opens browser, cleans up on exit
sec_analyst/        EDGAR, normalization, ratios, health, market/search agents
portfolio_risk/     VaR/CVaR, Monte Carlo, and scenario stress engine
sql/schema.sql      SQLite schema
scripts/            Synthetic sample generator
samples/            Synthetic 10-K/10-Q submissions and CompanyFacts JSON
tests/              Offline tests and edge cases
```
