"""Existing feature tests authenticate through the real session exchange."""
from fastapi.testclient import TestClient as AnonymousClient


class TestClient(AnonymousClient):
    __test__ = False

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('base_url', 'http://127.0.0.1')
        super().__init__(*args, **kwargs)

    def __enter__(self):
        client = super().__enter__()
        if self.base_url.host in {'127.0.0.1', 'localhost', '::1'}:
            response = self.post('/api/session', json={'key': self.app.state.sessions.path.read_text()},
                                 headers={'X-My-Harness': '1'})
            assert response.status_code == 200, response.text
        return client
