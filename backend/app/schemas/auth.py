from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import RoleName
from app.schemas.common import ORMModel

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class LoginRequest(BaseModel):
    # "identifier" is an email or username.
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str
    user: UserOut


class RefreshRequest(BaseModel):
    # Optional: non-browser clients may send the refresh token in the body instead of the cookie.
    refresh_token: str | None = Field(default=None, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    username: str
    full_name: str
    is_active: bool
    must_change_password: bool
    roles: list[str] = Field(validation_alias="role_names")
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    email: str = Field(max_length=255)
    username: str
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=1, max_length=256)
    role: RoleName = RoleName.VIEWER
    must_change_password: bool = True

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip()
        if not _USERNAME_RE.match(v):
            raise ValueError("username must be 3-64 chars of letters, digits, '_', '.', '-'")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    role: RoleName | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=256)
    must_change_password: bool | None = None


class ProfileUpdate(BaseModel):
    full_name: str = Field(max_length=255)


TokenResponse.model_rebuild()
