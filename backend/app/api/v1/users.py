from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, require_admin, require_operator, require_viewer
from app.core.errors import ConflictError, ForbiddenError, ValidationFailed
from app.database.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.repositories.base import paginate
from app.repositories.domain import UserRepository
from app.schemas.auth import ProfileUpdate, UserCreate, UserOut, UserUpdate
from app.schemas.common import Page, PageParams
from app.schemas.incident import UserRef
from app.security.passwords import hash_password, validate_password_policy
from app.services import audit, auth_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/assignable", response_model=list[UserRef], summary="Operators/admins that can own incidents"
)
def assignable(
    db: Session = Depends(get_db), _: Principal = Depends(require_operator)
) -> list[UserRef]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))
    return [UserRef.model_validate(u) for u in users if set(u.role_names) & {"OPERATOR", "ADMIN"}]


@router.patch("/me", response_model=UserOut)
def update_profile(
    body: ProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_viewer),
) -> UserOut:
    principal.user.full_name = body.full_name.strip()
    audit.record(
        db,
        action="user.update_profile",
        resource_type="user",
        resource_id=principal.user.id,
        actor=principal.user,
        ip=client_ip(request),
    )
    return UserOut.model_validate(principal.user)


@router.get("", response_model=Page[UserOut])
def list_users(
    params: PageParams = Depends(),
    search: str | None = Query(None, max_length=100),
    active: bool | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_admin),
) -> Page[UserOut]:
    rows, total = paginate(db, UserRepository(db).list(search, active, sort), params)
    return Page.build(
        [UserOut.model_validate(u) for u in rows], total, params.page, params.page_size
    )


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> UserOut:
    try:
        with db.begin_nested():
            user = auth_service.create_user(
                db,
                email=body.email,
                username=body.username,
                password=body.password,
                role=body.role,
                full_name=body.full_name,
                must_change_password=body.must_change_password,
            )
    except IntegrityError as exc:
        raise ConflictError("A user with that email or username already exists") from exc
    audit.record(
        db,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"role": body.role.value},
    )
    return UserOut.model_validate(user)


def _admin_count(db: Session) -> int:
    from app.models import Role, UserRole

    return int(
        db.scalar(
            select(func.count(User.id))
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "ADMIN", User.is_active.is_(True))
        )
        or 0
    )


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> UserOut:
    user = UserRepository(db).get_or_404(user_id)
    is_admin = "ADMIN" in user.role_names
    demoting = body.role is not None and body.role != RoleName.ADMIN and is_admin
    disabling = body.is_active is False and user.is_active
    if (demoting or disabling) and is_admin and _admin_count(db) <= 1:
        raise ForbiddenError(
            "Cannot remove or disable the last active administrator", code="last_admin"
        )
    if user.id == principal.user.id and (demoting or disabling):
        raise ForbiddenError("You cannot demote or disable your own account", code="self_lockout")
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.roles = [auth_service.get_role(db, body.role)]
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            auth_service.revoke_all_sessions(db, user.id)
    if body.must_change_password is not None:
        user.must_change_password = body.must_change_password
    if body.password:
        validate_password_policy(body.password)
        user.password_hash = hash_password(body.password)
        user.must_change_password = True
        auth_service.revoke_all_sessions(db, user.id)
    db.flush()
    audit.record(
        db,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        actor=principal.user,
        ip=client_ip(request),
        details={
            "fields": sorted(body.model_dump(exclude_unset=True)),
            "password_reset": bool(body.password),
        },
    )
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
):
    from fastapi import Response

    user = UserRepository(db).get_or_404(user_id)
    if user.id == principal.user.id:
        raise ForbiddenError("You cannot delete your own account", code="self_lockout")
    if "ADMIN" in user.role_names and user.is_active and _admin_count(db) <= 1:
        raise ForbiddenError("Cannot delete the last active administrator", code="last_admin")
    name = user.username
    UserRepository(db).delete(user)
    audit.record(
        db,
        action="user.delete",
        resource_type="user",
        resource_id=user_id,
        actor=principal.user,
        ip=client_ip(request),
        details={"username": name},
    )
    if name == "":  # pragma: no cover
        raise ValidationFailed("invalid")
    return Response(status_code=204)
