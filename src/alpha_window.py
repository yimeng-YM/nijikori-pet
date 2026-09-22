import ctypes, sys
from ctypes import wintypes, POINTER
from PIL import Image, ImageChops

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x02
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTTRANSPARENT = -1
GWLP_WNDPROC = -4
GWL_EXSTYLE = -20
GA_ROOT = 2

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]
class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

def _set_argtypes():
    user32.GetDC.argtypes = [wintypes.HWND]; user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]; user32.ReleaseDC.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, POINTER(RECT)]; user32.GetWindowRect.restype = ctypes.c_int
    user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, POINTER(POINT), POINTER(SIZE), wintypes.HDC, POINTER(POINT), ctypes.c_uint32, POINTER(BLENDFUNCTION), ctypes.c_uint32]; user32.UpdateLayeredWindow.restype = ctypes.c_int
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]; user32.SetWindowPos.restype = ctypes.c_int
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]; user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]; user32.GetAncestor.restype = wintypes.HWND
    if hasattr(user32, "GetWindowLongPtrW"):
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]; user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]; user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    else:
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]; user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]; user32.SetWindowLongW.restype = ctypes.c_long
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]; gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]; gdi32.DeleteDC.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]; gdi32.DeleteObject.restype = ctypes.c_int
    gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]; gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, POINTER(BITMAPINFO), ctypes.c_uint, POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]; gdi32.CreateDIBSection.restype = ctypes.c_void_p
_set_argtypes()

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)

def toplevel_hwnd(tk_widget):
    """Return the real top-level Win32 HWND for a Tk widget (winfo_id gives the
    inner widget handle; the toplevel is what we make layered)."""
    h = int(tk_widget.winfo_id())
    try:
        r = user32.GetAncestor(h, GA_ROOT)
        if r:
            return r
    except Exception:
        pass
    return h


def keep_topmost(tk_widget):
    """Promote the mapped wrapper without activating it or disturbing geometry."""
    hwnd = toplevel_hwnd(tk_widget)
    if not user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0013):
        # HWND_TOPMOST; SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        raise ctypes.WinError()


def _get_long(hwnd, idx):
    try:
        return user32.GetWindowLongPtrW(hwnd, idx)
    except Exception:
        return user32.GetWindowLongW(hwnd, idx)
def _set_long(hwnd, idx, val):
    try:
        user32.SetWindowLongPtrW(hwnd, idx, val)
    except Exception:
        user32.SetWindowLongW(hwnd, idx, val)

class AlphaWindow:
    """Per-pixel-alpha layered window (Win32 UpdateLayeredWindow) driven by a
    PIL RGBA frame.  Keeps the window's own input pipeline (mouse/click) working;
    the content is fully replaced by the frame so no colour-key / halo is used."""
    def __init__(self, hwnd):
        self.hwnd = int(hwnd)
        self._memdc = None
        self._hbmp = None
        self._oldbmp = None
        self._bits = None
        self._size = (0, 0)
        self._frame = None          # current RGBA frame (for hit-testing)
        self._hit = None
        self._old_wndproc = None
        self._ensure_style()
        self._alloc(1, 1)

    def _ensure_style(self):
        try:
            _set_long(self.hwnd, GWL_EXSTYLE, _get_long(self.hwnd, GWL_EXSTYLE) | WS_EX_LAYERED)
        except Exception:
            pass

    def _alloc(self, w, h):
        w = max(1, int(w)); h = max(1, int(h))
        if (w, h) == self._size and self._hbmp is not None:
            return
        if self._hbmp is not None:
            if self._memdc is not None and self._oldbmp is not None:
                gdi32.SelectObject(self._memdc, self._oldbmp)
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        if not self._memdc:
            self._memdc = gdi32.CreateCompatibleDC(None)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(self._memdc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not self._hbmp:
            raise OSError("CreateDIBSection failed")
        self._bits = bits.value
        self._oldbmp = gdi32.SelectObject(self._memdc, self._hbmp)
        self._size = (w, h)

    def present(self, frame):
        frame = frame.convert("RGBA")
        self._frame = frame
        w, h = frame.size
        self._alloc(w, h)
        r, g, b, a = frame.split()
        rp = ImageChops.multiply(r, a); gp = ImageChops.multiply(g, a); bp = ImageChops.multiply(b, a)
        bgra = Image.merge("RGBA", (bp, gp, rp, a))
        data = bgra.tobytes()
        ctypes.memmove(self._bits, data, len(data))
        rect = RECT(); user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        pptDst = POINT(rect.left, rect.top)
        psize = SIZE(w, h)
        ptSrc = POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
        hdcDst = user32.GetDC(None)
        try:
            if not user32.UpdateLayeredWindow(self.hwnd, hdcDst, ctypes.byref(pptDst), ctypes.byref(psize),
                                              self._memdc, ctypes.byref(ptSrc), 0, ctypes.byref(blend), ULW_ALPHA):
                raise ctypes.WinError()
        finally:
            user32.ReleaseDC(None, hdcDst)

    def _alpha_at_screen(self, sx, sy):
        try:
            frame = self._frame
            if frame is None:
                return 0
            rect = RECT(); user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            lx = int(sx - rect.left); ly = int(sy - rect.top)
            w, h = frame.size
            if lx < 0 or ly < 0 or lx >= w or ly >= h:
                return 0
            return frame.getpixel((lx, ly))[3]
        except Exception:
            return 0

    def install_click_through(self, alpha_thresh=8):
        """Subclass WM_NCHITTEST so pixels with alpha < thresh are click-through."""
        try:
            old_proc = _get_long(self.hwnd, GWLP_WNDPROC)
            thresh = alpha_thresh
            aw = self
            @WNDPROC
            def _proc(h, msg, wp, lp):
                if msg == WM_NCHITTEST:
                    try:
                        sx = lp & 0xFFFF
                        sy = (lp >> 16) & 0xFFFF
                        if sx & 0x8000:
                            sx -= 0x10000
                        if sy & 0x8000:
                            sy -= 0x10000
                        if aw._alpha_at_screen(sx, sy) < thresh:
                            return HTTRANSPARENT
                    except Exception:
                        pass
                return user32.CallWindowProcW(old_proc, h, msg, wp, lp)
            self._hit = _proc
            self._old_wndproc = old_proc
            _set_long(self.hwnd, GWLP_WNDPROC, ctypes.cast(_proc, ctypes.c_void_p).value)
            return old_proc
        except Exception:
            return None

    def close(self):
        try:
            if self._hit is not None:
                # restore original proc
                _set_long(self.hwnd, GWLP_WNDPROC, self._old_wndproc)
        except Exception:
            pass
        try:
            if self._oldbmp is not None:
                gdi32.SelectObject(self._memdc, self._oldbmp)
            if self._hbmp is not None:
                gdi32.DeleteObject(self._hbmp)
            if self._memdc is not None:
                gdi32.DeleteDC(self._memdc)
        except Exception:
            pass
        self._memdc = self._hbmp = self._oldbmp = None
