from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import get_latest_holdings
from app.infrastructure.db import get_async_db

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/holdings", response_class=HTMLResponse)
async def holdings_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> HTMLResponse:
    result = await get_latest_holdings(db)
    return templates.TemplateResponse(request, "holdings.html", {"holdings": result})
