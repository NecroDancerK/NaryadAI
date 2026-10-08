import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from pydantic import SecretStr
from pydantic import ValidationError
from app.config import Settings

from app import vision


class VisionClientTest(unittest.IsolatedAsyncioTestCase):
    def test_only_local_model_urls_are_allowed(self):
        for url in ("http://127.0.0.1:8081", "http://host.docker.internal:8081", "http://172.17.0.1:8081"):
            self.assertEqual(Settings(vlm_base_url=url, _env_file=None).vlm_base_url, url)
        for url in ("https://example.com", "http://8.8.8.8", "http://user:secret@127.0.0.1:8081"):
            with self.assertRaises(ValidationError):
                Settings(vlm_base_url=url, _env_file=None)

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "photo.jpg"
        self.path.write_bytes(b"\xff\xd8\xfftest")
        self.photos = [SimpleNamespace(file_path=str(self.path), photo_type="after")]

    async def asyncTearDown(self):
        self.directory.cleanup()

    def client(self, handler):
        real_client = httpx.AsyncClient
        return patch.object(vision.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))

    async def test_structured_observations_force_human_review(self):
        def handler(request):
            import json
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], vision.settings.vlm_model)
            self.assertNotIn("seed",payload)
            self.assertEqual(request.headers["Authorization"], "Bearer test-only")
            self.assertNotIn(self.path.name, request.content.decode())
            return httpx.Response(200, json={"choices":[{"finish_reason":"stop", "message":{"content":'{"observations":["Видно пятно"],"limitations":[],"needs_human_review":false}'}}]})
        with patch.object(vision.settings, "vlm_api_key", SecretStr("test-only")), self.client(handler):
            result = await vision.observe(self.photos)
        self.assertTrue(result["needs_human_review"])
        self.assertNotIn("score", result)
        self.assertTrue(result["limitations"])

    async def test_benchmark_seed_is_opt_in(self):
        def handler(request):
            import json
            payload=json.loads(request.content)
            self.assertEqual(payload['seed'],42)
            self.assertFalse(payload['chat_template_kwargs']['enable_thinking'])
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"observations":["Видно пятно"],"limitations":["Состав неизвестен"]}'}}]})
        with self.client(handler):
            await vision.observe(self.photos,seed=42)

    async def test_truncated_or_invalid_results_are_not_accepted(self):
        for finish, content in (("length", '{}'), ("stop", 'not-json'), ("stop", '{"observations":[],"limitations":[]}')):
            with self.client(lambda request: httpx.Response(200, json={"choices":[{"finish_reason":finish,"message":{"content":content}}]})):
                with self.assertRaises(vision.VisionError):
                    await vision.observe(self.photos)

    async def test_timeout_is_an_explicit_failure(self):
        def handler(request):
            raise httpx.ReadTimeout("timeout", request=request)
        with self.client(handler):
            with self.assertRaisesRegex(vision.VisionError, "отведённое время"):
                await vision.observe(self.photos)

    async def test_mislabeled_image_is_not_sent(self):
        self.path.write_bytes(b"<svg>untrusted</svg>")
        with patch.object(vision.httpx, "AsyncClient") as client:
            with self.assertRaises(vision.VisionError):
                await vision.observe(self.photos)
            client.assert_not_called()
