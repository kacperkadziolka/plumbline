from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.export_proposal_html import export_proposal_html

REPORTS_DIR = Path("data/reports/proposals")


async def save_proposal_html(
    proposal_id: int,
    session: AsyncSession,
) -> Path:
    """Generate and save an HTML decision report to disk.

    Returns:
        Path to the saved HTML file.

    Raises:
        DataMissingError: If proposal not found.
    """
    html_content = await export_proposal_html(proposal_id, session)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = REPORTS_DIR / f"{proposal_id}.html"
    file_path.write_text(html_content, encoding="utf-8")

    return file_path
