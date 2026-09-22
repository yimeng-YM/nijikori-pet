#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""window_capture.py — 按窗口句柄截图（可截被遮挡 / 最小化 / 后台窗口）。

提供 capture_window_by_handle(hwnd, save_path) 与 find_window_by_keyword(keyword)。
独立模块，不依赖 main.py 内部函数，便于在桌宠主程序中直接调用。
"""
import os
import sys
import ctypes
import struct
from ctypes import wintypes

__all__ = ["capture_window_by_handle", "capture_window_image", "find_window_by_keyword"]

_PW_CLIENTONLY = 0x1
_PW_RENDERFULLCONTENT = 0x2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


_APP_NAME_MAP = {
    "code.exe": "VS Code",
    "devenv.exe": "Visual Studio",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave 浏览器",
    "wechat.exe": "微信",
    "qq.exe": "QQ",
    "dingtalk.exe": "钉钉",
    "feishu.exe": "飞书",
    "explorer.exe": "文件资源管理器",
    "notepad.exe": "记事本",
    "windowsterminal.exe": "Windows 终端",
    "powershell.exe": "PowerShell",
    "cmd.exe": "命令提示符",
    "idea64.exe": "IntelliJ IDEA",
    "pycharm64.exe": "PyCharm",
    "clion64.exe": "CLion",
    "webstorm64.exe": "WebStorm",
    "cursor.exe": "Cursor",
    "word.exe": "Word",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "spotify.exe": "Spotify",
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "bilibili.exe": "哔哩哔哩",
    "steam.exe": "Steam",
    "obs64.exe": "OBS Studio",
    "potplayer64.exe": "PotPlayer",
    "vlc.exe": "VLC Player",
    "taskmgr.exe": "任务管理器",
    "mspaint.exe": "画图",
    "photoshop.exe": "Photoshop",
}

_EXCLUDED_TITLES = (
    "Program Manager", "Settings", "Microsoft Text Input Application",
    "Task View", "Windows Shell Experience Host", "Default IME",
    "MSCTFIME UI", "PopupHost", "Touch Keyboard",
)


def _get_window_rect(hwnd):
    """Get visual window bounds (excludes Win10/11 drop-shadow padding)."""
    rect = _RECT()
    try:
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if hr != 0:
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    except Exception:
        try:
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        except Exception:
            return {"left": 0, "top": 0, "right": 0, "bottom": 0}
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
    }


def _get_process_name(hwnd):
    """Get executable base name for a window handle."""
    if sys.platform != "win32":
        return ""
    try:
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        h_proc = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
        if not h_proc:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            ctypes.windll.kernel32.CloseHandle(h_proc)
    except Exception:
        pass
    return ""


def _get_app_friendly_name(proc, title):
    p = (proc or "").lower()
    if p in _APP_NAME_MAP:
        return _APP_NAME_MAP[p]
    if p.endswith(".exe"):
        return p[:-4]
    return proc or (title[:12] if title else "未知应用")


def _try_dpi_awareness():
    """Enable per-monitor DPI awareness so GDI captures use physical pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _capture_window_pixels(hwnd, width, height):
    """Off-screen render of a window into a PIL image (occlusion-free)."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        raise RuntimeError("无法获取目标窗口的设备上下文")
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old_bmp = gdi32.SelectObject(mem_dc, bmp)
    try:
        ok = user32.PrintWindow(hwnd, mem_dc, _PW_RENDERFULLCONTENT)
        if not ok:
            ok = user32.PrintWindow(hwnd, mem_dc, _PW_CLIENTONLY)
        if not ok:
            raise RuntimeError("PrintWindow 无法渲染该窗口")

        from PIL import Image as _Image
        header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buf_info = ctypes.create_string_buffer(header, 40)
        buf = ctypes.create_string_buffer(width * height * 4)
        got = gdi32.GetDIBits(hwnd_dc, bmp, 0, height, buf, ctypes.byref(buf_info), 0)
        if not got:
            raise RuntimeError("GetDIBits 读取窗口像素失败")
        return _Image.frombuffer("RGB", (width, height), buf.raw, "raw", "BGRX", 0, 1).copy()
    finally:
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)


def _is_flat_image(image):
    """True for a single-colour render (some GPU-accelerated windows return an
    all-black bitmap from PrintWindow, which is unusable as a screenshot)."""
    try:
        lo, hi = image.convert("L").getextrema()
        return lo == hi
    except Exception:
        return False


def _grab_screen_rect(hwnd):
    """Visible-screen fallback: grab the window's on-screen rectangle."""
    from PIL import ImageGrab
    rect = _get_window_rect(hwnd)
    left, top = rect["left"], rect["top"]
    width = rect["right"] - left
    height = rect["bottom"] - top
    if width <= 0 or height <= 0:
        return None
    try:
        return ImageGrab.grab(bbox=(left, top, left + width, top + height))
    except Exception:
        return None


def _window_capture(hwnd):
    """Return (image, method) for a window.

    PrintWindow renders the window off-screen, so whatever window happens to
    be on top (including the always-on-top desktop pet) is never baked into
    the screenshot.  A visible-screen grab is only a last-resort fallback.
    """
    user32 = ctypes.windll.user32
    # Remember and temporarily restore minimized windows so their full content
    # can be rendered (a minimized window only keeps a small taskbar thumbnail).
    was_minimized = bool(user32.IsIconic(hwnd))
    was_active = bool(user32.GetForegroundWindow() == hwnd)
    restored = False
    if was_minimized:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        restored = True
        try:
            import time as _time
            _time.sleep(0.35)  # give the app a moment to redraw
        except Exception:
            pass
    try:
        rect = _get_window_rect(hwnd)
        width = rect["right"] - rect["left"]
        height = rect["bottom"] - rect["top"]
        if width <= 0 or height <= 0:
            raise RuntimeError("目标窗口没有有效尺寸（可能已关闭或无内容）")
        _try_dpi_awareness()
        image = None
        try:
            image = _capture_window_pixels(hwnd, width, height)
            if not _is_flat_image(image):
                return image, "printwindow"
        except Exception:
            image = None
        fallback = _grab_screen_rect(hwnd)
        if fallback is None:
            if image is not None:
                return image, "printwindow"
            raise RuntimeError("无法截取该窗口（PrintWindow 与屏幕抓取都失败）")
        if image is not None:
            fallback.close()
            return image, "printwindow"
        return fallback, "screen"
    finally:
        if restored and not was_active:
            # Re-minimize the window to leave the desktop as we found it.
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE


def _window_title(hwnd):
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value


def capture_window_image(keyword=None, hwnd=None):
    """Capture a window entirely in memory (no files written).

    Returns (PIL.Image, meta) where meta = {window, width, height, method}.
    keyword is matched like find_window_by_keyword (title / process / app
    name); pass hwnd to target a known handle directly.
    """
    info = None
    if hwnd is None:
        info = find_window_by_keyword(keyword)
        if not info:
            raise ValueError("未找到匹配窗口：「%s」。可先用 get_screen_windows_info 查看窗口名。"
                             % (keyword or ""))
        hwnd = info.get("hwnd")
    hwnd = int(hwnd or 0)
    if not hwnd:
        raise ValueError("无效的窗口句柄 (hwnd=0)")
    if not ctypes.windll.user32.IsWindow(hwnd):
        raise ValueError("目标窗口不存在或已关闭")
    if info is None:
        title = _window_title(hwnd)
        proc = _get_process_name(hwnd)
        rect = _get_window_rect(hwnd)
        info = {"hwnd": hwnd, "title": title, "process": proc,
                "app_name": _get_app_friendly_name(proc, title),
                "x": rect["left"], "y": rect["top"],
                "width": rect["right"] - rect["left"],
                "height": rect["bottom"] - rect["top"]}
    image, method = _window_capture(hwnd)
    meta = {"window": info, "width": image.width, "height": image.height, "method": method}
    return image, meta


def capture_window_by_handle(hwnd, save_path):
    """Legacy helper: save a window's full content to the given path."""
    image, _meta = capture_window_image(hwnd=hwnd)
    try:
        folder = os.path.dirname(save_path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        image.save(save_path)
        return save_path
    finally:
        image.close()


def find_window_by_keyword(keyword):
    """Find a top-level window matching keyword (title / process / app name).

    Unlike main.py's list_desktop_windows, this enumerates windows WITHOUT
    skipping minimized or occluded ones, so background windows can be targeted.
    Returns a dict with 'hwnd', 'title', 'process', 'app_name', or None.
    """
    if not keyword or sys.platform != "win32":
        return None
    kw = keyword.lower().strip()
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    matches = []

    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.strip()
        if not title or title in _EXCLUDED_TITLES:
            return True
        proc = _get_process_name(hwnd)
        app_name = _get_app_friendly_name(proc, title)
        rect = _get_window_rect(hwnd)
        matches.append({
            "hwnd": hwnd,
            "title": title,
            "process": proc,
            "app_name": app_name,
            "x": rect["left"], "y": rect["top"],
            "width": rect["right"] - rect["left"],
            "height": rect["bottom"] - rect["top"],
        })
        return True

    try:
        cb = EnumWindowsProc(enum_cb)
        user32.EnumWindows(cb, 0)
    except Exception:
        pass

    if not matches:
        return None
    for w in matches:
        if w["title"].lower() == kw:
            return w
    for w in matches:
        if w["app_name"].lower() == kw or w["process"].lower() == kw:
            return w
    for w in matches:
        if kw in w["title"].lower():
            return w
    for w in matches:
        if kw in w["app_name"].lower() or w["process"].lower() == kw:
            return w
    return None


if __name__ == "__main__":
    import json
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    if q:
        w = find_window_by_keyword(q)
        print(json.dumps(w, ensure_ascii=False, default=str))
    else:
        print("usage: python window_capture.py <窗口关键词>")
