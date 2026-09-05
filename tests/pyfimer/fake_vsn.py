"""A fake VSN300 / VSN700 REST server for tests, on aiohttp's test server."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

from aiohttp import web

REALM = "VSN300"
NONCE = "b7e2a0f4c9d1"


def _md5(value: str) -> str:
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


@dataclass
class FakeVsn:
    """Serves status and livedata the way a card does, with its authentication."""

    model: str
    status: dict[str, Any]
    livedata: dict[str, Any]
    username: str = "guest"
    password: str = "secret"  # noqa: S105
    requires_auth: bool = True
    livedata_status: int = 200
    """HTTP status for livedata, to fake a card that refuses it."""
    requests: list[str] = field(default_factory=list)

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/v1/status", self._handler(lambda: self.status))
        app.router.add_get("/v1/livedata", self._handler(lambda: self.livedata, "livedata"))
        return app

    def _handler(
        self, payload: Callable[[], dict[str, Any]], name: str = "status"
    ) -> Callable[[web.Request], Any]:
        async def handle(request: web.Request) -> web.Response:
            self.requests.append(f"{request.method} {request.path_qs}")
            if self.requires_auth and not self._authorized(request):
                return self._challenge()
            if name == "livedata" and self.livedata_status != 200:
                return web.Response(status=self.livedata_status)
            return web.json_response(payload())

        return handle

    def _challenge(self) -> web.Response:
        if self.model == "VSN300":
            header = f'X-Digest realm="{REALM}", nonce="{NONCE}", qop="auth"'
        else:
            header = 'Basic realm="VSN700"'
        return web.Response(status=401, headers={"WWW-Authenticate": header})

    def _authorized(self, request: web.Request) -> bool:
        auth = request.headers.get("Authorization", "")
        if self.model == "VSN700":
            expected = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            return auth == f"Basic {expected}"
        if not auth.startswith("X-Digest "):
            return False
        params = dict(re.findall(r'(\w+)=(?:"([^"]*)")', auth))
        qop = re.search(r"qop=(\w+)", auth)
        ha1 = _md5(f"{self.username}:{REALM}:{self.password}")
        ha2 = _md5(f"GET:{params.get('uri', '')}")
        if qop:
            expected = _md5(
                f"{ha1}:{NONCE}:{params['nc'] if 'nc' in params else _nc(auth)}:{params['cnonce']}:{qop.group(1)}:{ha2}"
            )
        else:
            expected = _md5(f"{ha1}:{NONCE}:{ha2}")
        return params.get("response") == expected and params.get("uri") == request.path


def _nc(auth: str) -> str:
    match = re.search(r"nc=([0-9a-fA-F]+)", auth)
    return match.group(1) if match else ""
