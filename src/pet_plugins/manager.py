# -*- coding: utf-8 -*-
"""插件管理器：发现 → 信任确认 → 加载 → 注册表 → 分发 / 重载。

桌宠本体只在几个固定位置调用它（见 main.py 中的 ``PLUGINS`` 调用点），
因此插件系统与桌宠内核是单向依赖：内核认识插件管理器，插件只认识 API。
"""
import copy
import inspect
import json
import os
import shutil
import sys
import threading
import time

from pet_plugins.api import PluginAPI
from pet_plugins.hooks import HookBus
from pet_plugins.loader import (PluginCandidate, discover, load_module,
                                prune_sys_path, unload_module)
from pet_plugins.trust import TrustStore, path_digest

LOG_FILE = "plugins.log"
LOG_MAX_LINES = 800
# 插件自己的状态文件目录（EXE 版 data_dir 就是 exe 目录，所以不能叫 "plugins"，
# 否则会和用户插件目录撞在一起）
STATE_DIR_NAME = "plugin_state"
EXAMPLES_DIR_NAME = "_examples"
PLUGINS_README = """虹语织 · 插件目录 (plugins)
=============================

把 .py 文件放进这个文件夹，桌宠下次启动（或在控制中心点「重新加载」）
就会把它加载成新能力。支持两种形态：

1) 单文件插件
   plugins/我的工具.py

2) 文件夹插件（推荐，可带自己的模块与资源）
   plugins/你好插件/plugin.py      ← 入口文件（或 __init__.py）
   plugins/你好插件/helper.py
   plugins/你好插件/assets/...

以 _ 或 . 开头的文件/文件夹不会被加载（示例就放在 _examples/ 里）。

插件最简写法：

    def register(api):
        api.register_tool("my_tool", {
            "name": "my_tool",
            "description": "这个工具是干什么的、什么时候该用",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, my_handler)

    def my_handler(args, pet):
        return {"status": "success", "message": "你好呀！"}

安全说明：插件就是任意 Python 代码，等同于把本机执行权限交给它。
所以第一次加载（或插件内容变化后）桌宠会弹窗请你确认一次，
确认结果按内容哈希记在 data/plugin_trust.json 里，之后不再打扰。

完整 API（接管已有工具、改提示词、加菜单、加表情动作、监听事件）
见项目文档 docs/插件开发指南.md。
"""


class PluginError(Exception):
    """插件注册/加载阶段的可读错误。"""


class PluginHost:
    """桌宠本体提供给插件系统的接口集合（由 main.py 构造并注入）。"""

    def __init__(self, **kwargs):
        self.pet_tools_module = kwargs.get("pet_tools_module")
        self.tools_list = kwargs.get("tools_list")
        self.tool_categories = kwargs.get("tool_categories")
        self.vision_only_tools = kwargs.get("vision_only_tools")
        self.emotions = kwargs.get("emotions")
        self.text_bearing_emotions = kwargs.get("text_bearing_emotions")
        self.plugins_dir = kwargs.get("plugins_dir") or ""
        self.templates_dir = kwargs.get("templates_dir") or ""
        self.data_dir = kwargs.get("data_dir") or ""
        self.app_dir = kwargs.get("app_dir") or ""
        self.app_version = kwargs.get("app_version") or ""
        self.is_frozen = bool(kwargs.get("is_frozen"))
        self.logger = kwargs.get("logger")
        self.ui_kit = kwargs.get("ui_kit")
        self.on_tools_changed = kwargs.get("on_tools_changed")
        self.on_emotions_changed = kwargs.get("on_emotions_changed")
        self.on_actions_changed = kwargs.get("on_actions_changed")
        self.get_config = kwargs.get("get_config")
        self.set_config = kwargs.get("set_config")
        self.read_skill = kwargs.get("read_skill")
        self.list_skills = kwargs.get("list_skills")
        self.pet = None   # 桌宠实例在 UI 就绪后由 attach_pet 注入


class PluginRecord:
    """单个插件的加载记录。"""

    def __init__(self, candidate):
        self.candidate = candidate
        self.name = candidate.name
        self.module = None
        self.api = None
        self.status = "pending"     # loaded / failed / skipped / denied
        self.error = ""
        self.trust = candidate.meta.get("trust", "")
        self.loaded_at = ""

    def as_dict(self):
        return {
            "name": self.name,
            "path": self.candidate.path,
            "entry": self.candidate.entry_file,
            "is_package": self.candidate.is_package,
            "digest": self.candidate.digest,
            "status": self.status,
            "error": self.error,
            "trust": self.trust,
            "loaded_at": self.loaded_at,
        }


class PluginManager:
    """插件系统总入口（模块级单例见 pet_plugins.PLUGINS）。"""

    def __init__(self):
        self.host = None
        self.hooks = HookBus()
        self.trust = None
        self.plugins_dir = ""
        self.records = {}
        self._order = []
        self._lock = threading.RLock()
        self._tools = {}          # tool name -> entry dict
        self._wrappers = {}       # tool name (或 "*") -> {"before": [], "after": []}
        self._prompts = []        # {"plugin","text","when","priority","seq"}
        self._menu = []           # {"plugin","icon","label","callback","where","order","seq"}
        self._cc = []             # {"plugin","key","icon","title","builder","seq"}
        self._actions = {}        # action name -> {"plugin","handler","intensity","description"}
        self._seq = 0
        self._baseline = None
        self._log_path = ""
        self._builtin_tools = set()

    # ==================================================================
    # 挂载
    # ==================================================================
    def attach(self, host):
        """注入桌宠本体接口，并冻结"改造前"基线（重载时用它回滚）。"""
        self.host = host
        self.plugins_dir = host.plugins_dir
        self.trust = TrustStore(host.data_dir)
        self._log_path = os.path.join(host.data_dir, LOG_FILE)
        self._builtin_tools = {self._tool_name(t) for t in (host.tools_list or [])}
        self._baseline = {
            "tools": copy.deepcopy(list(host.tools_list or [])),
            "categories": copy.deepcopy(dict(host.tool_categories or {})),
            "vision_only": set(host.vision_only_tools or set()),
            "emotions": copy.deepcopy(list(host.emotions or [])),
        }
        return self

    def attach_pet(self, pet):
        """桌宠 UI 就绪后注入实例，插件才能操作界面。"""
        if self.host is not None:
            self.host.pet = pet

    def log(self, plugin, *parts):
        message = " ".join(str(p) for p in parts)
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{plugin}] {message}"
        try:
            print(f"[plugins] [{plugin}] {message}")
        except Exception:
            pass
        try:
            os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
            lines = []
            if os.path.isfile(self._log_path):
                with open(self._log_path, "r", encoding="utf-8", errors="replace") as handle:
                    lines = handle.read().splitlines()
            lines.append(line)
            if len(lines) > LOG_MAX_LINES:
                lines = lines[-LOG_MAX_LINES:]
            with open(self._log_path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    # ==================================================================
    # 目录与示例
    # ==================================================================
    def ensure_plugins_dir(self):
        """确保插件目录存在，并首次播种示例插件与说明文件。"""
        root = self.plugins_dir
        if not root:
            return ""
        try:
            os.makedirs(root, exist_ok=True)
        except OSError as exc:
            self.log("system", f"无法创建插件目录 {root}: {exc}")
            return root
        readme = os.path.join(root, "README.txt")
        if not os.path.exists(readme):
            try:
                with open(readme, "w", encoding="utf-8") as handle:
                    handle.write(PLUGINS_README)
            except OSError:
                pass
        templates = getattr(self.host, "templates_dir", "") if self.host else ""
        if templates and os.path.isdir(templates):
            target = os.path.join(root, EXAMPLES_DIR_NAME)
            try:
                if not os.path.isdir(target):
                    os.makedirs(target, exist_ok=True)
                    for entry in sorted(os.listdir(templates)):
                        source = os.path.join(templates, entry)
                        destination = os.path.join(target, entry)
                        if os.path.isdir(source):
                            shutil.copytree(source, destination)
                        elif entry.lower().endswith(".py"):
                            shutil.copy2(source, destination)
            except OSError as exc:
                self.log("system", f"播种示例插件失败: {exc}")
        return root

    def enable_examples(self):
        """把 _examples/ 里的示例复制到插件目录根下（复制后即可生效）。"""
        root = self.plugins_dir
        examples = os.path.join(root, EXAMPLES_DIR_NAME)
        if not os.path.isdir(examples):
            return []
        copied = []
        for entry in sorted(os.listdir(examples)):
            if not entry.lower().endswith(".py"):
                continue
            target = os.path.join(root, entry)
            if os.path.exists(target):
                continue
            try:
                shutil.copy2(os.path.join(examples, entry), target)
                copied.append(entry)
            except OSError as exc:
                self.log("system", f"复制示例 {entry} 失败: {exc}")
        return copied

    # ==================================================================
    # 加载 / 卸载 / 重载
    # ==================================================================
    def enabled(self):
        """插件总开关（config.json 的 enable_plugins，缺省开启）。"""
        getter = getattr(self.host, "get_config", None)
        if not callable(getter):
            return True
        try:
            value = getter("enable_plugins", True)
        except Exception:
            return True
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off", "关")

    def trust_required(self):
        """是否需要首次加载确认（config.json 的 plugin_trust_required，缺省需要）。"""
        getter = getattr(self.host, "get_config", None)
        if not callable(getter):
            return True
        try:
            value = getter("plugin_trust_required", True)
        except Exception:
            return True
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off", "关")

    def scan(self):
        """只做发现与指纹计算，不导入任何插件代码。"""
        self.ensure_plugins_dir()
        candidates = discover(self.plugins_dir)
        for candidate in candidates:
            try:
                candidate.digest = path_digest(candidate.path)
            except OSError as exc:
                candidate.digest = ""
                candidate.meta["digest_error"] = str(exc)
            candidate.meta["trust"] = self.trust.status(candidate.name, candidate.digest)
        return candidates

    def load_all(self, confirm=None, *, names=None):
        """加载全部（或指定）插件。

        confirm: ``callable(pending_list) -> iterable[approved_names]``，
                 仅在出现"新的/内容变化的"插件时调用；为 None 时跳过未确认的插件。
        返回本次加载结果摘要 dict。
        """
        with self._lock:
            if self.host is None:
                raise PluginError("插件系统尚未 attach 到桌宠")
            if not self.enabled():
                self.log("system", "插件功能已关闭（config.json: enable_plugins=false）")
                return {"loaded": [], "failed": [], "skipped": [], "disabled": True}
            candidates = self.scan()
            if names is not None:
                wanted = {str(n) for n in names}
                candidates = [c for c in candidates if c.name in wanted]
            # 幂等：已加载且内容未变化的插件不重复加载（重复注册会顶掉自己）
            candidates = [c for c in candidates if not self._already_loaded(c)]

            approved, denied, ready = [], [], []
            for candidate in candidates:
                status = candidate.meta.get("trust", "new")
                if status == "trusted":
                    ready.append(candidate)
                elif status == "denied":
                    denied.append(candidate)
                else:
                    approved.append(candidate)

            if approved:
                if not self.trust_required():
                    # 关掉确认机制：新的/变化过的插件直接信任并加载
                    for candidate in approved:
                        self.trust.decide(candidate.name, candidate.digest, True)
                        self.trust.set_path(candidate.name, candidate.path)
                        candidate.meta["trust"] = "trusted"
                        ready.append(candidate)
                elif callable(confirm):
                    try:
                        pending_info = [{"name": c.name, "path": c.path, "entry": c.entry_file,
                                         "status": c.meta.get("trust", "new"),
                                         "is_package": c.is_package, "digest": c.digest}
                                        for c in approved]
                        picked = {str(n) for n in (confirm(pending_info) or [])}
                    except Exception as exc:
                        self.log("system", f"信任确认流程出错，本次不加载新插件: {exc}")
                        picked = set()
                    for candidate in approved:
                        allowed = candidate.name in picked
                        self.trust.decide(candidate.name, candidate.digest, allowed)
                        self.trust.set_path(candidate.name, candidate.path)
                        candidate.meta["trust"] = "trusted" if allowed else "denied"
                        (ready if allowed else denied).append(candidate)
                else:
                    # 没有确认通道（如无界面的调用方）：不擅自加载未确认的插件
                    for candidate in approved:
                        self.trust.set_path(candidate.name, candidate.path)
                        candidate.meta["trust"] = "unknown"
                        self._record_skipped(candidate, "pending")

            for candidate in denied:
                self._record_skipped(candidate, "denied")

            loaded, failed = [], []
            for candidate in ready:
                record = self._load_one(candidate)
                (loaded if record.status == "loaded" else failed).append(record.name)

            self._order = [n for n in self._order if n in self.records]
            summary = {"loaded": loaded, "failed": failed,
                       "skipped": [c.name for c in denied],
                       "pending": [c.name for c in approved if c.meta.get("trust") == "unknown"]}
            if loaded or failed:
                self._notify_tools_changed()
            self.log("system", f"加载完成：成功 {len(loaded)}，失败 {len(failed)}，"
                               f"跳过 {len(summary['skipped'])}")
            return summary

    def _already_loaded(self, candidate):
        """已加载且内容未变化的插件：直接跳过，避免重复注册顶掉自己。"""
        record = self.records.get(candidate.name)
        return (record is not None and record.status == "loaded"
                and record.candidate.digest == candidate.digest)

    def _record_skipped(self, candidate, status):
        record = PluginRecord(candidate)
        record.status = status
        record.trust = candidate.meta.get("trust", status)
        self.records[candidate.name] = record
        if candidate.name not in self._order:
            self._order.append(candidate.name)

    def _load_one(self, candidate):
        record = PluginRecord(candidate)
        record.trust = candidate.meta.get("trust", "")
        self.records[candidate.name] = record
        if candidate.name not in self._order:
            self._order.append(candidate.name)
        try:
            module = load_module(candidate)
            record.module = module
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError("插件缺少 register(api) 入口函数")
            api = PluginAPI(self, candidate)
            record.api = api
            register(api)
            record.status = "loaded"
            record.loaded_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log(candidate.name, f"已加载（{candidate.entry_file}）")
            self.hooks.emit("plugin_loaded", self.host.pet, candidate.name, log=self._hook_log)
        except BaseException as exc:  # 插件自身出错不能拖垮桌宠
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            self.log(candidate.name, f"加载失败：{record.error}")
            self._unregister(candidate.name)
            try:
                unload_module(candidate)
            except Exception:
                pass
            record.module = None
            record.api = None
        return record

    def _hook_log(self, message):
        self.log("hook", message)

    def unload_all(self):
        """卸载全部插件（先跑 on_unload 回调），回滚注册并清掉模块缓存。"""
        with self._lock:
            for name in list(self._order):
                record = self.records.get(name)
                if record is None:
                    continue
                if record.api is not None:
                    record.api._run_unload_hooks()
                self._unregister(name)
                try:
                    unload_module(record.candidate)
                except Exception:
                    pass
                prune_sys_path(os.path.dirname(record.candidate.path))
            self.records.clear()
            self._order.clear()

    def _restore_baseline(self):
        """把工具表/分类/识图集合/表情表恢复到插件介入之前。"""
        if not self._baseline or self.host is None:
            return
        tools_list = self.host.tools_list
        if isinstance(tools_list, list):
            tools_list[:] = copy.deepcopy(self._baseline["tools"])
        categories = self.host.tool_categories
        if isinstance(categories, dict):
            categories.clear()
            categories.update(copy.deepcopy(self._baseline["categories"]))
        vision = self.host.vision_only_tools
        if isinstance(vision, set):
            vision.clear()
            vision.update(self._baseline["vision_only"])
        emotions = self.host.emotions
        if isinstance(emotions, list):
            emotions[:] = copy.deepcopy(self._baseline["emotions"])

    def _reset_registries(self):
        self._tools.clear()
        self._wrappers.clear()
        self._prompts.clear()
        self._menu.clear()
        self._cc.clear()
        self._actions.clear()
        self.hooks.clear()

    def disable_all(self):
        """停用全部插件：卸载、清空注册表、把工具/表情表回滚到基线并通知宿主。

        控制中心「启用插件系统」总开关关闭时走这里，保证效果立即生效，
        而不是等到下次重启才不加载。
        """
        with self._lock:
            self.unload_all()
            self._reset_registries()
            self._restore_baseline()
            self._notify_tools_changed()
            self._notify_emotions_changed()
            self._notify_actions_changed()
            self.log("system", "已停用全部插件，能力已还原到基线")
            return {"loaded": [], "failed": [], "skipped": [], "disabled": True}

    def reload(self, confirm=None):
        """卸载全部插件 → 回滚基线 → 重新扫描加载（热重载）。"""
        with self._lock:
            self.log("system", "开始重新加载插件…")
            self.disable_all()
            if self.trust is not None:
                self.trust.load()
            summary = self.load_all(confirm=confirm)
            self._notify_emotions_changed()
            self._notify_actions_changed()
            self._notify_tools_changed()
            return summary

    def set_plugin_enabled(self, name, enabled):
        """信任/停用某个插件（写入信任库），随后重载它。"""
        candidates = {c.name: c for c in self.scan()}
        candidate = candidates.get(str(name))
        if candidate is None:
            return {"status": "error", "message": f"没有找到插件：{name}"}
        self.trust.decide(candidate.name, candidate.digest, bool(enabled))
        self.trust.set_path(candidate.name, candidate.path)
        if enabled:
            self.unload_one(name)
            candidate.meta["trust"] = "trusted"
            record = self._load_one(candidate)
            self._notify_tools_changed()
            return {"status": "success" if record.status == "loaded" else "error",
                    "message": (f"已启用插件 {name}" if record.status == "loaded"
                                else f"插件 {name} 加载失败：{record.error}")}
        self.unload_one(name)
        self._record_skipped(candidate, "denied")
        self._notify_tools_changed()
        return {"status": "success", "message": f"已停用插件 {name}"}

    def unload_one(self, name):
        record = self.records.get(name)
        if record is None:
            return False
        if record.api is not None:
            record.api._run_unload_hooks()
        self._unregister(name)
        try:
            unload_module(record.candidate)
        except Exception:
            pass
        prune_sys_path(os.path.dirname(record.candidate.path))
        self.records.pop(name, None)
        if name in self._order:
            self._order.remove(name)
        return True

    # ==================================================================
    # 注册表
    # ==================================================================
    def _tool_name(self, entry):
        if isinstance(entry, dict):
            return str((entry.get("function") or {}).get("name") or "")
        return ""

    def register_tool(self, api, name, schema, handler, *, category="插件",
                      description=None, vision_only=False, override=False,
                      replace_schema=True):
        name = str(name or "").strip()
        if not name:
            raise PluginError("工具名不能为空")
        if not callable(handler):
            raise PluginError(f"工具 {name} 的 handler 必须是可调用对象")
        with self._lock:
            existing = self._tools.get(name)
            is_builtin = name in self._builtin_tools
            if (existing is not None or is_builtin) and not override:
                raise PluginError(f"工具 {name} 已存在；若要接管它请用 override_tool() 或 override=True")

            schema_added = False
            schema_replaced = None
            if schema is not None and replace_schema:
                schema = dict(schema)
                schema.setdefault("name", name)
                schema["name"] = name
                if description:
                    schema["description"] = description
                schema.setdefault("parameters", {"type": "object", "properties": {}, "required": []})
                wrapper = {"type": "function", "function": schema}
                tools_list = self.host.tools_list
                index = next((i for i, t in enumerate(tools_list or [])
                              if self._tool_name(t) == name), None)
                if index is None:
                    if tools_list is not None:
                        tools_list.append(wrapper)
                        schema_added = True
                else:
                    schema_replaced = copy.deepcopy(tools_list[index])
                    tools_list[index] = wrapper

            vision_added = False
            if vision_only:
                vision = self.host.vision_only_tools
                if isinstance(vision, set) and name not in vision:
                    vision.add(name)
                    vision_added = True

            categories = self.host.tool_categories
            old_category = categories.get(name) if isinstance(categories, dict) else None
            if isinstance(categories, dict) and category:
                categories[name] = str(category)

            entry = {
                "name": name,
                "plugin": api.name,
                "handler": handler,
                "override": bool(override or existing is not None or is_builtin),
                "arity": 3 if (override or is_builtin or existing is not None) and
                        self._accepts(handler, 3) else 2,
                "schema_added": schema_added,
                "schema_replaced": schema_replaced,
                "vision_added": vision_added,
                "old_category": old_category,
            }
            self._tools[name] = entry
            return name

    @staticmethod
    def _accepts(handler, count):
        """判断 handler 是否接受至少 count 个位置参数。"""
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            return True
        positional = [p for p in signature.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values()):
            return True
        return len(positional) >= count

    def wrap_tool(self, api, name, *, before=None, after=None):
        name = str(name or "*").strip() or "*"
        if before is not None and not callable(before):
            raise PluginError("wrap_tool 的 before 必须是可调用对象")
        if after is not None and not callable(after):
            raise PluginError("wrap_tool 的 after 必须是可调用对象")
        with self._lock:
            slot = self._wrappers.setdefault(name, {"before": [], "after": []})
            if before is not None:
                slot["before"].append((api.name, before))
            if after is not None:
                slot["after"].append((api.name, after))
        return name

    def add_prompt_block(self, api, text, *, priority=0, when=None):
        if not callable(text) and not isinstance(text, str):
            raise PluginError("add_prompt_block 的 text 必须是字符串或可调用对象")
        if when is not None and not callable(when):
            raise PluginError("add_prompt_block 的 when 必须是可调用对象")
        with self._lock:
            self._seq += 1
            entry = {"plugin": api.name, "text": text, "when": when,
                     "priority": int(priority or 0), "seq": self._seq}
            self._prompts.append(entry)
            self._prompts.sort(key=lambda e: (-e["priority"], e["seq"]))
        return entry

    def add_menu_item(self, api, label, callback, *, icon="🧩", where="quick", order=50):
        if not callable(callback):
            raise PluginError("add_menu_item 的 callback 必须是可调用对象")
        with self._lock:
            self._seq += 1
            entry = {"plugin": api.name, "icon": str(icon), "label": str(label),
                     "callback": callback, "where": str(where or "quick"),
                     "order": int(order or 50), "seq": self._seq}
            self._menu.append(entry)
            self._menu.sort(key=lambda e: (e["order"], e["seq"]))
        return entry

    def add_control_center_page(self, api, title, builder, *, icon="🧩", key=None):
        if not callable(builder):
            raise PluginError("add_control_center_page 的 builder 必须是可调用对象")
        with self._lock:
            self._seq += 1
            page_key = str(key or f"plugin:{api.name}")
            entry = {"plugin": api.name, "key": page_key, "icon": str(icon or "🧩"),
                     "title": str(title or api.name), "builder": builder, "seq": self._seq}
            self._cc = [p for p in self._cc if p["key"] != page_key]
            self._cc.append(entry)
        return entry

    def register_emotion(self, api, name, image, *, description="", text_bearing=False):
        name = str(name or "").strip()
        if not name:
            raise PluginError("表情名不能为空")
        path = str(image or "")
        if not os.path.isabs(path):
            path = os.path.join(api.dir, path)
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise PluginError(f"表情图片不存在：{path}")
        with self._lock:
            emotions = self.host.emotions
            if not isinstance(emotions, list):
                raise PluginError("当前桌宠不支持插件注册表情")
            if any(str(e[0]) == name for e in emotions):
                raise PluginError(f"表情 {name} 已存在")
            emotions.append((name, path, str(description or "插件表情")))
            if text_bearing and isinstance(self.host.text_bearing_emotions, set):
                self.host.text_bearing_emotions.add(name)
        self._notify_emotions_changed()
        return name

    def register_action(self, api, name, handler, *, description="", intensity="normal"):
        name = str(name or "").strip()
        if not name:
            raise PluginError("动作名不能为空")
        if not callable(handler):
            raise PluginError("动作 handler 必须是可调用对象")
        with self._lock:
            if name in self._actions:
                raise PluginError(f"动作 {name} 已被注册")
            self._actions[name] = {"plugin": api.name, "handler": handler,
                                   "intensity": str(intensity or "normal"),
                                   "description": str(description or "")}
        self._notify_actions_changed()
        return name

    def _unregister(self, plugin_name):
        """回滚某个插件的全部注册（加载失败 / 卸载 / 重载时调用）。"""
        with self._lock:
            tools_list = self.host.tools_list if self.host else None
            for name in [n for n, e in self._tools.items() if e["plugin"] == plugin_name]:
                entry = self._tools.pop(name)
                if isinstance(tools_list, list):
                    if entry["schema_added"]:
                        for i, t in enumerate(tools_list):
                            if self._tool_name(t) == name:
                                del tools_list[i]
                                break
                    elif entry["schema_replaced"] is not None:
                        for i, t in enumerate(tools_list):
                            if self._tool_name(t) == name:
                                tools_list[i] = entry["schema_replaced"]
                                break
                if entry["vision_added"] and isinstance(self.host.vision_only_tools, set):
                    self.host.vision_only_tools.discard(name)
                categories = self.host.tool_categories if self.host else None
                if isinstance(categories, dict):
                    if entry["old_category"] is None:
                        categories.pop(name, None)
                    else:
                        categories[name] = entry["old_category"]
            for name in [n for n, slot in self._wrappers.items()
                         if any(p == plugin_name for p, _ in slot["before"] + slot["after"])]:
                slot = self._wrappers[name]
                slot["before"] = [x for x in slot["before"] if x[0] != plugin_name]
                slot["after"] = [x for x in slot["after"] if x[0] != plugin_name]
                if not slot["before"] and not slot["after"]:
                    self._wrappers.pop(name, None)
            self._prompts = [p for p in self._prompts if p["plugin"] != plugin_name]
            self._menu = [m for m in self._menu if m["plugin"] != plugin_name]
            self._cc = [p for p in self._cc if p["plugin"] != plugin_name]
            for name in [n for n, a in self._actions.items() if a["plugin"] == plugin_name]:
                self._actions.pop(name, None)
            emotions = self.host.emotions if self.host else None
            if isinstance(emotions, list):
                keep = []
                for item in emotions:
                    if len(item) >= 2 and isinstance(item[1], str) and os.path.isabs(item[1]) \
                            and self._emotion_owner(item[1]) == plugin_name:
                        continue
                    keep.append(item)
                if len(keep) != len(emotions):
                    emotions[:] = keep
            self.hooks.off_plugin(plugin_name)

    def _emotion_owner(self, absolute_path):
        for name, record in self.records.items():
            if record.api is None:
                continue
            try:
                if os.path.commonpath([os.path.abspath(absolute_path),
                                       os.path.abspath(record.api.dir)]) == \
                        os.path.abspath(record.api.dir):
                    return name
            except (ValueError, OSError):
                continue
        return None

    # ==================================================================
    # 运行期接口（main.py 调用）
    # ==================================================================
    def has_tools(self):
        return bool(self._tools)

    def dispatch(self, tool_name, args, pet, call_original=None):
        """插件工具/接管的分发入口。

        返回 dict = 插件已处理；返回 None = 交回桌宠内置实现。"""
        entry = self._tools.get(tool_name)
        if entry is None:
            return None
        handler = entry["handler"]
        try:
            if entry["arity"] >= 3:
                return handler(args, pet, call_original)
            return handler(args, pet)
        except Exception as exc:
            self.log(entry["plugin"], f"工具 {tool_name} 执行出错: {type(exc).__name__}: {exc}")
            return {"status": "error", "error_type": "plugin_tool_error",
                    "message": f"插件 {entry['plugin']} 的工具 {tool_name} 执行出错：{exc}"}

    def run_before_tool(self, tool_name, args, pet):
        """工具执行前的包装钩子；返回 dict 则短路为工具结果。"""
        for key in (tool_name, "*"):
            for plugin, callback in self._wrappers.get(key, {}).get("before", []):
                try:
                    value = callback(args, pet)
                except Exception as exc:
                    self.log(plugin, f"before 钩子出错（{tool_name}）: {type(exc).__name__}: {exc}")
                    continue
                if isinstance(value, dict):
                    return value
        return None

    def run_after_tool(self, tool_name, args, result, pet):
        """工具执行后的包装钩子；返回 dict 则替换工具结果。"""
        for key in (tool_name, "*"):
            for plugin, callback in self._wrappers.get(key, {}).get("after", []):
                try:
                    value = callback(args, pet, result)
                except Exception as exc:
                    self.log(plugin, f"after 钩子出错（{tool_name}）: {type(exc).__name__}: {exc}")
                    continue
                if isinstance(value, dict):
                    result = value
        return result

    def prompt_blocks(self, pet=None):
        """返回本回合要注入系统提示词的插件段落。"""
        blocks = []
        for entry in list(self._prompts):
            try:
                if entry["when"] is not None and not entry["when"](pet):
                    continue
                text = entry["text"](pet) if callable(entry["text"]) else entry["text"]
            except Exception as exc:
                self.log(entry["plugin"], f"提示词段落出错: {type(exc).__name__}: {exc}")
                continue
            if text and str(text).strip():
                blocks.append(str(text).strip())
        return blocks

    def menu_items(self, where="quick"):
        return [m for m in list(self._menu) if m["where"] == where]

    def control_center_pages(self):
        return list(self._cc)

    def action_names(self):
        return sorted(self._actions)

    def action_info(self, name):
        return self._actions.get(name)

    def run_action(self, name, pet, intensity=None):
        """执行插件注册的自定义动作，返回是否已处理。"""
        entry = self._actions.get(name)
        if entry is None:
            return False
        try:
            entry["handler"](pet, intensity or entry["intensity"])
            return True
        except Exception as exc:
            self.log(entry["plugin"], f"动作 {name} 执行出错: {type(exc).__name__}: {exc}")
            return True

    def emit(self, event, *args, **kwargs):
        return self.hooks.emit(event, *args, log=self._hook_log, **kwargs)

    def emotion_sprite(self, name):
        """插件表情的绝对路径（找不到返回 None）。"""
        for item in (self.host.emotions if self.host else []) or []:
            if len(item) >= 2 and str(item[0]) == name and os.path.isabs(str(item[1])):
                return str(item[1])
        return None

    def ui_kit(self):
        kit = getattr(self.host, "ui_kit", None) if self.host else None
        return kit() if callable(kit) else {}

    def get_config(self, key=None, default=None):
        getter = getattr(self.host, "get_config", None) if self.host else None
        if not callable(getter):
            return default
        try:
            return getter(key, default)
        except Exception:
            return default

    def set_config(self, key, value):
        setter = getattr(self.host, "set_config", None) if self.host else None
        if not callable(setter):
            return False
        try:
            return bool(setter(key, value))
        except Exception:
            return False

    def read_skill(self, name):
        reader = getattr(self.host, "read_skill", None) if self.host else None
        if not callable(reader):
            return None
        try:
            return reader(name)
        except Exception:
            return None

    def list_skills(self):
        reader = getattr(self.host, "list_skills", None) if self.host else None
        if not callable(reader):
            return []
        try:
            return list(reader() or [])
        except Exception:
            return []

    # ---- 插件自己的状态文件 -------------------------------------------
    def _state_path(self, name):
        return os.path.join(self.host.data_dir, STATE_DIR_NAME, f"{name}.json")

    def load_state(self, name):
        path = self._state_path(name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, UnicodeError):
            return {}

    def save_state(self, name, state):
        path = self._state_path(name)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(state if isinstance(state, dict) else {}, handle,
                          ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except OSError as exc:
            self.log(name, f"保存插件状态失败: {exc}")
            return False

    # ---- 状态查询 ------------------------------------------------------
    def status(self):
        """返回给控制中心 / AI 工具用的完整状态。"""
        return {
            "enabled": self.enabled(),
            "trust_required": self.trust_required(),
            "plugins_dir": self.plugins_dir,
            "templates_dir": getattr(self.host, "templates_dir", "") if self.host else "",
            "tools": sorted(self._tools),
            "prompt_blocks": len(self._prompts),
            "menu_items": len(self._menu),
            "pages": [p["key"] for p in self._cc],
            "emotions": [str(e[0]) for e in (self.host.emotions if self.host else []) or []
                         if len(e) >= 2 and isinstance(e[1], str) and os.path.isabs(e[1])],
            "actions": sorted(self._actions),
            "plugins": [self.records[n].as_dict() for n in self._order if n in self.records],
        }

    def _notify_tools_changed(self):
        callback = getattr(self.host, "on_tools_changed", None) if self.host else None
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                self.log("system", f"工具表变更通知失败: {exc}")

    def _notify_emotions_changed(self):
        callback = getattr(self.host, "on_emotions_changed", None) if self.host else None
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                self.log("system", f"表情表变更通知失败: {exc}")

    def _notify_actions_changed(self):
        callback = getattr(self.host, "on_actions_changed", None) if self.host else None
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                self.log("system", f"动作表变更通知失败: {exc}")
