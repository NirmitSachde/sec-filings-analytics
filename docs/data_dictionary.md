# Data Dictionary — SEC Filings Analytics Platform

## Schema Overview

| Schema | Purpose |
|---|---|
| `raw` | Ingested data directly from EDGAR parsers |
| `ref` | Reference/lookup tables (ticker mappings, overrides) |
| `staging` | dbt staging models — type cleanup, NULL handling |
| `intermediate` | dbt intermediate — normalized, enriched datasets |
| `mart` | dbt marts — analytics-ready aggregations |
| `vec` | pgvector tables for semantic search |

---

## Raw Tables

### `raw.filing_index`
Master index of all tracked EDGAR filings.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) UK | SEC filing accession number |
| form_type | VARCHAR(20) | Filing type (4, 13F-HR, 10-K, etc.) |
| cik | INTEGER | Filer's Central Index Key |
| company_name | VARCHAR(200) | Company name from index |
| date_filed | DATE | Filing date |
| filename | VARCHAR(500) | EDGAR relative path |
| fetched_at | TIMESTAMPTZ | When raw documents were downloaded |
| parsed_at | TIMESTAMPTZ | When parsing completed |
| created_at | TIMESTAMPTZ | Row creation time |

### `raw.insider_transactions`
Individual insider transactions from Form 4 filings.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) | Parent filing |
| filing_date | DATE | Date filed with SEC |
| transaction_index | INTEGER | Position within filing |
| owner_cik | INTEGER | Reporting owner CIK |
| owner_name | VARCHAR(200) | Owner full name |
| is_director | BOOLEAN | Director relationship |
| is_officer | BOOLEAN | Officer relationship |
| is_ten_percent_owner | BOOLEAN | 10%+ owner |
| is_other | BOOLEAN | Other relationship |
| officer_title | VARCHAR(200) | Title if officer |
| issuer_cik | INTEGER | Issuing company CIK |
| issuer_name | VARCHAR(200) | Issuing company name |
| issuer_ticker | VARCHAR(20) | Trading symbol |
| security_title | VARCHAR(200) | Security being transacted |
| transaction_date | DATE | Date of transaction |
| transaction_code | VARCHAR(5) | P=Purchase, S=Sale, A=Award, M=Exercise, G=Gift |
| shares | FLOAT | Number of shares |
| price_per_share | FLOAT | Price per share in USD |
| shares_after | FLOAT | Post-transaction holdings |
| direct_or_indirect | VARCHAR(1) | D=Direct, I=Indirect |
| is_derivative | BOOLEAN | Derivative transaction flag |
| is_10b5_1 | BOOLEAN | Filed under Rule 10b5-1 plan |

### `raw.holdings_positions`
Institutional holdings from 13F-HR filings.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) | Parent filing |
| filer_cik | INTEGER | Institutional manager CIK |
| filer_name | VARCHAR(200) | Manager name |
| period_of_report | DATE | Reporting period end date |
| name_of_issuer | VARCHAR(200) | Held company name |
| cusip | VARCHAR(9) | CUSIP-9 identifier |
| ticker | VARCHAR(20) | Mapped trading symbol |
| value | BIGINT | Market value in USD |
| shares | BIGINT | Number of shares/principal |
| share_type | VARCHAR(10) | SH=Shares, PRN=Principal |
| investment_discretion | VARCHAR(10) | SOLE, DEFINED, OTHER |
| voting_sole | BIGINT | Sole voting authority shares |
| voting_shared | BIGINT | Shared voting authority shares |
| voting_none | BIGINT | No voting authority shares |

### `raw.xbrl_facts`
Structured financial data from XBRL-tagged filings.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) | Parent filing |
| cik | INTEGER | Filer CIK |
| concept | VARCHAR(200) | XBRL concept (e.g., us-gaap:Revenue) |
| value | TEXT | Reported value |
| unit | VARCHAR(50) | Unit (USD, shares, etc.) |
| decimals | VARCHAR(20) | Decimal precision |
| period_start | DATE | Period start (NULL if instant) |
| period_end | DATE | Period end |
| context_id | VARCHAR(200) | XBRL context identifier |
| is_instant | BOOLEAN | Point-in-time vs. duration |

### `raw.filing_sections`
Extracted text sections from 10-K/10-Q HTML.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) | Parent filing |
| cik | INTEGER | Filer CIK |
| section | VARCHAR(50) | Section ID (item_1a_risk_factors, etc.) |
| text | TEXT | Extracted section text |
| char_count | INTEGER | Character count |

### `raw.parse_failures`
Dead-letter queue for failed filing parses.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) | Failed filing |
| form_type | VARCHAR(20) | Filing type |
| exception_class | VARCHAR(200) | Python exception class name |
| traceback | TEXT | Full stack trace |
| parser_version | VARCHAR(20) | Parser version at time of failure |

---

## Reference Tables

### `ref.ticker_cik`
CIK-to-ticker mapping from SEC's company_tickers.json.

| Column | Type | Description |
|---|---|---|
| cik | INTEGER | Central Index Key |
| ticker | VARCHAR(20) | Trading symbol |
| company_name | VARCHAR(200) | Company name |
| exchange | VARCHAR(20) | Exchange (NYSE, NASDAQ, etc.) |

### `ref.ticker_overrides`
Manual overrides for delistings, ticker changes, CUSIP remaps.

| Column | Type | Description |
|---|---|---|
| cusip | VARCHAR(9) | CUSIP to override |
| cik | INTEGER | CIK to override |
| ticker | VARCHAR(20) | Correct ticker |
| notes | TEXT | Reason for override |

---

## Mart Tables (dbt)

### `mart.mart_insider_summary`
Monthly insider activity summary per issuer.

### `mart.mart_cluster_buying`
Companies with ≥3 distinct insiders buying in trailing 90 days, total value ≥$250K.

### `mart.mart_holdings_by_manager`
Top 50 positions per manager per period.

### `mart.mart_holdings_changes`
Quarter-over-quarter holding changes: NEW, INCREASED, REDUCED, EXITED.

### `mart.mart_ownership_concentration`
HHI and top-10-holder percentage per issuer.

### `mart.mart_fundamentals_quarterly`
Key financial metrics pivoted from XBRL facts.

### `mart.mart_risk_factors_text`
Risk-factor section text per issuer per year, ready for embedding.

---

## Vector Tables

### `vec.risk_factor_chunks`
Embedded risk-factor text chunks for semantic search.

| Column | Type | Description |
|---|---|---|
| id | BIGINT PK | Auto-increment |
| accession_number | VARCHAR(25) | Source filing |
| issuer_cik | INTEGER | Issuing company CIK |
| year | INTEGER | Filing year |
| chunk_index | INTEGER | Position within section |
| chunk_text | TEXT | Raw text of the chunk |
| embedding | vector(384) | BAAI/bge-small-en-v1.5 embedding |

HNSW index: `ix_risk_factor_embedding` (cosine similarity, m=16, ef_construction=64)

### `mart.risk_factor_diffs`
LLM-generated year-over-year risk-factor summaries.

| Column | Type | Description |
|---|---|---|
| issuer_cik | INTEGER | Company CIK |
| year | INTEGER | Current year being compared |
| diff_json | TEXT | JSON array of {new, dropped, sentiment} |
