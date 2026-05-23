"""Weekly email digest — top cluster-buying signals and risk-factor drift."""

import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from prefect import flow, task
from sqlalchemy import func

from sec_filings.config import get_settings
from sec_filings.db import get_session
from sec_filings.models import InsiderTransaction, RiskFactorDiff


@task
def build_digest_html() -> str:
    """Build the weekly digest HTML content."""
    session = get_session()
    since = datetime.date.today() - datetime.timedelta(days=7)

    try:
        # Top cluster-buying signals
        cluster_results = (
            session.query(
                InsiderTransaction.issuer_ticker,
                InsiderTransaction.issuer_name,
                func.count(func.distinct(InsiderTransaction.owner_cik)).label("n_insiders"),
                func.sum(InsiderTransaction.shares * InsiderTransaction.price_per_share).label("total_value"),
            )
            .filter(
                InsiderTransaction.transaction_code == "P",
                InsiderTransaction.filing_date >= since,
                InsiderTransaction.shares.isnot(None),
                InsiderTransaction.price_per_share.isnot(None),
            )
            .group_by(InsiderTransaction.issuer_ticker, InsiderTransaction.issuer_name)
            .having(func.count(func.distinct(InsiderTransaction.owner_cik)) >= 2)
            .order_by(func.count(func.distinct(InsiderTransaction.owner_cik)).desc())
            .limit(10)
            .all()
        )

        # Recent risk-factor diffs
        recent_diffs = (
            session.query(RiskFactorDiff)
            .order_by(RiskFactorDiff.created_at.desc())
            .limit(5)
            .all()
        )

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h1 style="color: #1a1a2e;">SEC Filings Weekly Digest</h1>
        <p style="color: #666;">Week ending {datetime.date.today().isoformat()}</p>

        <h2 style="color: #16213e;">Top Cluster Buying Signals</h2>
        <table style="width: 100%; border-collapse: collapse;">
        <tr style="background: #0f3460; color: white;">
            <th style="padding: 8px; text-align: left;">Ticker</th>
            <th style="padding: 8px; text-align: left;">Company</th>
            <th style="padding: 8px; text-align: right;">Insiders</th>
            <th style="padding: 8px; text-align: right;">Total Value</th>
        </tr>
        """

        for r in cluster_results:
            val = f"${r.total_value:,.0f}" if r.total_value else "N/A"
            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px; font-weight: bold;">{r.issuer_ticker or 'N/A'}</td>
                <td style="padding: 8px;">{r.issuer_name}</td>
                <td style="padding: 8px; text-align: right;">{r.n_insiders}</td>
                <td style="padding: 8px; text-align: right;">{val}</td>
            </tr>
            """

        html += """
        </table>

        <h2 style="color: #16213e; margin-top: 30px;">Recent Risk Factor Changes</h2>
        """

        if recent_diffs:
            for diff in recent_diffs:
                html += f"<p><strong>CIK {diff.issuer_cik}</strong> ({diff.year})</p>"
        else:
            html += "<p style='color: #666;'>No recent risk factor diffs available.</p>"

        html += """
        <hr style="margin-top: 30px; border: 1px solid #eee;">
        <p style="color: #999; font-size: 12px;">SEC Filings Analytics Platform — Automated Weekly Digest</p>
        </body>
        </html>
        """

        return html
    finally:
        session.close()


@task
def send_digest(html: str) -> bool:
    """Send the digest email via SMTP."""
    settings = get_settings()

    if not settings.smtp_host or not settings.digest_recipients:
        print("SMTP not configured — skipping email send")
        print(html)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"SEC Filings Weekly Digest — {datetime.date.today().isoformat()}"
    msg["From"] = settings.smtp_user
    msg["To"] = settings.digest_recipients

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)

    return True


@flow(name="Weekly Digest")
def run_weekly_digest() -> bool:
    """Build and send the weekly digest."""
    html = build_digest_html()
    return send_digest(html)


if __name__ == "__main__":
    run_weekly_digest()
