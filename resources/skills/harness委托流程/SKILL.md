---
name: harness委托流程
description: 主人委托harness任务时的固定流程：先在E:\Harness新建任务文件夹，再设为工作区指派
---

# Harness委托流程

## 用途
主人委托harness执行任务（3D场景、重构、批量迁移等重型任务）时的标准流程。

## 步骤
1. **先建工作区**：在 `E:\Harness` 下新建一个以任务命名的文件夹（如 `E:\Harness\日式乡村车站`），用 file_operations 的 create_folder 创建。
2. **委托执行**：用 delegate_to_harness 发起任务，prompt 里写清目标、细节要求、验收标准，并指定 cwd 为该工作区目录，产物会落在该工作区内。
3. **跟踪进度**：用 read_background_output 查看任务输出，完成后向主人汇报。

## 备注
- 每个委托任务独立一个文件夹，方便管理和查找产物
- 委托前主人会收到弹窗确认
- 3D场景类任务先读取「3D场景构建提示词」技能生成提示词再委托
