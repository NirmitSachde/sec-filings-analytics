with source as (
    select * from raw.insider_transactions
)

select
    id,
    accession_number,
    filing_date,
    transaction_index,
    owner_cik,
    trim(owner_name) as owner_name,
    is_director,
    is_officer,
    is_ten_percent_owner,
    is_other,
    trim(officer_title) as officer_title,
    issuer_cik,
    trim(issuer_name) as issuer_name,
    upper(trim(issuer_ticker)) as issuer_ticker,
    trim(security_title) as security_title,
    coalesce(transaction_date, filing_date) as transaction_date,
    transaction_code,
    shares,
    price_per_share,
    shares_after,
    direct_or_indirect,
    is_derivative,
    is_10b5_1,
    created_at
from source
where shares is not null
