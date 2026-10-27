"""Loopback Host, exact Origin and CSRF header; none of them replaces the session."""
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request

from my_harness.i18n import DEFAULT_LANGUAGE, message

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def problem(status: int, code: str, diagnostic: str) -> HTTPException:
    return HTTPException(status, {"code": code, "diagnostic": diagnostic})


def _say(request: Request, key: str) -> str:
    """Own diagnostic in the visual language the application exposes (`app.state.language`), else English."""
    reader = getattr(request.app.state, "language", None) if "app" in request.scope else None
    return message(key, reader() if reader else DEFAULT_LANGUAGE)


def _hostname(value: str | None) -> str | None:
    try:
        if not value:
            return None
        parsed = urlsplit(f"//{value}")
        if parsed.netloc != value or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return None
        return parsed.hostname
    except ValueError:
        return None


def local_request(request: Request, x_my_harness: Annotated[str | None, Header(
        description="Required with value 1 on mutations (CSRF protection).")] = None) -> None:
    """Rejects DNS rebinding (Host), cross-site requests (Origin) and foreign forms (own header)."""
    if _hostname(request.headers.get("host")) not in LOOPBACK_HOSTS:
        raise problem(403, "host_rejected", _say(request, "api.host_rejected"))
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            parsed = urlsplit(origin)
            expected = urlsplit(str(request.base_url))
            valid = (parsed.scheme, parsed.hostname, parsed.port) == (expected.scheme, expected.hostname, expected.port)
            valid = valid and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment
        except ValueError:
            valid = False
        if not valid:
            raise problem(403, "origin_rejected", _say(request, "api.origin_rejected"))
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise problem(403, "origin_rejected", _say(request, "api.cross_site"))
    if request.method in SAFE_METHODS:
        return
    if x_my_harness != "1":
        raise problem(403, "csrf_header_required", _say(request, "api.csrf_header_required"))
