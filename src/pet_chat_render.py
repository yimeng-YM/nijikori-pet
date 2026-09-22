"""RGBA dialogue artwork and text for the same native alpha path as the pet."""
import os
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
# No single Windows font covers both CJK and kaomoji symbols: Microsoft YaHei
# lacks ✧ ∇ ♡ ♥ ᴗ ‿ ✦ ⋆ ٩ ◕ ۶ ⊂ ⊃ …, while Segoe UI Symbol/Emoji cover them
# but lack full-width CJK forms. Draw text with per-character fallback runs.
SYMBOL_FALLBACKS = ("seguisym.ttf", "seguiemj.ttf", "segoeui.ttf")

_COVERAGE_CACHE = {}


def _read_cmap(data):
    """Codepoints mapped by a TTF/TTC's cmap — a minimal, dependency-free reader."""
    cps = set()
    try:
        first = 0
        if data[:4] == b"ttcf":  # TrueType collection: use the first face
            first = struct.unpack_from(">I", data, 12)[0]
        num_tables = struct.unpack_from(">H", data, first + 4)[0]
        cmap_off = None
        for i in range(num_tables):
            rec = first + 12 + 16 * i
            if data[rec:rec + 4] == b"cmap":
                cmap_off = struct.unpack_from(">I", data, rec + 8)[0]
                break
        if cmap_off is None:
            return cps
        # Table offsets inside a TTC face are absolute from the file start.
        base = cmap_off
        num_sub = struct.unpack_from(">H", data, base + 2)[0]
        rank_of = {(3, 10): 5, (0, 4): 4, (0, 6): 4, (0, 3): 3,
                   (3, 1): 2, (0, 1): 1, (0, 2): 1}
        best_rank, sub = -1, None
        for i in range(num_sub):
            pid, eid, off = struct.unpack_from(">HHI", data, base + 4 + 8 * i)
            rank = rank_of.get((pid, eid), 0)
            if rank > best_rank:
                best_rank, sub = rank, base + off
        if sub is None:
            return cps
        fmt = struct.unpack_from(">H", data, sub)[0]
        if fmt == 4:
            seg_x2 = struct.unpack_from(">H", data, sub + 6)[0]
            n = seg_x2 // 2
            # Layout: endCode[14..], startCode, idDelta, idRangeOffset follow,
            # each segCount*2 bytes, all offsets relative to the subtable start.
            ends = struct.unpack_from(f">{n}H", data, sub + 14)
            starts = struct.unpack_from(f">{n}H", data, sub + 14 + seg_x2)
            deltas = struct.unpack_from(f">{n}h", data, sub + 14 + 2 * seg_x2)
            range_offs = struct.unpack_from(f">{n}H", data, sub + 14 + 3 * seg_x2)
            for s, e, d, ro in zip(starts, ends, deltas, range_offs):
                if s == 0xFFFF and e == 0xFFFF:
                    continue
                if ro == 0:
                    for cp in range(s, e + 1):
                        if (cp + d) & 0xFFFF:
                            cps.add(cp)
                else:
                    for cp in range(s, e + 1):
                        if struct.unpack_from(">H", data, sub + ro + (cp - s) * 2)[0]:
                            cps.add(cp)
        elif fmt == 12:
            n_groups = struct.unpack_from(">I", data, sub + 12)[0]
            for i in range(n_groups):
                s, e, g = struct.unpack_from(">III", data, sub + 16 + 12 * i)
                if g:  # g == 0 would map the whole run to .notdef
                    cps.update(range(s, e + 1))
    except (struct.error, IndexError):
        pass
    return cps


def _font_coverage(name):
    if name not in _COVERAGE_CACHE:
        try:
            _COVERAGE_CACHE[name] = _read_cmap((_FONT_DIR / name).read_bytes())
        except OSError:
            _COVERAGE_CACHE[name] = set()
    return _COVERAGE_CACHE[name]


class ChatBubbleRenderer:
    def __init__(self, artwork, font, pixels_per_point, min_font_size=8):
        with Image.open(artwork) as source:
            self.source = source.convert("RGBA")
        self.font_spec = font.actual()
        self.pixels_per_point = pixels_per_point
        self.min_font_size = min_font_size
        self._fonts = {}       # (pixels, file or None) -> FreeTypeFont
        self._char_fonts = {}  # (pixels, char) -> FreeTypeFont for that glyph
        self._base_file = None
        self._banner = None
        self._text_key = None
        self._text_layer = None

    def set_font(self, font):
        spec = font.actual()
        if spec != self.font_spec:
            self.font_spec = spec
            self._fonts.clear()
            self._char_fonts.clear()
            self._base_file = None
            self._text_key = None

    def banner(self, width):
        if self._banner is None or self._banner.width != width:
            self._banner = self.source.resize(
                (width, round(width * self.source.height / self.source.width)),
                Image.Resampling.LANCZOS)
        return self._banner

    def _truetype(self, name, pixels):
        key = pixels, name
        if key not in self._fonts:
            try:
                self._fonts[key] = ImageFont.truetype(str(_FONT_DIR / name), pixels)
            except OSError:
                self._fonts[key] = None
        return self._fonts[key]

    def _font(self, points):
        """Base (CJK) font for layout metrics; records which file backs it."""
        pixels = max(1, round(points * self.pixels_per_point * 2))
        bold = self.font_spec.get("weight") == "bold"
        family = self.font_spec.get("family", "").lower()
        preferred = ("seguisb.ttf" if bold else "segoeui.ttf") if "segoe" in family else (
            "msyhbd.ttc" if bold else "msyh.ttc")
        file = self._base_file
        if file is None:
            file = self._base_file = next(
                (name for name in (preferred, "msyh.ttc", "segoeui.ttf")
                 if self._truetype(name, pixels) is not None), None)
        font = self._truetype(file, pixels) if file else None
        return font or ImageFont.load_default()

    def _char_font(self, ch, pixels, base_font):
        """Font actually able to draw `ch`; falls back to symbol/emoji fonts."""
        key = pixels, ch
        if key not in self._char_fonts:
            font = base_font
            base_file = self._base_file
            covered = ord(ch) in _font_coverage(base_file) if base_file else False
            if not covered:
                cp = ord(ch)
                for name in SYMBOL_FALLBACKS:
                    if name == base_file:
                        continue
                    if cp in _font_coverage(name):
                        candidate = self._truetype(name, pixels)
                        if candidate is not None:
                            font = candidate
                            break
            self._char_fonts[key] = font
        return self._char_fonts[key]

    def _runs(self, line, pixels, base_font):
        """Split a line into consecutive same-font runs for mixed drawing."""
        runs = []
        for ch in line:
            font = self._char_font(ch, pixels, base_font)
            if runs and runs[-1][1] is font:
                runs[-1][0] += ch
            else:
                runs.append([ch, font])
        return runs

    @staticmethod
    def _wrap(text, font, width, max_lines):
        """Wrap CJK and Latin text, stopping as soon as the visible box fills."""
        lines = []
        for rest in text.split("\n"):
            if len(lines) >= max_lines:
                return lines, True
            if not rest:
                lines.append("")
            while rest:
                if len(lines) >= max_lines:
                    return lines, True
                lo, hi = 1, min(len(rest), 1024)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if font.getlength(rest[:mid]) <= width:
                        lo = mid
                    else:
                        hi = mid - 1
                cut = lo
                # Prefer a word boundary for Latin runs without wasting CJK lines.
                if cut < len(rest) and rest[cut-1:cut+1].isascii():
                    space = rest.rfind(" ", 0, cut + 1)
                    if space >= cut // 2:
                        cut = max(1, space)
                lines.append(rest[:cut].rstrip())
                rest = rest[cut:].lstrip()
        return lines, False

    def _message_layer(self, size, text, color, bounds):
        key = size, text, color, bounds
        if key == self._text_key:
            return self._text_layer
        x0, y0, x1, y1 = bounds
        width, height = max(1, (x1 - x0) * 2), max(1, (y1 - y0) * 2)
        base = abs(int(self.font_spec.get("size", 11)))
        for points in range(base, min(base, self.min_font_size) - 1, -1):
            font = self._font(points)
            pixels = max(1, round(points * self.pixels_per_point * 2))
            ascent, descent = font.getmetrics()
            line_height = ascent + descent
            lines, overflow = self._wrap(text, font, width, max(1, height // line_height))
            if not overflow:
                break
        if overflow and lines:
            last = lines[-1]
            while last and font.getlength(last + "…") > width:
                last = last[:-1]
            lines[-1] = last + "…"
        layer = Image.new("RGBA", (size[0] * 2, size[1] * 2))
        draw = ImageDraw.Draw(layer)
        top = y0 * 2 + max(0, (height - len(lines) * line_height) // 2)
        for index, line in enumerate(lines):
            runs = self._runs(line, pixels, font)
            total = sum(run_font.getlength(run) for run, run_font in runs)
            x = (x0 + x1) - total / 2
            for run, run_font in runs:
                # Baseline anchors include the font's ascent, matching native line spacing.
                draw.text((x, top + index * line_height + ascent), run,
                          font=run_font, fill=color, anchor="ls")
                x += run_font.getlength(run)
        self._text_layer = layer.resize(size, Image.Resampling.LANCZOS)
        self._text_key = key
        return self._text_layer

    def render(self, size, text, color, bounds, controls):
        frame = Image.new("RGBA", size)
        frame.alpha_composite(self.banner(size[0]))
        if text:
            frame.alpha_composite(self._message_layer(size, text, color, bounds))
        for icon, x, y in controls:
            frame.alpha_composite(icon, (round(x - icon.width / 2), round(y - icon.height / 2)))
        return frame
