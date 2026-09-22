# -*- coding: utf-8 -*-
"""后台命令任务：start_background_command / read_background_output / stop_background_job。

让织织能启动长时间运行的命令（完整测试、编译、开发服务器）而不阻塞对话，
随后随时读取输出或终止任务。
"""
import os
import re
import time
import threading
import subprocess
from collections import deque

from pet_tools import register, expand_path


def _child_env():
    """Environment for background commands, with PyInstaller/Tcl leftovers removed.

    A frozen pet exports _MEI*/_PYI_* and TCL_LIBRARY/TK_LIBRARY pointing into
    its own extraction dir; a child Python started with those variables cannot
    import tkinter ("No module named 'tkinter'" / unusable init.tcl)."""
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("_PYI_") or k.startswith("_MEI")
                or k == "_MEIPASS2"]:
        del env[key]
    for key in ("TCL_LIBRARY", "TK_LIBRARY"):
        value = env.get(key) or ""
        if "_MEI" in value or not os.path.isdir(value):
            env.pop(key, None)
    return env

BG_JOBS = {}
BG_LOCK = threading.Lock()
BG_SEQ = 0
BG_MAX_JOBS = 8
BG_LINES_CAP = 2000          # 每个任务保留的输出行数环形上限
BG_RETAIN_SECS = 3600        # 已结束任务结果保留 1 小时


def _resolve_shell(cmd, shell="auto"):
    """与 main.resolve_shell 相同的轻量启发式（避免循环导入 main）。"""
    sh = str(shell or "auto").strip().lower()
    if sh in ("ps", "pwsh", "powershell", "powershell.exe"):
        return "powershell"
    if sh in ("cmd", "cmd.exe", "command", "命令提示符"):
        return "cmd"
    if sh != "auto":
        return "cmd"
    # PowerShell 特征：cmdlet / $变量 / 常用关键字
    if re.search(r"(?:^|[^$])\$[A-Za-z_][A-Za-z0-9_]*", cmd):
        return "powershell"
    if re.search(r"(?<![\w.-])[A-Za-z]+-[A-Za-z]+", cmd):
        return "powershell"
    if re.search(r"\b(Where-Object|Select-Object|ForEach-Object|Write-Host|Start-Process)\b", cmd, re.I):
        return "powershell"
    return "cmd"


def _pump(pipe, sink, proc_ref):
    """后台线程：持续把子进程输出按行存入环形 deque。"""
    try:
        for raw in iter(pipe.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            sink.append(line)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def _prune_finished():
    now = time.time()
    stale = [jid for jid, j in BG_JOBS.items()
             if j["done"].is_set() and now - j.get("finished_at", now) > BG_RETAIN_SECS]
    for jid in stale:
        BG_JOBS.pop(jid, None)


def _new_job(cmd, cwd, shell_used, description):
    global BG_SEQ
    with BG_LOCK:
        _prune_finished()
        running = sum(1 for j in BG_JOBS.values() if not j["done"].is_set())
        if running >= BG_MAX_JOBS:
            return None, f"后台任务已满（{BG_MAX_JOBS} 个运行中），请先用 read_background_output 查看或 stop_background_job 终止"
        BG_SEQ += 1
        job_id = f"bg_{BG_SEQ}"
        job = {
            "id": job_id,
            "cmd": cmd,
            "cwd": cwd,
            "shell": shell_used,
            "description": description,
            "stdout": deque(maxlen=BG_LINES_CAP),
            "stderr": deque(maxlen=BG_LINES_CAP),
            "out_truncated": False,
            "proc": None,
            "done": threading.Event(),
            "exit_code": None,
            "killed": False,
            "started_at": time.time(),
            "finished_at": None,
        }
        BG_JOBS[job_id] = job
        return job, None


def _clip(lines_deque, job, max_lines):
    if len(lines_deque) >= BG_LINES_CAP:
        job["out_truncated"] = True
    text = "\n".join(list(lines_deque)[-max_lines:])
    if len(lines_deque) > max_lines:
        job["out_truncated"] = True
    return text


@register("start_background_command", {
    "name": "start_background_command",
    "description": "在后台启动一条命令（长测试、编译、dev 服务器等），立即返回任务 id，不阻塞对话。之后用 read_background_output 轮询输出与退出码，用 stop_background_job 终止。执行前会弹窗请主人确认。",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要后台执行的命令"},
            "description": {"type": "string", "description": "命令作用说明（会展示给主人确认）"},
            "cwd": {"type": "string", "description": "可选：工作目录，默认活跃项目根目录"},
            "shell": {"type": "string", "enum": ["auto", "cmd", "powershell"], "description": "可选：指定 shell，默认 auto 自动识别"},
        },
        "required": ["command", "description"],
    },
})
def start_background_command(args, ctx=None):
    cmd = str(args.get("command") or "").strip()
    desc = str(args.get("description") or "").strip()
    if not cmd:
        return {"status": "error", "message": "缺少命令 command"}
    if not desc:
        return {"status": "error", "message": "缺少命令作用说明 description"}

    cwd = str(args.get("cwd") or "").strip()
    cwd = expand_path(cwd, ctx) if cwd else os.path.expanduser("~")

    if ctx is not None and hasattr(ctx, "_confirm_tool_action"):
        ok = ctx._confirm_tool_action(
            cmd, description=desc + f"（后台运行，目录: {cwd}）",
            prompt="织织准备在后台启动以下命令：")
        if not ok:
            return {"status": "cancelled", "message": "主人未确认，已取消后台命令"}

    shell_used = _resolve_shell(cmd, args.get("shell"))
    job, err = _new_job(cmd, cwd, shell_used, desc)
    if job is None:
        return {"status": "error", "message": err}

    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        if shell_used == "powershell" and os.name == "nt":
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", cmd],
                cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, creationflags=flags, env=_child_env())
        else:
            proc = subprocess.Popen(cmd, shell=True, cwd=cwd,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, creationflags=flags, env=_child_env())
    except Exception as e:
        job["done"].set()
        job["exit_code"] = -1
        job["finished_at"] = time.time()
        BG_JOBS.pop(job["id"], None)
        return {"status": "error", "message": f"启动失败: {e}"}

    job["proc"] = proc
    threading.Thread(target=_pump, args=(proc.stdout, job["stdout"], job), daemon=True).start()
    threading.Thread(target=_pump, args=(proc.stderr, job["stderr"], job), daemon=True).start()

    def _wait():
        try:
            code = proc.wait()
        except Exception:
            code = -1
        job["exit_code"] = code
        job["finished_at"] = time.time()
        job["done"].set()

    threading.Thread(target=_wait, daemon=True).start()

    return {
        "status": "success",
        "job_id": job["id"],
        "pid": proc.pid,
        "shell": shell_used,
        "cwd": cwd,
        "message": f"后台任务已启动（id={job['id']}）。用 read_background_output job_id='{job['id']}' 查看输出与退出码。",
    }


def _job_snapshot(job, max_lines=120):
    state = "finished" if job["done"].is_set() else ("killed" if job["killed"] else "running")
    snap = {
        "job_id": job["id"],
        "state": state,
        "shell": job["shell"],
        "cwd": job["cwd"],
        "command": job["cmd"],
        "elapsed_secs": round((job["finished_at"] or time.time()) - job["started_at"], 1),
        "exit_code": job["exit_code"] if job["done"].is_set() else None,
        "stdout_tail": _clip(job["stdout"], job, max_lines),
        "stderr_tail": _clip(job["stderr"], job, max_lines),
        "output_truncated": job["out_truncated"],
    }
    return snap


@register("read_background_output", {
    "name": "read_background_output",
    "description": "读取后台命令任务的最新输出、运行状态与退出码（相当于 job_output）。任务完成后 exit_code 非 0 表示命令失败，请结合 stderr_tail 判断原因。",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "start_background_command 返回的任务 id（如 bg_1）"},
            "max_lines": {"type": "integer", "description": "可选：各流最多返回的行数，默认 120"},
            "wait": {"type": "boolean", "description": "可选：是否等待任务结束再返回（默认最多等 60 秒），默认 False"},
            "wait_seconds": {"type": "integer", "description": "可选：等待任务结束的最长秒数（1-300）。长测试/编译建议直接给 120~300，一次等到结束或超时再返回，比反复轮询快得多；到时间仍未结束会返回当前输出与 running 状态"},
        },
        "required": ["job_id"],
    },
})
def read_background_output(args, ctx=None):
    job_id = str(args.get("job_id") or "").strip()
    try:
        max_lines = max(10, min(int(args.get("max_lines") or 120), 500))
    except Exception:
        max_lines = 120
    try:
        wait_seconds = int(args.get("wait_seconds") or 0)
    except Exception:
        wait_seconds = 0
    if wait_seconds > 0:
        wait_seconds = max(1, min(wait_seconds, 300))
    elif args.get("wait") in (True, "true", "1", "yes"):
        wait_seconds = 60
    with BG_LOCK:
        job = BG_JOBS.get(job_id)
    if job is None:
        return {"status": "error",
                "message": f"后台任务不存在或已过期: {job_id}（结果保留 1 小时）"}
    if wait_seconds:
        job["done"].wait(timeout=wait_seconds)
    snapshot = _job_snapshot(job, max_lines)
    if wait_seconds and not job["done"].is_set():
        snapshot["waited_seconds"] = wait_seconds
        snapshot["message"] = (f"已等待 {wait_seconds} 秒任务仍未结束；可再次调用 read_background_output "
                               f"并给更大的 wait_seconds，或先做别的事稍后再看。")
    return {"status": "success", **snapshot}


@register("stop_background_job", {
    "name": "stop_background_job",
    "description": "终止一个还在运行的后台命令任务（相当于 job_kill）。已结束的任务无需终止。",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "要终止的后台任务 id"},
            "reason": {"type": "string", "description": "可选：终止原因（记录在日志里）"},
        },
        "required": ["job_id"],
    },
})
def stop_background_job(args, ctx=None):
    job_id = str(args.get("job_id") or "").strip()
    with BG_LOCK:
        job = BG_JOBS.get(job_id)
    if job is None:
        return {"status": "error", "message": f"后台任务不存在: {job_id}"}
    if job["done"].is_set():
        return {"status": "success", "message": f"任务 {job_id} 已结束（exit_code={job['exit_code']}），无需终止"}
    job["killed"] = True
    proc = job["proc"]

    def _hard_kill():
        # Windows 上必须先 taskkill /T 连进程树一起杀：若先 proc.terminate() 杀掉
        # cmd.exe 包装进程，node 孙进程会脱离进程树变成孤儿继续跑，任务停不下来。
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            else:
                proc.kill()
        except Exception:
            pass

    threading.Thread(target=_hard_kill, daemon=True).start()
    reason = str(args.get("reason") or "").strip()
    return {"status": "success",
            "message": f"已请求终止任务 {job_id}" + (f"（原因: {reason}）" if reason else "") +
                       "，可用 read_background_output 确认其退出。"}
