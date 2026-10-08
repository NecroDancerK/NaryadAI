"""Administrator-only account management; credentials never enter audit responses."""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_pin, require_roles
from app.database import get_session
from app.domain import UserRole, WorkOrderStatus
from app.models import AdminAudit, User, WorkOrder
from app.realtime import manager

router = APIRouter(prefix="/api/admin", tags=["administration"])
ADMIN_LOCK = 710011


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=160)
    role: UserRole
    specialty: str | None = Field(default=None, max_length=100)

    @field_validator("full_name", "specialty", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserCreate(UserProfile):
    login: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    pin: str = Field(pattern=r"^[0-9]{6,8}$")

    @field_validator("login", mode="before")
    @classmethod
    def normalize_login(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserUpdate(UserProfile):
    is_active: bool
    expected_session_version: int = Field(ge=0)


class PinReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str = Field(pattern=r"^[0-9]{6,8}$")
    expected_session_version: int = Field(ge=0)


class AdminUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login: str
    full_name: str
    role: UserRole
    specialty: str | None
    is_active: bool
    session_version: int


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int
    target_id: int
    action: str
    changes: dict
    created_at: datetime


async def admin_lock(session: AsyncSession, actor: User):
    version = actor.session_version
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK})
    await session.refresh(actor)
    if not actor.is_active or actor.role != UserRole.ADMIN or actor.session_version != version:
        raise HTTPException(401, "Права администратора изменились. Войдите заново")


async def save(session: AsyncSession):
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(409, "Пользователь с таким логином уже существует") from error


@router.get("/users", response_model=list[AdminUserRead])
async def list_users(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                     _: User = Depends(require_roles(UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(User).order_by(User.id).offset(offset).limit(limit))).all()


@router.post("/users", response_model=AdminUserRead, status_code=201)
async def create_user(payload: UserCreate, actor: User = Depends(require_roles(UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    await admin_lock(session, actor)
    user = User(login=payload.login, full_name=payload.full_name, role=payload.role,
                specialty=payload.specialty if payload.role == UserRole.WORKER else None,
                pin_hash=await asyncio.to_thread(hash_pin, payload.pin), is_active=True, session_version=0)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(409, "Пользователь с таким логином уже существует") from error
    session.add(AdminAudit(actor_id=actor.id, target_id=user.id, action="user.created",
                           changes={"login": user.login, "role": user.role.value, "full_name": user.full_name}))
    await save(session)
    return user


@router.put("/users/{user_id}", response_model=AdminUserRead)
async def update_user(user_id: int, payload: UserUpdate, actor: User = Depends(require_roles(UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    await admin_lock(session, actor)
    user = await session.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.session_version != payload.expected_session_version:
        raise HTTPException(409, "Доступ пользователя уже изменился. Обновите список")
    if actor.id == user.id and (not payload.is_active or payload.role != UserRole.ADMIN):
        raise HTTPException(409, "Нельзя заблокировать себя или снять свою роль администратора")
    removes_admin = user.is_active and user.role == UserRole.ADMIN and (not payload.is_active or payload.role != UserRole.ADMIN)
    if removes_admin and (await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role == UserRole.ADMIN))) <= 1:
        raise HTTPException(409, "Нельзя отключить последнего активного администратора")
    if user.role != payload.role:
        owns_open_orders = await session.scalar(select(WorkOrder.id).where(
            (WorkOrder.assignee_id == user.id) | (WorkOrder.master_id == user.id),
            WorkOrder.status != WorkOrderStatus.CLOSED).limit(1))
        if owns_open_orders:
            raise HTTPException(409, "Сначала завершите или переназначьте незакрытые наряды пользователя")
    fields = {"full_name": payload.full_name, "role": payload.role, "is_active": payload.is_active,
              "specialty": payload.specialty if payload.role == UserRole.WORKER else None}
    changes = {}
    for name, value in fields.items():
        old = getattr(user, name)
        if old != value:
            changes[name] = {"before": old.value if isinstance(old, UserRole) else old,
                             "after": value.value if isinstance(value, UserRole) else value}
            setattr(user, name, value)
    revoked = bool({"role", "is_active"} & changes.keys())
    if revoked:
        user.session_version += 1
    if changes:
        session.add(AdminAudit(actor_id=actor.id, target_id=user.id, action="user.updated", changes=changes))
    await save(session)
    if revoked:
        await manager.revoke_user(user.id)
    return user


@router.post("/users/{user_id}/reset-pin", response_model=AdminUserRead)
async def reset_pin(user_id: int, payload: PinReset, actor: User = Depends(require_roles(UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    await admin_lock(session, actor)
    user = await session.get(User, user_id, with_for_update=True)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.session_version != payload.expected_session_version:
        raise HTTPException(409, "Доступ пользователя уже изменился. Обновите список")
    user.pin_hash = await asyncio.to_thread(hash_pin, payload.pin)
    user.session_version += 1
    session.add(AdminAudit(actor_id=actor.id, target_id=user.id, action="user.pin_reset", changes={"sessions_revoked": True}))
    await save(session)
    await manager.revoke_user(user.id)
    return user


@router.get("/audit", response_model=list[AuditRead])
async def audit(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                _: User = Depends(require_roles(UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(AdminAudit).order_by(AdminAudit.id.desc()).offset(offset).limit(limit))).all()
