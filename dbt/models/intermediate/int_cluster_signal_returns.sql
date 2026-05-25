-- Intermediate: per-signal forward returns at 30 / 90 / 180-day horizons.
-- Stock return is matched against same-window SPY return; difference is the
-- excess return (alpha). We use the first trading day on or after the target
-- date for entry and exit, so signals filed on weekends still get accurate
-- next-open pricing.

{% set horizons = [30, 90, 180] %}

with signals as (
    select * from {{ ref('int_cluster_buy_events') }}
),

-- For each (ticker, target_date), find the first trading day >= target_date
-- and pull its adjusted close.
price_at_or_after as (
    select
        s.signal_id,
        s.issuer_ticker,
        'entry' as leg,
        s.signal_date as target_date,
        (
            select p.adj_close
            from {{ ref('stg_daily_prices') }} p
            where p.ticker = s.issuer_ticker
              and p.price_date >= s.signal_date
            order by p.price_date
            limit 1
        ) as price
    from signals s

    {% for h in horizons %}
    union all
    select
        s.signal_id,
        s.issuer_ticker,
        'h{{ h }}' as leg,
        (s.signal_date + interval '{{ h }} days')::date as target_date,
        (
            select p.adj_close
            from {{ ref('stg_daily_prices') }} p
            where p.ticker = s.issuer_ticker
              and p.price_date >= s.signal_date + interval '{{ h }} days'
            order by p.price_date
            limit 1
        ) as price
    from signals s
    {% endfor %}
),

stock_prices_wide as (
    select
        signal_id,
        max(case when leg = 'entry' then price end) as entry_price,
        {% for h in horizons %}
        max(case when leg = 'h{{ h }}' then price end) as price_h{{ h }}{% if not loop.last %},{% endif %}
        {% endfor %}
    from price_at_or_after
    group by signal_id
),

-- Same machinery for SPY benchmark.
benchmark_at_or_after as (
    select
        s.signal_id,
        'entry' as leg,
        s.signal_date as target_date,
        (
            select p.adj_close
            from {{ ref('stg_daily_prices') }} p
            where p.ticker = 'SPY'
              and p.price_date >= s.signal_date
            order by p.price_date
            limit 1
        ) as price
    from signals s

    {% for h in horizons %}
    union all
    select
        s.signal_id,
        'h{{ h }}' as leg,
        (s.signal_date + interval '{{ h }} days')::date as target_date,
        (
            select p.adj_close
            from {{ ref('stg_daily_prices') }} p
            where p.ticker = 'SPY'
              and p.price_date >= s.signal_date + interval '{{ h }} days'
            order by p.price_date
            limit 1
        ) as price
    from signals s
    {% endfor %}
),

benchmark_prices_wide as (
    select
        signal_id,
        max(case when leg = 'entry' then price end) as bench_entry,
        {% for h in horizons %}
        max(case when leg = 'h{{ h }}' then price end) as bench_h{{ h }}{% if not loop.last %},{% endif %}
        {% endfor %}
    from benchmark_at_or_after
    group by signal_id
)

select
    s.signal_id,
    s.issuer_cik,
    s.issuer_ticker,
    s.issuer_name,
    s.signal_date,
    s.n_insiders_90d,
    s.total_value_90d,
    sp.entry_price,
    bp.bench_entry,

    {% for h in horizons %}
    sp.price_h{{ h }},
    bp.bench_h{{ h }},
    (sp.price_h{{ h }} - sp.entry_price) / nullif(sp.entry_price, 0) as stock_return_h{{ h }},
    (bp.bench_h{{ h }} - bp.bench_entry) / nullif(bp.bench_entry, 0) as bench_return_h{{ h }},
    (sp.price_h{{ h }} - sp.entry_price) / nullif(sp.entry_price, 0)
        - (bp.bench_h{{ h }} - bp.bench_entry) / nullif(bp.bench_entry, 0) as excess_return_h{{ h }},
    case
        when (sp.price_h{{ h }} - sp.entry_price) / nullif(sp.entry_price, 0)
             > (bp.bench_h{{ h }} - bp.bench_entry) / nullif(bp.bench_entry, 0)
        then 1 else 0
    end as beat_benchmark_h{{ h }}{% if not loop.last %},{% endif %}
    {% endfor %}

from signals s
left join stock_prices_wide sp on sp.signal_id = s.signal_id
left join benchmark_prices_wide bp on bp.signal_id = s.signal_id
where sp.entry_price is not null
  and sp.price_h180 is not null
  and bp.bench_entry is not null
  and bp.bench_h180 is not null
