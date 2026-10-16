"""桌宠 UI 工具箱 —— 抗锯齿圆角绘制、缓动动画与统一调色板。

tkinter Canvas 的 ``create_polygon(smooth=True)`` 没有抗锯齿，圆角边缘发毛。
这里改为 PIL 4 倍超采样绘制后缩小成带 alpha 的 PhotoImage（Canvas 会与背景
混合），同尺寸 / 同颜色的图只画一次。

控件构造参数与旧版保持一致：插件通过 ``ui_kit`` 拿到的 PastelButton /
ToggleSwitch 等无需改动。本模块不 import main，避免循环依赖。
"""

import sys
import ctypes
from collections import OrderedDict

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

PAL = {
    "bg":          "#f8f9fe",  # dialog background (soft white-lavender)
    "panel":       "#f6f8fe",  # panels / footer card
    "panel2":      "#eef2fc",
    "interior":    "#fbfcfe",  # solid color matching bubble inner area
    "ink":         "#3f4a6b",  # primary text (dark slate-indigo, ~8:1 on bg)
    "ink_soft":    "#5a6490",  # secondary text
    "ink_dim":     "#8a93ad",  # tertiary text
    "peri":        "#6a74b8",  # periwinkle accent (titles)
    "peri_deep":   "#55619f",
    "line":        "#c9d2f0",  # borders
    "line_soft":   "#dee4f6",
    "user":        "#2f79c3",  # user name (readable blue)
    "bot":         "#2e9e82",  # pet name (readable teal)
    "sys":         "#8a93ad",
    "tool":        "#7a5fd0",
    "cyan":        "#58bfe0",
    "gold":        "#e8b64a",
    "btn_primary":       "#aedcf2",
    "btn_primary_fg":    "#2f5671",
    "btn_primary_hover": "#9cd2ec",
    "btn_soft":          "#e7ecfa",
    "btn_soft_fg":       "#5a64a0",
    "btn_soft_hover":    "#d9e2f7",
    "btn_danger":        "#f3cdd9",
    "btn_danger_fg":     "#8f3b5c",
    "btn_danger_hover":  "#ecc0cf",
    "btn_ghost":         "#eef1f8",
    "btn_ghost_fg":      "#5a6490",
    "btn_ghost_hover":   "#e2e7f6",
    "menu_active":       "#e4eafa",
    "scroll_trough":     "#eef2fc",
    "scroll_thumb":      "#c3cdef",
    # --- Control-center tokens ---------------------------------------------
    "card":              "#ffffff",  # card surface (plugins rely on pure white)
    "accent":            "#7b87d9",  # switches / slider / focus ring
    "accent_deep":       "#55619f",
    "accent_soft":       "#e8ebfb",

    "nav_hover":         "#e2e8f8",
    "track_off":         "#d3daf0",
    "hero_a":            "#c9d3fb",  # overview hero gradient
    "hero_b":            "#c4ecf6",
    # --- Conversation-history window (see pet_chat_history.py) -------------
    # Bubble / card surfaces are tinted per speaker; every text color below
    # holds >= 4.5:1 contrast against the surface it sits on.
    "hist_surface":      "#ffffff",  # transcript canvas
    "hist_user_bubble":  "#dfeafc",
    "hist_user_text":    "#22405f",
    "hist_pet_bubble":   "#e4f6ef",
    "hist_pet_text":     "#1f4a3d",
    "hist_tool_card":    "#f2eefc",
    "hist_tool_text":    "#5b3fa8",
    "hist_tool_line":    "#6b5aa8",
    "hist_sys_pill":     "#eef1f8",
    "hist_sys_text":     "#5f6884",
    "hist_avatar_pet":   "#5cc4a5",
    "hist_avatar_user":  "#7aa9df",
    # --- Status badges & aliases -------------------------------------------
    "text":              "#3f4a6b",  # alias for ink (plugin compatibility)
    "badge_ok_bg":       "#e3f6ed",
    "badge_ok_fg":       "#1f6e4d",
    "badge_warn_bg":     "#fdf2dc",
    "badge_warn_fg":     "#8a5a14",
    "badge_err_bg":      "#fae4eb",
    "badge_err_fg":      "#963252",
    "badge_info_bg":     "#e8ebfb",
    "badge_info_fg":     "#55619f",
    "badge_muted_bg":    "#eef1f8",
    "badge_muted_fg":    "#6d7694",
}

_SS = 4                 # supersampling factor
_CACHE = OrderedDict()  # key -> PhotoImage
_CACHE_MAX = 800
_RESAMPLE = Image.Resampling.LANCZOS


# ---------------------------------------------------------------------------
# color & easing helpers
# ---------------------------------------------------------------------------
def to_rgb(color, widget=None):
    """'#rrggbb'（或任意 Tk 颜色名，需传 widget）→ (r, g, b)。"""
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    if widget is not None:
        return tuple(v >> 8 for v in widget.winfo_rgb(color))
    return (255, 255, 255)


def lerp_color(c1, c2, t):
    """Linear-interpolate two hex colors (t in 0..1) for smooth transitions."""
    t = max(0.0, min(1.0, t))
    a, b = to_rgb(c1), to_rgb(c2)
    return "#{:02x}{:02x}{:02x}".format(*(int(round(a[i] + (b[i] - a[i]) * t))
                                         for i in range(3)))


def ease_out(t):
    return 1.0 - (1.0 - t) ** 3


def _cached(key, render):
    img = _CACHE.get(key)
    if img is None:
        img = ImageTk.PhotoImage(render())
        _CACHE[key] = img
        if len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)   # widgets hold their own refs
    else:
        _CACHE.move_to_end(key)
    return img


# ---------------------------------------------------------------------------
# anti-aliased image factories
# ---------------------------------------------------------------------------
def _rr(w, h, r, fill, outline=None, width=1):
    W, H = max(1, w) * _SS, max(1, h) * _SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rad = int(max(0, min(r * _SS, (min(W, H) - 1) // 2)))
    ImageDraw.Draw(im).rounded_rectangle(
        (0, 0, W - 1, H - 1), radius=rad, fill=to_rgb(fill) + (255,),
        outline=(to_rgb(outline) + (255,)) if outline else None,
        width=int(width * _SS) if outline else 0)
    return im.resize((max(1, w), max(1, h)), _RESAMPLE)


def round_rect_photo(w, h, r, fill, outline=None, width=1):
    w, h = int(w), int(h)
    return _cached(("rr", w, h, int(r), fill, outline, width),
                   lambda: _rr(w, h, r, fill, outline, width))


def _knob(im, cx, cy, r, ring=None, ring_w=0):
    """Draw a white knob with a soft drop shadow onto a supersampled image."""
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((cx - r, cy - r + _SS, cx + r, cy + r + _SS),
                               fill=(45, 55, 100, 70))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(_SS * 1.3)))
    ImageDraw.Draw(im).ellipse(
        (cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255),
        outline=(to_rgb(ring) + (255,)) if ring else None,
        width=int(ring_w * _SS) if ring else 0)
    return im


def toggle_photo(w, h, t, on_c, off_c):
    w, h = int(w), int(h)
    q = round(max(0.0, min(1.0, t)) * 12) / 12.0

    def render():
        W, H = w * _SS, h * _SS
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle(
            (0, 0, W - 1, H - 1), radius=(H - 1) // 2,
            fill=to_rgb(lerp_color(off_c, on_c, q)) + (255,))
        pad = max(2.0, h * 0.13) * _SS
        r = H / 2.0 - pad
        x0, x1 = pad + r, W - pad - r
        im = _knob(im, x0 + (x1 - x0) * q, H / 2.0, r)
        return im.resize((w, h), _RESAMPLE)

    return _cached(("tg", w, h, q, on_c, off_c), render)


def knob_photo(d, ring, ring_w=2):
    d = int(d)

    def render():
        size = (d + 6) * _SS
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        r = d * _SS / 2.0
        im = _knob(im, size / 2.0, size / 2.0 - _SS, r, ring=ring, ring_w=ring_w)
        return im.resize((d + 6, d + 6), _RESAMPLE)

    return _cached(("knob", d, ring, ring_w), render)


def corner_photo(r, outer, fill, border, corner, widget=None):
    """r×r 圆角补丁：外侧填 outer，内侧 fill，带 1px border 弧线。"""
    r = int(r)
    key = ("corner", r, outer, fill, border, corner)

    def render():
        D = 2 * r * _SS
        im = Image.new("RGB", (D, D), to_rgb(outer, widget))
        ImageDraw.Draw(im).ellipse(
            (0, 0, D - 1, D - 1), fill=to_rgb(fill, widget),
            outline=to_rgb(border or fill, widget), width=_SS)
        im = im.resize((2 * r, 2 * r), _RESAMPLE)
        box = {"nw": (0, 0, r, r), "ne": (r, 0, 2 * r, r),
               "sw": (0, r, r, 2 * r), "se": (r, r, 2 * r, 2 * r)}[corner]
        return im.crop(box)

    return _cached(key, render)


def gradient_photo(w, h, r, c1, c2):
    """Rounded horizontal pastel gradient with two soft light orbs (hero banner)."""
    w, h = int(w), int(h)

    def render():
        ss = 2
        W, H = w * ss, h * ss
        mask = Image.linear_gradient("L").rotate(90).resize((W, H))
        im = Image.composite(Image.new("RGBA", (W, H), to_rgb(c1) + (255,)),
                             Image.new("RGBA", (W, H), to_rgb(c2) + (255,)), mask)
        orbs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(orbs)
        d.ellipse((W - H * 1.1, -H * 0.55, W + H * 0.25, H * 0.8), fill=(255, 255, 255, 60))
        d.ellipse((W * 0.42, H * 0.55, W * 0.42 + H * 0.9, H * 1.45), fill=(255, 255, 255, 45))
        im = Image.alpha_composite(im, orbs.filter(ImageFilter.GaussianBlur(ss * 2)))
        alpha = Image.new("L", (W, H), 0)
        ImageDraw.Draw(alpha).rounded_rectangle((0, 0, W - 1, H - 1), radius=r * ss, fill=255)
        im.putalpha(alpha)
        return im.resize((w, h), _RESAMPLE)

    return _cached(("grad", w, h, r, c1, c2), render)


# ---------------------------------------------------------------------------
# animation mixin
# ---------------------------------------------------------------------------
class _Anim:
    """Per-widget eased animations on named slots (16 ms frames)."""

    def _animate(self, ms, frame, slot="main", done=None):
        self._stop_anim(slot)
        steps = max(1, int(ms / 16))
        state = {"i": 0}

        def tick():
            state["i"] += 1
            try:
                frame(ease_out(state["i"] / steps))
            except tk.TclError:        # widget destroyed mid-animation
                self._jobs().pop(slot, None)
                return
            if state["i"] < steps:
                self._jobs()[slot] = self.after(16, tick)
            else:
                self._jobs().pop(slot, None)
                if done:
                    done()

        tick()

    def _jobs(self):
        if not hasattr(self, "_anim_jobs"):
            self._anim_jobs = {}
        return self._anim_jobs

    def _stop_anim(self, slot="main"):
        job = self._jobs().pop(slot, None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# widgets
# ---------------------------------------------------------------------------
class PastelButton(tk.Canvas, _Anim):
    """Anti-aliased rounded pastel button with eased hover / press feedback."""

    def __init__(self, master, text, command=None, parent_bg=PAL["panel"],
                 fill=PAL["btn_primary"], fg=PAL["btn_primary_fg"],
                 hover=None, font=None, padx=16, pady=7, radius=14):
        self._fill = fill
        self._hover = hover or fill
        self._fg = fg
        self._cmd = command
        self._r = radius
        self._t = 0.0
        self._pressed = False
        self._disabled = False
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._padx = int(padx)
        self._pady = int(pady)
        self._bw = self._font.measure(str(text)) + self._padx * 2
        self._bh = self._font.metrics("linespace") + self._pady * 2
        super().__init__(master, width=self._bw, height=self._bh, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._text_item = self.create_text(self._bw // 2, self._bh // 2, text=text,
                                           font=self._font, fill=fg)
        self._paint_t(0.0)
        self.bind("<Enter>", lambda e: self._fade(1.0) if not self._disabled else None)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def set_text(self, text):
        text = str(text)
        self._bw = self._font.measure(text) + self._padx * 2
        super().configure(width=self._bw)
        self.coords(self._text_item, self._bw // 2, self._bh // 2)
        self.itemconfigure(self._text_item, text=text)
        self._paint_t(self._t)

    def set_enabled(self, enabled):
        self._disabled = not bool(enabled)
        super().configure(cursor="arrow" if self._disabled else "hand2")
        self.itemconfigure(self._text_item, fill=PAL["ink_dim"] if self._disabled else self._fg)
        self._paint_t(0.0 if self._disabled else self._t)

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        text = kw.pop("text", None)
        state = kw.pop("state", None)
        cmd = kw.pop("command", None)
        if cmd is not None:
            self._cmd = cmd
        if text is not None:
            self.set_text(text)
        if state is not None:
            self.set_enabled(str(state).lower() != "disabled")
        if kw:
            return super().configure(**kw)
        return None

    config = configure

    def _paint_t(self, t):
        self._t = t
        if self._disabled:
            col = PAL["btn_ghost"]
        else:
            col = lerp_color(self._fill, self._hover, round(t * 6) / 6.0)
            if self._pressed:
                col = lerp_color(col, "#3f4a6b", 0.08)
        self._img = round_rect_photo(self._bw, self._bh, min(self._r, self._bh // 2), col)
        self.itemconfigure(self._bg_item, image=self._img)

    def _fade(self, target):
        if self._disabled:
            return
        start = self._t
        self._animate(110, lambda e: self._paint_t(start + (target - start) * e))

    def _leave(self, _e=None):
        self._pressed = False
        if not self._disabled:
            self._fade(0.0)

    def _press(self, _e=None):
        if self._disabled:
            return
        self._pressed = True
        self._paint_t(self._t)

    def _release(self, event):
        if self._disabled:
            return
        inside = 0 <= event.x < self._bw and 0 <= event.y < self._bh
        fire = self._pressed and inside
        self._pressed = False
        self._paint_t(self._t)
        if fire and self._cmd:
            self._cmd()



class ToggleSwitch(tk.Canvas, _Anim):
    """Anti-aliased pill toggle switch with an eased knob slide + color fade.

    Click flips the state, then invokes command(new_state: bool).
    """

    def __init__(self, master, command=None, initial=False,
                 on_color=PAL["accent"], off_color=PAL["track_off"], bg="#ffffff",
                 width=44, height=24):
        self._on = bool(initial)
        self._t = 1.0 if self._on else 0.0
        self._cmd = command
        self._on_c = on_color
        self._off_c = off_color
        self._cv_w = int(width)
        self._cv_h = int(height)
        super().__init__(master, width=self._cv_w, height=self._cv_h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._item = self.create_image(0, 0, anchor="nw")
        self.bind("<Button-1>", self._on_click)
        self._paint()

    def is_on(self):
        return self._on

    def set_state(self, value, animate=True):
        value = bool(value)
        target = 1.0 if value else 0.0
        self._on = value
        if not animate or abs(self._t - target) < 1e-6:
            self._stop_anim()
            self._t = target
            self._paint()
            return
        start = self._t

        def frame(e):
            self._t = start + (target - start) * e
            self._paint()

        self._animate(170, frame)

    def _on_click(self, _event=None):
        self.set_state(not self._on)
        if self._cmd:
            try:
                self._cmd(self._on)
            except Exception as e:
                print(f"[toggle] command failed: {e}")

    def _paint(self):
        self._img = toggle_photo(self._cv_w, self._cv_h, self._t, self._on_c, self._off_c)
        self.itemconfigure(self._item, image=self._img)


class SideNavItem(tk.Canvas, _Anim):
    """Sidebar navigation pill: icon glyph + text, hover fade, and a
    Fluent-style accent indicator that grows in when selected."""

    def __init__(self, master, icon, text, command, width=196, height=40,
                 bg=PAL["panel2"], font=None, icon_font=None):
        self._text = text
        self._icon = icon or ""
        self._icon_font = icon_font
        self._cmd = command
        self._cv_w = int(width)
        self._cv_h = int(height)
        self._bg = bg
        self._sel = False
        self._hover_t = 0.0
        self._ind_t = 0.0
        self._font = font or tkfont.nametofont("TkDefaultFont")
        super().__init__(master, width=self._cv_w, height=self._cv_h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", lambda e: self._cmd())
        self.bind("<Enter>", lambda e: self._fade_hover(1.0))
        self.bind("<Leave>", lambda e: self._fade_hover(0.0))
        self._paint()

    def set_selected(self, selected):
        selected = bool(selected)
        if selected == self._sel:
            return
        self._sel = selected
        if selected:
            self._ind_t = 0.0

            def frame(e):
                self._ind_t = e
                self._paint()

            self._animate(220, frame, slot="ind")
        else:
            self._stop_anim("ind")
            self._ind_t = 0.0
            self._paint()

    def _fade_hover(self, target):
        start = self._hover_t

        def frame(e):
            self._hover_t = start + (target - start) * e
            self._paint()

        self._animate(120, frame, slot="hover")

    def _paint(self):
        self.delete("all")
        w, h = self._cv_w, self._cv_h
        s = h / 40.0
        self._imgs = []
        if self._sel:
            img = round_rect_photo(w - 4, h - 4, 10 * s, "#ffffff", PAL["line_soft"])
            self._imgs.append(img)
            self.create_image(2, 2, image=img, anchor="nw")
            bar_h = int(round(18 * s * self._ind_t))
            if bar_h >= 2:
                bar = round_rect_photo(max(3, int(4 * s)), bar_h, 2 * s, PAL["accent"])
                self._imgs.append(bar)
                self.create_image(int(4 * s), h // 2, image=bar, anchor="w")
            fg, ic = PAL["peri_deep"], PAL["accent"]
        else:
            t = round(self._hover_t * 6) / 6.0
            if t > 0:
                img = round_rect_photo(w - 4, h - 4, 10 * s,
                                       lerp_color(self._bg, PAL["nav_hover"], t))
                self._imgs.append(img)
                self.create_image(2, 2, image=img, anchor="nw")
            fg = lerp_color(PAL["ink_soft"], PAL["ink"], t)
            ic = fg
        x = int(18 * s)
        if self._icon:
            ifont = (self._icon_font, max(9, int(self._font.cget("size")) + 1)) \
                if self._icon_font else self._font
            self.create_text(int(26 * s), h / 2, text=self._icon, font=ifont, fill=ic)
            x = int(48 * s)
        self.create_text(x, h / 2, text=self._text, font=self._font, fill=fg, anchor="w")


class ScrollableNavigation(tk.Frame):
    """Sidebar scroll container; the thin scrollbar only shows when needed."""

    def __init__(self, master, dpi=1):
        super().__init__(master, bg=PAL["panel2"])
        self.canvas = tk.Canvas(self, bg=PAL["panel2"], highlightthickness=0,
                                bd=0, yscrollincrement=max(1, int(22 * dpi)))
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style="CCNav.Vertical.TScrollbar")
        self._sb_shown = False
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body = tk.Frame(self.canvas, bg=PAL["panel2"])
        self.window_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", self._update_region)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.body.bind("<MouseWheel>", self._wheel)

    def _resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self._update_region()

    def _update_region(self, event=None):
        need = self.body.winfo_reqheight() > self.canvas.winfo_height() > 1
        if need != self._sb_shown:
            self._sb_shown = need
            if need:
                self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, before=self.canvas)
            else:
                self.scrollbar.pack_forget()
                self.canvas.yview_moveto(0)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(),
                                            max(self.body.winfo_reqheight() + int(self.canvas.cget("yscrollincrement")),
                                                self.canvas.winfo_height())))

    def _wheel(self, event):
        if self.body.winfo_reqheight() > self.canvas.winfo_height() and event.delta:
            steps = max(1, abs(int(event.delta / 120)))
            self.canvas.yview_scroll(-steps if event.delta > 0 else steps, "units")
        return "break"

    def bind_item(self, item):
        item.bind("<MouseWheel>", self._wheel, add="+")

    def reveal(self, item):
        self.update_idletasks()
        increment = int(self.canvas.cget("yscrollincrement"))
        height = max(self.body.winfo_reqheight() + increment, self.canvas.winfo_height())
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        item_top = item.winfo_y()
        item_bottom = item_top + item.winfo_height()
        if item_top < top:
            self.canvas.yview_moveto((item_top // increment * increment) / height)
        elif item_bottom > bottom:
            offset = item_bottom - self.canvas.winfo_height()
            self.canvas.yview_moveto(((offset + increment - 1) // increment * increment) / height)


class PastelSlider(tk.Canvas):
    """Anti-aliased rounded slider: lavender track, accent progress fill and a
    white shadowed knob. Supports drag, click-to-jump and mouse-wheel adjustment
    (wheel events are consumed so the page does not scroll while sliding)."""

    def __init__(self, master, from_=0, to=100, value=0, step=1,
                 command=None, on_release=None, bg="#ffffff",
                 width=300, height=28):
        self._lo = float(from_)
        self._hi = float(to)
        self._step = max(0.001, float(step))
        self._val = float(value)
        self._cmd = command
        self._rel = on_release
        self._sw = int(width)
        self._sh = int(height)
        self._hover = False
        self._dragging = False
        self._wheel_after = None
        super().__init__(master, width=self._sw, height=self._sh, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self._paint()

    def _x0(self):
        return 14.0

    def _x1(self):
        return self._sw - 14.0

    def _snap(self, v):
        v = max(self._lo, min(self._hi, v))
        v = self._lo + round((v - self._lo) / self._step) * self._step
        return max(self._lo, min(self._hi, v))

    def _x_for(self, val):
        ratio = (val - self._lo) / max(0.001, self._hi - self._lo)
        return self._x0() + (self._x1() - self._x0()) * ratio

    def _val_for(self, x):
        ratio = (x - self._x0()) / max(0.001, self._x1() - self._x0())
        ratio = max(0.0, min(1.0, ratio))
        return self._snap(self._lo + ratio * (self._hi - self._lo))

    def get_value(self):
        return int(round(self._val))

    def set_value(self, v, fire=True):
        self._val = self._snap(float(v))
        self._paint()
        if fire and self._cmd:
            self._cmd(int(round(self._val)))

    def _apply_x(self, x):
        self._val = self._val_for(x)
        self._paint()
        if self._cmd:
            self._cmd(int(round(self._val)))

    def _fire_release(self):
        self._wheel_after = None
        if self._rel:
            self._rel(int(round(self._val)))

    def _on_press(self, e):
        self._dragging = True
        self._apply_x(e.x)

    def _on_drag(self, e):
        self._apply_x(e.x)

    def _on_release(self, e):
        self._dragging = False
        self._apply_x(e.x)
        if self._rel:
            self._rel(int(round(self._val)))

    def _on_wheel(self, e):
        delta = 1 if e.delta > 0 else -1
        self.set_value(self._val + delta * self._step)
        if self._rel:
            # debounce: apply once shortly after the last wheel tick
            if self._wheel_after is not None:
                try:
                    self.after_cancel(self._wheel_after)
                except Exception:
                    pass
            self._wheel_after = self.after(350, self._fire_release)
        return "break"  # keep the page from scrolling while adjusting

    def _set_hover(self, on):
        self._hover = bool(on)
        self._paint()

    def _paint(self):
        self.delete("all")
        y = self._sh / 2.0
        th = max(5, int(self._sh * 0.24))
        x0, x1 = int(self._x0()), int(self._x1())
        x = int(round(self._x_for(self._val)))
        self._imgs = [round_rect_photo(x1 - x0, th, th / 2, "#e2e7f8")]
        self.create_image(x0, y, image=self._imgs[0], anchor="w")
        if x - x0 >= th:
            self._imgs.append(round_rect_photo(x - x0, th, th / 2, PAL["accent"]))
            self.create_image(x0, y, image=self._imgs[-1], anchor="w")
        d = int(self._sh * 0.68) + (2 if (self._hover or self._dragging) else 0)
        self._imgs.append(knob_photo(d, PAL["accent"]))
        self.create_image(x, y, image=self._imgs[-1])


class RoundedFrame(tk.Frame):
    """Frame with anti-aliased rounded corners and an optional 1px border.

    Put content into ``.body``. The corners are tiny image patches placed on
    top, so the frame stays a normal pack/grid container and resizes freely.
    """

    def __init__(self, master, radius=10, fill="#ffffff", border=None, outer=None):
        if outer is None:
            try:
                outer = master.cget("bg")
            except Exception:
                outer = PAL["bg"]
        self._outer, self._fill, self._border, self._r = outer, fill, border, int(radius)
        super().__init__(master, bg=border or fill, bd=0, highlightthickness=0)
        self.body = tk.Frame(self, bg=fill, bd=0, highlightthickness=0)
        pad = 1 if border else 0
        self.body.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self._corners = {}
        places = {"nw": dict(x=0, y=0), "ne": dict(relx=1.0, y=0),
                  "sw": dict(x=0, rely=1.0), "se": dict(relx=1.0, rely=1.0)}
        for c, kw in places.items():
            lab = tk.Label(self, bd=0, highlightthickness=0, padx=0, pady=0, bg=outer)
            lab.place(anchor=c, **kw)
            self._corners[c] = lab
        self._paint_corners()

    def _paint_corners(self):
        self._imgs = []
        for c, lab in self._corners.items():
            img = corner_photo(self._r, self._outer, self._fill, self._border, c, widget=self)
            self._imgs.append(img)
            lab.configure(image=img)
            lab.lift()

    def set_border(self, color):
        self._border = color
        self.configure(bg=color or self._fill)
        self._paint_corners()


def rounded_entry(parent, font, show="", fill="#fbfcfe", dpi=1.0, **kw):
    """Rounded input box with an accent focus ring. Returns the tk.Entry;
    pack / grid ``entry.box`` (the rounded container) instead of the entry."""
    box = RoundedFrame(parent, radius=int(7 * dpi), fill=fill, border=PAL["line"])
    e = tk.Entry(box.body, bg=fill, fg=PAL["ink"], insertbackground=PAL["peri"],
                 font=font, relief=tk.FLAT, bd=0, highlightthickness=0,
                 show=show or "", **kw)
    e.pack(fill=tk.X, padx=int(9 * dpi), pady=int(6 * dpi))
    e.bind("<FocusIn>", lambda _e: box.set_border(PAL["accent"]), add="+")
    e.bind("<FocusOut>", lambda _e: box.set_border(PAL["line"]), add="+")
    e.box = box  # type: ignore[attr-defined]
    return e


def rounded_combobox(parent, textvariable=None, values=(), font=None, dpi=1.0,
                     width=None, state="readonly", fill="#fbfcfe", on_change=None, **kw):
    """Rounded combobox inside a RoundedFrame container. Returns the ttk.Combobox;
    pack / grid ``combo.box`` instead of the combobox."""
    apply_combobox_style(parent, dpi=dpi)
    box = RoundedFrame(parent, radius=int(7 * dpi), fill=fill, border=PAL["line"])
    font = font or tkfont.nametofont("TkDefaultFont")
    cb_kw = dict(textvariable=textvariable, values=tuple(values), state=state,
                 font=font, style="CC.TCombobox")
    if width is not None:
        cb_kw["width"] = width
    cb_kw.update(kw)
    cb = ttk.Combobox(box.body, **cb_kw)
    cb.pack(fill=tk.X, padx=int(6 * dpi), pady=int(3 * dpi))
    cb.bind("<FocusIn>", lambda _e: box.set_border(PAL["accent"]), add="+")
    cb.bind("<FocusOut>", lambda _e: box.set_border(PAL["line"]), add="+")
    if callable(on_change):
        cb.bind("<<ComboboxSelected>>", lambda _e: on_change(cb.get()), add="+")
    cb.box = box  # type: ignore[attr-defined]
    return cb


def rounded_text(parent, font=None, height=6, dpi=1.0, fill="#fbfcfe", **kw):
    """Rounded multiline tk.Text with thin pastel scrollbar and accent focus border.
    Returns the tk.Text; pack / grid ``txt.box`` instead of the text widget."""
    apply_scroll_styles(parent, dpi=dpi)
    box = RoundedFrame(parent, radius=int(8 * dpi), fill=fill, border=PAL["line"])
    inner = tk.Frame(box.body, bg=fill)
    inner.pack(fill=tk.BOTH, expand=True, padx=int(4 * dpi), pady=int(4 * dpi))
    font = font or tkfont.nametofont("TkDefaultFont")
    txt_kw = dict(bg=fill, fg=PAL["ink"], font=font, height=height, wrap=tk.WORD,
                  relief=tk.FLAT, bd=0, highlightthickness=0,
                  insertbackground=PAL["peri"],
                  selectbackground=PAL["accent_soft"], selectforeground=PAL["ink"],
                  padx=int(6 * dpi), pady=int(4 * dpi), undo=True)
    txt_kw.update(kw)
    txt = tk.Text(inner, **txt_kw)
    vsb = ttk.Scrollbar(inner, orient="vertical", command=txt.yview,
                        style="CCCard.Vertical.TScrollbar")
    txt.configure(yscrollcommand=vsb.set)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    vsb.pack(side=tk.RIGHT, fill=tk.Y)
    txt.bind("<FocusIn>", lambda _e: box.set_border(PAL["accent"]), add="+")
    txt.bind("<FocusOut>", lambda _e: box.set_border(PAL["line"]), add="+")
    txt.box = box  # type: ignore[attr-defined]
    return txt


class Badge(tk.Canvas):
    """Anti-aliased pill badge for status labels (kind: ok / warn / err / info / muted)."""

    _KINDS = {
        "ok":    ("badge_ok_bg",    "badge_ok_fg"),
        "warn":  ("badge_warn_bg",  "badge_warn_fg"),
        "err":   ("badge_err_bg",   "badge_err_fg"),
        "info":  ("badge_info_bg",  "badge_info_fg"),
        "muted": ("badge_muted_bg", "badge_muted_fg"),
    }

    def __init__(self, master, text, kind="info", parent_bg="#ffffff",
                 font=None, padx=9, pady=2, fill=None, fg=None):
        bg_key, fg_key = self._KINDS.get(kind, self._KINDS["info"])
        self._fill = fill or PAL[bg_key]
        self._fg = fg or PAL[fg_key]
        self._font = font or tkfont.Font(root=master, family="Microsoft YaHei UI", size=9)
        self._padx = int(padx)
        self._pady = int(pady)
        self._bw = max(24, self._font.measure(str(text)) + self._padx * 2)
        self._bh = max(18, self._font.metrics("linespace") + self._pady * 2)
        super().__init__(master, width=self._bw, height=self._bh, bg=parent_bg,
                         highlightthickness=0, bd=0)
        self._img = round_rect_photo(self._bw, self._bh, self._bh // 2, self._fill)
        self._bg_item = self.create_image(0, 0, image=self._img, anchor="nw")
        self._txt_item = self.create_text(self._bw // 2, self._bh // 2, text=str(text),
                                          font=self._font, fill=self._fg)

    def set_badge(self, text, kind=None):
        if kind in self._KINDS:
            bg_key, fg_key = self._KINDS[kind]
            self._fill, self._fg = PAL[bg_key], PAL[fg_key]
        self._bw = max(24, self._font.measure(str(text)) + self._padx * 2)
        self.configure(width=self._bw)
        self._img = round_rect_photo(self._bw, self._bh, self._bh // 2, self._fill)
        self.itemconfigure(self._bg_item, image=self._img)
        self.coords(self._txt_item, self._bw // 2, self._bh // 2)
        self.itemconfigure(self._txt_item, text=str(text), fill=self._fg)


def show_help_popup(anchor, title, text, dpi=1.0):
    """Open a compact, rounded secondary popup window explaining a setting section."""
    root = anchor.winfo_toplevel()
    old = getattr(root, "_active_help_popup", None)
    if old is not None:
        try:
            old.destroy()
        except Exception:
            pass
    win = tk.Toplevel(root)
    root._active_help_popup = win  # type: ignore[attr-defined]
    win.title(f"{title} · 说明")
    win.configure(bg=PAL["bg"])
    win.resizable(False, False)
    try:
        win.attributes("-topmost", True)
        win.transient(root)
    except Exception:
        pass

    f_title = tkfont.Font(root=win, family="Microsoft YaHei UI", size=11, weight="bold")
    f_body = tkfont.Font(root=win, family="Microsoft YaHei UI", size=10)
    f_btn = tkfont.Font(root=win, family="Microsoft YaHei UI", size=9, weight="bold")

    card = RoundedFrame(win, radius=int(10 * dpi), fill="#ffffff", border=PAL["line_soft"])
    card.pack(fill=tk.BOTH, expand=True, padx=int(14 * dpi), pady=int(14 * dpi))
    inner = tk.Frame(card.body, bg="#ffffff")
    inner.pack(fill=tk.BOTH, expand=True, padx=int(18 * dpi), pady=int(14 * dpi))

    tk.Label(inner, text=title, font=f_title, fg=PAL["peri_deep"],
             bg="#ffffff").pack(anchor="w", pady=(0, int(6 * dpi)))
    tk.Frame(inner, bg=PAL["line_soft"], height=1).pack(fill=tk.X, pady=(0, int(8 * dpi)))
    tk.Label(inner, text=text, font=f_body, fg=PAL["ink_soft"], bg="#ffffff",
             justify=tk.LEFT, anchor="w",
             wraplength=int(360 * dpi)).pack(fill=tk.X, pady=(0, int(12 * dpi)))

    btn_row = tk.Frame(inner, bg="#ffffff")
    btn_row.pack(fill=tk.X)
    PastelButton(btn_row, "知道了", command=win.destroy, parent_bg="#ffffff",
                 fill=PAL["btn_primary"], fg=PAL["btn_primary_fg"],
                 hover=PAL["btn_primary_hover"], font=f_btn,
                 padx=int(14 * dpi), pady=int(5 * dpi),
                 radius=int(8 * dpi)).pack(side=tk.RIGHT)

    win.update_idletasks()
    w = max(int(380 * dpi), win.winfo_reqwidth())
    h = win.winfo_reqheight()
    try:
        ax, ay = anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height() + int(6 * dpi)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(12, min(ax - int(20 * dpi), sw - w - 16))
        y = max(12, min(ay, sh - h - 48))
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        win.geometry(f"{w}x{h}")
    style_titlebar(win, caption=PAL["bg"], text=PAL["ink"])
    win.bind("<Escape>", lambda _e: win.destroy())
    win.focus_force()
    return win


class HelpButton(tk.Canvas, _Anim):
    """Anti-aliased circular '?' button that opens a secondary explanation window."""

    def __init__(self, master, title, text, parent_bg="#ffffff", dpi=1.0):
        self._title = title
        self._text = text
        self._dpi = dpi
        self._t = 0.0
        self._d = max(18, int(20 * dpi))
        super().__init__(master, width=self._d, height=self._d, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        f_q = tkfont.Font(root=master, family="Microsoft YaHei UI", size=9, weight="bold")
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._txt_item = self.create_text(self._d // 2, self._d // 2, text="?",
                                          font=f_q, fill=PAL["peri_deep"])
        self._paint_t(0.0)
        self.bind("<Enter>", lambda _e: self._fade(1.0))
        self.bind("<Leave>", lambda _e: self._fade(0.0))
        self.bind("<ButtonRelease-1>", self._on_click)

    def _paint_t(self, t):
        self._t = t
        col = lerp_color(PAL["btn_soft"], PAL["accent"], round(t * 5) / 5.0)
        fg = "#ffffff" if t > 0.5 else PAL["peri_deep"]
        self._img = round_rect_photo(self._d, self._d, self._d // 2, col)
        self.itemconfigure(self._bg_item, image=self._img)
        self.itemconfigure(self._txt_item, fill=fg)

    def _fade(self, target):
        start = self._t
        self._animate(100, lambda e: self._paint_t(start + (target - start) * e))

    def _on_click(self, event):
        if 0 <= event.x < self._d and 0 <= event.y < self._d:
            show_help_popup(self, self._title, self._text, dpi=self._dpi)


class SmoothScroll:
    """Eased mouse-wheel scrolling for a Canvas with a scrollregion."""

    def __init__(self, canvas, step=70):
        self.cv = canvas
        self.step = step
        self.target = None
        self.job = None

    def _geometry(self):
        region = str(self.cv.cget("scrollregion")).split()
        total = float(region[3]) - float(region[1]) if len(region) == 4 else 0.0
        return total, float(self.cv.winfo_height())

    def wheel(self, event):
        try:
            total, view = self._geometry()
            if total <= view or not event.delta:
                return
            base = self.target if self.job is not None else self.cv.canvasy(0)
            self.target = max(0.0, min(total - view, base - event.delta / 120.0 * self.step))
            if self.job is None:
                self._tick()
        except tk.TclError:
            self.job = None

    def _tick(self):
        try:
            total, _view = self._geometry()
            cur = self.cv.canvasy(0)
            diff = self.target - cur
            if abs(diff) < 1.0 or total <= 0:
                if total > 0:
                    self.cv.yview_moveto(self.target / total)
                self.job = None
                return
            self.cv.yview_moveto((cur + diff * 0.32) / total)
            self.job = self.cv.after(12, self._tick)
        except tk.TclError:
            self.job = None


# ---------------------------------------------------------------------------
# window-level helpers
# ---------------------------------------------------------------------------
def apply_scroll_styles(root, dpi=1.0):
    """Thin, arrow-less pastel scrollbars for the control center."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    size = max(6, int(7 * dpi))
    for name, trough in (("CC.Vertical.TScrollbar", PAL["bg"]),
                         ("CCNav.Vertical.TScrollbar", PAL["panel2"]),
                         ("CCCard.Vertical.TScrollbar", PAL["card"])):
        style.layout(name, [("Vertical.Scrollbar.trough", {
            "sticky": "ns",
            "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
        })])
        style.configure(name, troughcolor=trough, background=PAL["scroll_thumb"],
                        bordercolor=trough, lightcolor=PAL["scroll_thumb"],
                        darkcolor=PAL["scroll_thumb"], gripcount=0, relief="flat",
                        arrowsize=size, width=size)
        style.map(name, background=[("pressed", PAL["accent"]), ("active", "#aab6e8")],
                  lightcolor=[("pressed", PAL["accent"]), ("active", "#aab6e8")],
                  darkcolor=[("pressed", PAL["accent"]), ("active", "#aab6e8")])


def apply_combobox_style(root, dpi=1.0):
    """Clean, flat pastel styling for ttk.Combobox (both CC.TCombobox and TCombobox)."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    pad = (int(6 * dpi), int(4 * dpi))
    for sname, border in (("CC.TCombobox", "#fbfcfe"), ("TCombobox", PAL["line"])):
        style.configure(sname,
                        fieldbackground="#fbfcfe",
                        background=PAL["btn_soft"],
                        foreground=PAL["ink"],
                        arrowcolor=PAL["peri_deep"],
                        bordercolor=border,
                        lightcolor="#fbfcfe",
                        darkcolor="#fbfcfe",
                        selectbackground=PAL["accent_soft"],
                        selectforeground=PAL["ink"],
                        arrowsize=int(12 * dpi),
                        padding=pad,
                        relief="flat")
        style.map(sname,
                  fieldbackground=[("readonly", "#fbfcfe"), ("disabled", PAL["panel2"])],
                  foreground=[("readonly", PAL["ink"]), ("disabled", PAL["ink_dim"])],
                  background=[("active", PAL["btn_soft_hover"]), ("readonly", PAL["btn_soft"])],
                  selectbackground=[("readonly", "#fbfcfe")],
                  selectforeground=[("readonly", PAL["ink"])])
    try:
        top = root.winfo_toplevel()
        top.option_add("*TCombobox*Listbox.background", "#ffffff")
        top.option_add("*TCombobox*Listbox.foreground", PAL["ink"])
        top.option_add("*TCombobox*Listbox.selectBackground", PAL["accent_soft"])
        top.option_add("*TCombobox*Listbox.selectForeground", PAL["peri_deep"])
    except Exception:
        pass


def style_secondary_window(win, title=None, width=None, height=None, dpi=1.0,
                           icon=None, parent=None, topmost=True):
    """Apply unified theme, geometry centering, scroll/combo styles, and Win11 titlebar tint."""
    if title:
        win.title(title)
    win.configure(bg=PAL["bg"])
    if topmost:
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
    if parent is not None:
        try:
            win.transient(parent)
        except Exception:
            pass
    if icon is not None:
        try:
            win.iconphoto(False, icon)
        except Exception:
            pass
    if width and height:
        try:
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            w = min(int(width), max(360, sw - 60))
            h = min(int(height), max(280, sh - 60))
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            win.geometry(f"{int(width)}x{int(height)}")
    apply_scroll_styles(win, dpi=dpi)
    apply_combobox_style(win, dpi=dpi)
    style_titlebar(win, caption=PAL["bg"], text=PAL["ink"])


def icon_family(root):
    """Windows' built-in icon font (Win11 Fluent / Win10 MDL2), or None."""
    try:
        fams = set(tkfont.families(root))
    except Exception:
        return None
    for fam in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if fam in fams:
            return fam
    return None


def style_titlebar(win, caption=None, text=None):
    """Win11: tint the native title bar to blend with the window (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        for attr, color in ((35, caption), (36, text)):   # CAPTION / TEXT color
            if color:
                r, g, b = to_rgb(color)
                val = ctypes.c_int(r | (g << 8) | (b << 16))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass
