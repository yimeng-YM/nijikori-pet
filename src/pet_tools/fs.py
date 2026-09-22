# -*- coding: utf-8 -*-
"""文件查找与精准编辑工具：glob_files / grep_files / edit_lines。"""
import os
import re
import time
import fnmatch
from functools import lru_cache
import pet_io

from pet_tools import (
    register, expand_path,
    IGNORE_DIR_NAMES, backup_file,
)

GREP_MATCH_CAP = 250
GREP_FILE_CAP = 4000
GREP_TIME_BUDGET = 30.0
GLOB_FILE_CAP = 100


# ---------------------------------------------------------------------------
# glob_files
# ---------------------------------------------------------------------------
@register("glob_files", {
    "name": "glob_files",
    "description": "按通配模式查找文件路径（如 *.py、src/**/*.ts、**/*.json）。支持 ** 递归。结果按修改时间从新到旧排序（最多100条）。找代码文件、看项目里有哪些某类文件时用它；按文件内容搜索则用 grep_files。",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "通配模式，如 *.py 或 src/**/*.ts（** 表示任意层级子目录）"},
            "path": {"type": "string", "description": "可选：起始目录，默认当前活跃项目根目录（未设项目则为主目录）"},
        },
        "required": ["pattern"],
    },
})
def glob_files(args, ctx=None):
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return {"status": "error", "message": "缺少查找模式 pattern"}
    base = expand_path(args.get("path") or ".", ctx)
    if not os.path.isdir(base):
        return {"status": "error", "message": f"目录不存在: {base}"}
    normalized = pattern.replace("\\", "/")
    if os.path.isabs(pattern):
        normalized = os.path.relpath(pattern, base).replace("\\", "/")
    parts = tuple(p.lower() for p in normalized.split("/") if p not in ("", "."))
    if ".." in parts:
        return {"status": "error", "message": "pattern 不能越过搜索起始目录"}

    def matches(relative):
        names = tuple(relative.replace("\\", "/").lower().split("/"))
        @lru_cache(None)
        def visit(i, j):
            if i == len(parts):
                return j == len(names)
            if parts[i] == "**":
                return visit(i + 1, j) or (j < len(names) and visit(i, j + 1))
            return j < len(names) and fnmatch.fnmatchcase(names[j], parts[i]) and visit(i + 1, j + 1)
        return visit(0, 0)

    results = []
    recursive = "**" in parts
    for folder, dirs, files in os.walk(base):
        depth = len(os.path.relpath(folder, base).split(os.sep)) if folder != base else 0
        dirs[:] = [d for d in dirs if d not in IGNORE_DIR_NAMES and not d.startswith(".")]
        if not recursive and depth >= len(parts) - 1:
            dirs[:] = []
        for name in files:
            full = os.path.join(folder, name)
            if not matches(os.path.relpath(full, base)):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            results.append({"path": full, "size": st.st_size,
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                            "_mt": st.st_mtime_ns})
    results.sort(key=lambda item: (-item["_mt"], item["path"].lower()))
    truncated = len(results) > GLOB_FILE_CAP
    results = results[:GLOB_FILE_CAP]
    for item in results:
        item.pop("_mt")
    return {"status": "success", "base": base, "pattern": pattern,
            "count": len(results), "truncated": truncated, "files": results}


# ---------------------------------------------------------------------------
# grep_files
# ---------------------------------------------------------------------------
@register("grep_files", {
    "name": "grep_files",
    "description": "在文件内容中搜索正则表达式（类似 ripgrep）：返回匹配文件、行号与该行内容。是代码导航的核心工具——找函数定义、查引用、定位报错来源都用它。可用 include 按扩展名过滤（如 *.py）。跳过 .git/node_modules 等目录与二进制文件。",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式，如 def execute_tool_call 或 class DesktopPet"},
            "path": {"type": "string", "description": "可选：搜索的文件或目录，默认活跃项目根目录"},
            "include": {"type": "string", "description": "可选：文件名通配过滤，如 *.py、*.{js,ts} 只支持单层（写 *.py）"},
            "ignore_case": {"type": "boolean", "description": "可选：忽略大小写，默认 False（区分大小写）"},
        },
        "required": ["pattern"],
    },
})
def grep_files(args, ctx=None):
    pattern = str(args.get("pattern") or "")
    if not pattern.strip():
        return {"status": "error", "message": "缺少搜索正则 pattern"}
    try:
        flags = re.IGNORECASE if args.get("ignore_case") in (True, "true", "1", "yes") else 0
        rx = re.compile(pattern, flags)
    except re.error as e:
        return {"status": "error", "message": f"正则表达式无效: {e}"}

    base = expand_path(args.get("path") or ".", ctx)
    inc = str(args.get("include") or "").strip()

    if os.path.isfile(base):
        files = [base]
    elif os.path.isdir(base):
        files = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in IGNORE_DIR_NAMES and not d.startswith(".")]
            if inc:
                filenames = [f for f in filenames if fnmatch.fnmatch(f.lower(), inc.lower())]
            for f in filenames:
                files.append(os.path.join(dirpath, f))
                if len(files) >= GREP_FILE_CAP:
                    break
            if len(files) >= GREP_FILE_CAP:
                break
    else:
        return {"status": "error", "message": f"路径不存在: {base}"}

    started = time.time()
    matches = []
    files_scanned = 0
    truncated = False
    for fp in files:
        if len(matches) >= GREP_MATCH_CAP or time.time() - started > GREP_TIME_BUDGET:
            truncated = True
            break
        try:
            text, _, partial = pet_io.read_text_prefix(fp, max_bytes=2_000_000)
        except (OSError, ValueError, UnicodeError, LookupError):
            continue
        truncated = truncated or partial
        files_scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                matches.append({
                    "file": fp,
                    "line_number": i,
                    "line": line.strip()[:240],
                })
                if len(matches) >= GREP_MATCH_CAP:
                    truncated = True
                    break

    return {
        "status": "success",
        "pattern": pattern,
        "path": base,
        "files_scanned": files_scanned,
        "match_count": len(matches),
        "truncated": truncated,
        "matches": matches,
    }


# ---------------------------------------------------------------------------
# edit_lines
# ---------------------------------------------------------------------------
@register("edit_lines", {
    "name": "edit_lines",
    "description": "按行号精准编辑文件（配合带行号的 read_file_contents 使用）：replace=替换行区间、insert_before/insert_after=在某行前/后插入、delete=删除行区间。适合 old_string 难以唯一定位时的修改。编辑前自动备份，可随时找回。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对路径基于活跃项目根目录）"},
            "mode": {"type": "string", "enum": ["replace", "insert_before", "insert_after", "delete"],
                     "description": "replace=把 start_line~end_line 替换为 content；insert_before/insert_after=在 start_line 前/后插入 content；delete=删除 start_line~end_line"},
            "start_line": {"type": "integer", "description": "起始行号（1-based，基于 read_file_contents 显示的行号）"},
            "end_line": {"type": "integer", "description": "可选：结束行号（含），replace/delete 时默认与 start_line 相同"},
            "content": {"type": "string", "description": "replace/insert 模式的新内容（可多行）；delete 模式不需要"},
            "encoding": {"type": "string", "description": "可选：文件编码，默认自动探测（utf-8/gb18030）"},
        },
        "required": ["path", "mode", "start_line"],
    },
})
def edit_lines(args, ctx=None):
    path = expand_path(args.get("path"), ctx)
    mode = str(args.get("mode") or "replace").strip().lower()
    if mode not in ("replace", "insert_before", "insert_after", "delete"):
        return {"status": "error", "message": f"未知 mode: {mode}"}
    if not os.path.isfile(path):
        return {"status": "error", "message": f"文件不存在: {path}"}
    try:
        start = int(args.get("start_line") or 0)
    except Exception:
        start = 0
    try:
        end = int(args.get("end_line") or start)
    except Exception:
        end = start

    try:
        text, enc, original = pet_io.read_text_file(path, encoding=args.get("encoding") or "auto")
    except (OSError, ValueError, UnicodeError, LookupError) as exc:
        return {"status": "error", "message": f"读取失败: {exc}"}
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if start < 1 or start > total:
        return {"status": "error", "message": f"start_line 越界: {start}（文件共 {total} 行）"}
    if end < start:
        end = start
    if end > total:
        end = total

    content = args.get("content")
    content = "" if content is None else str(content)
    if mode != "delete" and not content.strip():
        return {"status": "error", "message": f"{mode} 模式需要提供 content"}

    # 统一换行风格：跟随被替换区域首行的行尾
    if mode in ("replace", "insert_before", "insert_after"):
        sample = lines[min(start, total) - 1]
        eol = "\r\n" if sample.endswith("\r\n") else ("\n" if sample.endswith("\n") else os.linesep)
        new_lines = [ln + eol for ln in content.splitlines()]
        if not content.splitlines():
            new_lines = [eol]

    backup = backup_file(path)
    if not backup:
        return {"status": "error", "message": "无法备份文件，已取消编辑"}

    if mode == "replace":
        lines[start - 1:end] = new_lines
        changed = (start, end)
    elif mode == "insert_before":
        lines[start - 1:start - 1] = new_lines
        changed = (start, start - 1)
    elif mode == "insert_after":
        if not lines[start - 1].endswith(("\n", "\r")):
            lines[start - 1] += eol
        lines[start:start] = new_lines
        changed = (start + 1, start)
    else:  # delete
        del lines[start - 1:end]
        changed = (start, end)

    try:
        pet_io.atomic_write_text(path, "".join(lines), enc, expected_bytes=original)
    except Exception as e:
        return {"status": "error", "message": f"写入失败: {e}"}

    return {
        "status": "success",
        "path": path,
        "mode": mode,
        "affected_lines": {"from": changed[0], "to": changed[1]},
        "total_lines_before": total,
        "total_lines_after": len(lines),
        "backup": backup,
        "message": f"已完成 {mode}（第 {changed[0]} 行起），文件现共 {len(lines)} 行",
    }
