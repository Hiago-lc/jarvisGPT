"""Stop stalled tasks without imposing a total task length."""
import hashlib


class ProgressWatch:
    def __init__(self, unchanged_limit=10):
        self.last = None
        self.unchanged = 0
        self.limit = unchanged_limit
        self.changed = False

    def stalled(self, frame):
        image = (frame or {}).get('image')
        if image is None:
            self.changed = False
            return False
        small = image.convert('L').resize((64, 36))
        signature = hashlib.sha256(bytes(value // 16 for value in small.tobytes())).digest()
        self.changed = self.last is not None and signature != self.last
        self.unchanged = self.unchanged + 1 if signature == self.last else 0
        self.last = signature
        return self.unchanged >= self.limit
