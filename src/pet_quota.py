#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多供应商 API 额度查询。

不同供应商的额度 / 余额接口路径与字段完全不同，本模块把它们归一化成同一份结果：

    {
      "status": "success",
      "provider": "deepseek",              # 识别出的供应商标识（未收录时为域名）
      "provider_name": "DeepSeek",         # 用于展示的名称
      "currency": "CNY",
      "currency_symbol": "¥",
      "remaining": 12.34,                  # 账户币种下的剩余额度
      "used": 1.23,                        # 已使用（部分供应商不提供）
      "total": 13.57,                      # 总额度（部分供应商不提供）
      "usage_percentage": "9.06%",
      "expire_time": "2026-10-01" | "未知",
      "source": "/user/balance",           # 真正命中的接口路径，便于排错
      "note": "可选提示",
      # 兼容旧字段：仅在币种为 USD 时给出，避免把其它币种当美元用
      "remaining_usd": 12.34,
      "total_used_usd": 1.23,
      "total_granted_usd": 13.57
    }

已收录（探测顺序 = 域名命中优先 → 供应商家族常用接口 → 其余兜底）：

* OpenAI 计费接口 / OneAPI / NewAPI 中转站：``/dashboard/billing/subscription`` + ``/dashboard/billing/usage``
* OneAPI / NewAPI 账户接口：``/api/user/self``
* DeepSeek 官方：``/user/balance``
* OpenRouter：``/credits``（管理密钥），回退 ``/key``
* 硅基流动 SiliconFlow：``/user/info``
* Moonshot / Kimi：``/users/me/balance``

未收录的供应商不会被排除：所有探测路径都只发给用户自己填写的那个 API 地址，
按「域名命中 → 供应商家族常用接口 → 其余兜底」逐个尝试，命中即返回；因此自建 /
中转服务只要实现了上面任意一种常见额度接口就能读到数据。

对外接口：
    query(base_url, api_key, extra_headers=None, timeout=..., opener=None) -> dict
    format_amount(value, currency) -> str
    format_summary(result) -> str
    provider_label(result) -> str
    is_low(result, threshold) -> bool | None
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import urlparse

REQUEST_TIMEOUT = 6.0       # 单个额度接口的请求超时（秒）
TOTAL_BUDGET_SECS = 24.0    # 一次查询的总体时间预算（秒）
MAX_ATTEMPTS = 12           # 一次查询最多请求多少个接口

_CURRENCY_SYMBOLS = {
    "USD": "$", "US$": "$", "CNY": "¥", "RMB": "¥", "CNH": "¥",
    "EUR": "€", "GBP": "£", "JPY": "¥", "HKD": "HK$", "TWD": "NT$",
}

_PROVIDER_NAMES = {
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "siliconflow": "硅基流动",
    "moonshot": "Moonshot (Kimi)",
    "openai": "OpenAI",
    "oneapi": "OneAPI / NewAPI",
    "kouri": "Kouri",
}

# OneAPI / NewAPI 内部额度单位：500000 = $1
_ONEAPI_QUOTA_PER_USD = 500000.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _num(value):
    """宽松地把接口返回值转成 float：数字、数字字符串都接受。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _round(value):
    return None if value is None else round(float(value), 4)


def _urlopen(req, timeout):
    """与主程序一致的稳健 HTTP：先走系统代理，失败再直连（跳过失效的本地代理）。"""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except Exception:
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return direct.open(req, timeout=timeout)


class _Ctx:
    """一次查询的上下文：地址、鉴权头与已尝试过的接口记录。"""

    def __init__(self, base_url, api_key, extra_headers=None,
                 timeout=REQUEST_TIMEOUT, opener=None):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.extra_headers = dict(extra_headers or {})
        self.timeout = float(timeout or REQUEST_TIMEOUT)
        self.opener = opener or _urlopen
        self.deadline = time.monotonic() + TOTAL_BUDGET_SECS
        self.stop = False
        self.attempts = []      # [(path, status|错误类型), ...]
        self.ok_paths = []      # 返回过可解析 JSON 的接口路径
        self.auth_error = False

    @property
    def root(self):
        """去掉结尾的 /v1：用于 /user/balance、/api/user/self 这类根路径接口。"""
        return self.base_url[:-3].rstrip("/") if self.base_url.endswith("/v1") else self.base_url

    @property
    def v1(self):
        """保证以 /v1 结尾：用于 /credits、/user/info、/users/me/balance 等接口。"""
        return self.base_url if self.base_url.endswith("/v1") else self.base_url + "/v1"

    def headers(self):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        headers.update(self.extra_headers)
        return headers

    def get_json(self, url):
        """GET 一个候选额度接口，返回解析后的 JSON；任何失败都返回 None 并记账。"""
        if self.stop or len(self.attempts) >= MAX_ATTEMPTS or time.monotonic() > self.deadline:
            self.stop = True
            return None
        path = urlparse(url).path or "/"
        query = urlparse(url).query
        if query:
            path = f"{path}?{query}"
        try:
            request = urllib.request.Request(url, headers=self.headers(), method="GET")
            with self.opener(request, self.timeout) as resp:
                status = getattr(resp, "status", None) or getattr(resp, "code", 200)
                raw = resp.read()
            self.attempts.append((path, status))
        except urllib.error.HTTPError as exc:
            self.attempts.append((path, exc.code))
            if exc.code in (401, 403):
                self.auth_error = True
            return None
        except Exception as exc:  # 网络错误 / 超时 / 不支持的地址
            self.attempts.append((path, type(exc).__name__))
            return None
        try:
            parsed = json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, AttributeError):
            return None
        self.ok_paths.append(path)
        return parsed


def _result(ctx, currency, remaining=None, used=None, total=None,
            expire=None, note=None, source=None):
    """组装统一成功结果（未命中的字段留 None，交由展示层决定怎么说）。"""
    currency = str(currency or "").upper() or "USD"
    if total is None and remaining is not None and used is not None:
        total = remaining + used
    if remaining is None and total is not None and used is not None:
        remaining = max(0.0, total - used)
    percent = None
    if total and total > 0:
        spent = used if used is not None else (total - remaining if remaining is not None else None)
        if spent is not None:
            percent = f"{spent / total * 100:.2f}%"
    result = {
        "status": "success",
        "currency": currency,
        "currency_symbol": _CURRENCY_SYMBOLS.get(currency, ""),
        "remaining": _round(remaining),
        "used": _round(used),
        "total": _round(total),
        "usage_percentage": percent,
        "expire_time": expire or "未知",
        "source": source or (ctx.ok_paths[-1] if ctx.ok_paths else ""),
    }
    if note:
        result["note"] = note
    if currency == "USD":
        result["remaining_usd"] = result["remaining"]
        result["total_used_usd"] = result["used"]
        result["total_granted_usd"] = result["total"]
    return result


# ---------------------------------------------------------------------------
# 各供应商额度接口探测
# ---------------------------------------------------------------------------

def _probe_balance_dashboard(ctx):
    """OpenAI 计费接口 / OneAPI / NewAPI：subscription + usage（美元）。"""
    subscription = ctx.get_json(f"{ctx.v1}/dashboard/billing/subscription")
    if not isinstance(subscription, dict):
        subscription = ctx.get_json(f"{ctx.root}/dashboard/billing/subscription")
    if not isinstance(subscription, dict):
        return None
    total = _num(subscription.get("hard_limit_usd"))
    expire = "永久有效"
    until = _num(subscription.get("access_until"))
    if until and until > 0:
        try:
            expire = datetime.fromtimestamp(until).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            expire = "永久有效"
    today = datetime.now()
    start = (today - timedelta(days=3650)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    suffix = f"?start_date={start}&end_date={end}"
    usage = ctx.get_json(f"{ctx.v1}/dashboard/billing/usage{suffix}")
    if not isinstance(usage, dict):
        usage = ctx.get_json(f"{ctx.root}/dashboard/billing/usage{suffix}")
    used = None
    if isinstance(usage, dict):
        cents = _num(usage.get("total_usage"))
        if cents is not None:
            used = cents / 100.0
    if total is None and used is None:
        return None
    remaining = max(0.0, total - used) if (total is not None and used is not None) else None
    note = None if used is not None else "已用量接口不可用，只能读到总额度"
    return _result(ctx, "USD", remaining, used, total, expire, note=note)


def _probe_user_self(ctx):
    """OneAPI / NewAPI 账户接口：/api/user/self（额度单位为 500000 = $1）。"""
    data = ctx.get_json(f"{ctx.root}/api/user/self")
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None
    quota = _num(payload.get("quota"))
    used_quota = _num(payload.get("used_quota"))
    if quota is None and used_quota is None:
        return None
    remaining = None if quota is None else quota / _ONEAPI_QUOTA_PER_USD
    used = None if used_quota is None else used_quota / _ONEAPI_QUOTA_PER_USD
    total = None
    if remaining is not None and used is not None:
        total = remaining + used
    return _result(ctx, "USD", remaining, used, total)


def _probe_deepseek(ctx):
    """DeepSeek 官方：/user/balance（balance_infos[0].total_balance）。"""
    data = ctx.get_json(f"{ctx.root}/user/balance")
    if not isinstance(data, dict):
        data = ctx.get_json(f"{ctx.v1}/user/balance")
    infos = data.get("balance_infos") if isinstance(data, dict) else None
    if not isinstance(infos, list) or not infos:
        return None
    info = infos[0] if isinstance(infos[0], dict) else {}
    currency = str(info.get("currency") or "CNY").upper()
    remaining = _num(info.get("total_balance"))
    if remaining is None:
        granted = _num(info.get("granted_balance"))
        topped = _num(info.get("topped_up_balance"))
        if granted is not None or topped is not None:
            remaining = (granted or 0.0) + (topped or 0.0)
    if remaining is None:
        return None
    note = None if data.get("is_available", True) else "余额不足，接口可能已停用"
    return _result(ctx, currency, remaining=remaining, note=note)


def _probe_openrouter(ctx):
    """OpenRouter：/credits（管理密钥），回退 /key 的额度上限。"""
    data = ctx.get_json(f"{ctx.v1}/credits")
    payload = data.get("data") if isinstance(data, dict) else None
    if isinstance(payload, dict):
        total = _num(payload.get("total_credits"))
        used = _num(payload.get("total_usage"))
        if total is not None or used is not None:
            remaining = max(0.0, total - used) if (total is not None and used is not None) else None
            return _result(ctx, "USD", remaining, used, total)
    key = ctx.get_json(f"{ctx.v1}/key")
    payload = key.get("data") if isinstance(key, dict) else None
    if not isinstance(payload, dict):
        return None
    remaining = _num(payload.get("limit_remaining"))
    used = _num(payload.get("usage"))
    limit = _num(payload.get("limit"))
    if remaining is None and used is None:
        return None
    return _result(ctx, "USD", remaining, used, limit)


def _probe_siliconflow(ctx):
    """硅基流动 SiliconFlow：/user/info。

    字段含义：``totalBalance`` = 可用总余额（充值 + 赠送），``chargeBalance`` = 充值余额，
    ``balance`` = 赠送余额。平台只提供余额、不提供累计消耗，因此这里只报剩余额度，
    已用 / 总额留空而不是编造。"""
    data = ctx.get_json(f"{ctx.v1}/user/info")
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None
    total_balance = _num(payload.get("totalBalance"))
    if total_balance is None:
        total_balance = _num(payload.get("total_balance"))
    gift = _num(payload.get("balance"))
    remaining = total_balance if total_balance is not None else gift
    if remaining is None:
        return None
    currency = str(payload.get("currency") or "").upper() or _host_currency(ctx)
    return _result(ctx, currency, remaining=remaining)


def _host_currency(ctx):
    """按域名猜账户币种：国内站点（.cn）为人民币，国际站点为美元。

    只用于接口本身不返回币种的情况（硅基流动、Moonshot）；DeepSeek 等会自带 currency。"""
    host = (urlparse(ctx.base_url).hostname or "").lower()
    return "CNY" if host.endswith(".cn") else "USD"


def _probe_moonshot(ctx):
    """Moonshot / Kimi：/users/me/balance（available_balance）。

    国际站（api.moonshot.ai / platform.kimi.ai）以美元计价，国内站（api.moonshot.cn）以人民币计价。"""
    data = ctx.get_json(f"{ctx.v1}/users/me/balance")
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None
    remaining = _num(payload.get("available_balance"))
    if remaining is None:
        return None
    currency = str(payload.get("currency") or "").upper() or _host_currency(ctx)
    return _result(ctx, currency, remaining=remaining)


# 探测顺序 = 域名命中优先 → 该供应商家族的常用接口 → 其余按声明顺序兜底。
# 声明顺序刻意把 OpenAI 计费 / OneAPI / NewAPI 放最前：绝大多数自建中转站属于这一族。
_PROBES = (
    {"id": "oneapi", "hosts": (), "fn": _probe_balance_dashboard},
    {"id": "oneapi", "hosts": (), "fn": _probe_user_self},
    {"id": "deepseek", "hosts": ("api.deepseek.com",), "fn": _probe_deepseek},
    {"id": "openrouter", "hosts": ("openrouter.ai",), "fn": _probe_openrouter},
    {"id": "siliconflow", "hosts": ("api.siliconflow.cn", "api.siliconflow.com"),
     "fn": _probe_siliconflow},
    {"id": "moonshot", "hosts": ("api.moonshot.cn", "api.moonshot.ai", "api.kimi.com"),
     "fn": _probe_moonshot},
)

# 没有专属探测路径、但属于某一族的供应商：按家族常用接口优先尝试。
_FAMILY_ORDER = {
    "kouri": ("_probe_balance_dashboard", "_probe_user_self"),
    "openai": ("_probe_balance_dashboard", "_probe_user_self"),
    "oneapi": ("_probe_balance_dashboard", "_probe_user_self"),
}


def detect_provider(host):
    """按域名识别供应商；未收录时返回 ""（仍会走通用探测）。"""
    host = str(host or "").lower()
    if not host:
        return ""
    if "kourichat" in host or "kouri.chat" in host:
        return "kouri"
    for probe in _PROBES:
        for candidate in probe["hosts"]:
            if host == candidate or host.endswith("." + candidate):
                return probe["id"]
    return ""


def _provider_label(provider, host=""):
    if provider in _PROVIDER_NAMES:
        return _PROVIDER_NAMES[provider]
    return host or "API"


def _ordered_probes(provider):
    """域名命中的探测优先，其次该供应商家族的常用接口，其余按声明顺序兜底。

    同名探测只保留最先出现的那条，避免同一路径重复请求。"""
    preferred = [p for p in _PROBES if provider and p["id"] == provider and p["hosts"]]
    family_names = _FAMILY_ORDER.get(provider, ())
    family = [p for p in _PROBES if p["fn"].__name__ in family_names]
    seen, ordered = set(), []
    for probe in preferred + family + list(_PROBES):
        key = probe["fn"].__name__
        if key in seen:
            continue
        seen.add(key)
        ordered.append(probe)
    return ordered


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def query(base_url, api_key="", extra_headers=None, timeout=REQUEST_TIMEOUT, opener=None):
    """查询当前 API 地址对应账户的额度，返回统一结果字典。"""
    ctx = _Ctx(base_url, api_key, extra_headers=extra_headers,
               timeout=timeout, opener=opener)
    host = (urlparse(ctx.base_url).hostname or "").lower()
    provider = detect_provider(host)
    label = _provider_label(provider, host)
    if not ctx.base_url:
        return {"status": "error", "message": "还没有配置 API 地址呢"}
    if not ctx.api_key:
        return {"status": "error", "message": "还没有配置 API Key 呢"}

    for probe in _ordered_probes(provider):
        if ctx.stop:
            break
        try:
            result = probe["fn"](ctx)
        except Exception:
            result = None
        if isinstance(result, dict) and result.get("status") == "success":
            result["provider"] = provider or host
            result["provider_name"] = label
            return result

    tried = [{"path": path, "result": status} for path, status in ctx.attempts]
    if ctx.auth_error:
        message = f"{label} 拒绝了额度查询（401/403），该 Key 可能没有账单权限"
    else:
        message = f"没能从 {label} 的常见额度接口读到数据（已试 {len(ctx.attempts)} 个）"
    return {"status": "error", "message": message, "provider": provider or host,
            "provider_name": label, "tried": tried}


def format_amount(value, currency=None):
    """把额度数字格式化成带币种的短文本，例如 ``$12.34`` / ``¥12.34`` / ``-$1.00``。"""
    number = _num(value)
    if number is None:
        return "未知"
    code = str(currency or "").upper()
    sign = "-" if number < 0 else ""
    text = f"{abs(number):,.2f}"
    symbol = _CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{sign}{symbol}{text}"
    return f"{sign}{text} {code}".strip()


def provider_label(result):
    """结果对应的供应商展示名。"""
    if not isinstance(result, dict):
        return "API"
    return str(result.get("provider_name") or result.get("provider") or "API")


def format_summary(result):
    """一句话额度摘要：剩余 / 已用 / 总额（缺哪项就不说哪项）。"""
    if not isinstance(result, dict) or result.get("status") != "success":
        return ""
    currency = result.get("currency")
    remaining = _num(result.get("remaining"))
    used = _num(result.get("used"))
    total = _num(result.get("total"))
    if remaining is not None and used is not None and total is not None:
        text = (f"剩余 {format_amount(remaining, currency)}"
                f"（已用 {format_amount(used, currency)} / 总 {format_amount(total, currency)}）")
    elif remaining is not None and total is not None:
        text = f"剩余 {format_amount(remaining, currency)}（总 {format_amount(total, currency)}）"
    elif remaining is not None:
        text = f"剩余 {format_amount(remaining, currency)}"
    elif used is not None:
        text = f"已用 {format_amount(used, currency)}（总额度未提供）"
    elif total is not None:
        text = f"总额度 {format_amount(total, currency)}（剩余未知）"
    else:
        return "额度信息不完整"
    expire = str(result.get("expire_time") or "")
    if expire and expire not in ("未知", "永久有效"):
        text += f"，有效期至 {expire}"
    return text


def is_low(result, threshold):
    """剩余额度是否不高于阈值（阈值按账户币种比较）；无法判断时返回 None。"""
    if not isinstance(result, dict) or result.get("status") != "success":
        return None
    remaining = _num(result.get("remaining"))
    limit = _num(threshold)
    if remaining is None or limit is None:
        return None
    return remaining <= limit
