import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.domain import UserRole
from app.models import User

PIN_ITERATIONS = 210_000
bearer = HTTPBearer(auto_error=False)


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITERATIONS)
    return f"pbkdf2_sha256${PIN_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "role": user.role.value,
        "ver": user.session_version or 0,
        "exp": int(time.time()) + settings.access_token_minutes * 60,
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def decode_access_token(token: str) -> dict:
    try:
        body, encoded_signature = token.split(".", 1)
        signature = _b64decode(encoded_signature)
        expected = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(_b64decode(body))
        if not isinstance(payload.get("sub"), int) or payload.get("exp", 0) < time.time():
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия недействительна или истекла")


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход в систему")
    payload = decode_access_token(credentials.credentials)
    user = await session.get(User, payload["sub"])
    if not valid_user_session(user, payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия отозвана или учётная запись заблокирована")
    return user


def valid_user_session(user: User | None, payload: dict) -> bool:
    # Legacy tokens without ver remain valid only until the account's first revocation.
    return bool(user and user.is_active and payload.get("ver", 0) == user.session_version)


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return user

    return dependency
