from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import get_latest_holdings, valuate_portfolio_for_date
from app.core.errors import ValidationError
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


@router.get("/valuation", response_class=HTMLResponse)
async def valuation_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    as_of: str | None = None,
) -> HTMLResponse:
    if as_of is not None:
        try:
            valuation_date = date.fromisoformat(as_of)
        except ValueError:
            raise ValidationError(
                message="Invalid date format",
                details=f"Expected YYYY-MM-DD, got: {as_of}",
            ) from None
        result = await valuate_portfolio_for_date(valuation_date, db)
    else:
        result = None
    return templates.TemplateResponse(request, "valuation.html", {"valuation": result, "as_of": as_of or ""})
