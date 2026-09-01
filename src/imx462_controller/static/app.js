"use strict";

const state = {
  cameras: [],
  selectedId: null,
  defaultMode: null,
  cameraDefaultMode: null,
  caps: null,
  recording: false,
  singleMode: false,
  capturing: false,
  ws: null,
};

const MAX_NATIVE_EXPOSURE_US = 115000000;
const SINGLE_MODE_THRESHOLD_US = 2000000; // >2s forces single-frame mode
const MIN_FRAME_US = 16666; // 1/60s

const el = {
  cameraSelect: document.getElementById("camera-select"),
  modeSelect: document.getElementById("mode-select"),
  photoBtn: document.getElementById("photo-btn"),
  recordBtn: document.getElementById("record-btn"),
  recordLabel: document.getElementById("record-label"),
  stream: document.getElementById("stream"),
  viewport: document.getElementById("viewport"),
  placeholder: document.getElementById("placeholder"),
  wsPill: document.getElementById("ws-pill"),
  statUptime: document.getElementById("stat-uptime"),
  statRecording: document.getElementById("stat-recording"),
  statClients: document.getElementById("stat-clients"),
  statIso: document.getElementById("stat-iso"),
  statShutter: document.getElementById("stat-shutter"),
  aeToggle: document.getElementById("ae-toggle"),
  shutter: document.getElementById("shutter"),
  flicker: document.getElementById("flicker"),
  iso: document.getElementById("iso"),
  fullscreenBtn: document.getElementById("fullscreen-btn"),
  singleBtn: document.getElementById("single-btn"),
  captureBtn: document.getElementById("capture-btn"),
  awbToggle: document.getElementById("awb-toggle"),
  wbTemp: document.getElementById("wb-temp"),
  hflipToggle: document.getElementById("hflip-toggle"),
  vflipToggle: document.getElementById("vflip-toggle"),
  brightness: document.getElementById("brightness"),
  contrast: document.getElementById("contrast"),
  saturation: document.getElementById("saturation"),
  assetsBody: document.getElementById("assets-body"),
  assetsEmpty: document.getElementById("assets-empty"),
};

const SHUTTER_LISTS = {
  off: [
    ["1/600", 1667],
    ["1/500", 2000],
    ["1/400", 2500],
    ["1/320", 3125],
    ["1/250", 4000],
    ["1/200", 5000],
    ["1/160", 6250],
    ["1/125", 8000],
    ["1/100", 10000],
    ["1/80", 12500],
    ["1/60", 16667],
    ["1/50", 20000],
    ["1/40", 25000],
    ["1/30", 33333],
    ["1/25", 40000],
    ["1/20", 50000],
    ["1/15", 66667],
    ["1/13", 76923],
    ["1/10", 100000],
    ["1/8", 125000],
    ["1/6", 166667],
    ["1/5", 200000],
    ["1/4", 250000],
    ["1/3", 333333],
    ["1/2.5", 400000],
    ["1/2", 500000],
    ["0.8s", 800000],
    ["1s", 1000000],
    ["2s", 2000000],
    ["5s", 5000000],
    ["10s", 10000000],
    ["15s", 15000000],
    ["30s", 30000000],
  ],
  50: [
    ["1/100", 10000],
    ["1/50", 20000],
    ["1/25", 40000],
    ["1/20", 50000],
    ["1/10", 100000],
    ["1/5", 200000],
    ["1/2", 500000],
    ["1s", 1000000],
    ["2s", 2000000],
    ["5s", 5000000],
    ["10s", 10000000],
    ["15s", 15000000],
    ["30s", 30000000],
  ],
  60: [
    ["1/120", 8333],
    ["1/60", 16667],
    ["1/30", 33333],
    ["1/15", 66667],
    ["1/8", 125000],
    ["1/4", 250000],
    ["1/2", 500000],
    ["1s", 1000000],
    ["2s", 2000000],
    ["5s", 5000000],
    ["10s", 10000000],
    ["15s", 15000000],
    ["30s", 30000000],
  ],
};

const ISO_STEPS = [
  [100, 1.0],
  [125, 1.25],
  [160, 1.6],
  [200, 2.0],
  [250, 2.5],
  [320, 3.2],
  [400, 4.0],
  [500, 5.0],
  [640, 6.4],
  [800, 8.0],
  [1000, 10.0],
  [1250, 12.5],
  [1600, 16.0],
  [2000, 20.0],
  [2500, 25.0],
  [3200, 32.0],
];

function currentShutterList() {
  return el.flicker.value in SHUTTER_LISTS ? SHUTTER_LISTS[el.flicker.value] : SHUTTER_LISTS.off;
}

function capsBounds() {
  const c = state.caps || {};
  return {
    minUs: c.exposure_min_us != null ? c.exposure_min_us : 0,
    maxUs: c.exposure_max_us != null ? c.exposure_max_us : MAX_NATIVE_EXPOSURE_US,
    gainMin: c.gain_min != null ? c.gain_min : 1.0,
    gainMax: c.gain_max != null ? c.gain_max : 31.6,
  };
}

function populateShutter() {
  const list = currentShutterList();
  const { minUs, maxUs } = capsBounds();
  const filtered = list.filter(([, us]) => us >= minUs && us <= maxUs);
  const options = filtered.length ? filtered : list;
  const prev = el.shutter.value;
  el.shutter.innerHTML = "";
  for (const [label, us] of options) {
    const opt = document.createElement("option");
    opt.value = String(us);
    opt.textContent = label;
    el.shutter.appendChild(opt);
  }
  el.shutter.value = options.some(([, us]) => String(us) === prev) ? prev : String(options[0][1]);
}

function populateIso() {
  const { gainMin, gainMax } = capsBounds();
  const steps = ISO_STEPS.filter(([, gain]) => gain >= gainMin - 1e-9 && gain <= gainMax + 0.5);
  const options = steps.length ? steps : ISO_STEPS;
  const prev = el.iso.value;
  el.iso.innerHTML = "";
  for (const [iso] of options) {
    const opt = document.createElement("option");
    opt.value = String(iso);
    opt.textContent = String(iso);
    el.iso.appendChild(opt);
  }
  el.iso.value = options.some(([iso]) => String(iso) === prev) ? prev : String(options[0][0]);
}

function gainForIso(iso) {
  const entry = ISO_STEPS.find(([i]) => i === iso);
  return entry ? entry[1] : null;
}

function isoForGain(gain) {
  let best = ISO_STEPS[0];
  let bestDiff = Infinity;
  for (const [iso, g] of ISO_STEPS) {
    const d = Math.abs(g - gain);
    if (d < bestDiff) {
      bestDiff = d;
      best = [iso, g];
    }
  }
  return best[0];
}

function nearestShutterUs(us) {
  const list = currentShutterList();
  let best = null;
  let bestDiff = Infinity;
  for (const [, u] of list) {
    const d = Math.abs(u - us);
    if (d < bestDiff) {
      bestDiff = d;
      best = u;
    }
  }
  return best;
}

function flickerPeriodUs(value) {
  if (value === "50") return 10000;
  if (value === "60") return 8333;
  return 0;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

function bindSliderOutput(inputId, outputId) {
  const input = document.getElementById(inputId);
  const output = document.getElementById(outputId);
  input.addEventListener("input", () => (output.textContent = input.value));
}

bindSliderOutput("brightness", "brightness-out");
bindSliderOutput("contrast", "contrast-out");
bindSliderOutput("saturation", "saturation-out");

const wbInput = document.getElementById("wb-temp");
const wbOutput = document.getElementById("wb-out");
wbInput.addEventListener("input", () => (wbOutput.textContent = `${wbInput.value}K`));

async function loadCameras() {
  const data = await api("/api/cameras");
  state.cameras = data.cameras;
  state.defaultMode = data.default_mode || null;
  el.cameraSelect.innerHTML = "";
  for (const cam of state.cameras) {
    const opt = document.createElement("option");
    opt.value = cam.id;
    opt.textContent = cam.name + (cam.model ? ` (${cam.model})` : "");
    el.cameraSelect.appendChild(opt);
  }
  if (state.cameras.length) selectCamera(state.cameras[0].id);
}

function populateModes(camera) {
  el.modeSelect.innerHTML = "";
  for (const m of camera.modes) {
    const opt = document.createElement("option");
    opt.value = JSON.stringify(m);
    opt.textContent = `${m.width}x${m.height} RAW${m.bit_depth} @${m.framerate}fps`;
    el.modeSelect.appendChild(opt);
  }
}

function selectDefaultMode() {
  const target = JSON.stringify(state.cameraDefaultMode || state.defaultMode);
  if (!target || target === "null") return;
  for (const opt of el.modeSelect.options) {
    if (opt.value === target) {
      el.modeSelect.value = target;
      return;
    }
  }
}

function selectCamera(id) {
  state.selectedId = id;
  const camera = state.cameras.find((c) => c.id === id);
  if (!camera) return;
  state.caps = camera.capabilities || null;
  state.cameraDefaultMode = camera.default_mode || state.defaultMode;
  populateModes(camera);
  selectDefaultMode();
  populateShutter();
  populateIso();
  setStreamSrc(`/api/cameras/${id}/stream?t=${Date.now()}`);
  applyMode();
  refreshCapabilities(id);
}

async function refreshCapabilities(id) {
  try {
    const caps = await api(`/api/cameras/${id}/capabilities`);
    state.caps = caps;
    const camera = state.cameras.find((c) => c.id === id);
    if (camera) {
      camera.capabilities = caps;
      camera.modes = caps.modes;
    }
    if (state.selectedId === id && camera) {
      populateModes(camera);
      selectDefaultMode();
      populateShutter();
      populateIso();
    }
  } catch (err) {
    // Fall back to the static per-model capabilities already applied.
    console.warn("Capabilities refresh failed; using static per-model capabilities:", err);
  }
}

function setStreamSrc(url) {
  el.stream.src = url;
  el.viewport.classList.add("live");
}

function clearStream() {
  el.stream.removeAttribute("src");
  el.viewport.classList.remove("live");
}

async function applyMode() {
  if (state.selectedId == null || !el.modeSelect.value) return;
  const mode = JSON.parse(el.modeSelect.value);
  try {
    await api(`/api/cameras/${state.selectedId}/mode`, {
      method: "PUT",
      body: JSON.stringify(mode),
    });
  } catch (err) {
    toast(`Mode error: ${err.message}`, true);
  }
}

async function capturePhoto() {
  if (state.selectedId == null) return;
  try {
    await api(`/api/cameras/${state.selectedId}/photo`, { method: "POST" });
    loadAssets();
  } catch (err) {
    console.error("Photo error:", err);
  }
}

async function toggleRecording() {
  if (state.selectedId == null) return;
  const action = state.recording ? "stop" : "start";
  try {
    const res = await api(`/api/cameras/${state.selectedId}/recording/${action}`, {
      method: "POST",
    });
    state.recording = res.recording;
    updateRecordButton();
    if (!state.recording) loadAssets();
  } catch (err) {
    console.error("Recording error:", err);
  }
}

function updateRecordButton() {
  el.recordLabel.textContent = state.recording ? "Stop" : "Record";
  el.recordBtn.classList.toggle("btn-recording", state.recording);
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
  state.ws = ws;
  ws.onopen = () => {
    el.wsPill.dataset.state = "on";
    el.wsPill.textContent = "online";
  };
  ws.onmessage = (event) => {
    renderStatus(JSON.parse(event.data));
  };
  ws.onclose = () => {
    el.wsPill.dataset.state = "off";
    el.wsPill.textContent = "offline";
    setTimeout(connectWs, 2000);
  };
}

function renderCameraStats(current) {
  state.recording = current.recording;
  updateRecordButton();
  el.statRecording.textContent = current.recording ? "yes" : "no";
}

function renderLiveSettings(settings) {
  if (settings.analogue_gain > 0) {
    el.statIso.textContent = String(Math.round(settings.analogue_gain * 100));
    if (el.aeToggle.checked) el.iso.value = String(isoForGain(settings.analogue_gain));
  }
  if (settings.exposure_time > 0) {
    el.statShutter.textContent = formatShutterUs(settings.exposure_time);
    if (el.aeToggle.checked) {
      const nearest = nearestShutterUs(settings.exposure_time);
      if (nearest != null) el.shutter.value = String(nearest);
    }
  }
}

function renderStatus(msg) {
  if (msg.uptime_seconds != null) {
    el.statUptime.textContent = `${msg.uptime_seconds}s`;
  }
  const cameras = msg.cameras || [];
  const current = cameras.find((c) => c.id === Number(state.selectedId));
  if (current) renderCameraStats(current);
  el.statClients.textContent = msg.clients?.length ? msg.clients.join(", ") : "—";

  const settings = msg.settings?.[String(state.selectedId)];
  if (settings) renderLiveSettings(settings);
}

function formatShutterUs(us) {
  if (us >= 1000000) return `${(us / 1000000).toFixed(us % 1000000 === 0 ? 0 : 1)}s`;
  const denom = Math.round(1000000 / us);
  return `1/${denom}`;
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function loadAssets() {
  try {
    const data = await api("/api/assets");
    renderAssets(data.assets);
  } catch (err) {
    console.error("Assets error:", err);
  }
}

function renderAssets(assets) {
  el.assetsBody.innerHTML = "";
  el.assetsEmpty.style.display = assets.length ? "none" : "block";
  for (const a of assets) {
    const tr = document.createElement("tr");

    const name = document.createElement("td");
    name.className = "name";
    name.textContent = a.filename;

    const kind = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = a.kind;
    kind.appendChild(badge);

    const size = document.createElement("td");
    size.textContent = humanSize(a.size);

    const actions = document.createElement("td");
    actions.className = "row-actions";
    const dl = document.createElement("a");
    dl.className = "icon-btn download";
    dl.textContent = "Download";
    dl.href = `/api/assets/${encodeURIComponent(a.filename)}`;
    dl.setAttribute("download", "");
    const del = document.createElement("button");
    del.className = "icon-btn danger";
    del.textContent = "Delete";
    del.addEventListener("click", () => deleteAsset(del, a.filename));
    actions.append(dl, del);

    tr.append(name, kind, size, actions);
    el.assetsBody.appendChild(tr);
  }
}

let armedDelete = null;

async function deleteAsset(button, filename) {
  if (armedDelete !== filename) {
    armedDelete = filename;
    button.textContent = "Sure?";
    setTimeout(() => {
      if (armedDelete === filename) {
        armedDelete = null;
        button.textContent = "Delete";
      }
    }, 3000);
    return;
  }
  armedDelete = null;
  try {
    await api(`/api/assets/${encodeURIComponent(filename)}`, { method: "DELETE" });
    toast(`Deleted ${filename}`);
    loadAssets();
  } catch (err) {
    toast(`Delete failed: ${err.message}`, true);
    loadAssets();
  }
}

function toast(message, isError = false) {
  let box = document.getElementById("toast");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast";
    document.body.appendChild(box);
  }
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.classList.add("show");
  clearTimeout(box._t);
  box._t = setTimeout(() => box.classList.remove("show"), 3000);
}

function updateAeState() {
  const ae = el.aeToggle.checked;
  el.shutter.disabled = ae;
  el.iso.disabled = ae;
}

function updateAwbState() {
  const awb = el.awbToggle.checked;
  el.wbTemp.disabled = awb;
}

async function applyControls() {
  if (state.selectedId == null) return;
  const ae = el.aeToggle.checked;
  const awb = el.awbToggle.checked;
  const controls = {
    AeEnable: ae,
    AwbEnable: awb,
    AeFlickerPeriod: flickerPeriodUs(el.flicker.value),
    Brightness: Number.parseFloat(el.brightness.value) || 0,
    Contrast: Number.parseFloat(el.contrast.value) || 1.0,
    Saturation: Number.parseFloat(el.saturation.value) || 1.0,
  };
  if (!ae) {
    const shutterUs = Number.parseInt(el.shutter.value, 10);
    if (!Number.isNaN(shutterUs) && shutterUs > 0) {
      const nativeUs = Math.min(shutterUs, capsBounds().maxUs);
      const frameUs = Math.max(nativeUs, MIN_FRAME_US);
      controls.ExposureTime = nativeUs;
      controls.FrameDurationLimits = [frameUs, frameUs];
    }
    controls.AnalogueGain = gainForIso(Number.parseInt(el.iso.value, 10)) ?? 1.0;
  } else {
    controls.FrameDurationLimits = [MIN_FRAME_US, MIN_FRAME_US];
  }
  if (!awb) {
    const wb = Number.parseInt(el.wbTemp.value, 10);
    if (!Number.isNaN(wb)) controls.ColourTemperature = wb;
  }
  try {
    await api(`/api/cameras/${state.selectedId}/controls`, {
      method: "PUT",
      body: JSON.stringify({ controls }),
    });
  } catch (err) {
    toast(`Controls error: ${err.message}`, true);
  }
  syncSingleMode();
}

async function applyFlip() {
  if (state.selectedId == null) return;
  try {
    await api(`/api/cameras/${state.selectedId}/flip`, {
      method: "PUT",
      body: JSON.stringify({ hflip: el.hflipToggle.checked, vflip: el.vflipToggle.checked }),
    });
  } catch (err) {
    toast(`Flip error: ${err.message}`, true);
  }
}

function shouldSingleMode() {
  if (el.aeToggle.checked) return false;
  const shutterUs = Number.parseInt(el.shutter.value, 10);
  return !Number.isNaN(shutterUs) && shutterUs > SINGLE_MODE_THRESHOLD_US;
}

function syncSingleMode() {
  if (shouldSingleMode() !== state.singleMode) {
    setSingleMode(shouldSingleMode());
  }
}

async function setSingleMode(on) {
  state.singleMode = on;
  updateSingleUI();
  if (state.selectedId == null) return;
  try {
    await api(`/api/cameras/${state.selectedId}/stream-mode`, {
      method: "PUT",
      body: JSON.stringify({ mode: on ? "single" : "continuous" }),
    });
  } catch (err) {
    toast(`Stream mode error: ${err.message}`, true);
  }
}

function updateSingleUI() {
  el.singleBtn.classList.toggle("active", state.singleMode);
  el.captureBtn.hidden = !state.singleMode;
  const placeholderText = el.placeholder.querySelector("p");
  if (state.singleMode) {
    clearStream();
    if (placeholderText) placeholderText.textContent = "Single-frame mode — capture a frame";
  } else {
    if (state.selectedId != null) setStreamSrc(`/api/cameras/${state.selectedId}/stream?t=${Date.now()}`);
    if (placeholderText) placeholderText.textContent = "Select a camera to start live view";
  }
}

async function captureFrame() {
  if (state.selectedId == null || state.capturing) return;
  const shutterUs = Number.parseInt(el.shutter.value, 10);
  const exposureUs = Number.isNaN(shutterUs) || shutterUs <= 0 ? MIN_FRAME_US : shutterUs;
  const gain = gainForIso(Number.parseInt(el.iso.value, 10)) ?? 1.0;
  state.capturing = true;
  el.captureBtn.disabled = true;
  el.captureBtn.textContent = "Capturing…";
  try {
    const res = await api(`/api/cameras/${state.selectedId}/snapshot`, {
      method: "POST",
      body: JSON.stringify({ exposure_us: exposureUs, gain }),
    });
    const durationStr = exposureUs >= 1000000 ? `${(exposureUs / 1000000).toFixed(0)}s` : "frame";
    setStreamSrc(`${res.url}?t=${Date.now()}`);
    toast(`Captured ${durationStr}`);
    loadAssets();
  } catch (err) {
    toast(`Capture failed: ${err.message}`, true);
  } finally {
    state.capturing = false;
    el.captureBtn.disabled = false;
    el.captureBtn.textContent = "Capture frame";
  }
}

el.cameraSelect.addEventListener("change", (e) => selectCamera(Number(e.target.value)));
el.modeSelect.addEventListener("change", applyMode);
el.photoBtn.addEventListener("click", capturePhoto);
el.recordBtn.addEventListener("click", toggleRecording);
el.singleBtn.addEventListener("click", () => {
  if (state.singleMode) {
    // Exiting single-frame mode: restore auto exposure so the live feed
    // resumes at a fast frame rate. applyControls' syncSingleMode() then
    // switches the stream mode back to continuous.
    el.aeToggle.checked = true;
    updateAeState();
    applyControls();
  } else {
    setSingleMode(true);
  }
});
el.captureBtn.addEventListener("click", captureFrame);

el.aeToggle.addEventListener("change", () => {
  updateAeState();
  applyControls();
});
el.awbToggle.addEventListener("change", () => {
  updateAwbState();
  applyControls();
});
el.hflipToggle.addEventListener("change", applyFlip);
el.vflipToggle.addEventListener("change", applyFlip);
el.flicker.addEventListener("change", () => {
  populateShutter();
  applyControls();
});
for (const s of [el.shutter, el.iso, el.wbTemp, el.brightness, el.contrast, el.saturation]) {
  s.addEventListener("change", applyControls);
}

el.fullscreenBtn.addEventListener("click", () => {
  if (document.fullscreenElement) {
    document.exitFullscreen();
  } else {
    el.viewport.requestFullscreen();
  }
});

populateShutter();
populateIso();
updateAeState();
updateAwbState();
updateSingleUI();
try {
  await loadCameras();
} catch (err) {
  console.error("Failed to load cameras:", err);
}
await loadAssets();
connectWs();
