with current_holdings as (
    select * from {{ ref('stg_holdings_positions') }}
),

periods as (
    select distinct period_of_report
    from current_holdings
    order by period_of_report desc
),

with_prev as (
    select
        c.filer_cik,
        c.filer_name,
        c.period_of_report,
        c.cusip,
        c.name_of_issuer,
        c.ticker,
        c.value as current_value,
        c.shares as current_shares,
        p.value as previous_value,
        p.shares as previous_shares,
        p.period_of_report as previous_period
    from current_holdings c
    left join current_holdings p
        on c.filer_cik = p.filer_cik
        and c.cusip = p.cusip
        and p.period_of_report = (
            select max(period_of_report)
            from current_holdings
            where period_of_report < c.period_of_report
              and filer_cik = c.filer_cik
              and cusip = c.cusip
        )
)

select
    *,
    case
        when previous_value is null then 'NEW_POSITION'
        when current_value > previous_value then 'INCREASED'
        when current_value < previous_value then 'REDUCED'
        else 'UNCHANGED'
    end as change_type,
    current_value - coalesce(previous_value, 0) as value_delta,
    current_shares - coalesce(previous_shares, 0) as shares_delta
from with_prev
