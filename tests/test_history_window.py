"""Conversation-record regression tests.

Two things are locked down here:

1. 清空记录 must really reset the model context. The history window's 🧹 button
   used to empty only ``display_log`` (the view) while ``chat_history`` — the
   turns actually sent to the model — survived, so 织织 kept "remembering" a
   conversation the user had just cleared.
2. The rewritten record window (pet_chat_history) regroups the flat display_log
   into blocks and renders / filters them.
"""
import os
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pet_chat_history as hist

WIN32 = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Pure regrouping helpers (no Tk, runs everywhere)
# ---------------------------------------------------------------------------

class HistoryBlockTests(unittest.TestCase):
    def test_header_plus_body_becomes_one_message_block(self):
        blocks = hist.build_blocks([
            {"tag": "user", "text": "人: ", "ts": 1.0},
            {"tag": "msg", "text": "你好呀\n\n", "ts": 1.0},
            {"tag": "bot", "text": "虹语织: ", "ts": 2.0},
            {"tag": "msg", "text": "在的！(〃'▽'〃)\n\n", "ts": 2.0},
        ])
        self.assertEqual([b["kind"] for b in blocks], ["message", "message"])
        self.assertFalse(blocks[0]["pet"])
        self.assertEqual(blocks[0]["head"], "人")
        self.assertEqual(blocks[0]["ts"], 1.0)
        self.assertTrue(blocks[1]["pet"])
        # the log writes the full name; the window shows 织织
        self.assertEqual(blocks[1]["head"], "织织")
        self.assertEqual(hist.body_of(blocks[1]), "在的！(〃'▽'〃)")

    def test_tool_lines_collapse_into_a_single_card(self):
        blocks = hist.build_blocks([
            {"tag": "tool", "text": "[织织自主调用工具: run_command] ls\n"},
            {"tag": "tool", "text": "[织织自主调用工具: write_text_file] 写入 a.txt（3 字符）\n"},
        ])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["kind"], "tool")
        self.assertEqual(len(hist.body_of(blocks[0]).split("\n")), 2)

    def test_consecutive_system_notes_merge(self):
        blocks = hist.build_blocks([
            {"tag": "sys", "text": "系统提示: "},
            {"tag": "sys", "text": "上下文快满了\n\n"},
        ])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(hist.body_of(blocks[0]), "系统提示: 上下文快满了")

    def test_a_body_without_a_header_still_renders(self):
        blocks = hist.build_blocks([{"tag": "msg", "text": "孤儿消息"}])
        self.assertEqual(blocks[0]["kind"], "message")
        self.assertTrue(blocks[0]["pet"])

    def test_blank_entries_are_ignored(self):
        self.assertEqual(hist.build_blocks([{"tag": "tool", "text": "  "},
                                            {"tag": "sys", "text": "\n"}]), [])

    def test_filter_and_counts(self):
        blocks = hist.build_blocks([
            {"tag": "user", "text": "人: "}, {"tag": "msg", "text": "番茄炒蛋怎么做"},
            {"tag": "tool", "text": "[织织自主调用工具: web_search] 番茄炒蛋\n"},
            {"tag": "sys", "text": "系统: 已清空\n"},
        ])
        self.assertEqual(len(hist.filter_blocks(blocks, "chat")), 1)
        self.assertEqual(len(hist.filter_blocks(blocks, "tool")), 1)
        self.assertEqual(len(hist.filter_blocks(blocks, "sys")), 1)
        self.assertEqual(len(hist.filter_blocks(blocks, "all")), 3)
        self.assertEqual(len(hist.filter_blocks(blocks, "all", "番茄")), 2)
        self.assertEqual(hist.count_blocks(blocks),
                         {"all": 3, "chat": 1, "tool": 1, "sys": 1})

    def test_tool_prefix_is_rewritten_for_display(self):
        self.assertEqual(
            hist.pretty_tool_line("[织织自主调用工具: run_command] 运行 ls"),
            "run_command · 运行 ls")
        self.assertEqual(hist.pretty_tool_line("[织织自主调用工具: run_command]"),
                         "run_command")
        self.assertEqual(hist.pretty_tool_line("  → 执行指令: ls"), "→ 执行指令: ls")

    def test_block_to_text_round_trips_a_message(self):
        block = {"kind": "message", "pet": True, "head": "织织", "body": "晚上好\n\n"}
        self.assertEqual(hist.block_to_text(block), "织织：晚上好")


# ---------------------------------------------------------------------------
# Shared pet fixture
# ---------------------------------------------------------------------------

def build_pet(root):
    """A DesktopPet skeleton with just the state the record window touches."""
    import main
    pet = main.DesktopPet.__new__(main.DesktopPet)
    pet.root = root
    pet.dpi_scale = 1.0
    pet.app_icon = None
    pet.fam_main = "Microsoft YaHei UI"
    for name, size in (("f_title", 12), ("f_ui", 10), ("f_ui_bold", 10),
                       ("f_small", 9)):
        setattr(pet, name, tkfont.Font(root, family="Microsoft YaHei UI",
                                       size=size))
    pet._hist_fonts = None
    pet._hist_window = None
    pet.hist_win = None
    pet.hist_entry = None
    pet._turn_seq = 5
    pet._active_cancel_event = None
    pet._sync_chat_action = Mock()
    pet.show_dialog_line = Mock()
    pet.show_speech = Mock()
    return pet


def seed_session(pet):
    pet.chat_history = [{"role": "user", "content": "帮我查天气"},
                        {"role": "assistant", "content": "晴，26 度"}]
    pet.session_messages = [{"user": "帮我查天气", "bot": "晴，26 度"}]
    pet.display_log = [{"text": "人: ", "tag": "user", "ts": 1.0},
                       {"text": "帮我查天气\n\n", "tag": "msg", "ts": 1.0}]
    pet.memory = {"user_profile": {"favorability": 100},
                  "long_term_memories": ["主人喜欢番茄炒蛋"]}


# ---------------------------------------------------------------------------
# Real Tk: the clear semantics
# ---------------------------------------------------------------------------

@unittest.skipUnless(WIN32, "The desktop UI uses Win32")
class ConversationResetTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        main.enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.pet = build_pet(self.root)

    def test_reset_really_drops_the_model_context(self):
        """The heart of the bug report: clearing must empty chat_history."""
        seed_session(self.pet)
        done = self.pet.reset_conversation_context(announce=False)
        self.assertTrue(done["context"])
        self.assertEqual(self.pet.chat_history, [])
        self.assertEqual(self.pet.session_messages, [])
        self.assertEqual(done["turns"], 1)
        # the view is empty except for the single system notice
        self.assertEqual([e["tag"] for e in self.pet.display_log], ["sys"])

    def test_reset_invalidates_an_in_flight_turn(self):
        seed_session(self.pet)
        event = threading.Event()
        self.pet._active_cancel_event = event
        self.pet.reset_conversation_context(announce=False)
        self.assertTrue(event.is_set())
        self.assertIsNone(self.pet._active_cancel_event)
        # the superseded turn (old token) must drop its late reply...
        self.assertTrue(self.pet._chat_cancelled(None, 5))
        # ...while an unset event on the current token is still allowed through
        self.assertFalse(self.pet._chat_cancelled(threading.Event(),
                                                  self.pet._turn_seq))
        self.pet._sync_chat_action.assert_called()

    def test_long_term_memory_survives_a_plain_reset(self):
        seed_session(self.pet)
        self.pet.reset_conversation_context(announce=False)
        self.assertEqual(self.pet.memory["long_term_memories"], ["主人喜欢番茄炒蛋"])
        self.assertEqual(self.pet.memory["user_profile"]["favorability"], 100)

    def test_optional_wipe_also_resets_the_memory_archive(self):
        seed_session(self.pet)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memory.json")
            Path(path).write_text('{"user_profile": {"favorability": 100}}',
                                  encoding="utf-8")
            with patch.object(self.main, "MEMORY_FILE", path):
                done = self.pet.reset_conversation_context(wipe_memory=True,
                                                           announce=False)
                self.assertFalse(os.path.exists(path))
                # the archive came back in its pristine "we just met" state
                self.assertEqual(self.pet.memory["user_profile"]["favorability"],
                                 85)
                self.assertNotIn("主人喜欢番茄炒蛋",
                                 self.pet.memory["long_term_memories"])
        self.assertTrue(done["memory"])

    def test_clearing_only_the_view_keeps_the_context(self):
        seed_session(self.pet)
        done = self.pet.reset_conversation_context(wipe_view=True,
                                                   wipe_context=False,
                                                   announce=False)
        self.assertFalse(done["context"])
        self.assertEqual(len(self.pet.chat_history), 2)
        self.assertEqual([e["tag"] for e in self.pet.display_log], ["sys"])

    def test_clear_memory_still_forgets_the_session(self):
        seed_session(self.pet)
        self.pet.clear_memory()
        self.assertEqual(self.pet.chat_history, [])
        self.assertEqual(self.pet.memory["long_term_memories"], ["主人喜欢番茄炒蛋"])
        self.pet.show_speech.assert_called()

    def test_history_window_clear_button_clears_the_context(self):
        """End-to-end: one click on 🧹 must clear chat_history, with no prompt."""
        seed_session(self.pet)
        # no dialog may appear: nothing is stubbed for one
        self.pet._clear_history_log()
        self.assertEqual(self.pet.chat_history, [])
        self.assertEqual(self.pet.session_messages, [])
        self.assertEqual([e["tag"] for e in self.pet.display_log], ["sys"])
        # the long-term archive is a separate file and stays untouched
        self.assertEqual(self.pet.memory["long_term_memories"], ["主人喜欢番茄炒蛋"])
        self.assertEqual(self.pet.memory["user_profile"]["favorability"], 100)

    def test_history_window_clear_never_touches_the_memory_file(self):
        seed_session(self.pet)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memory.json")
            Path(path).write_text('{"user_profile": {"favorability": 100}}',
                                  encoding="utf-8")
            with patch.object(self.main, "MEMORY_FILE", path):
                self.pet._clear_history_log()
                self.assertTrue(os.path.exists(path))
        self.assertEqual(self.pet.chat_history, [])

    def test_hist_write_stamps_time_and_feeds_an_open_window(self):
        seed_session(self.pet)
        feed = Mock()
        self.pet._hist_window = Mock(alive=lambda: True, append=feed)
        self.pet._hist_write("你好\n", "msg")
        entry = self.pet.display_log[-1]
        self.assertGreater(entry["ts"], 0)
        feed.assert_called_once_with(entry)


# ---------------------------------------------------------------------------
# Real Tk: the rewritten record window
# ---------------------------------------------------------------------------

@unittest.skipUnless(WIN32, "The desktop UI uses Win32")
class HistoryWindowTests(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        main.enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.pet = build_pet(self.root)
        self.pet.display_log = []
        self.pet.chat_history = []
        self.pet.session_messages = []
        self.pet.memory = {"long_term_memories": ["a", "b"]}
        self.pet.open_history_window()
        self.root.update()
        self.win = self.pet._hist_window
        self.assertIsNotNone(self.win)
        self.assertIsNotNone(self.pet.hist_win)
        self.assertIs(self.pet.hist_entry, self.win.entry)
        self.addCleanup(self.pet._on_close_history)

    def feed(self):
        pet = self.pet
        pet._hist_write("人: ", "user")
        pet._hist_write("帮我看看对话记录界面好不好看\n\n", "msg")
        pet._hist_write("虹语织: ", "bot")
        pet._hist_write("安排上啦！(〃'▽'〃)\n\n", "msg")
        pet._hist_write("[织织自主调用工具: read_file_contents] 读取 src/main.py\n", "tool")
        pet._hist_write("系统: 对话临时上下文已清空（长期记忆档案仍保留）！\n\n", "sys")
        self.win._render()
        self.root.update()

    def kinds(self):
        return [b["kind"] for b in self.win._visible]

    def test_window_opens_with_a_live_session_summary(self):
        self.feed()
        text = self.win.subtitle.cget("text")
        self.assertIn("上下文", text)
        self.assertIn("长期记忆 2 条", text)

    def test_blocks_render_as_bubbles_cards_and_pills(self):
        self.feed()
        self.assertEqual(self.kinds(), ["message", "message", "tool", "sys"])
        canvas = self.win.canvas
        fills = {canvas.itemcget(i, "fill")
                 for i in canvas.find_all() if canvas.type(i) == "polygon"}
        for key in ("hist_user_bubble", "hist_pet_bubble", "hist_tool_card",
                    "hist_sys_pill"):
            self.assertIn(self.main.PAL[key], fills)
        # every drawn hit region maps back to a block (used by right-click copy)
        self.assertEqual(len(self.win._hits), len(self.win._visible))

    def test_nothing_overflows_the_canvas(self):
        """Long tool commands wrap inside the card instead of spilling sideways."""
        self.pet._hist_write(
            "[织织自主调用工具: edit_text_file] 修改 src/main.py: 把 “display_log = []” "
            "替换为 “reset_conversation_context()”，这么长的一行工具日志也不会溢出卡片边界。\n",
            "tool")
        self.win._render()
        self.root.update()
        canvas = self.win.canvas
        limit = canvas.winfo_width()
        for item in canvas.find_all():
            box = canvas.bbox(item)
            if box:
                self.assertLessEqual(box[2], limit, f"item overflows: {box}")
                self.assertGreaterEqual(box[0], 0)

    def test_filter_chips_narrow_the_transcript(self):
        self.feed()
        self.win.set_filter("tool")
        self.win._render()
        self.assertEqual(self.kinds(), ["tool"])
        self.win.set_filter("chat")
        self.win._render()
        self.assertEqual(self.kinds(), ["message", "message"])
        self.win.set_filter("all")
        self.win._render()
        self.assertEqual(len(self.win._visible), 4)

    def test_search_filters_and_reports_matches(self):
        self.feed()
        self.win._search_ph.hide()
        self.win.search.insert(0, "好看")
        self.win._on_search_key()
        self.win._render()
        self.assertEqual(self.kinds(), ["message"])
        self.assertIn("匹配 1 条", self.win._count_label.cget("text"))
        self.win._clear_search()
        self.win._render()
        self.assertEqual(len(self.win._visible), 4)

    def test_empty_transcript_shows_a_friendly_empty_state(self):
        self.win._render()           # first paint after the geometry settled
        self.root.update()
        self.assertEqual(self.win._visible, [])
        texts = [self.win.canvas.itemcget(i, "text")
                 for i in self.win.canvas.find_all()
                 if self.win.canvas.type(i) == "text"]
        self.assertTrue(any("还没有对话记录" in t for t in texts), texts)
        self.assertIsNone(self.win.scrollbar.winfo_manager() or None)

    def test_composer_ignores_the_placeholder_and_forwards_real_input(self):
        sent = []
        self.win.on_send = lambda: sent.append(self.win.entry.get())
        self.win.submit()                       # placeholder still showing
        self.assertEqual(sent, [])
        self.win._entry_ph.hide()
        self.win.entry.insert(0, "在吗")
        self.win.submit()
        self.assertEqual(sent, ["在吗"])

    def test_new_entries_stream_into_the_open_window(self):
        self.feed()
        before = len(self.win._blocks)
        self.pet._hist_write("虹语织: ", "bot")
        self.pet._hist_write("又聊了一句\n\n", "msg")
        self.win._render()
        self.assertEqual(len(self.win._blocks), before + 1)
        self.assertEqual(self.win._visible[-1]["body"].strip(), "又聊了一句")

    def test_closing_the_window_detaches_it_from_the_pet(self):
        win = self.win
        self.pet._on_close_history()
        self.assertFalse(win.alive())
        self.assertIsNone(self.pet.hist_win)
        self.assertIsNone(self.pet.hist_entry)
        self.assertIsNone(self.pet._hist_window)

    def test_history_button_refocuses_the_existing_window(self):
        first = self.pet._hist_window
        self.pet.open_history_window()
        self.root.update()
        self.assertIs(self.pet._hist_window, first)


if __name__ == "__main__":
    unittest.main()
