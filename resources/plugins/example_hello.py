# -*- coding: utf-8 -*-
"""示例插件 ①：最小可用插件。

演示三件事：
1. register_tool  —— 给桌宠加一个全新工具，AI 就能调用它；
2. add_prompt_block —— 把能力写进系统提示词，AI 才知道它存在；
3. on / state     —— 监听事件 + 插件自己的持久化数据。

用法：把本文件复制到 plugins\\ 目录（去掉 _examples 这一层），
重启桌宠或在控制中心点「重新加载插件」即可生效。
"""

# 当前插件的持久化数据（register 时从 api.state 取到）
_state = {}
_api = None


def register(api):
    global _state, _api
    _api = api
    _state = api.state
    _state.setdefault("total_calls", 0)
    _state.setdefault("installed_at", "")

    if not _state["installed_at"]:
        import time
        _state["installed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    api.register_tool(
        "plugin_hello",
        {
            "name": "plugin_hello",
            "description": "示例插件提供的问好工具：返回本插件的调用次数、安装时间与当前时间。"
                           "主人说“演示一下插件”“测试插件”时调用它。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "可选：要问候的名字"},
                },
                "required": [],
            },
        },
        hello,
        category="插件示例",
    )

    api.add_prompt_block(
        "你安装了示例插件 example_hello：主人要求演示/验证插件功能时，"
        "调用 plugin_hello 工具，并把返回内容活泼地念给主人听。"
    )

    api.on("startup", on_startup)
    api.on("message", on_message, priority=-10)
    api.on_unload(lambda: (api.log("退出，共被调用", _state["total_calls"], "次"),
                           api.save_state()))

    api.log("已加载（示例插件 ①）")


def hello(args, pet):
    import time
    _state["total_calls"] += 1
    _api.save_state()
    who = str(args.get("name") or "主人").strip()
    return {
        "status": "success",
        "greeting": f"{who}好呀！我是靠插件长出来的新能力～",
        "total_calls": _state["total_calls"],
        "installed_at": _state["installed_at"],
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": f"插件工具调用成功（这是第 {_state['total_calls']} 次）",
    }


def on_startup(pet):
    """桌宠启动完成。注意：改界面要回到 UI 线程（call_on_ui）。"""
    if _api is not None:
        _api.log("桌宠已启动")
        try:
            _api.call_on_ui(pet.show_speech, "示例插件已就位 (✧∇✧)", "递爱心", 2500)
        except Exception:
            pass


def on_message(pet, text):
    """每条主人消息都会到这里——示例里只做记录。"""
    if _api is not None:
        _api.log("收到消息:", (text or "")[:30])
