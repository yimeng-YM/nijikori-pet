---
name: 代码编辑流程手册
description: 织织帮主人改代码的标准流程：glob/grep 定位 → 带行号读原文 → 小步修改 → 跑测试验证 → git 提交的完整闭环
triggers:
    - 改代码
    - 修bug
    - 修复
    - 重构
    - 改一下代码
    - 写个函数
---

# 代码编辑流程手册

## 用途
主人让织织改代码/修 bug/加功能时，按这套标准流程做，稳稳的不翻车。

## 标准流程（五步闭环）
1. **定位**：
   - `glob_files` 找相关文件（如 `*.py`、`src/**/*.ts`）；
   - `grep_files` 按内容搜函数名/报错关键字，拿到文件与行号。
2. **读原文**：`read_file_contents` 带行号读目标区域（大文件用 offset/limit 分页）。
3. **小步修改**：
   - 首选 `edit_text_file`：find_text 必须能唯一命中（多处命中会被拒绝，加长定位文本即可）；
   - 确认全部替换时显式 `replace_all=true`；
   - old_string 不好定位时用 `edit_lines` 按行号改；
   - 每次只改一小步，靠返回的 changed_at_line 与 preview 自查。
4. **验证**：`run_command_capture` 跑测试/编译（长任务用 `start_background_command`），exit_code 非 0 就看 stderr_tail 修到通过为止。
5. **提交**：用 `run_command_capture` 执行 git 命令（status → add → commit，message 写清改了什么、为什么）。push 前会弹窗问主人。

## 纪律
- 改之前一定先读原文，禁止凭想象改；
- 一次对话里连续小步改，别一口气重写整个文件；
- 改坏了不怕：每次编辑自动备份（%TEMP%/nijikori_backups），大任务可委托 `delegate_to_harness`。
