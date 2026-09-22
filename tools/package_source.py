"""Build a source-only ZIP with a manifest, without local credentials or state."""
import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "requirements.txt", "启动桌宠.bat", ".gitignore",
              "data/config.example.json", "data/README.md"}
SOURCE_DIRS = {"src", "resources", "tests", "tools", "docs"}
EXCLUDED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache", "_skills_backup", ".build"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}


def source_files(root):
    root = root.resolve()
    candidates = [root / name for name in ROOT_FILES if (root / name).is_file()]
    for name in sorted(SOURCE_DIRS):
        folder = root / name
        if folder.is_dir():
            candidates.extend(folder.rglob("*"))
    selected = []
    for path in candidates:
        relative = path.relative_to(root)
        if (not path.is_file() or path.is_symlink() or
                any(part in EXCLUDED_DIRS for part in relative.parts) or
                path.suffix.lower() in EXCLUDED_SUFFIXES or
                path.name == ".env" or path.name.startswith(".env.") or
                (relative.parts[0] == "tools" and path.name.startswith("_"))):
            continue
        # Refuse links/junctions that would collect files outside the project.
        if not path.resolve().is_relative_to(root):
            continue
        selected.append(path)
    return sorted(set(selected), key=lambda p: p.relative_to(root).as_posix())


def package_source(root=ROOT, output=None):
    root = Path(root).resolve()
    files = source_files(root)
    if not (root / "src" / "main.py").is_file() or not files:
        raise ValueError("源码目录缺少 src/main.py")
    # The example is part of the source; local runtime config is never included.
    example = root / "data" / "config.example.json"
    if example.exists() and json.loads(example.read_text(encoding="utf-8-sig")).get("api_key"):
        raise ValueError("config.example.json 的 api_key 必须留空")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(output) if output else root / "release" / f"虹语织-桌宠v3-源码-{stamp}.zip"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    archive_root = "虹语织-桌宠v3-源码"
    manifest = {"format": 1, "created_at": datetime.now().isoformat(timespec="seconds"), "files": []}
    # Exclusive creation prevents overwriting any prior release.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            archive.writestr(f"{archive_root}/{relative}", data)
            manifest["files"].append({"path": relative, "size": len(data),
                                       "sha256": hashlib.sha256(data).hexdigest()})
        archive.writestr(f"{archive_root}/SOURCE_MANIFEST.json",
                         json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    with zipfile.ZipFile(output) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"压缩包校验失败：{bad_file}")
        names = {name.removeprefix(archive_root + "/") for name in archive.namelist()}
        for forbidden in ("config.json", "memory.json", "action_log.json"):
            if forbidden in names or "data/" + forbidden in names:
                raise ValueError(f"源码包误包含运行数据：{forbidden}")
        for item in manifest["files"]:
            data = archive.read(f"{archive_root}/{item['path']}")
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(f"源码哈希不匹配：{item['path']}")
    return {"path": str(output), "files": len(files), "size_bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New ZIP path; an existing file is never overwritten")
    args = parser.parse_args()
    print(json.dumps(package_source(output=args.output), ensure_ascii=False, indent=2))
