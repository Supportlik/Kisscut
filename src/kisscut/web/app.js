/* Kisscut studio.
   The canvas shows the photo exactly as the server will frame it - rotated
   first, then cropped - so a box drawn here is the box the cut uses. */

const $ = (id) => document.getElementById(id);

const state = {
  id: null,
  name: "sticker",
  image: null,          // HTMLImageElement of the source photo
  tool: "view",
  bg: "light",
  drag: null,
  recipe: {
    rotate: 0, crop: null, look: "as-shot", sharpness: 1, saturation: 1, brightness: 1,
    shape: "silhouette", source: "model", model: "birefnet-portrait", lasso: [],
    pop_out: true, border: 14, border_color: "#ffffff", shadow: true,
    zoom: 1, offset_x: 0, offset_y: 0,
  },
};

let meta = { models: {}, shapes: {}, looks: [] };
let previewUrl = null;
let previewSeq = 0;

/* ------------------------------------------------------------- helpers */

function toast(message, kind = "info", ms = 4200) {
  const el = $("toast");
  el.textContent = message;
  el.dataset.kind = kind;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, ms);
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(detail.error || "request failed");
  }
  return response;
}

/* --------------------------------------------------------------- stage */

function rotatedSize() {
  const { width: w, height: h } = state.image;
  const rad = (state.recipe.rotate * Math.PI) / 180;
  const cos = Math.abs(Math.cos(rad));
  const sin = Math.abs(Math.sin(rad));
  return { w: Math.round(w * cos + h * sin), h: Math.round(w * sin + h * cos) };
}

function drawStage() {
  const canvas = $("canvas");
  if (!state.image) return;

  const { w, h } = rotatedSize();
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);

  ctx.save();
  ctx.translate(w / 2, h / 2);
  ctx.rotate((-state.recipe.rotate * Math.PI) / 180);   // PIL turns counter-clockwise
  ctx.drawImage(state.image, -state.image.width / 2, -state.image.height / 2);
  ctx.restore();

  const crop = state.drag?.kind === "crop" ? state.drag.rect : state.recipe.crop;
  if (crop) {
    const [x0, y0, x1, y1] = crop.map((v, i) => v * (i % 2 ? h : w));
    ctx.fillStyle = "rgba(10,12,15,0.55)";
    ctx.fillRect(0, 0, w, y0);
    ctx.fillRect(0, y1, w, h - y1);
    ctx.fillRect(0, y0, x0, y1 - y0);
    ctx.fillRect(x1, y0, w - x1, y1 - y0);
    ctx.strokeStyle = "#e9e7e2";
    ctx.lineWidth = Math.max(2, w / 500);
    ctx.setLineDash([9, 7]);
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.setLineDash([]);
  }

  const trace = state.drag?.kind === "lasso" ? state.drag.points : state.recipe.lasso;
  if (trace && trace.length > 1) {
    ctx.beginPath();
    trace.forEach(([x, y], i) => {
      const px = x * w;
      const py = y * h;
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    });
    if (state.drag?.kind !== "lasso") ctx.closePath();
    ctx.strokeStyle = "#e4002b";
    ctx.lineWidth = Math.max(3, w / 320);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
  }
}

function canvasPoint(event) {
  const canvas = $("canvas");
  const box = canvas.getBoundingClientRect();
  return [
    Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1),
    Math.min(Math.max((event.clientY - box.top) / box.height, 0), 1),
  ];
}

function bindCanvas() {
  const canvas = $("canvas");

  canvas.addEventListener("pointerdown", (event) => {
    if (!state.image || state.tool === "view") return;
    canvas.setPointerCapture(event.pointerId);
    const point = canvasPoint(event);
    state.drag = state.tool === "crop"
      ? { kind: "crop", start: point, rect: [point[0], point[1], point[0], point[1]] }
      : { kind: "lasso", points: [point] };
    drawStage();
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!state.drag) return;
    const [x, y] = canvasPoint(event);
    if (state.drag.kind === "crop") {
      const [sx, sy] = state.drag.start;
      state.drag.rect = [Math.min(sx, x), Math.min(sy, y), Math.max(sx, x), Math.max(sy, y)];
    } else {
      const last = state.drag.points[state.drag.points.length - 1];
      if (Math.hypot(x - last[0], y - last[1]) > 0.004) state.drag.points.push([x, y]);
    }
    drawStage();
  });

  canvas.addEventListener("pointerup", () => {
    if (!state.drag) return;
    if (state.drag.kind === "crop") {
      const [x0, y0, x1, y1] = state.drag.rect;
      state.recipe.crop = (x1 - x0 > 0.03 && y1 - y0 > 0.03) ? [x0, y0, x1, y1] : null;
      if (!state.recipe.crop) toast("That crop was too small - ignored.");
    } else if (state.drag.points.length > 8) {
      state.recipe.lasso = state.drag.points;
      setSource("lasso");
    } else {
      toast("Trace a longer outline around the subject.");
    }
    state.drag = null;
    drawStage();
    refresh({ heavy: true });
  });
}

/* ------------------------------------------------------------- preview */

async function renderPreview() {
  if (!state.id) return;
  const seq = ++previewSeq;
  $("spinner").hidden = false;
  try {
    const response = await postJSON("/api/preview", { id: state.id, recipe: state.recipe });
    const blob = await response.blob();
    if (seq !== previewSeq) return;                // a newer request overtook this one
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    for (const id of ["previewImg", "chatLight", "chatDark"]) $(id).src = previewUrl;
    const clear = Number(response.headers.get("X-Transparent") || 0);
    $("previewMeta").textContent =
      `512 × 512 · ${clear}% transparent · ${state.recipe.shape} · border ${state.recipe.border} px`;
    $("previewMeta").title = clear < 6
      ? "Almost nothing is cut away - pick a cutout in step 3 or a rounder die in step 4."
      : "";
  } catch (error) {
    toast(error.message, "error");
  } finally {
    if (seq === previewSeq) $("spinner").hidden = true;
  }
}

async function loadSuggestions() {
  if (!state.id) return;
  const rail = $("shelf");
  try {
    const response = await postJSON("/api/suggestions", { id: state.id, recipe: state.recipe });
    const { suggestions } = await response.json();
    rail.innerHTML = "";
    for (const item of suggestions) {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.innerHTML = `<img alt="" src="${item.png}"><span>${item.name}</span>`;
      chip.addEventListener("click", () => {
        Object.assign(state.recipe, item.recipe);
        syncControls();
        refresh();
      });
      rail.appendChild(chip);
    }
  } catch (error) {
    rail.innerHTML = `<p class="hint">${error.message}</p>`;
  }
}

const previewSoon = debounce(renderPreview, 220);
const suggestSoon = debounce(loadSuggestions, 900);

function refresh({ heavy = false } = {}) {
  previewSoon();
  if (heavy) suggestSoon();
}

/* -------------------------------------------------------------- photo */

async function openFile(file) {
  if (!file) return;
  try {
    const response = await fetch("/api/open", {
      method: "POST",
      headers: { "X-Filename": encodeURIComponent(file.name) },
      body: await file.arrayBuffer(),
    });
    if (!response.ok) throw new Error((await response.json()).error);
    const info = await response.json();

    state.id = info.id;
    state.name = info.name;
    state.recipe.crop = null;
    state.recipe.lasso = [];
    state.recipe.rotate = info.angle || 0;
    state.recipe.look = info.look || "as-shot";

    $("photoName").textContent = `${file.name} · ${info.width} × ${info.height}`;
    for (const id of ["downloadPng", "downloadWebp", "saveFolder"]) $(id).disabled = false;
    $("stageEmpty").hidden = true;
    $("rotateRow").hidden = false;
    $("tiltNote").hidden = !info.angle;
    if (info.angle) {
      $("tiltNote").textContent =
        `Looks like a photo of a print, tilted ${info.angle}° - straightened, ` +
        `and set to the "print" look to clear the haze.`;
    }
    syncControls();

    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error("the photo could not be displayed"));
      image.src = info.source;
    });
    state.image = image;

    drawStage();
    renderPreview();
    loadSuggestions();
  } catch (error) {
    toast(error.message || "could not open that file", "error");
  }
}

/* ------------------------------------------------------------ controls */

function setSource(value) {
  state.recipe.source = value;
  document.querySelectorAll("[data-source]").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.source === value);
  });
  $("modelField").hidden = value !== "model";
  $("modelNote").textContent = value === "model" ? (meta.models[state.recipe.model] || "") : "";
  $("popField").hidden = value === "full" || state.recipe.shape === "silhouette";
}

function setShape(value) {
  state.recipe.shape = value;
  document.querySelectorAll(".die").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.shape === value);
  });
  const geometric = value !== "silhouette";
  $("zoomRow").hidden = !geometric;
  $("popField").hidden = !geometric || state.recipe.source === "full";
}

function setTool(value) {
  state.tool = value;
  document.querySelectorAll("[data-tool]").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.tool === value);
  });
  $("canvas").dataset.tool = value;
  $("toolNote").textContent = {
    view: "Drag a box to crop, or trace the subject by hand.",
    crop: "Drag a box on the photo. Everything outside is dropped.",
    lasso: "Draw around what you want to keep - it closes itself.",
  }[value];
}

function syncControls() {
  const r = state.recipe;
  $("rotate").value = r.rotate;
  $("rotateOut").textContent = `${Number(r.rotate).toFixed(1)}°`;
  $("border").value = r.border;
  $("borderOut").textContent = `${r.border} px`;
  $("shadow").checked = r.shadow;
  $("popOut").checked = r.pop_out;
  $("zoom").value = r.zoom;
  $("zoomOut").textContent = `${Number(r.zoom).toFixed(2)}×`;
  for (const key of ["sharpness", "saturation", "brightness"]) {
    $(key).value = r[key];
    $(`${key}Out`).textContent = Number(r[key]).toFixed(2);
  }
  document.querySelectorAll("#looks .seg-btn").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.look === r.look);
  });
  document.querySelectorAll(".swatch[data-color]").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.color === r.border_color);
  });
  setShape(r.shape);
  setSource(r.source);
}

function slider(id, key, format) {
  $(id).addEventListener("input", (event) => {
    state.recipe[key] = Number(event.target.value);
    $(`${id}Out`).textContent = format(event.target.value);
    previewSoon();
  });
}

/* ---------------------------------------------------------------- dies */

function dieIcon(shape) {
  const svg = (body) => `<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
  const points = (steps, radius) => {
    const pts = [];
    for (let i = 0; i < steps; i++) {
      const t = (i / steps) * Math.PI * 2 - Math.PI / 2;
      const r = radius(i, t);
      pts.push(`${(12 + r * Math.cos(t)).toFixed(2)},${(12 + r * Math.sin(t)).toFixed(2)}`);
    }
    return `<polygon points="${pts.join(" ")}"/>`;
  };
  // Fewer, deeper waves than the real die: at 24 px the shape has to read as
  // a scalloped edge, and eighteen of them would just blur into a circle.
  const rosette = (waves, depth) =>
    points(waves * 10, (_, t) => 10.5 * (1 - depth + depth * Math.cos(waves * t)));
  const star = (spikes, inner, outer) =>
    points(spikes * 2, (i) => (i % 2 ? inner : outer));
  switch (shape) {
    case "circle": return svg('<circle cx="12" cy="12" r="10"/>');
    case "square": return svg('<rect x="2" y="2" width="20" height="20" rx="2"/>');
    case "rounded": return svg('<rect x="2" y="2" width="20" height="20" rx="6"/>');
    case "bubble": return svg('<path d="M3 4h18a1 1 0 011 1v11a1 1 0 01-1 1H10l-4 4v-4H3a1 1 0 01-1-1V5a1 1 0 011-1z"/>');
    case "seal": return svg(rosette(10, 0.09));
    case "burst": return svg(star(12, 6.2, 10.5));
    case "heart": return svg('<path d="M12 21C6 16.5 2.5 13.3 2.5 9.3 2.5 6.4 4.8 4 7.8 4c1.8 0 3.3.9 4.2 2.2C12.9 4.9 14.4 4 16.2 4c3 0 5.3 2.4 5.3 5.3 0 4-3.5 7.2-9.5 11.7z"/>');
    default: return svg('<path d="M9 2.6c3-1.2 6 .4 7.4 2.6 1 1.6 3.4 1.4 4.6 3.2 1.5 2.3-.2 5-1.6 6.6-1.7 2-1.4 4.6-3.6 6.3-2.5 2-6.2 1.3-8.6-.6-2.2-1.7-2.2-4.2-3.6-6.2C2.2 12.3.8 9.6 2 7.2 3.3 4.6 6.2 3.7 9 2.6z"/>');
  }
}

function buildDies() {
  const holder = $("dies");
  holder.innerHTML = "";
  for (const [key, label] of Object.entries(meta.shapes)) {
    const button = document.createElement("button");
    button.className = "die";
    button.dataset.shape = key;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = dieIcon(key);
    button.addEventListener("click", () => { setShape(key); refresh(); });
    holder.appendChild(button);
  }
}

function buildLooks() {
  const holder = $("looks");
  holder.innerHTML = "";
  for (const look of meta.looks) {
    const button = document.createElement("button");
    button.className = "seg-btn";
    button.dataset.look = look;
    button.textContent = look[0].toUpperCase() + look.slice(1);
    button.addEventListener("click", () => {
      state.recipe.look = look;
      syncControls();
      previewSoon();
    });
    holder.appendChild(button);
  }
}

/* ----------------------------------------------------------------- go */

async function start() {
  meta = await (await fetch("/api/meta")).json();

  const select = $("model");
  for (const [key, label] of Object.entries(meta.models)) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${key} — ${label}`;
    select.appendChild(option);
  }
  select.value = state.recipe.model;
  select.addEventListener("change", () => {
    state.recipe.model = select.value;
    $("modelNote").textContent = meta.models[select.value] || "";
    refresh({ heavy: true });
  });

  buildDies();
  buildLooks();
  bindCanvas();
  syncControls();

  $("fileInput").addEventListener("change", (event) => openFile(event.target.files[0]));

  document.querySelectorAll("[data-tool]").forEach((button) => {
    button.addEventListener("click", () => setTool(button.dataset.tool));
  });
  document.querySelectorAll("[data-source]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.source === "lasso" && state.recipe.lasso.length < 3) {
        toast("Trace an outline first - pick Trace in step 2.");
        return;
      }
      setSource(button.dataset.source);
      refresh({ heavy: true });
    });
  });
  document.querySelectorAll("[data-bg]").forEach((button) => {
    button.addEventListener("click", () => {
      state.bg = button.dataset.bg;
      $("sheet").dataset.bg = state.bg;
      document.querySelectorAll("[data-bg]").forEach((other) => {
        other.classList.toggle("is-on", other === button);
      });
    });
  });
  document.querySelectorAll(".swatch[data-color]").forEach((button) => {
    button.addEventListener("click", () => {
      state.recipe.border_color = button.dataset.color;
      syncControls();
      previewSoon();
    });
  });
  $("colorPick").addEventListener("input", (event) => {
    state.recipe.border_color = event.target.value;
    syncControls();
    previewSoon();
  });

  slider("rotate", "rotate", (v) => `${Number(v).toFixed(1)}°`);
  slider("border", "border", (v) => `${v} px`);
  slider("zoom", "zoom", (v) => `${Number(v).toFixed(2)}×`);
  slider("sharpness", "sharpness", (v) => Number(v).toFixed(2));
  slider("saturation", "saturation", (v) => Number(v).toFixed(2));
  slider("brightness", "brightness", (v) => Number(v).toFixed(2));

  $("rotate").addEventListener("input", drawStage);
  $("rotate").addEventListener("change", () => refresh({ heavy: true }));

  $("shadow").addEventListener("change", (event) => {
    state.recipe.shadow = event.target.checked;
    previewSoon();
  });
  $("popOut").addEventListener("change", (event) => {
    state.recipe.pop_out = event.target.checked;
    previewSoon();
  });

  $("resetCrop").addEventListener("click", () => {
    state.recipe.crop = null;
    drawStage();
    refresh({ heavy: true });
  });
  $("clearLasso").addEventListener("click", () => {
    state.recipe.lasso = [];
    if (state.recipe.source === "lasso") setSource("model");
    drawStage();
    refresh({ heavy: true });
  });

  async function download(format) {
    if (!state.id) return;
    const button = format === "webp" ? $("downloadWebp") : $("downloadPng");
    button.disabled = true;
    try {
      const response = await postJSON("/api/export", {
        id: state.id, recipe: state.recipe, name: state.name, format,
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${state.name}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      const kb = Math.round(blob.size / 1024);
      const tooBig = format === "webp" && blob.size > 100000;
      toast(`${state.name}.${format} downloaded (${kb} KB)` +
            (tooBig ? " - over WhatsApp's 100 KB limit" : ""), tooBig ? "error" : "info");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  $("downloadPng").addEventListener("click", () => download("png"));
  $("downloadWebp").addEventListener("click", () => download("webp"));

  $("saveFolder").addEventListener("click", async () => {
    if (!state.id) return;
    $("saveFolder").disabled = true;
    try {
      const response = await postJSON("/api/save", {
        id: state.id, recipe: state.recipe, name: state.name,
      });
      const result = await response.json();
      const parts = result.files.map((f) => `${f.name} (${Math.round(f.bytes / 1024)} KB)`);
      toast(`Saved ${parts.join(" and ")} in ${result.dir}`,
            result.within_limit ? "info" : "error", 6500);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      $("saveFolder").disabled = false;
    }
  });

  // drag and drop anywhere
  const zone = $("dropZone");
  document.addEventListener("dragover", (event) => {
    event.preventDefault();
    document.body.classList.add("is-dragging");
    if (event.target.closest("#dropZone")) zone.classList.add("is-over");
  });
  document.addEventListener("dragleave", (event) => {
    if (event.relatedTarget) return;
    document.body.classList.remove("is-dragging");
    zone.classList.remove("is-over");
  });
  document.addEventListener("drop", (event) => {
    event.preventDefault();
    document.body.classList.remove("is-dragging");
    zone.classList.remove("is-over");
    openFile(event.dataTransfer.files[0]);
  });
}

start().catch((error) => toast(error.message, "error"));
