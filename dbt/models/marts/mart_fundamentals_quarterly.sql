with facts as (
    select * from {{ ref('int_xbrl_normalized') }}
    where unit in ('USD', 'usd')
),

pivoted as (
    select
        cik,
        period_end,
        max(case when concept like '%Revenue%' or concept like '%SalesRevenueNet%' then value::numeric end) as revenue,
        max(case when concept like '%GrossProfit%' then value::numeric end) as gross_profit,
        max(case when concept like '%OperatingIncomeLoss%' then value::numeric end) as operating_income,
        max(case when concept like '%NetIncomeLoss%' then value::numeric end) as net_income,
        max(case when concept like '%Assets' and concept not like '%Current%' then value::numeric end) as total_assets,
        max(case when concept like '%LongTermDebt%' or concept like '%LongTermDebtNoncurrent%' then value::numeric end) as total_debt,
        max(case when concept like '%NetCashProvided%OperatingActivities%' then value::numeric end) as cash_from_operations
    from facts
    group by 1, 2
)

select
    cik,
    period_end,
    revenue,
    gross_profit,
    operating_income,
    net_income,
    total_assets,
    total_debt,
    cash_from_operations
from pivoted
where revenue is not null or net_income is not null
order by cik, period_end
