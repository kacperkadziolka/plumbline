from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases import get_policy, list_policies, save_policy
from app.core.errors import DataMissingError, ValidationError
from app.infrastructure.db import get_async_db

router = APIRouter(tags=["policy"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/policy", response_class=HTMLResponse)
async def policy_editor_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    id: int | None = None,
) -> HTMLResponse:
    versions = await list_policies(db)

    editor_name = ""
    editor_yaml = ""
    if id is not None:
        try:
            policy = await get_policy(id, db)
            editor_name = policy.name
            editor_yaml = policy.yaml_text
        except DataMissingError:
            pass

    return templates.TemplateResponse(
        request,
        "policy.html",
        {
            "versions": versions.policies,
            "editor_name": editor_name,
            "editor_yaml": editor_yaml,
            "error": None,
            "success": None,
        },
    )


@router.post("/policy", response_class=HTMLResponse)
async def save_policy_action(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    name: Annotated[str, Form()],
    yaml_text: Annotated[str, Form()],
) -> HTMLResponse:
    name = name.strip()
    if not name:
        versions = await list_policies(db)
        return templates.TemplateResponse(
            request,
            "policy.html",
            {
                "versions": versions.policies,
                "editor_name": name,
                "editor_yaml": yaml_text,
                "error": "Policy name is required.",
                "success": None,
            },
        )

    try:
        result = await save_policy(name, yaml_text, db)
        await db.commit()
    except ValidationError as exc:
        versions = await list_policies(db)
        error_msg = exc.message
        if exc.details:
            error_msg = f"{exc.message}: {exc.details}"
        return templates.TemplateResponse(
            request,
            "policy.html",
            {
                "versions": versions.policies,
                "editor_name": name,
                "editor_yaml": yaml_text,
                "error": error_msg,
                "success": None,
            },
        )

    versions = await list_policies(db)

    success_msg = f"Policy saved (hash: {result.policy_hash[:12]}…)"
    if result.already_existed:
        success_msg = f"Policy already exists (hash: {result.policy_hash[:12]}…)"

    return templates.TemplateResponse(
        request,
        "policy.html",
        {
            "versions": versions.policies,
            "editor_name": name,
            "editor_yaml": yaml_text,
            "error": None,
            "success": success_msg,
        },
    )
