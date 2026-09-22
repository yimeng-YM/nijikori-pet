# -*- coding: utf-8 -*-
"""delegate_to_harness：把重型编码任务委托给本机 DeepSeek Harness 无头执行。"""
import os
import re
import shutil

from pet_tools import register
from pet_tools import shell as _shell


def _wrap_cmd(path):
    """把 .cmd/.bat 启动器包装成 cmd /c 形式（CreateProcess 不能直接执行批处理）。

    注意：cmd /c 会把 prompt 里的换行当命令分隔符（多行任务被截断到第一行，
    余下行还会被当命令执行）、展开 %VAR%，且首尾引号剥离对带空格路径不稳定。
    因此命中 .cmd/.bat 时优先用 _dsh_node_direct 解析成 node 直启；解析不出
    才退回 cmd /c 包装。"""
    if path.lower().endswith((".cmd", ".bat")):
        direct = _dsh_node_direct(path)
        if direct:
            return direct
        return ["cmd", "/c", path]
    return [path]


def _dsh_node_direct(cmd_path):
    """从 npm 风格的 .cmd 启动器解析出 ["node.exe", "<pkg>/lib/bin.js"] 直启参数。

    npm/pnpm/npx 生成的 dsh.cmd 本质是: node "<dp0>\..\@deepseek-ai\dsh\lib\bin.js" %*
    直接以 node 启动 bin.js 可完全绕过 cmd.exe 批处理层，保证多行 prompt 与
    %VAR%、引号、& 等字符原样传给 dsh。解析失败返回 None（调用方退回 cmd /c）。"""
    try:
        with open(cmd_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    # 匹配 "%_prog%"  "<...>\<pkg>\lib\bin.js" 的目标脚本路径
    m = re.search(r'"([^"]+\\lib\\bin\.js)"', text.replace("%dp0%\\", ""))
    if not m:
        return None
    script = os.path.normpath(os.path.join(os.path.dirname(cmd_path), m.group(1).lstrip("\\")))
    if not os.path.isfile(script):
        return None
    node = shutil.which("node")
    if not node:
        return None
    return [node, script]


def _find_dsh_launcher(ctx=None):
    """多级回退定位 dsh 启动命令，返回 (launcher_args, how) 或 (None, tried)。

    桌宠进程的 PATH 往往与终端不同（dsh 可能只存在于 npx 缓存或 npm 全局
    目录未进桌宠 PATH），所以依次尝试：
    1. config.harness_dsh_path —— 主人手动指定的 dsh 启动器完整路径（最高优先）；
    2. shutil.which 按当前 PATH 找 dsh / dsh.cmd / dsh.exe；
    3. 常见 npm 全局/pnpm 目录里的 dsh.cmd；
    4. npx 回退：npx --yes @deepseek-ai/dsh --profile headless（Node 官方
       安装目录几乎总在系统 PATH，最可靠）。"""
    tried = []

    # 1) 配置手动指定
    override = ""
    try:
        override = str((ctx.config or {}).get("harness_dsh_path") or "").strip() if ctx is not None else ""
    except Exception:
        override = ""
    if override:
        p = os.path.expandvars(os.path.expanduser(override))
        if os.path.isfile(p):
            return _wrap_cmd(p), "config"
        tried.append("config.harness_dsh_path=%s（文件不存在）" % override)

    # 2) 当前 PATH
    for name in ("dsh", "dsh.cmd", "dsh.exe"):
        p = shutil.which(name)
        if p:
            return _wrap_cmd(p), "which:%s" % name
        tried.append("which %s -> 无" % name)

    # 3) 常见包管理器全局目录
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    home = os.path.expanduser("~")
    for c in (os.path.join(appdata, "npm", "dsh.cmd"),
              os.path.join(appdata, "npm", "dsh"),
              os.path.join(localappdata, "pnpm", "dsh.cmd"),
              os.path.join(home, ".npm-global", "dsh.cmd")):
        if os.path.isfile(c):
            return _wrap_cmd(c), "found:%s" % c
        tried.append("%s -> 无" % c)

    # 3b) npx 缓存扫描（@deepseek-ai/dsh 曾以 npx 方式运行过的场景）
    npx_cache = os.path.join(localappdata, "npm-cache", "_npx")
    if os.path.isdir(npx_cache):
        try:
            for entry in sorted(os.listdir(npx_cache), reverse=True):
                bin_dsh = os.path.join(npx_cache, entry, "node_modules", ".bin", "dsh.cmd")
                if os.path.isfile(bin_dsh):
                    return _wrap_cmd(bin_dsh), "npx-cache:%s" % bin_dsh
                tried.append("%s -> 无" % bin_dsh)
        except Exception:
            pass

    # 4) npx 回退（最可靠：nodejs 目录几乎总在系统 PATH）
    for name in ("npx.cmd", "npx", "npx.exe"):
        p = shutil.which(name)
        if p:
            return _wrap_cmd(p) + ["--yes", "@deepseek-ai/dsh"], "npx:%s" % name
        tried.append("which %s -> 无" % name)

    return None, tried


@register("delegate_to_harness", {
    "name": "delegate_to_harness",
    "description": "把重型编码任务（大规模重构、批量迁移、完整测试矩阵、跨文件改造等）委托给本机的 DeepSeek Harness 代理在后台执行：以 dsh --profile headless 一次性任务方式运行，返回后台任务 id，可用 read_background_output 查看其进度与最终结果，stop_background_job 可终止。桌宠负责对话与拆解，Harness 负责真正动手写代码。执行前会弹窗请主人确认。轻量小改动请自己做，不要滥用委托。",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "给 Harness 的完整任务描述（要自包含：目标、涉及文件/目录、验收标准、注意事项）"},
            "title": {"type": "string", "description": "可选：任务简短标题（展示给主人确认用）"},
            "cwd": {"type": "string", "description": "可选：执行目录，默认用户主目录"},
        },
        "required": ["prompt"],
    },
})
def delegate_to_harness(args, ctx=None):
    prompt = str(args.get("prompt") or "").strip()
    title = str(args.get("title") or "").strip() or "Harness 委托任务"
    if not prompt:
        return {"status": "error", "message": "缺少任务描述 prompt"}

    launcher, how = _find_dsh_launcher(ctx)
    if launcher is None:
        return {"status": "error",
                "message": ("未找到 dsh 启动方式（DeepSeek Harness CLI）。已尝试："
                            + "；".join(how[:6])
                            + "。解决办法任选其一：① 在 config.json 设置 harness_dsh_path 为 dsh.cmd 完整路径；"
                              "② 终端执行 npm i -g @deepseek-ai/dsh 全局安装；"
                              "③ 确认已安装 Node.js（npx 可用即可，织织会自动回退用 npx 启动）")}
    shell_note = how

    cwd = str(args.get("cwd") or "").strip()
    if cwd:
        cwd = os.path.abspath(os.path.expanduser(os.path.expandvars(cwd)))
    else:
        cwd = os.path.expanduser("~")
    if not cwd or not os.path.isdir(cwd):
        return {"status": "error",
                "message": "未提供有效的 cwd 目录"}

    if ctx is not None and hasattr(ctx, "_confirm_tool_action"):
        ok = ctx._confirm_tool_action(
            prompt[:600] + ("…" if len(prompt) > 600 else ""),
            description=f"{title}（由 DeepSeek Harness 后台执行，目录: {cwd}）",
            prompt="织织准备把以下任务委托给 DeepSeek Harness 执行：")
        if not ok:
            return {"status": "cancelled", "message": "主人未确认，已取消委托"}

    # 通过后台命令引擎启动 dsh headless（复用确认已做，绕过二次确认：
    # _new_job 不弹窗，弹窗在 start_background_command 里做 —— 这里手动建任务）
    job, err = _shell._new_job(
        "dsh --profile headless <task>", cwd, "cmd", title)
    if job is not None:
        job["cmd"] = "[{}] dsh --profile headless".format(how)
    if job is None:
        return {"status": "error", "message": err}

    import subprocess
    import threading
    flags = 0x08000000 if os.name == "nt" else 0
    # 无头模式没有任何审批应答者（missing answerers fail closed），默认的
    # workspace-write + approval:ask 会让工作区外操作被拒、任务提前受挫；
    # 显式设为 danger-full-access（approval: never）让 headless 全程免审批。
    env = dict(os.environ)
    env.setdefault("DSH_PERMISSION_MODE", "danger-full-access")
    try:
        proc = subprocess.Popen(
            launcher + ["--profile", "headless", prompt],
            cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, creationflags=flags, env=env)
    except Exception as e:
        _shell.BG_JOBS.pop(job["id"], None)
        job["done"].set()
        return {"status": "error", "message": f"Harness 启动失败: {e}"}

    job["proc"] = proc
    job["cmd"] = f"[{how}] dsh --profile headless {title}"
    threading.Thread(target=_shell._pump, args=(proc.stdout, job["stdout"], job), daemon=True).start()
    threading.Thread(target=_shell._pump, args=(proc.stderr, job["stderr"], job), daemon=True).start()

    def _wait():
        try:
            code = proc.wait()
        except Exception:
            code = -1
        job["exit_code"] = code
        job["finished_at"] = __import__("time").time()
        job["done"].set()

    threading.Thread(target=_wait, daemon=True).start()

    # 向 dshpet-bridge 播报委托事件（fire-and-forget，失败不影响任务）
    try:
        import json as _json
        import urllib.request as _ureq
        status_url = str((ctx.config or {}).get("harness_status_url") or "").strip() if ctx is not None else ""
        status_url = status_url or "http://127.0.0.1:3080/api/dshpet/status"
        base = status_url.split("/api/dshpet/")[0]
        if base:
            req = _ureq.Request(
                base + "/api/dshpet/delegate",
                data=_json.dumps({"title": title, "prompt": prompt[:1000]}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            _ureq.urlopen(req, timeout=3)
    except Exception:
        pass

    return {
        "status": "success",
        "job_id": job["id"],
        "pid": proc.pid,
        "cwd": cwd,
        "title": title,
        "launch_via": how,
        "message": (f"已委托给 DeepSeek Harness（任务 {job['id']}）。"
                    f"用 read_background_output job_id=\"{job['id']}\" 跟踪进度；"
                    f"完成后把最终结果汇报给主人。"),
    }
