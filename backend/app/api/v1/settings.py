from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, require_admin, require_viewer
from app.database.session import get_db
from app.schemas.ops import SettingOut, SettingsUpdate
from app.services import audit, settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingOut])
def get_settings_(
    db: Session = Depends(get_db), _: Principal = Depends(require_viewer)
) -> list[dict]:
    return settings_service.list_settings(db)


@router.patch("", response_model=list[SettingOut])
def patch_settings(
    body: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> list[dict]:
    changed = settings_service.update(db, body.values, principal.user.username)
    audit.record(
        db,
        action="settings.update",
        resource_type="settings",
        actor=principal.user,
        ip=client_ip(request),
        details={"changed": changed},
    )
    return settings_service.list_settings(db)
