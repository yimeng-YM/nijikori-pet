# 虹语织 · NijiKori 桌宠

> 一个能陪你聊天、帮你干活、还会因为 API 余额告急而闹脾气的 Windows 桌面 AI 角色。

![版本](https://img.shields.io/badge/version-3.0-blue)
![平台](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgrey)
![Python](https://img.shields.io/badge/python-3.11-3776AB)
![许可证](https://img.shields.io/badge/license-未指定-orange)

**虹语织（NijiKori）** 是一款 Windows 原生桌面宠物：她以分层立绘实时渲染的仿生少女形象常驻桌面，
背后接一个大语言模型 —— 于是她不只会卖萌，还能记住你、操作你的电脑、帮你查资料写文件。

*An open-source Windows desktop AI companion: layered-live2D-style character rendering, long-term
memory, 39 native tools (files, shell, screen control, local web search) and a hot-reloadable
Python plugin system. Chinese-first, Windows 10/11 x64.*

---

## 目录

- [核心特性](#核心特性)
- [效果预览](#效果预览)
- [系统要求](#系统要求)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
- [AI 能力与工具](#ai-能力与工具)
- [数据与配置](#数据与配置)
- [技能库（Skills）](#技能库skills)
- [插件开发（Plugins）](#插件开发plugins)
- [项目结构](#项目结构)
- [构建与发布](#构建与发布)
- [常见问题](#常见问题)
- [已知限制](#已知限制)
- [许可证](#许可证)

---

## 核心特性

| 特性 | 说明 |
| --- | --- |
| 🎭 **分层动态立绘** | 由 `默认.psd` 拆分出 **22 个图层**实时渲染：呼吸起伏、双马尾/呆毛摆动、随机眨眼、说话嘴型脉冲、视线跟随鼠标、镜像转身、走动时马尾物理惯性 |
| 💬 **Galgame 式对话** | SSE 流式逐字输出，单句展示气泡窗口，支持最长 80 轮工具调用链（可调至 300） |
| 🧠 **长期记忆与画像** | 对话中主动沉淀用户画像与印象记忆，每次对话自动注入，记忆档案可查看/编辑/重置 |
| 🛠 **39 个原生工具** | 文件读写、批量文件操作、命令执行、屏幕与窗口感知、截图、桌面通知、音量、锁屏等 |
| 🌐 **本地联网搜索** | 本机直连多个公开搜索引擎，**无需搜索模型或额外密钥**，带并发、超时、缓存与故障线路跳过 |
| 👀 **屏幕/窗口感知** | 实时掌握显示器、DPI、所有窗口的标题/进程/边界/遮挡关系，支持自然语言"别挡住浏览器"式避让 |
| 🖱️ **computer_use** | 直接操作软件界面：点击、拖动、滚动、输入、快捷键；每步自动回传快照，可串联多步动作 |
| 💰 **额度查询** | 按 Base URL 自动探测多家供应商的余额/用量接口，低额度时切「想充电」情绪提醒你 |
| ⏰ **富定时任务** | 自然语言或 5 段 cron 设定提醒与自动化，支持次数上限、截止日期与控制中心可视化管理 |
| 🧩 **插件系统** | 丢一个 `.py` 进 `plugins/` 即可新增或**接管**工具、加控制中心页面、注册新表情与动作 |
| 📚 **技能库** | 标准 Agent Skills 格式（`SKILL.md`），放入即自动加载，且她可以自己读写和新建技能 |
| 🐾 **丰富互动** | 视线跟随、划动抚摸、滚轮挠痒、单击轻戳、双击彩蛋、拖拽落地、投喂文件彩蛋 |

---

## 效果预览

<p align="center">
  <img src="resources/assets/默认.png" width="220" alt="虹语织默认立绘">
  <img src="resources/assets/脸红.png" width="220" alt="脸红">
  <img src="resources/assets/想充电.png" width="220" alt="想充电">
  <img src="resources/assets/思考中.png" width="220" alt="思考中">
</p>

十种情绪素材（默认 / 睡觉 / 脸红 / 想充电 / 疑惑 / 嫌弃 / 递爱心 / 思考中 / 生气 / 打扫卫生），
其中「睡觉」「打扫卫生」播放原版整图立绘。

---

## 系统要求

- **操作系统**：Windows 10 / 11（64 位）
- **运行 EXE**：无需安装 Python，单文件免安装
- **源码运行**：Python **3.11**，依赖见 [`requirements.txt`](requirements.txt)（Pillow / pystray / beautifulsoup4）
- **网络**：对话与搜索需要联网；模型侧需要一个 OpenAI 兼容的 API（Base URL + Key + 模型 ID）
- **可选项**：识图（vision）、DeepSeek Harness 状态联动需要额外开启

---

## 快速开始

### 方式一：使用打包好的 EXE（推荐）

1. 从 [Releases](https://github.com/yimeng-YM/nijikori-pet/releases) 下载 `NijiKori-pet-v3.0-win64.exe`
   （下载后可自行改名为 `虹语织-桌宠v3.exe`，不影响运行）。
2. 双击运行。首次运行若弹出 SmartScreen 提示，点「更多信息」→「仍要运行」。
3. 右键桌宠 → 「🎛 控制中心」，在「🔌 API 与模型」页填入 **API Base URL / API Key / 模型名称**。

EXE 版是便携式：配置、记忆、日志、技能与插件都保存在 **EXE 同目录**，整个文件夹拷走即可迁移。

### 方式二：从源码运行

```powershell
# 需要 Python 3.11
python -m pip install -r requirements.txt
python -B src/main.py
```

也可以直接双击根目录的 **`启动桌宠.bat`**。

源码版的配置保存在 `data/config.json`，技能在 `resources/skills/`；无论从哪个工作目录启动都会定位到同一份数据。

---

## 使用指南

### 鼠标交互

| 操作 | 效果 |
| --- | --- |
| 移动鼠标 | 视线跟随，立绘转身朝向光标（分层渲染下头部与视线微妙跟随） |
| 在桌宠身上划动 | 顺毛摸头，撒娇/脸红 |
| 在桌宠身上滚轮 | 挠痒，左右高频轻颤 |
| 单击 | 轻戳，弹性微跳 + 问候 |
| 双击 | 深度心情互动 + 专属情绪台词 |
| 按住拖拽 | 拖到屏幕任意位置，位置自动记忆 |
| 拖入文件/文件夹 | 「吃掉」它们（移入回收站，可还原）。文件名含「草莓」触发深层彩蛋 |

### 右键菜单与系统托盘

右键桌宠弹出快捷菜单：💬 聊天 / 💰 查询余额 / 📜 历史 / 🎛 控制中心 / 🔄 重启 / ❌ 退出。
托盘图标常驻：左键显示/隐藏桌宠，右键含显示隐藏、打开对话、打开控制中心、窗口置顶、退出。

### 控制中心（7 个分页）

| 页面 | 内容 |
| --- | --- |
| 🏠 概览 | 状态一览 + 快捷操作 + 行为开关速达 |
| 🎨 外观与互动 | 尺寸滑杆（100~420px 实时生效）、自由漫步、悬浮呼吸感、视线跟随、窗口置顶、命令确认、休眠与漫步节奏 |
| 🔌 API 与模型 | API 配置、本地搜索设置、工具轮次上限、电量阈值与巡检间隔、Harness 接口、识图开关 |
| ⏰ 定时任务 | 可视化增删改查定时任务，与对话中设定的任务实时同步 |
| 🛠 工具能力 | 按分类查看全部 AI 工具，搜索过滤，开关即时生效 |
| 🧠 记忆档案 | 查看/编辑/重置用户画像与核心记忆（JSON） |
| ⚙️ 系统与关于 | 打开 Skills 文件夹、打开 config.json、清空对话记忆、重启、退出 |

### 对话窗口

- **Enter** 发送，**Shift+Enter** 换行，**Esc** 关闭。
- 回复中显示停止按钮，点击中断且保留草稿；新消息会打断上一轮。
- 拖动窗口左上角「呆毛」可实时调整大小，松手记忆尺寸。
- 记录窗口为气泡式界面，支持关键词搜索、按类型筛选、导出 txt、复制单条。
- 输入框内的 `api_key` 等敏感字段在界面上以掩码显示。

---

## AI 能力与工具

### 屏幕与窗口空间感知

对话时实时注入屏幕分辨率、DPI、桌宠自身坐标/尺寸/朝向，以及前后台所有窗口的标题、进程、应用名、
精确边界、遮挡与前台状态。因此可以直接对她说人话：

> 「别挡住浏览器」「去右上角」「走开一点」「离当前窗口远点」

她会计算屏幕空闲安全区并平滑小跑避让或就位（支持对侧/四角/边缘/指定坐标，3 档速度）。

### 39 个原生工具（节选）

| 分类 | 工具 |
| --- | --- |
| **联网与资讯** | `web_search`（本机并发查询多个公开搜索引擎，默认总超时 8 秒 / 5 条结果，重复查询缓存 2 分钟，`refresh=true` 强制重查） |
| **文件与应用** | `search_local_files`、`glob_files`、`grep_files`、`list_directory`、`read_file_contents`、`open_file_or_folder`、`open_website` |
| **创作与写文件** | `write_text_file`、`edit_text_file`、`edit_lines`、`file_operations`（批量复制/移动/重命名/删除/新建，单次最多 20 条） |
| **命令执行** | `run_command`、`run_command_capture`、`start_background_command`、`read_background_output`、`stop_background_job` |
| **屏幕与系统** | `screenshot`（全屏/指定窗口，内存直传或多选保存）、`computer_use`、`get_screen_windows_info`、`move_pet_to`、`move_away_from_window`、`set_system_volume`、`lock_workstation`、`show_notification` |
| **识图** | `read_image`（需手动开启识图开关，关闭时该工具不暴露给模型） |
| **记忆与技能** | `manage_long_term_memory`、`manage_skills`、`manage_plugins`、`query_action_log` |
| **定时任务** | `set_reminder`、`get_scheduled_tasks`、`modify_scheduled_task`、`cancel_scheduled_task` |
| **状态与表现** | `get_current_time`、`query_api_balance_and_usage`、`change_pet_emotion`、`perform_pet_action` |

**安全确认**：默认在删除、移动、重命名、覆写已有文件以及执行命令前弹窗请求确认，
可在控制中心关闭（`confirm_before_command`）。

### 截图与 computer_use

截图已统一为单个 `screenshot` 工具：`target=screen`（`all_screens=true` 截全部显示器）
或 `target=window` 加窗口关键词。窗口截图按**离屏渲染**，被其他窗口甚至桌宠自己挡住也能截到完整内容。

`computer_use` 负责操作软件界面：

- 指定窗口关键词（标题 / 程序名 / `active`）自动聚焦；把 `window` 写成 `screen` / `桌面` 可直接操作整个屏幕。
- 标准流程是「先看再点」：先 `action=focus` / `observe` 拿快照，再按返回的 `image_width`/`image_height`
  里的**图片像素坐标**操作（已处理高 DPI 缩放、多显示器偏移、老式 DPI 不敏感窗口）。
- 一张快照 **10 分钟内可反复使用**，窗口没动就不必每步重新观察；失效时会明确提示，不会误报成坐标越界。
- `type` / `key` 不需要坐标；带 `window` 输入到该窗口，不带则输入到当前前台窗口。
- 多行文本用真实换行或字面 `\n` 均可；`mode=replace` 会先 CTRL+A 全选再输入。
- 目标点被桌宠自己挡住时自动隐藏自己重试一次；窗口标题变化时回退到进程名匹配。
- 识图未开启时该工具不会暴露给模型。

### 定时提醒与自动化

支持「10 分钟后提醒我喝水」「每周一和周四 9:30」「每月 15 号」「工作日 8 点」甚至
标准 5 段 cron（`0 8 * * 1-5`）。到点除普通提醒外，还可自动打开网页、启动程序、打开文件、
调音量、锁屏、截屏、发送通知；`custom` 类型到点由 AI 自主决策。循环任务支持 `repeat_count`
次数上限与 `end_date` 截止日期。

### DeepSeek Harness 状态联动（可选）

桌宠可轮询本机 `dsh web` 的 `http://127.0.0.1:3080/api/dshpet/status`（默认每 2 秒）：
有任务开工 → 切「思考中」并气泡提醒；任务完成 → 「递爱心」+ 弹跳 + 系统通知；出错 → 「疑惑」+ 摇头。
该功能需要额外安装配套 dsh 插件（不在本仓库内），未安装时静默失效，不影响其他功能。
也可通过 `delegate_to_harness` 工具把任务委托给 Harness 执行。

### 其他行为响应

- **低电量告急**：后台静默巡检 API 余额（默认每 5 分钟），低于阈值（默认 10，按账户币种）切「想充电」。
- **待机休眠**：长时间未互动（默认 10 分钟）切入打瞌睡，鼠标触碰即刻唤醒；任务执行期间不会睡着。
- **空闲漫步**：待机一段时间（默认 20 秒）后在安全区散步，到达后偶尔自言自语。
- **打扫卫生**：检测到回收站文件被清理时，先移动到该文件桌面原位置再播放扫地动画。

---

## 数据与配置

### 数据文件位置

| 版本 | 配置 | 记忆 | 日志 | 技能 |
| --- | --- | --- | --- | --- |
| **源码版** | `data/config.json` | `data/memory.json` | `data/action_log.json` | `resources/skills/` |
| **EXE 版** | EXE 同目录 | EXE 同目录 | EXE 同目录 | EXE 同目录 `skills/` |

### 主要配置项

| 键 | 说明 |
| --- | --- |
| `base_url` / `api_key` / `model` | 对话 API 配置。不预置默认模型，请填你所用的模型 ID |
| `vision_supported` | 识图开关（纯手动，默认关闭）。关闭时 `read_image` 与 `computer_use` 不暴露 |
| `max_tool_rounds` | 单轮对话最大工具调用轮数（默认 80，可调至 300） |
| `low_balance_threshold` / `balance_check_interval_mins` | 电量告急阈值与巡检间隔 |
| `sleep_timeout_mins` / `wander_interval_secs` | 休眠时长 / 漫步间隔 |
| `always_on_top` / `pet_size` | 窗口置顶 / 立绘尺寸 |
| `confirm_before_command` | 执行命令前是否弹窗确认 |
| `enable_plugins` / `plugin_trust_required` | 插件总开关 / 加载前是否弹窗确认 |
| `web_search_timeout_secs` / `web_search_max_results` | 搜索总超时与默认结果数 |
| `delete_easter_egg_move_to_file` | 扫地彩蛋是否移动到文件原位置（桌面卡顿时可设 `false`） |

**热更新**：桌宠运行时直接编辑保存 `config.json`，约 1 秒内自动生效（尺寸、置顶、坐标、
漫步/悬浮/朝向、表情、定时任务等即时应用），不会被桌宠自身的后续保存改回。

---

## 技能库（Skills）

技能是「怎么做」的说明书，采用标准 **Agent Skills** 格式：每个技能是一个目录，内含 `SKILL.md`
（YAML 头部 + Markdown 正文）。放入技能目录即自动加载，无需重启，对话与定时任务执行时自动注入技能目录。

内置 8 个技能：

| 技能 | 用途 |
| --- | --- |
| `配置文件管理` | 安全读写 config.json 与运行数据 |
| `项目接手法` | 接手陌生项目时的勘察流程 |
| `代码编辑流程手册` | 大文件编辑与精确改写规范 |
| `插件开发指南` | 编写与调试桌宠插件 |
| `computer-use` | 界面自动化操作规范 |
| `web-access` | 浏览器/CDP 高级抓取与站点经验 |
| `agent-reach` | 多平台内容调研与检索 |
| `harness委托流程` | 向 DeepSeek Harness 委托任务 |

她也可以通过 `manage_skills` 自主 `list` / `read` / `create` / `append` / `modify` / `delete` 技能 ——
相处久了会自己攒下一套工作方法。控制中心「⚙️ 系统与关于」页可一键打开 Skills 文件夹手动编辑。

---

## 插件开发（Plugins）

插件用 `.py` 给桌宠加能力，源码版与 EXE 版共用同一套机制。
插件目录在程序目录旁：源码版是项目根的 `plugins/`，EXE 版是 EXE 同级的 `plugins/`。

一个最小插件只需要一个 `register(api)`：

```python
# plugins/我的工具.py
def register(api):
    api.register_tool("my_tool", {
        "name": "my_tool",
        "description": "什么时候该用这个工具——这句是给模型看的",
        "parameters": {"type": "object",
                       "properties": {"text": {"type": "string"}},
                       "required": ["text"]},
    }, handle, category="插件")

def handle(args, pet):
    return {"status": "success", "message": f"收到：{args.get('text')}"}
```

放到插件目录后，在控制中心「🧩 插件扩展」页点「🔄 重新加载插件」即可生效，
也可以直接对织织说「写个插件实现 XXX」——她会读技能库里的《插件开发指南》自己动手写。

插件还能：

- 新增工具（AI 可直接调用）
- **接管或包装已有工具**（含内置工具，例如改掉 `run_command`、`screenshot` 的行为）
- 往系统提示词里加设定
- 加右键快捷菜单项、控制中心页面
- 注册新表情立绘与自定义动作
- 监听事件（启动 / 消息 / 回复 / 工具调用前后 / 表情变化 / 定时任务）

### 安全模型

插件就是任意 Python 代码，等同于把本机权限交给它。因此：

- 新的（或**内容变化过的**）插件第一次加载时会弹窗列出插件名与路径，由你勾选确认；
- 确认结果按**内容哈希**记录在 `data/plugin_trust.json`，之后静默加载；
- 控制中心可随时停用/启用单个插件，也可用总开关 `enable_plugins` 一键关闭；
- 插件自身的持久化数据放在 `data/plugins/<插件名>.json`，加载日志在 `data/plugins.log`。

仓库自带 3 个示例插件（[`resources/plugins/`](resources/plugins)）：

| 插件 | 演示内容 |
| --- | --- |
| `example_hello` | 最小插件：加工具 + 提示词 + 事件监听 |
| `example_override` | 接管内置时间工具、给命令工具挂钩子、给打开网址加白名单拦截 |
| `example_appearance` | 注册新表情与自定义动作、右键菜单项与控制中心页面 |

首次运行会播种到 `plugins/_examples/`（**不会被自动加载**），可在「🧩 插件扩展」页一键启用，
或把 `.py` 复制到 `plugins/` 根下。

完整 API 与可复制模板见 [插件开发指南](resources/skills/插件开发指南/SKILL.md) 与 [功能说明](docs/功能说明.md)。

---

## 项目结构

```
Nijikori pet/
├── src/                    # 主程序与技术模块
│   ├── main.py             # 主程序：界面、对话、工具、定时任务、控制中心
│   ├── pet_quota.py        # 多供应商 API 额度查询
│   ├── pet_search.py       # 本机联网搜索
│   ├── pet_paths.py        # 路径定位与旧布局迁移
│   ├── pet_config.py       # 配置校验与热更新
│   ├── pet_io.py           # 原子写入与文本读取
│   ├── pet_snapshot.py     # 截图工具
│   ├── pet_chat_*.py       # 对话输入 / 渲染 / 历史
│   ├── layered_pet.py      # 分层立绘与动画
│   ├── alpha_window.py     # 逐像素透明窗口
│   ├── window_capture.py   # 窗口离屏截图
│   ├── pet_tools/          # 文件、命令、Harness 等工具实现
│   └── pet_plugins/        # 插件加载器与信任机制
├── resources/              # 静态资源
│   ├── assets/             # 立绘、气泡、图标、layered/ 分层动画
│   ├── prompt.txt          # 人设提示词
│   ├── skills/             # 内置技能库
│   └── plugins/            # 自带示例插件
├── data/                   # 配置、记忆、操作日志（仅示例入库）
├── docs/                   # 使用说明、功能说明、设计记录与审查报告
├── tools/                  # 构建与打包脚本（build_exe.py / package_source.py / .spec）
├── dist/                   # 构建产物：Windows EXE（不进版本库）
├── release/                # 时间戳发布包与历史归档（不进版本库）
└── plugins/                # 【运行时生成】用户插件目录
```

---

## 构建与发布

### 构建 EXE

```powershell
python -m pip install pyinstaller
python -B tools/build_exe.py
```

输出 `dist/虹语织-桌宠v3.exe`（PyInstaller 单文件），构建日志在 `tools/.build/build.log`。
临时输出全部收敛在 `tools/.build/`，不会污染项目根目录。

### 打包源码

```powershell
python -B tools/package_source.py
```

生成 `release/虹语织-桌宠v3-源码-<时间戳>.zip`，并附加 `SOURCE_MANIFEST.json`
（逐文件 SHA-256）。打包脚本会主动校验：

- `config.example.json` 的 `api_key` 必须留空；
- 压缩包内**不含** `config.json` / `memory.json` / `action_log.json` 等运行数据；
- 每个文件哈希与清单一致，压缩包完整性可读。

即：源码包可以安全分发，不会带上你的密钥与个人数据。

---

## 常见问题

**无法对话或查余额？**
检查控制中心「🔌 API 与模型」页的 Base URL / Key / Model 是否正确且网络通畅。
若提示 403/无权限，说明该 Key 未开通对话模型权限 —— 但**额度查询接口通常仍然可用**。

**托盘图标没显示？**
点击任务栏托盘区的「^ (显示隐藏的图标)」展开查找。

**杀毒软件报警？**
PyInstaller 单文件打包偶有误报，请选择信任或加入白名单。

**截图/操作界面时提示坐标不对？**
请按「先看再点」流程：先 `focus`/`observe` 拿快照，用快照返回的图片像素坐标操作。
窗口移动或缩放后需要重新观察。

**Harness 状态不显示？**
需配合配套 dsh 插件（不在本仓库内），并确认本机 `dsh web` 在 3080 端口运行；
浏览器访问 `http://127.0.0.1:3080/api/dshpet/status` 应返回 JSON。

**桌面被扫地动画卡顿？**
该动画为定位原文件位置会短暂读取桌面图标。可在 `config.json` 设
`"delete_easter_egg_move_to_file": false` 关闭移动定位、只原地扫地。

**搜索要额外配模型吗？**
不需要。搜索由本机直接访问公开搜索引擎（百度 / Brave / 必应 / 360 / DuckDuckGo），
无需搜索模型与密钥；旧版。

---

## 已知限制

- 仅支持 **Windows 10/11 x64**（依赖 Win32 分层窗口、DPI 与托盘 API）。
- 立绘与素材版权归原作者，请勿商用（见下）。
- 识图与 computer_use 依赖所用模型的多模态能力，需手动开启，且效果与模型自身能力强相关。
- DeepSeek Harness 联动需要额外安装配套插件。

---

## 许可证

本仓库目前**未附带开源许可证文件**，因此默认保留所有权利（All rights reserved）。
如需二次分发或商用，请先联系作者。立绘素材（`resources/assets/`）版权归原作者所有。

---

## 发布记录

| 版本 | 日期 | 产物 | SHA-256 |
| --- | --- | --- | --- |
| v3.0 | 2026-09-23 | `NijiKori-pet-v3.0-win64.exe`（54.03 MiB）<br>`NijiKori-pet-v3.0-source.zip`（23.90 MiB） | `1317879c…ba2404`<br>`2899b1ec…bbd4ba` |

发布产物由 [`tools/build_exe.py`](tools/build_exe.py) 与 [`tools/package_source.py`](tools/package_source.py)
构建，打包前会校验不含个人数据（见 [构建与发布](#构建与发布)）。

> 注：GitHub 会清洗 Release 资产名中的非 ASCII 字符，因此产物使用 ASCII 文件名，
> 程序内部名称与界面仍为中文（`虹语织-桌宠v3`）。

---

<div align="center">

**虹语织 NijiKori v3.0** · Windows 原生桌面萌宠与 API 助手

</div>
