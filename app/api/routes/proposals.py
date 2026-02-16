from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import ListProposalsResult, export_proposal_csv, export_proposal_html, list_proposals
from app.infrastructure.db import get_async_db

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("/")
async def list_proposals_endpoint(
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> ListProposalsResult:
    return await list_proposals(db)


@router.get("/{proposal_id}/csv")
async def export_proposal_csv_endpoint(
    proposal_id: int,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> Response:
    csv_text = await export_proposal_csv(proposal_id, db)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=proposal_{proposal_id}.csv"},
    )


@router.get("/{proposal_id}/html")
async def export_proposal_html_endpoint(
    proposal_id: int,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> Response:
    html_text = await export_proposal_html(proposal_id, db)
    return Response(
        content=html_text,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename=proposal_{proposal_id}.html"},
    )
