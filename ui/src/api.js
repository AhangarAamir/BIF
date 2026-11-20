export const AGENT_ID = "query-agent";
export const DB_ID = "bif-sessions";

const ADMIN_KEY = "bif-admin-token";
export const getAdminToken = () => localStorage.getItem(ADMIN_KEY) || "";
export const setAdminToken = (t) => (t ? localStorage.setItem(ADMIN_KEY, t) : localStorage.removeItem(ADMIN_KEY));

async function readError(res) {
  try {
    const body = await res.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

async function request(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getAdminToken();
  if (token) headers["X-Admin-Token"] = token;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  if (!res.ok) throw new Error(await readError(res));
  return res.status === 204 ? null : res.json();
}

export const api = {
  status: () => request("/api/status"),
  settings: () => request("/api/settings"),
  saveProfile: (p) => request("/api/settings/profiles", { method: "POST", body: p }),
  deleteProfile: (id) => request(`/api/settings/profiles/${id}`, { method: "DELETE" }),
  setActive: (id) => request("/api/settings/active", { method: "POST", body: { profile_id: id } }),
  setIngestProfile: (id) => request("/api/settings/ingest-profile", { method: "POST", body: { profile_id: id } }),
  saveEmbedding: (e) => request("/api/settings/embedding", { method: "PUT", body: e }),
  listModels: (q) => request("/api/models/list", { method: "POST", body: q }),
  testModel: (p) => request("/api/models/test", { method: "POST", body: p }),
  testEmbedding: (e) => request("/api/models/test-embedding", { method: "POST", body: e }),
  documents: () => request("/api/documents"),
  outline: (id) => request(`/api/documents/${id}/outline`),
  deleteDocument: (id, file) => request(`/api/documents/${id}?delete_file=${file ? "true" : "false"}`, { method: "DELETE" }),
  // items: [{ file, path }]; path is relative to the picked folder ("JOA/New JOA/x.pdf").
  // The server decides the final place (see bif/ingest/placement.py).
  upload: (items, { folder = "", keepTop = true, autoAnchor = true } = {}, ingest = false) => {
    const form = new FormData();
    for (const { file, path } of items) {
      form.append("files", file, file.name);
      form.append("paths", path || file.name);
    }
    form.append("folder", folder);
    form.append("keep_top", keepTop ? "true" : "false");
    form.append("auto_anchor", autoAnchor ? "true" : "false");
    form.append("ingest", ingest ? "true" : "false");
    return request("/api/documents/upload", { method: "POST", form });
  },
  folders: () => request("/api/folders"),
  uploadPreview: (body) => request("/api/upload/preview", { method: "POST", body }),
  ingest: (body) => request("/api/ingest", { method: "POST", body }),
  reembed: () => request("/api/reembed", { method: "POST" }),
  jobs: () => request("/api/jobs"),
  chunks: (ids) => request(`/api/chunks?ids=${ids.join(",")}`),
  feedback: (body) => request("/api/feedback", { method: "POST", body }),
};

export async function listSessions(userId) {
  const params = new URLSearchParams({
    type: "agent", component_id: AGENT_ID, user_id: userId, db_id: DB_ID,
    sort_by: "updated_at", sort_order: "desc", limit: "60",
  });
  return request(`/sessions?${params}`);
}

export async function getSessionRuns(sessionId, userId) {
  const params = new URLSearchParams({ type: "agent", user_id: userId, db_id: DB_ID });
  return request(`/sessions/${encodeURIComponent(sessionId)}/runs?${params}`);
}

export async function deleteSession(sessionId) {
  const params = new URLSearchParams({ type: "agent", db_id: DB_ID });
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}?${params}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(await readError(res));
}

export async function parseSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      if (!part.trim() || part.startsWith(":")) continue;
      let event = "message";
      const data = [];
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (!data.length) continue;
      let payload;
      try {
        payload = JSON.parse(data.join("\n"));
      } catch {
        payload = { content: data.join("\n") };
      }
      onEvent(payload.event || event, payload);
    }
  }
}

export async function runQuery({ message, sessionId, userId, signal, onEvent }) {
  const body = new FormData();
  body.append("message", message);
  body.append("stream", "true");
  body.append("session_id", sessionId);
  body.append("user_id", userId);
  const res = await fetch(`/agents/${AGENT_ID}/runs`, { method: "POST", body, signal });
  if (!res.ok) throw new Error(await readError(res));
  await parseSse(res, onEvent);
}

export function runsToMessages(runs) {
  const out = [];
  for (const run of runs || []) {
    if (run.run_input) out.push({ id: `${run.run_id}-u`, role: "user", content: run.run_input });
    out.push({
      id: `${run.run_id}-a`,
      role: "assistant",
      runId: run.run_id,
      content: typeof run.content === "string" ? run.content : run.content ? JSON.stringify(run.content) : "",
      metrics: run.metrics,
      reasoning: run.reasoning_content || "",
      model: run.metrics?.details?.model?.[0]?.id,
      error: run.status === "ERROR" ? "This run failed." : "",
      tools: (run.tools || []).map((t) => ({
        id: t.tool_call_id,
        name: t.tool_name,
        args: t.tool_args || {},
        result: typeof t.result === "string" ? t.result : "",
        status: t.tool_call_error ? "error" : "done",
      })),
    });
  }
  return out;
}

export function getUserId() {
  const key = "bif-user-id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}
