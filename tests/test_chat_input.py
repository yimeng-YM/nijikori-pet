"""Exercise real Tk input/layout and task transitions without starting the pet services."""
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@unittest.skipUnless(sys.platform == "win32", "The desktop UI uses Win32")
class ChatInputTests(unittest.TestCase):
    def setUp(self):
        import main
        main.enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.tk.call("tk", "scaling", 96 / 72)
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.pet = pet = main.DesktopPet.__new__(main.DesktopPet)
        self.addCleanup(lambda: pet.on_close_chat_window() if getattr(pet, "chat_open", False) else None)
        pet.root, pet.dpi_scale, pet.size = self.root, 1.0, 180
        pet.config = {"model": "test-model"}
        pet.chat_img_cache = {}
        pet.find_sprite_path = lambda name: str(main.PATHS.assets_dir / name)
        for name in ("f_chat", "f_small", "f_ui", "f_ui_bold", "f_title", "f_chat_bold", "f_sm_italic"):
            setattr(pet, name, tkfont.Font(self.root, family="Microsoft YaHei UI",
                                          size=9 if name == "f_small" else 10))
        pet.touch_interaction = Mock()
        pet._enable_taskbar = Mock()
        pet.speech_timer = None
        pet.bubble = Mock()
        pet.chat_history, pet.session_messages, pet.display_log = [], [], []
        pet._turn_seq, pet._active_cancel_event = 0, None
        pet._ai_work_lock, pet._ai_work = threading.Lock(), {}
        pet.current_emotion = "默认"
        pet.set_emotion = Mock()
        pet.show_speech = Mock()
        pet.save_config = Mock()
        pet.frames = {"默认": []}
        pet.memory = {}
        pet.get_desktop_perception_snapshot = Mock(return_value={})
        pet.get_skills_block = Mock(return_value="")
        pet._vision_enabled = Mock(return_value=False)
        pet._get_active_tools = Mock(return_value=[])
        pet._tk_call = lambda fn, *args: fn(*args)
        pet._tk_call_for_turn = lambda turn, fn: (
            fn() if not pet._chat_cancelled(turn.cancel_event, turn.token) else None)
        pet.open_chat_window()
        # Offscreen but mapped, so Tk still performs real wrapping and layout.
        pet.chat_win.geometry(f"{pet._chat_w}x{pet._chat_h}+4000+4000")
        self.root.update()
        self.composer = pet.chat_composer

    def write(self, text):
        self.composer.text.delete("1.0", "end")
        self.composer.text.insert("1.0", text)
        self.root.update()

    def assert_composer_fits(self):
        pet = self.pet
        x, y, width, height = pet._chat_input_box
        self.assertGreaterEqual(y, pet._chat_img_h)
        self.assertLess(y + self.composer.input_height, pet._chat_h)
        self.assertGreater(self.composer.text.winfo_width(), 120)

    def test_newlines_wrap_overflow_and_clear_resize_the_real_window(self):
        initial = self.pet._chat_h
        self.write("第一行\n第二行\n第三行\n第四行")
        self.assertGreater(self.pet._chat_h, initial)
        self.assert_composer_fits()
        self.write("长文本自动换行 " * 220)
        self.assertEqual(self.composer.itemcget(self.composer._scroll_window, "state"), "normal")
        self.composer.text.yview_moveto(1.0)
        self.root.update()
        self.assertAlmostEqual(self.composer.text.yview()[1], 1.0)
        self.assert_composer_fits()
        self.write("")
        self.assertEqual(self.pet._chat_h, initial)
        self.assertLessEqual(self.composer.input_height, 30)
        self.assertEqual(self.composer.itemcget(self.composer._scroll_window, "state"), "hidden")

    def test_send_preserves_newlines_and_stop_preserves_the_next_draft(self):
        self.write("第一段\n第二段")
        with patch("main.threading.Thread") as worker:
            self.composer._submit()
        worker.return_value.start.assert_called_once()
        self.assertEqual(self.pet.chat_history[-1]["content"], "第一段\n第二段")
        self.assertEqual(self.pet.chat_canvas.itemcget(self.pet._win_chat_stop, "state"), "normal")
        self.write("下一条消息\n尚未发送")
        self.composer._submit()
        self.assertEqual(len(self.pet.chat_history), 1)
        self.pet.chat_stop_button.invoke()
        self.assertTrue(self.pet._active_cancel_event.is_set())
        self.assertEqual(self.pet.chat_canvas.itemcget(self.pet._win_chat_stop, "state"), "hidden")
        self.assertEqual(self.composer.text.get("1.0", "end-1c"), "下一条消息\n尚未发送")
        self.pet._on_turn_cancelled(self.pet._turn_seq)
        self.assertFalse(self.composer.busy)

    def test_real_keyboard_bindings_newline_send_and_tab(self):
        self.composer.text.focus_force()
        self.write("草稿")
        self.composer.text.mark_set("insert", "end-1c")
        self.composer.text.event_generate("<Shift-Return>")
        self.root.update()
        self.assertEqual(self.composer.text.get("1.0", "end-1c"), "草稿\n")
        with patch("main.threading.Thread"):
            self.composer.text.event_generate("<Return>")
            self.root.update()
        self.assertEqual(self.pet.chat_history[-1]["content"], "草稿")
        self.composer.text.event_generate("<Tab>")
        self.root.update()
        self.assertNotEqual(self.root.focus_get(), self.composer.text)
        self.assertEqual(self.composer.text.get("1.0", "end-1c"), "")

    def test_success_error_and_cancel_hide_stop_control(self):
        import main
        for result in ("回复完成", RuntimeError("test failure"), main.TaskCancelled()):
            with self.subTest(result=result):
                self.write("测试消息")
                with patch("main.threading.Thread") as worker:
                    self.pet.send_chat_message()
                if isinstance(result, Exception):
                    self.pet._chat_complete_loop = Mock(side_effect=result)
                else:
                    self.pet._chat_complete_loop = Mock(return_value=(result, None))
                with patch("main.format_perception_prompt_block", return_value=""), \
                        patch("main.build_prompt_with_memory", return_value="system"):
                    worker.call_args.kwargs["target"]()
                self.assertFalse(self.composer.busy)
                self.assertIsNone(self.pet._active_cancel_event)
                self.assertEqual(self.pet.chat_canvas.itemcget(self.pet._win_chat_stop, "state"), "hidden")

    def test_reopen_busy_window_and_ignore_old_cancellation(self):
        self.pet._turn_seq = 2
        active = self.pet._active_cancel_event = threading.Event()
        self.pet.on_close_chat_window()
        self.root.update()
        self.pet._sync_chat_action()
        self.pet.open_chat_window()
        self.root.update()
        self.assertTrue(self.pet.chat_composer.busy)
        self.assertEqual(self.pet.chat_canvas.itemcget(self.pet._win_chat_stop, "state"), "normal")
        self.pet._on_turn_cancelled(1)
        self.assertIs(self.pet._active_cancel_event, active)
        self.assertTrue(self.pet.chat_composer.busy)

    def test_history_single_line_entry_can_still_send(self):
        history_entry = tk.Entry(self.root)
        history_entry.insert(0, "继续历史对话")
        with patch("main.threading.Thread"):
            self.pet.send_chat_message(history_entry)
        self.assertEqual(history_entry.get(), "")
        self.assertEqual(self.pet.chat_history[-1]["content"], "继续历史对话")
        self.assertTrue(self.composer.busy)

    def test_narrow_resize_does_not_persist_temporary_input_growth(self):
        from pet_config import validate_config
        self.write("多行草稿\n" * 5)
        self.pet._chat_rs = (0, 0, self.pet._chat_w, self.pet._chat_h)
        self.pet._chat_resize_motion(Mock(x_root=-300, y_root=0))
        self.root.update()
        self.pet._chat_resize_release(None)
        validate_config(self.pet.config)
        base = self.pet.config["chat_size"]["h"]
        self.assertLess(base, self.pet._chat_h)
        self.assert_composer_fits()
        self.write("")
        self.assertEqual(self.pet._chat_h, base)

    def test_history_control_is_above_the_compact_input_and_opens_the_log(self):
        cv = self.pet.chat_canvas
        hx, hy = cv.coords(self.pet._win_chat_history)
        ix, iy, width, height = self.pet._chat_input_box
        self.assertGreater(hx, self.pet._chat_w * .8)
        self.assertLess(hy, iy)
        self.assertLess(width, self.pet._chat_w * .7)
        self.assertGreater(hy, self.pet._chat_img_h * .2)
        banner = self.pet._chat_renderer.banner(self.pet._chat_w)
        self.assertGreater(banner.getpixel((round(hx), round(hy)))[3], 240)
        self.assertFalse(any(isinstance(child, tk.Button) for child in self.composer.winfo_children()))
        self.pet.chat_history_button.invoke()
        self.root.update()
        self.assertTrue(self.pet.hist_win.winfo_exists())

    def test_old_tall_footer_size_is_reset_but_new_manual_size_is_kept(self):
        self.pet.on_close_chat_window()
        self.pet.config["chat_size"] = {"w": 740, "h": 600}
        self.pet.open_chat_window()
        self.root.update()
        self.assertLess(self.pet._chat_h, 330)
        self.pet.on_close_chat_window()
        self.pet.config["chat_size"] = {"w": 740, "h": 400}
        self.pet.config["chat_input_layout"] = "compact"
        self.pet.open_chat_window()
        self.root.update()
        self.assertEqual(self.pet._chat_h, 400)

    def test_native_alpha_keeps_soft_edges_and_input_stays_opaque(self):
        import main
        pet = self.pet
        self.assertIsNotNone(pet._chat_alpha_win)
        self.assertEqual(pet._chat_alpha_win.hwnd, main.toplevel_hwnd(pet.chat_win))
        self.assertFalse(pet.chat_win.attributes("-transparentcolor"))
        frame = pet._chat_alpha_win._frame
        alpha = frame.getchannel("A")
        self.assertGreater(sum(alpha.histogram()[1:255]), 1000)
        self.assertEqual(frame.getpixel((pet._chat_w-2, pet._chat_h-2))[3], 0)
        # Transparent artwork pixels retain their original coverage, without a dark matte.
        banner = pet._chat_renderer.banner(pet._chat_w)
        sample = next((x, y) for y in range(45) for x in range(80)
                      if 20 < banner.getpixel((x, y))[3] < 230)
        self.assertEqual(frame.getpixel(sample), banner.getpixel(sample))
        pet.chat_win.focus_force()
        self.root.update()
        unfocused = float(pet.chat_input_win.attributes("-alpha"))
        pet.entry_input.focus_force()
        self.root.update()
        focused = float(pet.chat_input_win.attributes("-alpha"))
        self.assertEqual(unfocused, 1.0)
        self.assertEqual(focused, 1.0)

    def test_input_is_not_an_owned_popup_so_one_click_activates_it(self):
        # Regression: wm transient on an override-redirect toplevel makes
        # Windows activate the owner instead of the input, so the first click
        # never reached the caret and the user had to click the bubble first.
        from alpha_window import toplevel_hwnd, _get_long, GWL_EXSTYLE
        pet = self.pet
        self.assertEqual(str(pet.root.tk.call("wm", "transient", pet.chat_input_win)), "")
        ex = _get_long(toplevel_hwnd(pet.chat_input_win), GWL_EXSTYLE) & 0xFFFFFFFF
        self.assertFalse(ex & 0x08000000)  # WS_EX_NOACTIVATE
        pet.chat_win.focus_force()
        self.root.update()
        pet._focus_chat_input()
        self.root.update()
        self.assertEqual(self.root.focus_get(), pet.entry_input)

    def test_bubble_click_re_raises_the_input_above_it(self):
        import ctypes
        from alpha_window import user32, toplevel_hwnd, POINT
        pet = self.pet
        pet.chat_win.geometry(f"{pet._chat_w}x{pet._chat_h}+200+200")
        self.root.update()
        user32.WindowFromPoint.argtypes = [POINT]
        user32.WindowFromPoint.restype = ctypes.c_void_p
        pet.chat_win.lift()
        pet._raise_chat_input()
        self.root.update()
        self.root.update_idletasks()
        entry = pet.entry_input
        point = POINT(entry.winfo_rootx() + 20, entry.winfo_rooty() + 8)
        self.assertEqual(user32.GetAncestor(user32.WindowFromPoint(point), 2),
                         toplevel_hwnd(pet.chat_input_win))

    def test_mapped_input_stays_above_an_ordinary_window(self):
        import ctypes
        from alpha_window import user32, toplevel_hwnd, _get_long, GWL_EXSTYLE, POINT
        pet = self.pet
        pet.chat_win.geometry(f"{pet._chat_w}x{pet._chat_h}+200+200")
        self.root.update()
        other = tk.Toplevel(self.root)
        self.addCleanup(other.destroy)
        other.geometry("900x600+180+180")
        self.root.update()
        user32.WindowFromPoint.argtypes = [POINT]
        user32.WindowFromPoint.restype = ctypes.c_void_p
        for _ in range(2):
            other.lift()
            other.focus_force()
            self.root.update()
            for win in (pet.chat_win, pet.chat_input_win):
                self.assertTrue(_get_long(toplevel_hwnd(win), GWL_EXSTYLE) & 8)
            entry = pet.entry_input
            point = POINT(entry.winfo_rootx()+20, entry.winfo_rooty()+8)
            self.assertEqual(user32.GetAncestor(user32.WindowFromPoint(point), 2),
                             toplevel_hwnd(pet.chat_input_win))
            self.assertEqual(self.root.focus_get(), other)  # no focus stealing
            pet.chat_win.withdraw()
            self.root.update()
            pet.chat_win.deiconify()
            self.root.update()

    def test_dragging_tuft_resizes_from_top_left_and_input_follows(self):
        pet = self.pet
        pet.chat_win.geometry(f"{pet._chat_w}x{pet._chat_h}+400+300")
        self.root.update()
        x0, y0, x1, y1 = pet._chat_tuft_box
        cx, cy = (x0+x1)//2, (y0+y1)//2
        rx, ry = pet.chat_win.winfo_x()+cx, pet.chat_win.winfo_y()+cy
        width, height = pet._chat_w, pet._chat_h
        opposite = (pet.chat_win.winfo_x()+width, pet.chat_win.winfo_y()+height)
        pet.chat_canvas.event_generate("<ButtonPress-1>", x=cx, y=cy, rootx=rx, rooty=ry)
        self.assertIsNotNone(pet._chat_rs)
        pet.chat_canvas.event_generate("<B1-Motion>", x=cx-80, y=cy-40, rootx=rx-80, rooty=ry-40)
        self.root.update()
        pet.chat_canvas.event_generate("<ButtonRelease-1>", x=cx, y=cy)
        self.root.update()
        self.assertGreater(pet._chat_w, width)
        self.assertGreater(pet._chat_h, height)
        self.assertIsNone(pet._chat_rs)
        self.assertEqual((pet.chat_win.winfo_x()+pet._chat_w, pet.chat_win.winfo_y()+pet._chat_h), opposite)
        ix, iy, iw, ih = pet._chat_input_box
        self.assertEqual(pet.chat_input_win.winfo_x(), pet.chat_win.winfo_x()+ix)
        self.assertEqual(pet.chat_input_win.winfo_y(), pet.chat_win.winfo_y()+iy)
        self.assertEqual((pet.chat_input_win.winfo_width(), pet.chat_input_win.winfo_height()), (iw, ih))
        self.assertEqual(len(pet.chat_canvas.find_withtag("resize_hand")), 1)
        self.assertEqual(pet.chat_canvas.itemcget("resize_hand", "fill"), "")
        self.assertEqual(pet.chat_canvas.itemcget("resize_hand", "outline"), "")

    def test_input_hides_and_reappears_with_the_bubble(self):
        self.pet.chat_win.withdraw()
        self.root.update()
        self.assertFalse(self.pet.chat_input_win.winfo_ismapped())
        self.pet.chat_win.deiconify()
        self.root.update()
        self.assertTrue(self.pet.chat_input_win.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
