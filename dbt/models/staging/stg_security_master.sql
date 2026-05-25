-- Staging: security master. Ticker to GICS sector + industry.

select
    upper(ticker) as ticker,
    cik,
    company_name,
    gics_sector,
    gics_industry_group,
    gics_industry,
    is_active
from {{ source('raw', 'security_master') }}
