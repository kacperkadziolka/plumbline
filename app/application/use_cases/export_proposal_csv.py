import csv
import io

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.get_proposal import get_proposal


async def export_proposal_csv(
    proposal_id: int,
    session: AsyncSession,
) -> str:
    """Export a proposal as CSV text.

    Returns a CSV string with metadata comment header and trade rows.

    Raises:
        DataMissingError: If proposal not found.
    """
    proposal = await get_proposal(proposal_id, session)

    output = io.StringIO()

    output.write(f"# proposal_id: {proposal.proposal_id}\n")
    output.write(f"# created_at: {proposal.created_at.isoformat()}\n")
    output.write(f"# policy_id: {proposal.policy_id}\n")
    output.write(f"# policy_hash: {proposal.policy_hash}\n")
    output.write(f"# amount: {proposal.amount}\n")
    output.write(f"# currency: {proposal.currency}\n")
    output.write(f"# total_allocated: {proposal.total_allocated}\n")
    output.write(f"# unallocated: {proposal.unallocated}\n")

    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["ticker", "buy_amount", "current_weight", "target_weight", "gap"])
    for trade in proposal.trades:
        writer.writerow(
            [
                trade.ticker,
                str(trade.buy_amount),
                str(trade.current_weight),
                str(trade.target_weight),
                str(trade.gap),
            ]
        )

    return output.getvalue()
