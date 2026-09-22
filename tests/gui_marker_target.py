# -*- coding: utf-8 -*-
"""GUI target used by the computer-use alignment regression test.

Hosts a window with a known grid so the test can verify that image-pixel
coordinates from a snapshot map onto the right place on screen.
Set CU_DPI_AWARE=0 to simulate a legacy (DPI-unaware) application.
"""
import ctypes
import json
import os
import sys

import tkinter as tk

user32 = ctypes.windll.user32
if os.environ.get("CU_DPI_AWARE", "1") == "1":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

WIDTH, HEIGHT = 520, 320
# Client-coordinate markers the test looks for inside the snapshot image.
MARK_X, MARK_Y = 200, 150

hwnd_file, state_file = sys.argv[1], sys.argv[2]
# Optional third argument: record every key the window receives, so the test can
# prove that type/key really reached this window (newlines included).
keys_file = sys.argv[3] if len(sys.argv) > 3 else ""
root = tk.Tk()
root.title("NijiCU-Marker")
root.geometry("%dx%d+180+180" % (WIDTH, HEIGHT))
root.attributes("-topmost", True)
canvas = tk.Canvas(root, bg="white", highlightthickness=0, bd=0)
canvas.pack(fill="both", expand=True)
canvas.create_line(MARK_X, 0, MARK_X, HEIGHT, fill="#ff0000", width=1)
canvas.create_line(0, MARK_Y, WIDTH, MARK_Y, fill="#ff0000", width=1)
clicks = []
keys = []


def on_key(event):
    keys.append({"keysym": event.keysym, "char": event.char, "state": event.state})
    if keys_file:
        open(keys_file, "w", encoding="utf-8").write(json.dumps(keys, ensure_ascii=False))


def on_click(event):
    clicks.append({"x": event.x, "y": event.y,
                   "x_root": event.x_root, "y_root": event.y_root})
    open(state_file, "w", encoding="utf-8").write(json.dumps(clicks))


canvas.bind("<Button-1>", on_click)
root.bind("<Key>", on_key)
canvas.focus_set()
root.update()


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


hwnd = user32.GetAncestor(int(root.winfo_id()), 2) or int(root.winfo_id())
rect = _RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
origin = _POINT(0, 0)
user32.ClientToScreen(hwnd, ctypes.byref(origin))
# A DPI-unaware process sees virtualized (logical) coordinates.  Report both
# the rect this process sees and the client origin it reports, so the test can
# convert them to physical screen coordinates via the scale factor.
open(hwnd_file, "w", encoding="utf-8").write(json.dumps({
    "hwnd": hwnd,
    "window_rect": [rect.left, rect.top, rect.right, rect.bottom],
    "client_origin": [origin.x, origin.y],
    "mark": [MARK_X, MARK_Y],
}))
root.after(200, lambda: (user32.SetForegroundWindow(hwnd), root.focus_force()))
root.after(120000, root.destroy)
root.mainloop()
