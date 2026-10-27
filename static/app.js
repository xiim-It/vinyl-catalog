// Vinyl Catalog v3 — vanilla JS frontend. No build step.
(() => {
  const API = "";
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => [...r.querySelectorAll(s)];
  const esc = s => String(s||"").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);

  const state = {
    view: "tiles",
    records: [],
    folders: [],
    currentFolder: "",
    modalOpen: null,
  };

  // ---------- modal ----------
  const modal = $("#modal"), modalTitle = $("#modalTitle"), modalBody = $("#modalBody");
  function openModal(title, html, onClose){ state.modalOpen = onClose; modalTitle.textContent = title; modalBody.innerHTML = html; modal.classList.remove("hidden"); }
  function closeModal(){ modal.classList.add("hidden"); modalBody.innerHTML=""; if (state.modalOpen){ const c = state.modalOpen; state.modalOpen=null; c&&c(); } }
  $("#modalClose")?.remove?.();  // ensure no duplicate
  modal.querySelector(".modal-close").onclick = closeModal;
  $("#modalDone").onclick = closeModal;
  document.addEventListener("keydown", e => { if (e.key==="Escape" && !modal.classList.contains("hidden")) closeModal(); });

  // ---------- gallery ----------
  async function loadMeta(){ const r = await (await fetch(API+"/api/meta")).json(); $("#meta").textContent = `${r.record_count} records • ${r.image_count} images • schema v${r.schema_version} • app v${r.app_version}`; }
  async function loadRecords(){
    const q = new URLSearchParams();
    if ($("#search").value) q.set("search", $("#search").value);
    if ($("#filterStatus").value) q.set("status", $("#filterStatus").value);
    if ($("#filterConfidence").value) q.set("confidence", $("#filterConfidence").value);
    if ($("#filterHasAI").checked) q.set("has_ai", "true");
    if ($("#filterHasDiscogs").checked) q.set("has_discogs", "true");
    if ($("#yearFrom").value) q.set("year_from", $("#yearFrom").value);
    if ($("#yearTo").value) q.set("year_to", $("#yearTo").value);
    if ($("#genre").value) q.set("genre", $("#genre").value);
    if ($("#label").value) q.set("label", $("#label").value);
    q.set("sort", $("#sort").value);
    const r = await (await fetch(API+"/api/records?"+q)).json();
    state.records = r.records || [];
    renderRecords();
  }
  function renderRecords(){
    const out = $("#results"); out.className = "results " + state.view;
    if (!state.records.length){ out.innerHTML = `<div class="card"><div class="info">No records.</div></div>`; return; }
    out.innerHTML = state.records.map(r => {
      const thumb = (r.images && r.images[0] && r.images[0].thumb_path) || "";
      const ai = r.ai_confidence || "";
      const dc = r.discogs_confidence || "";
      const price = r.price_eur != null ? `${r.price_eur} EUR` : "—";
      return `<div class="card" data-id="${esc(r.id)}">
        ${thumb ? `<img loading="lazy" src="/images/${esc(r.id)}/${encodeURIComponent((r.images[0].thumb_path||"").split("/").pop())}">` : ""}
        <div class="info">
          <h3>${esc(r.artist||"?")} — ${esc(r.title||"Untitled")}</h3>
          <div class="small">${esc(r.label||"")} • ${r.year||""} • ${price}</div>
          <div>${ai?`<span class="conf ${esc(ai)}">AI: ${esc(ai)}</span>`:""}${dc?`<span class="conf ${esc(dc)}">DC: ${esc(dc)}</span>`:""}</div>
        </div>
      </div>`;
    }).join("");
    $$(".card", out).forEach(c => c.onclick = () => openRecord(c.dataset.id));
  }
  $$(".views button").forEach(b => b.onclick = () => { $$(".views button").forEach(x=>x.classList.remove("active")); b.classList.add("active"); state.view = b.dataset.view; renderRecords(); });
  ["#search","#filterStatus","#filterConfidence","#filterHasAI","#filterHasDiscogs","#yearFrom","#yearTo","#genre","#label","#sort"].forEach(s => $(s).addEventListener("input", loadRecords));
  $("#search").addEventListener("input", loadRecords);

  async function openRecord(id){
    const r = await (await fetch(API+"/api/records/"+id)).json();
    const rec = r.record;
    const imgs = (rec.images||[]).map(im => `<img loading="lazy" src="/images/${esc(rec.id)}/${encodeURIComponent(im.thumb_path ? im.thumb_path.split("/").pop() : im.stored_path.split("/").pop())}" title="${esc(im.role)}">`).join("");
    const fields = [["Artist","artist"],["Title","title"],["Label","label"],["Catalog #","catalog_number"],["Barcode","barcode"],["Year","year"],["Genre","genre"],["Format","format"],["Country","country"],["Price EUR","price_eur"],["Notes","notes"]];
    const editable = fields.map(([k,key]) => `<div class="row"><label>${k}</label><input data-f="${esc(key)}" value="${esc(rec[key]!==undefined && rec[key]!==null ? rec[key] : "")}"></div>`).join("");
    const dc = rec.discogs_data_json && rec.discogs_data_json.selected ? `<div class="kv"><div class="k">Discogs</div><div>${esc(rec.discogs_data_json.selected.title||"")} (${esc(rec.discogs_data_json.selected.label||"")} ${esc(rec.discogs_data_json.selected.catalog_number||"")})</div></div>` : "<em>No Discogs data yet</em>";
    const cands = (rec.discogs_data_json && rec.discogs_data_json.candidates) || [];
    const candHtml = cands.length ? `<h4>Discogs candidates</h4>${cands.slice(0,5).map((c,i) => `<div class="kv"><div class="k">#${i+1} score ${c.score||0}</div><div><strong>${esc(c.title||"")}</strong> — ${esc(c.label||"")} <button class="secondary" data-pick='${JSON.stringify(c)}'>Pick</button></div></div>`).join("")}` : "";
    openModal(`Record ${id}`, `
      <div class="thumbs">${imgs}</div>
      <h4>Data</h4>${editable}
      <h4>Discogs</h4>${dc}${candHtml}
      <div class="row" style="margin-top:12px"><button class="secondary" id="saveRec">Save</button><button class="secondary" id="delRec" style="color:var(--err)">Delete</button></div>
    `, null);
    $("#saveRec").onclick = async () => {
      const payload = {};
      $$("#modalBody [data-f]").forEach(el => payload[el.dataset.f] = el.value);
      await fetch(API+"/api/records/"+id, {method:"PATCH", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
      closeModal(); loadRecords();
    };
    $("#delRec").onclick = async () => {
      if (!confirm("Delete this record?")) return;
      await fetch(API+"/api/records/"+id, {method:"DELETE"});
      closeModal(); loadRecords();
    };
    $$("[data-pick]").forEach(btn => btn.onclick = async () => {
      const c = JSON.parse(btn.dataset.pick);
      await fetch(API+"/api/records/"+id+"/select_discogs", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({candidate: c})});
      closeModal(); loadRecords();
    });
  }

  // ---------- Import modal ----------
  function fsItemHtml(item){
    if (item.name==="..") return `<div class="item dir" data-path="${esc(item.path)}">⬆ ..</div>`;
    const ic = item.is_dir ? `<span class="small">${item.image_count||0} img</span>` : "";
    return `<div class="item ${item.is_dir?"dir":""}" data-path="${esc(item.path)}">${item.is_dir?"📁":"📄"} ${esc(item.name)} ${ic}</div>`;
  }
  async function browseFolder(path){
    const r = await (await fetch(API+"/api/fs/list?path="+encodeURIComponent(path))).json();
    state.currentFolder = r.path;
    const list = $("#folderList");
    if (!list) return;
    list.innerHTML = r.items.map(fsItemHtml).join("");
    $$(".item", list).forEach(it => it.onclick = () => browseFolder(it.dataset.path));
  }
  async function showImport(){
    openModal("Import", `
      <p>Select a folder on this computer to import vinyl photos from.</p>
      <div class="row"><label>Folder</label><input id="folderPath" placeholder="/path/to/photos"></div>
      <div class="row"><label>Browse</label><button class="secondary" id="browseHome">🏠 Home</button></div>
      <div id="folderList" class="folder-list"></div>
      <div class="row"><label>Images per record</label><input type="number" id="imagesPerRecord" value="2" min="1" max="6"></div>
      <div class="row"><label>Roles (per position)</label>
        <small>Position 1 → role below, etc. Up to 6 images per record.</small></div>
      <div id="rolesRow"></div>
      <div class="row" style="margin-top:12px"><button class="primary" id="doImport">Start import</button></div>
      <div id="importJob"></div>
    `);
    browseFolder("");
    $("#browseHome").onclick = () => browseFolder($("#folderPath").value || "");
    $("#folderPath").onchange = () => browseFolder($("#folderPath").value);
    const roles = ["front","back","label_a","label_b","inner_sleeve","other"];
    $("#rolesRow").innerHTML = roles.map((r,i)=>`<div class="row"><label>Pos ${i+1}</label>
      <select data-role="${i}">${roles.concat(["other"]).map(opt => `<option ${opt===r?"selected":""}>${opt}</option>`).join("")}</select></div>`).join("");
    $("#doImport").onclick = async () => {
      const payload = {folder: $("#folderPath").value || state.currentFolder, images_perRecord: parseInt($("#imagesPerRecord").value||"2",10)};
      const r = await (await fetch(API+"/api/import/start", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)})).json();
      if (r.warning) $("#importJob").innerHTML = `<div class="jobstatus">⚠ ${esc(r.warning)}</div>`;
      pollJob(r.job_id, $("#importJob"));
    };
  }

  // ---------- Settings + Enrich modals (shared helpers) ----------
  async function showAISettings(){
    const r = await (await fetch(API+"/api/settings")).json();
    openModal("AI Settings", `
      <div class="row"><label>Provider</label><select id="aiProv">
        <option ${r.ai_provider==="openai"?"selected":""}>openai</option>
        <option ${r.ai_provider==="anthropic"?"selected":""}>anthropic</option>
        <option ${r.ai_provider==="gemini"?"selected":""}>gemini</option>
      </select></div>
      <div class="row"><label>API key</label><input id="aiKey" placeholder="${r.ai_api_key_masked||"paste key"}" autocomplete="off"></div>
      <div class="row"><label>Model</label><input id="aiModel" value="${esc(r.ai_model)}"></div>
      <div class="row"><button class="secondary" id="testAI">Test</button><button class="primary" id="saveAI">Save</button></div>
      <div id="aiMsg" class="jobstatus"></div>
    `);
    $("#saveAI").onclick = async () => {
      const payload = {ai_provider:$("#aiProv").value, ai_model:$("#aiModel").value};
      if ($("#aiKey").value) payload.ai_api_key = $("#aiKey").value;
      await fetch(API+"/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
      $("#aiMsg").textContent = "Saved.";
    };
    $("#testAI").onclick = async () => {
      const r = await (await fetch(API+"/api/settings/test_ai", {method:"POST"})).json();
      $("#aiMsg").textContent = r.message || r.error;
    };
  }
  async function showDiscogsSettings(){
    const r = await (await fetch(API+"/api/settings")).json();
    openModal("Discogs Settings", `
      <p>To get a token:</p>
      <ol>
        <li>Sign in to <a href="https://www.discogs.com" target="_blank">discogs.com</a></li>
        <li>Click your avatar → <strong>Settings</strong></li>
        <li>Open the <strong>Developers</strong> tab</li>
        <li>Click <strong>Generate token</strong></li>
        <li>Paste it below</li>
      </ol>
      <div class="row"><label>Personal token</label><input id="dcToken" placeholder="${r.discogs_token_masked||"paste token"}" autocomplete="off"></div>
      <div class="row"><label>User-Agent</label><input id="dcUA" value="${esc(r.discogs_user_agent)}"></div>
      <div class="row"><button class="secondary" id="testDC">Test</button><button class="primary" id="saveDC">Save</button></div>
      <div id="dcMsg" class="jobstatus"></div>
    `);
    $("#saveDC").onclick = async () => {
      const payload = {discogs_user_agent:$("#dcUA").value};
      if ($("#dcToken").value) payload.discogs_token = $("#dcToken").value;
      await fetch(API+"/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
      $("#dcMsg").textContent = "Saved.";
    };
    $("#testDC").onclick = async () => {
      const r = await (await fetch(API+"/api/settings/test_discogs", {method:"POST"})).json();
      $("#dcMsg").textContent = r.message || r.error;
    };
  }

  // ---------- Enrich modals ----------
  async function showEnrich(kind){
    openModal(kind==="ai"?"Enrich with AI":"Enrich with Discogs", `
      <p>Choose which records to enrich.</p>
      <div class="row">
        <select id="scope">
          <option value="only_new">Only new (no AI data)</option>
          <option value="all">All records (warning: overwrites)</option>
          <option value="selected">Selected only</option>
        </select>
      </div>
      <div id="selectedList" class="folder-list"></div>
      <div class="row"><button class="primary" id="doEnrich">Start</button></div>
      <div id="jobOut"></div>
    `);
    const recs = (await (await fetch(API+"/api/records?limit=1000")).json()).records;
    state._enrichRecs = recs;
    $("#selectedList").innerHTML = recs.map(r => `<label class="item"><input type="checkbox" data-rid="${esc(r.id)}"> ${esc(r.artist||"?")} — ${esc(r.title||"")}</label>`).join("");
    const sync = () => {
      const isSel = $("#scope").value === "selected";
      $$("#selectedList input[type=checkbox]").forEach(c => c.disabled = !isSel);
    };
    $("#scope").onchange = sync; sync();
    $("#doEnrich").onclick = async () => {
      const scope = $("#scope").value;
      const ids = scope==="selected" ? $$("#selectedList input:checked").map(c => c.dataset.rid) : [];
      const url = kind==="ai" ? "/api/enrich/ai/start" : "/api/enrich/discogs/start";
      const r = await (await fetch(API+url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({scope, record_ids: ids})})).json();
      if (scope==="all") $("#jobOut").innerHTML = `<div class="jobstatus">⚠ Running on all ${r.record_count} records</div>` + $("#jobOut").innerHTML;
      pollJob(r.job_id, $("#jobOut"));
    };
  }

  async function pollJob(jobId, container){
    while (true){
      const r = await (await fetch(API+"/api/jobs/"+jobId)).json();
      const j = r.job;
      container.innerHTML = `
        <div class="row"><label>Job #${jobId}</label><div class="progress" style="flex:1"><div class="progress-bar" style="width:${j.percent||0}%"></div></div></div>
        <div class="jobstatus">${esc(j.status_text||"")} — ${j.done}/${j.total} (${Math.round(j.percent||0)}%, ETA ${j.eta_seconds||0}s)</div>
        <div class="row"><button class="secondary" id="cancelJob">Cancel</button></div>
      ` + (container.dataset.initial||"");
      $("#cancelJob").onclick = async () => { await fetch(API+"/api/jobs/"+jobId+"/cancel", {method:"POST"}); };
      if (["done","error","cancelled"].includes(j.state)) break;
      await new Promise(res => setTimeout(res, 700));
    }
  }

  async function showExport(){
    openModal("Export", `
      <p>Download the full catalogue in your preferred format.</p>
      <div class="row">
        <a class="secondary" href="/api/export?fmt=csv">⬇ CSV</a>
        <a class="secondary" href="/api/export?fmt=xlsx">⬇ Excel</a>
        <a class="secondary" href="/api/export?fmt=json">⬇ JSON</a>
        <a class="secondary" href="/api/export?fmt=html">⬇ Printable HTML</a>
      </div>
    `);
  }
  async function showBackup(){
    openModal("Export / Backup Database", `
      <p>Download a full backup (SQLite + images + manifest).</p>
      <div class="row"><a class="primary" href="/api/db/backup" style="text-decoration:none;padding:8px 16px;background:var(--acc);color:#fff;border-radius:8px">⬇ Download backup ZIP</a></div>
      <h4>Restore from ZIP</h4>
      <p>This replaces the current database. Make a backup first.</p>
      <input type="file" id="restoreFile" accept=".zip">
      <div id="restoreMsg" class="jobstatus"></div>
    `);
    $("#restoreFile").onchange = async () => {
      const f = $("#restoreFile").files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      const r = await (await fetch(API+"/api/db/restore", {method:"POST", body: fd})).json();
      $("#restoreMsg").textContent = r.ok ? "Restored." : ("Error: "+(r.detail||JSON.stringify(r)));
      if (r.ok) loadMeta();
    };
  }

  // ---------- wire up ----------
  $$(".sidebar button").forEach(b => b.onclick = () => {
    const k = b.dataset.modal;
    if (k==="import") showImport();
    else if (k==="ai_settings") showAISettings();
    else if (k==="ai_enrich") showEnrich("ai");
    else if (k==="discogs_settings") showDiscogsSettings();
    else if (k==="discogs_enrich") showEnrich("discogs");
    else if (k==="export") showExport();
    else if (k==="backup") showBackup();
  });

  // initial load
  loadMeta(); loadRecords();
})();
