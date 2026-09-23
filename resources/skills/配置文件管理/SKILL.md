---
name: 配置文件管理
description: 虹语织核心配置文件 config.json 的查看、修改、安全维护与参数调优指南
---

# 配置文件管理与维护

## 技能用途

用于安全、规范地查看、检查、修改和维护虹语织的桌面程序核心配置文件。

## 核心配置路径

- 使用每轮系统提示中“当前桌宠配置文件”提供的绝对路径。
- 源码版位于项目 `data/config.json`，EXE 版位于 EXE 同目录的 `config.json`。不要根据当前命令工作目录猜测路径。

## 主要配置项解析

1. **API与模型设置**
   - `base_url`：API 请求的基础地址
   - `api_key`：访问 API 的密钥
   - `model`：主对话模型 ID（不预置默认值，按所用供应商的模型 ID 填写）
   - `web_search_timeout_secs`：本地联网搜索总超时（3–30 秒，默认 8）
   - `web_search_max_results`：默认搜索结果数（1–10，默认 5）；搜索无需模型或密钥
   - `max_tool_rounds`：工具调用的最大轮数限制

2. **桌宠外观与交互设置**
   - `pet_size`：桌宠渲染尺寸（默认 180）
   - `x`, `y`：桌宠在屏幕上的初始/当前坐标
   - `pet_fps`：动画帧率
   - `current_emotion`：初始/当前表情（默认、思考中、递爱心等）
   - `always_on_top`：是否总在最前（窗口置顶）
   - `enable_wandering`：是否开启自主漫步
   - `wander_interval_secs`：漫步触发间隔时间（秒）
   - `enable_floating`：是否开启悬浮/浮动动效
   - `enable_mouse_facing`：是否开启视线跟随鼠标

3. **系统监控与安全策略**
   - `low_balance_threshold`：低余额预警阈值（按账户币种比较：美元账户填美元金额）
   - `balance_check_interval_mins`：余额检查间隔（分钟）
   - `sleep_timeout_mins`：无操作后进入休眠超时（分钟）
   - `confirm_before_command`：运行命令前是否必须弹窗确认

4. **核心设定**
   - `system_prompt`：虹语织的角色设定与全局行为规范

5. **额度查询（query_api_balance_and_usage）**
   - 按 `base_url` 自动探测账户额度：兼容 OpenAI 计费接口 / OneAPI / NewAPI 中转站、DeepSeek、OpenRouter、
     硅基流动、Moonshot(Kimi) 等常见额度接口；未收录的接口也会按常见路径依次尝试，无需额外配置项
   - 返回结果里 `remaining` / `used` / `total` 为账户币种金额，同时带 `currency` 与展示用文案；
     缺少的字段（例如某些供应商不提供已用量）会留空，不要编造

## 管理与修改操作规范

1. **修改前确认**：在修改前必须先调用 `read_file_contents` 读取当前最新内容，核实 JSON 格式是否完整。
2. **轻量改动**：改动单项（如修改 `model`、`wander_interval_secs`）时优先使用 `edit_text_file` 进行精确替换。
3. **格式合规**：修改后确保 JSON 语法正确（无多余逗号、双引号闭合），避免程序启动报错。
4. **安全保护**：严禁随意泄露或重置 `api_key`，修改 `system_prompt` 前需经主人确认。
