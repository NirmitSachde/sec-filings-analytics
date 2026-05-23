# Case Studies — SEC Filings Analytics Platform

## 1. Cluster Buying Screen — "Where are insiders putting their own money?"

Cluster buying — where three or more insiders at the same company buy open-market shares within a 90-day window — is the most historically predictive insider signal. This screen surfaces those clusters.

```bash
# Find companies with at least 3 insiders buying, $250K+ total
curl "localhost:8000/screen/cluster-buying?min_insiders=3&min_value=250000"
```

**Metabase:** The Cluster Buying Screener dashboard provides a filterable table with sector breakdown and time-series of cluster signal frequency.

---

## 2. Berkshire 13F Latest Changes — "What did Buffett buy/sell this quarter?"

Track quarter-over-quarter changes in any institutional manager's 13F holdings.

```bash
# Berkshire Hathaway (CIK 1067983) — holding changes
curl "localhost:8000/holdings/changes/1067983"

# Full current portfolio, top 50
curl "localhost:8000/holdings/1067983"
```

**Metabase:** The Hedge Fund Tracker dashboard lets you pick any 13F filer and see their portfolio composition, recent additions, and exits.

---

## 3. Risk Factor Similarity — "Find companies with 10-Ks textually similar to MRNA's pandemic-era risk factors"

Using sentence embeddings (BAAI/bge-small-en-v1.5) and pgvector cosine similarity, find companies whose risk disclosures are semantically close to a reference company.

```bash
# Companies with risk profiles most similar to Moderna (MRNA)
curl "localhost:8000/search/risk-similar/MRNA?top_k=10"

# Year-over-year risk factor diff for Moderna
curl "localhost:8000/search/diffs/MRNA/2024"
```

**Metabase:** The Risk Factor Drift dashboard ranks companies by the magnitude of year-over-year risk-factor text changes, flagging those with materially new disclosures.
