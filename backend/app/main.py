import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router
from app.realtime import manager
from app.deadlines import deadline_loop


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


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/ws")
async def realtime(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
