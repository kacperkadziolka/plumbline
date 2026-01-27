from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.templating import Jinja2Templates

from app.api.main import api_router
from app.core.config import settings
from app.core.errors import DataMissingError, PlumblineError, PolicyError, ValidationError
from app.infrastructure.db import init_db
from app.web.main import web_router

templates = Jinja2Templates(directory="app/web/templates")

# Order matters: subclasses must come before base class for isinstance checks
ERROR_TYPE_LABELS: tuple[tuple[type[PlumblineError], str], ...] = (
    (ValidationError, "Validation Error"),
    (DataMissingError, "Data Not Found"),
    (PolicyError, "Policy Error"),
    (PlumblineError, "Application Error"),  # Base class last
)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.include_router(web_router)
app.include_router(api_router, prefix=settings.API_V1_STR)


def _is_api_request(request: Request) -> bool:
    """Check if the request is for the API (JSON) vs web (HTML)."""
    return request.url.path.startswith(settings.API_V1_STR)


def _get_error_label(exc: PlumblineError) -> str:
    """Get human-readable error type label."""
    for error_class, label in ERROR_TYPE_LABELS:
        if isinstance(exc, error_class):
            return label
    return "Error"


@app.exception_handler(PlumblineError)
async def plumbline_error_handler(request: Request, exc: PlumblineError) -> HTMLResponse | JSONResponse:
    """Handle all Plumbline domain/application errors."""
    if _is_api_request(request):
        return JSONResponse(
            status_code=400,
            content={
                "error": type(exc).__name__,
                "message": exc.message,
                "details": exc.details,
            },
        )

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "error_type": _get_error_label(exc),
            "message": exc.message,
            "details": exc.details,
        },
        status_code=400,
    )
