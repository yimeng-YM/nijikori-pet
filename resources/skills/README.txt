虹语织 技能库 (Skills) 使用说明
================================

技能采用业界标准 Agent Skills 格式（Claude / OpenAI 通用）：
一个技能 = 一个文件夹，文件夹里必须有 SKILL.md 文件。
源码版技能库位于项目 resources/skills/，EXE 版位于 EXE 同目录的 skills/。

  skills/
    README.txt                    ← 本说明（txt 不会被当作技能）
    <技能文件夹名>/
      SKILL.md                    ← 技能内容（YAML 头部 + Markdown 正文）

SKILL.md 开头必须是 YAML 元信息（frontmatter），至少包含 name 和
description 两个字段，然后接 Markdown 正文：

  ---
  name: 技能名称
  description: 一句话说明这个技能是干什么的、什么时候该用
  ---

  # 技能标题
  ## 用途
  一句话说明这个技能是干嘛用的
  ## 步骤
  1. ...
  2. ...
  ## 备注
  补充信息

你可以自己新建文件夹和 SKILL.md 放进这里，桌宠会自动加载（无需重启）；
织织也会用 manage_skills 工具按同样标准创建、读取、追加、修改技能。

注意：
- 只会加载形如 SKILL.md 的文件（大小写不敏感，如 skill.md 也会识别）；
  散放的单个 .md 文件不会被当作技能。
- name 建议用简短中文词语或小写英文 kebab-case（不含空格）。
- 织织创建技能时会自动补全 standard frontmatter，无需手写。
- frontmatter 可以加 triggers 触发词列表，主人的消息命中触发词时该技能
  会被自动注入（不用织织自己想起来去读）：

  ---
  name: 技能名
  description: 一句话说明
  triggers:
    - 打开XX
    - 整理XX
  ---
- 复杂技能可以把参考资料/脚本放在技能文件夹内（如 references/api.md），
  织织用 manage_skills action=read 的 file 参数按相对路径读取。
