# -*- coding: utf-8 -*-
"""示例插件 ③：外观、菜单与控制中心页面。

演示三件事（"改桌宠现有能力"的外观与界面部分）：
1. register_emotion —— 加一个新表情（图片从插件自己的文件夹里取）；
2. register_action  —— 加一个自定义动作（自由编排演出）；
3. add_menu_item / add_control_center_page —— 加右键菜单项与设置页。

本示例生成的是一张纯色渐变图（PIL 现画，不依赖外部素材），
所以复制即用；换成你自己的立绘只要把 PNG 放进插件文件夹并改 _EMOTION_IMAGE。
"""

import os

_EMOTION_NAME = "插件气泡"
_EMOTION_IMAGE = "plugin_emotion.png"
_ACTION_NAME = "plugin_bounce_twice"
_state = {}
_api = None


def _make_demo_image(path, size=(320, 320)):
    """画一张带透明圆角与文字提示的示例立绘（只在图片不存在时生成）。"""
    if os.path.isfile(path):
        return True
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    try:
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 柔和的竖向渐变（品牌粉 → 青）
        top, bottom = (255, 182, 214), (150, 226, 255)
        for y in range(size[1]):
            t = y / max(1, size[1] - 1)
            draw.line([(0, y), (size[0], y)],
                      fill=(int(top[0] + (bottom[0] - top[0]) * t),
                            int(top[1] + (bottom[1] - top[1]) * t),
                            int(top[2] + (bottom[2] - top[2]) * t), 235))
        # 挖出圆角矩形（把四角擦成透明）
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([8, 8, size[0] - 8, size[1] - 8],
                                               radius=48, fill=255)
        img.putalpha(mask)
        draw = ImageDraw.Draw(img)
        draw.text((size[0] // 2 - 40, size[1] // 2 - 8), "PLUGIN",
                  fill=(90, 70, 120, 255))
        img.save(path)
        return True
    except Exception:
        return False


def register(api):
    global _state, _api
    _api = api
    _state = api.state
    _state.setdefault("clicks", 0)

    # ---- 1) 新表情（图片相对插件目录；也支持绝对路径 / GIF 动图） ----
    image_path = api.resolve(_EMOTION_IMAGE)
    if _make_demo_image(image_path):
        try:
            api.register_emotion(_EMOTION_NAME, _EMOTION_IMAGE,
                                 description="插件示例表情")
        except Exception as exc:
            api.log("注册表情失败:", exc)
    else:
        api.log("跳过表情注册（PIL 不可用或绘图失败）")

    # ---- 2) 自定义动作（AI 可以 perform_pet_action(action="plugin_bounce_twice")） ----
    api.register_action(_ACTION_NAME, bounce_twice,
                        description="插件示例：连跳两下并换个表情", intensity="normal")

    # ---- 3) 右键菜单项 + 控制中心页面 ----
    api.add_menu_item("🧩 插件示例问好", menu_greet, icon="🧩", order=20)
    api.add_control_center_page("插件示例", build_page, icon="🧩")

    api.add_prompt_block(
        "示例插件 example_appearance 注册了表情「插件气泡」与动作 plugin_bounce_twice；"
        "主人想看你做新动作时可以用 perform_pet_action 调用它。"
    )
    api.on_unload(lambda: api.save_state())
    api.log("已加载（示例插件 ③：外观与界面）")


def bounce_twice(pet, intensity):
    """自定义动作：连续两次弹跳 + 换成插件表情，再回到默认。"""
    pet.perform_pet_action("bounce", intensity or "strong")
    if _EMOTION_NAME in getattr(pet, "frames_normal", {}):
        pet.set_emotion(_EMOTION_NAME)
    pet.root.after(420, lambda: pet.perform_pet_action("jump", intensity or "strong"))
    pet.root.after(900, lambda: pet.set_emotion("默认"))


def menu_greet(pet):
    """右键菜单项的回调（在 UI 线程执行，可直接操作界面）。"""
    _state["clicks"] += 1
    _api.save_state()
    pet.show_speech(f"这是插件加的菜单项，你点了 {_state['clicks']} 次啦！(✧∇✧)",
                    "递爱心", 3000)


def build_page(page, api):
    """控制中心「插件示例」页：用桌宠同款控件画自己的设置界面。"""
    ui = api.pet_ui()
    dpi = ui.get("dpi", 1.0)
    pal = ui.get("pal", {})
    f_ui = ui.get("f_ui")
    f_small = ui.get("f_small")

    card = ui["card"](page, title="插件示例页面", icon="🧩",
                      subtitle="由 example_appearance 提供")

    ui["label"](card, text=f"插件目录：{api.dir}", font=f_small,
                fg=pal.get("ink_soft"), bg="#ffffff", justify="left",
                wraplength=int(540 * dpi)).pack(anchor="w")

    ui["label"](card, text=f"菜单项被点击次数：{_state.get('clicks', 0)}", font=f_ui,
                fg=pal.get("ink"), bg="#ffffff").pack(anchor="w", pady=(int(6 * dpi), 0))

    row = ui["frame"](card, bg="#ffffff")
    row.pack(fill="x", pady=(int(10 * dpi), 0))
    ui["button"](row, "🧩 打个招呼", command=lambda: menu_greet(api.get_pet()),
                 parent_bg="#ffffff", fill=pal.get("btn_primary"),
                 fg=pal.get("btn_primary_fg"), hover=pal.get("btn_primary_hover"),
                 font=f_ui, padx=int(12 * dpi), pady=int(6 * dpi)).pack(side="left")
    ui["button"](row, "✨ 做一次自定义动作",
                 command=lambda: bounce_twice(api.get_pet(), "strong"),
                 parent_bg="#ffffff", fill=pal.get("btn_soft"),
                 fg=pal.get("btn_soft_fg"), hover=pal.get("btn_soft_hover"),
                 font=f_ui, padx=int(12 * dpi), pady=int(6 * dpi)).pack(
                     side="left", padx=(int(8 * dpi), 0))
