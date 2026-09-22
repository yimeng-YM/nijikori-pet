import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pet_paths import PATHS, prepare_data_dir, resolve_app_paths


class AppPathTests(unittest.TestCase):
    def test_source_paths_are_relative_to_project_not_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = resolve_app_paths(source_file=root / "src/main.py", frozen=False)
            self.assertEqual(paths.app_dir, root)
            self.assertEqual(paths.data_dir, root / "data")
            self.assertEqual(paths.assets_dir, root / "resources/assets")
            self.assertEqual(paths.prompt_file, root / "resources/prompt.txt")
            self.assertEqual(paths.skills_dir, root / "resources/skills")
            self.assertEqual(paths.entry_file, root / "src/main.py")

    def test_frozen_exe_keeps_portable_data_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = resolve_app_paths(executable=root / "dist/pet.exe", bundle_dir=root / "bundle", frozen=True)
            self.assertEqual(paths.data_dir, root / "dist")
            self.assertEqual(paths.assets_dir, root / "bundle/assets")
            self.assertEqual(paths.skills_dir, root / "dist/skills")
            self.assertEqual(prepare_data_dir(paths), [])

    def test_old_source_data_moves_without_changing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = resolve_app_paths(source_file=root / "src/main.py", frozen=False)
            original = {'config.json': b'{"model":"custom"}', 'memory.json': b'{"note":"saved"}',
                        'action_log.json': b'[]'}
            for name, contents in original.items():
                (root / name).write_bytes(contents)
            self.assertEqual(len(prepare_data_dir(paths)), 3)
            for name, contents in original.items():
                self.assertEqual((root / "data" / name).read_bytes(), contents)
                self.assertFalse((root / name).exists())
            self.assertEqual(prepare_data_dir(paths), [])

    def test_migration_conflict_leaves_all_originals_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = resolve_app_paths(source_file=root / "src/main.py", frozen=False)
            paths.data_dir.mkdir()
            (root / "config.json").write_text("old config", encoding="utf-8")
            (root / "memory.json").write_text("old memory", encoding="utf-8")
            (paths.data_dir / "memory.json").write_text("new memory", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                prepare_data_dir(paths)
            self.assertEqual((root / "config.json").read_text(), "old config")
            self.assertEqual((root / "memory.json").read_text(), "old memory")
            self.assertEqual((paths.data_dir / "memory.json").read_text(), "new memory")

    def test_shipped_assets_prompt_and_skills_are_available(self):
        self.assertTrue(PATHS.entry_file.is_file())
        self.assertTrue((PATHS.assets_dir / "layered/manifest.json").is_file())
        self.assertIn("虹语织", PATHS.prompt_file.read_text(encoding="utf-8"))
        self.assertTrue((PATHS.skills_dir / "配置文件管理/SKILL.md").is_file())

    def test_layered_renderer_loads_relocated_assets_and_draws_visible_frame(self):
        from layered_pet import LayeredPetRenderer
        frame = LayeredPetRenderer(180).tick()
        self.assertEqual(frame.mode, "RGBA")
        self.assertEqual(frame.size, (180, 180))
        self.assertIsNotNone(frame.getchannel("A").getbbox())

    @unittest.skipUnless(sys.platform == "win32", "Desktop restart uses Win32")
    def test_restart_uses_new_entry_and_project_working_directory(self):
        import main
        pet = main.DesktopPet.__new__(main.DesktopPet)
        with patch.object(main.sys, "frozen", False, create=True), patch("subprocess.Popen") as popen, \
                patch.object(pet, "quit_pet") as quit_pet:
            pet.restart_pet()
        self.assertEqual(popen.call_args.args[0], [sys.executable, "-B", str(PATHS.entry_file)])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(PATHS.app_dir))
        quit_pet.assert_called_once()


if __name__ == "__main__":
    unittest.main()
