from fastapi import APIRouter

from app.web.routes import import_routes, pages

web_router = APIRouter()
web_router.include_router(pages.router)
web_router.include_router(import_routes.router)
