"""Process-local browser sessions; no credentials in SQLite, URLs or diagnostics."""
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import tempfile
import time
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from my_harness.api.security import problem
from my_harness.i18n import message


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: SecretStr = Field(min_length=1, max_length=128)


class SessionRead(BaseModel):
    expires_in: int


class LocalSessions:
    lifetime = 8 * 60 * 60
    limit = 32

    def __init__(self, language: Callable[[], str] = lambda: 'en'):
        # Visual language of the own diagnostics, read from the global preferences when an error is raised.
        self.language = language
        self.cookie = 'harness_session_' + secrets.token_hex(8)
        self.path: Path | None = None
        self._key = ''
        self._sessions: dict[str, float] = {}
        self.clock = time.monotonic
        self._attempts: list[float] = []

    def start(self):
        # mkdtemp/mode 0700 and exclusive 0600 file: independent of umask, DB,
        # checkout and the caller's cwd. Only the path is announced.
        directory = Path(tempfile.mkdtemp(prefix='harness-session-'))
        os.chmod(directory, 0o700)
        self.path = directory / 'login-key'
        self._key = secrets.token_urlsafe(32)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(self._key)
            # Fixed technical line in English, never localized: maintainer scripts read the path from it (P011-T010).
            print(f'My Harness: access key at {self.path}', flush=True)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        self._key = ''
        self._sessions.clear()
        self._attempts.clear()
        if self.path is not None:
            self.path.unlink(missing_ok=True)
            self.path.parent.rmdir()
            self.path = None

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def remaining(self, token: str | None) -> int:
        if not token or len(token) > 128:
            return 0
        deadline = self._sessions.get(self.digest(token), 0)
        return max(0, int(deadline - self.clock()))

    def require(self, request: Request):
        if not self.remaining(request.cookies.get(self.cookie)):
            raise problem(401, 'session_required', message('session.required', self.language()))

    def login(self, key: str, previous: str | None) -> str:
        now = self.clock()
        self._attempts = [t for t in self._attempts if now - t < 60]
        if len(self._attempts) >= 10:
            raise problem(429, 'login_rate_limited', message('session.rate_limited', self.language()))
        self._attempts.append(now)
        if not self._key or not key.isascii() or not hmac.compare_digest(key, self._key):
            raise problem(401, 'session_required', message('session.invalid_key', self.language()))
        self._sessions = {k: v for k, v in self._sessions.items() if v > now}
        self.revoke(previous)
        if len(self._sessions) >= self.limit:
            raise problem(429, 'session_limit', message('session.limit', self.language()))
        token = secrets.token_urlsafe(32)
        self._sessions[self.digest(token)] = now + self.lifetime
        return token

    def revoke(self, token: str | None):
        if token:
            self._sessions.pop(self.digest(token), None)


def session_router(sessions: LocalSessions) -> APIRouter:
    router = APIRouter(prefix='/api/session')

    @router.post('', response_model=SessionRead, operation_id='start_session',
                 openapi_extra={'requestBody': {'required': True, 'content': {
                     'application/json': {'schema': SessionCreate.model_json_schema()}}}})
    async def login(request: Request):
        # Read a bounded body ourselves: Pydantic validation errors must never
        # echo a submitted credential (including malformed/oversized inputs).
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 256:
                raise problem(400, 'invalid_login', message('session.invalid_login', sessions.language()))
            body.extend(chunk)
        try:
            data = SessionCreate.model_validate_json(bytes(body))
        except ValidationError:
            raise problem(400, 'invalid_login', message('session.invalid_login', sessions.language())) from None
        token = sessions.login(data.key.get_secret_value(), request.cookies.get(sessions.cookie))
        response = JSONResponse({'expires_in': sessions.lifetime})
        response.set_cookie(sessions.cookie, token, max_age=sessions.lifetime,
                            httponly=True, samesite='strict', path='/api')
        return response

    @router.get('', response_model=SessionRead, operation_id='read_session')
    async def status(request: Request):
        sessions.require(request)
        return SessionRead(expires_in=sessions.remaining(request.cookies.get(sessions.cookie)))

    @router.delete('', status_code=204, operation_id='close_session')
    async def logout(request: Request):
        sessions.revoke(request.cookies.get(sessions.cookie))
        response = Response(status_code=204)
        response.delete_cookie(sessions.cookie, path='/api', httponly=True, samesite='strict')
        return response

    return router
