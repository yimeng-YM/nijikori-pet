# -*- coding: utf-8 -*-
"""虹语织桌宠 · 代码编辑与增强工具包 (pet_tools)。

以注册表方式向 main.py 提供代码编辑与增强工具：
- fs.py      : glob_files / grep_files / edit_lines
- shell.py   : start_background_command / read_background_output / stop_background_job
- harness.py : delegate_to_harness

所有 handler 签名: handler(args: dict, ctx) -> dict
ctx 为桌宠主程序 DesktopPet 实例（提供 config / save_config /
_confirm_tool_action / show_speech / _tk_call / _execute_skills_management）。
工具 schema 通过 SCHEMAS 列表在 main.py 中并入 PET_TOOLS。
"""
import os
import pet_io as _io

# ---------------------------------------------------------------------------
# 注册表（必须先定义，子模块从本包 import register）
# ---------------------------------------------------------------------------
HANDLERS = {}
SCHEMAS = []


def register(name, function_schema):
    """把 handler 与 OpenAI function schema 一起登记进注册表。"""
    def deco(fn):
        HANDLERS[name] = fn
        SCHEMAS.append({"type": "function", "function": function_schema})
        return fn
    return deco


def get_handler(name):
    return HANDLERS.get(name)


# ---------------------------------------------------------------------------
# 共享助手
# ---------------------------------------------------------------------------
IGNORE_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vs", ".vscode", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".gradle", ".next", ".nuxt",
}

BINARY_EXTS = _io.BINARY_EXTS


def expand_path(path, ctx=None):
    """展开 ~ 与 %VAR% 并转为绝对路径。"""
    p = os.path.expanduser(os.path.expandvars(str(path or "")))
    return os.path.abspath(p)


def is_probably_binary(file_path):
    return _io.is_probably_binary(file_path)


def detect_encoding(file_path):
    try:
        return _io.detect_encoding(file_path), None
    except (OSError, UnicodeError, LookupError) as exc:
        return None, exc


def read_text_auto(file_path, max_bytes=_io.MAX_EDIT_BYTES, encoding="auto"):
    return _io.read_text_auto(file_path, max_bytes=max_bytes, encoding=encoding)


def backup_file(file_path):
    return _io.backup_file(file_path)


# 子模块最后导入（它们依赖上面的 register / 助手）
from pet_tools import fs as _fs          # noqa: E402,F401
from pet_tools import shell as _shell    # noqa: E402,F401
from pet_tools import harness as _harness  # noqa: E402,F401
