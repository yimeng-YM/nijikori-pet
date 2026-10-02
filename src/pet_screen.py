"""Monitor work areas and safe pet placement in desktop coordinates."""
import ctypes
import sys
from ctypes import wintypes


def monitor_work_areas(root):
    """Enumerate real monitors, including negative origins; exclude taskbars."""
    areas = []
    if sys.platform == "win32":
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                          wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                          wintypes.LPARAM)
        user32 = ctypes.windll.user32
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                              callback_type, wintypes.LPARAM]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL

        @callback_type
        def collect(monitor, dc, rect, data):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                if r.right > r.left and r.bottom > r.top:
                    areas.append((r.left, r.top, r.right, r.bottom))
            return True

        if not user32.EnumDisplayMonitors(None, None, collect, 0):
            areas.clear()
    return areas or [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]


def clamp_to_area(x, y, width, height, area):
    left, top, right, bottom = area
    return (max(left, min(int(x), max(left, right - width))),
            max(top, min(int(y), max(top, bottom - height))))


def nearest_area(x, y, width, height, areas):
    """Choose the monitor requiring the least movement, never a monitor gap."""
    def distance(area):
        nx, ny = clamp_to_area(x, y, width, height, area)
        return (nx - x) ** 2 + (ny - y) ** 2
    return min(areas, key=distance)


def rectangle_on_screens(x, y, width, height, areas):
    """Allow crossing adjoining monitors, but reject holes in the desktop."""
    right, bottom = x + width, y + height
    edges = sorted({x, right} | {edge for area in areas for edge in (area[0], area[2])
                                if x < edge < right})
    for start, end in zip(edges, edges[1:]):
        intervals = sorted((max(y, top), min(bottom, b)) for left, top, r, b in areas
                           if left <= start and r >= end and top < bottom and b > y)
        covered = y
        for top, b in intervals:
            if top > covered:
                return False
            covered = max(covered, b)
        if covered < bottom:
            return False
    return True


def safe_pet_position(x, y, size, areas, *, restrict=True):
    x, y, size = int(x), int(y), max(1, int(size))
    if rectangle_on_screens(x, y, size, size, areas):
        return x, y
    if not restrict:
        # Transparent sprite margins must not count as a reachable pet. Allow
        # partial clipping while a useful portion of its central body is visible.
        margin = size // 4
        required = min(32, max(1, size // 2))
        for left, top, right, bottom in areas:
            visible_w = min(x + size - margin, right) - max(x + margin, left)
            visible_h = min(y + size - margin, bottom) - max(y + margin, top)
            if visible_w >= required and visible_h >= required:
                return x, y
    area = nearest_area(x, y, size, size, areas)
    return clamp_to_area(x, y, size, size, area)
