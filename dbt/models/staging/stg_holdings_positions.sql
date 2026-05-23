with source as (
    select * from raw.holdings_positions
)

select
    id,
    accession_number,
    filer_cik,
    trim(filer_name) as filer_name,
    period_of_report,
    trim(name_of_issuer) as name_of_issuer,
    upper(trim(cusip)) as cusip,
    upper(trim(ticker)) as ticker,
    value,
    shares,
    upper(trim(share_type)) as share_type,
    upper(trim(investment_discretion)) as investment_discretion,
    voting_sole,
    voting_shared,
    voting_none,
    created_at
from source
where value > 0
