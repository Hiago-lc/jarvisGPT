"""Ground targets in visible Windows controls, then normalized screenshot boxes."""
import math
import platform
import threading


def _accessible_target(description, width, height):
    if platform.system() != 'Windows':
        return None
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend='uia')
        window = desktop.window(handle=foreground_id())
        query = description.strip().casefold()
        for prefix in ('botão ', 'botao ', 'campo ', 'button ', 'field '):
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break
        matches = []
        for control in window.descendants()[:600]:
            if not control.is_visible() or not control.is_enabled():
                continue
            if control.window_text().strip().casefold() != query:
                continue
            box = control.rectangle()
            x, y = (box.left + box.right) // 2, (box.top + box.bottom) // 2
            if box.width() > 0 and box.height() > 0 and 0 <= x < width and 0 <= y < height:
                matches.append((x, y))
        return matches[0] if len(matches) == 1 else None
    except Exception:
        return None


_PROBE_LOCK = threading.Lock()


def accessible_target(description, width, height):
    """A hung Windows accessibility provider must not freeze the whole task."""
    if platform.system() != 'Windows' or not _PROBE_LOCK.acquire(blocking=False):
        return None
    finished = threading.Event()
    result = []
    def inspect():
        try:
            # COM must be initialized in the worker that uses UI Automation.
            import pythoncom
            pythoncom.CoInitialize()
            try:
                result.append(_accessible_target(description, width, height))
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            result.append(None)
        finally:
            _PROBE_LOCK.release()
            finished.set()
    try:
        threading.Thread(target=inspect, daemon=True, name='uia-target-probe').start()
    except RuntimeError:
        _PROBE_LOCK.release()
        return None
    if finished.wait(.35) and result:
        return result[0]
    return None


def box_center(result, width, height):
    """Gemini box_2d is [ymin,xmin,ymax,xmax] on a 0..1000 scale."""
    if not isinstance(result, dict) or result.get('found') is not True:
        return None
    confidence = result.get('confidence')
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not .85 <= confidence <= 1:
        return None
    box = result.get('box_2d')
    if not isinstance(box, list) or len(box) != 4:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
        return None
    top, left, bottom, right = box
    if not (0 <= top < bottom <= 1000 and 0 <= left < right <= 1000):
        return None
    return min(width - 1, int((left + right) * width / 2000)), min(height - 1, int((top + bottom) * height / 2000))


def foreground_id():
    if platform.system() != 'Windows':
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return user32.GetForegroundWindow()
    except Exception:
        return None


def target_unchanged(before, after, box):
    """Reject visual fallback when its target region changed during inference."""
    from PIL import ImageChops
    if not isinstance(box, list) or len(box) != 4:
        return False
    top, left, bottom, right = box
    w, h = before.size
    area = (int(left * w / 1000), int(top * h / 1000),
            max(int(right * w / 1000), int(left * w / 1000) + 1),
            max(int(bottom * h / 1000), int(top * h / 1000) + 1))
    after = after.convert('RGB').resize(before.size)
    diff = ImageChops.difference(before.convert('RGB').crop(area), after.crop(area)).convert('L')
    histogram = diff.histogram()
    changed = sum(histogram[31:])
    return changed / max(1, sum(histogram)) < .10
