with holdings as (
    select * from {{ ref('stg_holdings_positions') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by filer_cik, period_of_report
            order by value desc
        ) as position_rank
    from holdings
)

select
    filer_cik,
    filer_name,
    period_of_report,
    cusip,
    name_of_issuer,
    ticker,
    value,
    shares,
    investment_discretion,
    position_rank
from ranked
where position_rank <= 50
