import asyncio
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.server import Config, create_app


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mode = "ok"
        self.received = None
        self.release = asyncio.Event()

        async def fake_ollama(request):
            self.received = await request.json()

            if self.mode == "slow":
                await self.release.wait()
            if self.mode == "invalid":
                return web.Response(text="not JSON")

            return web.json_response({
                "done": True,
                "response": "test answer",
                "eval_count": 2,
            })

        upstream_app = web.Application()
        upstream_app.router.add_post("/api/generate", fake_ollama)
        self.upstream = TestServer(upstream_app)
        await self.upstream.start_server()

        config = Config(
            upstream=str(self.upstream.make_url("/")).rstrip("/"),
            timeout=0.1,
        )
        self.client = TestClient(TestServer(create_app(config)))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.release.set()
        await self.client.close()
        await self.upstream.close()

    async def generate(self):
        return await self.client.post("/api/generate", json={
            "model": "llama3.2:1b",
            "prompt": "test prompt",
            "stream": False,
        })

    async def assert_error(self, response, status, code):
        self.assertEqual(response.status, status)
        body = await response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertEqual(
            body["error"]["request_id"],
            response.headers["X-Request-ID"],
        )

    async def test_forwards_request_and_response(self):
        response = await self.generate()
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["response"], "test answer")
        self.assertEqual(self.received["prompt"], "test prompt")
        self.assertFalse(self.received["stream"])

    async def test_timeout_returns_504(self):
        self.mode = "slow"
        response = await self.generate()
        await self.assert_error(response, 504, "upstream_timeout")

    async def test_connection_failure_returns_503(self):
        original_request = aiohttp.ClientSession.request
        upstream_url = str(self.upstream.make_url("/api/generate"))

        def request_with_failure(session, method, url, **kwargs):
            if str(url) == upstream_url:
                raise aiohttp.ClientConnectionError("test failure")
            return original_request(session, method, url, **kwargs)

        with patch(
            "gateway.server.aiohttp.ClientSession.request",
            new=request_with_failure,
        ):
            response = await self.generate()

        await self.assert_error(response, 503, "upstream_unavailable")

    async def test_invalid_upstream_json_returns_502(self):
        self.mode = "invalid"
        response = await self.generate()
        await self.assert_error(response, 502, "upstream_invalid_json")