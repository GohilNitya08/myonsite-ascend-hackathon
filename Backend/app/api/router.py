"""Top-level API router composition."""

from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.files import router as files_router
from app.api.routes.folders import router as folders_router
from app.api.routes.health import router as health_router
from app.api.routes.integrity import router as integrity_router
from app.api.routes.shares import router as shares_router
from app.api.routes.users import router as users_router
from app.api.routes.workspaces import router as workspaces_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(files_router)
api_router.include_router(folders_router)
api_router.include_router(integrity_router)
api_router.include_router(shares_router)
api_router.include_router(users_router)
api_router.include_router(workspaces_router)
