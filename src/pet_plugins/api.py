# -*- coding: utf-8 -*-
"""插件 API：插件通过 ``register(api)`` 拿到的能力入口。

一个插件最少只需要：

    def register(api):
        api.register_tool("my_tool", {...}, my_handler)

能力一览（详见各方法 docstring 与 docs/插件开发指南.md）：

- 新增工具：register_tool
- 接管/改写已有工具：override_tool / wrap_tool
- 往系统提示词加内容：add_prompt_block
- 监听事件：on（startup / message / tool_call / tool_result / emotion_change …）
- 加右键菜单与控制中心页面：add_menu_item / add_control_center_page
- 加表情立绘与自定义动作：register_emotion / register_action
- 插件自己的持久化数据：state / save_state
"""
import os


class PluginAPI:
    """交给单个插件的 API 门面（一个插件一个实例）。"""

    def __init__(self, manager, candidate):
        self._manager = manager
        self._candidate = candidate
        self._state = None
        self._unload_hooks = []

    # ------------------------------------------------------------------
    # 身份信息
    # ------------------------------------------------------------------
    @property
    def name(self):
        """插件名（即 plugins 文件夹里的文件名/文件夹名）。"""
        return self._candidate.name

    @property
    def dir(self):
        """插件所在目录（单文件插件为其父目录）。"""
        return os.path.dirname(self._candidate.path) if not self._candidate.is_package \
            else self._candidate.path

    @property
    def path(self):
        """插件入口文件路径。"""
        return self._candidate.entry_file

    @property
    def host_dir(self):
        """桌宠程序目录（EXE 同目录 / 源码项目根目录）。"""
        return self._manager.host.app_dir if self._manager.host else ""

    @property
    def data_dir(self):
        """桌宠数据目录（配置、记忆、插件状态都放这里）。"""
        return self._manager.host.data_dir if self._manager.host else ""

    @property
    def plugins_dir(self):
        return self._manager.plugins_dir

    @property
    def is_frozen(self):
        """是否运行在打包好的 EXE 中。"""
        return bool(self._manager.host and self._manager.host.is_frozen)

    def resolve(self, *parts):
        """把相对路径解析到插件自己的目录下（插件自带资源请用它）。"""
        return os.path.join(self.dir, *[str(p) for p in parts])

    def log(self, *parts):
        """写一行插件日志（控制台 + data/plugins.log）。"""
        self._manager.log(self.name, *parts)

    # ------------------------------------------------------------------
    # 工具：新增 / 接管 / 包装
    # ------------------------------------------------------------------
    def register_tool(self, name, schema, handler, *, category="插件",
                      description=None, vision_only=False, override=False):
        """注册一个新工具给模型调用。

        name       工具名（模型看到的名字，建议 ``插件名_动作`` 风格）
        schema     OpenAI function schema：``{"name":..., "description":..., "parameters":{...}}``
                   （``name`` 可省略，缺省用 name 参数）
        handler    ``handler(args: dict, pet) -> dict``，返回 ``{"status": "success", ...}``
                   或 ``{"status": "error", "message": ...}``
        category   控制中心「工具能力」页里的分组名
        vision_only 为 True 时，只有主人开启识图后模型才能看到它
        override   为 True 时允许顶掉同名内置工具（等价于 override_tool）
        """
        return self._manager.register_tool(self, name, schema, handler,
                                           category=category, description=description,
                                           vision_only=vision_only, override=override)

    def override_tool(self, name, handler, *, category=None):
        """接管一个已有工具（含内置工具）的实现。

        handler 签名为 ``handler(args, pet, call_original)``：

        - 返回 dict → 用你的结果替换原实现；
        - 返回 ``None`` → 本次调用交回原实现（相当于条件接管）；
        - 想拿到原结果再加工，调用 ``call_original()``。
        """
        return self._manager.register_tool(self, name, None, handler, category=category,
                                           override=True, replace_schema=False)

    def wrap_tool(self, name, *, before=None, after=None):
        """给任意工具（含内置工具）挂前后钩子，不替换原实现。

        before(args, pet)：返回 dict 则短路，直接作为工具结果，不再执行原实现；
                          返回 None 则继续执行。
        after(args, pet, result)：返回 dict 则替换结果，返回 None 则保持原结果。
        """
        return self._manager.wrap_tool(self, name, before=before, after=after)

    # ------------------------------------------------------------------
    # 提示词
    # ------------------------------------------------------------------
    def add_prompt_block(self, text, *, priority=0, when=None):
        """往系统提示词里追加一段内容（排在技能库之后）。

        text 可以是字符串，也可以是 ``callable(pet) -> str | None``（每次对话现算）。
        when 可选：``callable(pet) -> bool``，返回 False 时本回合不注入。
        """
        return self._manager.add_prompt_block(self, text, priority=priority, when=when)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def on(self, event, callback, *, priority=0):
        """监听事件，回调第一个参数固定是 pet。

        常用事件：startup / shutdown / message / reply / tool_call /
        tool_result / emotion_change / action / schedule_run / config_saved。
        """
        return self._manager.hooks.on(event, callback, plugin=self.name, priority=priority)

    def on_unload(self, callback):
        """注册卸载回调（重载/退出时调用），用于释放线程、句柄、临时文件。"""
        if not callable(callback):
            raise TypeError("on_unload 需要可调用对象")
        self._unload_hooks.append(callback)
        return callback

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def add_menu_item(self, label, callback, *, icon="🧩", where="quick", order=50):
        """往右键快捷菜单加一项。callback 接收 pet。"""
        return self._manager.add_menu_item(self, label, callback, icon=icon,
                                           where=where, order=order)

    def add_control_center_page(self, title, builder, *, icon="🧩", key=None):
        """在控制中心加一页。

        builder 签名为 ``builder(page_frame, api)``，在 page_frame 里自由摆放控件；
        可用 ``api.pet_ui()`` 拿到桌宠同款控件（卡片/滚动区/按钮/配色）。
        """
        return self._manager.add_control_center_page(self, title, builder, icon=icon, key=key)

    def pet_ui(self):
        """桌宠控制中心的同款 UI 工具箱（配色、DPI、卡片与按钮构造器）。"""
        return self._manager.ui_kit()

    # ------------------------------------------------------------------
    # 外观：表情与动作
    # ------------------------------------------------------------------
    def register_emotion(self, name, image, *, description="", text_bearing=False):
        """注册一个新表情立绘（支持 PNG / 动图 GIF / WebP）。

        image 可以是绝对路径，也可以是相对插件目录的路径。
        注册后 ``change_pet_emotion`` 与 ``perform_pet_action`` 都能使用该表情。
        """
        return self._manager.register_emotion(self, name, image,
                                              description=description,
                                              text_bearing=text_bearing)

    def register_action(self, name, handler, *, description="", intensity="normal"):
        """注册一个自定义肢体动作，供 ``perform_pet_action(action=name)`` 调用。

        handler 签名为 ``handler(pet, intensity)``，可以做任意演出
        （多次 set_emotion、show_speech、调用 pet 的动画方法等）。
        """
        return self._manager.register_action(self, name, handler,
                                             description=description, intensity=intensity)

    # ------------------------------------------------------------------
    # 桌宠交互
    # ------------------------------------------------------------------
    def get_pet(self):
        """拿到桌宠实例（未启动时返回 None）。只在主线程操作 Tk 控件。"""
        return self._manager.host.pet if self._manager.host else None

    def call_on_ui(self, function, *args, **kwargs):
        """线程安全地在 UI 线程执行 function（工作线程里改界面必须用它）。"""
        pet = self.get_pet()
        if pet is None:
            return None
        return pet._tk_call(function, *args, **kwargs)

    def show_speech(self, text, emotion="默认", duration=3000):
        """让桌宠说一句话（气泡）。"""
        pet = self.get_pet()
        if pet is None:
            return False
        self.call_on_ui(pet.show_speech, str(text), emotion, int(duration))
        return True

    def set_emotion(self, name):
        """切换桌宠表情。"""
        pet = self.get_pet()
        if pet is None:
            return False
        self.call_on_ui(pet.set_emotion, str(name))
        return True

    def get_config(self, key=None, default=None):
        """读取桌宠配置（config.json）。key 为 None 时返回整份配置的副本。"""
        return self._manager.get_config(key, default)

    def set_config(self, key, value):
        """修改并保存桌宠配置（会写入 config.json 并热生效）。"""
        return self._manager.set_config(key, value)

    def read_skill(self, name):
        """读取技能库中某个技能的 SKILL.md 正文（没有则返回 None）。"""
        return self._manager.read_skill(name)

    def list_skills(self):
        """列出技能库里的技能名。"""
        return self._manager.list_skills()

    # ------------------------------------------------------------------
    # 插件自己的持久化数据
    # ------------------------------------------------------------------
    @property
    def state(self):
        """插件自己的持久化字典，退出/重载时不会丢。

        改完记得 ``api.save_state()``（也可以在 register 里注册 on_unload 自动保存）。
        """
        if self._state is None:
            self._state = self._manager.load_state(self.name)
        return self._state

    def save_state(self):
        """把 ``api.state`` 写回 ``data/plugins/<插件名>.json``。"""
        return self._manager.save_state(self.name, self.state)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _run_unload_hooks(self):
        for callback in list(self._unload_hooks):
            try:
                callback()
            except Exception as exc:
                self.log(f"卸载回调出错: {type(exc).__name__}: {exc}")
        self._unload_hooks = []

    def __repr__(self):
        return f"<PluginAPI {self.name}>"
