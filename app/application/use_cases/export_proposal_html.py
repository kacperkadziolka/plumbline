import html
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.get_proposal import GetProposalResult, TradeRow, get_proposal

_CSS = """\
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.6;
    color: #1f2937;
    background: #f9fafb;
    margin: 2rem;
}
.container { max-width: 900px; margin: 0 auto; }
.header {
    background: white;
    padding: 1.5rem;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    margin-bottom: 1.5rem;
}
h1 { margin: 0 0 0.5rem 0; font-size: 1.5rem; }
.meta { color: #6b7280; font-size: 0.875rem; }
.summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
}
.card {
    background: white;
    padding: 1rem;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.card-label {
    font-size: 0.75rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.25rem;
}
.card-value { font-size: 1.25rem; font-weight: 600; }
table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    margin-bottom: 1.5rem;
}
th {
    background: #f9fafb;
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
td { padding: 0.75rem 1rem; border-top: 1px solid #e5e7eb; }
.text-right { text-align: right; }
.no-trades {
    background: white;
    padding: 2rem;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    text-align: center;
    color: #6b7280;
    margin-bottom: 1.5rem;
}
.explanations {
    background: #f3f4f6;
    padding: 1rem;
    border-radius: 8px;
    font-size: 0.875rem;
    color: #4b5563;
}
.explanations h3 { margin: 0 0 0.5rem 0; font-size: 0.875rem; font-weight: 600; }
.explanations ul { margin: 0; padding-left: 1.5rem; }
.explanations li { margin-bottom: 0.25rem; }
@media print {
    body { background: white; margin: 0; }
    .header, .card, table, .no-trades { box-shadow: none; }
}
"""


def _fmt_amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _fmt_pct(value: Decimal) -> str:
    return f"{value * 100:.1f}%"


def _render_trade_row(trade: TradeRow, currency: str) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(trade.ticker)}</td>"
        f'<td class="text-right">{_fmt_amount(trade.buy_amount)} {html.escape(currency)}</td>'
        f'<td class="text-right">{_fmt_pct(trade.current_weight)}</td>'
        f'<td class="text-right">{_fmt_pct(trade.target_weight)}</td>'
        f'<td class="text-right">{_fmt_pct(trade.gap)}</td>'
        "</tr>"
    )


def _render_trades_section(proposal: GetProposalResult) -> str:
    if not proposal.trades:
        return '<div class="no-trades">No trades needed. Portfolio is already at target weights.</div>'

    rows = "\n".join(_render_trade_row(t, proposal.currency) for t in proposal.trades)
    return f"""\
<table>
<thead>
<tr>
<th>Ticker</th>
<th class="text-right">Buy Amount</th>
<th class="text-right">Current %</th>
<th class="text-right">Target %</th>
<th class="text-right">Gap %</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>"""


def render_proposal_html(proposal: GetProposalResult) -> str:
    """Render a proposal as a self-contained HTML document.

    Pure function: takes data, returns HTML string. No I/O.
    """
    trades_html = _render_trades_section(proposal)
    currency = html.escape(proposal.currency)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proposal #{proposal.proposal_id} &mdash; Decision Report</title>
<style>
{_CSS}\
</style>
</head>
<body>
<div class="container">

<div class="header">
<h1>Contribution Proposal &mdash; Decision Report</h1>
<p class="meta">
Proposal #{proposal.proposal_id}
&middot; {proposal.created_at.strftime("%Y-%m-%d %H:%M")}
&middot; Policy hash: {html.escape(proposal.policy_hash[:12])}
</p>
</div>

<div class="summary">
<div class="card">
<div class="card-label">Amount</div>
<div class="card-value">{_fmt_amount(proposal.amount)} {currency}</div>
</div>
<div class="card">
<div class="card-label">Total Allocated</div>
<div class="card-value">{_fmt_amount(proposal.total_allocated)} {currency}</div>
</div>
<div class="card">
<div class="card-label">Unallocated</div>
<div class="card-value">{_fmt_amount(proposal.unallocated)} {currency}</div>
</div>
</div>

{trades_html}

<div class="explanations">
<h3>Column Explanations</h3>
<ul>
<li><strong>Buy Amount</strong> &mdash; Allocated purchase amount in {currency}.</li>
<li><strong>Current %</strong> &mdash; Position value as percentage of post-contribution portfolio.</li>
<li><strong>Target %</strong> &mdash; Desired weight according to selected policy.</li>
<li><strong>Gap %</strong> &mdash; Underweight relative to target (positive = underweight, needs buying).</li>
</ul>
</div>

</div>
</body>
</html>"""


async def export_proposal_html(
    proposal_id: int,
    session: AsyncSession,
) -> str:
    """Export a proposal as a self-contained HTML string.

    Raises:
        DataMissingError: If proposal not found.
    """
    proposal = await get_proposal(proposal_id, session)
    return render_proposal_html(proposal)
