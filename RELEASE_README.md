# SEC Financial Health Analyst — v1.0.0

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

## Analyze a company

- **Public filer:** Enter its ticker or CIK and provide a real contact email for
  the SEC request User-Agent. NVIDIA, Nividia, and NVDA resolve to NVIDIA.
- **Private company or research organization:** Download the CSV template from
  the app, enter verified financial statement values with an explicit
  three-letter currency code, and upload it. Blank values remain unavailable;
  they are never assumed to be zero.
- **Optional public market data:** When a ticker is available, the app requests
  read-only daily price history and reports equity-price VaR/CVaR, Monte Carlo,
  and illustrative stress metrics. These are not company solvency measures.
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
