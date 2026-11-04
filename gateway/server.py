"""Bounded admission and explicit failure semantics for non-streaming Ollama calls."""
import asyncio
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass

import aiohttp
from aiohttp import web

LOG = logging.getLogger("gateway")


@dataclass(frozen=True)
class Config:
    upstream: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:1b"
    max_inflight: int = 1
    timeout: float = 60
    probe_timeout: float = 2

    def __post_init__(self):
        if self.max_inflight < 1 or not all(math.isfinite(v) and v > 0
                                          for v in (self.timeout, self.probe_timeout)):
            raise ValueError("capacity and timeouts must be positive and finite")
        if not self.upstream.startswith(("http://", "https://")):
            raise ValueError("upstream must be an HTTP URL")


class Failure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class Gateway:
    def __init__(self, config):
        self.config = config
        self.active = 0
        self.diagnostics = 0
        self.session = None

    async def upstream(self, path, payload=None, timeout=None):
        try:
            # A single deadline includes connection acquisition, headers and body.
            async with asyncio.timeout(timeout or self.config.timeout):
                async with self.session.request(
                    "POST" if payload is not None else "GET",
                    self.config.upstream.rstrip("/") + path, json=payload,
                    allow_redirects=False,
                ) as response:
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise Failure(502, "upstream_response_too_large")
                    if response.status != 200:
                        raise Failure(503 if response.status in (404, 429, 503) else 502,
                                      "upstream_http_error")
                    try:
                        result = json.loads(body)
                    except (ValueError, UnicodeError):
                        raise Failure(502, "upstream_invalid_json")
                    if not isinstance(result, dict) or "error" in result:
                        raise Failure(502, "upstream_invalid_response")
                    return result
        except TimeoutError:
            raise Failure(504, "upstream_timeout")
        except aiohttp.ClientError:
            raise Failure(503, "upstream_unavailable")

    async def payload(self, request):
        try:
            async with asyncio.timeout(5):
                value = await request.json()
        except TimeoutError:
            raise Failure(408, "request_body_timeout")
        except (ValueError, UnicodeError):
            raise Failure(400, "invalid_json")
        if not isinstance(value, dict):
            raise Failure(400, "invalid_request")
        return value

    async def generate(self, request):
        value = await self.payload(request)
        if set(value) - {"model", "prompt", "stream", "options", "keep_alive"}:
            raise Failure(400, "unsupported_field")
        if value.get("model") != self.config.model:
            raise Failure(400, "unsupported_model")
        if value.get("stream", False) is not False:
            raise Failure(400, "streaming_not_supported")
        if not isinstance(value.get("prompt"), str) or not value["prompt"].strip():
            raise Failure(400, "invalid_prompt")
        if value.get("keep_alive", "10m") != "10m":
            raise Failure(400, "unsupported_keep_alive")
        options = value.get("options", {})
        bounds = {"num_predict": (1, 2048), "num_ctx": (512, 32768),
                  "temperature": (0, 2), "seed": (0, 2147483647)}
        if not isinstance(options, dict) or set(options) - bounds.keys():
            raise Failure(400, "invalid_options")
        for key, number in options.items():
            lo, hi = bounds[key]
            if (type(number) not in (int, float) or not math.isfinite(number)
                    or not lo <= number <= hi or (key != "temperature" and type(number) is not int)):
                raise Failure(400, "invalid_options")
        # No await between check and increment: atomic within this event loop.
        if self.active >= self.config.max_inflight:
            raise Failure(429, "capacity_exceeded")
        self.active += 1
        try:
            result = await self.upstream("/api/generate", {**value, "stream": False, "keep_alive": "10m"})
            if result.get("done") is not True or not isinstance(result.get("response"), str):
                raise Failure(502, "upstream_incomplete_response")
            return web.json_response(result)
        finally:
            self.active -= 1

    async def diagnostic(self, request):
        if self.diagnostics >= 2:
            raise Failure(503, "diagnostics_busy")
        self.diagnostics += 1
        try:
            if request.path == "/readyz":
                result = await self.upstream("/api/tags", timeout=self.config.probe_timeout)
                models = result.get("models")
                if not isinstance(models, list) or not any(
                    isinstance(m, dict) and m.get("name") == self.config.model for m in models
                ):
                    raise Failure(503, "model_not_available")
                return web.json_response({"ready": True, "model": self.config.model,
                                          "meaning": "reachable and installed; not necessarily warm"})
            payload = None
            if request.path == "/api/show":
                value = await self.payload(request)
                if value != {"model": self.config.model}:
                    raise Failure(400, "unsupported_model")
                payload = value
            result = await self.upstream(request.path, payload, self.config.probe_timeout)
            return web.json_response(result)
        finally:
            self.diagnostics -= 1


def create_app(config=None):
    gateway = Gateway(config or Config())

    @web.middleware
    async def audit(request, handler):
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        try:
            response = await handler(request)
        except Failure as exc:
            response = web.json_response({"error": {"code": exc.code, "request_id": request_id}},
                                         status=exc.status)
            if exc.status == 429:
                response.headers["Retry-After"] = "1"
        except web.HTTPException as exc:
            response = web.json_response({"error": {"code": "http_error", "request_id": request_id}},
                                         status=exc.status)
        response.headers["X-Request-ID"] = request_id
        LOG.info(json.dumps({"request_id": request_id, "method": request.method,
                             "route": request.match_info.route.resource.canonical
                             if request.match_info.route.resource else "unmatched",
                             "status": response.status,
                             "duration_ms": (time.monotonic() - started) * 1000}))
        return response

    app = web.Application(middlewares=[audit], client_max_size=65536)

    async def lifecycle(app):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None),
                                        connector=aiohttp.TCPConnector(limit=gateway.config.max_inflight + 2)) as session:
            gateway.session = session
            yield

    app.cleanup_ctx.append(lifecycle)
    async def health(request):
        return web.json_response({"alive": True})

    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", gateway.diagnostic)
    for name in ("version", "tags", "ps"):
        app.router.add_get("/api/" + name, gateway.diagnostic)
    app.router.add_post("/api/show", gateway.diagnostic)
    app.router.add_post("/api/generate", gateway.generate)
    return app
