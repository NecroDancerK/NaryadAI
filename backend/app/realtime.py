from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()
        self.user_ids: dict[WebSocket, int] = {}

    async def connect(self, websocket: WebSocket, user_id: int | None = None) -> None:
        await websocket.accept()
        self.connections.add(websocket)
        if user_id is not None:
            self.user_ids[websocket] = user_id

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)
        self.user_ids.pop(websocket, None)

    async def revoke_user(self, user_id: int) -> None:
        for connection, owner in list(self.user_ids.items()):
            if owner == user_id:
                self.disconnect(connection)
                try:
                    await connection.close(code=4401)
                except Exception:
                    pass

    async def broadcast(self, event: dict) -> None:
        event["connected_clients"] = len(self.connections)
        stale: list[WebSocket] = []
        for connection in list(self.connections):
            try:
                await connection.send_json(event)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


manager = ConnectionManager()
