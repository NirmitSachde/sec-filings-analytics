-- Mart: signal validation summary. Answers the question "Does cluster
-- buying actually predict forward returns?" Aggregates per-signal results
-- by GICS sector plus an 'ALL' row. Drives the by-sector bar chart and
-- summary stats on the web UI.

with detail as (
    select * from {{ ref('mart_signal_validation_detail') }}
),

by_sector as (
    select
        gics_sector,
        count(*) as n_signals,
        avg(stock_return_h180) as avg_stock_return_180d,
        avg(bench_return_h180) as avg_bench_return_180d,
        avg(excess_return_h180) as avg_excess_return_180d,
        percentile_cont(0.5) within group (order by excess_return_h180) as median_excess_return_180d,
        sum(beat_benchmark_h180)::numeric / count(*) as hit_rate_180d,
        sum(beat_benchmark_h90)::numeric  / count(*) as hit_rate_90d,
        sum(beat_benchmark_h30)::numeric  / count(*) as hit_rate_30d,
        stddev(excess_return_h180) as stddev_excess_180d,
        case
            when stddev(excess_return_h180) > 0
            then avg(excess_return_h180) / stddev(excess_return_h180)
            else null
        end as info_ratio_180d
    from detail
    group by 1
),

overall as (
    select
        'ALL' as gics_sector,
        count(*) as n_signals,
        avg(stock_return_h180) as avg_stock_return_180d,
        avg(bench_return_h180) as avg_bench_return_180d,
        avg(excess_return_h180) as avg_excess_return_180d,
        percentile_cont(0.5) within group (order by excess_return_h180) as median_excess_return_180d,
        sum(beat_benchmark_h180)::numeric / count(*) as hit_rate_180d,
        sum(beat_benchmark_h90)::numeric  / count(*) as hit_rate_90d,
        sum(beat_benchmark_h30)::numeric  / count(*) as hit_rate_30d,
        stddev(excess_return_h180) as stddev_excess_180d,
        case
            when stddev(excess_return_h180) > 0
            then avg(excess_return_h180) / stddev(excess_return_h180)
            else null
        end as info_ratio_180d
    from detail
)

select * from overall
union all
select * from by_sector
order by n_signals desc
