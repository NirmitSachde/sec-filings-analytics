{{ config(
    materialized='table',
    post_hook="create index on {{ this }} (ticker, price_date)"
) }}

-- Staging: daily price history. One row per (ticker, date).
-- Filters out obvious junk (zero/negative prices, non-trading days).
-- Materialized and indexed on (ticker, price_date): the backtest does tens of
-- thousands of "first trading day on or after" lookups against it.

select
    upper(ticker) as ticker,
    date::date as price_date,
    open::numeric as open,
    high::numeric as high,
    low::numeric as low,
    close::numeric as close,
    coalesce(adj_close, close)::numeric as adj_close,
    volume::bigint as volume
from {{ source('raw', 'daily_prices') }}
where close > 0
  and adj_close > 0
  and date is not null
