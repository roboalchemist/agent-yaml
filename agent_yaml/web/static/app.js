// agent-yaml interface runner: workflow catalog + WebGL stage graph + live trace.

import { createWebGLRenderer } from "./webgl.js";

const NODE_W = 168;
const NODE_H = 96;

const state = {
  catalog: [],
  catalogQuery: "",
  workflows: [],
  workflow: null,
  selectedNodeId: null,
  renderer: null,
  fallback: false,
  activeRunId: null,
  run: null,
  events: [],
  nodeStates: new Map(),
  nodeStarted: new Map(),
  filter: "all",
  follow: true,
  source: null,
  autoFocus: false,
};

const $ = (id) => document.getElementById(id);

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
};

// ---------------------------------------------------------------- bootstrap

async function init() {
  setupRenderer();

  $("catalog-search").addEventListener("input", (event) => {
    state.catalogQuery = event.target.value.trim().toLowerCase();
    renderCatalog();
  });
  $("refresh-catalog").addEventListener("click", loadCatalog);
  $("refresh-workflows").addEventListener("click", loadWorkflows);
  $("refresh-runs").addEventListener("click", loadRuns);
  $("run-button").addEventListener("click", () => startRun(false));
  $("dry-run-button").addEventListener("click", () => startRun(true));
  $("fit-button").addEventListener("click", () => state.renderer?.fit());
  $("zoom-in").addEventListener("click", () => state.renderer?.zoomBy(1.2));
  $("zoom-out").addEventListener("click", () => state.renderer?.zoomBy(1 / 1.2));
  $("follow-toggle").addEventListener("click", toggleFollow);
  $("focus-toggle").addEventListener("click", toggleAutoFocus);
  $("trace-clear").addEventListener("click", clearTrace);
  document.querySelectorAll("[data-filter]").forEach((chip) => {
    chip.addEventListener("click", () => setFilter(chip.dataset.filter));
  });
  window.addEventListener("resize", () => state.renderer?.resize());

  await Promise.all([loadCatalog(), loadWorkflows(), loadRuns()]);
  window.__ay.ready = true;
}

function setupRenderer() {
  const canvas = $("gl-canvas");
  const labelLayer = $("gl-labels");
  const renderer = createWebGLRenderer({
    canvas,
    labelLayer,
    onSelect: (id) => selectNode(id, true),
    onHover: (id) => {
      const el = $("hover-hint");
      const node = id ? state.workflow?.graph.nodes.find((n) => n.id === id) : null;
      el.textContent = node ? `${node.type} · ${node.label}` : "";
    },
  });

  if (renderer) {
    state.renderer = renderer;
    const observer = new ResizeObserver(() => renderer.resize());
    observer.observe(canvas.parentElement);
    $("fallback-notice").hidden = true;
  } else {
    state.fallback = true;
    $("fallback-notice").hidden = false;
    $("gl-canvas").hidden = true;
    $("gl-labels").hidden = true;
    $("dom-graph").hidden = false;
  }
}

// ------------------------------------------------------------------- catalog

async function loadCatalog() {
  state.catalog = await api("/api/workflows/discover");
  renderCatalog();
}

function renderCatalog() {
  const list = $("catalog-list");
  list.innerHTML = "";
  const query = state.catalogQuery;
  const matches = state.catalog.filter(
    (entry) =>
      !query ||
      entry.name.toLowerCase().includes(query) ||
      entry.description.toLowerCase().includes(query) ||
      entry.directory.includes(query),
  );

  const groups = new Map();
  for (const entry of matches) {
    if (!groups.has(entry.directory)) groups.set(entry.directory, []);
    groups.get(entry.directory).push(entry);
  }
  $("catalog-count").textContent = `${matches.length}/${state.catalog.length}`;

  for (const [directory, entries] of groups) {
    const heading = document.createElement("div");
    heading.className = "catalog-group";
    heading.textContent = `${directory} (${entries.length})`;
    list.appendChild(heading);

    for (const entry of entries) {
      const item = document.createElement("button");
      item.className = "catalog-item";
      item.type = "button";
      item.innerHTML = `
        <span class="catalog-name">${escapeHtml(entry.name)}</span>
        <span class="catalog-meta">
          <span class="pill pill-agent">${escapeHtml(entry.cli_agent)}</span>
          <span class="pill">${entry.stage_count} stage${entry.stage_count === 1 ? "" : "s"}</span>
        </span>
        <span class="catalog-desc">${escapeHtml(entry.description || entry.workflow_directory)}</span>
      `;
      item.addEventListener("click", () => openCatalogEntry(entry));
      list.appendChild(item);
    }
  }
}

async function openCatalogEntry(entry) {
  try {
    const workflow = await api("/api/workflows/import", {
      method: "POST",
      body: JSON.stringify({ path: entry.relative_path }),
    });
    await loadWorkflows();
    await selectWorkflow(workflow.id);
  } catch (error) {
    console.error(error);
    notify(error.message, "error");
  }
}

// ----------------------------------------------------------------- workflows

async function loadWorkflows() {
  const all = await api("/api/workflows");
  const byPath = new Map();
  for (const workflow of all) {
    const existing = byPath.get(workflow.path);
    if (!existing || workflow.id > existing.id) byPath.set(workflow.path, workflow);
  }
  state.workflows = [...byPath.values()].sort((a, b) => b.id - a.id);
  const list = $("workflow-list");
  list.innerHTML = "";
  for (const workflow of state.workflows) {
    const item = document.createElement("button");
    item.className = "list-item";
    item.type = "button";
    item.classList.toggle("active", state.workflow?.id === workflow.id);
    item.innerHTML = `<strong>${escapeHtml(workflow.name)}</strong><span>${escapeHtml(workflow.path)}</span>`;
    item.addEventListener("click", () => selectWorkflow(workflow.id));
    list.appendChild(item);
  }
}

async function selectWorkflow(id) {
  state.workflow = await api(`/api/workflows/${id}`);
  state.selectedNodeId = null;
  state.nodeStates.clear();
  state.nodeStarted.clear();

  $("workflow-title").textContent = state.workflow.name;
  const stages = state.workflow.graph.nodes.filter((n) => n.type === "task" || n.type === "loop").length;
  $("workflow-subtitle").textContent = `${stages} stage${stages === 1 ? "" : "s"} · ${state.workflow.graph.edges.length} transitions`;
  $("run-button").disabled = false;
  $("dry-run-button").disabled = false;
  $("empty-canvas").hidden = true;

  if (state.renderer) {
    state.renderer.setGraph(state.workflow.graph);
  } else {
    renderGraphDom();
  }
  renderInspector();
}

// ---------------------------------------------------------------------- runs

async function loadRuns() {
  const runs = await api("/api/runs?limit=10");
  const list = $("run-list");
  list.innerHTML = "";
  for (const run of runs) {
    const item = document.createElement("button");
    item.className = "list-item";
    item.type = "button";
    item.classList.toggle("active", state.activeRunId === run.id);
    item.innerHTML = `
      <strong>run #${run.id} <span class="status-dot status-${escapeHtml(run.status)}"></span></strong>
      <span>${escapeHtml(run.trigger || "manual")}${run.dry_run ? " · dry" : ""} · ${escapeHtml(run.status)}</span>
    `;
    item.addEventListener("click", () => openRun(run.id));
    list.appendChild(item);
  }
  if (!runs.length) {
    $("run-subtitle").textContent = "No runs yet — press Run.";
  }
}

async function openRun(runId) {
  const [snapshot, events] = await Promise.all([
    api(`/api/runs/${runId}/state`),
    api(`/api/runs/${runId}/events`),
  ]);
  state.activeRunId = runId;
  state.run = snapshot.run;
  state.events = [];
  state.nodeStates.clear();
  state.nodeStarted.clear();

  $("run-subtitle").textContent = `run #${runId} · ${snapshot.run.status}`;
  for (const node of snapshot.nodes) {
    state.nodeStates.set(node.node_id, {
      status: node.status,
      attempts: node.attempts,
      started_at: node.started_at,
      finished_at: node.finished_at,
      message: node.last_message,
    });
    applyNodeStatus(node.node_id, node.status, { payload: node.payload });
  }
  for (const event of events) {
    state.events.push(event);
    trackStart(event);
  }
  renderTrace();
  await loadRuns();

  if (snapshot.run.status === "running") connectStream(runId);
  else if (state.source) {
    state.source.close();
    state.source = null;
  }
}

// --------------------------------------------------------------------- runs

async function startRun(dryRun) {
  if (!state.workflow) return;
  const run = await api(`/api/workflows/${state.workflow.id}/runs`, {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun, variables: {} }),
  });
  state.activeRunId = run.id;
  state.run = run;
  state.events = [];
  state.nodeStates.clear();
  state.nodeStarted.clear();

  if (state.renderer && state.workflow) {
    state.renderer.setGraph(state.workflow.graph);
  }
  $("run-subtitle").textContent = `run #${run.id} ${dryRun ? "(dry run)" : ""}`;
  $("trace-empty").hidden = state.events.length > 0;
  renderTrace();
  connectStream(run.id);
  await loadRuns();
}

function connectStream(runId) {
  if (state.source) state.source.close();
  state.source = new EventSource(`/api/runs/${runId}/stream`);
  state.source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    state.events.push(event);
    handleEvent(event);
    if (event.type === "run_finished") {
      state.source.close();
      state.source = null;
      loadRuns();
    }
  };
  state.source.onerror = () => {
    // EventSource retries on its own; surface it once.
    notify("stream disconnected — retrying", "warn");
  };
}

function handleEvent(event) {
  trackStart(event);
  applyNodeStatus(event.node_id, event.status, event);
  renderTrace();
}

function trackStart(event) {
  if (!event.node_id) return;
  if (event.type.endsWith("_started") || event.type === "task_retrying") {
    if (!state.nodeStarted.has(event.node_id)) {
      state.nodeStarted.set(event.node_id, event.ts);
    }
  }
  if (["success", "failed", "skipped", "cancelled"].includes(event.status)) {
    state.nodeStates.set(event.node_id, {
      ...(state.nodeStates.get(event.node_id) || {}),
      status: event.status,
      finished_at: event.ts,
      message: event.message,
    });
  }
}

function applyNodeStatus(nodeId, status, meta = {}) {
  if (!nodeId || !status) return;
  const node = state.workflow?.graph.nodes.find((candidate) => candidate.id === nodeId);
  if (node) node.status = status;

  if (state.renderer) {
    state.renderer.setNodeState(nodeId, status, meta);
    if (state.autoFocus && status === "running") {
      state.renderer.focusNode(nodeId);
    }
  } else {
    renderGraphDom();
  }
  renderInspector();
}

// -------------------------------------------------------------------- trace

function eventKind(type) {
  if (type.startsWith("workflow") || type === "run_finished") return "workflow";
  if (type.startsWith("loop")) return "loop";
  if (type.startsWith("validator")) return "validator";
  if (type.startsWith("task")) return "task";
  return "other";
}

function setFilter(filter) {
  state.filter = filter;
  document.querySelectorAll("[data-filter]").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.filter === filter);
  });
  renderTrace();
}

function toggleAutoFocus() {
  state.autoFocus = !state.autoFocus;
  $("focus-toggle").classList.toggle("active", state.autoFocus);
  $("focus-toggle").textContent = state.autoFocus ? "Follow stage: on" : "Follow stage: off";
}

function toggleFollow() {
  state.follow = !state.follow;
  $("follow-toggle").classList.toggle("active", state.follow);
  $("follow-toggle").textContent = state.follow ? "Follow: on" : "Follow: off";
  if (state.follow) scrollTraceToEnd();
}

function clearTrace() {
  state.events = [];
  renderTrace();
}

function durationMs(nodeId) {
  const started = state.nodeStarted.get(nodeId);
  const finished = state.nodeStates.get(nodeId)?.finished_at;
  if (!started || !finished) return null;
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  return Number.isFinite(ms) ? Math.max(0, ms) : null;
}

function renderTrace() {
  const body = $("trace-body");
  const rows = state.events.filter(
    (event) => state.filter === "all" || eventKind(event.type) === state.filter,
  );
  body.innerHTML = "";
  $("trace-empty").hidden = rows.length > 0;
  $("trace-count").textContent = `${rows.length}/${state.events.length}`;

  const starts = new Map();
  const visible = rows.slice(-400);
  for (const event of visible) {
    if (event.type.endsWith("_started") && !starts.has(event.node_id)) {
      starts.set(event.node_id, event.ts);
    }
    const row = document.createElement("button");
    row.type = "button";
    row.className = `trace-row kind-${eventKind(event.type)} status-${event.status || "none"}`;
    row.addEventListener("click", () => {
      if (!event.node_id) return;
      selectNode(event.node_id);
      state.renderer?.focusNode(event.node_id);
    });

    const payload = event.payload || {};
    const duration =
      starts.has(event.node_id) && ["success", "failed", "skipped"].includes(event.status)
        ? Math.max(0, new Date(event.ts).getTime() - new Date(starts.get(event.node_id)).getTime())
        : null;
    const item =
      payload.item_id !== undefined
        ? ` · item ${payload.index + 1}/${payload.total} (${payload.item_id})`
        : "";
    const attempt = payload.attempt && payload.attempt > 1 ? ` · attempt ${payload.attempt}` : "";

    row.innerHTML = `
      <span class="trace-time">${formatTime(event.ts)}</span>
      <span class="trace-type">${escapeHtml(event.type)}</span>
      <span class="trace-node">${escapeHtml(event.node_id || "run")}${escapeHtml(item)}${escapeHtml(attempt)}</span>
      <span class="trace-status status-${escapeHtml(event.status || "none")}">${escapeHtml(event.status || "")}</span>
      <span class="trace-duration">${duration === null ? "" : `${duration} ms`}</span>
    `;
    if (event.message) row.title = event.message;
    body.appendChild(row);
  }
  if (state.follow) scrollTraceToEnd();
}

function scrollTraceToEnd() {
  const panel = $("trace-body-parent");
  panel.scrollTop = panel.scrollHeight;
}

// ---------------------------------------------------------------- inspector

function selectNode(nodeId, fromRenderer = false) {
  state.selectedNodeId = nodeId;
  // renderer.select() calls back into onSelect; avoid the loop when it originates there.
  if (!fromRenderer) state.renderer?.select(nodeId);
  renderInspector();
}

function renderInspector() {
  const box = $("node-inspector");
  const node = state.selectedNodeId
    ? state.workflow?.graph.nodes.find((candidate) => candidate.id === state.selectedNodeId)
    : null;
  if (!node) {
    box.classList.add("muted");
    box.innerHTML = "Select a stage on the canvas (or a trace row) to inspect it.";
    return;
  }
  box.classList.remove("muted");
  const live = state.nodeStates.get(node.id) || {};
  const duration = durationMs(node.id);
  box.innerHTML = `
    <div class="inspector-title">
      <strong>${escapeHtml(node.label)}</strong>
      <span class="pill">${escapeHtml(node.type)}</span>
    </div>
    <div class="inspector-state">
      <span class="status-dot status-${escapeHtml(node.status || "idle")}"></span>
      ${escapeHtml(node.status || "idle")}
      ${live.attempts ? `· ${live.attempts} attempt(s)` : ""}
      ${duration === null ? "" : `· ${duration} ms`}
    </div>
    ${live.message ? `<p class="inspector-message">${escapeHtml(live.message)}</p>` : ""}
    <pre>${escapeHtml(JSON.stringify(node.data ?? {}, null, 2))}</pre>
  `;
}

// ------------------------------------------------------------------ fallback

function renderGraphDom() {
  const host = $("dom-graph");
  host.innerHTML = "";
  const graph = state.workflow?.graph;
  if (!graph) return;

  const maxX = Math.max(...graph.nodes.map((n) => n.position.x + NODE_W + 80), 640);
  const maxY = Math.max(...graph.nodes.map((n) => n.position.y + NODE_H + 80), 480);
  host.style.width = `${maxX}px`;
  host.style.height = `${maxY}px`;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", String(maxX));
  svg.setAttribute("height", String(maxY));
  svg.classList.add("dom-edges");
  for (const edge of graph.edges) {
    const source = graph.nodes.find((n) => n.id === edge.source);
    const target = graph.nodes.find((n) => n.id === edge.target);
    if (!source || !target) continue;
    const sx = source.position.x + NODE_W;
    const sy = source.position.y + NODE_H / 2;
    const tx = target.position.x;
    const ty = target.position.y + NODE_H / 2;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${sx} ${sy} C ${sx + 60} ${sy}, ${tx - 60} ${ty}, ${tx} ${ty}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "rgba(160,170,190,0.45)");
    path.setAttribute("stroke-width", "2");
    svg.appendChild(path);
  }
  host.appendChild(svg);

  for (const node of graph.nodes) {
    const el = document.createElement("div");
    el.className = `dom-node status-${node.status || "idle"}`;
    el.style.left = `${node.position.x}px`;
    el.style.top = `${node.position.y}px`;
    el.style.width = `${NODE_W}px`;
    el.style.height = `${NODE_H}px`;
    el.innerHTML = `<span>${escapeHtml(node.type)}</span><strong>${escapeHtml(node.label)}</strong>`;
    el.addEventListener("click", () => selectNode(node.id));
    host.appendChild(el);
  }
}

// ------------------------------------------------------------------- helpers

function formatTime(ts) {
  if (!ts) return "";
  return ts.slice(11, 23);
}

function notify(message, kind = "info") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => {
    el.className = "toast";
  }, 3500);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

window.__ay = {
  state,
  ready: false,
  stats: () => state.renderer?.stats() ?? { webgl: false },
  traceRows: () => state.events.length,
  selectNode,
};

init().catch((error) => {
  console.error(error);
  notify(error.message, "error");
});
