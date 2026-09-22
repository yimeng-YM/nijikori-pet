"""Modern conversation-history window for the 虹语织 desktop pet.

The old history window was a flat ``tk.Text`` dump: every message was a plain
line ("人: …", "虹语织: …") with no speaker affordance, no timestamps, no way to
find anything, and re-rendering the whole 2000-entry log at once.

This module replaces it with a canvas-rendered transcript:

* chat bubbles (pet left / user right) with avatars, names and times,
* tool calls collapsed into compact accent cards,
* system notes as centered pills,
* keyword search + role filter chips with live counts,
* virtualized rendering (only the newest page of blocks is drawn, older ones
  load on demand) so a long session never blocks the UI,
* per-message copy via right-click and a "jump to latest" affordance.

Nothing here imports ``main``: palette, fonts and widgets are injected, which
keeps the window on-theme without a circular import.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

# Blocks drawn per virtualized page. Older blocks are reachable through the
# "载入更早" affordance at the top of the transcript.
PAGE_BLOCKS = 60

# A single tool card never renders more than this many lines; the remainder is
# summarised (the full text stays in the exported transcript).
TOOL_LINE_CAP = 24

TOOL_PREFIX = "[织织自主调用工具: "

FILTER_LABELS = (("all", "全部"), ("chat", "对话"), ("tool", "工具"), ("sys", "系统"))


# ---------------------------------------------------------------------------
# display_log -> render blocks
# ---------------------------------------------------------------------------

def _norm_head(text):
    head = str(text or "").strip().rstrip("：").rstrip(":").strip()
    if "虹语织" in head or "织织" in head:
        # the log writes the full name; the pet calls herself 织织 on screen
        return "织织"
    return head or "织织"


def consume(blocks, entry):
    """Fold one display_log entry into the block list (in place).

    main.py logs a chat message as two entries — a ``user``/``bot`` header line
    ("人: ") followed by a ``msg`` body — and every tool call as its own ``tool``
    line. Blocks regroup that flat stream into renderable units.
    """
    tag = entry.get("tag") or "msg"
    text = entry.get("text") or ""
    ts = entry.get("ts")
    if tag in ("user", "bot"):
        blocks.append({"kind": "message", "pet": tag == "bot",
                       "head": _norm_head(text), "body": "", "ts": ts})
    elif tag == "msg":
        if blocks and blocks[-1]["kind"] == "message":
            blocks[-1]["body"] += text
        else:
            blocks.append({"kind": "message", "pet": True, "head": "织织",
                           "body": text, "ts": ts})
    elif tag == "sys":
        body = text.strip()
        if not body:
            return blocks
        if blocks and blocks[-1]["kind"] == "sys":
            blocks[-1]["body"] = (blocks[-1]["body"] + " " + body).strip()
        else:
            blocks.append({"kind": "sys", "body": body, "ts": ts})
    else:  # tool
        body = text.strip()
        if not body:
            return blocks
        if blocks and blocks[-1]["kind"] == "tool":
            blocks[-1]["body"] += "\n" + body
        else:
            blocks.append({"kind": "tool", "body": body, "ts": ts})
    return blocks


def build_blocks(entries):
    blocks = []
    for entry in entries or ():
        consume(blocks, entry)
    return blocks


def body_of(block):
    """Display body of a block (trailing blank lines from the log removed)."""
    return (block.get("body") or "").strip("\n").rstrip()


def _matches(block, query):
    if not query:
        return True
    haystack = (body_of(block) + " " + str(block.get("head") or "")).lower()
    return query in haystack


def filter_blocks(blocks, kind="all", query=""):
    q = (query or "").strip().lower()
    wanted = {"chat": "message", "tool": "tool", "sys": "sys"}.get(kind)
    out = []
    for block in blocks:
        if wanted and block["kind"] != wanted:
            continue
        if not _matches(block, q):
            continue
        out.append(block)
    return out


def count_blocks(blocks, query=""):
    q = (query or "").strip().lower()
    counts = {"all": 0, "chat": 0, "tool": 0, "sys": 0}
    for block in blocks:
        if not _matches(block, q):
            continue
        counts["all"] += 1
        if block["kind"] == "message":
            counts["chat"] += 1
        elif block["kind"] == "tool":
            counts["tool"] += 1
        else:
            counts["sys"] += 1
    return counts


# Punctuation that must never begin a wrapped line (CJK 避头尾 / kinsoku). Keeping
# it on the previous line makes a small, deliberate overflow acceptable.
_TRAILING_MARKS = set("）〉》」』】〕〗〙〛”’!！,，.。:：;；?？、…‥ー～)%]}»")


def wrap_text(text, font, max_px):
    """Greedy wrap against real Tk font metrics (binary search per line).

    Measuring in Python keeps the whole transcript layout computable before any
    canvas item is created, so scrolling and re-wrapping stay cheap.
    """
    max_px = max(24, int(max_px))
    lines = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        rest = paragraph
        while rest:
            if font.measure(rest) <= max_px:
                lines.append(rest)
                break
            lo, hi = 1, len(rest)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.measure(rest[:mid]) <= max_px:
                    lo = mid
                else:
                    hi = mid - 1
            cut = max(1, lo)
            if cut < len(rest) and rest[cut - 1:cut + 1].isascii():
                space = rest.rfind(" ", 0, cut + 1)
                if space >= cut // 2:
                    cut = max(1, space)
            # 避头尾: never let closing punctuation start the next line
            while cut < len(rest) and rest[cut] in _TRAILING_MARKS:
                cut += 1
            lines.append(rest[:cut].rstrip())
            rest = rest[cut:].lstrip()
    return lines


def pretty_tool_line(line):
    """Turn "[织织自主调用工具: foo] bar" into the readable "foo · bar".

    The log wrapper repeats on every line of a tool chain, which drowns the
    actual content once several calls are shown together.
    """
    line = str(line or "").strip()
    if line.startswith(TOOL_PREFIX):
        rest = line[len(TOOL_PREFIX):]
        cut = rest.find("]")
        if cut >= 0:
            name = rest[:cut].strip()
            tail = rest[cut + 1:].strip()
            return f"{name} · {tail}" if tail else (name or "（已调用）")
    return line


def format_time(ts):
    try:
        return time.strftime("%H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def block_to_text(block):
    """Plain-text form of one block, used by the right-click copy action."""
    body = body_of(block)
    if block["kind"] == "message":
        head = block.get("head") or "织织"
        return f"{head}：{body}" if body else head
    return body


# ---------------------------------------------------------------------------
# Small widgets
# ---------------------------------------------------------------------------

class _Placeholder:
    """Greyed-out hint text inside a tk.Entry (Tk has none built in)."""

    def __init__(self, entry, text, normal_fg, dim_fg):
        self.entry = entry
        self.text = text
        self.normal_fg = normal_fg
        self.dim_fg = dim_fg
        self.active = False

    def show(self):
        if self.active:
            return
        if not self.entry.get():
            self.active = True
            self.entry.insert(0, self.text)
            self.entry.config(fg=self.dim_fg)

    def hide(self):
        if not self.active:
            return
        self.active = False
        self.entry.delete(0, tk.END)
        self.entry.config(fg=self.normal_fg)


class _Chip(tk.Canvas):
    """Pill-shaped filter chip with an active state and a live count."""

    def __init__(self, master, label, command, font, pal, dpi, rounded_rect,
                 active=False):
        self._label = label
        self._cmd = command
        self.font = font
        self.pal = pal
        self.dpi = dpi
        self._rounded = rounded_rect
        self._active = bool(active)
        self._hover = False
        # NOTE: never use `_w`/`_h` here — tkinter.Misc stores the widget's Tk
        # path name in `_w` and clobbering it breaks the widget.
        self._cw, self._ch = self._measure()
        super().__init__(master, width=self._cw, height=self._ch,
                         bg=pal["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self._paint()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda e: self._cmd(self._label_key))

    # -- geometry ---------------------------------------------------------
    def _measure(self):
        pad = int(round(11 * self.dpi))
        self._label_key = self._label.split(" ")[0]
        return self.font.measure(self._label) + pad * 2, self.font.metrics("linespace") + int(round(9 * self.dpi))

    def set_label(self, label):
        if label == self._label:
            return
        self._label = label
        w, h = self._measure()
        if (w, h) != (self._cw, self._ch):
            self._cw, self._ch = w, h
            self.config(width=w, height=h)
        self._paint()

    def set_active(self, flag):
        flag = bool(flag)
        if flag != self._active:
            self._active = flag
            self._paint()

    # -- painting ---------------------------------------------------------
    def _paint(self):
        self.delete("all")
        pal = self.pal
        if self._active:
            fill = pal["peri"]
            fg = "#ffffff"
        elif self._hover:
            fill = pal["btn_soft_hover"]
            fg = pal["btn_soft_fg"]
        else:
            fill = pal["btn_soft"]
            fg = pal["btn_soft_fg"]
        r = self._ch / 2
        self._rounded(self, 0.5, 0.5, self._cw - 0.5, self._ch - 0.5, r,
                      fill=fill, outline="")
        self.create_text(self._cw / 2, self._ch / 2, text=self._label,
                         font=self.font, fill=fg)

    def _on_enter(self, _event=None):
        self._hover = True
        if not self._active:
            self._paint()

    def _on_leave(self, _event=None):
        self._hover = False
        if not self._active:
            self._paint()


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

class ChatHistoryWindow:
    """A single, self-contained modern conversation-record window."""

    SEARCH_HINT = "搜索对话内容…"

    def __init__(self, host, parent, *, pal, fonts, dpi=1.0,
                 pastel_button, rounded_rect, scroll_style,
                 get_entries, get_subtitle, on_export, on_clear, on_send,
                 title="与 虹语织 的对话记录"):
        self.host = host
        self.pal = pal
        self.fonts = fonts
        self.dpi = float(dpi or 1.0)
        self._PastelButton = pastel_button
        self._rounded = rounded_rect
        self.scroll_style = scroll_style
        self.get_entries = get_entries
        self.get_subtitle = get_subtitle or (lambda: "")
        self.on_export = on_export
        self.on_clear = on_clear
        self.on_send = on_send
        self.title = title

        self.win = None
        self._blocks = []
        self._visible = []
        self._hits = []
        self._filter = "all"
        self._query = ""
        self._limit = PAGE_BLOCKS
        self._render_job = None
        self._flash_job = None
        self._stick = True

        self._build(parent)
        self.rebuild(preserve_limit=False)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _px(self, value):
        return int(round(value * self.dpi))

    def _build(self, parent):
        pal = self.pal
        fonts = self.fonts
        px = self._px

        win = tk.Toplevel(parent)
        self.win = win
        win.title(self.title)
        win.config(bg=pal["bg"])
        win.geometry(f"{px(720)}x{px(700)}")
        win.minsize(px(470), px(430))
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            icon = getattr(self.host, "app_icon", None)
            if icon is not None:
                win.iconphoto(False, icon)
        except Exception:
            pass

        # ---- header: title + live session stats ------------------------
        # No custom ✕ here: the toplevel already has a native close button.
        header = tk.Frame(win, bg=pal["bg"])
        header.pack(fill=tk.X, padx=px(18), pady=(px(14), 0))
        title_col = tk.Frame(header, bg=pal["bg"])
        title_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_col, text="对话记录", font=fonts["title"],
                 fg=pal["peri"], bg=pal["bg"]).pack(anchor="w")
        self.subtitle = tk.Label(title_col, text=self.get_subtitle(),
                                 font=fonts["small"], fg=pal["ink_soft"],
                                 bg=pal["bg"], anchor="w", justify="left")
        self.subtitle.pack(anchor="w")

        # ---- toolbar: search + record actions --------------------------
        bar = tk.Frame(win, bg=pal["bg"])
        bar.pack(fill=tk.X, padx=px(18), pady=(px(10), 0))
        search_wrap = tk.Frame(bar, bg="#ffffff", highlightthickness=1,
                               highlightbackground=pal["line"])
        search_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(search_wrap, text="🔍", font=fonts["small"],
                 fg=pal["ink_soft"], bg="#ffffff").pack(side=tk.LEFT,
                                                        padx=(px(8), 0))
        self.search = tk.Entry(search_wrap, font=fonts["ui"], bg="#ffffff",
                               fg=pal["ink"], relief=tk.FLAT,
                               insertbackground=pal["peri"], highlightthickness=0)
        self.search.pack(side=tk.LEFT, fill=tk.X, expand=True,
                         padx=(px(4), px(8)), ipady=px(5))
        self._search_ph = _Placeholder(self.search, self.SEARCH_HINT,
                                       pal["ink"], pal["ink_dim"])
        # <Key> runs before Tk's class binding inserts the character, so the
        # hint text is always gone before real input lands (also covers paste).
        self.search.bind("<Key>", self._on_search_key_press)
        self.search.bind("<FocusIn>", lambda e: self._on_search_key_press())
        self.search.bind("<FocusOut>", lambda e: self._search_ph.show())
        self.search.bind("<KeyRelease>", self._on_search_key)
        self.search.bind("<Escape>", lambda e: self._clear_search())

        for text, cmd, kind in (("导出", self.on_export, "soft"),
                                ("复制", self.copy_all, "soft"),
                                ("清空", self.on_clear, "danger")):
            fill, fg, hover = self._button_colors(kind)
            self._PastelButton(bar, text, command=cmd, parent_bg=pal["bg"],
                               fill=fill, fg=fg, hover=hover,
                               font=fonts["ui"], padx=px(11),
                               pady=px(5)).pack(side=tk.LEFT, padx=(px(6), 0))

        # ---- filter chips ----------------------------------------------
        chips_row = tk.Frame(win, bg=pal["bg"])
        chips_row.pack(fill=tk.X, padx=px(18), pady=(px(8), 0))
        self._chips = {}
        for key, label in FILTER_LABELS:
            chip = _Chip(chips_row, f"{label} 0", lambda k, key=key: self.set_filter(key),
                         fonts["small"], pal, self.dpi, self._rounded,
                         active=(key == self._filter))
            chip.pack(side=tk.LEFT, padx=(0, px(6)))
            self._chips[key] = (chip, label)
        self._count_label = tk.Label(chips_row, text="", font=fonts["small"],
                                     fg=pal["ink_soft"], bg=pal["bg"])
        self._count_label.pack(side=tk.RIGHT)

        # ---- transcript -------------------------------------------------
        body = tk.Frame(win, bg=pal["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=px(18), pady=(px(10), px(6)))
        self.canvas = tk.Canvas(body, bg=pal["hist_surface"],
                                highlightthickness=1,
                                highlightbackground=pal["line"], bd=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL,
                                       style=self.scroll_style,
                                       command=self.canvas.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.config(yscrollcommand=self._on_yview)
        self.canvas.bind("<Configure>", lambda e: self.schedule_render(70))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.canvas.bind("<Button-3>", self._on_right_click)

        self.jump = self._PastelButton(body, "↓ 最新", command=self.jump_to_latest,
                                       parent_bg=pal["hist_surface"],
                                       fill=pal["btn_primary"],
                                       fg=pal["btn_primary_fg"],
                                       hover=pal["btn_primary_hover"],
                                       font=fonts["small"], padx=px(10), pady=px(4))
        self.jump.place_forget()

        # ---- composer ---------------------------------------------------
        row = tk.Frame(win, bg=pal["bg"])
        row.pack(fill=tk.X, padx=px(18), pady=(0, px(14)))
        entry_wrap = tk.Frame(row, bg="#ffffff", highlightthickness=1,
                              highlightbackground=pal["line"])
        entry_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry = tk.Entry(entry_wrap, font=fonts["body"], bg="#ffffff",
                              fg=pal["ink"], relief=tk.FLAT,
                              insertbackground=pal["peri"], highlightthickness=0)
        self.entry.pack(fill=tk.X, expand=True, padx=px(8), ipady=px(6))
        self._entry_ph = _Placeholder(self.entry, "和织织说点什么…（Enter 发送）",
                                      pal["ink"], pal["ink_dim"])
        self.entry.bind("<Key>", lambda e: self._entry_ph.hide())
        self.entry.bind("<FocusIn>", lambda e: self._entry_ph.hide())
        self.entry.bind("<FocusOut>", lambda e: self._entry_ph.show())
        self.entry.bind("<Return>", lambda e: self.submit())
        self.entry.bind("<KP_Enter>", lambda e: self.submit())
        self._PastelButton(row, "发送", command=self.submit, parent_bg=pal["bg"],
                           fill=pal["btn_primary"], fg=pal["btn_primary_fg"],
                           hover=pal["btn_primary_hover"], font=fonts["ui_bold"],
                           padx=px(16), pady=px(6)).pack(side=tk.RIGHT,
                                                          padx=(px(10), 0))
        self._search_ph.show()
        self._entry_ph.show()
        self.entry.focus_set()

    def _button_colors(self, kind):
        pal = self.pal
        if kind == "danger":
            return pal["btn_danger"], pal["btn_danger_fg"], pal["btn_danger_hover"]
        if kind == "primary":
            return pal["btn_primary"], pal["btn_primary_fg"], pal["btn_primary_hover"]
        return pal["btn_soft"], pal["btn_soft_fg"], pal["btn_soft_hover"]

    def _colors(self):
        pal = self.pal
        return {
            "surface": pal.get("hist_surface", "#ffffff"),
            "user_bubble": pal.get("hist_user_bubble", "#dfeafc"),
            "user_text": pal.get("hist_user_text", "#22405f"),
            "pet_bubble": pal.get("hist_pet_bubble", "#e4f6ef"),
            "pet_text": pal.get("hist_pet_text", "#1f4a3d"),
            "tool_card": pal.get("hist_tool_card", "#f2eefc"),
            "tool_text": pal.get("hist_tool_text", "#5b3fa8"),
            "tool_line": pal.get("hist_tool_line", "#6b5aa8"),
            "sys_pill": pal.get("hist_sys_pill", "#eef1f8"),
            "sys_text": pal.get("hist_sys_text", "#5f6884"),
            "avatar_pet": pal.get("hist_avatar_pet", "#5cc4a5"),
            "avatar_user": pal.get("hist_avatar_user", "#7aa9df"),
            "meta": pal.get("ink_soft", "#5a6490"),
            "divider": pal.get("line_soft", "#dee4f6"),
            "load_more": pal.get("btn_soft", "#e7ecfa"),
            "load_more_text": pal.get("btn_soft_fg", "#5a64a0"),
        }

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def alive(self):
        try:
            return self.win is not None and bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def close(self):
        for job in (self._render_job, self._flash_job):
            if job is None:
                continue
            try:
                self.win.after_cancel(job)
            except Exception:
                pass
        self._render_job = self._flash_job = None
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        try:
            if self.win is not None:
                self.win.destroy()
        except tk.TclError:
            pass
        self.win = None

    def winfo_exists(self):
        return self.alive()

    # ------------------------------------------------------------------
    # data in
    # ------------------------------------------------------------------
    def rebuild(self, preserve_limit=False):
        self._blocks = build_blocks(self.get_entries())
        if not preserve_limit:
            self._limit = PAGE_BLOCKS
        self._stick = True
        self.refresh_subtitle()
        self.schedule_render(0)

    def append(self, entry):
        consume(self._blocks, entry)
        self.refresh_subtitle()
        self.schedule_render(40)

    def refresh_subtitle(self, text=None):
        if not self.alive():
            return
        if text is None:
            text = self.get_subtitle()
        try:
            self.subtitle.config(text=text)
        except tk.TclError:
            pass

    def flash(self, message, ms=1800):
        self.refresh_subtitle(message)
        if self._flash_job is not None:
            try:
                self.win.after_cancel(self._flash_job)
            except Exception:
                pass
        try:
            self._flash_job = self.win.after(ms, lambda: self.refresh_subtitle())
        except tk.TclError:
            self._flash_job = None

    # ------------------------------------------------------------------
    # filters & search
    # ------------------------------------------------------------------
    def set_filter(self, key):
        if key == self._filter:
            return
        self._filter = key
        self._limit = PAGE_BLOCKS
        self._stick = True
        for name, (chip, _label) in self._chips.items():
            chip.set_active(name == key)
        self.schedule_render(0)

    def _on_search_key_press(self, _event=None):
        self._search_ph.hide()

    def _on_search_key(self, _event=None):
        if self._search_ph.active:
            return
        query = self.search.get().strip()
        if query == self._query:
            return
        self._query = query
        self._limit = PAGE_BLOCKS
        self.schedule_render(200)

    def _clear_search(self):
        self._search_ph.hide()
        self.search.delete(0, tk.END)
        if self._query:
            self._query = ""
            self.schedule_render(0)
        return "break"

    def load_more(self):
        self._limit += PAGE_BLOCKS
        self.schedule_render(0)

    # ------------------------------------------------------------------
    # composer
    # ------------------------------------------------------------------
    def submit(self):
        if self._entry_ph.active:
            self.entry.focus_set()
            return "break"
        if not self.entry.get().strip():
            return "break"
        self._entry_ph.hide()
        try:
            self.on_send()
        finally:
            self.entry.focus_set()
        return "break"

    # ------------------------------------------------------------------
    # copy
    # ------------------------------------------------------------------
    def _to_clipboard(self, text):
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
        except tk.TclError:
            return
        self.flash("已复制到剪贴板 ✓")

    def copy_all(self):
        text = "".join(e.get("text", "") for e in self.get_entries())
        if not text.strip():
            self.flash("还没有可以复制的记录哦")
            return
        self._to_clipboard(text)

    def _on_right_click(self, event):
        cy = self.canvas.canvasy(event.y)
        for y0, y1, index in self._hits:
            if y0 - 2 <= cy <= y1 + 2:
                try:
                    block = self._visible[index]
                except IndexError:
                    return None
                menu = tk.Menu(self.win, tearoff=0)
                menu.add_command(label="复制这条",
                                 command=lambda b=block: self._to_clipboard(block_to_text(b)))
                menu.add_command(label="复制全部记录", command=self.copy_all)
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    menu.grab_release()
                return "break"
        return None

    # ------------------------------------------------------------------
    # scrolling
    # ------------------------------------------------------------------
    def _on_yview(self, first, last):
        try:
            self.scrollbar.set(first, last)
            self._stick = float(last) >= 0.999
        except (tk.TclError, ValueError):
            return
        self._update_jump()

    def _on_wheel(self, event):
        if not self.alive():
            return
        steps = int(-event.delta / 120) or (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(steps * 3, "units")
        return "break"

    def jump_to_latest(self):
        if not self.alive():
            return
        self._stick = True
        self.canvas.yview_moveto(1.0)
        self._update_jump()

    def _update_jump(self):
        if not self.alive():
            return
        try:
            if self._stick:
                self.jump.place_forget()
            else:
                self.jump.place(relx=1.0, rely=1.0, x=-self._px(24),
                                y=-self._px(14), anchor="se")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def schedule_render(self, delay=40):
        if not self.alive() or self._render_job is not None:
            return
        try:
            self._render_job = self.win.after(delay, self._render)
        except tk.TclError:
            self._render_job = None

    def _render(self):
        # Drop (and cancel) any job this call supersedes: a direct call while a
        # timer is pending would otherwise leave a dangling Tcl callback.
        job, self._render_job = self._render_job, None
        if job is not None:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        if not self.alive():
            return
        canvas = self.canvas
        try:
            canvas.delete("all")
        except tk.TclError:
            return
        width = canvas.winfo_width()
        if width <= 1:
            self.schedule_render(40)
            return

        col = self._colors()
        pad = self._px(16)
        inner = max(140, width - 2 * pad)
        blocks = filter_blocks(self._blocks, self._filter, self._query)
        total = len(blocks)
        start = max(0, total - self._limit)
        self._visible = blocks
        self._hits = []

        y = pad
        if start > 0:
            y = self._draw_load_more(canvas, start, y, inner, col)
        for index in range(start, total):
            y0 = y
            y = self._draw_block(canvas, blocks[index], y, inner, col, pad)
            self._hits.append((y0, y, index))
            y += self._px(12)
        if total:
            # extra bottom room so the floating "↓ 最新" chip never covers the tail
            y += pad + self._px(20)
        else:
            self._draw_empty(canvas, width, col)
            y = max(y, canvas.winfo_height())

        try:
            canvas.config(scrollregion=(0, 0, width, max(y, canvas.winfo_height())))
        except tk.TclError:
            return
        self._sync_scrollbar(y <= canvas.winfo_height())
        self._refresh_chips(total)
        if self._stick:
            canvas.yview_moveto(1.0)
        self._update_jump()

    def _sync_scrollbar(self, fits):
        """Hide the bar when the whole transcript already fits on screen."""
        try:
            if fits:
                self.scrollbar.pack_forget()
            elif not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        except tk.TclError:
            pass

    def _refresh_chips(self, total):
        counts = count_blocks(self._blocks, self._query)
        for key, (chip, label) in self._chips.items():
            chip.set_label(f"{label} {counts.get(key, 0)}")
        if self._query:
            self._count_label.config(text=f"匹配 {total} 条")
        elif total > self._limit:
            self._count_label.config(text=f"显示最近 {self._limit} / {total} 条")
        else:
            self._count_label.config(text=f"共 {total} 条")

    def _rr(self, canvas, x0, y0, x1, y1, r, **kw):
        r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        return self._rounded(canvas, x0, y0, x1, y1, r, **kw)

    def _draw_block(self, canvas, block, y, inner, col, pad):
        if block["kind"] == "sys":
            return self._draw_pill(canvas, block, y, inner, col)
        if block["kind"] == "tool":
            return self._draw_tool(canvas, block, y, inner, col, pad)
        return self._draw_message(canvas, block, y, inner, col, pad)

    def _draw_message(self, canvas, block, y, inner, col, pad):
        px = self._px
        f_body = self.fonts["body"]
        f_meta = self.fonts["meta"]
        pet = bool(block.get("pet"))
        body = body_of(block)
        avatar = px(26)
        gap = px(9)
        bpx, bpy = px(13), px(9)
        radius = px(13)
        meta_h = f_meta.metrics("linespace")

        text_left = pad + avatar + gap
        max_bubble = int(inner * 0.74)
        lines = wrap_text(body, f_body, max(80, max_bubble - 2 * bpx)) if body else []
        line_h = f_body.metrics("linespace")
        bubble_w = (max((f_body.measure(line) for line in lines), default=0)
                    + 2 * bpx) if lines else 0
        bubble_h = (len(lines) * line_h + 2 * bpy) if lines else 0

        # avatar
        ax = pad + avatar / 2 if pet else pad + inner - avatar / 2
        canvas.create_oval(ax - avatar / 2, y, ax + avatar / 2, y + avatar,
                           fill=col["avatar_pet" if pet else "avatar_user"],
                           outline="")
        canvas.create_text(ax, y + avatar / 2, text="织" if pet else "我",
                           fill="#ffffff", font=self.fonts["avatar"])

        name = block.get("head") or ("织织" if pet else "人")
        stamp = format_time(block.get("ts"))
        meta = f"{name} · {stamp}" if stamp else name
        if pet:
            canvas.create_text(text_left, y + avatar / 2, text=meta, anchor="w",
                               fill=col["meta"], font=f_meta)
        else:
            # keep the right-aligned meta clear of the avatar column
            canvas.create_text(pad + inner - avatar - gap, y + avatar / 2,
                               text=meta, anchor="e", fill=col["meta"],
                               font=f_meta)

        top = y + max(avatar, meta_h) + px(6)
        if lines:
            x0 = text_left if pet else pad + inner - bubble_w
            key = "pet" if pet else "user"
            self._rr(canvas, x0, top, x0 + bubble_w, top + bubble_h, radius,
                     fill=col[f"{key}_bubble"], outline=col["divider"], width=1)
            text_y = top + bpy
            for line in lines:
                canvas.create_text(x0 + bpx, text_y, text=line or " ", anchor="nw",
                                   fill=col[f"{key}_text"], font=f_body)
                text_y += line_h
        return top + bubble_h

    def _draw_pill(self, canvas, block, y, inner, col):
        px = self._px
        font = self.fonts["small"]
        body = body_of(block) or "（空）"
        line_h = font.metrics("linespace")
        max_w = int(inner * 0.82)
        lines = wrap_text(body, font, max(60, max_w - px(26)))
        width = max((font.measure(line) for line in lines), default=0) + px(26)
        height = len(lines) * line_h + px(12)
        x0 = px(8) + (inner - width) / 2.0
        self._rr(canvas, x0, y, x0 + width, y + height, height / 2.0,
                 fill=col["sys_pill"], outline="")
        text_y = y + px(6)
        for line in lines:
            canvas.create_text(x0 + width / 2, text_y, text=line or " ",
                               anchor="n", fill=col["sys_text"], font=font)
            text_y += line_h
        return y + height

    def _draw_tool(self, canvas, block, y, inner, col, pad):
        px = self._px
        font = self.fonts["small"]
        head_font = self.fonts["ui_bold"]
        source = [line for line in body_of(block).split("\n") if line.strip()]
        source = [pretty_tool_line(line) for line in source]
        hidden = 0
        if len(source) > TOOL_LINE_CAP:
            hidden = len(source) - TOOL_LINE_CAP
            source = source[:TOOL_LINE_CAP]
        indent = px(20)
        avail = max(60, inner - indent - px(16))
        wrapped = []
        for line in source:
            wrapped.extend(wrap_text(line, font, avail) or [""])
        if hidden:
            wrapped.append(f"…（还有 {hidden} 行，可从「导出」查看全文）")

        head_h = head_font.metrics("linespace")
        line_h = font.metrics("linespace")
        height = px(10) + head_h + px(6) + len(wrapped) * line_h + px(11)
        self._rr(canvas, pad, y, pad + inner, y + height, px(12),
                 fill=col["tool_card"], outline=col["divider"], width=1)
        self._rr(canvas, pad + px(7), y + px(9), pad + px(10), y + height - px(9),
                 px(2), fill=col["tool_text"], outline="")

        text_x = pad + indent
        canvas.create_text(text_x, y + px(10), text="🛠 工具调用", anchor="nw",
                           fill=col["tool_text"], font=head_font)
        text_y = y + px(10) + head_h + px(6)
        for line in wrapped:
            canvas.create_text(text_x, text_y, text=line or " ", anchor="nw",
                               fill=col["tool_line"], font=font)
            text_y += line_h
        return y + height

    def _draw_empty(self, canvas, width, col):
        """Friendly empty state (nothing yet vs. nothing matched the filter)."""
        px = self._px
        searching = bool(self._query) or self._filter != "all"
        line1 = "没有找到匹配的记录" if searching else "还没有对话记录"
        line2 = ("换个关键词试试，或点「全部」看看别的记录～" if searching
                 else "去和织织聊两句，我们的聊天记录就会留在这里啦～")
        top = max(px(70), canvas.winfo_height() // 2 - px(52))
        canvas.create_text(width / 2, top, text="🫧",
                           font=self.fonts["title"], fill=col["load_more_text"])
        canvas.create_text(width / 2, top + px(38), text=line1,
                           font=self.fonts["ui_bold"], fill=col["sys_text"])
        canvas.create_text(width / 2, top + px(62), text=line2,
                           font=self.fonts["small"], fill=col["meta"])

    def _draw_load_more(self, canvas, start, y, inner, col):
        px = self._px
        font = self.fonts["ui"]
        shown = min(start, PAGE_BLOCKS)
        label = f"↑ 载入更早的 {shown} 条（还有 {start} 条）"
        width = font.measure(label) + px(30)
        height = font.metrics("linespace") + px(12)
        x0 = (inner - width) / 2.0
        self._rr(canvas, x0, y, x0 + width, y + height, height / 2.0,
                 fill=col["load_more"], outline="", tags=("loadmore",))
        canvas.create_text(x0 + width / 2, y + height / 2, text=label,
                           fill=col["load_more_text"], font=font,
                           tags=("loadmore",))
        for item in canvas.find_withtag("loadmore"):
            canvas.tag_bind(item, "<Button-1>", lambda e: self.load_more())
            canvas.tag_bind(item, "<Enter>",
                            lambda e: canvas.config(cursor="hand2"))
            canvas.tag_bind(item, "<Leave>", lambda e: canvas.config(cursor=""))
        return y + height + px(12)
