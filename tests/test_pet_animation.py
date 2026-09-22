"""Visual motion invariants and task/sprite lifecycle regressions."""
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from layered_pet import LayeredPetRenderer, K_BROW_R, K_LID_R, K_EYE_R


class LayeredAnimationTests(unittest.TestCase):
    def test_blink_lowers_intact_brow_and_lid_and_hides_iris(self):
        renderer = LayeredPetRenderer(700)
        opened, closed = [Image.new("RGBA", (700, 700)) for _ in range(2)]
        renderer._draw_eyes(opened, 0, 0, 0, 0, 0)
        renderer._draw_eyes(closed, 1, 0, 0, 0, 0)
        x, y = map(int, renderer.pos[K_BROW_R])
        brow = renderer.img[K_BROW_R]
        box = (x, y, x+brow.width, y+brow.height+15)
        a, b = opened.crop(box), closed.crop(box)
        ab, bb = a.getbbox(), b.getbbox()
        self.assertGreater(bb[1], ab[1])
        self.assertEqual(a.crop(ab).tobytes(), b.crop(bb).tobytes())

        # The dark upper lash keeps its thickness and width while moving down.
        x, y = map(int, renderer.pos[K_LID_R])
        w = renderer.img[K_LID_R].width
        height = renderer.img[K_EYE_R].height + renderer.img[K_LID_R].height
        silhouettes = []
        for frame in (opened, closed):
            crop = frame.crop((x, y, x+w, y+height))
            mask = Image.new("L", crop.size)
            mask.putdata([a if max(r, g, b) < 70 else 0 for r, g, b, a in crop.getdata()])
            silhouettes.append(mask)
        a, b = silhouettes
        ab, bb = a.getbbox(), b.getbbox()
        self.assertGreater(bb[1], ab[1])
        self.assertLessEqual(abs((ab[3]-ab[1])-(bb[3]-bb[1])), 1)
        self.assertLessEqual(abs((ab[2]-ab[0])-(bb[2]-bb[0])), 1)
        # Edge alpha changes slightly when the underlying iris is occluded.
        self.assertAlmostEqual(sum(a.getdata()) / sum(b.getdata()), 1.0, delta=.05)
        gold = lambda frame: sum(a > 0 and r > 100 and 80 < g < 230 and b < 150
                                 for r, g, b, a in frame.getdata())
        self.assertGreater(gold(opened), 100)
        # The original lash artwork itself has a few warm-colored edge pixels.
        self.assertLess(gold(closed), gold(opened) * .025)

    def test_working_spin_changes_tuft_and_stopping_restores_idle(self):
        renderer = LayeredPetRenderer(350)
        renderer.pose = lambda t: dict(head_dy=0, float_dy=0, ahoge=0,
                                      tail_r=0, tail_l=0, hair_r=0, hair_l=0)
        renderer._blink_amount = lambda now: 0
        idle = renderer.tick(0)
        renderer.set_working(True)
        start = renderer.tick(.1)
        for i in range(2, 7):
            renderer.set_working(True)  # polling must not restart the spin
            end = renderer.tick(i*.1)
        self.assertNotEqual(start.crop((100, 0, 250, 130)).tobytes(),
                            end.crop((100, 0, 250, 130)).tobytes())
        self.assertEqual(start.crop((0, 150, 350, 350)).tobytes(),
                         end.crop((0, 150, 350, 350)).tobytes())
        renderer.set_working(False)
        self.assertEqual(renderer.tick(.7).tobytes(), idle.tobytes())
        renderer.set_facing("left")
        self.assertEqual(renderer.tick(.8).tobytes(),
                         idle.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes())


@unittest.skipUnless(sys.platform == "win32", "Desktop integration uses Win32")
class TaskAnimationTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        self.pet = main.DesktopPet.__new__(main.DesktopPet)
        self.pet._ai_work_lock = threading.Lock()
        self.pet._ai_work = {}
        self.pet._active_cancel_event = None
        self.pet._harness_busy = False

    def test_work_indicator_survives_closed_chat_and_clears_on_finish_or_error(self):
        pet = self.pet
        pet.chat_open, pet.chat_composer = False, None
        pet.layered = LayeredPetRenderer(220)
        for failure in (None, RuntimeError("request failed")):
            def worker(*args):
                pet._sync_chat_action()
                self.assertTrue(pet.layered.working)
                self.assertTrue(pet._is_ai_working())
                if failure:
                    raise failure
                return "done", None
            pet._chat_complete_loop_impl = worker
            if failure:
                with self.assertRaises(RuntimeError):
                    pet._chat_complete_loop("", {}, {})
            else:
                self.assertEqual(pet._chat_complete_loop("", {}, {}), ("done", None))
            pet._sync_chat_action()
            self.assertFalse(pet.layered.working)
            self.assertEqual(pet._ai_work, {})

    def test_cancelled_turn_does_not_hide_other_background_work(self):
        pet = self.pet
        cancel = pet._active_cancel_event = threading.Event()
        pet._ai_work = {"chat": cancel, "scheduled": None}
        self.assertTrue(pet._is_ai_working())
        cancel.set()
        self.assertTrue(pet._is_ai_working())
        pet._ai_work.pop("scheduled")
        self.assertFalse(pet._is_ai_working())
        pet._harness_busy = True
        self.assertTrue(pet._is_ai_working())
        pet._harness_busy = False
        self.assertFalse(pet._is_ai_working())

    def test_sweep_preserves_source_pauses_and_holds_the_displayed_last_frame(self):
        pet, main = self.pet, self.main
        for name in ("frames_normal", "frames_flipped", "frames_rgba_normal",
                     "frames_rgba_flipped", "frame_delays"):
            setattr(pet, name, {})
        pet.size = 220
        pet.find_sprite_path = lambda filename: str(main.PATHS.assets_dir / filename)
        with patch.object(main, "EMOTIONS", [("打扫卫生", "打扫卫生.png", "")]), \
                patch.object(main.ImageTk, "PhotoImage", side_effect=lambda img: img):
            pet.load_all_sprites()
        delays = pet.frame_delays["打扫卫生"]
        self.assertEqual(len(delays), 24)
        self.assertEqual(delays[13], 500)
        self.assertEqual(delays[-1], 1500)
        pet.root = Mock()
        pet.current_emotion, pet.facing = "默认", "right"
        pet.config = {}
        pet.anim_timer, pet.layered = None, None
        pet._alpha_used = True
        pet._present_current = Mock()
        pet.set_emotion("打扫卫生")
        for index, delay in enumerate(delays):
            self.assertIs(pet._cur_pil_frame, pet.frames_rgba_normal["打扫卫生"][index])
            actual_delay, callback = pet.root.after.call_args.args
            self.assertEqual(actual_delay, delay)
            callback()
        self.assertIs(pet._cur_pil_frame, pet.frames_rgba_normal["打扫卫生"][0])
        pet.current_emotion = "默认"
        pet.root.after.reset_mock()
        callback()
        pet.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
