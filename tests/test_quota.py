"""多供应商 API 额度查询（pet_quota）回归测试。

全部用例都使用注入的假 opener，不产生任何真实网络请求。
"""
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pet_quota


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self.code = status
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_opener(routes, calls=None):
    """routes: {路径: (状态码, JSON负载)}；未列出的路径一律 404。"""
    def opener(request, timeout):
        parts = urlparse(request.full_url)
        path = parts.path + (("?" + parts.query) if parts.query else "")
        if calls is not None:
            calls.append(path)
        entry = routes.get(parts.path)
        if entry is None:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", None, None)
        status, payload = entry
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", None, None)
        return FakeResponse(payload, status)
    return opener


class DeepSeekTests(unittest.TestCase):
    BALANCE = {"is_available": True, "balance_infos": [
        {"currency": "CNY", "total_balance": "12.34",
         "granted_balance": "10.00", "topped_up_balance": "2.34"}]}

    def test_domain_probe_wins_and_reports_cny(self):
        calls = []
        result = pet_quota.query("https://api.deepseek.com", "sk-test",
                                 opener=make_opener({"/user/balance": (200, self.BALANCE)}, calls))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "deepseek")
        self.assertEqual(result["provider_name"], "DeepSeek")
        self.assertEqual(result["currency"], "CNY")
        self.assertEqual(result["remaining"], 12.34)
        self.assertEqual(result["source"], "/user/balance")
        # 首选就是 DeepSeek 自己的余额接口
        self.assertEqual(calls[0], "/user/balance")
        # 非美元账户不得伪装成 USD 字段
        self.assertNotIn("remaining_usd", result)

    def test_base_url_with_v1_still_hits_root_balance(self):
        calls = []
        result = pet_quota.query("https://api.deepseek.com/v1", "sk-test",
                                 opener=make_opener({"/user/balance": (200, self.BALANCE)}, calls))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["remaining"], 12.34)

    def test_unavailable_balance_is_noted(self):
        payload = {"is_available": False, "balance_infos": [
            {"currency": "USD", "total_balance": "0.00"}]}
        result = pet_quota.query("https://api.deepseek.com", "sk-test",
                                 opener=make_opener({"/user/balance": (200, payload)}))
        self.assertEqual(result["note"], "余额不足，接口可能已停用")
        self.assertEqual(result["remaining_usd"], 0.0)


class OpenRouterTests(unittest.TestCase):
    def test_credits_endpoint(self):
        result = pet_quota.query(
            "https://openrouter.ai/api/v1", "sk-test",
            opener=make_opener({"/api/v1/credits": (200, {"data": {
                "total_credits": 100.5, "total_usage": 25.75}})}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider_name"], "OpenRouter")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["remaining"], 74.75)
        self.assertEqual(result["used"], 25.75)
        self.assertEqual(result["total"], 100.5)
        self.assertEqual(result["usage_percentage"], "25.62%")

    def test_key_endpoint_fallback(self):
        payload = {"data": {"limit": 10, "usage": 4, "limit_remaining": 6}}
        result = pet_quota.query(
            "https://openrouter.ai/api/v1", "sk-test",
            opener=make_opener({"/api/v1/key": (200, payload)}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["remaining"], 6.0)
        self.assertEqual(result["used"], 4.0)
        self.assertEqual(result["total"], 10.0)


class ChineseProviderTests(unittest.TestCase):
    def test_siliconflow_user_info(self):
        payload = {"code": 20000, "data": {
            "balance": "88.88", "totalBalance": "100.00", "chargeBalance": "50.00"}}
        result = pet_quota.query(
            "https://api.siliconflow.cn/v1", "sk-test",
            opener=make_opener({"/v1/user/info": (200, payload)}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider_name"], "硅基流动")
        self.assertEqual(result["currency"], "CNY")
        # 平台只报余额、不报累计消耗：剩余取 totalBalance，已用/总额留空
        self.assertEqual(result["remaining"], 100.0)
        self.assertIsNone(result["used"])
        self.assertIsNone(result["total"])
        self.assertEqual(pet_quota.format_summary(result), "剩余 ¥100.00")

    def test_siliconflow_international_is_usd(self):
        payload = {"data": {"balance": "0.88", "totalBalance": "88.88"}}
        result = pet_quota.query(
            "https://api.siliconflow.com/v1", "sk-test",
            opener=make_opener({"/v1/user/info": (200, payload)}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["remaining"], 88.88)

    def test_moonshot_balance(self):
        payload = {"code": 0, "data": {
            "available_balance": 49.58894, "voucher_balance": 46.58893,
            "cash_balance": 3.00001}}
        result = pet_quota.query(
            "https://api.moonshot.ai/v1", "sk-test",
            opener=make_opener({"/v1/users/me/balance": (200, payload)}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider_name"], "Moonshot (Kimi)")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["remaining"], 49.5889)

    def test_moonshot_cn_is_cny(self):
        payload = {"code": 0, "data": {"available_balance": 100.0}}
        result = pet_quota.query(
            "https://api.moonshot.cn/v1", "sk-test",
            opener=make_opener({"/v1/users/me/balance": (200, payload)}))
        self.assertEqual(result["currency"], "CNY")
        self.assertEqual(pet_quota.format_summary(result), "剩余 ¥100.00")


class OneApiFamilyTests(unittest.TestCase):
    def test_dashboard_billing_subscription_and_usage(self):
        result = pet_quota.query(
            "https://api.kourichat.com/v1", "sk-test",
            opener=make_opener({
                "/v1/dashboard/billing/subscription": (200, {
                    "hard_limit_usd": 20.0, "access_until": 1790000000}),
                "/v1/dashboard/billing/usage": (200, {"total_usage": 500}),
            }))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["remaining"], 15.0)
        self.assertEqual(result["used"], 5.0)
        self.assertEqual(result["total"], 20.0)
        self.assertRegex(result["expire_time"], r"^\d{4}-\d{2}-\d{2}$")

    def test_newapi_user_self_on_unknown_relay(self):
        calls = []
        result = pet_quota.query(
            "https://relay.example.com", "sk-test",
            opener=make_opener({"/api/user/self": (200, {
                "success": True, "data": {"quota": 2500000, "used_quota": 1000000},
            })}, calls))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["remaining"], 5.0)
        self.assertEqual(result["used"], 2.0)
        self.assertEqual(result["total"], 7.0)
        # 未收录域名：provider 回落为域名，但仍能读到额度
        self.assertEqual(result["provider"], "relay.example.com")
        self.assertIn("/api/user/self", calls)

    def test_unknown_relay_with_deepseek_style_balance(self):
        result = pet_quota.query(
            "https://another-relay.example.com/v1", "sk-test",
            opener=make_opener({"/user/balance": (200, {"is_available": True, "balance_infos": [
                {"currency": "USD", "total_balance": "7.50"}]})}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["remaining"], 7.5)
        self.assertEqual(result["remaining_usd"], 7.5)


class FailureTests(unittest.TestCase):
    def test_missing_key_or_url(self):
        self.assertEqual(pet_quota.query("https://api.deepseek.com", "")["status"], "error")
        self.assertEqual(pet_quota.query("", "sk-test")["status"], "error")

    def test_auth_rejection_is_explained(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", None, None)

        result = pet_quota.query("https://api.deepseek.com", "sk-test", opener=opener)
        self.assertEqual(result["status"], "error")
        self.assertIn("401", result["message"])
        self.assertTrue(result["tried"])

    def test_probe_budget_is_bounded(self):
        calls = []
        result = pet_quota.query("https://unknown.example.com/v1", "sk-test",
                                 opener=make_opener({}, calls))
        self.assertEqual(result["status"], "error")
        self.assertLessEqual(len(calls), pet_quota.MAX_ATTEMPTS)
        self.assertGreaterEqual(len(calls), 4)
        self.assertIn("没能", result["message"])


class FormattingTests(unittest.TestCase):
    def test_format_amount(self):
        self.assertEqual(pet_quota.format_amount(12.3, "USD"), "$12.30")
        self.assertEqual(pet_quota.format_amount(1234.5, "CNY"), "¥1,234.50")
        self.assertEqual(pet_quota.format_amount(5, "XYZ"), "5.00 XYZ")
        self.assertEqual(pet_quota.format_amount(None, "USD"), "未知")

    def test_format_summary(self):
        full = {"status": "success", "currency": "USD", "remaining": 15.0,
                "used": 5.0, "total": 20.0, "expire_time": "未知"}
        self.assertEqual(pet_quota.format_summary(full),
                         "剩余 $15.00（已用 $5.00 / 总 $20.00）")
        only_remaining = {"status": "success", "currency": "CNY", "remaining": 12.34,
                          "used": None, "total": None, "expire_time": "未知"}
        self.assertEqual(pet_quota.format_summary(only_remaining), "剩余 ¥12.34")
        only_used = {"status": "success", "currency": "USD", "remaining": None,
                     "used": 3.0, "total": None, "expire_time": "未知"}
        self.assertEqual(pet_quota.format_summary(only_used), "已用 $3.00（总额度未提供）")
        with_expiry = dict(full, expire_time="2026-10-01")
        self.assertIn("有效期至 2026-10-01", pet_quota.format_summary(with_expiry))
        self.assertEqual(pet_quota.format_summary({"status": "error"}), "")

    def test_is_low_and_provider_label(self):
        result = {"status": "success", "remaining": 8.0, "currency": "USD",
                  "provider_name": "DeepSeek"}
        self.assertTrue(pet_quota.is_low(result, 10))
        self.assertFalse(pet_quota.is_low(result, 5))
        self.assertIsNone(pet_quota.is_low({"status": "success", "remaining": None}, 10))
        self.assertIsNone(pet_quota.is_low({"status": "error"}, 10))
        self.assertEqual(pet_quota.provider_label(result), "DeepSeek")
        self.assertEqual(pet_quota.provider_label(None), "API")


if __name__ == "__main__":
    unittest.main()
