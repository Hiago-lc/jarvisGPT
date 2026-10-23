"""Read taskbar labels without asking vision to recognize tiny application logos."""
import platform
import re
import threading

_LOCK = threading.Lock()


def label_matches(label, title):
    query = ' '.join(title.casefold().split())
    label = ' '.join(label.casefold().split())
    # Keep application variants distinct (Opera GX is not Opera).
    return bool(query and (label == query or re.match(re.escape(query) + r'(?:\s*[,;:–—-]|\s+\d+\b)', label)))


def _read(title, size):
    from pywinauto import Desktop
    width, height = size
    result = []
    for window in Desktop(backend='uia').windows():
        if window.class_name() not in ('Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
            continue
        for button in window.descendants()[:400]:
            if button.element_info.control_type not in ('Button', 'ListItem', 'TabItem', 'MenuItem'):
                continue
            if not button.is_visible() or not button.is_enabled():
                continue
            label = button.window_text().strip()
            if not label_matches(label, title):
                continue
            rect = button.rectangle()
            if not (0 <= rect.left < rect.right <= width and 0 <= rect.top < rect.bottom <= height):
                continue
            item = {'label': label[:200], 'box_2d': [rect.top * 1000 / height, rect.left * 1000 / width, rect.bottom * 1000 / height, rect.right * 1000 / width]}
            if item not in result:
                result.append(item)
    return result


def taskbar_targets(title, size, timeout=.6):
    if platform.system() != 'Windows':
        return [], 'unsupported'
    if not _LOCK.acquire(blocking=False):
        return [], 'busy'
    finished = threading.Event()
    result = []
    code = ['unavailable']
    def inspect():
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                result.extend(_read(title, size))
                code[0] = 'ok' if result else 'not_found'
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            code[0] = 'unavailable'
        finally:
            _LOCK.release()
            finished.set()
    try:
        threading.Thread(target=inspect, daemon=True, name='taskbar-labels').start()
    except RuntimeError:
        _LOCK.release()
        return [], 'unavailable'
    if not finished.wait(timeout):
        return [], 'timeout'
    return result, code[0]
