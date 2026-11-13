"use strict";
const S = { token: null, user: null, facilities: [], users: [], tab: "Dashboard", ticket: null };
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pill = v => `<span class="pill ${esc(v)}">${esc(v)}</span>`;

async function api(path, opts = {}) {
  const method = opts.method || "GET";
  const headers = { "Content-Type": "application/json", ...(S.token ? { Authorization: "Bearer " + S.token } : {}), ...(opts.headers || {}) };
  if (method === "POST" && !headers["Idempotency-Key"]) headers["Idempotency-Key"] = crypto.randomUUID();   // one key per user action
  const send = () => fetch("/api" + path, { method, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let res;
  try { res = await send(); if (res.status === 503 && method === "POST") { await new Promise(r => setTimeout(r, 300)); res = await send(); } }
  catch (e) { if (method !== "POST") throw e; await new Promise(r => setTimeout(r, 300)); res = await send(); }   // safe retry: same Idempotency-Key
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.message || res.statusText); e.status = res.status; e.data = data; throw e; }
  return data;
}
function toast(msg, ok = true) { const t = $("#toast"); t.className = ok ? "ok" : "err"; t.textContent = msg; }
async function act(fn, okMsg) {
  try { const r = await fn(); toast(okMsg || "Done"); await render(); return r; }
  catch (e) { toast(`${e.status || ""} ${e.data?.error || "error"}: ${e.message}`, false); }
}

$("#go").onclick = async () => {
  try {
    const r = await api("/login", { method: "POST", body: { username: $("#u").value, password: $("#p").value } });
    S.token = r.token; S.user = r.user;
    $("#login").hidden = true; $("#app").hidden = false;
    $("#who").textContent = `${r.user.display_name} (${r.user.role})`;
    S.facilities = await api("/facilities"); S.users = await api("/users");
    buildTabs(); render();
  } catch (e) { alert(e.message); }
};
function buildTabs() {
  const tabs = ["Dashboard", "Facilities & Bookings", "Tickets", "Approvals & Loans", "Sensors"];
  if (["admin", "facility_manager", "approver"].includes(S.user.role)) tabs.push("Audit");
  $("#tabs").innerHTML = tabs.map(t => `<button data-t="${t}" class="${t === S.tab ? "on" : ""}">${t}</button>`).join("");
  $("#tabs").onclick = e => { if (e.target.dataset.t) { S.tab = e.target.dataset.t; buildTabs(); render(); } };
}
async function render() {
  const v = $("#view");
  try { v.innerHTML = await ({ "Dashboard": dash, "Facilities & Bookings": bookings, "Tickets": tickets, "Approvals & Loans": approvals, "Sensors": sensors, "Audit": audit }[S.tab])(); }
  catch (e) { v.innerHTML = `<p class="note">Could not load: ${esc(e.message)}</p>`; }
  bind();
}
async function dash() {
  const d = await api("/dashboard");
  const k = (l, n) => `<div class="kpi"><b>${n ?? 0}</b>${l}</div>`;
  return `<h2>Operations dashboard</h2><div class="grid">${k("Open tickets on track", d.open_ticket_sla.on_track)}${k("Open tickets at risk", d.open_ticket_sla.at_risk)}${k("Open tickets breached", d.open_ticket_sla.breached)}
  ${k("Pending approvals", d.pending_approvals)}${k("Sensor alerts recorded", d.sensor_alerts)}${k("Active bookings", (d.bookings_by_status.approved || 0) + (d.bookings_by_status.confirmed || 0) + (d.bookings_by_status.in_use || 0) + (d.bookings_by_status.requested || 0))}</div>
  <h3>Tickets by status</h3><p>${Object.entries(d.tickets_by_status).map(([s, n]) => `${pill(s)} ${n}`).join(" &nbsp; ") || "none"}</p><p class="note">${esc(d.note)}</p>`;
}
async function bookings() {
  const fid = S.facFilter || "", date = S.dateFilter || "";
  const rows = await api(`/bookings?facility_id=${fid}&date=${date}`);
  const opts = S.facilities.map(f => `<option value="${f.id}" ${String(f.id) === String(fid) ? "selected" : ""}>${esc(f.code)} – ${esc(f.name)}${f.restricted ? " (restricted)" : ""}</option>`).join("");
  return `<div class="row"><div><h2>Facility catalogue</h2><table><tr><th>Code</th><th>Name</th><th>Kind</th><th>Cap.</th><th>Campus</th><th>Access</th></tr>
  ${S.facilities.map(f => `<tr><td>${esc(f.code)}</td><td>${esc(f.name)}</td><td>${esc(f.kind)}</td><td>${f.capacity}</td><td>${esc(f.campus)}</td><td>${f.restricted ? "approval needed" : "open"}</td></tr>`).join("")}</table></div>
  <div class="card"><h3>Request a booking</h3><label>Facility<select id="bf">${opts}</select></label><label>Start<input id="bs" value="2026-11-20T09:00"></label><label>End<input id="be" value="2026-11-20T11:00"></label>
  <label>Purpose<input id="bp" value="Lecture"></label><button id="bgo">Submit booking</button><p class="note">Overlaps are rejected by the server (HTTP 409).</p></div></div>
  <h3>Booking calendar</h3><div class="row"><label>Facility<select id="ff"><option value="">All</option>${opts}</select></label><label>Date<input id="fd" placeholder="2026-11-20" value="${esc(date)}"></label><button class="alt" id="fgo">Filter</button></div>
  <table><tr><th>#</th><th>Facility</th><th>Start</th><th>End</th><th>By</th><th>Status</th><th>Actions</th></tr>${rows.map(b => `<tr><td>${b.id}</td><td>${esc(b.facility_code)}</td><td>${esc(b.start_ts)}</td><td>${esc(b.end_ts)}</td><td>${esc(b.requester)}</td><td>${pill(b.status)}</td>
  <td>${["confirm", "check_in", "complete", "cancel"].map(a => `<button class="alt bt" data-b="${b.id}" data-a="${a}">${a}</button>`).join(" ")}</td></tr>`).join("")}</table>`;
}
async function tickets() {
  const list = await api("/tickets");
  const techs = S.users.filter(u => u.role === "technician");
  let detail = "";
  if (S.ticket) {
    const d = await api("/tickets/" + S.ticket), t = d.ticket; S.tv = t.version;
    detail = `<div class="card"><h3>#${t.id} ${esc(t.title)} ${pill(t.status)} <span class="note">version ${t.version}</span></h3><p>${esc(t.description)}</p>
    <p><b>Suggested</b> ${esc(t.suggested_category)}/${esc(t.suggested_priority)} – <i>${esc(t.triage_explanation)}</i><br><b>Final</b> ${esc(t.category)}/${esc(t.priority)} · SLA ${pill(t.sla.state)} (${t.sla.minutes_remaining ?? "–"} min) · due ${esc(t.sla_due_at)}</p>
    <p>Assignee: ${esc(t.assignee || "–")} · Inspection: ${esc(t.inspection_notes || "–")} · Resolution: ${esc(t.resolution_notes || "–")}</p>
    <div class="row"><div><label>Assign to<select id="at">${techs.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join("")}</select></label>
    <label>Priority override<select id="ap"><option value="">(keep suggestion)</option><option>P1</option><option>P2</option><option>P3</option><option>P4</option></select></label><button id="ago" data-t="${t.id}">Assign</button></div>
    <div><label>Notes<input id="tn" placeholder="inspection / resolution notes"></label>${["start_inspection", "request_work", "resolve", "close"].map(a => `<button class="alt tt" data-t="${t.id}" data-a="${a}">${a}</button>`).join(" ")}</div></div>
    <h4>DevOps / delivery link <span class="mode">integration mode: ${esc(d.links[0]?.mode || "simulated")}</span></h4>
    ${d.links.map(l => `<p>${esc(l.external_ref)} · ${pill(l.delivery_status)} · verified: ${l.verified_at ? "yes" : "no"}</p>`).join("") || "<p class='note'>No link yet.</p>"}
    <button class="alt dl" data-t="${t.id}">Create link</button> <button class="alt dl" data-t="${t.id}" data-fail="1">Create link (simulate tracker outage)</button>
    ${d.links.map(l => `<button class="alt lp" data-l="${l.id}">Advance delivery</button> <button class="alt lv" data-l="${l.id}">Verify delivery</button>`).join(" ")}
    <h4>History</h4><table><tr><th>Time</th><th>Actor</th><th>Action</th><th>Details</th><th>Instance</th></tr>${d.history.map(h => `<tr><td>${esc(h.ts)}</td><td>${esc(h.actor)}</td><td>${esc(h.action)}</td><td>${esc(h.details)}</td><td>${esc(h.instance_id)}</td></tr>`).join("")}</table></div>`;
  }
  return `<h2>Maintenance queue</h2><table><tr><th>#</th><th>Title</th><th>Facility</th><th>Cat/Pri</th><th>Status</th><th>SLA</th><th>Assignee</th><th></th></tr>
  ${list.map(t => `<tr><td>${t.id}</td><td>${esc(t.title)}</td><td>${esc(t.facility_code)}</td><td>${esc(t.category)}/${esc(t.priority)}</td><td>${pill(t.status)}</td><td>${pill(t.sla.state)}</td><td>${esc(t.assignee || "–")}</td><td><button class="alt tv" data-t="${t.id}">Open</button></td></tr>`).join("")}</table>
  <div class="card"><h3>Report a fault</h3><div class="row"><div><label>Facility<select id="nf">${S.facilities.map(f => `<option value="${f.id}">${esc(f.code)}</option>`).join("")}</select></label><label>Title<input id="nt" value="Projector not working"></label>
  <label>Description<textarea id="nd">No image on the projector in the room.</textarea></label><button id="ngo">Create ticket</button> <button class="alt" id="npv">Preview triage</button></div><div id="npvout" class="note"></div></div></div>${detail}`;
}
async function approvals() {
  const [ap, ln, eq] = await Promise.all([api("/approvals").catch(() => []), api("/equipment-loans"), api("/equipment")]);
  return `<h2>Approvals</h2><table><tr><th>#</th><th>Type</th><th>Subject</th><th>Requester</th><th>Decision</th><th>Reason</th><th></th></tr>${ap.map(a => `<tr><td>${a.id}</td><td>${esc(a.subject_type)}</td><td>${a.subject_id}</td><td>${esc(a.requester)}</td><td>${pill(a.decision)}</td><td>${esc(a.reason || "")}</td>
  <td>${a.decision === "pending" ? `<input class="rs" data-a="${a.id}" placeholder="reason (required)"><button class="alt ad" data-a="${a.id}" data-d="approved">Approve</button> <button class="warn ad" data-a="${a.id}" data-d="rejected">Reject</button>` : ""}</td></tr>`).join("")}</table>
  <div class="card"><h3>Request an equipment loan</h3><label>Equipment<select id="le">${eq.map(e => `<option value="${e.id}">${esc(e.name)}</option>`).join("")}</select></label><label>From<input id="ls" value="2026-11-24"></label><label>To<input id="lt" value="2026-11-26"></label><button id="lgo">Request loan</button></div>
  <h3>Loans</h3><table><tr><th>#</th><th>Equipment</th><th>From</th><th>To</th><th>Status</th></tr>${ln.map(l => `<tr><td>${l.id}</td><td>${esc(l.equipment)}</td><td>${esc(l.start_date)}</td><td>${esc(l.end_date)}</td><td>${pill(l.status)}</td></tr>`).join("")}</table>`;
}
async function sensors() {
  return `<h2>Sensor alert intake (controlled events)</h2><p class="note">Events at or above the threshold create a ticket. Re-sending the same event id never creates a second record.</p>
  <div class="card"><div class="row"><label>Sensor<input id="ss" value="S-TEMP-1"></label><label>Event id<input id="se" value="EVT-${Date.now() % 100000}"></label>
  <label>Facility<select id="sf">${S.facilities.map(f => `<option value="${f.id}">${esc(f.code)}</option>`).join("")}</select></label>
  <label>Metric<select id="sm"><option>temperature_c</option><option>humidity_pct</option><option>power_kw</option><option>water_leak</option></select></label><label>Value<input id="sv" value="36"></label></div>
  <button id="sgo">Send event</button> <button class="alt" id="sgo2">Send same event again (duplicate)</button><p id="sout" class="note"></p></div>`;
}
async function audit() {
  const rows = await api("/audit");
  return `<h2>Audit trail (latest 200, append-only)</h2><table><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Details</th><th>Instance</th></tr>${rows.map(r => `<tr><td>${r.id}</td><td>${esc(r.ts)}</td><td>${esc(r.actor)}</td><td>${esc(r.action)}</td><td>${esc(r.entity_type)} ${r.entity_id ?? ""}</td><td>${esc(r.details)}</td><td>${esc(r.instance_id)}</td></tr>`).join("")}</table>`;
}
function bind() {
  const on = (sel, fn) => document.querySelectorAll(sel).forEach(el => el.onclick = () => fn(el));
  const val = id => $("#" + id)?.value;
  if ($("#bgo")) $("#bgo").onclick = () => act(() => api("/bookings", { method: "POST", body: { facility_id: +val("bf"), start_ts: val("bs"), end_ts: val("be"), purpose: val("bp") } }), "Booking submitted");
  if ($("#fgo")) $("#fgo").onclick = () => { S.facFilter = val("ff"); S.dateFilter = val("fd"); render(); };
  on(".bt", el => act(() => api(`/bookings/${el.dataset.b}/transition`, { method: "POST", body: { action: el.dataset.a } }), "Booking updated"));
  on(".tv", el => { S.ticket = el.dataset.t; render(); });
  if ($("#ngo")) $("#ngo").onclick = () => act(() => api("/tickets", { method: "POST", body: { title: val("nt"), description: val("nd"), facility_id: +val("nf") } }), "Ticket created");
  if ($("#npv")) $("#npv").onclick = async () => { const r = await api("/triage-preview?text=" + encodeURIComponent(val("nt") + ". " + val("nd"))); $("#npvout").textContent = `${r.category} / ${r.priority} – ${r.explanation} [${r.method}]`; };
  if ($("#ago")) $("#ago").onclick = el => act(() => api(`/tickets/${S.ticket}/assign`, { method: "POST", body: { technician_id: +val("at"), priority: val("ap") || undefined, expected_version: S.tv } }), "Ticket assigned");
  on(".tt", el => act(() => api(`/tickets/${el.dataset.t}/transition`, { method: "POST", body: { action: el.dataset.a, notes: val("tn"), expected_version: S.tv } }), "Ticket updated"));
  on(".dl", el => act(() => api(`/tickets/${el.dataset.t}/devops-link`, { method: "POST", headers: el.dataset.fail ? { "X-Simulate-Integration": "down" } : {} }), "Link created"));
  on(".lp", el => { const order = ["opened", "in_progress", "delivered"]; api("/tickets/" + S.ticket).then(d => { const l = d.links.find(x => x.id == el.dataset.l); act(() => api(`/integration-links/${l.id}/progress`, { method: "POST", body: { delivery_status: order[order.indexOf(l.delivery_status) + 1] } }), "Delivery advanced"); }); });
  on(".lv", el => act(() => api(`/integration-links/${el.dataset.l}/verify`, { method: "POST" }), "Delivery verified"));
  on(".ad", el => act(() => api(`/approvals/${el.dataset.a}/decide`, { method: "POST", body: { decision: el.dataset.d, reason: document.querySelector(`.rs[data-a="${el.dataset.a}"]`).value } }), "Decision recorded"));
  if ($("#lgo")) $("#lgo").onclick = () => act(() => api("/equipment-loans", { method: "POST", body: { equipment_id: +val("le"), start_date: val("ls"), end_date: val("lt") } }), "Loan requested");
  const send = async () => { try { const r = await api("/sensor-events", { method: "POST", body: { sensor_id: val("ss"), event_id: val("se"), facility_id: +val("sf"), metric: val("sm"), value: +val("sv") } }); $("#sout").textContent = JSON.stringify(r); toast(r.duplicate ? "Duplicate event: existing record returned" : "Event recorded"); } catch (e) { toast(`${e.status} ${e.data?.error}: ${e.message}`, false); } };
  if ($("#sgo")) $("#sgo").onclick = send;
  if ($("#sgo2")) $("#sgo2").onclick = send;
}
