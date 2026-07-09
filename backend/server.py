<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Sherlock — Candidate Identification</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#12151c;
    --ink-2:#1b1f29;
    --paper:#efe9db;
    --paper-dim:#c9c0aa;
    --rule:#3a3f4d;
    --gold:#c9a24a;
    --rust:#b3441e;
    --sage:#4a7c72;
    --sage-dim:#2c463f;
    --text:#efe9db;
    --text-dim:#9aa0ad;
    --serif:'Source Serif 4', Georgia, serif;
    --mono:'IBM Plex Mono', 'Courier New', monospace;
  }
  *{box-sizing:border-box; margin:0; padding:0;}
  body{
    background:
      radial-gradient(ellipse at top left, #1a1f2b 0%, var(--ink) 55%),
      var(--ink);
    color:var(--text);
    font-family:var(--serif);
    min-height:100vh;
    padding:32px 20px 80px;
  }
  ::selection{background:var(--rust); color:var(--paper);}

  .wrap{max-width:1040px; margin:0 auto;}

  /* ---------- Header / case label ---------- */
  header{
    display:flex; align-items:flex-end; justify-content:space-between;
    border-bottom:2px solid var(--gold);
    padding-bottom:18px; margin-bottom:28px;
    flex-wrap:wrap; gap:16px;
  }
  .brand{display:flex; align-items:baseline; gap:14px;}
  .brand h1{
    font-size:30px; letter-spacing:0.5px; font-weight:700;
    font-family:var(--serif);
  }
  .brand .case-tag{
    font-family:var(--mono); font-size:11px; letter-spacing:1.5px;
    color:var(--gold); text-transform:uppercase;
    border:1px solid var(--gold); border-radius:2px;
    padding:3px 8px;
  }
  .status-line{
    font-family:var(--mono); font-size:12px; color:var(--text-dim);
    display:flex; align-items:center; gap:8px;
  }
  .dot{width:8px; height:8px; border-radius:50%; background:var(--rule); display:inline-block; transition:background .3s;}
  .dot.live{background:var(--sage); box-shadow:0 0 8px var(--sage);}
  .dot.err{background:var(--rust); box-shadow:0 0 8px var(--rust);}

  /* ---------- Intake form ---------- */
  .intake{
    background:var(--ink-2); border:1px solid var(--rule); border-radius:6px;
    padding:22px 24px; margin-bottom:32px;
  }
  .intake h2{
    font-family:var(--mono); font-size:12px; letter-spacing:2px; text-transform:uppercase;
    color:var(--gold); margin-bottom:16px; font-weight:600;
  }
  .intake-grid{
    display:grid; grid-template-columns:1fr 1fr; gap:14px;
  }
  @media(max-width:640px){ .intake-grid{grid-template-columns:1fr;} }
  .field label{
    display:block; font-family:var(--mono); font-size:10.5px; letter-spacing:1px;
    text-transform:uppercase; color:var(--text-dim); margin-bottom:6px;
  }
  .field input{
    width:100%; background:var(--ink); border:1px solid var(--rule); border-radius:4px;
    padding:9px 11px; color:var(--text); font-family:var(--mono); font-size:13px;
    outline:none; transition:border-color .2s;
  }
  .field input:focus{border-color:var(--gold);}
  .field input::placeholder{color:#555b6b;}
  .intake-actions{
    display:flex; gap:10px; margin-top:18px; align-items:center; flex-wrap:wrap;
  }
  button{
    font-family:var(--mono); font-size:12px; letter-spacing:1px; text-transform:uppercase;
    font-weight:600; border-radius:4px; border:1px solid transparent; cursor:pointer;
    padding:10px 18px; transition:all .15s;
  }
  .btn-primary{background:var(--gold); color:var(--ink); border-color:var(--gold);}
  .btn-primary:hover{background:#dab766;}
  .btn-primary:disabled{opacity:0.4; cursor:not-allowed;}
  .btn-ghost{background:transparent; color:var(--text-dim); border-color:var(--rule);}
  .btn-ghost:hover{color:var(--text); border-color:var(--text-dim);}
  .intake-note{font-family:var(--mono); font-size:11px; color:var(--text-dim); margin-left:auto;}

  /* ---------- Board ---------- */
  .board{display:none;}
  .board.active{display:block;}

  .meta-strip{
    display:flex; gap:28px; flex-wrap:wrap; margin-bottom:26px;
    font-family:var(--mono); font-size:12px; color:var(--text-dim);
  }
  .meta-strip b{color:var(--text); font-weight:600;}

  .empty-state{
    text-align:center; padding:60px 20px; color:var(--text-dim);
    font-family:var(--mono); font-size:13px; border:1px dashed var(--rule); border-radius:6px;
  }

  .dossier{
    background:var(--paper); color:#1c1a14; border-radius:6px;
    margin-bottom:22px; overflow:hidden; position:relative;
    box-shadow:0 6px 24px rgba(0,0,0,0.35);
    border-left:5px solid var(--paper-dim);
    transition:border-color .4s;
  }
  .dossier.leading{border-left-color:var(--rust);}
  .dossier.cleared{border-left-color:var(--sage);}

  .dossier-top{
    display:flex; justify-content:space-between; align-items:flex-start;
    padding:20px 24px 14px; gap:16px; flex-wrap:wrap;
  }
  .dossier-id{display:flex; flex-direction:column; gap:4px;}
  .dossier-name{font-size:22px; font-weight:700; font-family:var(--serif);}
  .dossier-sub{font-family:var(--mono); font-size:11px; color:#6b6552; letter-spacing:0.5px;}

  .stamp{
    font-family:var(--mono); font-weight:700; font-size:12px; letter-spacing:2px;
    padding:6px 12px; border:2px solid currentColor; border-radius:3px;
    transform:rotate(-4deg); text-transform:uppercase; white-space:nowrap;
  }
  .stamp.candidate{color:var(--rust);}
  .stamp.cleared{color:var(--sage-dim);}
  .stamp.pending{color:#8a8163; border-style:dashed;}

  .score-row{
    padding:0 24px 18px; display:flex; align-items:center; gap:14px;
  }
  .score-bar-track{
    flex:1; height:10px; background:#dcd4bd; border-radius:6px; overflow:hidden;
  }
  .score-bar-fill{
    height:100%; border-radius:6px; transition:width .5s ease, background .5s ease;
  }
  .score-num{font-family:var(--mono); font-weight:700; font-size:14px; min-width:52px; text-align:right;}

  .signals-wrap{border-top:1px solid #d8cfb4; padding:14px 24px 22px;}
  .signals-heading{
    font-family:var(--mono); font-size:10.5px; letter-spacing:1.5px; text-transform:uppercase;
    color:#8a8163; margin-bottom:10px; font-weight:600;
  }
  table.signal-table{width:100%; border-collapse:collapse; font-family:var(--mono);}
  .signal-table thead th{
    text-align:left; font-size:10px; letter-spacing:1px; text-transform:uppercase;
    color:#8a8163; font-weight:600; padding:0 10px 8px 0; border-bottom:1px solid #d8cfb4;
  }
  .signal-table thead th.num{text-align:right;}
  .signal-table tbody td{
    padding:9px 10px 9px 0; border-bottom:1px solid #e9e2cc; vertical-align:top; font-size:12px;
  }
  .signal-table tbody tr:last-child td{border-bottom:none;}
  .signal-table td.num{text-align:right; font-weight:600; white-space:nowrap;}
  .signal-name{color:#2c2a20; font-weight:700; white-space:nowrap;}
  .signal-reason-cell{color:#6b6552; line-height:1.5;}
  .evidence-line{
    display:block; margin-top:3px; font-size:10.5px; color:#a39a7f;
  }

  .p-meta{
    display:flex; flex-wrap:wrap; gap:6px 18px; padding:0 24px 14px;
    font-family:var(--mono); font-size:11px; color:#6b6552;
  }
  .p-meta span b{color:#2c2a20;}

  /* ---------- Activity log ---------- */
  .log-panel{
    background:var(--ink-2); border:1px solid var(--rule); border-radius:6px;
    margin-top:30px; padding:18px 22px 8px;
  }
  .log-heading{
    font-family:var(--mono); font-size:11px; letter-spacing:2px; text-transform:uppercase;
    color:var(--gold); margin-bottom:12px; font-weight:600;
    display:flex; justify-content:space-between; align-items:center;
  }
  .log-heading .clear-log{
    font-size:10px; letter-spacing:1px; color:var(--text-dim); cursor:pointer; text-transform:none;
    background:none; border:none; padding:0;
  }
  .log-heading .clear-log:hover{color:var(--text);}
  .log-list{max-height:340px; overflow-y:auto;}
  .log-row{
    display:grid; grid-template-columns:78px 150px 1fr 60px; gap:12px; align-items:baseline;
    font-family:var(--mono); font-size:11.5px; padding:8px 0; border-bottom:1px solid var(--rule);
  }
  .log-row:last-child{border-bottom:none;}
  .log-time{color:var(--text-dim);}
  .log-event{color:var(--gold); font-weight:600;}
  .log-detail{color:var(--text-dim);}
  .log-detail b{color:var(--text);}
  .log-conf{text-align:right; font-weight:700;}
  .log-empty{color:var(--text-dim); font-size:12px; padding:10px 0 16px;}

  footer{
    text-align:center; margin-top:40px; font-family:var(--mono); font-size:11px; color:#4d5262;
  }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="brand">
      <h1>Sherlock</h1>
      <span class="case-tag">Candidate Identification</span>
    </div>
    <div class="status-line"><span class="dot" id="statusDot"></span><span id="statusText">Awaiting case file</span></div>
  </header>

  <div class="intake" id="intake">
    <h2>Open Case File</h2>
    <div class="intake-grid">
      <div class="field">
        <label for="apiBase">Backend URL</label>
        <input id="apiBase" type="text" value="https://truecandidate.onrender.com" placeholder="https://your-backend.onrender.com" />
      </div>
      <div class="field">
        <label for="meetingId">Meeting ID</label>
        <input id="meetingId" type="text" placeholder="e.g. 9763851399" />
      </div>
    </div>
    <div class="intake-actions">
      <button class="btn-primary" id="connectBtn">Open Case</button>
      <button class="btn-ghost" id="disconnectBtn" style="display:none;">Close Case</button>
      <span class="intake-note" id="intakeNote"></span>
    </div>
  </div>

  <div class="board" id="board">
    <div class="meta-strip" id="metaStrip"></div>
    <div id="dossierList"></div>
    <div class="log-panel">
      <div class="log-heading">
        <span>Activity Log</span>
        <button class="clear-log" id="clearLogBtn">Clear</button>
      </div>
      <div class="log-list" id="logList">
        <div class="log-empty">No events received yet.</div>
      </div>
    </div>
  </div>

  <footer>Live evidence stream via WebSocket — signals update as participants act</footer>
</div>

<script>
(function(){
  const $ = (id) => document.getElementById(id);
  const statusDot = $('statusDot');
  const statusText = $('statusText');
  const intakeNote = $('intakeNote');
  const connectBtn = $('connectBtn');
  const disconnectBtn = $('disconnectBtn');
  const board = $('board');
  const metaStrip = $('metaStrip');
  const dossierList = $('dossierList');
  const logList = $('logList');
  const clearLogBtn = $('clearLogBtn');

  // Restore last-used values for convenience
  try{
    const savedBase = localStorage.getItem('sherlock_api_base');
    const savedMeeting = localStorage.getItem('sherlock_meeting_id');
    if(savedBase) $('apiBase').value = savedBase;
    if(savedMeeting) $('meetingId').value = savedMeeting;
  }catch(e){}

  let ws = null;
  let currentMeetingId = null;
  let currentContext = null;
  let currentState = { participants: {}, event_count: 0 };
  let eventLog = [];

  const SIGNAL_ORDER = ['name_match','email_match','interviewer_exclusion','speaking_pattern','transcript_language','join_order','screen_share'];

  function setStatus(mode, text){
    statusDot.className = 'dot' + (mode ? ' ' + mode : '');
    statusText.textContent = text;
  }

  function httpBase(){
    return $('apiBase').value.trim().replace(/\/$/, '');
  }
  function wsBase(){
    return httpBase().replace(/^http/, 'ws');
  }

  async function fetchState(meetingId){
    const res = await fetch(`${httpBase()}/api/meeting/${encodeURIComponent(meetingId)}`);
    if(!res.ok){
      throw new Error(res.status === 404 ? 'No case file found for that meeting ID yet.' : `Server returned ${res.status}`);
    }
    return res.json();
  }

  function connectSocket(meetingId){
    const url = `${wsBase()}/ws/${encodeURIComponent(meetingId)}`;
    ws = new WebSocket(url);

    ws.onopen = () => setStatus('live', 'Live — receiving evidence');
    ws.onerror = () => setStatus('err', 'Connection error');
    ws.onclose = () => setStatus('', 'Disconnected');

    ws.onmessage = (evt) => {
      let msg;
      try{ msg = JSON.parse(evt.data); }catch(e){ return; }

      if(msg.type === 'connected'){
        currentContext = msg.context;
        currentState = msg.state || currentState;
        renderAll();
      } else if(msg.type === 'meeting_event'){
        currentState = msg.state || currentState;
        recordLogEntry(msg);
        renderAll();
      } else if(msg.type === 'error'){
        setStatus('err', msg.message || 'Server error');
      } else if(msg.type === 'scenario_complete'){
        setStatus('live', 'Scenario complete — case remains open');
      }
    };
  }

  async function openCase(){
    const meetingId = $('meetingId').value.trim();
    if(!meetingId){
      intakeNote.textContent = 'Enter a meeting ID first.';
      return;
    }
    try{ localStorage.setItem('sherlock_api_base', httpBase()); localStorage.setItem('sherlock_meeting_id', meetingId); }catch(e){}

    connectBtn.disabled = true;
    intakeNote.textContent = 'Opening case file…';
    setStatus('', 'Connecting…');

    try{
      const data = await fetchState(meetingId);
      currentContext = data.context;
      currentState = data;
      currentMeetingId = meetingId;

      board.classList.add('active');
      disconnectBtn.style.display = 'inline-block';
      intakeNote.textContent = '';
      renderAll();
      connectSocket(meetingId);
    }catch(err){
      intakeNote.textContent = err.message || 'Could not open case file.';
      setStatus('err', 'Failed to load');
    }finally{
      connectBtn.disabled = false;
    }
  }

  function closeCase(){
    if(ws){ ws.close(); ws = null; }
    currentMeetingId = null;
    board.classList.remove('active');
    disconnectBtn.style.display = 'none';
    setStatus('', 'Awaiting case file');
  }

  function renderAll(){
    if(!currentContext) return;

    const ctx = currentContext;
    metaStrip.innerHTML = `
      <div>Candidate: <b>${escapeHtml(ctx.candidate_name || '—')}</b></div>
      <div>Role: <b>${escapeHtml(ctx.job_title || '—')}</b></div>
      <div>Meeting ID: <b>${escapeHtml(ctx.meeting_id || currentMeetingId)}</b></div>
      <div>Events observed: <b>${currentState.event_count ?? 0}</b></div>
    `;

    const participants = Object.values(currentState.participants || {});
    if(participants.length === 0){
      dossierList.innerHTML = `<div class="empty-state">No participants have joined yet. Dossiers will appear here as evidence arrives.</div>`;
      return;
    }

    participants.sort((a,b) => (b.composite_score||0) - (a.composite_score||0));
    const topScore = participants[0].composite_score || 0;

    dossierList.innerHTML = participants.map((p, idx) => renderDossier(p, idx === 0 && topScore >= 0.6)).join('');
    renderLog();
  }

  function renderDossier(p){
    const score = p.composite_score ?? 0.5;
    const pct = Math.round(score * 100);
    let cls = '', stampHtml = '';

    if(score >= 0.7){
      cls = 'leading';
      stampHtml = `<div class="stamp candidate">Likely Candidate</div>`;
    } else if(score <= 0.3){
      cls = 'cleared';
      stampHtml = `<div class="stamp cleared">Likely Interviewer</div>`;
    } else {
      stampHtml = `<div class="stamp pending">Under Review</div>`;
    }

    const barColor = score >= 0.7 ? 'var(--rust)' : (score <= 0.3 ? 'var(--sage)' : 'var(--gold)');

    const rows = SIGNAL_ORDER
      .filter(k => p.signals && p.signals[k])
      .map(k => {
        const s = p.signals[k];
        const evidenceEntries = Object.entries(s.evidence || {}).filter(([k,v]) => v !== null && v !== undefined && v !== '');
        const evidenceStr = evidenceEntries.map(([k,v]) => `${k}: ${typeof v === 'number' ? v : v}`).join('  ·  ');
        return `
          <tr>
            <td class="signal-name">${escapeHtml(s.label)}</td>
            <td class="num">${s.score.toFixed(2)}</td>
            <td class="num">${(s.signal_confidence ?? 0).toFixed(2)}</td>
            <td class="num">${(s.weight ?? 0).toFixed(2)}</td>
            <td class="num">${(s.effective_weight ?? 0).toFixed(3)}</td>
            <td class="signal-reason-cell">${escapeHtml(s.reason)}${evidenceStr ? `<span class="evidence-line">${escapeHtml(evidenceStr)}</span>` : ''}</td>
          </tr>
        `;
      }).join('');

    const nameHistory = (p.name_history || []).join(' → ');
    const metaParts = [
      `<span>Speaking: <b>${(p.speaking_duration ?? 0).toFixed(1)}s</b> across <b>${p.speaking_turns ?? 0}</b> turns (avg ${(p.avg_turn_length ?? 0).toFixed(1)}s, longest ${(p.longest_speaking_turn ?? 0).toFixed(1)}s)</span>`,
      `<span>Screen share: <b>${p.has_shared_screen ? 'yes' : 'no'}</b></span>`,
      `<span>Webcam: <b>${p.webcam_on ? 'on' : 'off'}</b></span>`,
      `<span>Transcript words: <b>${p.transcript_word_count ?? 0}</b></span>`,
      `<span>Active: <b>${p.is_active ? 'yes' : 'no'}</b></span>`,
    ];
    if(nameHistory) metaParts.push(`<span>Name history: <b>${escapeHtml(nameHistory)}</b></span>`);

    return `
      <div class="dossier ${cls}">
        <div class="dossier-top">
          <div class="dossier-id">
            <div class="dossier-name">${escapeHtml(p.display_name || 'Unknown')}</div>
            <div class="dossier-sub">ID ${escapeHtml(p.participant_id)} · joined position #${p.join_order} ${p.email ? '· ' + escapeHtml(p.email) : ''}</div>
          </div>
          ${stampHtml}
        </div>
        <div class="score-row">
          <div class="score-bar-track"><div class="score-bar-fill" style="width:${pct}%; background:${barColor};"></div></div>
          <div class="score-num">${pct}%</div>
        </div>
        <div class="p-meta">${metaParts.join('')}</div>
        <div class="signals-wrap">
          <div class="signals-heading">Evidence breakdown — ${SIGNAL_ORDER.filter(k=>p.signals&&p.signals[k]).length} signals</div>
          <table class="signal-table">
            <thead>
              <tr>
                <th>Signal</th>
                <th class="num">Score</th>
                <th class="num">Confidence</th>
                <th class="num">Weight</th>
                <th class="num">Effective</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function recordLogEntry(msg){
    const ev = msg.event || {};
    const ident = msg.identification || {};
    const state = msg.state || currentState;
    const p = (state.participants || {})[ev.participant_id] || {};

    eventLog.unshift({
      timestamp: ev.timestamp || Date.now()/1000,
      eventType: ev.event_type || 'unknown',
      participantName: p.display_name || ev.participant_id || '—',
      participantId: ev.participant_id,
      data: ev.data || {},
      candidateName: ident.candidate_display_name || null,
      confidence: typeof ident.confidence === 'number' ? ident.confidence : null,
      isLocked: !!ident.is_locked,
    });
    if(eventLog.length > 200) eventLog.length = 200; // cap growth
  }

  function renderLog(){
    if(eventLog.length === 0){
      logList.innerHTML = `<div class="log-empty">No events received yet.</div>`;
      return;
    }
    logList.innerHTML = eventLog.map(e => {
      const t = new Date(e.timestamp * 1000);
      const timeStr = t.toLocaleTimeString([], {hour12:false});
      const dataStr = Object.entries(e.data || {})
        .filter(([k,v]) => v !== null && v !== undefined && v !== '')
        .map(([k,v]) => `${k}=${v}`).join(', ');
      const confStr = e.confidence !== null ? Math.round(e.confidence*100) + '%' : '—';
      const confColor = e.confidence === null ? '#6b7280' : (e.confidence >= 0.7 ? 'var(--rust)' : (e.confidence <= 0.3 ? 'var(--sage)' : 'var(--gold)'));
      return `
        <div class="log-row">
          <div class="log-time">${timeStr}</div>
          <div class="log-event">${escapeHtml(e.eventType)}</div>
          <div class="log-detail"><b>${escapeHtml(e.participantName)}</b>${dataStr ? ' — ' + escapeHtml(dataStr) : ''}${e.candidateName ? ' · leading: <b>' + escapeHtml(e.candidateName) + '</b>' : ''}</div>
          <div class="log-conf" style="color:${confColor};">${confStr}</div>
        </div>
      `;
    }).join('');
  }

  clearLogBtn.addEventListener('click', () => { eventLog = []; renderLog(); });

  function escapeHtml(str){
    if(str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  connectBtn.addEventListener('click', openCase);
  disconnectBtn.addEventListener('click', closeCase);
  $('meetingId').addEventListener('keydown', (e) => { if(e.key === 'Enter') openCase(); });
})();
</script>
</body>
</html>
