from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import get_backtest_run, list_backtest_runs, list_policies, run_backtest
from app.core.errors import DataMissingError, PlumblineError, ValidationError
from app.infrastructure.db import get_async_db

router = APIRouter(tags=["backtests"])
templates = Jinja2Templates(directory="app/web/templates")


async def _render_list(
    request: Request,
    db: AsyncSession,
    *,
    error: str | None = None,
    form_policy_id: str = "",
    form_backtest_yaml: str = "",
    form_include_satellite: bool = False,
) -> HTMLResponse:
    runs_result = await list_backtest_runs(db)
    policies = await list_policies(db)
    return templates.TemplateResponse(
        request,
        "backtests.html",
        {
            "runs": runs_result.runs,
            "policies": policies.policies,
            "error": error,
            "form_policy_id": form_policy_id,
            "form_backtest_yaml": form_backtest_yaml,
            "form_include_satellite": form_include_satellite,
        },
    )


@router.get("/backtests", response_class=HTMLResponse)
async def backtests_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> HTMLResponse:
    return await _render_list(request, db)


@router.post("/backtests", response_model=None)
async def run_backtest_action(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    policy_id: Annotated[str, Form()],
    backtest_yaml: Annotated[str, Form()],
    include_satellite: Annotated[str | None, Form()] = None,
) -> Response:
    form_sat = include_satellite is not None

    try:
        parsed_policy_id = int(policy_id)
    except (ValueError, TypeError):
        return await _render_list(
            request,
            db,
            error="Please select a policy.",
            form_policy_id=policy_id,
            form_backtest_yaml=backtest_yaml,
            form_include_satellite=form_sat,
        )

    try:
        result = await run_backtest(parsed_policy_id, backtest_yaml, form_sat, db)
        await db.commit()
    except (ValidationError, DataMissingError) as exc:
        error_msg = exc.message
        if isinstance(exc, PlumblineError) and exc.details:
            error_msg = f"{exc.message}: {exc.details}"
        return await _render_list(
            request,
            db,
            error=error_msg,
            form_policy_id=policy_id,
            form_backtest_yaml=backtest_yaml,
            form_include_satellite=form_sat,
        )

    return RedirectResponse(url=f"/backtests/{result.run_id}", status_code=303)


@router.get("/backtests/{run_id}", response_class=HTMLResponse)
async def backtest_detail_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    run_id: int,
) -> HTMLResponse:
    result = await get_backtest_run(run_id, db)
    return templates.TemplateResponse(
        request,
        "backtest_detail.html",
        {"run": result},
    )
