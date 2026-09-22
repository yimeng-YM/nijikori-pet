"""Low-profile growing input and small galgame-style dialogue controls."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


class ChatIconButton(tk.Button):
    """Native keyboard-accessible button with crisp, font-independent icons."""

    def __init__(self, master, palette, dpi, command, icon, label):
        self.palette = palette
        self.dpi = dpi
        self.size = round(22 * dpi)
        self._background = master.cget("bg")
        self._images = {}
        self._rgba_images = {}
        self._tip = None
        self._tip_job = None
        self._hovered = False
        super().__init__(master, command=command, bd=0, relief=tk.FLAT,
                         bg=self._background, activebackground=self._background, padx=0, pady=0,
                         highlightthickness=max(1, round(dpi)),
                         highlightbackground=self._background, highlightcolor=palette["peri"],
                         takefocus=True, cursor="hand2")
        self.set_icon(icon, label)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._show_tip)
        self.bind("<FocusOut>", self._hide_tip)
        self.bind("<Return>", lambda event: (self.invoke(), "break")[1])
        self.bind("<Destroy>", self._hide_tip)

    def render_icon(self, hovered=None):
        hovered = self._hovered if hovered is None else hovered
        focused = self.focus_get() == self
        key = self.icon, hovered, focused, str(self["state"])
        if key in self._rgba_images:
            return self._rgba_images[key]
        pal = self.palette
        ink = pal["peri_deep"] if hovered else pal["ink_soft"]
        # Draw at 4x and downsample so curved icons stay smooth at every DPI.
        scale = self.size * 4 / 24
        bitmap = Image.new("RGBA", (self.size * 4, self.size * 4))
        draw = ImageDraw.Draw(bitmap)
        box = lambda values: tuple(round(v * scale) for v in values)
        stroke = max(1, round(1.3 * scale))
        if hovered or focused:
            draw.rounded_rectangle(box((0, 0, 24, 24)), radius=round(5 * scale), fill=pal["panel2"])
        if focused:
            draw.rounded_rectangle(box((1, 1, 23, 23)), radius=round(5 * scale),
                                   outline=pal["peri"], width=stroke)
        if self.icon == "stop":
            draw.rounded_rectangle(box((7, 7, 17, 17)), radius=round(1.5 * scale), fill=ink)
        elif self.icon == "close":
            draw.line(box((7, 7, 17, 17)), fill=ink, width=stroke)
            draw.line(box((7, 17, 17, 7)), fill=ink, width=stroke)
        else:
            # Open logbook: a quiet visual-novel backlog affordance.
            draw.line(box((12, 7, 8, 5, 4, 5, 4, 17, 8, 17, 12, 19,
                           16, 17, 20, 17, 20, 5, 16, 5, 12, 7, 12, 19)),
                      fill=ink, width=stroke, joint="curve")
        image = bitmap.resize((self.size, self.size), Image.Resampling.LANCZOS)
        self._rgba_images[key] = image
        return image

    def _image(self, hovered):
        key = self.icon, hovered, str(self["state"])
        if key in self._images:
            return self._images[key]
        image = ImageTk.PhotoImage(self.render_icon(hovered), master=self)
        self._images[key] = image
        return image

    def set_icon(self, icon, label, enabled=True):
        self.icon, self.label = icon, label
        self.configure(text=label, state=tk.NORMAL if enabled else tk.DISABLED,
                       cursor="hand2" if enabled else "arrow")
        self.configure(image=self._image(self._hovered))
        if self._tip is not None:
            self._tip_label.configure(text=label)

    def _enter(self, _event=None):
        self._hovered = True
        self.configure(image=self._image(True))
        self._tip_job = self.after(450, self._show_tip)

    def _leave(self, _event=None):
        self._hovered = False
        self.configure(image=self._image(False))
        self._hide_tip()

    def _show_tip(self, _event=None):
        self._hide_tip()
        self._tip = tk.Toplevel(self)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        self._tip_label = tk.Label(self._tip, text=self.label, bg=self.palette["ink"],
                                   fg="white", padx=8, pady=4)
        self._tip_label.pack()
        self._tip.update_idletasks()
        x = min(self.winfo_rootx(), self.winfo_screenwidth() - self._tip.winfo_reqwidth() - 4)
        y = max(4, self.winfo_rooty() - self._tip.winfo_reqheight() - 6)
        self._tip.geometry(f"+{max(4, x)}+{y}")

    def _hide_tip(self, _event=None):
        if self._tip_job is not None:
            self.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class ChatComposer(tk.Canvas):
    """One to six display lines; overflow scrolls without growing the window forever."""

    def __init__(self, master, palette, font, dpi, on_send, on_height_change):
        self.palette, self.dpi, self.font = palette, dpi, font
        self._send = on_send
        self._on_height_change = on_height_change
        self.busy = False
        self._refresh_job = None
        self._focused = False
        # Set by the pet to promote the whole input toplevel before editing.
        self.on_activate = None
        self._visible_lines = 1
        self._line_height = font.metrics("linespace")
        self._inset = round(3 * dpi)
        self.min_height = self._line_height + 2 * self._inset
        self.input_height = self.min_height
        super().__init__(master, width=400, height=self.min_height, bg=master.cget("bg"),
                         bd=0, highlightthickness=0)
        self.text = tk.Text(self, height=1, width=1, wrap=tk.WORD, font=font,
                            bg=palette["bg"], fg=palette["ink"], insertbackground=palette["peri"],
                            insertwidth=max(1, round(2 * dpi)), bd=0, relief=tk.FLAT,
                            highlightthickness=0, padx=0, pady=0, undo=True,
                            maxundo=100, autoseparators=True, takefocus=True)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self._text_window = self.create_window(0, 0, window=self.text, anchor="nw")
        self._scroll_window = self.create_window(0, 0, window=self.scrollbar, anchor="ne", state="hidden")
        self._hint = tk.Label(self, text="输入消息…  Enter 发送", font=font, anchor="w",
                              fg=palette["ink_dim"], bg=palette["bg"], bd=0, padx=0, pady=0)
        self._hint.bind("<Button-1>", self._activate)
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<Configure>", self._queue_refresh)
        self.text.bind("<FocusIn>", lambda event: self._focus(True))
        self.text.bind("<FocusOut>", lambda event: self._focus(False))
        self.text.bind("<Return>", self._submit)
        self.text.bind("<Shift-Return>", self._newline)
        self.text.bind("<KP_Enter>", self._submit)
        self.text.bind("<Shift-KP_Enter>", self._newline)
        self.text.bind("<Tab>", lambda event: self._tab(False))
        self.text.bind("<Shift-Tab>", lambda event: self._tab(True))
        self.text.bind("<Control-a>", self._select_all)
        self.bind("<Configure>", self._layout)
        self.bind("<Destroy>", self._destroy)
        self._overflow = False
        self._queue_refresh()

    def _activate(self, _event=None):
        if callable(self.on_activate):
            self.on_activate()
        else:
            self.text.focus_set()

    def _submit(self, _event=None):
        # Enter never cancels a running answer or accidentally sends a draft.
        if not self.busy:
            self._send()
        return "break"

    def _newline(self, _event=None):
        if self.text.tag_ranges(tk.SEL):
            self.text.delete(tk.SEL_FIRST, tk.SEL_LAST)
        self.text.insert(tk.INSERT, "\n")
        self.text.see(tk.INSERT)
        return "break"

    def _tab(self, backwards):
        if hasattr(self, "on_tab"):
            self.on_tab(backwards)
            return "break"
        target = self.text.tk_focusPrev() if backwards else self.text.tk_focusNext()
        if target is not None:
            target.focus_set()
        return "break"

    def _select_all(self, _event=None):
        self.text.tag_add(tk.SEL, "1.0", "end-1c")
        return "break"

    def _focus(self, focused):
        self._focused = focused
        self._layout()

    def set_busy(self, busy):
        self.busy = bool(busy)

    def _modified(self, _event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self._queue_refresh()

    def _queue_refresh(self, _event=None):
        if self._refresh_job is None:
            self._refresh_job = self.after_idle(self._refresh)

    def _refresh(self):
        self._refresh_job = None
        count = self.text.count("1.0", "end-1c", "displaylines")
        lines = 1 + (count[0] if count else 0)
        self._overflow = lines > 6
        self._visible_lines = min(lines, 6)
        height = max(self.min_height, self._visible_lines * self._line_height + 2 * self._inset)
        changed = height != self.input_height
        self.input_height = height
        self.configure(height=height)
        self._layout()
        if changed:
            self._on_height_change(height)

    def _layout(self, _event=None):
        width = self.winfo_width()
        height = self.input_height
        dpi, pal = self.dpi, self.palette
        self.delete("surface")
        r = round(6 * dpi)
        x0, y0, x1, y1 = 1, 1, width - 1, height - 1
        points = [x0+r, y0, x1-r, y0, x1, y0, x1, y0+r, x1, y1-r,
                  x1, y1, x1-r, y1, x0+r, y1, x0, y1, x0, y1-r, x0, y0+r, x0, y0]
        self.create_polygon(points, smooth=True, fill=pal["bg"], outline="", tags="surface")
        self.create_line(round(6*dpi), height-1, width-round(6*dpi), height-1,
                         fill=pal["line"] if self._focused else pal["line_soft"],
                         width=max(1, round(dpi)), tags="surface")
        self.tag_lower("surface")
        text_x = round(8 * dpi)
        right = width - text_x
        scroll_width = round(10 * dpi) if self._overflow else 0
        text_height = self._visible_lines * self._line_height
        text_y = (height - text_height) // 2
        self.coords(self._text_window, text_x, text_y)
        self.itemconfigure(self._text_window, width=max(1, right-text_x-scroll_width),
                           height=text_height)
        self.coords(self._scroll_window, right, self._inset)
        self.itemconfigure(self._scroll_window, state="normal" if self._overflow else "hidden",
                           width=max(1, scroll_width), height=height - 2 * self._inset)
        if not self.text.get("1.0", "end-1c") and not self._focused:
            self._hint.place(x=text_x, y=text_y, width=max(1, right-text_x))
        else:
            self._hint.place_forget()

    def _destroy(self, event):
        if event.widget is self and self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
