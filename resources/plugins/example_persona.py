# -*- coding: utf-8 -*-
"""示例：让织织通过对话编辑人设、插件提示词，并扩展原有 API 页面。"""
import tkinter as tk
from tkinter import messagebox


def register(api):
    # 注入内容存入插件状态；重载后仍会恢复，停用插件则立即失效。
    api.add_prompt_block(lambda pet: api.state.get("injection", ""), key="editable")
    api.modify_control_center_page("api", extend_api_page)
    api.register_tool("manage_persona_prompt", {
        "name": "manage_persona_prompt",
        "description": "主人要求查看或修改织织人设、插件提示词注入时使用。修改必须按主人的具体要求执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set_persona", "set_injection", "clear_injection"]},
                "text": {"type": "string", "description": "set_persona 或 set_injection 时的新正文"},
            },
            "required": ["action"],
        },
    }, lambda args, pet: manage(api, args), category="记忆与技能")


def manage(api, args):
    action = str(args.get("action") or "get")
    if action == "get":
        return {"status": "success", "persona": api.get_persona(),
                "injection": api.state.get("injection", "")}
    if action == "set_persona":
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            return {"status": "error", "message": "人设正文不能为空"}
        if not api.set_persona(text):
            return {"status": "error", "message": "人设保存失败，原配置未改变"}
        return {"status": "success", "message": "人设已保存，下次模型请求生效"}
    if action == "set_injection":
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            return {"status": "error", "message": "注入正文不能为空"}
        previous = api.state.get("injection", "")
        api.state["injection"] = text
        if not api.save_state():
            api.state["injection"] = previous
            return {"status": "error", "message": "插件提示词保存失败"}
        return {"status": "success", "message": "插件提示词已更新，下次模型请求生效"}
    if action == "clear_injection":
        previous = api.state.get("injection", "")
        api.state.pop("injection", None)
        if not api.save_state():
            api.state["injection"] = previous
            return {"status": "error", "message": "插件提示词保存失败"}
        return {"status": "success", "message": "插件提示词已清除"}
    return {"status": "error", "message": f"未知操作：{action}"}


def extend_api_page(page, api, call_original):
    call_original()
    ui = api.pet_ui()
    row = tk.Frame(page, bg=ui["pal"]["bg"])
    row.pack(side=tk.BOTTOM, fill=tk.X, padx=int(26 * ui["dpi"]), pady=(0, 8))
    tk.Button(row, text="✏️ 编辑人设与插件提示词",
              command=lambda: open_editor(page, api),
              font=ui["f_ui"], bg=ui["pal"]["btn_soft"],
              fg=ui["pal"]["btn_soft_fg"], relief=tk.FLAT,
              cursor="hand2").pack(side=tk.LEFT)


def open_editor(page, api):
    win = tk.Toplevel(page)
    win.title("编辑人设与插件提示词")
    win.geometry("660x540")
    win.transient(page.winfo_toplevel())
    tk.Label(win, text="人设正文（保存到 config.json）").pack(anchor="w", padx=16, pady=(14, 2))
    persona = tk.Text(win, height=12, wrap="word")
    persona.pack(fill=tk.BOTH, expand=True, padx=16)
    persona.insert("1.0", api.get_persona())
    tk.Label(win, text="本插件的补充提示词（停用插件后不再注入）").pack(
        anchor="w", padx=16, pady=(12, 2))
    injection = tk.Text(win, height=7, wrap="word")
    injection.pack(fill=tk.BOTH, expand=True, padx=16)
    injection.insert("1.0", api.state.get("injection", ""))

    def save():
        new_persona = persona.get("1.0", "end-1c")
        if not new_persona.strip():
            messagebox.showerror("无法保存", "人设正文不能为空", parent=win)
            return
        if not api.set_persona(new_persona):
            messagebox.showerror("无法保存", "配置保存失败", parent=win)
            return
        previous = api.state.get("injection", "")
        api.state["injection"] = injection.get("1.0", "end-1c")
        if not api.save_state():
            api.state["injection"] = previous
            messagebox.showerror("部分保存失败", "人设已保存，但插件提示词未能保存", parent=win)
            return
        win.destroy()

    tk.Button(win, text="保存并应用", command=save).pack(pady=12)
