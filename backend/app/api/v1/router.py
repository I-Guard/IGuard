from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    audit,
    auth,
    incidents,
    logs,
    recovery,
    reports,
    servers,
    services,
    settings,
    system,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for module in (
    system,
    auth,
    servers,
    services,
    incidents,
    recovery,
    logs,
    alerts,
    audit,
    reports,
    settings,
    users,
):
    api_router.include_router(module.router)
