with sections as (
    select * from {{ ref('stg_filing_sections') }}
    where section = 'item_1a_risk_factors'
)

select
    cik as issuer_cik,
    accession_number,
    extract(year from created_at) as year,
    text as risk_factor_text,
    char_count
from sections
order by cik, year
