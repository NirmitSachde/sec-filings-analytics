with source as (
    select * from raw.xbrl_facts
)

select
    id,
    accession_number,
    cik,
    trim(concept) as concept,
    value,
    trim(unit) as unit,
    decimals,
    period_start,
    period_end,
    context_id,
    is_instant,
    created_at
from source
