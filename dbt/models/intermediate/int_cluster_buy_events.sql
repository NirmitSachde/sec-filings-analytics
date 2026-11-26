{{ config(materialized='table') }}

-- Intermediate: historical cluster-buy *events*. One row per (issuer, signal_date).
--
-- Unlike `mart_cluster_buying`, which surfaces issuers whose trailing-90-day
-- window currently meets the threshold, this model emits one event each time
-- a fresh cluster forms, anywhere in the historical record. That's the unit
-- we backtest against.
--
-- Definition: an open-market purchase (Form 4 Table I, code P, price > 0).
-- On each filing date, look back 90 calendar days of *filings*. If the window
-- holds >= 3 distinct insiders and >= $250K of buy value, that filing date is a
-- cluster point. Deduplicate to one event per (issuer, calendar quarter) so the
-- same cluster is not counted twice.
--
-- Point in time: the window and the signal date both use the FILING date, the
-- day the trade became public, not the trade date. Insiders have up to two
-- business days (often more when late) to file, so keying on the trade date
-- would let the backtest act on information nobody had yet.
--
-- Ticker: the issuer's current primary ticker from SEC company_tickers.json
-- (ref.ticker_cik), falling back to the symbol written on the filing. This
-- keeps renamed companies priceable (a 2019 "FB" filing is priced as META).

with insider_buys as (
    select
        issuer_cik,
        issuer_name,
        issuer_ticker,
        owner_cik,
        filing_date,
        shares,
        shares * price_per_share as transaction_value
    from {{ ref('stg_insider_transactions') }}
    where transaction_code = 'P'
      and not is_derivative
      and price_per_share > 0
      and shares > 0
),

-- Postgres has no count(distinct) over a window, so collapse to one row per
-- (issuer, insider, filing date), then self-join each filing date to the
-- 90 days of filings before it.
buys_daily as (
    select
        issuer_cik,
        max(issuer_name) as issuer_name,
        max(issuer_ticker) as issuer_ticker,
        owner_cik,
        filing_date,
        sum(shares) as shares,
        sum(transaction_value) as value
    from insider_buys
    group by issuer_cik, owner_cik, filing_date
),

issuer_days as (
    select issuer_cik, filing_date, max(issuer_name) as issuer_name, max(issuer_ticker) as issuer_ticker
    from buys_daily
    group by issuer_cik, filing_date
),

trailing_window as (
    select
        d.issuer_cik,
        d.issuer_name,
        d.issuer_ticker,
        d.filing_date,
        count(distinct b.owner_cik) as n_insiders_90d,
        sum(b.value) as total_value_90d,
        sum(b.value) / nullif(sum(b.shares), 0) as avg_buy_price_90d
    from issuer_days d
    join buys_daily b
      on b.issuer_cik = d.issuer_cik
     and b.filing_date between d.filing_date - interval '90 days' and d.filing_date
    group by d.issuer_cik, d.issuer_name, d.issuer_ticker, d.filing_date
),

qualifying as (
    select *
    from trailing_window
    where n_insiders_90d >= 3
      and total_value_90d >= 250000
),

dedupe_per_quarter as (
    select distinct on (issuer_cik, date_trunc('quarter', filing_date))
        issuer_cik,
        issuer_name,
        issuer_ticker as filing_ticker,
        filing_date as signal_date,
        n_insiders_90d,
        total_value_90d,
        avg_buy_price_90d
    from qualifying
    order by issuer_cik, date_trunc('quarter', filing_date), filing_date
),

primary_ticker as (
    select distinct on (cik) cik, ticker
    from {{ source('ref', 'ticker_cik') }}
    order by cik, id
),

-- Tickers that currently belong to some SEC registrant. A delisted company's old
-- symbol is only used as a fallback when nobody holds it today, otherwise the
-- backtest would price a different company.
taken as (
    select distinct ticker from {{ source('ref', 'ticker_cik') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['d.issuer_cik', 'd.signal_date']) }} as signal_id,
    d.issuer_cik,
    d.issuer_name,
    coalesce(
        pt.ticker,
        case when t.ticker is null then d.filing_ticker end
    ) as issuer_ticker,
    d.filing_ticker,
    d.signal_date,
    d.n_insiders_90d,
    d.total_value_90d,
    d.avg_buy_price_90d
from dedupe_per_quarter d
left join primary_ticker pt on pt.cik = d.issuer_cik
left join taken t on t.ticker = d.filing_ticker
