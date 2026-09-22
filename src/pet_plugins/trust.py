# -*- coding: utf-8 -*-
"""插件信任库：首次加载弹窗确认，确认后按内容哈希记住。

插件就是任意 Python 代码，放进 plugins 文件夹即等于交出本机执行权限，
因此默认策略是「新的或内容变过的插件必须经主人确认一次」：

- 确认过 → 记下 ``{"status": "trusted", "hash": ...}``，之后静默加载；
- 拒绝过 → 记下 ``{"status": "denied", "hash": ...}``，不再反复打扰；
- 内容变化 → 哈希不匹配，视为新插件重新询问（避免"确认过的空壳被换芯"）。

信任库保存在数据目录的 plugin_trust.json，属于本机运行数据。
"""
import hashlib
import json
import os
import threading
import time

TRUST_FILE = "plugin_trust.json"
_CHUNK = 1024 * 1024
_SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vs", ".vscode"}


def file_digest(path):
    """单个文件的 sha256（带 sha256: 前缀）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def path_digest(path):
    """文件或文件夹的内容指纹。

    文件夹按「相对路径 + 内容」排序后汇总，因此增删/改名/改内容都会变，
    但文件系统时间戳变化不会误判。
    """
    path = os.path.abspath(str(path))
    if os.path.isfile(path):
        return file_digest(path)
    if not os.path.isdir(path):
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, name)
            entries.append((os.path.relpath(full, path).replace("\\", "/"), full))
    for relative, full in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(file_digest(full).encode("ascii"))
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


class TrustStore:
    """plugin_trust.json 的读写与状态判定。"""

    def __init__(self, data_dir):
        self.path = os.path.join(str(data_dir), TRUST_FILE)
        self._data = {}
        self._lock = threading.RLock()
        self.load()

    def load(self):
        with self._lock:
            self._data = {}
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    plugins = data.get("plugins")
                    self._data = plugins if isinstance(plugins, dict) else {}
            except (OSError, ValueError, UnicodeError):
                self._data = {}
            return self._data

    def save(self):
        with self._lock:
            payload = {"format": 1, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "plugins": self._data}
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
                return True
            except OSError:
                return False

    # -- 查询 --------------------------------------------------------------
    def record(self, name):
        with self._lock:
            item = self._data.get(str(name))
            return dict(item) if isinstance(item, dict) else {}

    def status(self, name, digest):
        """返回 trusted / denied / new / changed。"""
        item = self.record(name)
        if not item or item.get("hash") != digest:
            return "changed" if item else "new"
        return "denied" if item.get("status") == "denied" else "trusted"

    def is_trusted(self, name, digest):
        return self.status(name, digest) == "trusted"

    # -- 写入 --------------------------------------------------------------
    def decide(self, name, digest, allowed):
        with self._lock:
            self._data[str(name)] = {
                "status": "trusted" if allowed else "denied",
                "hash": digest,
                "path": self._data.get(str(name), {}).get("path", ""),
                "decided_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        self.save()

    def set_path(self, name, path):
        with self._lock:
            item = self._data.setdefault(str(name), {})
            if isinstance(item, dict):
                item["path"] = str(path)
        self.save()

    def forget(self, name):
        with self._lock:
            self._data.pop(str(name), None)
        self.save()

    def trusted_names(self):
        with self._lock:
            return sorted(k for k, v in self._data.items()
                          if isinstance(v, dict) and v.get("status") == "trusted")
