# -*- coding: utf-8 -*-
"""Verify kaomoji font fallback in ChatBubbleRenderer.

Run directly:  python -X utf8 tests/test_kaomoji_fallback.py
Kept out of module scope so "python -m unittest discover -s tests" only collects
real unittest cases and does not execute (and sys.exit) this manual probe.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image
from pet_chat_render import ChatBubbleRenderer, _font_coverage


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    msyh = _font_coverage("msyh.ttc")
    sym = _font_coverage("seguisym.ttf")
    emj = _font_coverage("seguiemj.ttf")

    checks = [
        ("msyh has 中", ord("中") in msyh, True),
        ("msyh has あ", ord("あ") in msyh, True),
        ("msyh has ▽", ord("▽") in msyh, True),
        ("msyh lacks ✧", ord("✧") in msyh, False),
        ("msyh lacks ∇", ord("∇") in msyh, False),
        ("msyh lacks ♡", ord("♡") in msyh, False),
        ("sym has ✧", ord("✧") in sym, True),
        ("sym has ∇", ord("∇") in sym, True),
        ("sym has ♡", ord("♡") in sym, True),
        ("sym lacks 中", ord("中") in sym, False),
        ("emj has U+1F600", 0x1F600 in emj, True),
    ]
    ok = True
    print("coverage sizes: msyh", len(msyh), "sym", len(sym), "emj", len(emj))
    for name, got, want in checks:
        status = "PASS" if got == want else "FAIL"
        ok &= got == want
        print(status, name)

    class FakeTkFont:
        def actual(self):
            return {"family": "Microsoft YaHei UI", "weight": "bold", "size": 11}

    art = Image.new("RGBA", (400, 200), (255, 240, 245, 255))
    buf = io.BytesIO()
    art.save(buf, "PNG")
    buf.seek(0)
    r = ChatBubbleRenderer(buf, FakeTkFont(), 1.0)
    base = r._font(11)
    px = 22
    for ch in "(✧∇✧)♡‿∀٩◕۶中あو":
        f = r._char_font(ch, px, base)
        src = ("base(msyh)" if f is base else
               next(n for n in ("seguisym.ttf", "seguiemj.ttf", "segoeui.ttf")
                    if f is r._truetype(n, px)))
        print(f"U+{ord(ch):04X} {ch} -> {src}")

    sample = "你好呀～(✧∇✧) 好开心！(≧▽≦)ノ♡ ✧٩(ˊωˋ*)و✧ ∇"
    frame = r.render((400, 200), sample, (90, 70, 120, 255), (20, 60, 380, 160), [])
    frame.save(Path(__file__).parent / "bubble_kaomoji_check.png")
    print("saved", Path(__file__).parent / "bubble_kaomoji_check.png")
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
