let docs = null;
let selectedEndpointId = "";
let selectedLang = "curl";

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, payload) {
  const options = payload
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
    : {};
  const res = await fetch(path, options);
  return res.json();
}

function methodClass(method) {
  return method.toLowerCase();
}

function inlineFormat(line) {
  return escapeHtml(line).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function formatAnswer(text) {
  const parts = String(text).split(/```/);
  return parts
    .map((part, index) => {
      if (index % 2 === 1) {
        const code = part.replace(/^[a-zA-Z]+\n/, "");
        return `<pre class="answer-code">${escapeHtml(code.trim())}</pre>`;
      }

      const lines = part.trim().split(/\n+/).filter(Boolean);
      let html = "";
      let inList = false;
      lines.forEach((line) => {
        if (line.startsWith("- ")) {
          if (!inList) {
            html += "<ul>";
            inList = true;
          }
          html += `<li>${inlineFormat(line.slice(2))}</li>`;
        } else {
          if (inList) {
            html += "</ul>";
            inList = false;
          }
          html += `<p>${inlineFormat(line)}</p>`;
        }
      });
      if (inList) html += "</ul>";
      return html;
    })
    .join("");
}

function shortAuth(auth) {
  if (!auth) return "未说明";
  if (auth.includes("Bearer")) return "Bearer";
  return auth.length > 12 ? `${auth.slice(0, 12)}...` : auth;
}

function setActiveEndpoint(endpointId) {
  selectedEndpointId = endpointId;
  document.querySelectorAll(".endpoint-item").forEach((node) => {
    node.classList.toggle("active", node.dataset.endpointId === endpointId);
  });
  if ($("endpointSelect")) $("endpointSelect").value = endpointId;
}

function renderEndpoints(items) {
  const list = $("endpointList");
  list.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "endpoint-item";
    node.dataset.endpointId = item.id;
    const tags = (item.tags || [])
      .slice(0, 2)
      .map((tag) => `<span>${escapeHtml(tag)}</span>`)
      .join("");
    node.innerHTML = `
      <div class="endpoint-topline">
        <span class="endpoint-method ${methodClass(item.method)}">${escapeHtml(item.method)}</span>
        <span class="endpoint-version">${escapeHtml(item.version || "v1")}</span>
      </div>
      <div class="endpoint-path">${escapeHtml(item.path)}</div>
      <div class="endpoint-name">${escapeHtml(item.name)}</div>
      <div class="endpoint-summary">${escapeHtml(item.summary || "")}</div>
      <div class="endpoint-footer">
        <div class="tag-row">${tags}</div>
        <span class="auth-chip">${escapeHtml(shortAuth(item.auth))}</span>
      </div>
    `;
    node.addEventListener("click", () => {
      setActiveEndpoint(item.id);
      generateCode();
      renderReferences([item]);
    });
    list.appendChild(node);
  });
  setActiveEndpoint(selectedEndpointId || items[0]?.id || "");
}

function renderEndpointSelect() {
  const select = $("endpointSelect");
  select.innerHTML = "";
  docs.endpoints.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.method} ${item.path}`;
    select.appendChild(option);
  });
  selectedEndpointId = docs.endpoints[0]?.id || "";
  select.value = selectedEndpointId;
}

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  if (role === "agent") {
    node.innerHTML = `<div class="message-label">Agent</div><div class="message-body">${formatAnswer(text)}</div>`;
  } else {
    node.innerHTML = `<div class="message-label">You</div><div class="message-body"><p>${escapeHtml(text)}</p></div>`;
  }
  $("chatLog").appendChild(node);
  $("chatLog").scrollTop = $("chatLog").scrollHeight;
  return node;
}

function renderTrace(trace) {
  const list = $("traceList");
  list.innerHTML = "";
  trace.forEach((item) => {
    const node = document.createElement("li");
    node.className = "trace-item";
    node.innerHTML = `<span class="trace-title">${escapeHtml(item.title)}</span><span>${escapeHtml(item.detail)}</span>`;
    list.appendChild(node);
  });
}

function renderReferences(items) {
  const refs = $("referenceList");
  refs.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "reference";
    node.innerHTML = `
      <div class="reference-route">
        <span class="endpoint-method ${methodClass(item.method)}">${escapeHtml(item.method)}</span>
        <strong>${escapeHtml(item.path)}</strong>
      </div>
      <div class="reference-name">${escapeHtml(item.name)}</div>
      <div class="reference-note">${escapeHtml(item.summary || "")}</div>
    `;
    refs.appendChild(node);
  });
}

async function sendChat(message) {
  addMessage("user", message);
  $("chatInput").value = "";
  const pending = addMessage("agent", "处理中...");
  try {
    const data = await api("/api/chat", { message });
    pending.innerHTML = `<div class="message-label">Agent</div><div class="message-body">${formatAnswer(data.answer)}</div>`;
    renderTrace(data.trace);
    renderReferences(data.matches || []);
    if (data.matches?.[0]) {
      setActiveEndpoint(data.matches[0].id);
      generateCode();
    }
  } catch (err) {
    pending.innerHTML = `<div class="message-label">Agent</div><div class="message-body"><p>请求失败：${escapeHtml(err)}</p></div>`;
  }
}

async function searchDocs() {
  const query = $("searchInput").value;
  const data = await api("/api/search", { query });
  renderEndpoints(data.results || docs.endpoints);
}

async function generateCode() {
  if (!selectedEndpointId) return;
  const data = await api("/api/code", { endpoint_id: selectedEndpointId, language: selectedLang });
  $("codeOutput").textContent = data.code;
}

function switchTab(tab) {
  document.querySelectorAll(".tab").forEach((node) => node.classList.toggle("active", node.dataset.tab === tab));
  document.querySelectorAll(".tab-pane").forEach((node) => node.classList.remove("active"));
  $(`${tab}Tab`).classList.add("active");
}

async function runTest() {
  let body = $("bodyInput").value.trim();
  const method = $("methodSelect").value;
  if (method === "GET") body = "";
  const data = await api("/api/test", {
    method,
    url: $("urlInput").value,
    body,
    headers: { "Accept": "application/json" }
  });
  $("testOutput").textContent = JSON.stringify(data, null, 2);
}

async function init() {
  docs = await api("/api/docs");
  const health = await api("/api/health");
  $("docCount").textContent = `${health.endpoints} 个接口`;
  $("metricApis").textContent = health.endpoints;
  $("modelStatus").textContent = `${health.provider} · ${health.provider === "openai_compat" ? health.openai_model : health.ollama_model}`;
  renderEndpoints(docs.endpoints);
  renderEndpointSelect();
  renderTrace([
    { title: "输入解析", detail: "等待问题" },
    { title: "知识库召回", detail: "待触发" },
    { title: "模型/规则推理", detail: "待触发" },
    { title: "结构化输出", detail: "待触发" }
  ]);
  renderReferences([docs.endpoints[0]]);
  addMessage("agent", "你好，我可以查询接口文档、解释参数、生成调用示例，也可以对本机地址执行受限接口测试。");
  generateCode();
}

document.addEventListener("DOMContentLoaded", () => {
  init();
  $("searchInput").addEventListener("input", searchDocs);
  $("refreshBtn").addEventListener("click", init);
  $("chatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const message = $("chatInput").value.trim();
    if (message) sendChat(message);
  });
  document.querySelectorAll(".quick-prompts button").forEach((node) => {
    node.addEventListener("click", () => sendChat(node.dataset.prompt));
  });
  document.querySelectorAll(".tab").forEach((node) => {
    node.addEventListener("click", () => switchTab(node.dataset.tab));
  });
  $("runTestBtn").addEventListener("click", runTest);
  $("endpointSelect").addEventListener("change", (event) => {
    selectedEndpointId = event.target.value;
    generateCode();
  });
  document.querySelectorAll(".segment").forEach((node) => {
    node.addEventListener("click", () => {
      selectedLang = node.dataset.lang;
      document.querySelectorAll(".segment").forEach((item) => item.classList.toggle("active", item === node));
      generateCode();
    });
  });
});
