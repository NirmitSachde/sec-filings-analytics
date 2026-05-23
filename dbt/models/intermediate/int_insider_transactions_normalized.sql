with txns as (
    select * from {{ ref('stg_insider_transactions') }}
),

enriched as (
    select
        *,
        coalesce(shares * price_per_share, 0) as transaction_value,
        case
            when transaction_code = 'P' then 'BUY'
            when transaction_code = 'S' then 'SELL'
            when transaction_code = 'A' then 'AWARD'
            when transaction_code = 'M' then 'EXERCISE'
            when transaction_code = 'G' then 'GIFT'
            else 'OTHER'
        end as transaction_type,
        sum(case when transaction_code = 'P' then shares else 0 end)
            over (partition by owner_cik, issuer_cik
                  order by transaction_date
                  rows between 29 preceding and current row) as rolling_30d_buys,
        sum(case when transaction_code = 'P' then shares else 0 end)
            over (partition by owner_cik, issuer_cik
                  order by transaction_date
                  rows between 89 preceding and current row) as rolling_90d_buys,
        sum(case when transaction_code = 'P' then shares else 0 end)
            over (partition by owner_cik, issuer_cik
                  order by transaction_date
                  rows between 179 preceding and current row) as rolling_180d_buys,
        sum(case when transaction_code = 'S' then shares else 0 end)
            over (partition by owner_cik, issuer_cik
                  order by transaction_date
                  rows between 89 preceding and current row) as rolling_90d_sells
    from txns
)

select
    *,
    rolling_90d_buys - rolling_90d_sells as net_90d_shares
from enriched
