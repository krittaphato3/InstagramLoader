// Instagram Media Downloader — frontend logic.
// Talks to the FastAPI backend (/api/...) and drives the grid, filters,
// selection, download progress, and toasts.
"use strict";

const state = {
  items: [],       // raw items from /api/resolve
  selected: new Set(), // ids currently selected
  filter: "all",   // active filter tab
  username: null,
  fetching: false,
  jobId: null,
};

const els = {
  urlInput: document.getElementById("urlInput"),
  fetchBtn: document.getElementById("fetchBtn"),
  statusArea: document.getElementById("statusArea"),
  toolbar: document.getElementById("toolbar"),
  grid: document.getElementById("grid"),
  downloadBtn: document.getElementById("downloadBtn"),
  selectedCount: document.getElementById("selectedCount"),
  progressOverlay: document.getElementById("progressOverlay"),
  progressBar: document.getElementById("progressBar"),
  progressText: document.getElementById("progressText"),
};

/* ---------------- Toasts ---------------- */
function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

/* ---------------- State helpers ---------------- */
function setStatus(type, html) {
  els.statusArea.innerHTML = `<div class="status ${type}">${html}</div>`;
}
function clearStatus() { els.statusArea.innerHTML = ""; }

function visibleItems() {
  if (state.filter === "all") return state.items;
  return state.items.filter((it) => it.type === state.filter);
}
function filteredIds() { return new Set(visibleItems().map((it) => it.id)); }
function updateCount() {
  els.selectedCount.textContent = `${state.selected.size} item${state.selected.size === 1 ? "" : "s"} selected`;
}
function updateDownloadBtn() {
  els.downloadBtn.disabled = state.selected.size === 0;
}

/* ---------------- Render ---------------- */
function renderGrid() {
  const items = visibleItems();
  els.grid.hidden = items.length === 0;
  if (items.length === 0) {
    els.grid.innerHTML = "";
    if (state.items.length) setStatus("info", "No media match this filter.");
    return;
  }
  els.grid.innerHTML = "";
  for (const it of items) {
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.id = it.id;

    const thumb = document.createElement("img");
    thumb.className = "thumb";
    thumb.loading = "lazy";
    if (it.thumbnail_url) thumb.src = it.thumbnail_url;
    else thumb.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><rect width='100%25' height='100%25' fill='%23ddd'/></svg>";

    const badge = document.createElement("span");
    badge.className = `badge badge-${it.type}`;
    badge.textContent = it.type.charAt(0).toUpperCase() + it.type.slice(1);

    const caption = document.createElement("div");
    caption.className = "caption";
    caption.textContent = it.caption || (it.timestamp || "No caption");

    const check = document.createElement("label");
    check.className = "select-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.selected.has(it.id);
    cb.addEventListener("change", () => toggleSelect(it.id, cb.checked));
    check.appendChild(cb);

    card.append(thumb, badge, caption, check);
    els.grid.appendChild(card);
  }
}

function toggleSelect(id, checked) {
  if (checked) state.selected.add(id);
  else state.selected.delete(id);
  updateCount();
  updateDownloadBtn();
}

/* ---------------- Selection helpers ---------------- */
function selectType(type) {
  const target = new Set(
    state.items.filter((it) => type === "all" || it.type === type).map((it) => it.id)
  );
  state.selected = target;
  updateCount();
  updateDownloadBtn();
  renderGrid();
}

/* ---------------- Filters ---------------- */
function setFilter(filter) {
  state.filter = filter;
  document.querySelectorAll(".chip").forEach((c) => {
    c.classList.toggle("is-active", c.dataset.filter === filter);
  });
  renderGrid();
}

/* ---------------- Fetch ---------------- */
async function fetchMedia() {
  const input = els.urlInput.value.trim();
  if (!input) { toast("Paste an Instagram link or username first.", "error"); return; }
  if (state.fetching) return;

  state.fetching = true;
  els.fetchBtn.disabled = true;
  clearStatus();
  setStatus("loading", `<span class="spinner"></span>Fetching media…`);

  try {
    const resp = await fetch("/api/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Could not fetch media.");

    state.items = data.items || [];
    state.username = data.username || null;
    state.selected = new Set();
    state.filter = "all";
    document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("is-active", c.dataset.filter === "all"));

    clearStatus();
    els.toolbar.hidden = state.items.length === 0;
    if (state.items.length === 0) {
      setStatus("info", "No public media found for this input.");
    }
    updateCount();
    updateDownloadBtn();
    renderGrid();
  } catch (err) {
    setStatus("error", friendly(err.message));
    els.grid.hidden = true;
    els.toolbar.hidden = true;
  } finally {
    state.fetching = false;
    els.fetchBtn.disabled = false;
  }
}

function friendly(msg) {
  if (/denied|blocked/.test(msg)) return "This content appears to be private or unavailable.";
  if (/login|logged in/i.test(msg)) return "Instagram requires login to view this content.";
  if (/rate|too many/i.test(msg)) return "Too many requests. Please wait a moment and try again.";
  if (/timed? ?out|network/i.test(msg)) return "Could not reach Instagram. Please try again later.";
  if (/deleted|not found/i.test(msg)) return "This post could not be found. It may have been deleted.";
  return msg || "Something went wrong.";
}

/* ---------------- Download ---------------- */
async function startDownload() {
  const chosen = state.items.filter((it) => state.selected.has(it.id));
  if (chosen.length === 0) return;

  els.progressOverlay.hidden = false;
  els.progressBar.value = 0;
  els.progressText.textContent = "Starting download…";

  try {
    const resp = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: chosen.map(stripForDownload), username: state.username }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Could not start download.");

    const jobId = data.job_id;
    await pollJob(jobId);
  } catch (err) {
    els.progressOverlay.hidden = true;
    toast("Could not start download: " + friendly(err.message), "error");
  }
}

function stripForDownload(it) {
  const { id, type, media_url, source_url, caption, timestamp } = it;
  return { id, type, media_url, source_url, caption, timestamp };
}

async function pollJob(jobId) {
  while (true) {
    await new Promise((r) => setTimeout(r, 800));
    const resp = await fetch(`/api/status/${jobId}`);
    const data = await resp.json();
    if (!resp.ok) { els.progressOverlay.hidden = true; toast(friendly(data.detail), "error"); return; }

    els.progressBar.value = data.progress || 0;
    els.progressText.textContent =
      data.status === "completed"
        ? "Completed. Preparing ZIP…"
        : data.status === "failed"
        ? "Download failed."
        : `Downloading… ${data.completed}/${data.total} done${data.failed ? `, ${data.failed} failed` : ""}`;

    if (data.status === "completed") {
      els.progressOverlay.hidden = true;
      toast(`Success! ${data.completed} item${data.completed === 1 ? "" : "s"} downloaded${data.failed ? `, ${data.failed} failed` : ""}.`, "success");
      if (data.zip_url) {
        window.location.href = data.zip_url;
        toast("ZIP download started.", "success");
      }
      return;
    }
    if (data.status === "failed") {
      els.progressOverlay.hidden = true;
      toast("Some items failed to download. Check the report for details.", "error");
      return;
    }
  }
}

/* ---------------- Dark mode ---------------- */
function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark") applyTheme(true);
  document.getElementById("darkToggle").checked = saved === "dark";
  document.getElementById("darkToggle").addEventListener("change", (e) => applyTheme(e.target.checked));
}
function applyTheme(dark) {
  document.documentElement.dataset.theme = dark ? "dark" : "";
  localStorage.setItem("theme", dark ? "dark" : "");
}

/* ---------------- Wire up ---------------- */
els.fetchBtn.addEventListener("click", fetchMedia);
els.urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") fetchMedia(); });
els.downloadBtn.addEventListener("click", startDownload);

document.getElementById("selectAll").addEventListener("click", () => { state.selected = filteredIds(); updateCount(); updateDownloadBtn(); renderGrid(); });
document.getElementById("deselectAll").addEventListener("click", () => { state.selected = new Set(); updateCount(); updateDownloadBtn(); renderGrid(); });
document.getElementById("selectPosts").addEventListener("click", () => selectType("post"));
document.getElementById("selectReels").addEventListener("click", () => selectType("reel"));
document.getElementById("selectStories").addEventListener("click", () => selectType("story"));
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => setFilter(c.dataset.filter)));

initTheme();
updateCount();
updateDownloadBtn();