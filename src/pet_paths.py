"""Resolve app resources and persistent data independently of the working directory."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    app_dir: Path
    resource_dir: Path
    data_dir: Path
    skills_dir: Path
    entry_file: Path

    @property
    def assets_dir(self):
        return self.resource_dir / "assets"

    @property
    def prompt_file(self):
        return self.resource_dir / "prompt.txt"


def resolve_app_paths(*, source_file=None, executable=None, bundle_dir=None, frozen=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        exe = Path(executable or sys.executable).resolve()
        resources = Path(bundle_dir or sys._MEIPASS).resolve()
        return AppPaths(exe.parent, resources, exe.parent, exe.parent / "skills", exe)
    source = Path(source_file or __file__).resolve().parent
    project = source.parent
    return AppPaths(project, project / "resources", project / "data",
                    project / "resources" / "skills", source / "main.py")


def prepare_data_dir(paths):
    """Migrate the former source layout at startup; never overwrite existing data."""
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    if paths.data_dir == paths.app_dir:
        return []  # EXE keeps its existing portable data layout.
    planned = []
    for name in ("config.json", "memory.json", "action_log.json"):
        old = paths.app_dir / name
        new = paths.data_dir / name
        if old.is_file():
            if new.exists():
                raise FileExistsError(f"数据迁移存在同名文件，请先核对：{old} 与 {new}")
            planned.append((old, new))
    for old, new in planned:
        os.rename(old, new)
    return [str(new) for _, new in planned]


PATHS = resolve_app_paths()
