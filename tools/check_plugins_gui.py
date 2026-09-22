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

    # 任何错误弹窗都会阻塞自动化：换成记录，由检查判定为失败
    dialogs = []
    real_showerror = main.messagebox.showerror

    def fake_showerror(title=None, message=None, **kwargs):
        dialogs.append(f"{title}: {message}")
        print(f"    [错误弹窗被拦截] {title}: {message}")

    main.messagebox.showerror = fake_showerror
    main.messagebox.showwarning = fake_showerror
    # 这个检查会点「启用插件系统」总开关，而它内部会 save_config() 写真实
    # data/config.json —— 验证脚本绝不能改主人的配置，这里改成只改内存。
    real_save_config = pet.save_config

    def memory_only_save_config():
        return True

    pet.save_config = memory_only_save_config
    state = {"dialogs": dialogs, "real_showerror": real_showerror,
             "real_save_config": real_save_config}

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
        # 真实点击插件清单里的启用/停用开关（曾被误传布尔值当插件名）
        step_toggle_plugin_off,
        step_verify_plugin_disabled,
        step_toggle_plugin_on,
        step_verify_plugin_enabled,
        # 总开关：关掉应立即卸下能力，打开应恢复
        step_master_switch_off,
        step_master_switch_on,
        step_finish,
    ])

    def run_next():
        try:
            step = next(steps)
        except StopIteration:
            root.quit()          # 步骤跑完一定收工，某一步出错也不会挂住窗口
            return
        try:
            step(pet, state)
        except Exception:
            record(step.__name__, False, traceback.format_exc(limit=3).replace("\n", " | "))
        root.after(400, run_next)

    root.after(600, run_next)
    root.after(60000, root.quit)     # 兜底：无论发生什么都不要挂住
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


def find_plugin_switch(pet, plugin_name):
    """在「插件扩展」页里找到某个插件那一行的 ToggleSwitch。

    页面用 functools.partial 把插件名绑在开关命令上，据此精确定位。"""
    page = pet._cc_page_frame
    for item in walk(page) if page is not None else []:
        if type(item).__name__ != "ToggleSwitch":
            continue
        cmd = getattr(item, "_cmd", None)
        args = getattr(cmd, "args", ())        # functools.partial
        if args and args[0] == plugin_name:
            return item
    return None


def step_toggle_plugin_off(pet, state):
    """真实点击插件清单里的开关（复现"没有找到插件：False"那个缺陷路径）。"""
    pet._cc_show("plugins")
    pet.root.update()
    switch = find_plugin_switch(pet, "gui_plugin")
    record("插件行的开关可定位", switch is not None)
    if switch is None:
        return
    switch._on_click()                          # 与真实鼠标点击走同一条路径
    pet.root.update()
    state["dialogs"].clear()


def step_verify_plugin_disabled(pet, state):
    """开关拨到关：插件应被卸下，且不能弹出错误对话框。"""
    pet._cc_show("plugins")                     # 页面重建由 220ms 定时器触发，这里手动刷新
    pet.root.update()
    record("关闭插件没有弹出错误弹窗", not state["dialogs"], str(state["dialogs"])[:120])
    record("关闭后插件已从插件表卸下",
           not any(t["function"]["name"] == "gui_tool" for t in main.PET_TOOLS))
    record("关闭后插件状态变为未启用",
           (main._PLUGINS.records.get("gui_plugin") or None) is not None
           and main._PLUGINS.records["gui_plugin"].status != "loaded",
           str(getattr(main._PLUGINS.records.get("gui_plugin"), "status", "gone")))
    record("关闭后提示词段落已移除", main._PLUGINS.prompt_blocks(None) == [])


def step_toggle_plugin_on(pet, state):
    """再点一次开关：插件应重新加载。"""
    switch = find_plugin_switch(pet, "gui_plugin")
    record("停用后的开关仍可定位", switch is not None)
    if switch is None:
        return
    switch._on_click()
    pet.root.update()
    state["dialogs"].clear()


def step_verify_plugin_enabled(pet, state):
    pet._cc_show("plugins")
    pet.root.update()
    record("重新启用插件没有弹出错误弹窗", not state["dialogs"], str(state["dialogs"])[:120])
    record("重新启用后工具回到插件表",
           any(t["function"]["name"] == "gui_tool" for t in main.PET_TOOLS))
    record("重新启用后插件状态为已加载",
           getattr(main._PLUGINS.records.get("gui_plugin"), "status", None) == "loaded")


def find_toggle_by_label(pet, label_text):
    """按设置行的标题文字找到对应的 ToggleSwitch。

    注意：控制中心页头还有一个「窗口置顶」开关，不能简单取"第一个开关"。
    """
    page = pet._cc_page_frame
    for item in walk(page) if page is not None else []:
        if not isinstance(item, tk.Label):
            continue
        try:
            text = str(item.cget("text"))
        except Exception:
            continue
        if label_text not in text:
            continue
        row = item.master.master          # left frame -> row
        for sibling in row.winfo_children():
            if type(sibling).__name__ == "ToggleSwitch":
                return sibling
    return None


def click_master_switch(pet):
    """点击「启用插件系统」总开关。"""
    switch = find_toggle_by_label(pet, "启用插件系统")
    if switch is None:
        return False
    switch._on_click()
    return True


def step_master_switch_off(pet, state):
    """总开关拨到关：插件能力应立即卸下（而不是等重启）。"""
    pet._cc_show("plugins")
    pet.root.update()
    state["dialogs"].clear()
    ok = click_master_switch(pet)
    record("总开关可点击", ok)
    pet.root.update()
    record("关闭总开关没有弹出错误弹窗", not state["dialogs"], str(state["dialogs"])[:120])
    record("关闭总开关后插件能力立即失效",
           not any(t["function"]["name"] == "gui_tool" for t in main.PET_TOOLS))
    record("关闭总开关写入了 config", pet.config.get("enable_plugins") is False,
           str(pet.config.get("enable_plugins")))


def step_master_switch_on(pet, state):
    """总开关拨回开：插件应重新加载。"""
    pet._cc_show("plugins")
    pet.root.update()
    state["dialogs"].clear()
    click_master_switch(pet)
    pet.root.update()
    record("打开总开关没有弹出错误弹窗", not state["dialogs"], str(state["dialogs"])[:120])
    record("打开总开关后插件能力恢复",
           any(t["function"]["name"] == "gui_tool" for t in main.PET_TOOLS))


def step_finish(pet, state):
    main.messagebox.showerror = state["real_showerror"]
    main.messagebox.showwarning = state["real_showerror"]
    pet.save_config = state["real_save_config"]
    main._PLUGINS.disable_all()
    pet._cc_close()
    pet.root.quit()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main_check())
