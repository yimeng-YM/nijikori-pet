---
name: 项目接手法
description: 接手陌生项目时的固定套路：目录概览 → 依赖清单 → 入口文件 → 跑起来的步骤，先建认知再动手
triggers:
    - 接手
    - 这个项目
    - 看看项目
    - 了解项目
    - 新项目
---

# 项目接手法

## 用途
第一次接触某个项目时按这个套路快速建立全局认知。

## 步骤
1. **看目录**：`list_directory` / `glob_files` 看项目根目录有哪些文件（如 `*.*`、`**/*.py`），建立整体印象；
2. **读门面**：`read_file_contents` 读 README.md / package.json / requirements.txt / pyproject.toml 等依赖与说明文件；
3. **找入口**：`glob_files` 找 main.py / index.ts / app.py 等入口，`grep_files` 搜 `if __name__` 或主函数；
4. **试运行**：问主人或按 README 跑一次（`run_command_capture` 或后台任务），确认环境能转；
5. **汇报**：用织织的话总结『这个项目是干啥的、怎么跑、关键文件在哪』，然后等主人下指令。

## 纪律
- 动手改之前先走完 1-4 步；
- 大型改造任务优先委托 delegate_to_harness。
