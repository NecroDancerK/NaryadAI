"""Manual-browser fault harness, never imported by app.main or production routes.

Run only against a disposable *_test database. Set control JSON to
{"mode":"drop_completion_reply"}, then to {"mode":"pass"} for recovery.
"""
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.main import app
from app import routes

if not make_url(settings.database_url).database.endswith("_test"):
    raise RuntimeError("Acceptance harness requires an isolated *_test database")

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:15173"],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
routes.STORAGE_DIR = Path("/tmp/naryad-acceptance-photos")

CONTROL = Path(os.environ.get("ACCEPTANCE_CONTROL", "/acceptance-control.json"))


class ReplyLossHarness:
    def __init__(self):
        self.dropped = False

    async def __call__(self, scope, receive, send):
        mode = json.loads(CONTROL.read_text()).get("mode") if CONTROL.exists() else "pass"
        completion = scope["type"] == "http" and scope.get("method") == "POST" and scope["path"].endswith("/complete")
        if completion and mode == "drop_completion_reply" and self.dropped:
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"detail":"Acceptance test: replies held"}'})
            return
        lost = False
        async def fault_send(message):
            nonlocal lost
            if completion and mode == "drop_completion_reply" and message["type"] == "http.response.start" and message["status"] == 200:
                lost = True
                headers = [(key, value) for key, value in message["headers"] if key.lower() != b"content-length"]
                # Start a reply but never complete its body: fetch/json sees a network read failure.
                await send({**message, "headers": headers})
            elif lost and message["type"] == "http.response.body":
                self.dropped = True
                await send({**message, "more_body": True})
                raise ConnectionResetError("Acceptance test: reply dropped AFTER order commit")
            else:
                await send(message)
        await app(scope, receive, fault_send)


application = ReplyLossHarness()
