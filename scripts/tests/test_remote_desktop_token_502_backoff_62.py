"""Token 5xx must not be mistaken for bad credentials or retried twice per loop."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'client/runtime'))
from clientflow_runtime.remote_desktop_net import TransportError
from websockets.exceptions import WebSocketException, InvalidStatusCode

AGENT = ROOT / 'client/runtime/clientflow_runtime/remote_desktop_agent.py'
AUTH = ROOT / 'backend/service1/routers/remote_desktop_auth.py'


def test_token_502_never_enters_same_token_https_fallback():
    tree = ast.parse(AGENT.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RemoteDesktopAgent')
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_channel')
    class StopAfterRetry(BaseException):
        pass
    class StubTransport:
        def websocket_url(self, path):
            assert '/files/ws' in path
            return 'wss://invalid.example/api/remote-desktop-agent/files/ws'
        def websocket_headers(self):
            raise TransportError('backend unavailable', status_code=502)
    class Logs:
        entries = []
        def warning(self, message, **kwargs):
            self.entries.append((message, kwargs))
    class Context:
        async def __aenter__(self):
            raise AssertionError('WebSocket must not open without token')
        async def __aexit__(self, *_args):
            pass
    async def halt(_delay):
        raise StopAfterRetry

    scope = {
        'TransportError': TransportError,
        'WebSocketException': WebSocketException,
        'OSError': OSError,
        'RuntimeError': RuntimeError,
        'json': __import__('json'),
        'websockets': SimpleNamespace(connect=lambda *args, **kwargs: Context()),
        'asyncio': SimpleNamespace(sleep=halt),
        'backoff_seconds': lambda attempt: 1,
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(AGENT), 'exec'), scope)
    class Stub:
        credential = SimpleNamespace(client_id=1)
        transport = StubTransport()
        logger = Logs()
        file_ws = None
        file_sessions = set()
        fallback_calls = 0
        def ssl_context(self):
            return None
        async def _http_channel_once(self, channel):
            self.fallback_calls += 1
    obj = Stub()
    try:
        asyncio.run(scope['_channel'](obj, 'files'))
    except StopAfterRetry:
        pass
    else:
        raise AssertionError('Missing bounded retry')
    assert obj.fallback_calls == 0
    assert obj.logger.entries == [('remote_desktop_token_or_transport_unavailable', {'extra': {'event': 'files', 'status_code': 502}})]


def test_database_token_failure_maps_to_retryable_503_not_401():
    source = AUTH.read_text(encoding='utf-8')
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'remote_desktop_token')
    from sqlalchemy.exc import SQLAlchemyError
    class FakeResponseError(Exception):
        def __init__(self, status_code, detail):
            self.status_code = status_code
            self.detail = detail
    class StubSession:
        def __init__(self, _engine):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
    class Logs:
        entries = []
        def warning(self, message, *args):
            self.entries.append((message, args))
    def broken_response(*_args, **_kwargs):
        raise SQLAlchemyError('database details must not enter logs')
    scope = {
        'router': SimpleNamespace(post=lambda _path: lambda f: f),
        'Session': StubSession,
        'engine': object(),
        'issue_remote_desktop_token_response': broken_response,
        'logger': Logs(),
        'SQLAlchemyError': SQLAlchemyError,
        'HTTPException': FakeResponseError,
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(AUTH), 'exec'), scope)
    try:
        scope['remote_desktop_token'](SimpleNamespace(domain='remote_desktop', client_id=1, credential_id='id', client_secret='secret'))
    except FakeResponseError as exc:
        assert exc.status_code == 503
        assert 'midlertidigt' in exc.detail
    else:
        raise AssertionError('missing 503')
    assert len(scope['logger'].entries) == 1
    assert 'database details' not in repr(scope['logger'].entries)


def test_websocket_handshake_500_uses_https_fallback_instead_of_crashing():
    tree = ast.parse(AGENT.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RemoteDesktopAgent')
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_channel')
    class StopAfterFallback(BaseException):
        pass
    class StubTransport:
        def websocket_url(self, _path):
            return 'wss://invalid.example/ws'
        def websocket_headers(self):
            return {'Authorization': 'Bearer [redacted]'}
    class Context:
        async def __aenter__(self):
            raise InvalidStatusCode(500, {})
        async def __aexit__(self, *_args):
            pass
    class Logs:
        entries = []
        def warning(self, msg, **kwargs):
            self.entries.append(msg)
        def exception(self, *args, **kwargs):
            raise AssertionError('The HTTPS fallback should complete here')
    scope = {
        'TransportError': TransportError,
        'WebSocketException': WebSocketException,
        'OSError': OSError,
        'RuntimeError': RuntimeError,
        'json': __import__('json'),
        'websockets': SimpleNamespace(connect=lambda *a, **kw: Context()),
        'asyncio': SimpleNamespace(sleep=lambda t: None),
        'backoff_seconds': lambda attempt: 1,
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(AGENT), 'exec'), scope)
    class Stub:
        credential = SimpleNamespace(client_id=1)
        transport = StubTransport()
        logger = Logs()
        file_ws = None
        file_sessions = set()
        fallback_calls = 0
        def ssl_context(self):
            return None
        async def _http_channel_once(self, channel):
            self.fallback_calls += 1
            raise StopAfterFallback
    obj = Stub()
    try:
        asyncio.run(scope['_channel'](obj, 'files'))
    except StopAfterFallback:
        pass
    else:
        raise AssertionError('Expected fallback attempt')
    assert obj.fallback_calls == 1
    assert obj.logger.entries == ['remote_desktop_websocket_unavailable_using_https_fallback']
