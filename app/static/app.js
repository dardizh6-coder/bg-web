/* Aucto.ch zhaku-style UI driver (uses existing FastAPI endpoints) */
/* global window, document, fetch, navigator */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// If you host the frontend separately (e.g. 1a-hosting), set this BEFORE loading app.js:
//   <script>window.API_BASE_URL="https://bg-web-production.up.railway.app";</script>
const API_BASE = String(window.API_BASE_URL || "").replace(/\/+$/, "");
function apiUrl(pathOrUrl) {
  const s = String(pathOrUrl || "");
  if (!s) return s;
  if (s.startsWith("http://") || s.startsWith("https://") || s.startsWith("data:") || s.startsWith("blob:")) return s;
  return `${API_BASE}${s}`;
}

function withToken(url) {
  // Ensure the token is applied to the API host (not the frontend host)
  const full = apiUrl(url);
  if (!state.clientToken) return full;
  try {
    const u = new URL(full, window.location.href);
    if (!u.searchParams.get("token")) u.searchParams.set("token", state.clientToken);
    return u.toString();
  } catch {
    const sep = full.includes("?") ? "&" : "?";
    return `${full}${sep}token=${encodeURIComponent(state.clientToken)}`;
  }
}

const state = {
  clientToken: null,
  paid: false,
  stripeConfigured: false,
  adsense: { client: "", slot: "" },

  files: [],
  jobId: null,
  images: [], // {id, filename, status, original_url, cutout_url, width, height, rotate, scale, x, y, bgId, shadow}
  currentIndex: 0,

  backgrounds: [], // {id, name, description, thumb_url}
  currentBgId: null,

  // editor params
  carPosition: { x: 0, y: 0 },
  carRotation: 0,
  carScale: 100,
  shadow: true,

  // per-image settings
  settings: [], // {x,y,rotate,scale,bgId,shadow}

  // local preview caches (avoid server roundtrips while dragging sliders)
  _imgCache: new Map(), // src -> HTMLImageElement
};

const screens = {
  upload: $("#screen-upload"),
  processing: $("#screen-processing"),
  background: $("#screen-background"),
  position: $("#screen-position"),
  download: $("#screen-download"),
};

function uid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.clientToken) headers["x-client-token"] = state.clientToken;

  const res = await fetch(apiUrl(path), {
    // Cross-domain hosting: don't rely on cookies (third-party cookies are often blocked).
    credentials: "omit",
    ...opts,
    headers,
  });
  if (!res.ok) {
    const txt = await res.text();
    try {
      throw new Error(JSON.parse(txt).detail || txt);
    } catch {
      throw new Error(txt);
    }
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return await res.json();
  return res;
}

function showScreen(name) {
  Object.values(screens).forEach((el) => el && el.classList.remove("active"));
  const el = screens[name];
  if (el) el.classList.add("active");
}

function setPaidUI() {
  $("#paidPill")?.classList.toggle("hidden", !state.paid);
  const ad = $("#adBanner");
  if (ad) ad.style.display = state.paid ? "none" : "block";
}

function setWatermarkNotice() {
  const box = $("#watermark-notice");
  if (!box) return;
  const shouldShow = !state.paid && state.stripeConfigured;
  box.style.display = shouldShow ? "block" : "none";
}

async function initClient() {
  let tok = localStorage.getItem("aucto_client_token");
  if (!tok) {
    tok = uid();
    localStorage.setItem("aucto_client_token", tok);
  }
  state.clientToken = tok;
  await api("/api/client/register", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token: tok }),
  });
}

async function loadMe() {
  const me = await api("/api/me");
  state.paid = !!me.paid;
  state.stripeConfigured = !!me.stripe_configured;
  state.adsense = me.adsense || state.adsense;
  setPaidUI();
  setWatermarkNotice();

  // Optional AdSense injection (if configured)
  if (!state.paid && state.adsense?.client && state.adsense?.slot) {
    const slot = $("#adSlot");
    if (slot) {
      slot.innerHTML = "";
      const script = document.createElement("script");
      script.async = true;
      script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${state.adsense.client}`;
      script.crossOrigin = "anonymous";
      document.head.appendChild(script);

      const ins = document.createElement("ins");
      ins.className = "adsbygoogle";
      ins.style.display = "block";
      ins.setAttribute("data-ad-client", state.adsense.client);
      ins.setAttribute("data-ad-slot", state.adsense.slot);
      ins.setAttribute("data-ad-format", "auto");
      ins.setAttribute("data-full-width-responsive", "true");
      slot.appendChild(ins);
      try {
        (window.adsbygoogle = window.adsbygoogle || []).push({});
      } catch {}
    }
  }
}

async function checkCheckoutReturn() {
  const u = new URL(window.location.href);
  const sessionId = u.searchParams.get("session_id");
  if (u.searchParams.get("checkout") === "success" && sessionId) {
    try {
      await api(`/api/stripe/checkout-status?session_id=${encodeURIComponent(sessionId)}`);
      await loadMe();
      // Re-render current canvases now that paid status changed
      await renderBackgroundPreview();
      await renderPositionPreview();
      await renderFinalPreview();
    } catch (e) {
      console.warn(e);
    }
    u.searchParams.delete("checkout");
    u.searchParams.delete("session_id");
    window.history.replaceState({}, "", u.toString());
  }
}

async function startCheckout() {
  if (!state.stripeConfigured) return;
  const out = await api("/api/stripe/create-checkout", { method: "POST" });
  window.location.href = out.url;
}

// ---- Upload / Processing ----
function setStatusStep(stepKey) {
  const order = ["upload", "remove", "showroom", "done"];
  const idx = order.indexOf(stepKey);
  $$(".status-step").forEach((el) => {
    const s = el.dataset.step;
    const i = order.indexOf(s);
    el.classList.toggle("active", i !== -1 && i <= idx);
  });
}

function setProcessing(text, progressPct) {
  const status = $("#processing-status");
  const fill = $("#progress-fill");
  if (status) status.textContent = text;
  if (fill) fill.style.width = `${progressPct}%`;
}

function showProcessingOverlay(show) {
  const overlay = $("#processing-overlay");
  if (overlay) overlay.style.display = show ? "flex" : "none";
}

function drawImageCover(canvas, img) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  // "cover" behavior: fill the entire canvas, crop overflow.
  const s = Math.max(w / img.width, h / img.height);
  const dw = img.width * s;
  const dh = img.height * s;
  const x = (w - dw) / 2;
  const y = (h - dh) / 2;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, x, y, dw, dh);
}

function sizeCanvasToParent(canvas, minW = 320, minH = 240) {
  const host = canvas.parentElement || canvas;
  const rect = host.getBoundingClientRect();
  const w = Math.max(minW, Math.floor(rect.width || 0));
  const h = Math.max(minH, Math.floor(rect.height || 0));
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
}

function loadImage(src) {
  const resolved = apiUrl(src);
  const cached = state._imgCache.get(resolved);
  if (cached) return Promise.resolve(cached);
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      state._imgCache.set(resolved, img);
      resolve(img);
    };
    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = resolved;
  });
}

function drawCover(ctx, w, h, img) {
  const s = Math.max(w / img.width, h / img.height);
  const dw = img.width * s;
  const dh = img.height * s;
  const x = (w - dw) / 2;
  const y = (h - dh) / 2;
  ctx.drawImage(img, x, y, dw, dh);
}

function drawLocalComposite(canvas, bgImg, carImg) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";

  // Background fills canvas
  drawCover(ctx, w, h, bgImg);

  // Car transform (fast client-side preview)
  const base = Math.min(w / carImg.width, h / carImg.height);
  const scale = base * (Number(state.carScale || 100) / 100);
  const rot = (Number(state.carRotation || 0) * Math.PI) / 180;
  const ox = Number(state.carPosition?.x || 0) * base;
  const oy = Number(state.carPosition?.y || 0) * base;

  ctx.save();
  ctx.translate(w / 2 + ox, h / 2 + oy);
  ctx.rotate(rot);
  ctx.scale(scale, scale);
  ctx.drawImage(carImg, -carImg.width / 2, -carImg.height / 2);
  ctx.restore();
}

function ensureDefaultSettings() {
  if (!state.settings[state.currentIndex]) {
    state.settings[state.currentIndex] = {
      x: 0,
      y: 0,
      rotate: 0,
      scale: 100,
      bgId: state.currentBgId || (state.backgrounds[0] && state.backgrounds[0].id) || null,
      shadow: true,
    };
  }
}

function loadSettingsForCurrent() {
  ensureDefaultSettings();
  const s = state.settings[state.currentIndex];
  state.carPosition = { x: s.x, y: s.y };
  state.carRotation = s.rotate;
  state.carScale = s.scale;
  state.shadow = s.shadow !== false;
}

function saveSettingsForCurrent() {
  ensureDefaultSettings();
  state.settings[state.currentIndex] = {
    ...state.settings[state.currentIndex],
    x: state.carPosition.x,
    y: state.carPosition.y,
    rotate: state.carRotation,
    scale: state.carScale,
    bgId: state.currentBgId,
    shadow: state.shadow,
  };
}

async function startProcessing(files) {
  state.files = files;
  showScreen("processing");
  showProcessingOverlay(true);
  setStatusStep("upload");
  setProcessing("Uploading…", 20);

  // show original preview image
  try {
    const first = files[0];
    const url = URL.createObjectURL(first);
    const imgEl = $("#original-image");
    if (imgEl) imgEl.src = url;
  } catch {}

  const fd = new FormData();
  files.forEach((f) => fd.append("files", f, f.name));
  const job = await api("/api/jobs", { method: "POST", body: fd });
  state.jobId = job.job_id;
  state.images = (job.images || []).map((im) => ({
    ...im,
    rotate: 0,
    scale: 100,
    x: 0,
    y: 0,
    bgId: null,
    shadow: true,
  }));
  state.currentIndex = 0;
  state.settings = [];

  setStatusStep("remove");
  setProcessing("Removing background…", 55);
  await pollJobUntilDone();
}

async function pollJobUntilDone() {
  let done = false;
  while (!done) {
    const st = await api(`/api/jobs/${state.jobId}`);
    const imgs = st.images || [];
    // merge
    state.images = state.images.map((old) => {
      const n = imgs.find((x) => x.id === old.id);
      return n ? { ...old, ...n } : old;
    });

    const ready = imgs.filter((x) => x.status === "ready").length;
    const total = imgs.length || 1;
    setProcessing(`Processing ${ready}/${total}…`, 55 + Math.round((ready / total) * 40));

    // preview-canvas: show first ready composite (fills the whole preview panel)
    const firstReady = imgs.find((x) => x.status === "ready");
    if (firstReady) {
      try {
        const canvas = $("#preview-canvas");
        if (canvas) {
          if (!state.currentBgId && state.backgrounds[0]) state.currentBgId = state.backgrounds[0].id;
          sizeCanvasToParent(canvas, 320, 240);
          const qs = new URLSearchParams();
          qs.set("image_id", firstReady.id);
          qs.set("bg_id", state.currentBgId || "studio_neutral");
          qs.set("rotate", "0");
          qs.set("scale", "1");
          qs.set("x", "0");
          qs.set("y", "0");
          qs.set("shadow", "true");
          qs.set("snap", "true");
          qs.set("fmt", "png");
          const img = await loadImage(withToken(`/api/render/preview?${qs.toString()}&t=${Date.now()}`));
          drawImageCover(canvas, img);
        }
      } catch {}
    }

    done = imgs.every((x) => x.status === "ready" || x.status === "error");
    if (!done) await new Promise((r) => setTimeout(r, 900));
  }

  // keep only successful
  const ok = state.images.filter((x) => x.status === "ready");
  const errCount = state.images.filter((x) => x.status === "error").length;
  state.images = ok;
  if (!state.images.length) {
    setStatusStep("done");
    setProcessing("All images failed. Please try different photos.", 100);
    return;
  }
  if (errCount) alert(`${errCount} image(s) failed to process and were skipped.`);

  setStatusStep("done");
  setProcessing("Ready!", 100);
  showProcessingOverlay(false);

  // default background selection
  if (!state.currentBgId && state.backgrounds[0]) state.currentBgId = state.backgrounds[0].id;
  showScreen("background");
  await renderBackgroundPreview();
  renderBackgroundThumbnails();
  updateBgNavButtons();
}

// ---- Background selection ----
async function loadBackgrounds() {
  const res = await api("/api/backgrounds");
  state.backgrounds = (res.backgrounds || []).map((b) => ({ ...b, thumb_url: apiUrl(b.thumb_url) }));
  if (!state.currentBgId && state.backgrounds[0]) state.currentBgId = state.backgrounds[0].id;
}

function renderBackgroundThumbnails(filterText = "") {
  const container = $("#background-thumbnails");
  if (!container) return;
  container.innerHTML = "";

  const q = (filterText || "").trim().toLowerCase();
  const list = !q
    ? state.backgrounds
    : state.backgrounds.filter((b) => `${b.name} ${b.description}`.toLowerCase().includes(q));

  list.forEach((bg) => {
    const div = document.createElement("div");
    div.className = "thumbnail";
    div.dataset.bgId = bg.id;
    div.innerHTML = `<img src="${apiUrl(bg.thumb_url)}" alt="${bg.name}" loading="lazy"><span>${bg.name}</span>`;
    div.addEventListener("click", async () => {
      state.currentBgId = bg.id;
      saveSettingsForCurrent();
      highlightSelectedBg();
      await renderBackgroundPreview();
      updateBgNavButtons();
    });
    container.appendChild(div);
  });

  highlightSelectedBg();
}

function highlightSelectedBg() {
  $$(".thumbnail").forEach((t) => t.classList.toggle("selected", t.dataset.bgId === state.currentBgId));
}

function updateBgNavButtons() {
  const next = $("#bg-next-btn");
  if (next) next.disabled = !state.currentBgId || !state.images.length;
}

async function renderBackgroundPreview() {
  const canvas = $("#background-canvas");
  if (!canvas || !state.images.length || !state.currentBgId) return;

  const imgId = state.images[state.currentIndex]?.id;
  if (!imgId) return;

  sizeCanvasToParent(canvas, 400, 300);

  const qs = new URLSearchParams();
  qs.set("image_id", imgId);
  qs.set("bg_id", state.currentBgId);
  qs.set("rotate", "0");
  qs.set("scale", "1");
  qs.set("x", "0");
  qs.set("y", "0");
  qs.set("shadow", "true");
  qs.set("snap", "true");
  qs.set("fmt", "png");

  const url = withToken(`/api/render/preview?${qs.toString()}&t=${Date.now()}`);
  const img = await loadImage(url);
  drawImageCover(canvas, img);
}

// ---- Position screen ----
function updateImageNavigation() {
  const nav = $("#image-navigation");
  const prev = $("#prev-image-btn");
  const next = $("#next-image-btn");
  const cur = $("#current-image-number");
  const tot = $("#total-images-number");

  const total = state.images.length;
  if (nav) nav.style.display = total > 1 ? "flex" : "none";
  if (cur) cur.textContent = String(state.currentIndex + 1);
  if (tot) tot.textContent = String(total || 1);
  if (prev) prev.disabled = state.currentIndex <= 0;
  if (next) next.disabled = state.currentIndex >= total - 1;
}

function syncSliders() {
  const rot = $("#rotation-slider");
  const rotD = $("#rotation-display");
  const sc = $("#scale-slider");
  const scD = $("#scale-display");

  if (rot) rot.value = String(state.carRotation);
  if (rotD) rotD.textContent = `${state.carRotation}°`;
  if (sc) sc.value = String(state.carScale);
  if (scD) scD.textContent = `${state.carScale}%`;
}

async function renderPositionPreview() {
  const canvas = $("#position-canvas");
  if (!canvas || !state.images.length || !state.currentBgId) return;
  const imgId = state.images[state.currentIndex]?.id;
  if (!imgId) return;

  sizeCanvasToParent(canvas, 320, 240);

  // Local composition: background thumb + cutout
  const bgSrc = apiUrl(state.backgrounds.find((b) => b.id === state.currentBgId)?.thumb_url || `/api/backgrounds/${state.currentBgId}/thumb.png`);
  const carSrc = withToken(apiUrl(`/api/images/${imgId}/cutout.png`));
  const [bgImg, carImg] = await Promise.all([loadImage(bgSrc), loadImage(carSrc)]);
  drawLocalComposite(canvas, bgImg, carImg);
}

function moveCar(dx, dy) {
  state.carPosition.x += dx;
  state.carPosition.y += dy;
  saveSettingsForCurrent();
  renderPositionPreview();
}

// ---- Download ----
function currentFormat() {
  const active = document.querySelector(".format-btn.active");
  const fmt = active?.dataset?.format || "png";
  return fmt === "jpg" ? "jpg" : "png";
}

async function renderFinalPreview() {
  const canvas = $("#final-canvas");
  if (!canvas || !state.images.length || !state.currentBgId) return;
  const imgId = state.images[state.currentIndex]?.id;
  if (!imgId) return;

  sizeCanvasToParent(canvas, 320, 240);

  // Local preview (instant). Download button still uses server render.
  const bgSrc = apiUrl(state.backgrounds.find((b) => b.id === state.currentBgId)?.thumb_url || `/api/backgrounds/${state.currentBgId}/thumb.png`);
  const carSrc = withToken(apiUrl(`/api/images/${imgId}/cutout.png`));
  const [bgImg, carImg] = await Promise.all([loadImage(bgSrc), loadImage(carSrc)]);
  drawLocalComposite(canvas, bgImg, carImg);
}

function downloadCurrent() {
  const fmt = currentFormat();
  const imgId = state.images[state.currentIndex]?.id;
  if (!imgId || !state.currentBgId) return;
  const qs = new URLSearchParams();
  qs.set("image_id", imgId);
  qs.set("bg_id", state.currentBgId);
  qs.set("rotate", String(state.carRotation));
  qs.set("scale", String(state.carScale / 100));
  qs.set("x", String(state.carPosition.x));
  qs.set("y", String(state.carPosition.y));
  qs.set("shadow", String(!!state.shadow));
  qs.set("snap", "false");
  qs.set("fmt", fmt);
  window.location.href = withToken(apiUrl(`/api/render/download?${qs.toString()}`));
}

async function downloadAllZip() {
  const fmt = currentFormat();
  const items = state.images.map((im, idx) => {
    const s = state.settings[idx] || { x: 0, y: 0, rotate: 0, scale: 100, bgId: state.currentBgId, shadow: true };
    return {
      image_id: im.id,
      bg_id: s.bgId || state.currentBgId,
      rotate: Number(s.rotate || 0),
      scale: Number((s.scale || 100) / 100),
      x: Number(s.x || 0),
      y: Number(s.y || 0),
      shadow: !!s.shadow,
      snap: false,
    };
  });

  const res = await fetch(apiUrl("/api/render/zip"), {
    method: "POST",
    credentials: "omit",
    headers: { "content-type": "application/json", "x-client-token": state.clientToken },
    body: JSON.stringify({ items, fmt }),
  });
  if (!res.ok) throw new Error(await res.text());
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "aucto_processed.zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---- Bind UI ----
function bind() {
  // Help
  $("#help-btn")?.addEventListener("click", () => {
    alert(
      "Aucto.ch — Guide\n\n" +
        "IMPORTANT: Use EXTERIOR pictures only.\n\n" +
        "1) Upload your car photos\n" +
        "2) Wait for background removal\n" +
        "3) Choose a showroom background\n" +
        "4) Adjust position/rotation/scale\n" +
        "5) Download (pay once to remove watermark)\n"
    );
  });

  // Upload button triggers file input
  $("#upload-btn")?.addEventListener("click", (e) => {
    e.preventDefault();
    $("#file-input")?.click();
  });

  $("#file-input")?.addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []).filter((f) => f.type && f.type.startsWith("image/"));
    if (!files.length) return;
    try {
      await startProcessing(files);
    } catch (err) {
      console.error(err);
      alert(`Upload failed: ${err.message}`);
      showScreen("upload");
    } finally {
      e.target.value = "";
    }
  });

  // Drag/drop
  const dz = $("#drop-zone");
  if (dz) {
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", async (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      const files = Array.from(e.dataTransfer.files || []).filter((f) => f.type && f.type.startsWith("image/"));
      if (!files.length) return;
      try {
        await startProcessing(files);
      } catch (err) {
        console.error(err);
        alert(`Upload failed: ${err.message}`);
        showScreen("upload");
      }
    });
  }

  // Paste button
  $("#paste-btn")?.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      if (!navigator.clipboard?.read) {
        alert("Clipboard read not available. Try Ctrl+V.");
        return;
      }
      const items = await navigator.clipboard.read();
      const files = [];
      for (const it of items) {
        for (const type of it.types) {
          if (type.startsWith("image/")) {
            const blob = await it.getType(type);
            files.push(new File([blob], `clipboard.${type.split("/")[1] || "png"}`, { type }));
          }
        }
      }
      if (!files.length) {
        alert("No image found in clipboard.");
        return;
      }
      await startProcessing(files);
    } catch (err) {
      console.warn(err);
      alert("Clipboard access failed. Please upload instead.");
    }
  });

  // Mobile gallery/camera
  $("#gallery-btn")?.addEventListener("click", (e) => {
    e.preventDefault();
    const fi = $("#file-input");
    if (fi) {
      fi.setAttribute("capture", "environment");
      fi.click();
    }
  });

  // Processing back button
  $("#processing-back-btn")?.addEventListener("click", () => {
    state.files = [];
    state.jobId = null;
    state.images = [];
    state.settings = [];
    state.currentIndex = 0;
    showScreen("upload");
  });

  // Background search
  $("#bg-search")?.addEventListener("input", (e) => {
    renderBackgroundThumbnails(e.target.value || "");
  });

  // Background nav
  $("#bg-back-btn")?.addEventListener("click", () => showScreen("processing"));
  $("#bg-next-btn")?.addEventListener("click", async () => {
    loadSettingsForCurrent();
    syncSliders();
    updateImageNavigation();
    showScreen("position");
    await renderPositionPreview();
  });

  // Position controls
  $("#move-left")?.addEventListener("click", () => moveCar(-20, 0));
  $("#move-right")?.addEventListener("click", () => moveCar(20, 0));
  $("#move-up")?.addEventListener("click", () => moveCar(0, -20));
  $("#move-down")?.addEventListener("click", () => moveCar(0, 20));

  $("#rotation-slider")?.addEventListener("input", (e) => {
    state.carRotation = Number(e.target.value || 0);
    $("#rotation-display").textContent = `${state.carRotation}°`;
    saveSettingsForCurrent();
    renderPositionPreview();
  });

  $("#scale-slider")?.addEventListener("input", (e) => {
    state.carScale = Number(e.target.value || 100);
    $("#scale-display").textContent = `${state.carScale}%`;
    saveSettingsForCurrent();
    renderPositionPreview();
  });

  $("#reset-position-btn")?.addEventListener("click", () => {
    state.carPosition = { x: 0, y: 0 };
    state.carRotation = 0;
    state.carScale = 100;
    state.shadow = true;
    saveSettingsForCurrent();
    syncSliders();
    renderPositionPreview();
  });

  $("#position-back-btn")?.addEventListener("click", async () => {
    showScreen("background");
    await renderBackgroundPreview();
  });

  $("#position-next-btn")?.addEventListener("click", async () => {
    showScreen("download");
    setWatermarkNotice();
    await renderFinalPreview();
  });

  // image navigation
  $("#prev-image-btn")?.addEventListener("click", async () => {
    if (state.currentIndex <= 0) return;
    saveSettingsForCurrent();
    state.currentIndex -= 1;
    loadSettingsForCurrent();
    syncSliders();
    updateImageNavigation();
    await renderPositionPreview();
  });
  $("#next-image-btn")?.addEventListener("click", async () => {
    if (state.currentIndex >= state.images.length - 1) return;
    saveSettingsForCurrent();
    state.currentIndex += 1;
    loadSettingsForCurrent();
    syncSliders();
    updateImageNavigation();
    await renderPositionPreview();
  });

  // Download
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".format-btn");
    if (!btn) return;
    $$(".format-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
  });

  $("#download-btn")?.addEventListener("click", downloadCurrent);
  $("#batch-download-btn")?.addEventListener("click", async () => {
    try {
      await downloadAllZip();
    } catch (e) {
      alert(`Batch download failed: ${e.message}`);
    }
  });

  $("#start-over-btn")?.addEventListener("click", () => {
    state.files = [];
    state.jobId = null;
    state.images = [];
    state.settings = [];
    state.currentIndex = 0;
    state.currentBgId = state.backgrounds[0]?.id || null;
    showScreen("upload");
  });

  $("#remove-watermark-btn")?.addEventListener("click", async () => {
    if (state.paid) return;
    if (!state.stripeConfigured) {
      alert("Payments are not configured yet.");
      return;
    }
    await startCheckout();
  });

  // resize re-render
  window.addEventListener("resize", () => {
    if (screens.background?.classList.contains("active")) renderBackgroundPreview();
    if (screens.position?.classList.contains("active")) renderPositionPreview();
    if (screens.download?.classList.contains("active")) renderFinalPreview();
  });
}

async function boot() {
  bind();
  await initClient();
  await loadBackgrounds();
  await loadMe();
  await checkCheckoutReturn();
  showScreen("upload");
}

boot().catch((e) => {
  console.error(e);
  alert(`Failed to start app: ${e.message}`);
});

