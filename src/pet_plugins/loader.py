# -*- coding: utf-8 -*-
"""插件发现与加载。

支持的目录形态（plugins 文件夹内）：

    plugins/
    ├── 我的工具.py              ← 单文件插件（直接就是一个 .py）
    ├── 你好插件/                 ← 文件夹插件（推荐，可带自己的模块与资源）
    │   ├── plugin.py            ← 入口（或 __init__.py）
    │   ├── helper.py            ← 插件自己的模块，可用相对导入
    │   └── assets/...
    └── _examples/               ← 下划线开头的目录/文件一律跳过（放示例）

约定：以下划线或点开头的文件/文件夹不加载，方便用户把示例、备份、
未完成的插件放在同一目录里而不被自动执行。
"""
import importlib.util
import os
import re
import sys
import threading
from dataclasses import dataclass, field

MODULE_PREFIX = "nijikori_plugin_"
PACKAGE_ENTRY_FILES = ("plugin.py", "__init__.py")
_IMPORT_LOCK = threading.RLock()
_UNSAFE = re.compile(r"[^0-9A-Za-z_]")


@dataclass
class PluginCandidate:
    """一个待加载的插件。"""
    name: str
    path: str            # 单文件插件的 .py 路径，或文件夹插件的目录
    entry_file: str      # 真正 import 的入口文件
    is_package: bool
    digest: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def module_name(self):
        return MODULE_PREFIX + _UNSAFE.sub("_", self.name)

    @property
    def search_dir(self):
        """导入时临时加入 sys.path 的目录（让插件能 import 同目录的模块）。"""
        return os.path.dirname(self.path) if not self.is_package else os.path.dirname(self.path)


def _visible(name):
    return bool(name) and not name.startswith(("_", "."))


def discover(plugins_dir):
    """扫描插件目录，返回按名称排序的候选列表（不导入、不执行）。"""
    root = os.path.abspath(str(plugins_dir))
    found = []
    if not os.path.isdir(root):
        return found
    try:
        entries = sorted(os.listdir(root), key=lambda s: s.lower())
    except OSError:
        return found
    for entry in entries:
        if not _visible(entry):
            continue
        full = os.path.join(root, entry)
        if os.path.isfile(full):
            if not entry.lower().endswith(".py") or entry.lower() == "__init__.py":
                continue
            found.append(PluginCandidate(name=os.path.splitext(entry)[0], path=full,
                                         entry_file=full, is_package=False))
            continue
        if not os.path.isdir(full):
            continue
        for candidate_entry in PACKAGE_ENTRY_FILES:
            entry_file = os.path.join(full, candidate_entry)
            if os.path.isfile(entry_file):
                found.append(PluginCandidate(name=entry, path=full, entry_file=entry_file,
                                             is_package=True))
                break
    return found


def load_module(candidate):
    """按文件路径导入插件模块，返回 module（同时登记进 sys.modules）。"""
    entry_file = os.path.abspath(candidate.entry_file)
    if not os.path.isfile(entry_file):
        raise FileNotFoundError(entry_file)
    module_name = candidate.module_name
    with _IMPORT_LOCK:
        if candidate.is_package:
            spec = importlib.util.spec_from_file_location(
                module_name, entry_file,
                submodule_search_locations=[os.path.dirname(entry_file)])
        else:
            spec = importlib.util.spec_from_file_location(module_name, entry_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法为插件创建导入规格: {entry_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        search_dir = candidate.search_dir
        inserted = search_dir not in sys.path
        if inserted:
            sys.path.insert(0, search_dir)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # 导入失败不留半成品，避免下次 import 命中残缺模块。
            unload_module(candidate)
            raise
        finally:
            if inserted:
                try:
                    sys.path.remove(search_dir)
                except ValueError:
                    pass
        return module


def unload_module(candidate):
    """从 sys.modules 移除插件模块及其子模块，返回移除数量。"""
    module_name = candidate.module_name if isinstance(candidate, PluginCandidate) else str(candidate)
    with _IMPORT_LOCK:
        names = [n for n in sys.modules
                 if n == module_name or n.startswith(module_name + ".")]
        for name in names:
            sys.modules.pop(name, None)
        return len(names)


def prune_sys_path(directory):
    """把某个目录从 sys.path 中彻底清掉（插件卸载后的收尾）。"""
    directory = os.path.abspath(str(directory))
    removed = 0
    with _IMPORT_LOCK:
        for item in list(sys.path):
            try:
                if item and os.path.abspath(item) == directory:
                    sys.path.remove(item)
                    removed += 1
            except (OSError, ValueError):
                continue
    return removed
