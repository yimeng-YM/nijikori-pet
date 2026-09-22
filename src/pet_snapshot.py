"""Transient vision snapshots: memory-only capture and owned skill PNG cleanup.

One unified tool (screenshot) covers everything the pet used to split across
three tools:

* capture the whole screen / all monitors, or one specific window;
* save the picture to disk, or keep it in memory only (transient vision);
* read back a computer-use observation token and delete its temporary PNG.
"""
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageGrab

MAX_SIDE = 1280
# A computer-use observation stays readable for this long; the PowerShell engine
# keeps the matching .json state for the same window so one snapshot can drive
# several input steps instead of dying after the first use.
OBSERVATION_MAX_AGE_SECONDS = 600
OBSERVATION_RE = re.compile(r"[a-f0-9]{32}")

SCHEMA = {
    "type": "function",
    "function": {
        "name": "screenshot",
        "description": (
            "截图工具（全屏 / 指定窗口，保存或不保存，三合一）。"
            "target=screen 截屏幕（all_screens=true 截所有显示器）；target=window 用 window 关键词"
            "（窗口标题 / 程序名 / 应用名，或 'active'/'当前'）截指定窗口——按窗口离屏渲染，"
            "被其他窗口遮挡或桌宠自己盖住也能截到完整内容。"
            "save=false（默认）时截图全程在内存处理、不生成文件，直接把图片注入本回合供你识别（需要开启识图）；"
            "save=true 或给 save_path 时把 PNG 保存到磁盘（默认 桌面/屏幕截图_时间.png 或 窗口截图_时间.png）。"
            "两种可以同时用。computer-use 返回的 observation 编号也可传进来读同一张截图并自动删除临时 PNG。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["screen", "window"],
                    "description": "可选：截图对象，screen=屏幕（默认），window=指定窗口",
                },
                "window": {
                    "type": "string",
                    "description": "target=window 时必填：窗口标题 / 程序名(exe) / 应用名关键词（如 'VS Code'、'微信'、'notepad.exe'），或 'active'/'当前' 表示当前前台窗口",
                },
                "all_screens": {
                    "type": "boolean",
                    "description": "可选：target=screen 时是否截取所有显示器，默认 false（仅主屏幕）",
                },
                "save": {
                    "type": "boolean",
                    "description": "可选：是否把截图保存成文件，默认 false（只在内存里给你看）。true 时保存到 save_path，未给则保存到桌面并按时间命名",
                },
                "save_path": {
                    "type": "string",
                    "description": "可选：图片保存路径（给了就保存到这个位置，等价于 save=true）",
                },
                "question": {
                    "type": "string",
                    "description": "可选：希望重点观察的内容",
                },
                "observation": {
                    "type": "string",
                    "description": "可选：computer-use 返回的快照编号；读取同一张截图并删除临时 PNG，保留操作坐标状态（10 分钟内有效，同一张可复用多次）",
                },
            },
            "additionalProperties": False,
        },
    },
}


def _encode(image):
    """Create a standalone data URL, closing all derived images and buffers."""
    with image.convert("RGB") as rgb:
        rgb.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        with io.BytesIO() as output:
            rgb.save(output, format="JPEG", quality=85)
            data = output.getvalue()
        return {
            "width": rgb.width, "height": rgb.height, "size_bytes": len(data),
            "data_url": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii"),
        }


def default_save_path(target="screen", now=None):
    """Desktop screenshot path: 屏幕截图_时间.png or 窗口截图_时间.png."""
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    name = "窗口截图" if target == "window" else "屏幕截图"
    return os.path.join(os.path.expanduser("~"), "Desktop", name + "_" + stamp + ".png")


def _save_image(image, path):
    folder = os.path.dirname(str(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    image.save(path, format="PNG")
    return path


def _read_observation(observation, all_screens):
    """Read a computer-use observation PNG into memory; always delete it."""
    if all_screens:
        raise ValueError("observation 与 all_screens 不可同时使用")
    if not OBSERVATION_RE.fullmatch(observation):
        raise ValueError("无效 observation；请使用 computer-use 返回的快照编号")
    root = Path(tempfile.gettempdir()) / "NijiKori-computer-use"
    state_path = root / (observation + ".json")
    png_path = root / (observation + ".png")
    # Refuse redirects. The state file's screenshot field is deliberately ignored.
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError("快照目录不能是链接或重定向目录")
    for path in (state_path, png_path):
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise ValueError("快照文件不能是链接")
    if not state_path.is_file():
        raise ValueError("快照状态已失效（已被清理或从未存在），请重新 Observe/focus 拿一张新快照")
    if not png_path.is_file():
        raise ValueError("这张快照的临时图片已经被读取或清理，请重新 Observe/focus 拿一张新快照")
    try:
        if state_path.stat().st_size > 65536:
            raise ValueError("快照状态文件过大")
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        if not isinstance(state, dict) or state.get("observation") != observation:
            raise ValueError("快照状态与编号不匹配")
        created = datetime.fromisoformat(state["created_utc"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("快照时间缺少时区")
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if not -5 <= age <= OBSERVATION_MAX_AGE_SECONDS:
            raise ValueError("快照已过期（超过 10 分钟），请重新 Observe")
        if png_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("快照图片过大")
        with Image.open(png_path) as image:
            if image.size != (state["image_width"], state["image_height"]) or max(image.size) > MAX_SIDE:
                raise ValueError("快照尺寸与操作坐标不匹配，请重新 Observe")
            image.load()
            return image.copy(), state
    finally:
        # The JSON stores coordinates only and is consumed by the next input step.
        # Unlink failure must propagate: never claim a successful cleanup otherwise.
        png_path.unlink(missing_ok=True)


def capture_snapshot(*, observation="", all_screens=False, target="screen", window="",
                     save_path=None, save=False, encode=True, now=None):
    """Capture a screenshot for vision and/or saving.

    Returns a dict with the encoded image (unless encode=False), the capture
    source and the saved file path when one was written.  Raises ValueError /
    RuntimeError on invalid input or capture failure.
    """
    if not isinstance(observation, str):
        raise ValueError("observation 必须是字符串")
    if not isinstance(all_screens, bool):
        raise ValueError("all_screens 必须是布尔值")
    if not isinstance(target, str) or target not in ("screen", "window"):
        raise ValueError("target 只能是 screen 或 window")
    if not isinstance(window, str):
        raise ValueError("window 必须是字符串")
    dest = str(save_path or "").strip() or None

    if observation:
        image, state = _read_observation(observation, all_screens)
        try:
            saved = _save_image(image, dest) if dest else None
            encoded = _encode(image) if encode else {"width": image.width, "height": image.height}
        finally:
            image.close()
        return {
            **encoded, "source": "computer-use", "observation": observation,
            "window_id": state["window_id"], "temporary_file_deleted": True,
            "saved_to_disk": bool(saved), "path": saved,
        }

    if all_screens and target == "window":
        raise ValueError("target=window 时不能同时使用 all_screens")
    if target == "window":
        if not window:
            raise ValueError("target=window 时必须提供 window 关键词")
        from window_capture import capture_window_image
        image, meta = capture_window_image(window)
        source = "window"
    else:
        image = ImageGrab.grab(all_screens=all_screens)
        meta = {"source": "screen", "all_screens": all_screens}
        source = "screen"
    try:
        if dest is None and save:
            dest = default_save_path(source, now)
        saved = _save_image(image, dest) if dest else None
        encoded = _encode(image) if encode else {"width": image.width, "height": image.height}
    finally:
        image.close()
    result = {**encoded, **{k: v for k, v in meta.items() if k != "source"},
              "source": source, "temporary_file_deleted": False,
              "saved_to_disk": bool(saved), "path": saved}
    if meta.get("window"):
        result["window"] = meta["window"]
    return result
