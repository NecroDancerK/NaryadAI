"""Run locally: python -m app.bootstrap_admin --login admin --name 'System admin'."""
import argparse
import asyncio
import getpass

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.admin_routes import ADMIN_LOCK, UserCreate
from app.auth import hash_pin
from app.database import SessionLocal
from app.domain import UserRole
from app.models import AdminAudit, User


async def bootstrap(payload: UserCreate):
    async with SessionLocal() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK})
        if await session.scalar(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))):
            raise ValueError("Активный администратор уже есть. Новых пользователей создавайте через его кабинет")
        user = User(login=payload.login, full_name=payload.full_name, role=UserRole.ADMIN,
                    specialty=None, pin_hash=hash_pin(payload.pin), is_active=True, session_version=0)
        session.add(user)
        try:
            await session.flush()
            session.add(AdminAudit(actor_id=user.id, target_id=user.id, action="admin.bootstrapped",
                                   changes={"login": user.login, "role": "admin"}))
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise ValueError("Логин уже занят. Существующая учётная запись не изменена") from error
        print(f"Администратор {user.login} создан. PIN не сохраняется в выводе команды")


def main():
    parser = argparse.ArgumentParser(description="Создать первого администратора после миграции БД")
    parser.add_argument("--login", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    pin = getpass.getpass("Новый PIN (6–8 цифр): ")
    if pin != getpass.getpass("Повторите PIN: "):
        parser.exit(1, "PIN-коды не совпадают\n")
    try:
        payload = UserCreate(login=args.login, full_name=args.name, role=UserRole.ADMIN, pin=pin)
        asyncio.run(bootstrap(payload))
    except ValidationError:
        parser.exit(1, "Проверьте логин (латиница, цифры, ._-), имя и PIN (6–8 цифр)\n")
    except ValueError as error:
        parser.exit(1, str(error)+"\n")


if __name__ == "__main__":
    main()
