# 虹语织 · NijiKori 桌宠

Windows 桌面角色与 AI 助手，支持对话、记忆、技能、电脑工具和本地联网搜索。搜索由本机直接访问公开搜索引擎，无需单独的搜索模型或密钥。

能力可模块化扩展：把 `.py` 放进 `plugins/` 就能给桌宠加新工具、接管或改写已有工具，
源码版与打包好的 EXE 使用同一套插件机制（EXE 的插件目录就在 exe 同级）。

## 启动

使用 Python 3.11，首次运行先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

随后双击根目录的 **启动桌宠.bat**。也可以在根目录运行 `python -B src/main.py`。首次在控制中心填写对话 API 配置。

## 目录

| 位置 | 内容 |
| --- | --- |
| `src/` | 主程序、搜索模块、渲染器和 `pet_tools/` 工具包、`pet_plugins/` 插件系统 |
| `resources/` | `assets/` 立绘、`prompt.txt` 人设、`skills/` 技能库、`plugins/` 示例插件 |
| `plugins/` | 用户插件目录（运行时生成）：放进 `.py` 即可扩展桌宠 |
| `data/` | 本机配置、记忆、操作日志、插件信任与状态；发布包仅附空密钥示例和说明 |
| `docs/` | 使用说明、功能介绍、插件开发指南、验证记录与历史评审 |
| `tests/` | 搜索、路径迁移、重启、插件与源码打包回归测试 |
| `tools/` | 检查与打包脚本；构建缓存集中在 `.build/` |
| `dist/` | 最新构建的 Windows EXE |
| `release/` | 带时间戳的源码包、EXE 和历史归档 |

源码运行时，配置保存在 `data/config.json`，技能保存在 `resources/skills/`；从任何工作目录启动都会定位到同一份数据。旧源码根目录的三个运行数据文件会在启动时自动迁入 `data/`，遇到同名文件会停止迁移，避免覆盖。

EXE 保持便携用法：配置、记忆、日志、技能与插件仍保存在 EXE 同目录。

## 插件（用 .py 扩展或改写能力）

一个插件最少只要一个 `register(api)`：

```python
# plugins/我的工具.py
def register(api):
    api.register_tool("my_tool", {
        "name": "my_tool",
        "description": "什么时候该用这个工具——这句是给模型看的",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    }, handle, category="插件")

def handle(args, pet):
    return {"status": "success", "message": f"收到：{args.get('text')}"}
```

放到插件目录后，用控制中心「🧩 插件扩展」页的「🔄 重新加载插件」，或直接跟织织说
「写个插件实现 XXX」——她会读技能库里的「插件开发指南」自己动手。

插件还能：接管或包装已有工具（含内置工具）、往系统提示词加设定、加右键菜单项与控制中心页面、
注册新表情立绘与自定义动作、监听启动/消息/工具调用等事件。完整 API 与可复制模板见
[插件开发指南](resources/skills/插件开发指南/SKILL.md) 与 [功能说明](docs/功能说明.md)。

安全上，插件是任意 Python 代码：新的（或内容变化过的）插件第一次加载时会弹窗请你确认，
确认结果按内容哈希记在 `data/plugin_trust.json`，之后静默加载；控制中心可随时停用单个插件。
自带 3 个示例插件（`example_hello` / `example_override` / `example_appearance`），
首次运行播种在 `plugins/_examples/`（不会被自动加载），可一键启用。

## 检查与打包

在根目录执行：

```powershell
python -B -m unittest discover -s tests -v
python -B tools/check_web_search.py
python -B tools/check_plugins_gui.py
python -B tools/package_source.py
```

第二条会联网检查搜索效果；第三条会打开真实 Tk 窗口，自动验证插件确认弹窗、控制中心插件页、
插件页面与右键菜单项是否正常渲染（全程自动点击，临时目录，不影响本机数据）；
第四条生成不含个人配置、记忆、日志、缓存和 EXE 的源码 ZIP，并校验文件哈希。
构建独立 EXE：

```powershell
python -m pip install pyinstaller
python -B tools/build_exe.py
```

输出为 `dist/虹语织-桌宠v2.exe`，构建日志位于 `tools/.build/build.log`。

详细操作见 [使用说明](docs/使用说明.txt)，完整功能见 [功能说明](docs/功能说明.md)，搜索实现与验证见 [搜索改造记录](docs/SEARCH_REWORK_2026-09-06.md)。

## 截图与电脑操作（统一截图工具 + computer_use）

原来的 `take_screenshot` / `capture_window` / `take_snapshot` 已合并为一个 **`screenshot`** 工具：`target=screen`（`all_screens=true` 截全部显示器）或 `target=window` 加窗口关键词截指定窗口；窗口截图按窗口离屏渲染，被别的窗口或桌宠自己挡住也能截到完整内容。`save=false`（默认）时图片全程在内存中处理并直接注入当前对话，本轮结束释放，不写入持久聊天记录；`save=true` 或给 `save_path` 时保存成 PNG。识图关闭时该工具仍可用于保存截图。

**`computer_use`** 负责操作软件界面。指定窗口关键词（标题 / 程序名 / `active`）即自动聚焦该窗口；**不指定窗口时把 `window` 写成 `screen` / `桌面`，即可直接操作整个屏幕**（点任务栏、桌面图标、开始菜单都行）。支持点击 / 双击 / 拖动 / 滚动 / 输入文字 / 快捷键；**每一步操作后自动把最新快照注入对话**，不需要再手动截图和读图，还可以用 `snapshot_delay_ms` 等待界面加载、用 `steps` 一次执行多步。

体验优化（依据桌宠自己的实测报告）：

- **一张快照 10 分钟内可反复使用**：`last_observation` 可以连续驱动多次点击/输入，只有在窗口移动、缩放或进程变化时才需要重新观察；失效时会明确提示「快照已失效/已过期」，不再误报成坐标越界。
- **`type` / `key` 不再要求坐标**：带 `window` 直接输入到该窗口，不带 `window` 就输入到当前前台窗口（前台是桌宠自己会明确拒绝）。
- **多行文本可靠**：`text` 里的真实换行或字面 `\n` 都按回车处理；`mode=replace` 会先按 CTRL,A 全选再输入，用来整段覆盖文字。
- **桌宠挡住目标时自动让开**：引擎识别出目标点被桌宠自己覆盖后返回 `pet_blocks`，桌宠临时隐藏自己重试一次再恢复。
- **窗口标题变了也能继续用**：另存为/换文档后脚本会回退到进程名，并记住上次用该关键词命中的窗口；`PowerPoint`→POWERPNT、`Word`→WINWORD、`Edge`→msedge、`记事本`→notepad 等应用名可直接用。
- **steps 动作名与单步一致**：`double_click` / `doubleclick` / `dblclick`、`input`、`keys`、`wait` 都接受，写错会报错并列出合法动作。

标准流程是「先看再点」：第一次操作先用 `action=focus`（或 `observe`）拿到快照，再按返回的 `image_width`/`image_height` 里的**图片像素**坐标点击。坐标换算已处理高 DPI 缩放、多显示器偏移和老式 DPI 不敏感窗口，窗口被其他窗口甚至桌宠自己挡住也不影响截图（离屏渲染）。截整个屏幕时会临时把桌宠自己藏起来、拍完立刻恢复，避免它出现在画面里。

识图未开启时该工具不会暴露给模型。新版工具需要重启源码程序或使用重新构建的 EXE。
