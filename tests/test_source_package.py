import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("package_source", Path(__file__).parents[1] / "tools/package_source.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class SourcePackageTests(unittest.TestCase):
    def test_archive_contains_source_and_manifest_without_runtime_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {"src/main.py": "print('hello')", "data/config.example.json": '{"api_key":""}',
                     "config.json": "private", "memory.json": "private", "action_log.json": "private",
                     "resources/assets/pet.png": "asset", "src/pet_tools/__init__.py": "", "src/pet_tools/__pycache__/x.pyc": "cache",
                     "tools/package_source.py": "# source", "tools/_debug.py": "debug", "resources/skills/example/.env": "secret",
                     "resources/skills/example/SKILL.md": "# skill", "build/stale.py": "stale", "dist/pet.exe": "binary", "data/config.json": "private", "tools/.build/cache.py": "cache"}
            for name, text in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            output = root / "release/source.zip"
            result = packaging.package_source(root, output)
            with zipfile.ZipFile(output) as archive:
                names = {name.split("/", 1)[1] for name in archive.namelist()}
            self.assertEqual(names, {"src/main.py", "data/config.example.json", "resources/assets/pet.png", "src/pet_tools/__init__.py",
                                     "tools/package_source.py", "resources/skills/example/SKILL.md", "SOURCE_MANIFEST.json"})
            self.assertEqual(result["files"], 6)
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                packaging.package_source(root, output)
            self.assertEqual(output.read_bytes(), original)

    def test_example_credentials_cannot_enter_a_source_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "data").mkdir()
            (root / "src/main.py").write_text("", encoding="utf-8")
            (root / "data/config.example.json").write_text(json.dumps({"api_key": "sample-secret"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                packaging.package_source(root, root / "source.zip")
            self.assertFalse((root / "source.zip").exists())


if __name__ == "__main__":
    unittest.main()
