select
    filer_cik,
    filer_name,
    period_of_report,
    cusip,
    name_of_issuer,
    ticker,
    change_type,
    current_value,
    previous_value,
    value_delta,
    current_shares,
    previous_shares,
    shares_delta
from {{ ref('int_holdings_changes') }}
where change_type != 'UNCHANGED'
order by abs(value_delta) desc
