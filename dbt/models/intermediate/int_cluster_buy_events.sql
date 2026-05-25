-- Intermediate: historical cluster-buy *events*. One row per (issuer, signal_date).
--
-- Unlike `mart_cluster_buying` which surfaces issuers whose trailing-90-day
-- window currently meets the threshold, this model emits one event each time
-- a fresh cluster forms, anywhere in the historical record. That's the unit
-- we backtest against.
--
-- Definition: for each open-market insider buy, look back 90 calendar days.
-- If the trailing window contains >=3 distinct insiders and >= $250K of buy
-- value, mark that day as a cluster point. Deduplicate to one event per
-- (issuer, calendar quarter) so we don't double-count the same cluster.

with insider_buys as (
    select
        issuer_cik,
        issuer_name,
        issuer_ticker,
        owner_cik,
        transaction_date,
        transaction_value
    from {{ ref('int_insider_transactions_normalized') }}
    where transaction_type = 'BUY'
      and transaction_value > 0
),

trailing_window as (
    select
        issuer_cik,
        issuer_name,
        issuer_ticker,
        transaction_date,
        count(distinct owner_cik) over (
            partition by issuer_cik
            order by transaction_date
            range between interval '90 days' preceding and current row
        ) as n_insiders_90d,
        sum(transaction_value) over (
            partition by issuer_cik
            order by transaction_date
            range between interval '90 days' preceding and current row
        ) as total_value_90d
    from insider_buys
),

qualifying as (
    select *
    from trailing_window
    where n_insiders_90d >= 3
      and total_value_90d >= 250000
),

dedupe_per_quarter as (
    select distinct on (issuer_cik, date_trunc('quarter', transaction_date))
        {{ dbt_utils.generate_surrogate_key(['issuer_cik', 'transaction_date']) }} as signal_id,
        issuer_cik,
        issuer_name,
        issuer_ticker,
        transaction_date as signal_date,
        n_insiders_90d,
        total_value_90d
    from qualifying
    order by issuer_cik, date_trunc('quarter', transaction_date), transaction_date
)

select * from dedupe_per_quarter
