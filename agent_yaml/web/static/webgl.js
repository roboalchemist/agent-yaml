// WebGL2 stage-graph renderer for the agent-yaml interface runner.
//
// Draws the workflow stage graph with GPU geometry: instanced rounded-rectangle
// nodes (SDF shader) and tessellated bezier edges. Text lives in a DOM layer so
// it stays crisp and accessible while the GPU handles the graph itself.
//
// No external dependencies. Falls back by returning null when WebGL2 is missing
// (the caller then uses the DOM renderer).

const NODE_W = 168;
const NODE_H = 96;
const NODE_RADIUS = 14;
const EDGE_WIDTH = 1.8;
const EDGE_SAMPLES = 26;

const PALETTE = {
  idle: { fill: [0.105, 0.121, 0.152], border: [0.184, 0.212, 0.266], glow: 0 },
  running: { fill: [0.227, 0.176, 0.058], border: [0.941, 0.706, 0.160], glow: 1 },
  success: { fill: [0.070, 0.145, 0.101], border: [0.239, 0.862, 0.517], glow: 0 },
  failed: { fill: [0.164, 0.078, 0.086], border: [1.0, 0.360, 0.400], glow: 0 },
  skipped: { fill: [0.101, 0.117, 0.149], border: [0.419, 0.447, 0.501], glow: 0 },
  partial: { fill: [0.164, 0.129, 0.074], border: [1.0, 0.662, 0.301], glow: 0 },
  cancelled: { fill: [0.117, 0.117, 0.117], border: [0.501, 0.501, 0.501], glow: 0 },
};

const NODE_VS = `#version 300 es
in vec2 a_corner;
in vec2 i_center;
in vec2 i_size;
in float i_radius;
in vec3 i_fill;
in vec3 i_border;
in vec2 i_flags;      // x = selected, y = pulse
uniform vec2 u_pan;
uniform float u_zoom;
uniform vec2 u_res;

out vec2 v_local;
out vec2 v_size;
out float v_radius;
out vec3 v_fill;
out vec3 v_border;
out float v_selected;
out float v_pulse;

void main() {
  vec2 world = i_center + a_corner * i_size * 0.5;
  vec2 screen = (world - u_pan) * u_zoom;
  vec2 clip = vec2(screen.x / u_res.x * 2.0 - 1.0, 1.0 - screen.y / u_res.y * 2.0);
  gl_Position = vec4(clip, 0.0, 1.0);

  v_local = a_corner * i_size * 0.5;
  v_size = i_size;
  v_radius = i_radius;
  v_fill = i_fill;
  v_border = i_border;
  v_selected = i_flags.x;
  v_pulse = i_flags.y;
}`;

const NODE_FS = `#version 300 es
precision highp float;
in vec2 v_local;
in vec2 v_size;
in float v_radius;
in vec3 v_fill;
in vec3 v_border;
in float v_selected;
in float v_pulse;
uniform float u_time;
uniform float u_zoom;
out vec4 out_color;

float sd_round_box(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
  float d = sd_round_box(v_local, v_size * 0.5, v_radius);
  float aa = max(fwidth(d), 0.0001);
  float body = 1.0 - smoothstep(-aa, aa, d);

  float border_width = mix(1.4, 2.4, v_selected);
  float inner = 1.0 - smoothstep(-aa, aa, d + border_width);
  vec3 color = mix(v_border, v_fill, inner);

  // Running stages breathe with a soft glow ring.
  float pulse = v_pulse * (0.55 + 0.45 * sin(u_time * 4.0));
  float ring = smoothstep(10.0 * aa, 0.0, d) * smoothstep(0.0, 6.0 * aa, d);
  color += v_border * ring * pulse * 0.9;
  float alpha = body;

  // Selection adds a crisp outer halo.
  float halo = smoothstep(3.0 * aa, 0.0, d) * smoothstep(0.0, 2.0 * aa, d);
  color = mix(color, vec3(0.92, 0.96, 1.0), halo * v_selected * 0.9);
  alpha = max(alpha, halo * v_selected);

  out_color = vec4(color, alpha);
}`;

const EDGE_VS = `#version 300 es
in vec2 a_pos;
in vec3 a_color;
uniform vec2 u_pan;
uniform float u_zoom;
uniform vec2 u_res;
out vec3 v_color;
void main() {
  vec2 screen = (a_pos - u_pan) * u_zoom;
  vec2 clip = vec2(screen.x / u_res.x * 2.0 - 1.0, 1.0 - screen.y / u_res.y * 2.0);
  gl_Position = vec4(clip, 0.0, 1.0);
  v_color = a_color;
}`;

const EDGE_FS = `#version 300 es
precision highp float;
in vec3 v_color;
out vec4 out_color;
void main() {
  out_color = vec4(v_color, 0.55);
}`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`shader compile failed: ${log}`);
  }
  return shader;
}

function program(gl, vsSource, fsSource) {
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, vsSource));
  gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, fsSource));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    throw new Error(`program link failed: ${gl.getProgramInfoLog(prog)}`);
  }
  return prog;
}

function statusStyle(status) {
  return PALETTE[status] || PALETTE.idle;
}

/** Sample a cubic bezier into world-space points. */
function bezier(from, c1, c2, to, samples) {
  const points = [];
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    const mt = 1 - t;
    const x =
      mt * mt * mt * from.x + 3 * mt * mt * t * c1.x + 3 * mt * t * t * c2.x + t * t * t * to.x;
    const y =
      mt * mt * mt * from.y + 3 * mt * mt * t * c1.y + 3 * mt * t * t * c2.y + t * t * t * to.y;
    points.push({ x, y });
  }
  return points;
}

/**
 * Create a WebGL2 renderer bound to a canvas + DOM label layer.
 *
 * Returns null when WebGL2 is unavailable so callers can fall back.
 */
export function createWebGLRenderer({ canvas, labelLayer, onSelect, onHover }) {
  const gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: false });
  if (!gl) return null;

  const nodeProg = program(gl, NODE_VS, NODE_FS);
  const edgeProg = program(gl, EDGE_VS, EDGE_FS);

  const nodeLoc = {
    corner: gl.getAttribLocation(nodeProg, "a_corner"),
    center: gl.getAttribLocation(nodeProg, "i_center"),
    size: gl.getAttribLocation(nodeProg, "i_size"),
    radius: gl.getAttribLocation(nodeProg, "i_radius"),
    fill: gl.getAttribLocation(nodeProg, "i_fill"),
    border: gl.getAttribLocation(nodeProg, "i_border"),
    flags: gl.getAttribLocation(nodeProg, "i_flags"),
    pan: gl.getUniformLocation(nodeProg, "u_pan"),
    zoom: gl.getUniformLocation(nodeProg, "u_zoom"),
    res: gl.getUniformLocation(nodeProg, "u_res"),
    time: gl.getUniformLocation(nodeProg, "u_time"),
  };
  const edgeLoc = {
    pos: gl.getAttribLocation(edgeProg, "a_pos"),
    color: gl.getAttribLocation(edgeProg, "a_color"),
    pan: gl.getUniformLocation(edgeProg, "u_pan"),
    zoom: gl.getUniformLocation(edgeProg, "u_zoom"),
    res: gl.getUniformLocation(edgeProg, "u_res"),
  };

  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
    gl.STATIC_DRAW,
  );

  const nodeVao = gl.createVertexArray();
  const nodeBuffer = gl.createBuffer();
  const edgeVao = gl.createVertexArray();
  const edgeBuffer = gl.createBuffer();

  const state = {
    nodes: [],
    edges: [],
    nodeIndex: new Map(),
    pan: { x: 0, y: 0 },
    zoom: 1,
    selected: null,
    hovered: null,
    width: 1,
    height: 1,
    dpr: 1,
    needsRender: true,
    running: 0,
    raf: null,
    startedAt: performance.now(),
    labels: new Map(),
    disposed: false,
  };

  const ctx = gl;
  let edgeVertexCount = 0;

  function bindNodeVao() {
    ctx.bindVertexArray(nodeVao);
    ctx.bindBuffer(ctx.ARRAY_BUFFER, quad);
    ctx.enableVertexAttribArray(nodeLoc.corner);
    ctx.vertexAttribPointer(nodeLoc.corner, 2, ctx.FLOAT, false, 0, 0);

    ctx.bindBuffer(ctx.ARRAY_BUFFER, nodeBuffer);
    const stride = 13 * 4;
    const attrs = [
      [nodeLoc.center, 2, 0],
      [nodeLoc.size, 2, 2 * 4],
      [nodeLoc.radius, 1, 4 * 4],
      [nodeLoc.fill, 3, 5 * 4],
      [nodeLoc.border, 3, 8 * 4],
      [nodeLoc.flags, 2, 11 * 4],
    ];
    for (const [location, size, offset] of attrs) {
      if (location < 0) continue;
      ctx.enableVertexAttribArray(location);
      ctx.vertexAttribPointer(location, size, ctx.FLOAT, false, stride, offset);
      ctx.vertexAttribDivisor(location, 1);
    }
  }

  function bindEdgeVao() {
    ctx.bindVertexArray(edgeVao);
    ctx.bindBuffer(ctx.ARRAY_BUFFER, edgeBuffer);
    const stride = 5 * 4;
    ctx.enableVertexAttribArray(edgeLoc.pos);
    ctx.vertexAttribPointer(edgeLoc.pos, 2, ctx.FLOAT, false, stride, 0);
    ctx.enableVertexAttribArray(edgeLoc.color);
    ctx.vertexAttribPointer(edgeLoc.color, 3, ctx.FLOAT, false, stride, 8);
  }

  function uploadNodes() {
    const data = new Float32Array(state.nodes.length * 13);
    state.nodes.forEach((node, i) => {
      const style = statusStyle(node.status);
      const base = i * 13;
      const selected = state.selected === node.id ? 1 : 0;
      const pulse = node.status === "running" ? 1 : 0;
      data.set(
        [
          node.position.x + NODE_W / 2,
          node.position.y + NODE_H / 2,
          NODE_W,
          NODE_H,
          NODE_RADIUS,
          style.fill[0],
          style.fill[1],
          style.fill[2],
          style.border[0],
          style.border[1],
          style.border[2],
          selected,
          pulse,
        ],
        base,
      );
    });
    ctx.bindBuffer(ctx.ARRAY_BUFFER, nodeBuffer);
    ctx.bufferData(ctx.ARRAY_BUFFER, data, ctx.DYNAMIC_DRAW);
  }

  function edgeColor(edge) {
    const source = state.nodeIndex.get(edge.source);
    const target = state.nodeIndex.get(edge.target);
    const active = [source?.status, target?.status];
    if (active.includes("failed")) return [1.0, 0.36, 0.4];
    if (active.includes("running")) return [0.941, 0.706, 0.16];
    if (target?.status === "success" || source?.status === "success") return [0.239, 0.862, 0.517];
    return [0.42, 0.48, 0.56];
  }

  function uploadEdges() {
    const vertices = [];
    for (const edge of state.edges) {
      const source = state.nodeIndex.get(edge.source);
      const target = state.nodeIndex.get(edge.target);
      if (!source || !target) continue;
      const from = { x: source.position.x + NODE_W, y: source.position.y + NODE_H / 2 };
      const to = { x: target.position.x, y: target.position.y + NODE_H / 2 };
      const dx = to.x - from.x;
      const c1 = { x: from.x + Math.max(40, dx / 2), y: from.y };
      const c2 = { x: to.x - Math.max(40, dx / 2), y: to.y };
      const points = bezier(from, c1, c2, to, EDGE_SAMPLES);
      const color = edgeColor(edge);
      for (let i = 0; i < points.length - 1; i += 1) {
        const a = points[i];
        const b = points[i + 1];
        const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
        const nx = (-(b.y - a.y) / len) * (EDGE_WIDTH / 2);
        const ny = ((b.x - a.x) / len) * (EDGE_WIDTH / 2);
        const quadPoints = [
          [a.x + nx, a.y + ny],
          [a.x - nx, a.y - ny],
          [b.x + nx, b.y + ny],
          [b.x + nx, b.y + ny],
          [a.x - nx, a.y - ny],
          [b.x - nx, b.y - ny],
        ];
        for (const [x, y] of quadPoints) vertices.push(x, y, color[0], color[1], color[2]);
      }
    }
    edgeVertexCount = vertices.length / 5;
    ctx.bindBuffer(ctx.ARRAY_BUFFER, edgeBuffer);
    ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array(vertices), ctx.STATIC_DRAW);
  }

  function buildLabels() {
    labelLayer.innerHTML = "";
    state.labels.clear();
    for (const node of state.nodes) {
      const el = document.createElement("div");
      el.className = "gl-label";
      el.dataset.nodeId = node.id;
      el.innerHTML = `
        <span class="gl-kind">${escapeHtml(node.type || "task")}</span>
        <strong class="gl-title">${escapeHtml(node.label || node.id)}</strong>
        <span class="gl-status">${escapeHtml(node.status || "idle")}</span>
      `;
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        select(node.id);
      });
      labelLayer.appendChild(el);
      state.labels.set(node.id, el);
    }
  }

  function layoutLabels() {
    for (const node of state.nodes) {
      const el = state.labels.get(node.id);
      if (!el) continue;
      const style = statusStyle(node.status);
      const x = (node.position.x - state.pan.x) * state.zoom;
      const y = (node.position.y - state.pan.y) * state.zoom;
      el.style.transform = `translate(${x}px, ${y}px) scale(${state.zoom})`;
      el.style.width = `${NODE_W}px`;
      el.style.height = `${NODE_H}px`;
      el.dataset.status = node.status || "idle";
      el.style.setProperty("--node-accent", `rgb(${style.border.map((c) => Math.round(c * 255)).join(",")})`);
      el.classList.toggle("selected", state.selected === node.id);
    }
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    state.dpr = window.devicePixelRatio || 1;
    state.width = Math.max(1, rect.width);
    state.height = Math.max(1, rect.height);
    canvas.width = Math.round(state.width * state.dpr);
    canvas.height = Math.round(state.height * state.dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
    state.needsRender = true;
  }

  function draw() {
    const w = canvas.width;
    const h = canvas.height;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const zoom = state.zoom * state.dpr;
    gl.useProgram(edgeProg);
    gl.uniform2f(edgeLoc.pan, state.pan.x, state.pan.y);
    gl.uniform1f(edgeLoc.zoom, zoom);
    gl.uniform2f(edgeLoc.res, w, h);
    bindEdgeVao();
    gl.drawArrays(gl.TRIANGLES, 0, edgeVertexCount);

    gl.useProgram(nodeProg);
    gl.uniform2f(nodeLoc.pan, state.pan.x, state.pan.y);
    gl.uniform1f(nodeLoc.zoom, zoom);
    gl.uniform2f(nodeLoc.res, w, h);
    gl.uniform1f(nodeLoc.time, (performance.now() - state.startedAt) / 1000);
    bindNodeVao();
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, state.nodes.length);

    state.needsRender = false;
  }

  function animate() {
    if (state.disposed) return;
    if (state.needsRender || state.running > 0) {
      draw();
      layoutLabels();
    }
    state.raf = requestAnimationFrame(animate);
  }

  // ---- interaction
  let dragging = null;

  function toWorld(event) {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    return { x: state.pan.x + x / state.zoom, y: state.pan.y + y / state.zoom };
  }

  function nodeAt(world) {
    for (const node of state.nodes) {
      if (
        world.x >= node.position.x &&
        world.x <= node.position.x + NODE_W &&
        world.y >= node.position.y &&
        world.y <= node.position.y + NODE_H
      ) {
        return node;
      }
    }
    return null;
  }

  function select(nodeId) {
    state.selected = nodeId;
    uploadNodes();
    layoutLabels();
    state.needsRender = true;
    if (onSelect) onSelect(nodeId);
  }

  canvas.addEventListener("pointerdown", (event) => {
    dragging = {
      startX: event.clientX,
      startY: event.clientY,
      panX: state.pan.x,
      panY: state.pan.y,
      moved: false,
    };
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (dragging) {
      const dx = event.clientX - dragging.startX;
      const dy = event.clientY - dragging.startY;
      if (Math.abs(dx) + Math.abs(dy) > 3) dragging.moved = true;
      state.pan.x = dragging.panX - dx / state.zoom;
      state.pan.y = dragging.panY - dy / state.zoom;
      state.needsRender = true;
      layoutLabels();
      return;
    }
    const world = toWorld(event);
    const node = nodeAt(world);
    const id = node ? node.id : null;
    if (id !== state.hovered) {
      state.hovered = id;
      canvas.style.cursor = id ? "pointer" : "grab";
      if (onHover) onHover(id);
    }
  });

  canvas.addEventListener("pointerup", (event) => {
    if (dragging && !dragging.moved) {
      const world = toWorld(event);
      const node = nodeAt(world);
      select(node ? node.id : null);
    }
    dragging = null;
  });

  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      const worldX = state.pan.x + px / state.zoom;
      const worldY = state.pan.y + py / state.zoom;
      const factor = Math.exp(-event.deltaY * 0.0015);
      state.zoom = Math.min(3, Math.max(0.2, state.zoom * factor));
      state.pan.x = worldX - px / state.zoom;
      state.pan.y = worldY - py / state.zoom;
      state.needsRender = true;
      layoutLabels();
    },
    { passive: false },
  );

  // ---- public API
  function setGraph(graph) {
    state.nodes = (graph.nodes || []).map((node) => ({
      ...node,
      position: { x: node.position?.x ?? 0, y: node.position?.y ?? 0 },
      status: node.status || "idle",
    }));
    state.edges = (graph.edges || []).map((edge) => ({ ...edge }));
    state.nodeIndex = new Map(state.nodes.map((node) => [node.id, node]));
    state.selected = null;
    buildLabels();
    uploadNodes();
    uploadEdges();
    fit();
    state.needsRender = true;
    layoutLabels();
  }

  function setNodeState(nodeId, status, meta = {}) {
    const node = state.nodeIndex.get(nodeId);
    if (!node) return;
    node.status = status || "idle";
    node.lastEvent = meta;
    state.running = state.nodes.filter((n) => n.status === "running").length;
    uploadNodes();
    uploadEdges();
    updateLabel(node);
    state.needsRender = true;
  }

  function updateLabel(node) {
    const el = state.labels.get(node.id);
    if (!el) return;
    el.dataset.status = node.status;
    const statusEl = el.querySelector(".gl-status");
    if (statusEl) statusEl.textContent = node.status;
    const style = statusStyle(node.status);
    el.style.setProperty("--node-accent", `rgb(${style.border.map((c) => Math.round(c * 255)).join(",")})`);
  }

  function fit() {
    if (!state.nodes.length) {
      state.pan = { x: 0, y: 0 };
      state.zoom = 1;
      return;
    }
    const minX = Math.min(...state.nodes.map((n) => n.position.x));
    const minY = Math.min(...state.nodes.map((n) => n.position.y));
    const maxX = Math.max(...state.nodes.map((n) => n.position.x + NODE_W));
    const maxY = Math.max(...state.nodes.map((n) => n.position.y + NODE_H));
    const bw = Math.max(1, maxX - minX);
    const bh = Math.max(1, maxY - minY);
    state.zoom = Math.min(1.2, Math.max(0.25, Math.min(state.width / (bw + 120), state.height / (bh + 120))));
    state.pan.x = minX - (state.width / state.zoom - bw) / 2;
    state.pan.y = minY - (state.height / state.zoom - bh) / 2;
  }

  function focusNode(nodeId) {
    const node = state.nodeIndex.get(nodeId);
    if (!node) return;
    state.pan.x = node.position.x + NODE_W / 2 - state.width / state.zoom / 2;
    state.pan.y = node.position.y + NODE_H / 2 - state.height / state.zoom / 2;
    state.needsRender = true;
    layoutLabels();
  }

  function zoomBy(factor) {
    const center = { x: state.width / 2, y: state.height / 2 };
    const worldX = state.pan.x + center.x / state.zoom;
    const worldY = state.pan.y + center.y / state.zoom;
    state.zoom = Math.min(3, Math.max(0.2, state.zoom * factor));
    state.pan.x = worldX - center.x / state.zoom;
    state.pan.y = worldY - center.y / state.zoom;
    state.needsRender = true;
    layoutLabels();
  }

  function stats() {
    return {
      webgl: true,
      nodes: state.nodes.length,
      edges: state.edges.length,
      zoom: Number(state.zoom.toFixed(3)),
      running: state.running,
      selected: state.selected,
    };
  }

  function destroy() {
    state.disposed = true;
    if (state.raf) cancelAnimationFrame(state.raf);
    labelLayer.innerHTML = "";
  }

  resize();
  animate();

  return {
    setGraph,
    setNodeState,
    select,
    focusNode,
    zoomBy,
    fit,
    resize,
    stats,
    destroy,
    get selected() {
      return state.selected;
    },
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
