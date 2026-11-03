# SEC Financial Health Analyst — v1.1.0

A local-first company financial-health screening app for SEC filings and
user-supplied financial statements.

## Start the web app on Windows

1. Install Python 3.12 or later.
2. Extract this ZIP to a folder you can write to.
3. Double-click `start_analyst.bat`.
4. Keep the launcher window open while using the app. Press Ctrl+C there to
   stop the local server.

The launcher creates a project-local Python environment, installs the
requirements, starts Streamlit on `127.0.0.1:8501`, and opens your browser.
Alternatively, follow the manual setup in `README.md`.

The default launch installs only the core application. To opt in to Dask,
Prefect, Alpaca WebSocket, or Kafka/Redpanda features, run
`python -m pip install -r production_requirements.txt` in the extracted project
environment. These integrations require your own credentials and/or cluster
infrastructure.

## Analyze a company

- **Public filer:** Enter its ticker or CIK and provide a real contact email for
  the SEC request User-Agent. NVIDIA, Nividia, and NVDA resolve to NVIDIA.
- **Private company or research organization:** Download the CSV template from
  the app, enter verified financial statement values with an explicit
  three-letter currency code, and upload it. Blank values remain unavailable;
  they are never assumed to be zero.
- **Optional public market data:** When a ticker is available, the app requests
  read-only daily price history and reports equity-price VaR/CVaR, Monte Carlo,
  and illustrative stress metrics. Dask execution is optional; choose it in
  the app. Simulation speed depends on your host and settings. These are not
  company solvency measures.
- **Stress testing:** Historical replay uses the dates in the supplied price
  history. Rate shocks use modified-duration first-order sensitivity. Named
  Basel/Federal Reserve reference scenarios are illustrative templates, not
  official regulatory scenarios or capital calculations.
- **Issuer taxonomies:** Upload a `taxonomy_mappings.json` in the selected
  managed workspace for supported extension tags (see
  `samples/taxonomy_mappings.example.json`). Non-GAAP facts remain
  separate from GAAP ratios. The report links to the accession and Inline
  XBRL element when available; SEC CompanyFacts does not provide printed page
  numbers.
- **Streaming:** The optional `run_alpaca_kafka_stream` adapter sends Alpaca
  minute bars and rolling risk snapshots to Kafka. It does not submit trades.
  Provide API keys, feed entitlements, and broker configuration via environment
  variables. Kafka defaults to plaintext for local development; configure
  `KAFKA_SECURITY_PROTOCOL` and the corresponding SASL/TLS environment
  variables for secured brokers.
- **Large simulations:** A development-host benchmark completed 1,000,000
  paths over 8 assets in 0.819 seconds with Dask (Windows 11, Python 3.12.10).
  Other hardware, horizons, and asset counts will differ; run the included
  benchmark rather than assuming this throughput.
- **Optional web research:** Set `BRAVE_SEARCH_API_KEY` in the environment to
  enable search. Search results are unverified leads, not financial evidence.

Votee AI, Wonderful, and PwC do not have bundled or fabricated financial
statements. Supply verified statements to assess a private or ambiguous entity.

## Privacy and limitations

SEC filings and uploaded statement values are processed and stored locally.
Statement values are not sent to search or AI services. Optional market
requests send the selected ticker; optional search sends the company name and a
general research query. Reports are screening aids, not an audit, credit
rating, valuation, investment recommendation, or substitute for professional
advice.

See `README.md` for detailed metric definitions, data handling, sample inputs,
and test instructions.
