"""Seed demo data from test fixtures so the API has something to return."""

import datetime
from pathlib import Path

from sec_filings.db import get_session
from sec_filings.models import (
    FilingIndex,
    HoldingsPosition,
    InsiderTransaction,
    TickerCik,
)
from sec_filings.parsers.form13f import parse_form13f
from sec_filings.parsers.form4 import parse_form4

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "filings"


def seed() -> None:
    session = get_session()

    # Ticker mappings
    tickers = [
        TickerCik(cik=320193, ticker="AAPL", company_name="Apple Inc", exchange="NASDAQ"),
        TickerCik(cik=1067983, ticker="BRK-A", company_name="Berkshire Hathaway Inc", exchange="NYSE"),
        TickerCik(cik=789019, ticker="MSFT", company_name="Microsoft Corp", exchange="NASDAQ"),
    ]
    for t in tickers:
        session.merge(t)

    # Filing index entries
    filings = [
        FilingIndex(
            accession_number="0000320193-24-000042",
            form_type="4",
            cik=320193,
            company_name="Apple Inc",
            date_filed=datetime.date(2024, 3, 15),
            filename="edgar/data/320193/0000320193-24-000042.txt",
        ),
        FilingIndex(
            accession_number="0001067983-24-000003",
            form_type="13F-HR",
            cik=1067983,
            company_name="Berkshire Hathaway Inc",
            date_filed=datetime.date(2024, 5, 15),
            filename="edgar/data/1067983/0001067983-24-000003.txt",
        ),
    ]
    for f in filings:
        session.merge(f)

    # Parse Form 4 fixture into insider transactions
    form4_xml = (FIXTURES / "form4_sample.xml").read_text()
    form4_result = parse_form4(form4_xml, "0000320193-24-000042")
    for tx in form4_result.transactions:
        session.merge(InsiderTransaction(**tx.model_dump()))

    # Add additional insider transactions for cluster-buying demo
    insider_buys = [
        ("Cook Timothy D", 1234567, "CEO", True, True, datetime.date(2024, 3, 15), 10000, 172.50),
        ("Maestri Luca", 2345678, "CFO", False, True, datetime.date(2024, 3, 20), 5000, 175.00),
        ("Williams Jeff", 3456789, "COO", False, True, datetime.date(2024, 3, 25), 8000, 178.00),
        ("Adams Katherine", 4567890, "General Counsel", False, True, datetime.date(2024, 4, 1), 3000, 180.00),
    ]
    for i, (name, cik, title, is_dir, is_off, date, shares, price) in enumerate(insider_buys):
        session.merge(
            InsiderTransaction(
                accession_number=f"0000320193-24-{40000+i:06d}",
                filing_date=date,
                transaction_index=0,
                owner_cik=cik,
                owner_name=name,
                is_director=is_dir,
                is_officer=is_off,
                is_ten_percent_owner=False,
                is_other=False,
                officer_title=title,
                issuer_cik=320193,
                issuer_name="Apple Inc",
                issuer_ticker="AAPL",
                security_title="Common Stock",
                transaction_date=date,
                transaction_code="P",
                shares=float(shares),
                price_per_share=float(price),
                shares_after=100000.0,
                direct_or_indirect="D",
                is_derivative=False,
                is_10b5_1=False,
            )
        )

    # Parse 13F-HR fixture
    primary = (FIXTURES / "form13f_primary.xml").read_text()
    infotable = (FIXTURES / "form13f_infotable.xml").read_text()
    f13f = parse_form13f(infotable, primary, "0001067983-24-000003")

    for h in f13f.holdings:
        session.merge(
            HoldingsPosition(
                accession_number=f13f.accession_number,
                filer_cik=f13f.filer_cik,
                filer_name=f13f.filer_name,
                period_of_report=f13f.period_of_report,
                name_of_issuer=h.name_of_issuer,
                cusip=h.cusip,
                ticker=h.ticker,
                value=h.value,
                shares=h.shares,
                share_type=h.share_type,
                investment_discretion=h.investment_discretion,
                voting_sole=h.voting_sole,
                voting_shared=h.voting_shared,
                voting_none=h.voting_none,
            )
        )

    session.commit()
    print("Seeded demo data:")
    print(f"  - {len(tickers)} ticker mappings")
    print(f"  - {len(filings)} filings in index")
    print(f"  - {len(form4_result.transactions) + len(insider_buys)} insider transactions")
    print(f"  - {len(f13f.holdings)} institutional holdings")

    session.close()


if __name__ == "__main__":
    seed()
