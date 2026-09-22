"""Exercise the native mini-chat alpha surface without starting pet services."""
import sys
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@unittest.skipUnless(sys.platform == "win32", "The desktop UI uses Win32")
class MiniChatTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        main.enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.tk.call("tk", "scaling", 96 / 72)
        self.root.overrideredirect(True)
        self.root.geometry("220x220+4000+4000")
        self.root.update()
        self.addCleanup(self.root.destroy)
        self.pet = pet = main.DesktopPet.__new__(main.DesktopPet)
        pet.root, pet.dpi_scale, pet.size = self.root, 1.0, 220
        pet.config = {"pet_size": 220}
        pet.always_on_top = True
        pet.bubble_cache = {}
        pet.fam_main = "Microsoft YaHei UI"
        pet.f_bubble = tkfont.Font(self.root, family=pet.fam_main, size=11, weight="bold")
        pet.find_sprite_path = lambda name: str(main.PATHS.assets_dir / name)
        pet.layered = Mock()
        pet.chat_open, pet.speech_timer = False, None
        pet.current_emotion = "默认"
        pet.set_emotion = Mock()
        pet.init_bubble()

    def show(self, text):
        self.pet.show_speech(text, duration_ms=30000)
        self.root.update()

    def test_native_surface_preserves_original_soft_edge_coverage(self):
        pet = self.pet
        self.show("人，织织在这里呀！")
        self.assertIsNotNone(pet._bubble_alpha_win)
        self.assertEqual(pet._bubble_alpha_win.hwnd, self.main.toplevel_hwnd(pet.bubble))
        self.assertFalse(pet.bubble.attributes("-transparentcolor"))
        frame = pet._bubble_alpha_win._frame
        self.assertEqual(frame.size, pet.bubble_geo)
        self.assertEqual(frame.getpixel((0, 0))[3], 0)
        self.assertGreater(sum(frame.getchannel("A").histogram()[1:255]), 1000)
        banner = pet._bubble_renderer.banner(frame.width)
        sample = next((x, y) for y in range(30) for x in range(60)
                      if 20 < banner.getpixel((x, y))[3] < 230)
        self.assertEqual(frame.getpixel(sample), banner.getpixel(sample))

    def test_multiline_text_fits_artwork_at_small_and_large_sizes(self):
        pet = self.pet
        for size, dpi in ((100, 1.0), (220, 1.5), (420, 2.0)):
            pet.config["pet_size"], pet.dpi_scale = size, dpi
            self.show("第一段中文和 English words\n\n" + "换行后的长句仍然留在气泡里面。" * 20)
            renderer = pet._bubble_renderer
            x0, y0, x1, y1 = renderer._text_key[-1]
            left, top, right, bottom = renderer._text_layer.getbbox()
            self.assertGreaterEqual(left, x0-2)
            self.assertGreaterEqual(top, y0-2)
            self.assertLessEqual(right, x1+2)
            self.assertLessEqual(bottom, y1+2)
            font = renderer._font(11)
            self.assertEqual(renderer._wrap("第一段\n\n第二段", font, 1000, 5),
                             (["第一段", "", "第二段"], False))

    def test_move_resize_hide_reshow_and_destroy_keep_the_surface_in_sync(self):
        pet = self.pet
        self.show("短句")
        alpha = pet._bubble_alpha_win
        self.root.geometry("220x220+4200+4400")
        self.root.update()
        pet.update_bubble_position()
        self.root.update()
        w, h = pet.bubble_geo
        self.assertEqual(pet.bubble.winfo_x(), self.root.winfo_x()+110-w//2)
        self.assertEqual(pet.bubble.winfo_y(), self.root.winfo_y()-h-8)
        self.show("长句内容 " * 100)
        self.assertIs(pet._bubble_alpha_win, alpha)
        self.assertEqual(alpha._size, pet.bubble_geo)
        pet.hide_speech()
        self.root.update()
        self.assertFalse(pet.bubble.winfo_ismapped())
        self.show("再次出现")
        self.assertTrue(pet.bubble.winfo_ismapped())
        self.assertIs(pet._bubble_alpha_win, alpha)
        self.assertEqual(alpha._size, pet.bubble_geo)
        pet.bubble.destroy()
        self.root.update()
        self.assertIsNone(pet._bubble_alpha_win)
        self.assertIsNone(pet._bubble_render_job)
        self.assertIsNone(alpha._memdc)

    def test_emotion_thumbnail_composes_with_straight_alpha(self):
        pet = self.pet
        self.show(chr(0) + "IMG:生气")
        frame = pet._bubble_alpha_win._frame
        expected = pet._bubble_renderer.banner(frame.width).copy()
        box = int(frame.height * .72)
        with Image.open(self.main.PATHS.assets_dir / "生气.png") as source:
            artwork = source.convert("RGBA")
        artwork.thumbnail((box, box), Image.Resampling.LANCZOS)
        x = (frame.width-box)//2 + (box-artwork.width)//2
        y = (frame.height-box)//2 + (box-artwork.height)//2
        expected.alpha_composite(artwork, (x, y))
        self.assertEqual(frame.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
