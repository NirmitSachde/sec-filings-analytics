with facts as (
    select * from {{ ref('stg_xbrl_facts') }}
),

-- Deduplicate: keep one fact per (cik, concept, period_end) — prefer non-instant, latest context
ranked as (
    select
        *,
        row_number() over (
            partition by cik, concept, period_end
            order by is_instant asc, context_id desc
        ) as rn
    from facts
    where period_end is not null
)

select
    id,
    accession_number,
    cik,
    concept,
    value,
    unit,
    decimals,
    period_start,
    period_end,
    context_id,
    is_instant
from ranked
where rn = 1
