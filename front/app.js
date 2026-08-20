// Instagram Media Downloader — IG-style profile + post viewer, grouped posts.
"use strict";

const state = {
  sessionId: null,
  username: null,
  profile: null,
  posts: [],          // all loaded posts (grouped)
  stories: [],
  storiesStatus: null,
  tab: "post",        // post | reel | story
  selected: new Set(), // of post.id
  loadingMore: false,
  hasMore: false,
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
  downloadAllBtn: document.getElementById("downloadAllBtn"),
  statPosts: document.getElementById("statPosts"),
  statFollowers: document.getElementById("statFollowers"),
  statFollowing: document.getElementById("statFollowing"),
  profileFullName: document.getElementById("profileFullName"),
  profileBio: document.getElementById("profileBio"),
  highlightsRow: document.getElementById("highlightsRow"),
  grid: document.getElementById("grid"),
  loadMore: document.getElementById("loadMore"),
  loadMoreBtn: document.getElementById("loadMoreBtn"),
  modal: document.getElementById("modal"),
  modalClose: document.getElementById("modalClose"),
  modalMedia: document.getElementById("modalMedia"),
  modalAvatar: document.getElementById("modalAvatar"),
  modalUsername: document.getElementById("modalUsername"),
  modalInfo: document.getElementById("modalInfo"),
  modalDownload: document.getElementById("modalDownload"),
  modalSelectCb: document.getElementById("modalSelectCb"),
  modalChildren: document.getElementById("modalChildren"),
  progressOverlay: document.getElementById("progressOverlay"),
  progressBar: document.getElementById("progressBar"),
  progressText: document.getElementById("progressText"),
  bulkBar: document.getElementById("bulkBar"),
  selCount: document.getElementById("selCount"),
  clearSelBtn: document.getElementById("clearSelBtn"),
  downloadSelBtn: document.getElementById("downloadSelBtn"),
  brand: document.getElementById("brand"),
};
const modalState = { post: null, itemIdx: 0 };

/* ---------------- helpers ---------------- */
function fmt(n) {
  if (n == null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}
function prox(url) {
  if (!url) return "";
  if (url.startsWith("/api/proxy")) return url;
  return `/api/proxy?url=${encodeURIComponent(url)}`;
}
function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}
function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}
function setStatus(type, html) {
  els.statusArea.innerHTML = `<div class="status ${type}">${html}</div>`;
}
function clearStatus() { els.statusArea.innerHTML = ""; }
function withSpinner(msg) { return `<span class="spinner"></span>${msg}`; }
function friendly(msg) {
  if (/requires login|login/i.test(msg)) return "This content requires login to view.";
  if (/private/i.test(msg)) return "This account is private or unavailable.";
  if (/rate|too many/i.test(msg)) return "Too many requests. Wait a moment and retry.";
  if (/timed? ?out|network/i.test(msg)) return "Could not reach Instagram. Try again later.";
  if (/deleted|not found/i.test(msg)) return "This post could not be found. It may have been deleted.";
  return msg || "Something went wrong.";
}

/* ---------------- theme ---------------- */
function initTheme() {
  const saved = localStorage.getItem("theme") || "light";
  if (saved === "dark") document.documentElement.dataset.theme = "dark";
  els.themeBtn.textContent = saved === "dark" ? "☀️" : "🌙";
}
els.themeBtn.addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme !== "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "";
  localStorage.setItem("theme", dark ? "dark" : "light");
  els.themeBtn.textContent = dark ? "☀️" : "🌙";
});

/* ---------------- search / resolve ---------------- */
async function search(raw) {
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
    els.loadMore.hidden = true;
  }
}
function applyResolve(data) {
  state.sessionId = data.session_id || null;
  state.username = data.username;
  state.profile = data.profile || null;
  state.posts = data.posts || [];
  state.stories = data.stories || [];
  state.storiesStatus = data.stories_status || null;
  state.selected = new Set();
  state.hasMore = !!data.has_more;
  state.tab = "post";

  els.home.hidden = true;
  els.profileView.hidden = false;

  const p = state.profile;
  if (p && p.profile_pic_url) {
    els.profileAvatar.src = prox(p.profile_pic_url);
  }
  els.profileUsername.textContent = p ? p.username : state.username || "";
  els.statPosts.textContent = fmt(p ? p.post_count : state.posts.length);
  els.statFollowers.textContent = fmt(p ? p.followers : null);
  els.statFollowing.textContent = fmt(p ? p.following : null);
  els.profileFullName.textContent = p ? p.full_name || "" : "";
  els.profileBio.textContent = p ? p.bio || "" : "";

  // stories highlight bubble (only show if there are stories)
  els.highlightsRow.hidden = !(state.stories.length > 0);

  // Stories notice
  if (state.tab === "post" && state.storiesStatus === "login_required") {
    setStatus("info", "Stories require login to view — posts and reels are available below.");
  }

  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === "post"));
  renderGrid();
  updateBulkBar();
  updateLoadMore();
}
els.searchBtn.addEventListener("click", () => search());
els.searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
els.quickForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const v = els.homeInput.value.trim();
  if (v) { els.searchInput.value = v; search(v); }
});
els.brand.addEventListener("click", goHome);
function goHome() {
  els.home.hidden = false;
  els.profileView.hidden = true;
  els.grid.hidden = true;
  els.loadMore.hidden = true;
  els.bulkBar.hidden = true;
  els.statusArea.innerHTML = "";
}

/* ---------------- load more ---------------- */
async function loadMore() {
  if (state.loadingMore || !state.hasMore || !state.sessionId) return;
  state.loadingMore = true;
  els.loadMoreBtn.textContent = "Loading…";
  els.loadMoreBtn.disabled = true;
  try {
    const resp = await fetch("/api/resolve/more", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: state.sessionId }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Could not load more");
    state.posts = state.posts.concat(data.posts || []);
    state.hasMore = !!data.has_more;
    renderGrid();
    updateBulkBar();
  } catch (err) {
    toast("Could not load more: " + friendly(err.message), "error");
  } finally {
    state.loadingMore = false;
    els.loadMoreBtn.textContent = "Load more";
    els.loadMoreBtn.disabled = false;
    updateLoadMore();
  }
}
els.loadMoreBtn.addEventListener("click", loadMore);
function updateLoadMore() {
  els.loadMore.hidden = !state.hasMore || state.tab !== "post";
}

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("is-active", x === t));
    state.tab = t.dataset.tab;
    renderGrid();
    updateLoadMore();
    if (state.tab === "story" && state.stories.length === 0) {
      setStatus("info", "No stories available. Instagram requires login to view someone's stories — this app never bypasses that.");
    } else if (state.tab !== "story" || state.stories.length > 0) {
      clearStatus();
    }
  })
);
function visiblePosts() {
  const all = state.tab === "story"
    ? state.stories
    : state.posts.filter((p) => state.tab === "post" ? p.type === "post" : p.type === "reel");
  return all;
}

/* ---------------- grid ---------------- */
function renderGrid() {
  const posts = visiblePosts();
  els.grid.innerHTML = "";
  if (posts.length === 0) { els.grid.hidden = true; return; }
  els.grid.hidden = false;

  for (const p of posts) {
    const card = document.createElement("div");
    card.className = "card";
    if (state.selected.has(p.id)) card.classList.add("selected");
    card.dataset.id = p.id;

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = prox(p.thumbnail_url);
    img.alt = "post";
    card.appendChild(img);

    // multi-item indicator (carousel)
    if (p.media_count > 1) {
      const multi = document.createElement("span");
      multi.className = "multi";
      multi.textContent = "▱ " + p.media_count;
      card.appendChild(multi);
    }
    // video / reel corner icon
    if (p.is_video) {
      const vid = document.createElement("span");
      vid.className = "corner";
      vid.textContent = "▶";
      card.appendChild(vid);
    }
    // hover overlay with stats
    const ov = document.createElement("div");
    ov.className = "ov";
    ov.innerHTML = `
      <span class="stat">♥ ${fmt(p.likes)}</span>
      <span class="stat">💬 ${fmt(p.comments)}</span>
    `;
    card.appendChild(ov);

    // selection checkbox
    if (state.tab !== "story") {
      const sel = document.createElement("label");
      sel.className = "sel";
      sel.addEventListener("click", (e) => e.stopPropagation());
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.selected.has(p.id);
      cb.addEventListener("change", () => toggleSelect(p.id, cb.checked));
      sel.appendChild(cb);
      card.appendChild(sel);
    }

    card.addEventListener("click", () => openModal(p));
    els.grid.appendChild(card);
  }
}

/* ---------------- selection ---------------- */
function toggleSelect(id, checked) {
  if (checked) state.selected.add(id);
  else state.selected.delete(id);
  updateBulkBar();
  renderGrid();
}
function updateBulkBar() {
  const n = state.selected.size;
  els.selCount.textContent = String(n);
  els.bulkBar.hidden = n === 0;
  els.downloadSelBtn.disabled = n === 0;
}
els.clearSelBtn.addEventListener("click", () => {
  state.selected = new Set();
  updateBulkBar();
  renderGrid();
});

/* ---------------- modal / post viewer ---------------- */
function openModal(post) {
  modalState.post = post;
  modalState.itemIdx = 0;
  renderModal();
  els.modal.hidden = false;
}
function renderModal() {
  const p = modalState.post;
  if (!p) return;
  els.modalMedia.innerHTML = "";

  const it = p.items[modalState.itemIdx];
  const isVideo = it.is_video || /\.(mp4|webm|mov)(\?|$)/.test(String(it.media_url || ""));

  if (isVideo) {
    const v = document.createElement("video");
    v.src = prox(it.media_url);
    v.controls = true; v.autoplay = true;
    els.modalMedia.appendChild(v);
  } else {
    const img = document.createElement("img");
    img.src = prox(it.media_url || it.thumbnail_url);
    els.modalMedia.appendChild(img);
  }

  // carousel nav arrows if multi-item
  if (p.items.length > 1) {
    const prev = document.createElement("button");
    prev.className = "modal-nav prev"; prev.textContent = "‹";
    prev.onclick = () => { modalState.itemIdx = (modalState.itemIdx - 1 + p.items.length) % p.items.length; renderModal(); };
    const next = document.createElement("button");
    next.className = "modal-nav next"; next.textContent = "›";
    next.onclick = () => { modalState.itemIdx = (modalState.itemIdx + 1) % p.items.length; renderModal(); };
    els.modalMedia.appendChild(prev);
    els.modalMedia.appendChild(next);
  }

  // author
  if (state.profile && state.profile.profile_pic_url) {
    els.modalAvatar.src = prox(state.profile.profile_pic_url);
  }
  els.modalUsername.textContent = state.profile ? state.profile.username : state.username || "";

  // info
  els.modalInfo.innerHTML = `
    <div class="caption">${escapeHtml(p.caption)}</div>
    <div class="meta">
      <span>${new Date(p.timestamp).toLocaleDateString()}</span>
      <span>♥ ${fmt(p.likes)}</span>
      <span>💬 ${fmt(p.comments)}</span>
      ${p.items.length > 1 ? `<span>${modalState.itemIdx + 1}/${p.items.length}</span>` : ""}
    </div>
  `;

  // children thumbnails (carousel picker)
  els.modalChildren.innerHTML = "";
  if (p.items.length > 1) {
    els.modalChildren.hidden = false;
    p.items.forEach((c, i) => {
      const b = document.createElement("button");
      if (i === modalState.itemIdx) b.classList.add("active");
      const t = document.createElement("img");
      t.src = prox(c.thumbnail_url || c.media_url);
      b.appendChild(t);
      b.onclick = () => { modalState.itemIdx = i; renderModal(); };
      els.modalChildren.appendChild(b);
    });
  } else {
    els.modalChildren.hidden = true;
  }

  // select-this-post checkbox
  els.modalSelectCb.checked = state.selected.has(p.id);
  els.modalSelectCb.onchange = () => toggleSelect(p.id, els.modalSelectCb.checked);
}
els.modalClose.addEventListener("click", () => { els.modal.hidden = true; });
els.modal.addEventListener("click", (e) => { if (e.target === els.modal) els.modal.hidden = true; });
document.addEventListener("keydown", (e) => {
  if (els.modal.hidden || !modalState.post) return;
  const p = modalState.post;
  if (e.key === "Escape") { els.modal.hidden = true; }
  else if (e.key === "ArrowLeft" && p.items.length > 1) { modalState.itemIdx = (modalState.itemIdx - 1 + p.items.length) % p.items.length; renderModal(); }
  else if (e.key === "ArrowRight" && p.items.length > 1) { modalState.itemIdx = (modalState.itemIdx + 1) % p.items.length; renderModal(); }
});

/* ---------------- download single (current item in modal) ---------------- */
els.modalDownload.addEventListener("click", async () => {
  const p = modalState.post;
  if (!p) return;
  const it = p.items[modalState.itemIdx];
  const itemIds = p.items.map((c) => c.id);
  const flat = p.items.map((c) => ({
    id: c.id,
    type: p.type,
    media_url: c.media_url,
    source_url: p.source_url,
    caption: p.caption,
    timestamp: p.timestamp,
  }));
  // Single-item post: stream one file; carousel: download all children as ZIP
  if (p.items.length === 1) {
    await downloadOneFile(it, p);
  } else {
    await startBulk(flat, state.username);
  }
});
async function downloadOneFile(item, post) {
  try {
    const resp = await fetch("/api/download/single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: item.id, type: post.type, media_url: item.media_url, timestamp: post.timestamp, is_video: item.is_video }),
    });
    if (!resp.ok) { const e = await resp.json(); throw new Error(e.detail || "Download failed"); }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${sanitize(post.id)}.${item.is_video ? "mp4" : "jpg"}`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast("Downloaded " + post.id, "success");
  } catch (err) {
    toast("Download failed: " + friendly(err.message), "error");
  }
}

/* ---------------- bulk download (ZIP) ---------------- */
els.downloadSelBtn.addEventListener("click", () => {
  const chosen = state.posts.filter((p) => state.selected.has(p.id));
  const flat = [];
  chosen.forEach((p) => {
    p.items.forEach((c) => flat.push({
      id: c.id,
      type: p.type,
      media_url: c.media_url,
      source_url: p.source_url,
      caption: p.caption,
      timestamp: p.timestamp,
    }));
  });
  if (flat.length) startBulk(flat, state.username);
});
els.downloadAllBtn.addEventListener("click", async () => {
  // Use everything currently loaded.
  if (state.posts.length === 0) return;
  const flat = [];
  state.posts.forEach((p) => p.items.forEach((c) => flat.push({
    id: c.id, type: p.type, media_url: c.media_url, source_url: p.source_url, caption: p.caption, timestamp: p.timestamp,
  })));
  toast(`Downloading all ${flat.length} media from ${state.posts.length} posts…`, "info");
  startBulk(flat, state.username);
});
async function startBulk(items, username) {
  els.progressOverlay.hidden = false;
  els.progressBar.value = 0;
  els.progressText.textContent = "Starting download…";
  try {
    const resp = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items, username }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Could not start download");
    await pollJob(data.job_id);
  } catch (err) {
    els.progressOverlay.hidden = true;
    toast("Could not start download: " + friendly(err.message), "error");
  }
}
async function pollJob(jobId) {
  while (true) {
    await new Promise((r) => setTimeout(r, 800));
    const resp = await fetch(`/api/status/${jobId}`);
    const data = await resp.json();
    if (!resp.ok) { els.progressOverlay.hidden = true; toast(friendly(data.detail), "error"); return; }
    els.progressBar.value = data.progress || 0;
    if (data.status === "completed") {
      els.progressText.textContent = `Completed! ${data.completed} files${data.failed ? `, ${data.failed} failed` : ""}.`;
      if (data.zip_url) {
        window.location.href = data.zip_url;
        toast("ZIP download started.", "success");
      }
      setTimeout(() => { els.progressOverlay.hidden = true; }, 1200);
      return;
    }
    els.progressText.textContent = data.status === "failed"
      ? "Download failed."
      : `Downloading… ${data.completed}/${data.total}`;
    if (data.status === "failed") { els.progressOverlay.hidden = true; toast("Download failed.", "error"); return; }
  }
}
function sanitize(s) { return String(s || "media").replace(/[^\w.-]/g, "_"); }

/* ---------------- init ---------------- */
initTheme();
updateBulkBar();