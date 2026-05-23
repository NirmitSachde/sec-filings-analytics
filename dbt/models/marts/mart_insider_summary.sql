with txns as (
    select * from {{ ref('int_insider_transactions_normalized') }}
)

select
    issuer_cik,
    issuer_name,
    issuer_ticker,
    date_trunc('month', transaction_date)::date as month,
    count(case when transaction_type = 'BUY' then 1 end) as n_insider_buys,
    count(case when transaction_type = 'SELL' then 1 end) as n_insider_sells,
    coalesce(sum(case when transaction_type = 'BUY' then shares else -shares end), 0) as net_shares,
    coalesce(sum(transaction_value), 0) as dollar_volume,
    count(distinct owner_cik) as distinct_insiders
from txns
where transaction_type in ('BUY', 'SELL')
group by 1, 2, 3, 4
