"""Crop the primary capture without losing its input-coordinate transform."""
import platform


def active_bounds(size):
    width, height = size
    if platform.system() != 'Windows':
        return (0, 0, width, height)
    try:
        import ctypes
        from ctypes import wintypes
        from core.screen_target import foreground_id
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(foreground_id()), ctypes.byref(rect)):
            raise ValueError('Window unavailable')
        # Reject windows wholly outside the supported primary capture.
        if rect.right <= 0 or rect.bottom <= 0 or rect.left >= width or rect.top >= height:
            raise RuntimeError('A janela ativa está fora do monitor principal. Mova-a para o monitor principal.')
        bounds = (max(0, rect.left), max(0, rect.top), min(width, rect.right), min(height, rect.bottom))
        if bounds[2] - bounds[0] >= 100 and bounds[3] - bounds[1] >= 100:
            return bounds
    except RuntimeError:
        raise
    except Exception:
        pass
    return (0, 0, width, height)


def crop(image, bounds, size):
    """Capture pixels and mouse coordinates can use different resolutions."""
    width, height = size
    sx, sy = image.width / width, image.height / height
    left, top, right, bottom = bounds
    return image.crop((round(left * sx), round(top * sy), round(right * sx), round(bottom * sy)))


def locate(result, bounds):
    from core.screen_target import box_center
    left, top, right, bottom = bounds
    point = box_center(result, right - left, bottom - top)
    return (left + point[0], top + point[1]) if point is not None else None
