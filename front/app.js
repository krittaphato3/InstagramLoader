// Instagram Media Downloader — Instagram-style frontend.
// Search bar, profile page, post/reel/story viewers, multi-select, bulk ZIP,
// and per-item single download.
"use strict";

const state = {
  items: [],
  stories: [],
  selected: new Set(),
  tab: "all",
  username: null,
  profile: null,
  profilePic: null,
};

const els = {
  searchInput: document.getElementById("searchInput"),
  searchBtn: document.getElementById("searchBtn"),
  themeBtn: document.getElementById("themeBtn"),
  statusArea: document.getElementById("statusArea"),
  home: document.getElementById("home"),
  quickForm: document.getElementById("quickForm"),
  homeInput: document.getElementById("homeInput"),
  profileView: document.getElementById("profileView"),
  profileAvatar: document.getElementById("profileAvatar"),
  profileUsername: document.getElementById("profileUsername"),
  statPosts: document.getElementById("statPosts"),
  statFollowers: document.getElementById("statFollowers"),
  statFollowing: document.getElementById("statFollowing"),
  profileFullName: document.getElementById("profileFullName"),
  profileBio: document.getElementById("profileBio"),
  selectAllCb: document.getElementById("selectAllCb"),
  downloadSelectedBtn: document.getElementById("downloadSelectedBtn"),
  selectedCount: document.getElementById("selectedCount"),
  grid: document.getElementById("grid"),
  modal: document.getElementById("modal"),
  modalClose: document.getElementById("modalClose"),
  modalMedia: document.getElementById("modalMedia"),
  modalInfo: document.getElementById("modalInfo"),
  modalDownload: document.getElementById("modalDownload"),
  progressOverlay: document.getElementById("progressOverlay"),
  progressBar: document.getElementById("progressBar"),
  progressText: document.getElementById("progressText"),
  brand: document.getElementById("brand"),
};
const modalState = { item: null, items: null, idx: 0 };

/* ---------------- Toasts ---------------- */
function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

/* ---------------- Status ---------------- */
function setStatus(type, html) {
  els.statusArea.innerHTML = `<div class="status ${type}">${html}</div>`;
}
function clearStatus() { els.statusArea.innerHTML = ""; }
function withSpinner(msg) { return `<span class="spinner"></span>${msg}`; }

/* ---------------- Theme ---------------- */
function initTheme() {
  const saved = localStorage.getItem("theme") || "light";
  if (saved === "dark") document.documentElement.dataset.theme = "dark";
  els.themeBtn.textContent = saved === "dark" ? "☀️" : "🌙";
}
els.themeBtn.addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme !== "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "";
  localStorage.setItem("theme", dark ? "dark" : "");
  els.themeBtn.textContent = dark ? "☀️" : "🌙";
});

/* ---------------- Fetch media ---------------- */
async function fetchMedia(raw) {
  const input = (raw ?? els.searchInput.value ?? "").trim();
  if (!input) return;
  clearStatus();
  setStatus("info", withSpinner("Loading…"));
  try {
    const resp = await fetch("/api/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Could not fetch");
    applyResolve(data);
    clearStatus();
  } catch (err) {
    clearStatus();
    setStatus("error", friendly(err.message));
    els.profileView.hidden = true;
    els.grid.hidden = true;
  }
}

function applyResolve(data) {
  state.items = data.items || [];
  state.stories = data.stories || [];
  state.username = data.username;
  state.profile = data.profile || null;
  state.selected = new Set();
  state.tab = "all";

  // Profile header
  els.profileView.hidden = false;
  const p = data.profile;
  if (p) {
    els.profileAvatar.src = (p.profile_pic_url ? prox(p.profile_pic_url) : "");
    els.profileUsername.textContent = p.username || state.username || "";
    els.statPosts.textContent = fmt(p.post_count);
    els.statFollowers.textContent = fmt(p.followers);
    els.statFollowing.textContent = fmt(p.following);
    els.profileFullName.textContent = p.full_name || "";
    els.profileBio.textContent = p.bio || "";
  } else {
    els.statPosts.textContent = String(data.items.length);
    els.statFollowers.textContent = "—";
    els.statFollowing.textContent = "—";
    els.profileUsername.textContent = state.username || "Unknown";
  }

  // Show story notice if login required
  if (data.stories_status === "login_required") {
    setStatus("info", "Stories require login to view — posts & reels still available.");
  }

  // Reset tabs visible
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === "all"));
  document.getElementById("home").hidden = true;
  updateTabCounts();
  renderGrid();
  updateSelectionUI();
}

function fmt(n) {
  if (n == null) return "0";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

// Instagram's CDN sends Cross-Origin-Resource-Policy: same-origin, which makes
// the browser block direct <img>/<video> loading (NotSameOrigin). Route all
// media through our backend proxy so it renders in the page.
function prox(url) {
  if (!url) return "";
  if (url.startsWith("/api/proxy")) return url;
  return `/api/proxy?url=${encodeURIComponent(url)}`;
}

/* ---------------- Tab filtering ---------------- */
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("is-active", x === t));
    state.tab = t.dataset.tab;
    renderGrid();
    selCheckboxSync();
  })
);

function visibleItems() {
  const all = [...state.items, ...state.stories];
  return state.tab === "all" ? all : all.filter((i) => i.type === state.tab);
}
function updateTabCounts() {
  document.querySelectorAll(".tab").forEach((t) => {
    const tab = t.dataset.tab;
    const n = tab === "all" ? state.items.length + state.stories.length : (tab === "story" ? state.stories : state.items).filter((i) => i.type === tab).length;
  });
}

/* ---------------- Selection ---------------- */
function toggleSelect(id, checked) {
  if (checked) state.selected.add(id);
  else state.selected.delete(id);
  updateSelectionUI();
}
function updateSelectionUI() {
  els.selectedCount.textContent = String(state.selected.size);
  els.downloadSelectedBtn.disabled = state.selected.size === 0;
  selCheckboxSync();
}
function selCheckboxSync() {
  const vis = visibleItems();
  const visibleIds = new Set(vis.map((i) => i.id));
  const selVisible = vis.filter((i) => state.selected.has(i.id)).length;
  els.selectAllCb.checked = vis.length > 0 && selVisible === vis.length;
  els.selectAllCb.indeterminate = selVisible > 0 && selVisible < vis.length;
}
els.selectAllCb.addEventListener("change", () => {
  const vis = visibleItems();
  if (els.selectAllCb.checked) vis.forEach((i) => state.selected.add(i.id));
  else vis.forEach((i) => state.selected.delete(i.id));
  updateSelectionUI();
  renderGrid();
});

/* ---------------- Render grid ---------------- */
function renderGrid() {
  const items = visibleItems();
  els.grid.innerHTML = "";
  if (items.length === 0) {
    els.grid.hidden = true;
    if (state.tab === "story" && state.stories.length === 0) {
      setStatus("info", emptyStateText());
    }
    return;
  }
  els.grid.hidden = false;
  if (state.tab === "story") clearStatus();

  for (const it of items) {
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.id = it.id;

    const img = document.createElement("img");
    img.loading = "lazy";
    if (it.thumbnail_url) img.src = prox(it.thumbnail_url);
    else img.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><rect width='100%25' height='100%25' fill='%23ccc'/></svg>";
    card.appendChild(img);

    // Type badge
    const badge = document.createElement("span");
    badge.className = `badge badge-${it.type}`;
    badge.textContent = it.type.charAt(0).toUpperCase() + it.type.slice(1);
    card.appendChild(badge);

    // Overlay (likes / play)
    const ov = document.createElement("div");
    ov.className = "overlay";
    if (it.type === "story") {
      // story indicator
      ov.innerHTML = `<span class="play">▶</span>`;
    } else if (it.is_video) {
      ov.innerHTML = `<span class="play">▶</span>`;
    } else if (it.likes != null) {
      ov.innerHTML = `<span class="like">♥ ${fmt(it.likes)}</span>`;
    }
    card.appendChild(ov);

    // Checkbox
    const sel = document.createElement("label");
    sel.className = "sel";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.selected.has(it.id);
    cb.addEventListener("change", (e) => { e.stopPropagation(); toggleSelect(it.id, cb.checked); });
    sel.appendChild(cb);
    card.appendChild(sel);

    card.addEventListener("click", () => openModal(it, items));
    els.grid.appendChild(card);
  }
}

/* ---------------- Modal viewer ---------------- */
function openModal(item, allItems) {
  modalState.item = item;
  modalState.items = allItems;
  modalState.idx = allItems.findIndex((i) => i.id === item.id);
  renderModal();
  els.modal.hidden = false;
}
function renderModal() {
  const it = modalState.item;
  if (!it) return;
  els.modalMedia.innerHTML = "";
  const isVideo = it.is_video || /\.(mp4|webm|mov)(\?|$)/.test(String(it.media_url || ""));
  if (isVideo) {
    const v = document.createElement("video");
    v.src = prox(it.media_url);
    v.controls = true;
    v.autoplay = true;
    v.muted = false;
    v.style.maxWidth = "100%";
    v.style.maxHeight = "62vh";
    els.modalMedia.appendChild(v);
  } else {
    const img = document.createElement("img");
    img.src = prox(it.media_url || it.thumbnail_url);
    img.style.maxWidth = "100%";
    img.style.maxHeight = "62vh";
    els.modalMedia.appendChild(img);
  }
  els.modalInfo.innerHTML = `
    <span><b>${it.type}</b></span>
    <span>♥ ${it.likes != null ? fmt(it.likes) : "—"}</span>
    <span>💬 ${it.comments != null ? fmt(it.comments) : "—"}</span>
    ${it.timestamp ? `<span>${new Date(it.timestamp).toLocaleString()}</span>` : ""}
    ${it.caption ? `<div class="caption">${escapeHtml(it.caption)}</div>` : ""}
  `;
}
els.modalDownload.addEventListener("click", () => {
  const it = modalState.item;
  if (!it) return;
  downloadSingle(it);
});
els.modalClose.addEventListener("click", () => { els.modal.hidden = true; });
els.modal.addEventListener("click", (e) => { if (e.target === els.modal) els.modal.hidden = true; });

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* ---------------- Single download ---------------- */
async function downloadSingle(it) {
  try {
    const resp = await fetch("/api/download/single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: it.id, type: it.type, media_url: it.media_url, timestamp: it.timestamp, is_video: it.is_video }),
    });
    if (!resp.ok) { const e = await resp.json(); throw new Error(e.detail || "Download failed"); }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${sanitize(it.id)}_${it.type}.${it.is_video ? "mp4" : "jpg"}`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast("Downloaded " + it.id, "success");
  } catch (err) {
    toast("Download failed: " + friendly(err.message), "error");
  }
}
function sanitize(s) { return String(s || "media").replace(/[^\w.-]/g, "_"); }

/* ---------------- Bulk download (ZIP) ---------------- */
els.downloadSelectedBtn.addEventListener("click", startBulkDownload);
async function startBulkDownload() {
  const chosen = visibleItems().filter((i) => state.selected.has(i.id));
  if (!chosen.length) return;
  els.progressOverlay.hidden = false;
  els.progressBar.value = 0;
  els.progressText.textContent = "Starting download…";
  try {
    const resp = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: chosen.map(strip), username: state.username || state.profile?.username }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Could not start download");
    await pollJob(data.job_id);
  } catch (err) {
    els.progressOverlay.hidden = true;
    toast("Could not start download: " + friendly(err.message), "error");
  }
}
function strip(it) { const { id, type, media_url, source_url, caption, timestamp } = it; return { id, type, media_url, source_url, caption, timestamp }; }
async function pollJob(jobId) {
  while (true) {
    await new Promise((r) => setTimeout(r, 800));
    const resp = await fetch(`/api/status/${jobId}`);
    const data = await resp.json();
    if (!resp.ok) { els.progressOverlay.hidden = true; toast(friendly(data.detail), "error"); return; }
    els.progressBar.value = data.progress || 0;
    els.progressText.textContent = data.status === "completed"
      ? `Completed! ${data.completed} downloaded${data.failed ? `, ${data.failed} failed` : ""}.`
      : data.status === "failed" ? "Download failed." : `Downloading… ${data.completed}/${data.total}`;
    if (data.status === "completed") {
      els.progressOverlay.hidden = true;
      toast(data.failed ? `Done: ${data.completed} ok, ${data.failed} failed` : `Downloaded ${data.completed} media.`, "success");
      if (data.zip_url) { window.location.href = data.zip_url; toast("ZIP download started.", "success"); }
      return;
    }
    if (data.status === "failed") { els.progressOverlay.hidden = true; toast("Some items failed. Check the report.", "error"); return; }
  }
}

/* ---------------- Errors ---------------- */
function emptyStateText() {
  if (state.tab === "story") {
    return "No stories are currently available. Instagram requires login to view someone's stories — this app never bypasses that.";
  }
  if (state.tab === "reel") {
    return "No reels found for this account.";
  }
  return "No media found for this filter.";
}

function friendly(msg) {
  if (/requires login|login/i.test(msg)) return "This content requires login to view.";
  if (/private/i.test(msg)) return "This account is private or unavailable.";
  if (/rate|too many/i.test(msg)) return "Too many requests. Wait a moment and retry.";
  if (/timed? ?out|network/i.test(msg)) return "Could not reach Instagram. Try again later.";
  if (/deleted|not found/i.test(msg)) return "This post could not be found. It may have been deleted.";
  return msg || "Something went wrong.";
}

/* ---------------- Nav actions ---------------- */
function doSearch() {
  const v = els.searchInput.value.trim();
  if (v) fetchMedia(v);
}
els.searchBtn.addEventListener("click", doSearch);
els.searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
els.quickForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const v = els.homeInput.value.trim();
  if (v) { els.searchInput.value = v; fetchMedia(v); }
});
els.brand.addEventListener("click", () => {
  els.home.hidden = false;
  els.profileView.hidden = true;
  els.grid.hidden = true;
  clearStatus();
});

initTheme();
updateSelectionUI();