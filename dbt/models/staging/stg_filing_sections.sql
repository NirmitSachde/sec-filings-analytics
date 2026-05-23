with source as (
    select * from raw.filing_sections
)

select
    id,
    accession_number,
    cik,
    section,
    text,
    char_count,
    created_at
from source
where char_count >= 100
