// ============================================================
// QFACE Dashboard — script.js
// ============================================================

// Toast
function showToast(message, type = "info") {
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

// ============================================================
// Polling state
// ============================================================
const pagination = {
  all: { page: 1, limit: 50, total: 0, pages: 1, lastId: 0 },
  recognised: { page: 1, limit: 50, total: 0, pages: 1, lastId: 0 },
  unrecognised: { page: 1, limit: 50, total: 0, pages: 1, lastId: 0 },
  door: { page: 1, limit: 50, total: 0, pages: 1 },
};
let activeTab = "all";
let statsIntervalId = null;
let logIntervalId = null;

// ============================================================
// API helpers — all go through main_server proxy
// ============================================================
const API = {
  stats: () => fetch("/api/proxy/stats").then((r) => r.json()),
  logs: (params) =>
    fetch("/api/proxy/logs?" + new URLSearchParams(params)).then((r) =>
      r.json(),
    ),
  deleteLog: (id) =>
    fetch(`/api/proxy/logs/${id}`, { method: "DELETE" }).then((r) => r.json()),
  clearLogs: () =>
    fetch("/api/proxy/clear_logs", { method: "DELETE" }).then((r) => r.json()),
  moveToDb: (id, name) =>
    fetch(`/api/proxy/logs/${id}/move_to_database`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(name ? { name } : {}),
    }).then((r) => r.json()),
  faces: () => fetch("/api/proxy/faces").then((r) => r.json()),
  createFace: (data) =>
    fetch("/api/proxy/faces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then((r) => r.json()),
  deleteFace: (name) =>
    fetch(`/api/proxy/faces/${name}`, { method: "DELETE" }).then((r) =>
      r.json(),
    ),
  trainedData: () => fetch("/api/proxy/trained_data").then((r) => r.json()),
  doorLogs: (params) =>
    fetch("/api/proxy/door_logs?" + new URLSearchParams(params)).then((r) =>
      r.json(),
    ),
  rebuildCache: () =>
    fetch("/api/proxy/cache/rebuild", { method: "POST" }).then((r) => r.json()),
  trainedImage: (person, img) => `/api/proxy/trained_image/${person}/${img}`,
  logImage: (prediction, filename, isRec) =>
    isRec && prediction && prediction !== "Unknown"
      ? `/api/proxy/log_image/recognised/${prediction}/${filename}`
      : `/api/proxy/log_image/unrecognised/${filename}`,
};

// ============================================================
// Open Door
// ============================================================
async function openDoor() {
  const btn = document.getElementById("openDoorBtn");
  if (!btn || btn.classList.contains("loading")) return;
  btn.classList.add("loading");
  btn.textContent = "⏳ OPENING...";
  try {
    const res = await fetch("/api/proxy/door", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ door_id: 1, action: "open" }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      btn.classList.add("success");
      btn.textContent = "✅ DOOR OPENED!";
      showToast("Door opened!", "success");
      setTimeout(() => {
        btn.classList.remove("success", "loading");
        btn.textContent = "🚪 OPEN DOOR";
      }, 2000);
    } else throw new Error(data.message || "Failed");
  } catch (e) {
    btn.classList.add("error");
    btn.textContent = "❌ FAILED";
    showToast("Door error: " + e.message, "error");
    setTimeout(() => {
      btn.classList.remove("error", "loading");
      btn.textContent = "🚪 OPEN DOOR";
    }, 2000);
  }
}

// ============================================================
// Stats
// ============================================================
async function loadStats() {
  try {
    const data = await API.stats();
    updateStatsUI(data);
  } catch (e) {
    /* silent */
  }
}

function updateStatsUI(s) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  set("totalCount", s.total || 0);
  set("recognisedCount", s.recognised || 0);
  set("unrecognisedCount", s.unrecognised || 0);
  set("uniquePeople", s.unique_people || 0);

  const sc = document.getElementById("statsContent");
  if (!sc) return;
  sc.innerHTML = `
    <div style="padding:20px;">
      <h2>Recognition Statistics</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-top:20px;">
        <div style="background:#f8f9fa;padding:20px;border-radius:8px;text-align:center;">
          <div style="font-size:36px;font-weight:bold;color:#667eea;">${s.total || 0}</div>
          <div style="color:#666;margin-top:4px;">Total</div>
        </div>
        <div style="background:#d4edda;padding:20px;border-radius:8px;text-align:center;">
          <div style="font-size:36px;font-weight:bold;color:#155724;">${s.recognised || 0}</div>
          <div style="color:#155724;margin-top:4px;">✅ Recognised</div>
        </div>
        <div style="background:#f8d7da;padding:20px;border-radius:8px;text-align:center;">
          <div style="font-size:36px;font-weight:bold;color:#721c24;">${s.unrecognised || 0}</div>
          <div style="color:#721c24;margin-top:4px;">❌ Unrecognised</div>
        </div>
        <div style="background:#fff3cd;padding:20px;border-radius:8px;text-align:center;">
          <div style="font-size:36px;font-weight:bold;color:#856404;">${s.unique_people || 0}</div>
          <div style="color:#856404;margin-top:4px;">👥 Unique People</div>
        </div>
      </div>
      ${
        s.people_list && s.people_list.length > 0
          ? `
        <div style="margin-top:24px;">
          <h3>People Recognised</h3>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;">
            ${s.people_list.map((n) => `<span style="background:#667eea;color:white;padding:4px 14px;border-radius:20px;font-size:14px;">${n}</span>`).join("")}
          </div>
        </div>`
          : ""
      }
    </div>`;
}

// ============================================================
// Recognition Logs
// ============================================================
function getConfClass(c) {
  return c >= 80 ? "high" : c >= 50 ? "medium" : "low";
}

function renderLogRow(entry, index) {
  const conf = entry.confidence || 0;
  const isRec = entry.is_recognised === 1 || entry.is_recognised === true;
  const pred = entry.prediction || "Unknown";
  const imgSrc =
    isRec && pred !== "Unknown"
      ? `/api/proxy/log_image/recognised/${pred}/${entry.filename}`
      : !isRec
        ? `/api/proxy/log_image/unrecognised/${entry.filename}`
        : "";

  const adminActions = isAdmin
    ? `
    <td>
      ${
        isRec
          ? `<button class="btn btn-success btn-sm" onclick="moveToDatabase(${entry.id})">📁 DB</button>`
          : `<button class="btn btn-warning btn-sm" onclick="moveUnrecToDb(${entry.id})">📁 DB</button>`
      }
      <button class="delete-btn" style="margin-left:4px;" onclick="deleteLog(${entry.id})">✕</button>
    </td>`
    : "";

  return `<tr>
    <td>${index + 1}</td>
    <td class="image-cell">${
      imgSrc
        ? `<img src="${imgSrc}" alt="face" loading="lazy"
           onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2260%22 height=%2260%22%3E%3Crect width=%2260%22 height=%2260%22 fill=%22%23eee%22/%3E%3Ctext x=%2250%25%22 y=%2255%25%22 text-anchor=%22middle%22 font-size=%2212%22 fill=%22%23aaa%22%3E?%3C/text%3E%3C/svg%3E'">`
        : "<span style='color:#aaa;'>—</span>"
    }</td>
    <td><strong>${pred}</strong></td>
    <td>
      <div class="confidence-bar"><div class="fill ${getConfClass(conf)}" style="width:${Math.min(conf, 100)}%"></div></div>
      <span style="font-size:12px;margin-left:6px;">${conf.toFixed(1)}%</span>
    </td>
    <td><span class="badge ${isRec ? "recognised" : "unrecognised"}">${isRec ? "✅" : "❌"}</span></td>
    <td style="font-size:12px;">${(entry.date || entry.timestamp || "").replace("T", " ").slice(0, 19)}</td>
    ${adminActions}
  </tr>`;
}

function renderTable(logs, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!logs || logs.length === 0) {
    el.innerHTML = `<div class="empty-state"><div class="emoji">📋</div><p>No records</p></div>`;
    return;
  }
  const cols = `<th>#</th><th>Image</th><th>Name</th><th>Confidence</th><th>Status</th><th>Date & Time</th>${isAdmin ? "<th>Actions</th>" : ""}`;
  el.innerHTML = `<table><thead><tr>${cols}</tr></thead><tbody>${logs.map((e, i) => renderLogRow(e, i)).join("")}</tbody></table>`;
}

// Prepend new rows to an existing table (live update without flicker)
function prependRows(logs, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const tbody = el.querySelector("tbody");
  if (!tbody) {
    renderTable(logs, containerId);
    return;
  }
  const cols = `<th>#</th><th>Image</th><th>Name</th><th>Confidence</th><th>Status</th><th>Date & Time</th>${isAdmin ? "<th>Actions</th>" : ""}`;
  const newRows = logs.map((e, i) => renderLogRow(e, i)).join("");
  tbody.insertAdjacentHTML("afterbegin", newRows);
  // Renumber existing rows
  tbody
    .querySelectorAll("tr td:first-child")
    .forEach((td, i) => (td.textContent = i + 1));
  // Trim to 50 rows max
  const rows = tbody.querySelectorAll("tr");
  for (let i = 50; i < rows.length; i++) rows[i].remove();
}

async function loadData(tab = "all", page = 1, incremental = false) {
  try {
    const key = tab;
    const searchId = "search" + tab.charAt(0).toUpperCase() + tab.slice(1);
    const search = (document.getElementById(searchId) || {}).value || "";
    const params = { tab, search, limit: 50, offset: (page - 1) * 50 };
    if (incremental && pagination[key].lastId > 0) {
      params.last_id = pagination[key].lastId;
    }

    const data = await API.logs(params);
    if (!data.success) {
      showToast("Failed to load logs", "error");
      return;
    }

    const tableId =
      tab === "all"
        ? "allTable"
        : tab === "recognised"
          ? "recognisedTable"
          : "unrecognisedTable";

    if (incremental && data.logs && data.logs.length > 0) {
      prependRows(data.logs, tableId);
      pagination[key].lastId = data.logs[0].id;
    } else if (!incremental) {
      renderTable(data.logs, tableId);
      if (data.logs && data.logs.length > 0) {
        pagination[key].lastId = data.logs[0].id;
      }
      pagination[key] = {
        ...pagination[key],
        page,
        total: data.total || 0,
        pages: data.pages || 1,
      };
      renderPagination(key);
    }

    if (data.stats) updateStatsUI(data.stats);
  } catch (e) {
    console.error("loadData error:", e);
  }
}

function renderPagination(key) {
  const info = pagination[key];
  const suffix = key === "all" ? "all" : key === "recognised" ? "rec" : "unrec";
  const container = document.getElementById(key + "Pagination");
  if (!container) return;
  if (info.pages <= 1) {
    container.innerHTML = "";
    return;
  }
  let html = "";
  const start = Math.max(1, info.page - 2);
  const end = Math.min(info.pages, info.page + 2);
  if (start > 1)
    html += `<button onclick="loadData('${key}',1)">1</button>${start > 2 ? "<span>…</span>" : ""}`;
  for (let i = start; i <= end; i++) {
    html += `<button class="${i === info.page ? "active" : ""}" onclick="loadData('${key}',${i})">${i}</button>`;
  }
  if (end < info.pages)
    html += `${end < info.pages - 1 ? "<span>…</span>" : ""}<button onclick="loadData('${key}',${info.pages})">${info.pages}</button>`;
  container.innerHTML = html;
  const pg = document.getElementById(suffix + "Page");
  if (pg) pg.textContent = info.page;
  const pgs = document.getElementById(suffix + "Pages");
  if (pgs) pgs.textContent = info.pages;
}

async function deleteLog(id) {
  if (!confirm("Delete this log entry?")) return;
  try {
    const data = await API.deleteLog(id);
    if (data.success) {
      showToast("Deleted", "success");
      loadData(activeTab, 1);
    } else showToast("Error: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

async function moveToDatabase(logId) {
  if (!confirm("Move this image to training database?")) return;
  try {
    const data = await API.moveToDb(logId);
    if (data.success) {
      showToast("Moved to database", "success");
    } else showToast("Failed: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

async function moveUnrecToDb(logId) {
  const name = prompt("Enter name for this person:");
  if (!name || !name.trim()) return;
  try {
    const data = await API.moveToDb(logId, name.trim());
    if (data.success) {
      showToast(`Moved as: ${name}`, "success");
      loadData(activeTab, 1);
    } else showToast("Failed: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

async function clearAllLogs() {
  if (!confirm("Clear ALL recognition and door logs? This cannot be undone!"))
    return;
  try {
    const data = await API.clearLogs();
    if (data.success) {
      showToast("All logs cleared", "success");
      loadData("all", 1);
    } else showToast("Failed: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

// ============================================================
// Door Logs
// ============================================================
async function loadDoorLogs(page = 1) {
  const search = (document.getElementById("searchDoor") || {}).value || "";
  try {
    const data = await API.doorLogs({ page, limit: 50, search });
    if (!data.success) return;
    pagination.door = { page, limit: 50, total: data.total, pages: data.pages };
    const container = document.getElementById("doorTable");
    if (!container) return;
    if (!data.logs || data.logs.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="emoji">🚪</div><p>No door logs</p></div>`;
    } else {
      let html = `<table><thead><tr><th>#</th><th>Person</th><th>Action</th><th>Result</th><th>Confidence</th><th>Timestamp</th></tr></thead><tbody>`;
      data.logs.forEach((log, i) => {
        html += `<tr>
          <td>${i + 1}</td>
          <td><strong>${log.person || "Unknown"}</strong></td>
          <td>${log.action || "door_open"}</td>
          <td><span class="badge ${log.result === "success" ? "recognised" : "unrecognised"}">${log.result}</span></td>
          <td>${log.confidence != null ? log.confidence.toFixed(1) + "%" : "—"}</td>
          <td style="font-size:12px;">${(log.timestamp || "").replace("T", " ").slice(0, 19)}</td>
        </tr>`;
      });
      html += `</tbody></table>`;
      container.innerHTML = html;
    }
    // Pagination
    const pc = document.getElementById("doorPagination");
    if (pc) {
      if (data.pages > 1) {
        let ph = "";
        for (let i = 1; i <= data.pages; i++)
          ph += `<button class="${i === page ? "active" : ""}" onclick="loadDoorLogs(${i})">${i}</button>`;
        pc.innerHTML = ph;
      } else pc.innerHTML = "";
    }
    const dp = document.getElementById("doorPage");
    if (dp) dp.textContent = page;
    const dps = document.getElementById("doorPages");
    if (dps) dps.textContent = data.pages;
  } catch (e) {
    showToast("Error loading door logs", "error");
  }
}

// ============================================================
// Trained Data
// ============================================================
async function loadTrainedData() {
  try {
    const data = await API.trainedData();
    const container = document.getElementById("trainedContainer");
    if (!container) return;
    if (!data.success || !data.data || data.data.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="emoji">📚</div><p>No trained data</p></div>`;
      return;
    }
    let html = `<div class="trained-grid">`;
    data.data.forEach((person) => {
      html += `<div class="trained-card">
        <div class="name">👤 ${person.name}</div>
        <div style="font-size:13px;color:#666;margin:4px 0;">${person.image_count} images</div>
        <div class="trained-images">`;
      person.images.slice(0, 6).forEach((img) => {
        const imgUrl = `/api/proxy/trained_image/${person.name}/${img}`;
        const short = img.length > 20 ? img.slice(0, 18) + "…" : img;
        html += `<div class="trained-image-item">
          <img src="${imgUrl}" alt="${img}" loading="lazy" onerror="this.style.display='none'">
          <span title="${img}">${short}</span>
          <button class="btn btn-danger btn-sm" onclick="deleteTrainedImage('${person.name}','${img}')">🗑️</button>
        </div>`;
      });
      if (person.images.length > 6)
        html += `<div style="font-size:12px;color:#999;">+${person.images.length - 6} more</div>`;
      html += `</div>
        <div class="actions" style="margin-top:8px;">
          <button class="btn btn-success btn-sm" onclick="trainFace('${person.name}')">📸 Train</button>
        </div>
      </div>`;
    });
    html += `</div>`;
    container.innerHTML = html;
  } catch (e) {
    showToast("Error loading trained data", "error");
  }
}

async function deleteTrainedImage(person, image) {
  if (!confirm(`Delete ${image} for ${person}?`)) return;
  try {
    const res = await fetch(`/api/proxy/trained_data/${person}/${image}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (data.success) {
      showToast("Deleted", "success");
      loadTrainedData();
    } else showToast("Error: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

// ============================================================
// Faces
// ============================================================
async function loadFaces() {
  try {
    const data = await API.faces();
    const container = document.getElementById("facesTable");
    if (!container) return;
    if (!data.success || !data.faces || data.faces.length === 0) {
      container.innerHTML = `<div class="empty-state"><p>No faces in database</p></div>`;
      return;
    }
    let html = `<table><thead><tr><th>Name</th><th>Allowed Hours</th><th>Images</th><th>Actions</th></tr></thead><tbody>`;
    data.faces.forEach((f) => {
      html += `<tr>
        <td><strong>${f.name}</strong></td>
        <td>${f.entry_start_time} – ${f.entry_end_time}</td>
        <td>${f.image_count || 0}</td>
        <td>
          <button class="btn btn-success btn-sm" onclick="trainFace('${f.name}')">📸 Train</button>
          <button class="btn btn-primary btn-sm" onclick="editFaceTime('${f.name}')">✏️</button>
          <button class="btn btn-danger btn-sm" onclick="deleteFace('${f.name}')">🗑️</button>
        </td>
      </tr>`;
    });
    html += `</tbody></table>`;
    container.innerHTML = html;
  } catch (e) {
    showToast("Error loading faces", "error");
  }
}

function showAddFaceForm() {
  document.getElementById("addFaceForm").style.display = "block";
}
function cancelAddFace() {
  document.getElementById("addFaceForm").style.display = "none";
  document.getElementById("newFaceName").value = "";
  document.getElementById("newFaceStart").value = "00:00";
  document.getElementById("newFaceEnd").value = "23:59";
}

async function createFace() {
  const name = document.getElementById("newFaceName").value.trim();
  const start = document.getElementById("newFaceStart").value;
  const end = document.getElementById("newFaceEnd").value;
  if (!name) {
    showToast("Name required", "error");
    return;
  }
  try {
    const data = await API.createFace({
      name,
      start_time: start,
      end_time: end,
    });
    if (data.success) {
      showToast(`Face ${name} created`, "success");
      cancelAddFace();
      loadFaces();
    } else showToast(data.message || "Failed", "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

async function editFaceTime(name) {
  const start = prompt("New start time (HH:MM):", "00:00");
  if (start === null) return;
  const end = prompt("New end time (HH:MM):", "23:59");
  if (end === null) return;
  try {
    const res = await fetch(`/api/proxy/faces/${name}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_time: start, end_time: end })
    });
    const data = await res.json();
    if (data.success) { showToast("Updated", "success"); loadFaces(); }
    else showToast(data.message || "Failed", "error");
  } catch (e) { showToast("Error", "error"); }
}

async function deleteFace(name) {
  if (!confirm(`Delete face "${name}" and all its images?`)) return;
  try {
    const data = await API.deleteFace(name);
    if (data.success) {
      showToast(`Deleted ${name}`, "success");
      loadFaces();
    } else showToast(data.message || "Failed", "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

function trainFace(name) {
  window.location.replace(`/camera?train=${encodeURIComponent(name)}`);
}

// ============================================================
// Users
// ============================================================
function loadUsers() {
  fetch("/api/users")
    .then((r) => r.json())
    .then((data) => {
      if (!data.success) return;
      const grid = document.getElementById("userGrid");
      if (!grid) return;
      if (!data.users || data.users.length === 0) {
        grid.innerHTML = `<div class="empty-state"><p>No users</p></div>`;
        return;
      }
      grid.innerHTML = data.users
        .map(
          (u) => `
      <div class="user-card">
        <div class="user-icon">${u.is_admin ? "👑" : "👤"}</div>
        <div class="user-name">${u.username}</div>
        <div class="user-hours">${u.entry_start_time} – ${u.entry_end_time}</div>
        <div class="user-hours">${u.is_admin ? "Admin" : "User"}</div>
        <div class="user-actions">
          <button class="btn btn-success btn-sm" onclick="trainUser('${u.username}')">Train</button>
          <button class="btn btn-primary btn-sm" onclick="showEditUser('${u.username}')">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="deleteUser('${u.username}')">Delete</button>
        </div>
        <div id="edit_${u.username}" style="display:none;margin-top:10px;padding:10px;background:#f8f9fa;border-radius:4px;">
          <div style="display:flex;gap:5px;flex-wrap:wrap;">
            <input type="time" id="edit_start_${u.username}" value="${u.entry_start_time}" style="padding:4px;border:1px solid #ddd;border-radius:4px;">
            <input type="time" id="edit_end_${u.username}" value="${u.entry_end_time}" style="padding:4px;border:1px solid #ddd;border-radius:4px;">
            <select id="edit_admin_${u.username}" style="padding:4px;border:1px solid #ddd;border-radius:4px;">
              <option value="0" ${u.is_admin ? "" : "selected"}>User</option>
              <option value="1" ${u.is_admin ? "selected" : ""}>Admin</option>
            </select>
            <button class="btn btn-success btn-sm" onclick="updateUser('${u.username}')">Save</button>
            <button class="btn btn-danger btn-sm" onclick="hideEditUser('${u.username}')">Cancel</button>
          </div>
        </div>
      </div>`,
        )
        .join("");
    });
}

function showEditUser(u) {
  document.getElementById(`edit_${u}`).style.display = "block";
}
function hideEditUser(u) {
  document.getElementById(`edit_${u}`).style.display = "none";
}
function trainUser(u) {
  window.location.replace(`/camera?train=${encodeURIComponent(u)}`);
}

function addUser() {
  const username = document.getElementById("newUsername").value.trim();
  const password = document.getElementById("newPassword").value.trim();
  const startTime = document.getElementById("newStartTime").value;
  const endTime = document.getElementById("newEndTime").value;
  const isAdminVal = parseInt(document.getElementById("newIsAdmin").value);
  if (!username || !password) {
    showToast("Username and password required", "error");
    return;
  }
  fetch("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      password,
      startTime,
      endTime,
      isAdmin: isAdminVal,
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast(`User ${username} added`, "success");
        document.getElementById("newUsername").value = "";
        document.getElementById("newPassword").value = "";
        loadUsers();
      } else showToast(data.message || "Failed", "error");
    });
}

function deleteUser(username) {
  if (!confirm(`Delete user "${username}"?`)) return;
  fetch("/api/users", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast(`Deleted ${username}`, "success");
        loadUsers();
      } else showToast(data.message || "Failed", "error");
    });
}

function updateUser(username) {
  const startTime = document.getElementById(`edit_start_${username}`).value;
  const endTime = document.getElementById(`edit_end_${username}`).value;
  const isAdminVal = parseInt(
    document.getElementById(`edit_admin_${username}`).value,
  );
  fetch("/api/users/update", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, startTime, endTime, isAdmin: isAdminVal }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast("Updated", "success");
        loadUsers();
      } else showToast(data.message || "Failed", "error");
    });
}

// ============================================================
// Profile / Change Password
// ============================================================
function loadProfile() {
  const content = document.getElementById("profileContent");
  if (!content) return;
  content.innerHTML = `
    <div style="padding:20px;">
      <h2>Profile Settings</h2>
      <div style="background:#f8f9fa;padding:20px;border-radius:8px;margin-top:20px;max-width:400px;">
        <div style="margin-bottom:12px;"><strong>Username:</strong> ${currentUsername}</div>
        <div style="margin-bottom:12px;"><strong>Role:</strong> ${isAdmin ? "Admin 👑" : "User"}</div>
        <hr style="margin:16px 0;">
        <h3>Change Password</h3>
        <div style="margin-top:12px;">
          <div style="margin-bottom:10px;">
            <label style="font-weight:600;display:block;margin-bottom:4px;">Current Password</label>
            <input type="password" id="currentPass" style="width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;">
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-weight:600;display:block;margin-bottom:4px;">New Password</label>
            <input type="password" id="newPass" style="width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;">
          </div>
          <div style="margin-bottom:14px;">
            <label style="font-weight:600;display:block;margin-bottom:4px;">Confirm New Password</label>
            <input type="password" id="confirmPass" style="width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;">
          </div>
          <button class="btn btn-primary" onclick="changePassword()">Change Password</button>
        </div>
      </div>
    </div>`;
}

function showChangePassword() {
  switchTab("profile");
}

function changePassword() {
  const curr = document.getElementById("currentPass").value;
  const nw = document.getElementById("newPass").value;
  const conf = document.getElementById("confirmPass").value;
  if (!curr || !nw || !conf) {
    showToast("Fill all fields", "error");
    return;
  }
  if (nw !== conf) {
    showToast("Passwords don't match", "error");
    return;
  }
  if (nw.length < 4) {
    showToast("Password too short", "error");
    return;
  }
  fetch("/api/change_password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: currentUsername,
      current_password: curr,
      new_password: nw,
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast("Password changed!", "success");
        ["currentPass", "newPass", "confirmPass"].forEach(
          (id) => (document.getElementById(id).value = ""),
        );
      } else showToast(data.message || "Failed", "error");
    });
}

// ============================================================
// Log Files
// ============================================================
let currentLogFile = null;

async function loadLogFiles() {
  try {
    const res = await fetch("/api/log_files");
    const data = await res.json();
    const container = document.getElementById("logFilesList");
    if (!container) return;
    if (!data.success || !data.files || data.files.length === 0) {
      container.innerHTML = `<div class="empty-state"><p>No log files</p></div>`;
      return;
    }
    const fmtSize = (s) =>
      s < 1024
        ? s + " B"
        : s < 1024 * 1024
          ? (s / 1024).toFixed(1) + " KB"
          : (s / 1048576).toFixed(1) + " MB";
    let html = `<table><thead><tr><th>File</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead><tbody>`;
    data.files.forEach((f) => {
      html += `<tr>
        <td><strong>${f.name}</strong></td>
        <td>${fmtSize(f.size)}</td>
        <td style="font-size:12px;">${new Date(f.modified).toLocaleString()}</td>
        <td><button class="btn btn-primary btn-sm" onclick="viewLogFile('${f.name}')">View</button></td>
      </tr>`;
    });
    html += `</tbody></table>`;
    container.innerHTML = html;
    document.getElementById("logFileContent").style.display = "none";
  } catch (e) {
    showToast("Error loading log files", "error");
  }
}

async function viewLogFile(filename) {
  currentLogFile = filename;
  document.getElementById("currentLogFileName").textContent = filename;
  document.getElementById("logFileContent").style.display = "block";
  await refreshLogContent();
}

async function refreshLogContent() {
  if (!currentLogFile) return;
  try {
    const res = await fetch(`/api/log_file/${currentLogFile}?lines=200`);
    if (res.ok) {
      const text = await res.text();
      const pre = document.getElementById("logFileContentPre");
      if (pre) {
        pre.textContent = text;
        pre.scrollTop = pre.scrollHeight;
      }
    }
  } catch (e) {
    showToast("Error loading log", "error");
  }
}

async function clearLogFile() {
  if (!currentLogFile || !confirm(`Clear "${currentLogFile}"?`)) return;
  try {
    const res = await fetch(`/api/log_file/clear/${currentLogFile}`, {
      method: "POST",
    });
    const data = await res.json();
    if (data.success) {
      showToast("Log cleared", "success");
      await refreshLogContent();
      loadLogFiles();
    } else showToast("Failed: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

function closeLogContent() {
  document.getElementById("logFileContent").style.display = "none";
  currentLogFile = null;
}

async function clearAllLogFiles() {
  if (!confirm("Clear all log files?")) return;
  try {
    const res = await fetch("/api/clear_log_files", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Log files cleared", "success");
      loadLogFiles();
    } else showToast("Failed: " + data.message, "error");
  } catch (e) {
    showToast("Error", "error");
  }
}

// ============================================================
// Tab switching
// ============================================================
function switchTab(tab) {
  activeTab = tab;
  document
    .querySelectorAll(".tab-content")
    .forEach((el) => el.classList.remove("active"));
  document
    .querySelectorAll(".tab-btn")
    .forEach((el) => el.classList.remove("active"));
  const tabEl = document.getElementById(tab + "Tab");
  if (tabEl) tabEl.classList.add("active");
  const btnEl = document.querySelector(
    `.tab-btn[onclick="switchTab('${tab}')"]`,
  );
  if (btnEl) btnEl.classList.add("active");

  clearIntervals();

  switch (tab) {
    case "camera":
      // Direct img tag instead of iframe for mobile performance
      const cf = document.getElementById("cameraFeedDash");
      if (cf) cf.src = CAMERA_STREAM_URL + "?t=" + Date.now();
      break;
    case "users":
      loadUsers();
      break;
    case "profile":
      loadProfile();
      break;
    case "faces":
      loadFaces();
      break;
    case "door":
      loadDoorLogs(1);
      logIntervalId = setInterval(
        () => loadDoorLogs(pagination.door.page),
        3000,
      );
      break;
    case "trained":
      loadTrainedData();
      break;
    case "stats":
      loadStats();
      statsIntervalId = setInterval(loadStats, 5000);
      break;
    case "logs":
      loadLogFiles();
      break;
    default:
      loadData(tab, 1);
      logIntervalId = setInterval(
        () => loadData(tab, pagination[tab].page, true),
        3000,
      );
      break;
  }
}

function clearIntervals() {
  if (statsIntervalId) {
    clearInterval(statsIntervalId);
    statsIntervalId = null;
  }
  if (logIntervalId) {
    clearInterval(logIntervalId);
    logIntervalId = null;
  }
}

// ============================================================
// Auth
// ============================================================
function logout() {
  fetch("/api/logout", { method: "POST" }).then(
    () => (window.location.href = "/login"),
  );
}

function openCamera(e) {
  e.preventDefault();
  window.location.replace("/camera");
}

// ============================================================
// Init
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  loadData("all", 1);
  loadStats();
  logIntervalId = setInterval(
    () => loadData("all", pagination.all.page, true),
    3000,
  );
});

function reloadCameraFeed() {
  const img = document.getElementById("cameraFeedDash");
  if (img) img.src = CAMERA_STREAM_URL + "?t=" + Date.now();
}
