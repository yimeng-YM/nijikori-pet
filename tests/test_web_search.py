import base64
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pet_config
import pet_search as search


BAIDU = '''<html><head><title>Python tkinter 官方文档_百度搜索</title></head>
<body><div id="content_left">
<div><h3><a href="https://www.baidu.com/baidu.php?ad=1">广告</a></h3></div>
<div class="result c-container new-pmd" mu="https://docs.python.org/zh-cn/3/library/tkinter.html?utm_source=baidu">
<h3><a href="http://www.baidu.com/link?url=redirect"><span><em>tkinter</em> 官方文档</span></a></h3>
<div><span>嵌套的中文摘要 &amp; Python 接口。</span></div><script>untrusted_script()</script></div>
<div class="result c-container" mu="https://docs.python.org/zh-cn/3/library/tkinter.html#same">
<h3><a href="https://example.org/duplicate">重复结果</a></h3></div>
</div></body></html>'''
DDG = '''<html><div class="result result--ad"><a class="result__a" href="https://ad.example.org">广告</a></div>
<div class="result web-result"><h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fdocs%3Fq%3Da%26utm_source%3Dx">Example 文档</a></h2>
<a class="result__snippet">真实的 <b>网页</b> 摘要</a></div>
<a href="https://navigation.example.org">导航</a></html>'''


def bing_page(url="https://docs.python.org/3/library/tkinter.html", title="Tkinter Python reference"):
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f'''<html><li class="b_algo other"><h2><a href="https://www.bing.com/ck/a?u=a1{encoded}"><strong>{title}</strong></a></h2>
<div class="b_caption"><p>Python GUI programming &amp; examples</p></div></li></html>'''


def rows(engine, count=5):
    return [{"title": f"Source {i}", "url": f"https://example.org/{i}",
             "snippet": "Source evidence", "engine": engine} for i in range(count)]


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200, charset="utf-8"):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "text/html" + (f"; charset={charset}" if charset else "")


class ParserTests(unittest.TestCase):
    def test_baidu_nested_markup_original_url_and_ads(self):
        result = search.parse_results(BAIDU, "baidu")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://docs.python.org/zh-cn/3/library/tkinter.html")
        self.assertIn("中文摘要", result[0]["snippet"])
        self.assertNotIn("untrusted_script", result[0]["snippet"])

    def test_bing_unwraps_base64_redirect(self):
        result = search.parse_results(bing_page(), "bing")
        self.assertEqual(result[0]["url"], "https://docs.python.org/3/library/tkinter.html")
        self.assertEqual(result[0]["snippet"], "Python GUI programming & examples")

    def test_ddg_unwraps_redirect_and_ignores_navigation(self):
        result = search.parse_results(DDG, "duckduckgo")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://example.org/docs?q=a")

    def test_brave_returns_only_web_cards(self):
        doc = '''<div class="snippet" data-type="ad"><a href="https://ad.example"><div class="title">ad</div></a></div>
<div class="snippet" data-type="web"><a href="https://example.org/doc"><cite>Site breadcrumb</cite><div class="search-snippet-title">Document title</div></a>
<div class="generic-snippet"><div class="content">Document summary</div></div></div>'''
        result = search.parse_results(doc, "brave")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Document title")
        self.assertEqual(result[0]["snippet"], "Document summary")

    def test_360_uses_original_url(self):
        doc = '''<li class="res-list"><h3 class="res-title"><a href="https://www.so.com/link?m=redirect" data-mdurl="https://example.org/weather">天气</a></h3>
<div class="res-rich"><span class="res-list-summary">北京天气摘要</span></div></li>'''
        result = search.parse_results(doc, "so")
        self.assertEqual(result[0]["url"], "https://example.org/weather")
        self.assertEqual(result[0]["snippet"], "北京天气摘要")

    def test_captcha_is_not_a_success(self):
        for engine, page in [("duckduckgo", '<form id="challenge-form">Select ducks</form>'),
                             ("baidu", '<title>百度安全验证</title>'),
                             ("bing", '<div id="b_captcha"></div>')]:
            with self.subTest(engine=engine), self.assertRaises(search.SearchFailure):
                search.parse_results(page, engine)

    def test_empty_page_and_unsafe_links(self):
        self.assertEqual(search.parse_results('<a href="https://example.org">Navigation</a>', "bing"), [])
        for url in ("javascript:alert(1)", "file:///C:/secret", "https://user:pass@example.org", "https://x:bad/"):
            self.assertEqual(search._clean_url(url, "bing"), "")

    def test_bing_query_broadening_is_discarded(self):
        with patch.object(search, "_fetch", return_value=bing_page("https://python.org", "Welcome to Python")):
            result = search._search_engine("bing", "Python tkinter 官方文档", 5, 100, threading.Event(), None)
        self.assertEqual(result, [])

    def test_bing_relevant_query_is_retained(self):
        with patch.object(search, "_fetch", return_value=bing_page()):
            self.assertTrue(search._search_engine("bing", "Python tkinter documentation", 5, 100, threading.Event(), None))

    def test_bing_chinese_query_broadening_is_discarded(self):
        with patch.object(search, "_fetch", return_value=bing_page("https://example.org", "中国百科")):
            self.assertEqual(search._search_engine("bing", "中国天气网 北京 天气", 5, 100, threading.Event(), None), [])


class NetworkTests(unittest.TestCase):
    def fetch(self, opener):
        with patch.object(search.urllib.request, "build_opener", return_value=opener):
            return search._fetch("https://www.baidu.com/s?wd=test", time.monotonic() + 2, threading.Event(), None)

    def test_request_has_no_credentials_and_decodes_chinese(self):
        captured = []

        class Opener:
            def open(self, req, timeout):
                captured.append(req)
                return FakeResponse('<meta charset="gb18030">中文结果'.encode("gb18030"), charset=None)

        self.assertIn("中文结果", self.fetch(Opener()))
        self.assertEqual(captured[0].get_method(), "GET")
        self.assertNotIn("Authorization", captured[0].headers)
        self.assertNotIn("Cookie", captured[0].headers)
        self.assertIsNone(captured[0].data)

    def test_oversized_response_is_rejected(self):
        class Opener:
            def open(self, req, timeout):
                return FakeResponse(b"x" * 257)
        with patch.object(search, "MAX_RESPONSE_BYTES", 256), self.assertRaises(search.SearchFailure):
            self.fetch(Opener())

    def test_202_challenge_is_rejected(self):
        class Opener:
            def open(self, req, timeout):
                return FakeResponse(b"challenge", status=202)
        with self.assertRaisesRegex(search.SearchFailure, "验证码"):
            self.fetch(Opener())

    def test_broken_proxy_uses_direct_connection(self):
        used = []

        class Opener:
            def open(self, req, timeout):
                used.append(timeout)
                if len(used) == 1:
                    raise urllib.error.URLError("private proxy credentials")
                return FakeResponse(b"ok")

        with patch.object(search.urllib.request, "getproxies", return_value={"https": "http://127.0.0.1:9"}):
            self.assertEqual(self.fetch(Opener()), "ok")
        self.assertEqual(len(used), 2)

    def test_request_query_preserves_operators_and_unicode(self):
        query = 'site:python.org "tkinter" 中文 & docs'
        with patch.object(search, "_fetch", return_value=BAIDU) as fetch:
            search._search_engine("baidu", query, 5, 100, threading.Event(), None)
        from urllib.parse import urlsplit, parse_qs
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)["wd"], [query])


class CoordinatorTests(unittest.TestCase):
    def test_parallel_fallback_does_not_wait_for_stalled_primary(self):
        release = threading.Event()
        entered = threading.Event()

        def engine(name, *args):
            if name == "baidu":
                entered.set()
                release.wait(2)
                return []
            entered.wait(1)
            return rows(name)

        try:
            started = time.monotonic()
            result = search.LocalWebSearch(engine).search("中文搜索", timeout=1)
            self.assertEqual(result["status"], "success")
            self.assertLess(time.monotonic() - started, 0.8)
            self.assertNotIn("baidu", result["engines"])
        finally:
            release.set()

    def test_total_deadline_and_cancel_even_if_transport_stalls(self):
        release = threading.Event()

        def stalled(*args):
            release.wait(2)
            return []

        try:
            started = time.monotonic()
            result = search.LocalWebSearch(stalled).search("test", timeout=0.12)
            self.assertEqual(result["status"], "error")
            self.assertLess(time.monotonic() - started, 0.5)
            cancel = threading.Event()
            timer = threading.Timer(0.08, cancel.set)
            timer.start()
            started = time.monotonic()
            result = search.LocalWebSearch(stalled).search("test", timeout=2, cancel_event=cancel)
            timer.join()
            self.assertEqual(result["status"], "cancelled")
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            release.set()

    def test_cache_refresh_expiry_and_copy_isolation(self):
        calls = []

        def engine(name, *args):
            calls.append(name)
            return rows(name)

        client = search.LocalWebSearch(engine)
        first = client.search("中文")
        first["results"][0]["title"] = "mutated"
        count = len(calls)
        second = client.search("中文")
        self.assertTrue(second["cached"])
        self.assertNotEqual(second["results"][0]["title"], "mutated")
        self.assertEqual(second["searched_at"], first["searched_at"])
        self.assertEqual(len(calls), count)
        self.assertFalse(client.search("中文", refresh=True)["cached"])
        self.assertFalse(client.search("中文", limit=1)["cached"])
        client._cache_ttl = 0
        self.assertFalse(client.search("中文")["cached"])

    def test_cache_is_bounded(self):
        client = search.LocalWebSearch(lambda name, *args: rows(name))
        with patch.object(search, "CACHE_SIZE", 2):
            for query in ("one", "two", "three"):
                client.search(query)
        self.assertEqual(len(client._cache), 2)
        self.assertNotIn(("one", 5), client._cache)

    def test_failures_cool_down_without_disclosing_exception(self):
        calls = []

        def fail(name, *args):
            calls.append(name)
            raise OSError("secret-token@proxy")

        client = search.LocalWebSearch(fail)
        result = client.search("first")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("secret-token", str(result))
        self.assertEqual(len(calls), len(search.ENGINE_URLS))
        self.assertIn("retry_after_seconds", client.search("second"))
        self.assertEqual(len(calls), len(search.ENGINE_URLS))
        self.assertFalse(client._cache)

    def test_workers_are_bounded_across_repeated_timeouts(self):
        release = threading.Event()
        calls = []

        def stalled(name, *args):
            calls.append(name)
            release.wait(2)
            return []

        client = search.LocalWebSearch(stalled)
        try:
            for i in range(5):
                client.search(str(i), timeout=0.02)
            self.assertLessEqual(len(calls), search.MAX_WORKERS)
        finally:
            release.set()

    def test_invalid_arguments_never_start_network(self):
        def forbidden(*args):
            self.fail("Unexpected network request")
        client = search.LocalWebSearch(forbidden)
        for kwargs in ({"query": None}, {"query": " "}, {"query": "x" * 501},
                       {"query": "x", "limit": True}, {"query": "x", "limit": 11},
                       {"query": "x", "timeout": float("nan")},
                       {"query": "x", "refresh": "false"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(client.search(**kwargs)["status"], "error")
        event = threading.Event()
        event.set()
        self.assertEqual(client.search("query", cancel_event=event)["status"], "cancelled")

    def test_dedup_merges_partial_results_and_keeps_sources(self):
        def engine(name, *args):
            if name == "baidu":
                time.sleep(0.04)
                return rows(name, 1)
            return rows(name, 3)
        result = search.LocalWebSearch(engine).search("中文", limit=3)
        self.assertEqual(result["results_count"], 3)
        self.assertEqual(result["results"][0]["engine"], "baidu")
        self.assertEqual(len({r["url"] for r in result["results"]}), 3)
        self.assertIn("https://example.org/0", result["search_results"])


class ConfigTests(unittest.TestCase):
    def test_old_search_model_removed_without_changing_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"search_model": "retired-model", "api_key": "test-key",
                                        "model": "custom-chat", "reminders": []}), encoding="utf-8")
            result = pet_config.read_config(path)
        self.assertNotIn("search_model", result)
        self.assertEqual(result["api_key"], "test-key")
        self.assertEqual(result["model"], "custom-chat")
        self.assertEqual(result["reminders"], [])

    def test_settings_bounds(self):
        for key, values in {"web_search_timeout_secs": [0, 31, True, float("inf"), "8"],
                            "web_search_max_results": [0, 11, True, 2.5, "5"]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(pet_config.ConfigError):
                    pet_config.validate_config({key: value})
        pet_config.validate_config({"web_search_timeout_secs": 8, "web_search_max_results": 5})


@unittest.skipUnless(sys.platform == "win32", "Desktop integration uses Win32")
class IntegrationTests(unittest.TestCase):
    def test_search_guidance_applies_after_custom_persona_and_external_skills(self):
        import main
        from datetime import datetime
        from pet_search_prompt import build_search_prompt
        with patch.object(main, "load_action_log", return_value=[]), \
                patch.object(main, "build_search_prompt", return_value=build_search_prompt(datetime(2026, 9, 6))):
            prompt = main.build_prompt_with_memory("自定义角色：仅说 20 字。", {}, skills_block="外部技能示例：mcporter call exa.web_search_exa")
        self.assertTrue(prompt.startswith("自定义角色：仅说 20 字。"))
        self.assertGreater(prompt.index("【本地联网搜索：关键词与结果使用规则】"), prompt.index("外部技能示例"))
        self.assertIn("当前本地日期：2026-09-06", prompt)
        self.assertIn("2026年09月", prompt)
        self.assertIn("searched_at 是检索时间", prompt)
        self.assertIn("普通公开网页搜索直接调用内置 web_search", prompt)
        self.assertIn("工具参数和必要的来源链接不受 25 字", prompt)

    def test_tool_dispatch_ignores_provider_and_passes_cancellation(self):
        import main
        from pet_runtime import TOOL_TURN, TurnState
        pet = main.DesktopPet.__new__(main.DesktopPet)
        pet.config = {"base_url": "https://unreachable.invalid", "api_key": "", "search_model": "retired-model",
                      "web_search_timeout_secs": 4, "web_search_max_results": 3}
        event = threading.Event()
        token = TOOL_TURN.set(TurnState(cancel_event=event))
        try:
            with patch.object(main, "perform_web_search", return_value={"status": "success"}) as perform:
                result = pet._dispatch_tool_call("web_search", {"query": "public query", "refresh": True})
            perform.assert_called_once_with("public query", limit=3, timeout=4, refresh=True, cancel_event=event)
            self.assertEqual(result["status"], "success")
        finally:
            TOOL_TURN.reset(token)

    def test_full_tool_entry_returns_real_parser_output_without_api(self):
        import main
        pet = main.DesktopPet.__new__(main.DesktopPet)
        pet.config = {}
        with patch.object(main, "perform_web_search", side_effect=search.LocalWebSearch().search), \
                patch.object(search, "_fetch", return_value=BAIDU), patch.object(pet, "_record_action"):
            result = pet.execute_tool_call("web_search", {"query": "Python tkinter 官方文档"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["results"][0]["url"], "https://docs.python.org/zh-cn/3/library/tkinter.html")
        self.assertNotIn("search_model", result)


if __name__ == "__main__":
    unittest.main()
