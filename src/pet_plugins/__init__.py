# -*- coding: utf-8 -*-
"""虹语织桌宠 · 插件系统（pet_plugins）。

把 ``.py`` 文件放进桌宠的 ``plugins`` 文件夹，就能给桌宠加新能力，或改写
已有能力；源码运行与打包好的 EXE 使用同一套机制（EXE 版插件目录就在
exe 同级的 ``plugins``）。

    from pet_plugins import PLUGINS

    PLUGINS.attach(host)          # main.py 启动时注入桌宠接口
    PLUGINS.attach_pet(pet)       # UI 就绪后注入桌宠实例
    PLUGINS.load_all(confirm=cb)  # 扫描并加载（新插件先问主人）
    PLUGINS.dispatch(...)         # 工具分发时优先问插件

模块组成：

- ``hooks``   : 事件总线（startup / message / tool_call / tool_result …）
- ``trust``   : 按内容哈希记住主人的加载许可
- ``loader``  : 插件目录扫描与按路径导入（EXE 内同样可用）
- ``api``     : 交给插件的 API 门面
- ``manager`` : 注册表、分发、重载与状态查询
"""
from pet_plugins.api import PluginAPI
from pet_plugins.hooks import EVENTS, HookBus
from pet_plugins.loader import PluginCandidate, discover, load_module, unload_module
from pet_plugins.manager import (LOG_FILE, PluginError, PluginHost, PluginManager,
                                 PluginRecord)
from pet_plugins.trust import TrustStore, path_digest

# 模块级单例：桌宠本体只跟它打交道。
PLUGINS = PluginManager()

__all__ = [
    "PLUGINS", "PluginManager", "PluginAPI", "PluginHost", "PluginRecord",
    "PluginError", "HookBus", "EVENTS", "TrustStore", "path_digest",
    "PluginCandidate", "discover", "load_module", "unload_module", "LOG_FILE",
]
