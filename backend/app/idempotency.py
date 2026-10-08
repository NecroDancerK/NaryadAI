"""Successful receipts and side effects share one database transaction."""
import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from app.models import IdempotentAction
from app.schemas import WorkOrderRead


def request_hash(operation, order_id, payload):
    body = json.dumps([operation, order_id, payload], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


async def replay(session, actor_id, key, fingerprint):
    if key is None:
        return None
    try:
        if str(UUID(key)) != key:
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(422, "Idempotency-Key должен быть UUID в каноническом формате")
    # Transaction-scoped PG lock also serializes reuse across different orders/endpoints.
    lock_id = int.from_bytes(hashlib.sha256(f"{actor_id}:{key}".encode()).digest()[:8], signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
    receipt = await session.scalar(select(IdempotentAction).where(
        IdempotentAction.actor_id == actor_id, IdempotentAction.key == key))
    if receipt:
        if receipt.request_hash != fingerprint:
            raise HTTPException(409, "Ключ действия уже использован с другим содержимым")
        return receipt.response_body
    return None


async def commit_action(session, order, actor_id, key, fingerprint):
    await session.flush()
    await session.refresh(order)
    body = WorkOrderRead.model_validate(order).model_dump(mode="json")
    if key is not None:
        session.add(IdempotentAction(actor_id=actor_id, key=key, request_hash=fingerprint, response_body=body))
    await session.commit()
    return body
