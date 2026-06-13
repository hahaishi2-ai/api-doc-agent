#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API接口文档智能查询与测试助手.

一个零第三方依赖的课程演示 Agent：
- 检索本地 API 文档知识库
- 调用 Ollama 或 OpenAI-compatible 本地模型 API 生成回答
- 模型不可用时使用规则兜底，保证现场可演示
- 提供受限的接口测试能力，默认只允许 localhost/127.0.0.1
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_FILE = BASE_DIR / "data" / "api_docs.json"
CONFIG_FILE = BASE_DIR / "config.json"


def load_docs() -> dict[str, Any]:
    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


API_DOCS = load_docs()
APP_CONFIG = load_config()


def llm_config() -> dict[str, Any]:
    return APP_CONFIG.get("llm", {})


def env_or_config(env_name: str, value: Any, default: str) -> str:
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value
    if value is None:
        return default
    return str(value)


def config_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_./:-]+|[\u4e00-\u9fff]", text.lower())


def endpoint_text(endpoint: dict[str, Any]) -> str:
    parts: list[str] = [
        endpoint.get("id", ""),
        endpoint.get("method", ""),
        endpoint.get("path", ""),
        endpoint.get("name", ""),
        endpoint.get("summary", ""),
        " ".join(endpoint.get("tags", [])),
        endpoint.get("auth", ""),
        endpoint.get("version", ""),
    ]
    for param in endpoint.get("parameters", []):
        parts.extend([param.get("name", ""), param.get("type", ""), param.get("description", "")])
    body = endpoint.get("request_body", {})
    parts.extend([body.get("description", ""), json.dumps(body.get("schema", {}), ensure_ascii=False)])
    parts.append(json.dumps(endpoint.get("responses", {}), ensure_ascii=False))
    parts.append(json.dumps(endpoint.get("examples", {}), ensure_ascii=False))
    return " ".join(parts)


def domain_boost(query: str, endpoint: dict[str, Any]) -> float:
    endpoint_id = endpoint.get("id", "")
    boost = 0.0
    if "自习室" in query and "座位" in query and "预约" not in query and endpoint_id == "study_room_seats":
        boost += 10
    if "预约" in query and endpoint_id == "reservation_create":
        boost += 10
    if "失物" in query and "匹配" in query and endpoint_id == "lost_found_match":
        boost += 10
    if "快递" in query and endpoint_id == "express_packages":
        boost += 10
    if "食堂" in query and endpoint_id == "canteen_menu":
        boost += 10
    if "反馈" in query and endpoint_id == "feedback_create":
        boost += 10
    if "列表" in query and "失物" in query and endpoint_id == "lost_found_list":
        boost += 8
    return boost


def search_endpoints(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return API_DOCS["endpoints"][:limit]

    query_tokens = tokenize(q)
    scored: list[tuple[float, dict[str, Any]]] = []
    for endpoint in API_DOCS["endpoints"]:
        text = endpoint_text(endpoint).lower()
        score = domain_boost(q, endpoint)
        for token in query_tokens:
            if not token:
                continue
            score += text.count(token)
            if token in endpoint.get("path", "").lower():
                score += 3
            if token in endpoint.get("name", "").lower():
                score += 2
            if token == endpoint.get("method", "").lower():
                score += 2
        if q in text:
            score += 5
        if score > 0:
            scored.append((score, endpoint))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def classify_intent(message: str) -> str:
    text = message.lower()
    code_words = ["代码", "示例", "curl", "python", "javascript", "js", "调用样例"]
    test_words = ["测试", "调试", "请求", "发送", "调用接口", "状态码"]
    schema_words = ["参数", "字段", "返回", "响应", "body", "schema"]
    change_words = ["版本", "变更", "历史", "废弃", "兼容"]
    if any(word in text for word in code_words):
        return "code_sample"
    if any(word in text for word in test_words):
        return "api_test"
    if any(word in text for word in schema_words):
        return "schema_explain"
    if any(word in text for word in change_words):
        return "change_history"
    return "doc_query"


def endpoint_to_context(endpoint: dict[str, Any]) -> str:
    return json.dumps(
        {
            "id": endpoint.get("id"),
            "method": endpoint.get("method"),
            "path": endpoint.get("path"),
            "name": endpoint.get("name"),
            "summary": endpoint.get("summary"),
            "tags": endpoint.get("tags"),
            "auth": endpoint.get("auth"),
            "parameters": endpoint.get("parameters", []),
            "request_body": endpoint.get("request_body", {}),
            "responses": endpoint.get("responses", {}),
            "examples": endpoint.get("examples", {}),
            "changes": endpoint.get("changes", []),
        },
        ensure_ascii=False,
        indent=2,
    )


def build_messages(user_message: str, intent: str, matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    context = "\n\n".join(endpoint_to_context(item) for item in matches)
    system = (
        "你是“API接口文档智能查询与测试助手”，服务对象是后端开发、测试和产品同学。"
        "你只能依据给定的 API 文档上下文回答，不要编造不存在的接口。"
        "回答时优先给出：结论、接口与路径、关键参数、请求/响应说明、测试建议、风险提示。"
        "如果上下文不足，明确说明需要补充哪些接口文档。"
    )
    user = (
        f"用户意图: {intent}\n"
        f"用户问题: {user_message}\n\n"
        f"召回到的 API 文档上下文:\n{context}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_local_model(messages: list[dict[str, str]]) -> tuple[str | None, str]:
    config = llm_config()
    if config_bool(os.getenv("AGENT_DISABLE_LLM"), config_bool(config.get("disable_llm"), False)):
        return None, "disabled"

    provider = env_or_config("AGENT_PROVIDER", config.get("provider"), "ollama").strip().lower()
    timeout = float(env_or_config("AGENT_LLM_TIMEOUT", config.get("timeout_seconds"), "20"))

    if provider == "openai_compat":
        openai_config = config.get("openai_compat", {})
        base_url = env_or_config("OPENAI_BASE_URL", openai_config.get("base_url"), "http://127.0.0.1:1234/v1").rstrip("/")
        model = env_or_config("OPENAI_MODEL", openai_config.get("model"), "local-model")
        api_key = env_or_config("OPENAI_API_KEY", openai_config.get("api_key"), "lm-studio")
        payload = {"model": model, "messages": messages, "temperature": 0.2}
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"], f"openai_compat:{model}"
        except Exception as exc:  # noqa: BLE001
            return None, f"openai_compat_error:{exc}"

    ollama_config = config.get("ollama", {})
    base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or str(ollama_config.get("base_url", "http://127.0.0.1:11434"))
    base_url = base_url.rstrip("/")
    model = env_or_config("OLLAMA_MODEL", ollama_config.get("model"), "qwen2.5:7b-instruct")
    payload = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.2}}
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("message", {}).get("content") or data.get("response"), f"ollama:{model}"
    except Exception as exc:  # noqa: BLE001
        return None, f"ollama_error:{exc}"


def fallback_answer(message: str, intent: str, matches: list[dict[str, Any]]) -> str:
    if not matches:
        return (
            "没有在当前知识库中找到匹配接口。建议补充接口名称、路径、HTTP 方法或业务关键词，"
            "例如“查询自习室座位 GET 参数”或“失物招领匹配接口怎么测试”。"
        )

    top = matches[0]
    params = top.get("parameters", [])
    param_lines = []
    for param in params:
        required = "必填" if param.get("required") else "选填"
        param_lines.append(f"- {param['name']}（{param['type']}，{required}）：{param['description']}")
    body_schema = top.get("request_body", {}).get("schema", {})
    if body_schema:
        for field, desc in body_schema.items():
            param_lines.append(f"- {field}：{desc}")
    if not param_lines:
        param_lines.append("- 该接口没有 URL 查询参数，也没有配置请求体字段。")

    sample = top.get("examples", {}).get("curl", "")
    changes = top.get("changes", [])
    change_text = "；".join(changes[:2]) if changes else "暂无版本变更记录。"

    if intent == "code_sample":
        sample_block = sample or "当前接口未配置 curl 示例，可在页面右侧选择接口生成模板代码。"
        return (
            f"推荐使用 `{top['method']} {top['path']}`（{top['name']}）。\n\n"
            f"```bash\n{sample_block}\n```\n\n"
            "调用前请确认鉴权方式、请求域名和测试环境数据是否可用。"
        )

    if intent == "change_history":
        return (
            f"`{top['method']} {top['path']}` 的版本信息为 `{top.get('version', '未标注')}`。\n\n"
            f"主要变更：{change_text}\n\n"
            "如果用于上线前检查，建议补充请求样例和响应字段变更对比。"
        )

    return (
        f"最匹配的接口是 `{top['method']} {top['path']}`：{top['summary']}\n\n"
        f"关键参数：\n" + "\n".join(param_lines) + "\n\n"
        f"鉴权方式：{top.get('auth', '未说明')}。\n"
        "测试建议：先用正常参数验证成功响应，再分别测试缺少必填参数、越界分页、无权限 Token 和空结果场景。"
    )


def make_trace(message: str, intent: str, matches: list[dict[str, Any]], model_status: str) -> list[dict[str, str]]:
    return [
        {"id": "input", "title": "输入解析", "status": "done", "detail": message[:80]},
        {"id": "intent", "title": "意图识别", "status": "done", "detail": intent},
        {
            "id": "retrieve",
            "title": "知识库召回",
            "status": "done",
            "detail": f"命中 {len(matches)} 个接口文档",
        },
        {"id": "reason", "title": "模型/规则推理", "status": "done", "detail": model_status},
        {"id": "output", "title": "结构化输出", "status": "done", "detail": "已生成答复与引用接口"},
    ]


def generate_code(endpoint: dict[str, Any], language: str) -> str:
    base_url = "http://localhost:8765/mock-api"
    url = f"{base_url}{endpoint['path']}"
    method = endpoint["method"].upper()
    body = endpoint.get("examples", {}).get("json_body", {})
    query = endpoint.get("examples", {}).get("query", {})
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    if language == "python":
        return (
            "import requests\n\n"
            f"url = {url!r}\n"
            "headers = {'Authorization': 'Bearer <token>'}\n"
            f"payload = {json.dumps(body, ensure_ascii=False, indent=2)!r}\n\n"
            f"response = requests.request({method!r}, url, headers=headers, json=payload if payload else None)\n"
            "print(response.status_code)\n"
            "print(response.json())\n"
        )
    if language == "javascript":
        return (
            f"const url = {json.dumps(url, ensure_ascii=False)};\n"
            "const response = await fetch(url, {\n"
            f"  method: {json.dumps(method)},\n"
            "  headers: {\n"
            "    'Authorization': 'Bearer <token>',\n"
            "    'Content-Type': 'application/json'\n"
            "  },\n"
            f"  body: {json.dumps(json.dumps(body, ensure_ascii=False), ensure_ascii=False)}\n"
            "});\n"
            "console.log(response.status, await response.json());\n"
        )
    return endpoint.get("examples", {}).get(
        "curl",
        f"curl -X {method} {json.dumps(url)} -H 'Authorization: Bearer <token>'",
    )


def allowed_test_url(url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(url)
    config_hosts = APP_CONFIG.get("security", {}).get("allowed_test_hosts", ["localhost", "127.0.0.1", "::1"])
    env_hosts = os.getenv("AGENT_ALLOWED_HOSTS")
    host_source = env_hosts.split(",") if env_hosts else config_hosts
    allowed_hosts = {str(item).strip().lower() for item in host_source if str(item).strip()}
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return False, "只允许 http/https 请求"
    if host not in allowed_hosts:
        return False, f"默认只允许测试本机地址，当前主机 `{host}` 未在 AGENT_ALLOWED_HOSTS 中"
    return True, ""


def run_http_test(payload: dict[str, Any]) -> dict[str, Any]:
    method = payload.get("method", "GET").upper()
    url = payload.get("url", "")
    body = payload.get("body", "")
    headers = payload.get("headers", {})
    ok, reason = allowed_test_url(url)
    if not ok:
        return {"ok": False, "error": reason}
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return {"ok": False, "error": "不支持的 HTTP 方法"}

    data = None
    if method in {"POST", "PUT", "PATCH"} and body:
        data = body.encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read(4000).decode("utf-8", errors="replace")
            response_headers = dict(resp.headers.items())
            return {
                "ok": True,
                "status": resp.status,
                "elapsed_ms": round((time.time() - started) * 1000),
                "headers": {key: response_headers[key] for key in list(response_headers)[:8]},
                "body": text,
            }
    except urllib.error.HTTPError as exc:
        text = exc.read(4000).decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "elapsed_ms": round((time.time() - started) * 1000), "body": text}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def mock_api_response(method: str, path: str, query: dict[str, list[str]], payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    api_path = path.replace("/mock-api", "", 1)
    endpoint = next(
        (item for item in API_DOCS["endpoints"] if item["method"] == method and item["path"] == api_path),
        None,
    )
    if not endpoint:
        return 404, {"error": "mock endpoint not found", "path": api_path}

    if endpoint["id"] == "lost_found_list":
        return 200, {
            "items": [
                {"id": "LF-1024", "title": "蓝色卡套校园卡", "status": "found", "location": "图书馆二楼", "match_score": 0.91},
                {"id": "LF-1029", "title": "黑色笔记本", "status": "lost", "location": "教学楼 A 区", "match_score": 0.74}
            ],
            "total": 2,
            "page": int(query.get("page", ["1"])[0]),
        }
    if endpoint["id"] == "lost_found_match":
        if not payload.get("description") or payload.get("status") not in {"lost", "found"}:
            return 422, {"error": "description 与 status 为必填项"}
        return 200, {
            "matches": [
                {"item_id": "LF-1024", "title": "蓝色卡套校园卡", "similarity": 0.91, "reason": "颜色、地点和物品类别高度一致"}
            ],
            "confidence": 0.91,
        }
    if endpoint["id"] == "canteen_menu":
        return 200, {
            "canteen_id": query.get("canteen_id", ["syu-a"])[0],
            "meal": query.get("meal", ["lunch"])[0],
            "dishes": [
                {"name": "番茄牛腩饭", "price": 16, "calorie": 690, "tags": ["高蛋白"]},
                {"name": "清炒时蔬", "price": 6, "calorie": 120, "tags": ["低脂"]}
            ],
            "calorie_total": 810,
        }
    if endpoint["id"] == "study_room_seats":
        return 200, {
            "building": query.get("building", ["library"])[0],
            "room": query.get("room", ["203"])[0],
            "occupied_rate": 0.68,
            "seats": [
                {"seat_id": "LIB-203-A08", "status": "available"},
                {"seat_id": "LIB-203-A09", "status": "occupied"},
                {"seat_id": "LIB-203-A10", "status": "reserved"}
            ],
        }
    if endpoint["id"] == "reservation_create":
        required = {"seat_id", "start_time", "end_time"}
        if not required.issubset(payload):
            return 422, {"error": "seat_id、start_time、end_time 为必填项"}
        return 201, {"reservation_id": "RSV-20260610-008", "checkin_qr": "mock://qr/RSV-20260610-008"}
    if endpoint["id"] == "express_packages":
        return 200, {
            "packages": [
                {"tracking_no": "YT10240001", "pickup_code": "A-314", "station": "东门驿站", "status": "arrived"}
            ],
            "station_load": 0.57,
        }
    if endpoint["id"] == "feedback_create":
        if len(str(payload.get("content", ""))) < 10:
            return 422, {"error": "反馈正文至少 10 个字符"}
        return 201, {"ticket_id": "FB-20260609-0017", "eta_hours": 24}

    return 200, {"ok": True, "endpoint": endpoint["id"]}


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "APIDocAgent/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, data: Any, status: int = 200) -> None:
        raw = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_file(STATIC_DIR / "index.html")
            return
        if parsed.path.startswith("/static/"):
            safe = parsed.path.replace("/static/", "", 1)
            self.send_file(STATIC_DIR / safe)
            return
        if parsed.path == "/api/docs":
            self.send_json(API_DOCS)
            return
        if parsed.path == "/api/health":
            config = llm_config()
            openai_config = config.get("openai_compat", {})
            ollama_config = config.get("ollama", {})
            self.send_json(
                {
                    "ok": True,
                    "provider": env_or_config("AGENT_PROVIDER", config.get("provider"), "ollama"),
                    "ollama_model": env_or_config("OLLAMA_MODEL", ollama_config.get("model"), "qwen2.5:7b-instruct"),
                    "openai_model": env_or_config("OPENAI_MODEL", openai_config.get("model"), "local-model"),
                    "openai_base_url": env_or_config("OPENAI_BASE_URL", openai_config.get("base_url"), "http://127.0.0.1:1234/v1"),
                    "config_file": str(CONFIG_FILE),
                    "endpoints": len(API_DOCS["endpoints"]),
                }
            )
            return
        if parsed.path.startswith("/mock-api/"):
            status, data = mock_api_response("GET", parsed.path, urllib.parse.parse_qs(parsed.query), {})
            self.send_json(data, status=status)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "JSON 格式错误"}, status=400)
            return

        if parsed.path == "/api/search":
            query = payload.get("query", "")
            self.send_json({"ok": True, "results": search_endpoints(query)})
            return

        if parsed.path == "/api/chat":
            message = payload.get("message", "").strip()
            if not message:
                self.send_json({"ok": False, "error": "请输入问题"}, status=400)
                return
            intent = classify_intent(message)
            matches = search_endpoints(message, limit=4)
            messages = build_messages(message, intent, matches)
            answer, model_status = call_local_model(messages)
            if not answer:
                answer = fallback_answer(message, intent, matches)
            self.send_json(
                {
                    "ok": True,
                    "answer": answer,
                    "intent": intent,
                    "matches": matches,
                    "trace": make_trace(message, intent, matches, model_status),
                }
            )
            return

        if parsed.path == "/api/code":
            endpoint_id = payload.get("endpoint_id", "")
            language = payload.get("language", "curl")
            endpoint = next((item for item in API_DOCS["endpoints"] if item["id"] == endpoint_id), API_DOCS["endpoints"][0])
            self.send_json({"ok": True, "code": generate_code(endpoint, language), "endpoint": endpoint})
            return

        if parsed.path == "/api/test":
            self.send_json(run_http_test(payload))
            return

        if parsed.path.startswith("/mock-api/"):
            status, data = mock_api_response("POST", parsed.path, urllib.parse.parse_qs(parsed.query), payload)
            self.send_json(data, status=status)
            return

        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser(description="API接口文档智能查询与测试助手")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    print(f"API Doc Agent running at http://{args.host}:{args.port}")
    print("Config file:", CONFIG_FILE)
    print("Local model provider:", env_or_config("AGENT_PROVIDER", llm_config().get("provider"), "ollama"))
    server.serve_forever()


if __name__ == "__main__":
    main()
