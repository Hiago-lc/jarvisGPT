"""Ground targets in visible Windows controls, then normalized screenshot boxes."""
import math
import platform


def accessible_target(description, width, height):
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
