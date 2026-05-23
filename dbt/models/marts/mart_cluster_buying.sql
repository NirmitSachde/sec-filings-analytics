with txns as (
    select * from {{ ref('int_insider_transactions_normalized') }}
    where transaction_type = 'BUY'
      and transaction_date >= current_date - interval '90 days'
),

cluster as (
    select
        issuer_cik,
        issuer_name,
        issuer_ticker,
        count(distinct owner_cik) as n_distinct_insiders_buying_90d,
        sum(transaction_value) as total_buy_value,
        max(transaction_date) as latest_buy_date,
        min(transaction_date) as earliest_buy_date
    from txns
    group by 1, 2, 3
)

select *
from cluster
where n_distinct_insiders_buying_90d >= 3
  and total_buy_value >= 250000
order by n_distinct_insiders_buying_90d desc, total_buy_value desc
