# -*- coding: utf-8 -*-
"""插件系统（pet_plugins）回归测试：发现 / 信任确认 / 注册 / 接管 / 重载。

全部在无 GUI 环境下运行：用一个假的 PluginHost 代替桌宠本体，
只验证插件系统的行为契约（工具表、分发、提示词、状态、回滚）。
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pet_plugins import PluginHost, PluginManager, path_digest  # noqa: E402
from pet_plugins.loader import discover  # noqa: E402
from pet_plugins.trust import TrustStore  # noqa: E402

BUILTIN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "builtin_tool",
        "description": "内置工具",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def make_host(root, plugins_dir, templates_dir=None):
    """构造一个最小可用的假宿主（工具表/分类/表情表都是真的可变对象）。"""
    tools = [dict(BUILTIN_SCHEMA)]
    categories = {"builtin_tool": "内置"}
    vision = {"read_image"}
    emotions = [("默认", "默认.png", "元气满满")]
    config = {}

    host = PluginHost(
        tools_list=tools,
        tool_categories=categories,
        vision_only_tools=vision,
        emotions=emotions,
        text_bearing_emotions=set(),
        plugins_dir=str(plugins_dir),
        templates_dir=str(templates_dir or ""),
        data_dir=str(root / "data"),
        app_dir=str(root),
        app_version="test",
        get_config=lambda key=None, default=None: config.get(key, default),
        set_config=lambda key, value: config.__setitem__(key, value) or True,
        read_skill=lambda name: None,
        list_skills=lambda: [],
    )
    os.makedirs(host.data_dir, exist_ok=True)
    os.makedirs(host.plugins_dir, exist_ok=True)
    manager = PluginManager()
    manager.attach(host)
    return manager, host, tools, categories, vision, emotions, config


def write_plugin(plugins_dir, name, body, as_package=False):
    """写一个插件到插件目录，返回入口文件路径。"""
    source = textwrap.dedent(body).strip() + "\n"
    if as_package:
        folder = Path(plugins_dir) / name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "plugin.py"
    else:
        path = Path(plugins_dir) / f"{name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


TOOL_PLUGIN = """
    def register(api):
        api.register_tool("plugin_echo", {
            "name": "plugin_echo",
            "description": "回声工具",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, handler, category="插件")
        api.add_prompt_block("插件注入的段落")

    def handler(args, pet):
        return {"status": "success", "echo": args.get("text", "")}
"""


class PluginDiscoveryTests(unittest.TestCase):
    def test_finds_single_file_and_package_and_skips_underscore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            plugins.mkdir()
            write_plugin(plugins, "single", TOOL_PLUGIN)
            write_plugin(plugins, "packed", TOOL_PLUGIN, as_package=True)
            write_plugin(plugins, "_draft", TOOL_PLUGIN)
            (plugins / "_examples").mkdir()
            write_plugin(plugins / "_examples", "sample", TOOL_PLUGIN)
            (plugins / "notes.txt").write_text("not a plugin", encoding="utf-8")

            names = sorted(c.name for c in discover(plugins))
            self.assertEqual(names, ["packed", "single"])
            packed = next(c for c in discover(plugins) if c.name == "packed")
            self.assertTrue(packed.is_package)

    def test_digest_changes_when_plugin_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_plugin(directory, "p", TOOL_PLUGIN)
            first = path_digest(path)
            path.write_text(path.read_text(encoding="utf-8") + "\n# tweak\n", encoding="utf-8")
            self.assertNotEqual(first, path_digest(path))


class PluginTrustTests(unittest.TestCase):
    def test_new_plugin_requires_confirmation_and_is_remembered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            write_plugin(plugins, "echo", TOOL_PLUGIN)
            manager, host, tools, _cats, _vision, _emo, _cfg = make_host(root, plugins)

            asked = []

            def confirm(pending):
                asked.append([p["name"] for p in pending])
                return ["echo"]

            summary = manager.load_all(confirm=confirm)
            self.assertEqual(summary["loaded"], ["echo"])
            self.assertEqual(asked, [["echo"]])
            self.assertTrue(any(t["function"]["name"] == "plugin_echo" for t in tools))

            # 第二次：已确认过 → 不再询问
            asked.clear()
            manager.unload_all()
            summary = manager.load_all(confirm=confirm)
            self.assertEqual(summary["loaded"], ["echo"])
            self.assertEqual(asked, [])

    def test_declined_plugin_is_not_loaded_and_not_asked_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            write_plugin(plugins, "echo", TOOL_PLUGIN)
            manager, host, tools, _c, _v, _e, _cfg = make_host(root, plugins)

            manager.load_all(confirm=lambda pending: [])
            self.assertEqual(manager.records["echo"].status, "denied")
            self.assertFalse(any(t["function"]["name"] == "plugin_echo" for t in tools))

            calls = []
            manager.load_all(confirm=lambda pending: calls.append(pending) or [])
            self.assertEqual(calls, [], "被拒绝过的插件不应再次询问")

    def test_changed_plugin_is_asked_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            path = write_plugin(plugins, "echo", TOOL_PLUGIN)
            manager, _h, _t, _c, _v, _e, _cfg = make_host(root, plugins)
            manager.load_all(confirm=lambda pending: ["echo"])
            manager.unload_all()

            path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            pending_seen = []
            manager.load_all(confirm=lambda pending: pending_seen.append(
                [(p["name"], p["status"]) for p in pending]) or ["echo"])
            self.assertEqual(pending_seen, [[("echo", "changed")]])

    def test_trust_can_be_disabled_in_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            write_plugin(plugins, "echo", TOOL_PLUGIN)
            manager, _h, tools, _c, _v, _e, config = make_host(root, plugins)
            config["plugin_trust_required"] = False
            summary = manager.load_all(confirm=lambda pending: [])
            self.assertEqual(summary["loaded"], ["echo"])
            self.assertTrue(any(t["function"]["name"] == "plugin_echo" for t in tools))

    def test_enable_plugins_false_loads_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            write_plugin(plugins, "echo", TOOL_PLUGIN)
            manager, _h, tools, _c, _v, _e, config = make_host(root, plugins)
            config["enable_plugins"] = False
            summary = manager.load_all(confirm=lambda pending: ["echo"])
            self.assertTrue(summary.get("disabled"))
            self.assertEqual(len(tools), 1)

    def test_trust_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TrustStore(directory)
            self.assertEqual(store.status("p", "sha256:x"), "new")
            store.decide("p", "sha256:x", True)
            self.assertEqual(store.status("p", "sha256:x"), "trusted")
            store.decide("p", "sha256:x", False)
            self.assertEqual(store.status("p", "sha256:x"), "denied")
            self.assertEqual(TrustStore(directory).status("p", "sha256:x"), "denied")


class PluginRegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.plugins = self.root / "plugins"
        self.manager, self.host, self.tools, self.cats, self.vision, self.emotions, self.cfg = \
            make_host(self.root, self.plugins)

    def tearDown(self):
        self.manager.unload_all()
        self._tmp.cleanup()

    def _load(self, name, body, **kwargs):
        write_plugin(self.plugins, name, body, **kwargs)
        return self.manager.load_all(confirm=lambda pending: [p["name"] for p in pending])

    def test_new_tool_is_registered_with_schema_and_category(self):
        self._load("echo", TOOL_PLUGIN)
        schema = next(t for t in self.tools if t["function"]["name"] == "plugin_echo")
        self.assertEqual(schema["function"]["description"], "回声工具")
        self.assertEqual(self.cats["plugin_echo"], "插件")
        self.assertEqual(self.manager.prompt_blocks(None), ["插件注入的段落"])

    def test_dispatch_calls_plugin_handler(self):
        self._load("echo", TOOL_PLUGIN)
        result = self.manager.dispatch("plugin_echo", {"text": "hi"}, None)
        self.assertEqual(result, {"status": "success", "echo": "hi"})
        self.assertIsNone(self.manager.dispatch("builtin_tool", {}, None))

    def test_handler_exception_becomes_error_result(self):
        self._load("boom", """
            def register(api):
                api.register_tool("boom_tool", {
                    "name": "boom_tool", "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                }, handler)

            def handler(args, pet):
                raise RuntimeError("炸了")
        """)
        result = self.manager.dispatch("boom_tool", {}, None)
        self.assertEqual(result["status"], "error")
        self.assertIn("炸了", result["message"])

    def test_override_builtin_tool_can_call_original(self):
        self._load("takeover", """
            def register(api):
                api.override_tool("builtin_tool", handler)

            def handler(args, pet, call_original):
                original = call_original()
                original["patched"] = True
                return original
        """)
        seen = {}

        def original():
            seen["called"] = True
            return {"status": "success", "from": "builtin"}

        result = self.manager.dispatch("builtin_tool", {}, None, call_original=original)
        self.assertTrue(seen.get("called"))
        self.assertTrue(result["patched"])
        # 接管不改变原 schema，也不重复插入工具表
        self.assertEqual(sum(t["function"]["name"] == "builtin_tool" for t in self.tools), 1)

    def test_override_can_replace_schema_and_restores_on_unload(self):
        original = dict(BUILTIN_SCHEMA["function"])
        self._load("takeover", """
            def register(api):
                api.override_tool("builtin_tool", handler)
                api.register_tool("builtin_tool", {
                    "name": "builtin_tool",
                    "description": "被插件改写过的内置工具",
                    "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
                }, handler, override=True)

            def handler(args, pet, call_original=None):
                return {"status": "success"}
        """)
        patched = next(t for t in self.tools if t["function"]["name"] == "builtin_tool")
        self.assertEqual(patched["function"]["description"], "被插件改写过的内置工具")
        self.manager.unload_all()
        self.manager._restore_baseline()
        restored = next(t for t in self.tools if t["function"]["name"] == "builtin_tool")
        self.assertEqual(restored["function"], original)

    def test_duplicate_tool_name_without_override_is_rejected(self):
        summary = self._load("dup", """
            def register(api):
                api.register_tool("builtin_tool", {
                    "name": "builtin_tool", "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                }, handler)

            def handler(args, pet):
                return {"status": "success"}
        """)
        self.assertEqual(summary["failed"], ["dup"])
        self.assertIn("已存在", self.manager.records["dup"].error)

    def test_failing_plugin_is_rolled_back_completely(self):
        summary = self._load("halfway", """
            def register(api):
                api.register_tool("half_tool", {
                    "name": "half_tool", "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                }, handler, category="插件")
                api.add_prompt_block("半途而废")
                api.add_menu_item("半途", lambda pet: None)
                api.on("startup", lambda pet: None)
                raise ValueError("注册到一半失败")

            def handler(args, pet):
                return {"status": "success"}
        """)
        self.assertEqual(summary["failed"], ["halfway"])
        self.assertFalse(any(t["function"]["name"] == "half_tool" for t in self.tools))
        self.assertNotIn("half_tool", self.cats)
        self.assertEqual(self.manager.prompt_blocks(None), [])
        self.assertEqual(self.manager.menu_items(), [])
        self.assertEqual(self.manager.hooks.callbacks("startup"), [])
        self.assertIsNone(self.manager.dispatch("half_tool", {}, None))

    def test_wrap_tool_before_short_circuit_and_after_rewrite(self):
        self._load("wrap", """
            def register(api):
                api.wrap_tool("builtin_tool", before=before, after=after)

            def before(args, pet):
                if args.get("block"):
                    return {"status": "error", "message": "被 before 拦下"}
                return None

            def after(args, pet, result):
                result["wrapped"] = True
                return result
        """)
        blocked = self.manager.run_before_tool("builtin_tool", {"block": True}, None)
        self.assertEqual(blocked["message"], "被 before 拦下")
        self.assertIsNone(self.manager.run_before_tool("builtin_tool", {}, None))
        rewritten = self.manager.run_after_tool("builtin_tool", {}, {"status": "success"}, None)
        self.assertTrue(rewritten["wrapped"])

    def test_wildcard_wrapper_applies_to_every_tool(self):
        self._load("wrapall", """
            def register(api):
                api.wrap_tool("*", after=after)

            def after(args, pet, result):
                result["seen"] = True
                return result
        """)
        result = self.manager.run_after_tool("anything", {}, {"status": "success"}, None)
        self.assertTrue(result["seen"])

    def test_prompt_block_when_filter_and_callable(self):
        self._load("prompt", """
            def register(api):
                api.add_prompt_block(lambda pet: "动态段落", when=lambda pet: bool(getattr(pet, "flag", False)))
        """)
        self.assertEqual(self.manager.prompt_blocks(None), [])

        class FakePet:
            flag = True

        self.assertEqual(self.manager.prompt_blocks(FakePet()), ["动态段落"])

    def test_plugin_state_persists_between_loads(self):
        self._load("stateful", """
            def register(api):
                api.state.setdefault("count", 0)
                api.state["count"] += 1
                api.save_state()
        """)
        self.assertEqual(self.manager.load_state("stateful")["count"], 1)
        self.manager.unload_all()
        self.manager.load_all(confirm=lambda pending: [p["name"] for p in pending])
        self.assertEqual(self.manager.load_state("stateful")["count"], 2)

    def test_emotion_registration_uses_absolute_path(self):
        self._load("emo", """
            def register(api):
                api.register_emotion("插件表情", "face.png", description="来自插件")
        """, as_package=True)
        # 图片不存在 → 加载失败（可读错误），不会污染表情表
        self.assertEqual(self.manager.records["emo"].status, "failed")
        self.assertIn("表情图片不存在", self.manager.records["emo"].error)
        self.assertEqual(len(self.emotions), 1)

    def test_emotion_registration_succeeds_with_real_file(self):
        folder = self.plugins / "emo"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "face.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (folder / "plugin.py").write_text(textwrap.dedent("""
            def register(api):
                api.register_emotion("插件表情", "face.png", description="来自插件")
        """).strip() + "\n", encoding="utf-8")
        self.manager.load_all(confirm=lambda pending: [p["name"] for p in pending])
        self.assertEqual(self.manager.records["emo"].status, "loaded")
        self.assertEqual(self.emotions[-1][0], "插件表情")
        self.assertTrue(os.path.isabs(self.emotions[-1][1]))
        self.assertEqual(self.manager.emotion_sprite("插件表情"), self.emotions[-1][1])

    def test_custom_action_is_dispatched(self):
        self._load("act", """
            def register(api):
                api.register_action("plugin_wave", run, description="挥手")

            def run(pet, intensity):
                pet.done = intensity
        """)

        class FakePet:
            done = None

        pet = FakePet()
        self.assertTrue(self.manager.run_action("plugin_wave", pet, "strong"))
        self.assertEqual(pet.done, "strong")
        self.assertFalse(self.manager.run_action("nope", pet))
        self.assertEqual(self.manager.action_names(), ["plugin_wave"])

    def test_reload_is_idempotent_and_restores_baseline(self):
        self._load("echo", TOOL_PLUGIN)
        self._load("wrap", """
            def register(api):
                api.wrap_tool("builtin_tool", after=lambda a, p, r: r)
        """)
        before = len(self.tools)
        summary = self.manager.reload(confirm=lambda pending: [p["name"] for p in pending])
        self.assertEqual(sorted(summary["loaded"]), ["echo", "wrap"])
        self.assertEqual(len(self.tools), before)
        self.assertEqual(sum(t["function"]["name"] == "plugin_echo" for t in self.tools), 1)
        self.assertEqual(len(self.manager.prompt_blocks(None)), 1)

    def test_disable_and_enable_one_plugin(self):
        self._load("echo", TOOL_PLUGIN)
        self.assertEqual(self.manager.set_plugin_enabled("echo", False)["status"], "success")
        self.assertFalse(any(t["function"]["name"] == "plugin_echo" for t in self.tools))
        self.assertEqual(self.manager.set_plugin_enabled("echo", True)["status"], "success")
        self.assertTrue(any(t["function"]["name"] == "plugin_echo" for t in self.tools))

    def test_examples_are_seeded_and_can_be_enabled(self):
        templates = self.root / "templates"
        write_plugin(templates, "example_demo", TOOL_PLUGIN)
        self.host.templates_dir = str(templates)
        self.manager.ensure_plugins_dir()
        seeded = self.plugins / "_examples" / "example_demo.py"
        self.assertTrue(seeded.is_file())
        # 示例放在 _examples/ 下不会被自动加载
        self.assertEqual(discover(self.plugins), [])
        copied = self.manager.enable_examples()
        self.assertEqual(copied, ["example_demo.py"])
        self.assertEqual([c.name for c in discover(self.plugins)], ["example_demo"])

    def test_status_reports_plugin_surface(self):
        self._load("echo", TOOL_PLUGIN)
        status = self.manager.status()
        self.assertEqual(status["tools"], ["plugin_echo"])
        self.assertEqual(status["prompt_blocks"], 1)
        self.assertEqual([p["name"] for p in status["plugins"]], ["echo"])
        self.assertEqual(status["plugins"][0]["status"], "loaded")


class PluginPathTests(unittest.TestCase):
    def test_plugins_dir_follows_program_dir_in_both_layouts(self):
        from pet_paths import resolve_app_paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = resolve_app_paths(source_file=root / "src/main.py", frozen=False)
            self.assertEqual(source.plugins_dir, root / "plugins")
            self.assertEqual(source.plugin_templates_dir, root / "resources/plugins")
            self.assertEqual(source.plugin_state_dir, root / "data/plugin_state")

            frozen = resolve_app_paths(executable=root / "dist/pet.exe",
                                       bundle_dir=root / "bundle", frozen=True)
            self.assertEqual(frozen.plugins_dir, root / "dist/plugins")
            self.assertEqual(frozen.plugin_templates_dir, root / "bundle/plugins")
            # 冻结版 data_dir 就是 exe 目录：状态目录不能和插件目录重合
            self.assertEqual(frozen.plugin_state_dir, root / "dist/plugin_state")
            self.assertNotEqual(frozen.plugin_state_dir, frozen.plugins_dir)


class MainIntegrationTests(unittest.TestCase):
    """main.py 侧的接线：工具表、分发入口、提示词。"""

    @classmethod
    def setUpClass(cls):
        import main  # 与 test_app_paths 一样：导入主程序模块本身
        cls.main = main
        # 这一组测试操作的是模块级单例：把插件日志重定向到临时文件，
        # 避免污染本机真实的 data/plugins.log
        cls._log_dir = tempfile.TemporaryDirectory()
        cls._log_backup = getattr(main._PLUGINS, "_log_path", "")
        main._PLUGINS._log_path = str(Path(cls._log_dir.name) / "plugins.log")

    @classmethod
    def tearDownClass(cls):
        cls.main._PLUGINS._log_path = cls._log_backup
        cls._log_dir.cleanup()

    def test_manage_plugins_tool_is_exposed(self):
        main = self.main
        schema = main.pet_tool_schema("manage_plugins")
        self.assertIsNotNone(schema)
        self.assertEqual(main.TOOL_CATEGORIES["manage_plugins"], "记忆与技能")
        self.assertIn("manage_plugins", main.WORK_LOG_TOOLS)

    def test_plugin_dir_matches_app_paths(self):
        from pet_paths import PATHS
        self.assertEqual(self.main.PLUGINS_DIR, str(PATHS.plugins_dir))

    def test_plugin_guide_is_injected_into_prompt(self):
        prompt = self.main.build_prompt_with_memory(
            "基础人设", {"user_profile": {}}, skills_block=None)
        self.assertIn("插件系统（Plugins）", prompt)
        self.assertIn(self.main.PLUGINS_DIR, prompt)

    def test_plugin_tool_reaches_active_tools_and_dispatch(self):
        main = self.main
        manager = main._PLUGINS
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = write_plugin(tmp.name, "it_plugin", """
            def register(api):
                api.register_tool("plugin_it_tool", {
                    "name": "plugin_it_tool",
                    "description": "集成测试工具",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }, handler, category="插件测试")
                api.override_tool("get_current_time", takeover)

            def handler(args, pet):
                return {"status": "success", "from": "plugin"}

            def takeover(args, pet, call_original):
                return {"status": "success", "from": "plugin-override"}
        """)
        candidate = next(c for c in discover(tmp.name) if c.name == "it_plugin")
        candidate.digest = path_digest(candidate.path)
        record = manager._load_one(candidate)
        self.addCleanup(lambda: (manager.unload_one("it_plugin"),
                                 manager._restore_baseline()))
        self.assertEqual(record.status, "loaded")

        pet = main.DesktopPet.__new__(main.DesktopPet)
        pet.config = {}
        names = [t["function"]["name"] for t in pet._get_active_tools()]
        self.assertIn("plugin_it_tool", names)
        self.assertIn("plugin_it_tool", [t["function"]["name"] for t in main.PET_TOOLS])

        # 新工具与"接管内置工具"都从 _dispatch_tool_call 走插件
        self.assertEqual(pet._dispatch_tool_call("plugin_it_tool", {}),
                         {"status": "success", "from": "plugin"})
        self.assertEqual(pet._dispatch_tool_call("get_current_time", {}),
                         {"status": "success", "from": "plugin-override"})

    def test_plugin_error_does_not_break_dispatch(self):
        main = self.main
        manager = main._PLUGINS
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        write_plugin(tmp.name, "broken_it", """
            def register(api):
                api.register_tool("plugin_broken_tool", {
                    "name": "plugin_broken_tool", "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                }, handler)

            def handler(args, pet):
                raise RuntimeError("故意炸")
        """)
        candidate = next(c for c in discover(tmp.name) if c.name == "broken_it")
        candidate.digest = path_digest(candidate.path)
        manager._load_one(candidate)
        self.addCleanup(lambda: (manager.unload_one("broken_it"),
                                 manager._restore_baseline()))
        pet = main.DesktopPet.__new__(main.DesktopPet)
        pet.config = {}
        result = pet._dispatch_tool_call("plugin_broken_tool", {})
        self.assertEqual(result["status"], "error")
        # 内置工具不受影响
        self.assertEqual(pet._dispatch_tool_call("unknown_tool_name", {}),
                         {"status": "unknown_tool", "name": "unknown_tool_name"})

    def test_source_layout_end_to_end_with_real_host(self):
        """端到端：真实宿主接线（PET_TOOLS / 提示词 / 分发）跑通一个插件。

        插件目录与信任库都指向临时位置，绝不碰项目里的 plugins/ 与 data/。
        """
        main = self.main
        manager = main._PLUGINS
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        plugins = Path(tmp.name) / "plugins"
        write_plugin(plugins, "e2e_plugin", """
            def register(api):
                api.register_tool("plugin_e2e", {
                    "name": "plugin_e2e",
                    "description": "端到端测试工具",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }, handler, category="插件测试")
                api.add_prompt_block("E2E-PLUGIN-BLOCK")

            def handler(args, pet):
                return {"status": "success", "from": "e2e"}
        """)

        original_dir = manager.plugins_dir
        original_trust = manager.trust
        manager.plugins_dir = str(plugins)
        manager.trust = TrustStore(str(Path(tmp.name) / "data"))
        self.addCleanup(lambda: (manager.unload_all(), manager._restore_baseline(),
                                 setattr(manager, "plugins_dir", original_dir),
                                 setattr(manager, "trust", original_trust),
                                 manager._notify_tools_changed()))

        # 第一次加载必须经过确认回调
        asked = []
        summary = manager.load_all(confirm=lambda pending: (
            asked.extend(p["name"] for p in pending) or ["e2e_plugin"]))
        self.assertEqual(asked, ["e2e_plugin"])
        self.assertEqual(summary["loaded"], ["e2e_plugin"])
        self.assertIn("plugin_e2e", [t["function"]["name"] for t in main.PET_TOOLS])

        # 提示词里能看到插件段落
        prompt = main.build_prompt_with_memory(
            "基础人设", {"user_profile": {}}, skills_block=None)
        self.assertIn("E2E-PLUGIN-BLOCK", prompt)

        # 模型可见 + 分发到插件
        pet = main.DesktopPet.__new__(main.DesktopPet)
        pet.config = {}
        self.assertIn("plugin_e2e", [t["function"]["name"] for t in pet._get_active_tools()])
        self.assertEqual(pet._dispatch_tool_call("plugin_e2e", {}),
                         {"status": "success", "from": "e2e"})

        # 卸载后工具表回到基线（不留残留）
        manager.unload_all()
        manager._restore_baseline()
        self.assertNotIn("plugin_e2e", [t["function"]["name"] for t in main.PET_TOOLS])

    def test_emotion_catalog_refresh_updates_tool_enum(self):
        main = self.main
        emotions_before = list(main.EMOTIONS)
        main.EMOTIONS.append(("测试表情", "测试表情.png", "临时"))
        try:
            pet = main.DesktopPet.__new__(main.DesktopPet)
            pet._refresh_emotion_tool_enum()
            enum = main.pet_tool_schema("change_pet_emotion")["parameters"]["properties"]["emotion"]["enum"]
            self.assertIn("测试表情", enum)
        finally:
            main.EMOTIONS[:] = emotions_before
            pet = main.DesktopPet.__new__(main.DesktopPet)
            pet._refresh_emotion_tool_enum()


if __name__ == "__main__":
    unittest.main()
