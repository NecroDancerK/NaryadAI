import asyncio
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

from app.routes import router
from app.vision_routes import router as vision_router
from app.admin_routes import router as admin_router
from app.realtime import manager
from app.deadlines import deadline_loop
from app.auth import decode_access_token, valid_user_session
from app.database import SessionLocal
from app.models import User


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(deadline_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="НарядAI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(vision_router)
app.include_router(admin_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    if request.url.path.startswith("/api/admin/"):
        # Validation errors must not echo PIN input or the submitted credentials.
        return JSONResponse(status_code=422, content={"detail": "Проверьте поля: логин, имя, роль и PIN (6–8 цифр)"})
    return await request_validation_exception_handler(request, error)


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/ws")
async def realtime(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = decode_access_token(token)
    except Exception:
        await websocket.close(code=4401)
        return
    async with SessionLocal() as session:
        if not valid_user_session(await session.get(User, payload["sub"]), payload):
            await websocket.close(code=4401)
            return
    await manager.connect(websocket, payload["sub"])
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                pass
            async with SessionLocal() as session:
                if not valid_user_session(await session.get(User, payload["sub"]), payload) or payload["exp"] < time.time():
                    await websocket.close(code=4401)
                    break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
