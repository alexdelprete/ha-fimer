"""Authentication for the VSN300 and VSN700 datalogger REST APIs.

The VSN300 answers with an ``X-Digest`` challenge (HTTP digest with a
non-standard scheme name) and expects the response in an ``X-Digest``
authorization header. The VSN700 uses preemptive HTTP basic authentication.
Some cards are configured without authentication and answer directly.
"""

from __future__ import annotations

import base64
import hashlib
import re

# The nonce count and client nonce the VSN300's own web UI sends. Every
# firmware accepts its own UI, so these are the safe choice; RFC-style random
# values were reported failing in the field on some builds.
_NONCE_COUNT = "00000002"
_CLIENT_NONCE = "ddf4bfcaf87acba9"


def parse_digest_challenge(www_authenticate: str) -> dict[str, str]:
    """Return the parameters of a ``Digest`` or ``X-Digest`` challenge."""
    challenge = re.sub(r"^(Digest|X-Digest)\s+", "", www_authenticate, flags=re.IGNORECASE)
    params: dict[str, str] = {}
    for match in re.finditer(r'(\w+)=(?:"([^"]+)"|([^,\s]+))', challenge):
        params[match.group(1)] = match.group(2) or match.group(3)
    return params


def digest_response(
    username: str,
    password: str,
    realm: str,
    nonce: str,
    method: str,
    uri: str,
    qop: str | None = None,
) -> str:
    """Return the digest response hash, with or without quality of protection."""
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    if qop:
        return _md5(f"{ha1}:{nonce}:{_NONCE_COUNT}:{_CLIENT_NONCE}:{qop}:{ha2}")
    return _md5(f"{ha1}:{nonce}:{ha2}")


def build_digest_header(
    username: str, password: str, challenge: dict[str, str], method: str, uri: str
) -> str:
    """Return the value of the ``X-Digest`` authorization header for a challenge."""
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    qop = challenge.get("qop")
    response = digest_response(username, password, realm, nonce, method, uri, qop)
    parts = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'response="{response}"',
    ]
    if qop:
        parts += [
            'algorithm="MD5"',
            f"qop={qop}",
            f"nc={_NONCE_COUNT}",
            f'cnonce="{_CLIENT_NONCE}"',
        ]
    if opaque := challenge.get("opaque"):
        parts.append(f'opaque="{opaque}"')
    return ", ".join(parts)


def basic_credentials(username: str, password: str) -> str:
    """Return the base64 credentials of a basic authorization header."""
    return base64.b64encode(f"{username}:{password}".encode()).decode()


def _md5(value: str) -> str:
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()
