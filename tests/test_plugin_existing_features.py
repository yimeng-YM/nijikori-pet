"""插件修改已有页面与提示词的最小回归测试。"""
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pet_plugins.api import PluginAPI
from pet_plugins.manager import PluginError, PluginHost, PluginManager


class ExistingFeatureTests(unittest.TestCase):
    def setUp(self):
        self.manager = PluginManager()
        self.first = self._api("first")
        self.second = self._api("second")

    def _api(self, name):
        candidate = SimpleNamespace(name=name, path=__file__, is_package=False,
                                    entry_file=__file__)
        api = PluginAPI(self.manager, candidate)
        self.manager.records[name] = SimpleNamespace(api=api)
        return api

    def test_builtin_page_can_be_extended_and_restored(self):
        rendered = []

        def extend(page, api, original):
            original()
            rendered.append(api.name)

        self.first.modify_control_center_page("api", extend)
        self.manager.render_control_center_page("api", None,
                                                lambda page: rendered.append("original"))
        self.assertEqual(rendered, ["original", "first"])
        self.manager._unregister("first")
        rendered.clear()
        self.manager.render_control_center_page("api", None,
                                                lambda page: rendered.append("original"))
        self.assertEqual(rendered, ["original"])

    def test_page_error_falls_back_once(self):
        rendered = []

        def broken(page, api, original):
            raise RuntimeError("bad plugin")

        self.first.modify_control_center_page("api", broken)
        self.manager.render_control_center_page("api", None,
                                                lambda page: rendered.append("original"))
        self.assertEqual(rendered, ["original"])
        with self.assertRaises(PluginError):
            self.first.modify_control_center_page("missing", broken)
        with self.assertRaises(PluginError):
            self.first.add_control_center_page("bad", lambda page, api: None,
                                               key="api")

    def test_prompt_update_is_scoped_to_own_plugin(self):
        self.first.add_prompt_block("old", key="editable")
        self.second.add_prompt_block("other", key="editable")
        self.first.add_prompt_block("new", key="editable")
        self.assertEqual(self.manager.prompt_blocks(), ["other", "new"])
        self.assertTrue(self.first.remove_prompt_block("editable"))
        self.assertEqual(self.manager.prompt_blocks(), ["other"])
        self.assertFalse(self.first.remove_prompt_block("editable"))

    def test_persona_uses_host_config_and_rejects_empty_text(self):
        config = {"system_prompt": "原人设"}
        self.manager.host = PluginHost(
            get_config=lambda key, default: config.get(key, default),
            set_config=lambda key, value: config.__setitem__(key, value) or True)
        self.assertEqual(self.first.get_persona(), "原人设")
        self.assertTrue(self.first.set_persona("新人设"))
        self.assertEqual(config["system_prompt"], "新人设")
        with self.assertRaises(ValueError):
            self.first.set_persona("  ")

    def test_new_example_is_seeded_into_existing_examples_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            templates = root / "templates"
            examples = root / "plugins" / "_examples"
            templates.mkdir()
            examples.mkdir(parents=True)
            (templates / "example_persona.py").write_text("new", encoding="utf-8")
            (examples / "example_old.py").write_text("user edit", encoding="utf-8")
            self.manager.plugins_dir = str(root / "plugins")
            self.manager.host = PluginHost(templates_dir=str(templates))
            self.manager.ensure_plugins_dir()
            self.assertEqual((examples / "example_persona.py").read_text(encoding="utf-8"), "new")
            self.assertEqual((examples / "example_old.py").read_text(encoding="utf-8"), "user edit")

    def test_example_tool_persists_injection_across_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugins = root / "plugins"
            plugins.mkdir()
            source = Path(__file__).resolve().parents[1] / "resources" / "plugins" / "example_persona.py"
            shutil.copy2(source, plugins / "example_persona.py")
            config = {"plugin_trust_required": False, "system_prompt": "原人设"}
            manager = PluginManager()
            manager.attach(PluginHost(
                plugins_dir=str(plugins), data_dir=str(root / "data"),
                templates_dir="", tools_list=[], tool_categories={},
                vision_only_tools=set(), emotions=[], text_bearing_emotions=set(),
                get_config=lambda key, default: config.get(key, default),
                set_config=lambda key, value: config.__setitem__(key, value) or True))
            self.assertEqual(manager.load_all()["loaded"], ["example_persona"])
            result = manager.dispatch("manage_persona_prompt",
                                      {"action": "set_injection", "text": "补充设定"}, None)
            self.assertEqual(result["status"], "success")
            self.assertEqual(manager.prompt_blocks(), ["补充设定"])
            self.assertEqual(manager.dispatch("manage_persona_prompt",
                                              {"action": "set_persona", "text": "新人设"}, None)["status"],
                             "success")
            self.assertEqual(config["system_prompt"], "新人设")
            manager.reload()
            self.assertEqual(manager.prompt_blocks(), ["补充设定"])
            manager.disable_all()
            self.assertEqual(manager.prompt_blocks(), [])


if __name__ == "__main__":
    unittest.main()
