with holdings as (
    select * from {{ ref('stg_holdings_positions') }}
),

latest_period as (
    select max(period_of_report) as period from holdings
),

issuer_totals as (
    select
        h.cusip,
        h.name_of_issuer,
        h.ticker,
        h.period_of_report,
        sum(h.value) as total_institutional_value,
        count(distinct h.filer_cik) as n_holders
    from holdings h
    cross join latest_period lp
    where h.period_of_report = lp.period
    group by 1, 2, 3, 4
    having sum(h.value) > 0
),

holder_shares as (
    select
        h.cusip,
        h.filer_cik,
        h.value,
        it.total_institutional_value,
        (h.value::numeric / it.total_institutional_value) as ownership_share,
        row_number() over (partition by h.cusip order by h.value desc) as holder_rank
    from holdings h
    join issuer_totals it on h.cusip = it.cusip and h.period_of_report = it.period_of_report
),

concentration as (
    select
        it.cusip,
        it.name_of_issuer,
        it.ticker,
        it.period_of_report,
        it.n_holders,
        it.total_institutional_value,
        coalesce(sum(case when hs.holder_rank <= 10 then hs.ownership_share end) * 100, 0) as top10_holder_pct,
        sum(power(hs.ownership_share, 2)) * 10000 as hhi
    from issuer_totals it
    join holder_shares hs on it.cusip = hs.cusip
    group by 1, 2, 3, 4, 5, 6
)

select *
from concentration
order by hhi desc
