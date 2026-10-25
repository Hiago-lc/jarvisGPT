"""Optional, bounded bridge between automation workers and the Qt monitor."""
from contextlib import contextmanager
import threading
from functools import wraps

_handler = None
_local = threading.local()


def install(handler):
    global _handler
    _handler = handler


def notify(action, **payload):
    if _handler is None:
        return True
    event = threading.Event()
    payload['_ack'] = event
    payload['_ok'] = False
    try:
        _handler(action, payload)
        return event.wait(2) and payload['_ok']
    except Exception:
        return False


@contextmanager
def unobstructed():
    depth = getattr(_local, 'depth', 0)
    if depth == 0 and not notify('occlude', hidden=True):
        raise RuntimeError('O painel de acompanhamento não respondeu; nenhuma entrada enviada.')
    _local.depth = depth + 1
    try:
        yield
    finally:
        _local.depth = depth
        if depth == 0:
            notify('occlude', hidden=False)


def without_obstruction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with unobstructed():
            return function(*args, **kwargs)
    return wrapped
