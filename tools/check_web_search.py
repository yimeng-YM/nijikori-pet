"""Real-network smoke test; only public queries, never the chat API or its key."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pet_search import perform_web_search  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    queries = sys.argv[1:] or ["Python tkinter 官方文档", "Python tkinter documentation", "中国天气网 北京 天气"]
    failures = 0
    for query in queries:
        result = perform_web_search(query, refresh=True)
        cached = perform_web_search(query) if result["status"] == "success" else {}
        print(json.dumps({"query": query, "status": result["status"],
                          "engines": result.get("engines"), "elapsed_ms": result.get("elapsed_ms"),
                          "results_count": result.get("results_count"), "cached_repeat": cached.get("cached"),
                          "results": [{"title": r["title"], "url": r["url"]} for r in result.get("results", [])],
                          "message": result.get("message")}, ensure_ascii=False, indent=2), flush=True)
        failures += result["status"] != "success" or cached.get("cached") is not True
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
