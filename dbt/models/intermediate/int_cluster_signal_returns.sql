{{ config(materialized='table') }}

-- Intermediate: per-signal forward returns at 30 / 90 / 180-day horizons.
--
-- Entry is the close of the first trading day strictly AFTER the signal (filing)
-- date, because a Form 4 often lands after the close. Exit is the first trading
-- day on or after signal_date + horizon. Prices are adjusted for splits and
-- dividends, so returns are total returns. The same windows are measured on SPY;
-- the difference is the excess return.
--
-- Data-quality rules (a signal is kept only if all hold):
--   1. The stock actually traded (volume > 0) on the entry day and the 180-day
--      exit day. Thin OTC names often carry stale or garbage quotes on Yahoo.
--   2. The entry price is within 0.5x to 2x of the average price the insiders
--      paid in the cluster window. This catches mis-mapped tickers and broken
--      price histories while allowing for later split and dividend adjustment.
--   3. Full 180 days of prices exist for both the stock and SPY.

{% set horizons = [30, 90, 180] %}

with signals as (
    select * from {{ ref('int_cluster_buy_events') }}
    where issuer_ticker is not null
),

legs as (
    select
        s.signal_id,
        s.issuer_ticker,
        s.signal_date,
        e.adj_close as entry_price,
        e.volume as entry_volume,
        be.adj_close as bench_entry
        {% for h in horizons %},
        x{{ h }}.adj_close as price_h{{ h }},
        x{{ h }}.volume as volume_h{{ h }},
        bx{{ h }}.adj_close as bench_h{{ h }}
        {% endfor %}
    from signals s
    left join lateral (
        select p.adj_close, p.volume from {{ ref('stg_daily_prices') }} p
        where p.ticker = s.issuer_ticker and p.price_date > s.signal_date
        order by p.price_date limit 1
    ) e on true
    left join lateral (
        select p.adj_close from {{ ref('stg_daily_prices') }} p
        where p.ticker = 'SPY' and p.price_date > s.signal_date
        order by p.price_date limit 1
    ) be on true
    {% for h in horizons %}
    left join lateral (
        select p.adj_close, p.volume from {{ ref('stg_daily_prices') }} p
        where p.ticker = s.issuer_ticker
          and p.price_date >= s.signal_date + interval '{{ h }} days'
        order by p.price_date limit 1
    ) x{{ h }} on true
    left join lateral (
        select p.adj_close from {{ ref('stg_daily_prices') }} p
        where p.ticker = 'SPY'
          and p.price_date >= s.signal_date + interval '{{ h }} days'
        order by p.price_date limit 1
    ) bx{{ h }} on true
    {% endfor %}
)

select
    s.signal_id,
    s.issuer_cik,
    s.issuer_ticker,
    s.issuer_name,
    s.signal_date,
    s.n_insiders_90d,
    s.total_value_90d,
    s.avg_buy_price_90d,
    l.entry_price,
    l.bench_entry,

    {% for h in horizons %}
    l.price_h{{ h }},
    l.bench_h{{ h }},
    (l.price_h{{ h }} - l.entry_price) / nullif(l.entry_price, 0) as stock_return_h{{ h }},
    (l.bench_h{{ h }} - l.bench_entry) / nullif(l.bench_entry, 0) as bench_return_h{{ h }},
    (l.price_h{{ h }} - l.entry_price) / nullif(l.entry_price, 0)
        - (l.bench_h{{ h }} - l.bench_entry) / nullif(l.bench_entry, 0) as excess_return_h{{ h }},
    case
        when (l.price_h{{ h }} - l.entry_price) / nullif(l.entry_price, 0)
             > (l.bench_h{{ h }} - l.bench_entry) / nullif(l.bench_entry, 0)
        then 1 else 0
    end as beat_benchmark_h{{ h }}{% if not loop.last %},{% endif %}
    {% endfor %}

from signals s
join legs l on l.signal_id = s.signal_id
where l.entry_price is not null
  and l.price_h180 is not null
  and l.bench_entry is not null
  and l.bench_h180 is not null
  and l.entry_volume > 0
  and l.volume_h180 > 0
  and l.entry_price / nullif(s.avg_buy_price_90d, 0) between 0.5 and 2.0
