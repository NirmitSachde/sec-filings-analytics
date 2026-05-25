-- Mart: one row per cluster-buy signal with its forward returns and the
-- benchmark-adjusted excess return at each horizon. Drives the per-signal
-- detail view in Metabase and the distribution histogram on the web UI.

select
    r.signal_id,
    r.issuer_cik,
    r.issuer_ticker,
    r.issuer_name,
    coalesce(sm.gics_sector, 'Unclassified') as gics_sector,
    coalesce(sm.gics_industry, 'Unclassified') as gics_industry,
    r.signal_date,
    extract(year from r.signal_date)::int as signal_year,
    r.n_insiders_90d,
    r.total_value_90d,

    r.entry_price,
    r.stock_return_h30,
    r.stock_return_h90,
    r.stock_return_h180,

    r.bench_return_h30,
    r.bench_return_h90,
    r.bench_return_h180,

    r.excess_return_h30,
    r.excess_return_h90,
    r.excess_return_h180,

    r.beat_benchmark_h30,
    r.beat_benchmark_h90,
    r.beat_benchmark_h180
from {{ ref('int_cluster_signal_returns') }} r
left join {{ ref('stg_security_master') }} sm
    on sm.ticker = r.issuer_ticker
