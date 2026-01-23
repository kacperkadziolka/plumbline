from fastapi import APIRouter

from app.web.routes import pages

web_router = APIRouter()
web_router.include_router(pages.router)
