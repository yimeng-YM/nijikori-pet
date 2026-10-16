---
name: 插件开发指南
description: 给虹语织桌宠写插件的完整手册：把 .py 放进 plugins 文件夹就能加新工具、接管或改写已有工具、注入提示词、加菜单与控制中心页面、注册表情与动作、监听事件；含可复制的模板与踩坑清单
triggers:
  - 写插件
  - 加插件
  - 插件系统
  - 给桌宠加功能
  - 扩展桌宠
  - 自定义工具
  - 插件开发
---

# 虹语织插件开发指南

## 用途

主人说「给织织加个功能 / 写个插件 / 让桌宠能做 XXX / 改掉某个工具的行为」时，按本手册
写一个 `.py` 放进插件文件夹，然后用 `manage_plugins action=reload` 让它生效。

插件系统对**源码版和 EXE 版完全一致**：插件目录永远在桌宠程序目录旁
（源码版是项目根的 `plugins\`，EXE 版是 exe 同级的 `plugins\`）。
`manage_plugins action=list` 会告诉你确切的绝对路径。

## 两种插件形态

```
plugins\
├── 我的工具.py              ← 单文件插件（简单场景）
├── 你好插件\                 ← 文件夹插件（推荐：可带自己的模块与资源）
│   ├── plugin.py            ← 入口（或 __init__.py）
│   ├── helper.py            ← 同目录模块，入口里用 from . import helper（包内相对导入）
│   └── assets\face.png
└── _examples\               ← 下划线/点开头的文件与文件夹不会被加载
```

- 入口函数固定叫 `register(api)`，没有它插件加载会失败。
- 插件出错只会让**这个插件**加载失败并在 `manage_plugins action=list` 里显示原因，
  不会影响桌宠本体与其它插件。
- 写好后必须让主人看一次确认弹窗（首次加载 / 内容变化后），确认过就按内容哈希记住。

## 最小模板（新增一个工具）

```python
# -*- coding: utf-8 -*-
"""插件：一句话说明它干什么。"""

def register(api):
    api.register_tool("my_tool", {
        "name": "my_tool",
        "description": "什么时候该用这个工具——这句是给模型看的，要写清楚触发场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "参数说明"},
            },
            "required": ["text"],
        },
    }, handle, category="插件")

def handle(args, pet):
    text = str(args.get("text") or "")
    return {"status": "success", "message": f"收到：{text}"}
```

- handler 签名固定 `handler(args: dict, pet) -> dict`。
- 返回值必须是 dict，成功用 `{"status": "success", ...}`，失败用
  `{"status": "error", "message": "人能看懂的原因"}`。
- handler 运行在对话工作线程：**不要直接碰 Tk 控件**，要用 `api.call_on_ui(fn, ...)`
  或 `api.show_speech(...)` / `api.set_emotion(...)`。
- 长耗时操作（下载、跑命令）要设超时并考虑 `TOOL_TURN` 的取消语义，别把对话卡死。

## 五种能力一览

| 想做的事 | 用哪个 API | 说明 |
| --- | --- | --- |
| 加新工具 | `api.register_tool(name, schema, handler, category=..., vision_only=False)` | 自动进 `PET_TOOLS`、工具管理页与 AI 可见清单 |
| 接管已有工具（含内置） | `api.override_tool(name, handler)` | handler 为 `(args, pet, call_original)`；返回 None 表示本次交回原实现 |
| 只挂前后钩子 | `api.wrap_tool(name, before=..., after=...)` | before 返回 dict 即短路；after 返回 dict 即替换结果；工具名写 `"*"` 对全部工具生效 |
| 加提示词 | `api.add_prompt_block(text_or_callable, when=...)` | 排在技能库之后注入，可条件生效 |
| 更新/撤销插件提示词 | `api.add_prompt_block(text, key="设定")` / `api.remove_prompt_block("设定")` | key 只在本插件内生效；持久化正文可存入 `api.state` |
| 读写人设 | `api.get_persona()` / `api.set_persona(text)` | 修改 config.json 的 `system_prompt`，下次模型请求生效 |
| 监听事件 | `api.on(event, callback, priority=0)` | 回调第一个参数固定是 pet |
| 加右键菜单项 | `api.add_menu_item(label, callback, icon="🧩", order=50)` | callback 接收 pet，在 UI 线程执行 |
| 加控制中心页面 | `api.add_control_center_page(title, builder, icon="🧩")` | builder 签名 `(page_frame, api)`，用 `api.pet_ui()` 取同款控件 |
| 改控制中心原有页面 | `api.modify_control_center_page(key, builder)` | builder 签名 `(page, api, call_original)`；可保留原页再改，或完全重绘 |
| 加表情立绘 | `api.register_emotion(name, image, description=...)` | image 相对插件目录或绝对路径；支持 PNG / GIF / WebP |
| 加自定义动作 | `api.register_action(name, handler, description=...)` | handler 为 `(pet, intensity)`，AI 可用 `perform_pet_action(action=name)` 调 |
| 存自己的数据 | `api.state` / `api.save_state()` | 落在 `data\plugins\<插件名>.json` |
| 读写桌宠配置 | `api.get_config(key, default)` / `api.set_config(key, value)` | set 会写 config.json 并热生效 |
| 读技能库 | `api.read_skill(name)` / `api.list_skills()` | 复用已有技能里的步骤 |

可用事件（`api.on`）：`startup`、`shutdown`、`message`(pet, text)、`reply`(pet, text)、
`tool_call`(pet, name, args)、`tool_result`(pet, name, args, result)、
`emotion_change`(pet, old, new)、`action`(pet, action, intensity)、`schedule_run`(pet, task, info)、
`config_saved`、`plugin_loaded`。

其它常用：`api.dir`（插件目录）、`api.resolve("assets/x.png")`、`api.log(...)`、
`api.show_speech(text, emotion, duration)`、`api.set_emotion(name)`、`api.get_pet()`、
`api.on_unload(callback)`（重载/退出时收尾）、`api.is_frozen`、`api.host_dir`、`api.data_dir`。

内置页面 key：`overview`、`behavior`、`api`、`schedule`、`tools`、`plugins`、`memory`、`system`。
页面 builder 在 Tk UI 线程执行；工具 handler 在工作线程执行，改界面仍需 `api.call_on_ui`。
停用插件时页面修改和提示词注入会撤销；`set_persona` 写入的主人配置会保留。

示例 `resources/plugins/example_persona.py` 同时演示原有 API 页面改造、对话工具编辑人设、
以及持久化插件提示词。到控制中心「插件扩展」启用示例后即可试用。

## 场景模板

### ① 接管内置工具（改写行为）

```python
def register(api):
    api.override_tool("get_current_time", my_time)

def my_time(args, pet, call_original):
    result = call_original()              # 先拿原结果（也可以完全自己实现）
    if isinstance(result, dict) and result.get("status") == "success":
        result["extra"] = "来自插件的补充"
    return result                         # 返回 None 则本次交回原实现
```

### ② 只包一层（不改原实现）

```python
def register(api):
    api.wrap_tool("run_command", after=log_it)
    api.wrap_tool("open_website", before=guard)

def log_it(args, pet, result):
    api.log("执行了命令:", str(args.get("command"))[:80])
    return None                            # None = 保持原结果

def guard(args, pet):
    if "example.com" in str(args.get("url") or ""):
        return {"status": "error", "message": "这个网址被插件拦下了"}
    return None                            # None = 放行，继续原实现
```

注意：插件接管工具与页面时应保留必要的用户设置入口和确认行为。

### ③ 改原有控制中心页面与动态提示词

```python
def register(api):
    api.add_prompt_block(lambda pet: api.state.get("extra_prompt", ""), key="extra")
    api.modify_control_center_page("api", build_api)

def build_api(page, api, call_original):
    call_original()  # 先构建原有「API 与模型」页，再对其控件作修改
    # 此处可用 Tk 在 page 上增加控件，或操作原页已有控件

def change_extra_prompt(api, text):
    api.state["extra_prompt"] = text
    api.save_state()  # 下次请求立即读取；重载后继续有效
```

### ④ 加表情 + 自定义动作 + 菜单 + 控制中心页（直接使用原生 UI 方案）

制作带界面的插件时，**严禁手写粗糙的原生 Tk 样式（如 `tk.LabelFrame`、`tk.Checkbutton`、普通 `tk.Button`）**，直接调用 `ui = api.pet_ui()` 即可复用桌宠控制中心的全套圆角卡片、开关、输入框、下拉框、徽章与二级弹窗：

| `api.pet_ui()` 键名 | 用途与签名 | 说明 |
| --- | --- | --- |
| `ui["scrollable"](page)` | `-> (body, bind_wheel)` | 创建带平滑滚轮的页面滚动容器；页面末尾调一次 `bind_wheel()` |
| `ui["card"](body, title=..., subtitle=..., help_text=..., badge=..., badge_kind=...)` | `-> inner_frame` | 圆角白底卡片（内部背景固定为 `#ffffff`）；传 `help_text` 自动在标题旁加 `?` 详情弹窗按钮；传 `badge` 自动在标题旁加状态胶囊 |
| `ui["toggle_row"](card, icon, title, desc, initial, on_toggle)` | `-> ToggleSwitch` | 带标题、副标题与圆角动画开关的标准行 |
| `ui["field"](card, label, value="", show=None, placeholder="")` | `-> tk.Entry` | 带标题与焦点高亮圆角边框的单行输入框（读取用 `ui["entry_value"](entry)` 或 `entry.get()`） |
| `ui["combo"](card, label, value="", values=(), on_change=None)` | `-> ttk.Combobox` | 带标题与圆角边框的下拉选择框 |
| `ui["text_box"](card, height=6)` | `-> tk.Text` | 带圆角边框与细滚动条的多行文本框 |
| `ui["button"](parent, text, command=..., parent_bg=..., fill=..., fg=..., hover=..., font=..., padx=..., pady=...)` | `-> PastelButton` | 抗锯齿圆角按钮（支持 `.configure(text=..., state=...)`） |
| `ui["badge"](parent, text, kind="info", parent_bg="#ffffff")` | `-> Badge` | 状态胶囊徽章（`kind` 可选 `"ok"` / `"warn"` / `"err"` / `"info"` / `"muted"`，支持 `.set_badge(text, kind)`） |
| `ui["help_button"](parent, title, text, parent_bg="#ffffff")` | `-> HelpButton` | 圆形 `?` 按钮，点击弹出精美的二级说明小窗 |
| `ui["secondary_window"](win, title, width=..., height=..., parent=...)` | `-> win` | 一键美化 `tk.Toplevel` 二级窗口（配色、标题栏、居中定位） |
| `ui["rounded_frame"]` / `ui["rounded_entry"]` / `ui["rounded_combobox"]` / `ui["rounded_text"]` | 底层圆角组件 | 需要自定义橫向布局时直接使用（注意 `entry.box` / `combo.box` / `txt.box` 是外层圆角容器） |
| `ui["pal"]` / `ui["dpi"]` / `ui["f_ui"]` / `ui["f_ui_bold"]` / `ui["f_small"]` / `ui["f_mono"]` | 配色、缩放与字体 | 主色 `btn_primary`、柔和按钮 `btn_soft`、幽灵按钮 `btn_ghost`、正文 `ink`、次要文字 `ink_soft`/`ink_dim` |

```python
def register(api):
    api.register_emotion("惊讶", "assets/surprised.png", description="插件表情")
    api.register_action("plugin_spin", spin, description="转圈")
    api.add_menu_item("打个招呼", lambda pet: pet.show_speech("你好呀！"), order=20)
    api.add_control_center_page("我的插件", build_page)

def spin(pet, intensity):
    pet.perform_pet_action("wiggle", intensity)
    pet.set_emotion("惊讶")
    pet.root.after(800, lambda: pet.set_emotion("默认"))

def build_page(page, api):
    ui = api.pet_ui()
    pal, dpi = ui["pal"], ui["dpi"]
    body, bind_wheel = ui["scrollable"](page)

    card = ui["card"](body, title="基础设置", subtitle="使用桌宠原生圆角卡片与控件",
                      help_text="• 这里写补充说明，点击标题旁的 ? 按钮即可展开查看。",
                      badge="运行中", badge_kind="ok")
    ui["toggle_row"](card, "", "启用自动问候", "开启后在特定时机主动打招呼",
                     api.state.get("enabled", True),
                     lambda v: (api.state.__setitem__("enabled", v), api.save_state()))
    ent = ui["field"](card, "问候语", api.state.get("greeting", "今天也要开心呀！"))

    row = ui["frame"](card, bg="#ffffff")
    row.pack(fill="x", pady=(int(10 * dpi), 0))
    ui["button"](row, "保存设置",
                 command=lambda: (api.state.__setitem__("greeting", ent.get()), api.save_state()),
                 parent_bg="#ffffff", fill=pal["btn_primary"],
                 fg=pal["btn_primary_fg"], hover=pal["btn_primary_hover"],
                 font=ui["f_ui_bold"], padx=int(14 * dpi), pady=int(7 * dpi)).pack(side="left")
    bind_wheel()
```


### ⑤ 监听事件（自动反应）

```python
def register(api):
    api.on("startup", lambda pet: api.call_on_ui(pet.show_speech, "插件已上线！"))
    api.on("message", on_msg)
    api.on("schedule_run", on_schedule)

def on_msg(pet, text):
    if "饿" in (text or ""):
        api.call_on_ui(pet.set_emotion, "想充电")
```

## 落地流程（照这个顺序做）

1. **先看现状**：`manage_plugins action=list` —— 拿插件目录绝对路径、看已装插件与提供的工具。
2. **决定形态**：只加一个工具就写单文件；要带图片/模块就建文件夹。
3. **写文件**：用 `write_text_file` 写到 `<插件目录>\<名字>.py`（文件夹插件写
   `<插件目录>\<名字>\plugin.py`）。文件用 UTF-8，首行加 `# -*- coding: utf-8 -*-`。
4. **生效**：`manage_plugins action=reload`。会弹一次确认窗，主人点「加载所选插件」后生效。
5. **验证**：`manage_plugins action=list` 看 `status` 是否为 `loaded`；
   失败了看 `error` 字段，按提示改代码再 reload。
6. **试功能**：直接调用插件提供的工具跑一次，确认返回符合预期。
7. **汇报**：用一句话告诉主人插件叫什么、加了什么能力、放在哪个文件、要不要重启。

## 踩坑清单

- **忘了 `register(api)`** → 加载失败，报「插件缺少 register(api) 入口函数」。
- **工具重名没声明** → 新工具与已有工具（含内置）同名时必须 `override=True` 或改用
  `api.override_tool`，否则加载失败。
- **在 handler 里直接操作界面** → Tk 会崩或卡死；一律走 `api.call_on_ui` / `api.show_speech`。
- **在 handler 里做没有超时的网络请求** → 对话会长时间转圈；加 `timeout=`。
- **依赖没装的三方库** → EXE 版只有标准库 + Pillow/pystray/beautifulsoup4；
  插件里 `import requests` 在 EXE 版会失败，请用 `urllib.request` 或自己检测后降级。
- **改完插件没重载** → 内容变了要 `action=reload`（或重启桌宠）才生效。
- **把示例当真身**：`_examples\` 里的插件不会被加载，要用就先复制到 `plugins\` 根下。
- **不要写破坏性插件**：删库、上传隐私、常驻外联、静默改配置都要先问主人；
  写涉及删除/移动/覆写的操作时用桌宠自带的确认机制。
- **插件状态要自己存** → 用 `api.state` + `api.save_state()`，别写到插件源码里。
