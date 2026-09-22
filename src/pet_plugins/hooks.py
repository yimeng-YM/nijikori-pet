# -*- coding: utf-8 -*-
"""事件钩子总线。

插件用 ``api.on("tool_call", cb)`` 监听桌宠的运行事件；总线按优先级顺序
调用回调，单个回调抛错只记日志，绝不影响桌宠本体与其它插件。

约定：回调统一以桌宠实例（pet）作为第一个参数，其后是该事件的具体参数。
回调返回值一般被忽略；仅 ``first()`` 会用返回值做拦截（如工具调用前短路）。
"""
import threading

# 事件名仅用于文档与自检；注册未知事件不会报错（向后兼容）。
EVENTS = {
    "startup": "桌宠启动完成、插件加载完毕（pet）",
    "shutdown": "桌宠退出前（pet）",
    "message": "主人发出一条消息（pet, text）",
    "reply": "桌宠产出一条回复（pet, text）",
    "tool_call": "任何工具即将执行（pet, tool_name, args）",
    "tool_result": "任何工具执行完毕（pet, tool_name, args, result）",
    "emotion_change": "表情切换（pet, old_emotion, new_emotion）",
    "action": "肢体动作播放（pet, action, intensity）",
    "schedule_run": "定时任务触发（pet, task, info）",
    "config_saved": "配置写入成功（pet, config）",
    "plugin_loaded": "某个插件加载完成（pet, plugin_name）",
}


class HookBus:
    """插件事件总线（线程安全）。"""

    def __init__(self):
        self._hooks = {}       # event -> list[dict]
        self._seq = 0
        self._lock = threading.RLock()

    # -- 注册 / 注销 --------------------------------------------------------
    def on(self, event, callback, plugin=None, priority=0):
        if not callable(callback):
            raise TypeError("hook 回调必须是可调用对象")
        name = str(event or "").strip()
        if not name:
            raise ValueError("事件名不能为空")
        with self._lock:
            self._seq += 1
            entry = {"plugin": plugin, "callback": callback,
                     "priority": int(priority or 0), "seq": self._seq}
            self._hooks.setdefault(name, []).append(entry)
            self._hooks[name].sort(key=lambda e: (-e["priority"], e["seq"]))
            return entry

    def off(self, entry):
        with self._lock:
            for name, items in list(self._hooks.items()):
                if entry in items:
                    items.remove(entry)
                    if not items:
                        self._hooks.pop(name, None)
                    return True
        return False

    def off_plugin(self, plugin):
        """注销某个插件注册的全部回调。"""
        removed = 0
        with self._lock:
            for name, items in list(self._hooks.items()):
                keep = [e for e in items if e["plugin"] != plugin]
                removed += len(items) - len(keep)
                if keep:
                    self._hooks[name] = keep
                else:
                    self._hooks.pop(name, None)
        return removed

    def clear(self):
        with self._lock:
            self._hooks.clear()

    # -- 触发 --------------------------------------------------------------
    def callbacks(self, event):
        with self._lock:
            return list(self._hooks.get(str(event or ""), ()))

    def emit(self, event, *args, log=None, **kwargs):
        """顺序调用所有回调，返回 [(plugin, result), ...]。

        单个回调异常会被吞掉并交给 log（缺省 print），保证互不影响。"""
        results = []
        for entry in self.callbacks(event):
            try:
                results.append((entry["plugin"], entry["callback"](*args, **kwargs)))
            except Exception as exc:  # 插件出错绝不连累桌宠
                message = f"[plugins] 事件 {event} 的回调出错（插件 {entry['plugin']}）: {type(exc).__name__}: {exc}"
                if callable(log):
                    log(message)
                else:
                    print(message)
        return results

    def first(self, event, *args, log=None, **kwargs):
        """顺序调用回调，返回第一个非 None 的结果（用于拦截型事件）。"""
        for entry in self.callbacks(event):
            try:
                value = entry["callback"](*args, **kwargs)
            except Exception as exc:
                message = f"[plugins] 事件 {event} 的回调出错（插件 {entry['plugin']}）: {type(exc).__name__}: {exc}"
                if callable(log):
                    log(message)
                else:
                    print(message)
                continue
            if value is not None:
                return value
        return None
