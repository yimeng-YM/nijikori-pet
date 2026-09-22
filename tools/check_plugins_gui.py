# -*- coding: utf-8 -*-
"""插件系统 GUI 冒烟验证（源码版真实 Tk 窗口，自动开关）。

用法（在项目根目录）：

    python -B tools/check_plugins_gui.py

覆盖自动化单元测试碰不到的真实界面，全程自动点击、无需人工操作：

1. 首次加载确认弹窗能否打开、勾选、返回被批准的插件名（含「全部跳过」路径）；
2. 插件能否通过真实加载流程注册成功；
3. 控制中心「🧩 插件扩展」页能否真正渲染（卡片/开关/按钮/插件清单与状态）；
4. 插件自己注册的控制中心页面能否渲染；
5. 插件注册的右键菜单项能否进入并渲染快捷菜单。

脚本使用临时插件目录与临时信任库，不会读写项目里的 plugins/ 与 data/。
退出码 0 表示全部通过。
"""
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import tkinter as tk  # noqa: E402

import main  # noqa: E402
from pet_plugins.trust import TrustStore  # noqa: E402
from test_plugins import write_plugin  # noqa: E402

RESULTS = []
TMP = tempfile.TemporaryDirectory()


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def find_toplevel(root, title_part):
    for child in root.winfo_children():
        try:
            if isinstance(child, tk.Toplevel) and title_part in str(child.title()):
                return child
        except Exception:
            continue
    return None


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def click_button(widget, text):
    """在控件树里找 PastelButton 并触发它的命令。"""
    for item in walk(widget):
        if type(item).__name__ == "PastelButton":
            try:
                labels = [item.itemcget(i, "text") for i in item.find_all()
                          if item.type(i) == "text"]
            except Exception:
                labels = []
            if any(text in str(label) for label in labels):
                if item._cmd:
                    item._cmd()
                    return True
    return False


def main_check():
    root = tk.Tk()
    root.withdraw()
    pet = main.DesktopPet(root)
    pet.root.withdraw()
    try:
        pet.bubble.withdraw()
    except Exception:
        pass
    # 把插件目录/信任库指向临时位置，绝不碰项目里的真实数据
    manager = main._PLUGINS
    plugins_dir = Path(TMP.name) / "plugins"
    manager.plugins_dir = str(plugins_dir)
    manager.trust = TrustStore(str(Path(TMP.name) / "data"))
    manager._log_path = str(Path(TMP.name) / "plugins.log")   # 不污染本机 data/plugins.log
    manager.ensure_plugins_dir()

    # 造一个插件：提供工具 + 菜单项 + 控制中心页面 + 提示词
    write_plugin(plugins_dir, "gui_plugin", """
        def register(api):
            api.register_tool("gui_tool", {
                "name": "gui_tool", "description": "GUI 验证工具",
                "parameters": {"type": "object", "properties": {}},
            }, handler, category="插件测试")
            api.add_menu_item("🧩 GUI 插件菜单项", lambda pet: None, order=20)
            api.add_control_center_page("GUI 插件页", build_page, icon="🧩")
            api.add_prompt_block("GUI 验证段落")

        def handler(args, pet):
            return {"status": "success"}

        def build_page(page, api):
            ui = api.pet_ui()
            card = ui["card"](page, title="GUI 插件页", icon="🧩")
            ui["label"](card, text="来自插件的内容", font=ui["f_ui"],
                        fg=ui["pal"]["ink"], bg="#ffffff").pack(anchor="w")
    """)

    steps = iter([
        step_load_plugin,
        step_consent_dialog,
        step_control_center_page,
        step_plugin_page,
        step_quick_menu,
        step_finish,
    ])
    state = {}

    def run_next():
        try:
            step = next(steps)
        except StopIteration:
            return
        try:
            step(pet, state)
        except Exception:
            record(step.__name__, False, traceback.format_exc(limit=3).replace("\n", " | "))
        root.after(400, run_next)

    root.after(600, run_next)
    root.mainloop()

    print("\n==== 汇总 ====")
    failed = [r for r in RESULTS if not r[1]]
    print(f"通过 {len(RESULTS) - len(failed)} / {len(RESULTS)}")
    TMP.cleanup()
    return 1 if failed else 0


def step_load_plugin(pet, state):
    """确认弹窗：打开后自动点「加载所选插件」。"""
    pending = [{"name": "gui_plugin", "path": str(Path(TMP.name) / "plugins" / "gui_plugin.py"),
                "entry": "", "status": "new", "is_package": False, "digest": "sha256:x"}]

    def auto_click():
        dialog = find_toplevel(pet.root, "插件加载确认")
        if dialog is None:
            state["consent_error"] = "确认弹窗没有出现"
            return
        # 弹窗里的第一个 PastelButton 就是「✅ 加载所选插件」
        clicked = click_button(dialog, "加载所选插件")
        state["consent_clicked"] = clicked
        if not clicked:
            dialog.destroy()

    pet.root.after(500, auto_click)
    approved = pet._plugin_consent_dialog(pending)
    record("首次加载确认弹窗可打开并返回勾选结果",
           approved == ["gui_plugin"] and state.get("consent_clicked"),
           f"approved={approved} clicked={state.get('consent_clicked')}")


def step_consent_dialog(pet, state):
    """取消勾选后应返回空列表（「全部跳过」路径）。"""
    pending = [{"name": "skipme", "path": "x", "entry": "", "status": "changed",
                "is_package": False, "digest": "sha256:y"}]

    def auto_click():
        dialog = find_toplevel(pet.root, "插件加载确认")
        if dialog is None:
            return
        if not click_button(dialog, "全部跳过"):
            dialog.destroy()

    pet.root.after(500, auto_click)
    approved = pet._plugin_consent_dialog(pending)
    record("确认弹窗「全部跳过」返回空", approved == [], f"approved={approved}")


def step_control_center_page(pet, state):
    """加载插件（走真实注册表）并渲染控制中心插件页。"""
    manager = main._PLUGINS
    summary = manager.load_all(confirm=lambda pending: [p["name"] for p in pending])
    state["summary"] = summary
    record("插件通过真实加载流程注册成功",
           summary.get("loaded") == ["gui_plugin"], str(summary))

    pet.open_control_center()
    pet.root.update()
    pet._cc_show("plugins")
    pet.root.update()
    page = pet._cc_page_frame
    widgets = list(walk(page)) if page is not None else []
    record("控制中心「插件扩展」页渲染成功", len(widgets) > 15,
           f"控件数={len(widgets)}")
    labels = []
    for item in widgets:
        if isinstance(item, tk.Label):
            try:
                labels.append(str(item.cget("text")))
            except Exception:
                pass
    record("插件清单显示插件名与状态",
           any("gui_plugin" in t and "已加载" in t for t in labels),
           "、".join(t for t in labels if "gui_plugin" in t)[:80])


def step_plugin_page(pet, state):
    """插件自己注册的控制中心页面。"""
    pages = [p["key"] for p in main._PLUGINS.control_center_pages()]
    record("插件页面已注册到控制中心", pages == ["plugin:gui_plugin"], str(pages))
    pet._cc_show("plugin:gui_plugin")
    pet.root.update()
    page = pet._cc_page_frame
    labels = []
    for item in walk(page) if page is not None else []:
        if isinstance(item, tk.Label):
            try:
                labels.append(str(item.cget("text")))
            except Exception:
                pass
    record("插件自定义页面渲染成功", any("来自插件的内容" in t for t in labels),
           "、".join(labels)[:80])


def step_quick_menu(pet, state):
    """右键快捷菜单里应出现插件菜单项。"""
    items = pet._plugin_menu_items()
    record("插件菜单项已进入快捷菜单数据", 
           len(items) == 1 and "GUI 插件菜单项" in items[0]["label"], str(items))
    menu = main.QuickMenu(pet, 100, 100)
    pet.root.update()
    texts = []
    for child in walk(menu):
        if isinstance(child, tk.Canvas):
            try:
                texts += [str(child.itemcget(i, "text")) for i in child.find_all()
                          if child.type(i) == "text"]
            except Exception:
                pass
    record("快捷菜单真实渲染出插件项",
           any("GUI 插件菜单项" in t for t in texts), "、".join(texts)[:120])
    menu._dismiss()


def step_finish(pet, state):
    main._PLUGINS.unload_all()
    main._PLUGINS._restore_baseline()
    pet._cc_close()
    pet.root.quit()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main_check())
