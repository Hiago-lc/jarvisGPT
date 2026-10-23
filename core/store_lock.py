"""Reentrant thread and process lock for the JSON memory store."""
import os
import threading


class StoreLock:
    def __init__(self, path):
        self.path = path
        self.thread_lock = threading.RLock()
        self.local = threading.local()

    def __enter__(self):
        self.thread_lock.acquire()
        depth = getattr(self.local, 'depth', 0)
        if depth:
            self.local.depth += 1
            return self
        try:
            path = self.path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.local.file = open(path, 'a+b')
            if os.name == 'nt':
                import msvcrt
                self.local.file.seek(0)
                if not self.local.file.read(1):
                    self.local.file.write(b'0')
                    self.local.file.flush()
                self.local.file.seek(0)
                msvcrt.locking(self.local.file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self.local.file.fileno(), fcntl.LOCK_EX)
            self.local.depth = 1
            return self
        except Exception:
            if getattr(self.local, 'file', None):
                self.local.file.close()
            self.thread_lock.release()
            raise

    def __exit__(self, *args):
        self.local.depth -= 1
        try:
            if not self.local.depth:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        self.local.file.seek(0)
                        msvcrt.locking(self.local.file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.local.file.fileno(), fcntl.LOCK_UN)
                finally:
                    self.local.file.close()
        finally:
            self.thread_lock.release()
