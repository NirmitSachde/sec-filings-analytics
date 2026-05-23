"""Dead-letter pipeline for failed parses."""

import traceback as tb

from sec_filings.db import get_session
from sec_filings.models import ParseFailure


def record_parse_failure(
    accession_number: str,
    form_type: str,
    exception: Exception,
    parser_version: str,
) -> None:
    session = get_session()
    try:
        failure = ParseFailure(
            accession_number=accession_number,
            form_type=form_type,
            exception_class=type(exception).__name__,
            traceback=tb.format_exc(),
            parser_version=parser_version,
        )
        session.add(failure)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
