# -*- coding: utf-8 -*-
"""示例插件 ②：接管 / 改写桌宠的现有能力。

演示三件事（这是"修改桌宠现有能力"的三种姿势）：
1. override_tool —— 接管已有工具（含内置工具），可以选择性调用原实现；
2. wrap_tool     —— 不改原实现，只在工具执行前后插一脚（before 可短路）；
3. add_prompt_block + on("tool_result") —— 观察并影响对话上下文。

本示例做的是：
- 把内置的 get_current_time 接管掉：在原结果上补一句"插件附言"；
- 给 run_command / run_command_capture 挂 after 钩子，记录每次命令；
- 用 before 钩子拦截 open_website：访问非白名单域名时先拒绝（安全演示）。

注意：插件接管的是"工具行为"，桌宠原有的确认弹窗、禁用开关、定时授权
等安全机制仍在更外层生效，插件改不掉它们。
"""

_state = {}
_api = None

# 允许打开的白名单（演示 before 短路；留空表示不限制）
ALLOWED_SITES = ("github.com", "docs.python.org", "www.python.org")


def register(api):
    global _state, _api
    _api = api
    _state = api.state
    _state.setdefault("commands_seen", [])
    _state.setdefault("blocked_sites", 0)

    # ---- 1) 接管已有工具：handler(args, pet, call_original) ----
    api.override_tool("get_current_time", current_time_plus, category="账户与信息")

    # ---- 2) 不改原实现，挂前后钩子 ----
    api.wrap_tool("run_command", after=after_command)
    api.wrap_tool("run_command_capture", after=after_command)
    api.wrap_tool("open_website", before=before_open_website)

    api.add_prompt_block(
        "示例插件 example_override 正在运行：时间类回答来自插件的接管版本，"
        "打开网站受白名单限制（github.com / docs.python.org）。主人问起时如实说明。"
    )
    api.on_unload(lambda: api.save_state())
    api.log("已加载（示例插件 ②：接管与钩子）")


def current_time_plus(args, pet, call_original):
    """接管 get_current_time：先拿原结果，再补充插件信息。"""
    original = call_original()
    if not isinstance(original, dict):
        return original
    if original.get("status") != "success":
        return original
    original["plugin_note"] = "（这句附言来自 example_override 插件对时间工具的接管）"
    original["message"] = original.get("message") or "时间已获取（插件增强版）"
    return original


def after_command(args, pet, result):
    """命令执行后记录一笔（不改变结果）。"""
    try:
        command = str(args.get("command") or args.get("cmd") or "")[:120]
        _state["commands_seen"].append(command)
        del _state["commands_seen"][:-50]      # 只留最近 50 条
    except Exception:
        pass
    return None                                 # None = 保持原结果


def before_open_website(args, pet):
    """before 钩子：返回 dict 即短路，不再执行原实现。"""
    url = str(args.get("url") or "")
    if not ALLOWED_SITES:
        return None
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host and any(host == site or host.endswith("." + site) for site in ALLOWED_SITES):
        return None                             # 白名单内，交给原实现
    _state["blocked_sites"] += 1
    _api.save_state()
    return {
        "status": "error",
        "error_type": "plugin_blocked",
        "message": f"示例插件拦下了这个网址：{url}（不在白名单内）。"
                   f"要放开请编辑 plugins/example_override.py 里的 ALLOWED_SITES。",
    }
