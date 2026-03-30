import atexit
from typing import List, Tuple, Optional

import win32gui
from mss import mss
from PIL import Image


_sct = mss()


def _cleanup():
    global _sct
    try:
        if _sct is not None:
            _sct.close()
    except Exception:
        pass


atexit.register(_cleanup)


def list_visible_windows() -> List[Tuple[int, str]]:
    windows = []

    def enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return

        windows.append((hwnd, title))

    win32gui.EnumWindows(enum_handler, None)
    return windows


def find_window_by_title_contains(keyword: str) -> List[Tuple[int, str]]:
    keyword = keyword.lower().strip()
    matches = []

    def enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return

        if keyword in title.lower():
            matches.append((hwnd, title))

    win32gui.EnumWindows(enum_handler, None)
    return matches


def _get_client_rect_on_screen(hwnd: int) -> Optional[dict]:
    if not win32gui.IsWindow(hwnd):
        return None

    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        if right <= left or bottom <= top:
            return None

        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (left, top))
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            return None

        return {
            "left": screen_left,
            "top": screen_top,
            "width": width,
            "height": height,
        }
    except Exception:
        return None


def capture_window(hwnd: int):
    global _sct

    if not win32gui.IsWindow(hwnd):
        return None

    if win32gui.IsIconic(hwnd):
        return None

    region = _get_client_rect_on_screen(hwnd)
    if region is None:
        return None

    try:
        shot = _sct.grab(region)
        return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception:
        return None