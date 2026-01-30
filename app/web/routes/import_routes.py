from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.import_holdings_manual import import_holdings_manual
from app.infrastructure.db import get_async_db

router = APIRouter(tags=["import"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "import.html")


@router.post("/import/holdings/manual", response_class=HTMLResponse)
async def upload_holdings_manual(
    request: Request,
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> HTMLResponse:
    content = (await file.read()).decode("utf-8")
    as_of_date = datetime.now(UTC)

    result = await import_holdings_manual(content, as_of_date, db)
    await db.commit()

    return templates.TemplateResponse(
        request,
        "import_success.html",
        {
            "position_count": result.position_count,
            "snapshot_id": result.snapshot_id,
            "as_of_date": result.as_of_date,
        },
    )
