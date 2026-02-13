from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import (
    deserialize_allocation_result,
    generate_proposal,
    list_policies,
    save_proposal,
    serialize_allocation_result,
)
from app.core.errors import DataMissingError, PlumblineError, ValidationError
from app.infrastructure.db import get_async_db

router = APIRouter(tags=["propose"])
templates = Jinja2Templates(directory="app/web/templates")


async def _render_form(
    request: Request,
    db: AsyncSession,
    *,
    error: str | None = None,
    success: str | None = None,
    result: object | None = None,
    allocation_json: str = "",
    form_amount: str = "",
    form_currency: str = "EUR",
    form_policy_id: str = "",
    form_include_satellite: bool = False,
    saved_proposal_id: int | None = None,
) -> HTMLResponse:
    policies = await list_policies(db)
    return templates.TemplateResponse(
        request,
        "propose.html",
        {
            "policies": policies.policies,
            "result": result,
            "allocation_json": allocation_json,
            "error": error,
            "success": success,
            "form_amount": form_amount,
            "form_currency": form_currency,
            "form_policy_id": form_policy_id,
            "form_include_satellite": form_include_satellite,
            "saved_proposal_id": saved_proposal_id,
        },
    )


@router.get("/propose", response_class=HTMLResponse)
async def propose_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> HTMLResponse:
    return await _render_form(request, db)


@router.post("/propose", response_class=HTMLResponse)
async def generate_proposal_action(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    amount: Annotated[str, Form()],
    currency: Annotated[str, Form()],
    policy_id: Annotated[str, Form()],
    include_satellite: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    form_sat = include_satellite is not None

    try:
        parsed_amount = Decimal(amount.strip())
    except (InvalidOperation, ValueError):
        return await _render_form(
            request,
            db,
            error=f"Invalid amount: {amount}",
            form_amount=amount,
            form_currency=currency,
            form_policy_id=policy_id,
            form_include_satellite=form_sat,
        )

    try:
        parsed_policy_id = int(policy_id)
    except (ValueError, TypeError):
        return await _render_form(
            request,
            db,
            error="Please select a policy.",
            form_amount=amount,
            form_currency=currency,
            form_policy_id=policy_id,
            form_include_satellite=form_sat,
        )

    try:
        result = await generate_proposal(parsed_policy_id, parsed_amount, currency.strip().upper(), form_sat, db)
    except (ValidationError, DataMissingError) as exc:
        error_msg = exc.message
        if isinstance(exc, PlumblineError) and exc.details:
            error_msg = f"{exc.message}: {exc.details}"
        return await _render_form(
            request,
            db,
            error=error_msg,
            form_amount=amount,
            form_currency=currency,
            form_policy_id=policy_id,
            form_include_satellite=form_sat,
        )

    alloc_json = serialize_allocation_result(result.allocation_result)

    return await _render_form(
        request,
        db,
        result=result,
        allocation_json=alloc_json,
        form_amount=amount,
        form_currency=currency,
        form_policy_id=policy_id,
        form_include_satellite=form_sat,
    )


@router.post("/propose/save", response_class=HTMLResponse)
async def save_proposal_action(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    policy_id: Annotated[int, Form()],
    amount: Annotated[str, Form()],
    currency: Annotated[str, Form()],
    allocation_json: Annotated[str, Form()],
) -> HTMLResponse:
    allocation_result = deserialize_allocation_result(allocation_json)
    saved = await save_proposal(policy_id, Decimal(amount), currency, allocation_result, db)
    await db.commit()

    return await _render_form(
        request,
        db,
        success=f"Proposal saved (ID: {saved.proposal_id})",
        saved_proposal_id=saved.proposal_id,
        form_amount=amount,
        form_currency=currency,
        form_policy_id=str(policy_id),
    )
