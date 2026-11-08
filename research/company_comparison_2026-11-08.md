# NVIDIA, Microsoft & Alphabet - SEC filing comparison

**As of 2026-11-08.** Latest available SEC 10-Q compared with the nearest prior-year 10-Q. Values in USD. This is a financial screening, not an investment recommendation.

## Quick comparison

| Company | Latest quarter | Revenue | YoY revenue | Net income | YoY net income | Operating margin | Net margin | Current ratio | Liabilities / assets |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [NVDA](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm) | 2026-07-26 | $96.2B | +105.9% | $59.7B | +125.9% | 66.2% | 62.0% | 4.59x | 28.5% |
| [MSFT](https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/msft-20260930.htm) | 2026-09-30 | $92.3B | +18.8% | $36.6B | +32.0% | 49.8% | 39.7% | 1.22x | 39.6% |
| [GOOGL](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/goog-20260930.htm) | 2026-09-30 | $127.6B | +24.7% | $26.5B | -24.3% | 31.8% | 20.7% | 2.79x | 32.5% |

## Findings

### NVIDIA CORP (NVDA)
- Filed **2026-08-26** for period ending **2026-07-26**; prior-year comparator ended 2025-07-27. [Latest filing](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm) | [Prior-year filing](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000209/nvda-20250727.htm).
- Revenue $96.2B (+105.9% YoY); operating income $63.7B (+124.1% YoY); net income $59.7B (+125.9% YoY).
- Operating margin 66.2% (+5.4 pp YoY); net margin 62.0% (+5.5 pp YoY). Liquidity: current ratio 4.59x; quick ratio 3.85x.
- Strongest reported growth and operating profitability in this comparison. Current ratio is ample; high margins and rapid growth do not remove semiconductor-cycle, customer-concentration, export-control, or execution risks, which these ratios do not measure.

### MICROSOFT CORP (MSFT)
- Filed **2026-10-28** for period ending **2026-09-30**; prior-year comparator ended 2025-09-30. [Latest filing](https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/msft-20260930.htm) | [Prior-year filing](https://www.sec.gov/Archives/edgar/data/789019/000119312525256321/msft-20250930.htm).
- Revenue $92.3B (+18.8% YoY); operating income $45.9B (+21.0% YoY); net income $36.6B (+32.0% YoY).
- Operating margin 49.8% (+0.9 pp YoY); net margin 39.7% (+4.0 pp YoY). Liquidity: current ratio 1.22x; quick ratio 1.21x.
- Reported quarterly free cash flow is $18.6B versus $25.7B a year earlier (-27.4%); capex was $39.4B versus $19.4B a year earlier. The cash-flow/capex increase merits monitoring alongside strong operating growth.
- Most balanced high-margin profile of the three in the reported quarter; liquidity is tighter than NVIDIA's or Alphabet's on the current-ratio screen. Its lower one-day historical VaR is relative to this sample and not a forecast.

### Alphabet Inc. (GOOGL)
- Filed **2026-10-29** for period ending **2026-09-30**; prior-year comparator ended 2025-09-30. [Latest filing](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/goog-20260930.htm) | [Prior-year filing](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000091/goog-20250930.htm).
- Revenue $127.6B (+24.7% YoY); operating income $40.6B (+29.9% YoY); net income $26.5B (-24.3% YoY).
- Operating margin 31.8% (+1.3 pp YoY); net margin 20.7% (-13.4 pp YoY). Liquidity: current ratio 2.79x; quick ratio 2.69x.
- Operating income grew +29.9%, while GAAP net income fell. The SEC CompanyFacts line `EquitySecuritiesFvNiGainLoss` shows a quarter fair-value result of -$8.7B versus $10.7B a year earlier (pre-tax swing -$19.4B); this volatile non-operating item helps explain the divergence and is not a recurring operating-margin measure.
- Stronger reported current ratio than Microsoft, though liabilities/assets increased versus the year-ago quarter. The fair-value investment result makes single-quarter GAAP net-income comparisons unusually noisy.

## Market-risk screen

Project RiskEngine historical 95% one-day risk, based on the 250 daily return observations ending 2026-11-06 and scaled to a hypothetical $10,000 single-stock position:

| Ticker | Reference share price (Nov 6 close) | Daily volatility | 95% historical VaR | 95% historical CVaR |
|---|---:|---:|---:|---:|
| NVDA | $186.64 | 2.4% | $399 / $10k | $500 / $10k |
| MSFT | $530.61 | 2.1% | $285 / $10k | $410 / $10k |
| GOOGL | $284.78 | 2.1% | $295 / $10k | $472 / $10k |

Historical VaR estimates a loss threshold from the selected past returns; CVaR estimates average loss in the tail beyond that threshold. These single-stock results are not forecasts and do not account for valuation, portfolio diversification, or fundamental solvency.

## Overall read-through

On the latest reported quarter, NVIDIA leads on growth and profitability but also has the highest observed daily return volatility. Microsoft shows steadier growth, high operating profitability, and lower historical VaR, with a large capex/FCF swing to watch. Alphabet's revenue and operating income grew, but quarterly net income fell because of a large adverse equity-security fair-value swing; its underlying operating margin improved. The comparison does not establish which stock is attractive without valuation, forecasts, and risk tolerance.

## Method and limitations

- Statements and ratios were run through the project's SEC filing, CompanyFacts normalization, validation, SQLite/DuckDB lineage, ratio, health-summary, and market-risk workflow. Raw submissions and CompanyFacts payloads are preserved under `data/sec_cache/`; per-company outputs are under `data/companies/`.
- SEC filings are linked above; raw facts were fetched from SEC submissions and CompanyFacts endpoints. Market prices/returns are read-only Yahoo Finance chart API data, observed at the timestamp shown in the per-company report.
- SEC data retrieval succeeded using a descriptive User-Agent. No contact email was supplied or fabricated. The project's UI still requires a user-provided SEC contact email for future live retrieval.
- Revenue, income, and margin comparisons use corresponding reported 10-Q quarters from each issuer. The quarter ends differ for NVIDIA vs. the other two.
- Quarterly cash-flow comparison is incomplete: standalone quarterly operating-cash-flow/capex facts were not available to the project normalizer for NVIDIA and Alphabet, so their FCF is intentionally not estimated. Microsoft Q1 cash flows are available.
- Quick ratio follows the project implementation; prepaid-expense facts were not available and therefore could not be deducted. Custom XBRL concepts may not be represented in standardized CompanyFacts.
- Valuation multiples, forward estimates, segment performance, and comprehensive non-GAAP reconciliations are outside this run.
