"""User CRUD operations."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth.providers import hash_password, verify_password
from core.exceptions import InvalidCredentialsError, NotFoundError
from core.models.common import UserCreate, UserUpdate
from core.models.user import Role, User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Find a user by email address, eagerly loading their role."""
    stmt = select(User).where(User.email == email).options(selectinload(User.role))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    """Find a user by ID."""
    stmt = select(User).where(User.id == user_id).options(selectinload(User.role))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    data: UserCreate,
) -> User:
    """Create a new user with a local password hash."""
    role_id = None
    if data.role_name:
        result = await session.execute(select(Role).where(Role.name == data.role_name))
        role = result.scalar_one_or_none()
        if role:
            role_id = role.id

    user = User(
        id=str(uuid.uuid4()),
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        org_id=data.org_id,
        team_id=data.team_id,
        role_id=role_id,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user, ["role"])
    return user


async def create_user_from_keycloak(
    session: AsyncSession,
    *,
    keycloak_sub: str,
    email: str,
    full_name: str,
    role_name: str = "scientist",
    org_id: str,
    team_id: str | None = None,
) -> User:
    """Create a local user record for a Keycloak-authenticated user.

    No password is stored — authentication is handled entirely by Keycloak.
    The user ID is set to the Keycloak ``sub`` claim so that token payloads
    match the local DB record.
    """
    role_id = None
    if role_name:
        result = await session.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one_or_none()
        if role:
            role_id = role.id

    user = User(
        id=keycloak_sub,
        email=email,
        full_name=full_name,
        hashed_password=None,
        org_id=org_id,
        team_id=team_id,
        role_id=role_id,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user, ["role"])
    return user


async def get_or_create_from_keycloak(
    session: AsyncSession,
    *,
    sub: str,
    email: str,
    full_name: str,
    role_name: str | None = None,
    org_id: str,
    team_id: str | None = None,
) -> User:
    """JIT (Just-In-Time) user provisioning from a Keycloak token.

    If the user already exists (by email), return them and update their
    Keycloak sub if needed. Otherwise, create a new local record.

    Raises ValueError if org_id is not provided.
    """
    if not org_id:
        raise ValueError("org_id is required for user provisioning")
    if not email or "@" not in email:
        raise ValueError(f"Cannot JIT-provision user with invalid email: {email!r}")

    # First try by email (most reliable — Keycloak sub may differ across realms)
    user = await get_user_by_email(session, email)
    if user is not None:
        # Track the Keycloak sub as external_id (don't mutate the PK —
        # it's referenced by audit_logs and other FK tables).
        if user.external_id != sub:
            user.external_id = sub
            await session.flush()
        return user

    # Also try by external_id (sub) in case email changed
    result = await session.execute(select(User).where(User.external_id == sub))
    user = result.scalar_one_or_none()
    if user is not None:
        user.email = email
        await session.flush()
        return user

    # Also try by ID (sub) for legacy records where id == keycloak sub
    user = await get_user_by_id(session, sub)
    if user is not None:
        user.email = email
        user.external_id = sub
        await session.flush()
        return user

    # Fully new user — JIT provision
    return await create_user_from_keycloak(
        session,
        keycloak_sub=sub,
        email=email,
        full_name=full_name,
        role_name=role_name or "scientist",
        org_id=org_id,
        team_id=team_id,
    )


async def update_user(session: AsyncSession, user_id: str, data: UserUpdate) -> User:
    """Update an existing user."""
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User", user_id)

    update_data = data.model_dump(exclude_unset=True)

    # org_id is immutable via normal update — only AdminUserUpdate allows it
    update_data.pop("org_id", None)

    # Handle role_name -> role_id resolution
    if "role_name" in update_data:
        role_name = update_data.pop("role_name")
        if role_name:
            result = await session.execute(select(Role).where(Role.name == role_name))
            role = result.scalar_one_or_none()
            if role:
                user.role_id = role.id

    for field, value in update_data.items():
        setattr(user, field, value)

    await session.flush()
    return user


async def list_users(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    org_id: str | None = None,
) -> list[User]:
    """List users with optional org filter."""
    stmt = (
        select(User)
        .options(selectinload(User.role))
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    )
    if org_id:
        stmt = stmt.where(User.org_id == org_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_users(session: AsyncSession, org_id: str | None = None) -> int:
    """Count users with optional org filter."""
    stmt = select(func.count(User.id))
    if org_id:
        stmt = stmt.where(User.org_id == org_id)
    result = await session.execute(stmt)
    return result.scalar_one()


async def change_password(
    session: AsyncSession,
    user_id: str,
    current_password: str,
    new_password: str,
) -> User:
    """Change a local user's password after verifying the current one.

    Raises NotFoundError if user doesn't exist, HTTPException (400) if the
    user is SSO-only, and InvalidCredentialsError if current password is wrong.
    """
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User", user_id)

    if not user.hashed_password:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Password change is not available for SSO-authenticated accounts",
        )

    if not verify_password(current_password, user.hashed_password):
        raise InvalidCredentialsError()

    user.hashed_password = hash_password(new_password)
    await session.flush()
    return user
