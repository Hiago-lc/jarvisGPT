"""Optional, bounded bridge between automation workers and the Qt monitor."""
from contextlib import contextmanager
import threading
from functools import wraps

_handler = None
_view_lock = threading.RLock()
_view_users = 0


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
    # Streaming capture and the input executor can overlap on different threads.
    # Show the panel only after ALL active users have finished, not after the
    # first thread exits its context.
    global _view_users
    with _view_lock:
        if _view_users == 0 and not notify('occlude', hidden=True):
            raise RuntimeError('O painel de acompanhamento não respondeu; nenhuma entrada enviada.')
        _view_users += 1
    try:
        yield
    finally:
        with _view_lock:
            _view_users -= 1
            if _view_users == 0:
                notify('occlude', hidden=False)


def without_obstruction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with unobstructed():
            return function(*args, **kwargs)
    return wrapped
