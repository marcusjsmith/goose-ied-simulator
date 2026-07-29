/** IEC 61850 GOOSE IED Simulator – Web UI */

let ws = null;
let state = null;
let expandedMessageId = null;
let lastLogHeadId = null;
let userPinnedScroll = false;
let lastReadings = { v: null, i: null, p: null };
let lastAvailableLnKeys = '';
let lastActiveLnKeys = '';
let expandedLnKeys = new Set();

const API = {
  post: async (path, body = {}) => {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join(', ')
          : `Request failed (${res.status})`;
      throw new Error(msg);
    }
    return data;
  },
  state: () => fetch('/api/state').then(r => r.json()),
};

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onmessage = (evt) => {
    state = JSON.parse(evt.data);
    render(state);
  };

  ws.onclose = () => setTimeout(connectWebSocket, 2000);
}

function render(data) {
  updatePublisherStatus(data);
  updateSLD(data);
  updateFaultList(data);
  updateLNList(data);
  updateStats(data);
  updateLNSelect(data);
  updateGooseLog(data);
}

function updatePublisherStatus(data) {
  const pill = document.getElementById('publisher-status');
  const info = document.getElementById('goose-info');
  const running = data.publisher_running;

  pill.classList.toggle('running', running);
  pill.querySelector('span:last-child').textContent = running ? 'Publisher Running' : 'Publisher Stopped';

  document.getElementById('goose-path')?.classList.toggle('active', running);
  document.getElementById('switch-led')?.classList.toggle('active', running);

  if (data.goose_config) {
    info.textContent = `${data.goose_config.dst_mac} · APPID ${data.goose_config.app_id}`;
    document.getElementById('goose-mac').textContent = data.goose_config.dst_mac;
  }
}

function updateSLD(data) {
  const breakerBox = document.getElementById('breaker-box');
  const breakerText = document.getElementById('breaker-text');
  const swBlade = document.getElementById('sw-blade');
  const faultOverlay = document.getElementById('fault-overlay');
  const faultText = document.getElementById('fault-text');
  const iedLed = document.getElementById('ied-led');

  breakerBox.classList.remove('open', 'tripping');
  swBlade.classList.remove('open');

  if (data.breaker_state === 'open') {
    breakerBox.classList.add('open');
    breakerText.textContent = 'O';
    swBlade.classList.add('open');
  } else if (data.breaker_state === 'tripping') {
    breakerBox.classList.add('tripping');
    breakerText.textContent = '!';
  } else {
    breakerText.textContent = 'CB';
  }

  const mmxu = data.active_nodes?.find(n => n.key === 'MMXU1');
  if (mmxu) {
    const v = mmxu.values['PhV.phsA.cVal.mag.f'];
    const i = mmxu.values['A.phsA.cVal.mag.f'];
    const p = mmxu.values['TotW.mag.f'];
    const f = mmxu.values['Hz.mag.f'];

    const vText = `${Number(v).toFixed(1)} kV`;
    const iText = `${Number(i).toFixed(0)} A`;
    const pText = `${Number(p).toFixed(2)} MW`;
    const fText = `${Number(f).toFixed(2)} Hz`;

    flashReading('ied-voltage', v, lastReadings.v);
    flashReading('ied-current', i, lastReadings.i);
    flashReading('ied-power', p, lastReadings.p);
    flashReading('load-power', p, lastReadings.p);

    document.getElementById('ied-voltage').textContent = vText;
    document.getElementById('ied-current').textContent = iText;
    document.getElementById('ied-power').textContent = pText;
    document.getElementById('ied-freq').textContent = fText;
    document.getElementById('load-power').textContent = pText;

    lastReadings = { v, i, p };
  }

  if (data.active_fault && data.active_fault !== 'none') {
    faultOverlay.classList.remove('hidden');
    const fault = data.faults?.find(f => f.type === data.active_fault);
    faultText.textContent = fault ? fault.name.toUpperCase() : 'FAULT';
    iedLed.classList.add('fault');
  } else {
    faultOverlay.classList.add('hidden');
    iedLed.classList.remove('fault');
  }
}

function flashReading(elementId, value, prev) {
  if (prev == null || value === prev) return;
  const el = document.getElementById(elementId);
  if (!el) return;
  el.classList.add('live-flash');
  setTimeout(() => el.classList.remove('live-flash'), 400);
}

function updateFaultList(data) {
  const container = document.getElementById('fault-list');
  if (!data.faults) return;

  container.innerHTML = data.faults.map(f => `
    <button class="fault-btn ${data.active_fault === f.type ? 'active' : ''}"
            style="border-left-color: ${f.color}"
            data-fault="${f.type}">
      <span class="fname">${f.name}</span>
      <span class="fdesc">${f.description}</span>
    </button>
  `).join('');

  container.querySelectorAll('.fault-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      API.post('/api/fault/apply', { fault_type: btn.dataset.fault });
    });
  });
}

function updateLNSelect(data) {
  const select = document.getElementById('ln-add-select');
  const btnAdd = document.getElementById('btn-add-ln');
  const available = (data.available_lns || []).filter(ln => !ln.active);
  const keys = available.map(ln => ln.key).join(',');

  if (keys === lastAvailableLnKeys && select.options.length > 0) {
    return;
  }
  lastAvailableLnKeys = keys;

  const previous = select.value;
  if (!available.length) {
    select.innerHTML = '<option value="">All nodes active</option>';
    select.disabled = true;
    btnAdd.disabled = true;
    return;
  }

  select.disabled = false;
  btnAdd.disabled = false;
  select.innerHTML = available.map(ln =>
    `<option value="${ln.key}">${ln.ln_name} – ${ln.description}</option>`
  ).join('');

  if (previous && available.some(ln => ln.key === previous)) {
    select.value = previous;
  }
}

function updateLNList(data) {
  const container = document.getElementById('ln-list');
  if (!data.active_nodes) return;

  const keys = data.active_nodes.map(n => n.key).join(',');
  const structureChanged = keys !== lastActiveLnKeys;
  lastActiveLnKeys = keys;

  if (!structureChanged && container.children.length > 0) {
    data.active_nodes.forEach(node => {
      const card = container.querySelector(`.ln-card[data-ln="${node.key}"]`);
      if (!card) return;
      node.available_attributes.forEach(a => {
        const row = card.querySelector(`.attr-toggle[data-da="${a.name}"]`)?.closest('.attr-row');
        if (!row) return;
        const val = node.values[a.name];
        const displayVal = typeof val === 'boolean' ? (val ? 'TRUE' : 'false') : val;
        const valEl = row.querySelector('.attr-val');
        if (valEl) valEl.textContent = displayVal;
      });
    });
    return;
  }

  container.querySelectorAll('.ln-card.expanded').forEach(card => {
    expandedLnKeys.add(card.dataset.ln);
  });

  container.innerHTML = data.active_nodes.map(node => {
    const expanded = expandedLnKeys.has(node.key);
    const attrs = node.available_attributes.map(a => {
      const enabled = node.enabled_attributes.includes(a.name);
      const val = node.values[a.name];
      const displayVal = typeof val === 'boolean' ? (val ? 'TRUE' : 'false') : val;
      return `
        <div class="attr-row">
          <input type="checkbox" ${enabled ? 'checked' : ''}
                 data-ln="${node.key}" data-da="${a.name}" class="attr-toggle">
          <label title="${a.description}">${a.name}</label>
          <span class="attr-val">${displayVal}</span>
        </div>`;
    }).join('');

    return `
      <div class="ln-card ${expanded ? 'expanded' : ''}" data-ln="${node.key}">
        <div class="ln-card-header">
          <div>
            <div class="ln-name">${node.ln_name}</div>
            <div class="ln-desc">${node.description}</div>
          </div>
          <button type="button" class="ln-remove" data-ln="${node.key}" title="Remove from GOOSE dataset">×</button>
        </div>
        <div class="ln-attrs">${attrs}</div>
      </div>`;
  }).join('');

  container.querySelectorAll('.ln-card-header').forEach(hdr => {
    hdr.addEventListener('click', (e) => {
      if (e.target.classList.contains('ln-remove')) return;
      const key = hdr.parentElement.dataset.ln;
      hdr.parentElement.classList.toggle('expanded');
      if (hdr.parentElement.classList.contains('expanded')) {
        expandedLnKeys.add(key);
      } else {
        expandedLnKeys.delete(key);
      }
    });
  });

  container.querySelectorAll('.ln-remove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      API.post('/api/logical-nodes/remove', { ln_key: btn.dataset.ln })
        .then(refreshState)
        .catch(showError);
    });
  });

  container.querySelectorAll('.attr-toggle').forEach(cb => {
    cb.addEventListener('change', () => {
      API.post('/api/logical-nodes/attribute', {
        ln_key: cb.dataset.ln,
        da_name: cb.dataset.da,
        enabled: cb.checked,
      }).catch(showError);
    });
  });
}

async function refreshState() {
  render(await API.state());
}

function showError(err) {
  console.error(err);
  const msg = typeof err.message === 'string' ? err.message : 'Request failed';
  alert(msg);
}

function updateStats(data) {
  const stats = data.goose_stats || {};
  document.getElementById('stat-stnum').textContent = stats.st_num ?? '—';
  document.getElementById('stat-sqnum').textContent = stats.sq_num ?? '—';
  document.getElementById('stat-entries').textContent = stats.entries ?? '—';
  document.getElementById('stat-frame').textContent = stats.frame_len ? `${stats.frame_len} B` : '—';
}

function formatLogTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
}

function renderPayloadGrid(entries) {
  return `<dl class="payload-grid">${entries.map(([k, v]) =>
    `<dt>${k}</dt><dd>${v}</dd>`
  ).join('')}</dl>`;
}

function renderMessageBody(msg) {
  const eth = msg.ethernet || {};
  const pdu = msg.goose_pdu || {};
  const dataset = msg.dataset || [];

  const ethGrid = renderPayloadGrid([
    ['Destination MAC', eth.dst_mac || '—'],
    ['Source MAC', eth.src_mac || '—'],
    ['EtherType', eth.ethertype || '—'],
    ['APPID', eth.app_id || '—'],
    ['Length', eth.length != null ? `${eth.length} bytes` : '—'],
  ]);

  const pduGrid = renderPayloadGrid([
    ['gocbRef', pdu.gocb_ref || '—'],
    ['datSet', pdu.dat_set || '—'],
    ['goID', pdu.go_id || '—'],
    ['timeAllowedToLive', pdu.time_allowed_to_live_ms != null ? `${pdu.time_allowed_to_live_ms} ms` : '—'],
    ['t', pdu.timestamp || '—'],
    ['stNum', pdu.st_num ?? '—'],
    ['sqNum', pdu.sq_num ?? '—'],
    ['confRev', pdu.conf_rev ?? '—'],
    ['test', pdu.test ? 'TRUE' : 'FALSE'],
    ['ndsCom', pdu.nds_com ? 'TRUE' : 'FALSE'],
    ['numDatSetEntries', pdu.num_dat_set_entries ?? '—'],
  ]);

  const datasetRows = dataset.map(row => `
    <tr>
      <td class="col-idx">${row.index}</td>
      <td>${row.ref}</td>
      <td class="col-type">${row.mms_type}</td>
      <td class="col-val">${row.value}</td>
      <td class="col-hex">${row.encoded_hex}</td>
    </tr>
  `).join('');

  const datasetTable = dataset.length ? `
    <table class="dataset-table">
      <thead>
        <tr>
          <th>#</th><th>Reference</th><th>Type</th><th>Value</th><th>BER Hex</th>
        </tr>
      </thead>
      <tbody>${datasetRows}</tbody>
    </table>
  ` : '<div class="goose-log-empty">No dataset entries</div>';

  const hexPreview = msg.frame_hex
    ? `<div class="frame-hex">${msg.frame_hex.match(/.{1,2}/g)?.join(' ') || msg.frame_hex}</div>`
    : '';

  return `
    <div class="payload-section">
      <div class="payload-section-title">Ethernet Header</div>
      ${ethGrid}
    </div>
    <div class="payload-section">
      <div class="payload-section-title">GOOSE PDU</div>
      ${pduGrid}
    </div>
    <div class="payload-section">
      <div class="payload-section-title">Dataset Payload (${dataset.length} entries)</div>
      ${datasetTable}
    </div>
    <div class="payload-section">
      <div class="payload-section-title">Full Frame Hex (${msg.frame_len || 0} bytes)</div>
      ${hexPreview}
    </div>
  `;
}

function updateGooseLog(data) {
  const log = data.goose_message_log || [];
  const windowEl = document.getElementById('goose-log-window');
  const countEl = document.getElementById('goose-log-count');

  countEl.textContent = `${log.length} message${log.length === 1 ? '' : 's'}`;

  if (!log.length) {
    windowEl.innerHTML = '<div class="goose-log-empty">Start GOOSE publishing to see live messages and payload breakout here.</div>';
    expandedMessageId = null;
    lastLogHeadId = null;
    return;
  }

  const headId = log[0]?.id ?? null;
  if (headId !== lastLogHeadId) {
    expandedMessageId = headId;
    lastLogHeadId = headId;
  }

  const wasAtTop = windowEl.scrollTop < 20;
  windowEl.innerHTML = log.map(msg => {
    const isStateChange = msg.state_change;
    const badgeClass = isStateChange ? 'state-change' : 'retransmit';
    const badgeText = isStateChange ? 'STATE CHANGE' : 'RETRANSMIT';
    const expanded = msg.id === expandedMessageId;
    const pdu = msg.goose_pdu || {};

    return `
      <div class="goose-msg ${isStateChange ? 'state-change' : ''} ${expanded ? 'expanded' : ''}" data-id="${msg.id}">
        <div class="goose-msg-header">
          <span class="goose-msg-time">${formatLogTime(msg.time)}</span>
          <span class="goose-msg-badge ${badgeClass}">${badgeText}</span>
          <span class="goose-msg-summary">
            stNum=<span>${pdu.st_num ?? '—'}</span>
            sqNum=<span>${pdu.sq_num ?? '—'}</span>
            · ${msg.frame_len || 0}B
            · ${pdu.num_dat_set_entries ?? 0} entries
          </span>
          <span class="goose-msg-toggle">▼</span>
        </div>
        <div class="goose-msg-body">${renderMessageBody(msg)}</div>
      </div>
    `;
  }).join('');

  if (wasAtTop && !userPinnedScroll) {
    windowEl.scrollTop = 0;
  }
}

document.getElementById('goose-log-window')?.addEventListener('scroll', (e) => {
  userPinnedScroll = e.target.scrollTop > 30;
});

document.getElementById('goose-log-window')?.addEventListener('click', (e) => {
  const hdr = e.target.closest('.goose-msg-header');
  if (!hdr) return;
  const msgEl = hdr.closest('.goose-msg');
  if (!msgEl) return;
  const id = Number(msgEl.dataset.id);
  expandedMessageId = expandedMessageId === id ? null : id;
  document.querySelectorAll('#goose-log-window .goose-msg').forEach(el => {
    el.classList.toggle('expanded', Number(el.dataset.id) === expandedMessageId);
  });
});

document.getElementById('btn-start').addEventListener('click', () => API.post('/api/publisher/start'));
document.getElementById('btn-stop').addEventListener('click', () => API.post('/api/publisher/stop'));
document.getElementById('btn-publish').addEventListener('click', () => API.post('/api/publisher/publish'));
document.getElementById('btn-clear-log').addEventListener('click', () => {
  expandedMessageId = null;
  lastLogHeadId = null;
  userPinnedScroll = false;
  API.post('/api/goose/messages/clear');
});
document.getElementById('btn-toggle-breaker').addEventListener('click', () => API.post('/api/breaker/toggle'));
document.getElementById('btn-clear-fault').addEventListener('click', () => API.post('/api/fault/clear'));
document.getElementById('btn-add-ln').addEventListener('click', async () => {
  const select = document.getElementById('ln-add-select');
  const lnKey = select.value;
  if (!lnKey) return;
  try {
    await API.post('/api/logical-nodes/add', { ln_key: lnKey });
    expandedLnKeys.add(lnKey);
    lastAvailableLnKeys = '';
    await refreshState();
  } catch (err) {
    showError(err);
  }
});

connectWebSocket();
fetch('/api/state').then(r => r.json()).then(render);
