/** IEC 61850 GOOSE IED Simulator – Web UI */

let ws = null;
let state = null;

const API = {
  post: (path, body = {}) =>
    fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json()),
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
}

function updatePublisherStatus(data) {
  const pill = document.getElementById('publisher-status');
  const info = document.getElementById('goose-info');
  const running = data.publisher_running;

  pill.classList.toggle('running', running);
  pill.querySelector('span:last-child').textContent = running ? 'Publisher Running' : 'Publisher Stopped';

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
    document.getElementById('ied-voltage').textContent = `${Number(v).toFixed(1)} kV`;
    document.getElementById('ied-current').textContent = `${Number(i).toFixed(0)} A`;
    document.getElementById('ied-power').textContent = `${Number(p).toFixed(1)} MW`;
    document.getElementById('ied-freq').textContent = `${Number(f).toFixed(1)} Hz`;
    document.getElementById('load-power').textContent = `${Number(p).toFixed(1)} MW`;
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
  const available = (data.available_lns || []).filter(ln => !ln.active);
  select.innerHTML = available.map(ln =>
    `<option value="${ln.key}">${ln.ln_name} – ${ln.description}</option>`
  ).join('');
}

function updateLNList(data) {
  const container = document.getElementById('ln-list');
  if (!data.active_nodes) return;

  container.innerHTML = data.active_nodes.map(node => {
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
      <div class="ln-card" data-ln="${node.key}">
        <div class="ln-card-header">
          <div>
            <div class="ln-name">${node.ln_name}</div>
            <div class="ln-desc">${node.description}</div>
          </div>
          <button class="ln-remove" data-ln="${node.key}" title="Remove from GOOSE dataset">×</button>
        </div>
        <div class="ln-attrs">${attrs}</div>
      </div>`;
  }).join('');

  container.querySelectorAll('.ln-card-header').forEach(hdr => {
    hdr.addEventListener('click', (e) => {
      if (e.target.classList.contains('ln-remove')) return;
      hdr.parentElement.classList.toggle('expanded');
    });
  });

  container.querySelectorAll('.ln-remove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      API.post('/api/logical-nodes/remove', { ln_key: btn.dataset.ln });
    });
  });

  container.querySelectorAll('.attr-toggle').forEach(cb => {
    cb.addEventListener('change', () => {
      API.post('/api/logical-nodes/attribute', {
        ln_key: cb.dataset.ln,
        da_name: cb.dataset.da,
        enabled: cb.checked,
      });
    });
  });
}

function updateStats(data) {
  const stats = data.goose_stats || {};
  document.getElementById('stat-stnum').textContent = stats.st_num ?? '—';
  document.getElementById('stat-sqnum').textContent = stats.sq_num ?? '—';
  document.getElementById('stat-entries').textContent = stats.entries ?? '—';
  document.getElementById('stat-frame').textContent = stats.frame_len ? `${stats.frame_len} B` : '—';
}

document.getElementById('btn-start').addEventListener('click', () => API.post('/api/publisher/start'));
document.getElementById('btn-stop').addEventListener('click', () => API.post('/api/publisher/stop'));
document.getElementById('btn-publish').addEventListener('click', () => API.post('/api/publisher/publish'));
document.getElementById('btn-toggle-breaker').addEventListener('click', () => API.post('/api/breaker/toggle'));
document.getElementById('btn-clear-fault').addEventListener('click', () => API.post('/api/fault/clear'));
document.getElementById('btn-add-ln').addEventListener('click', () => {
  const select = document.getElementById('ln-add-select');
  if (select.value) API.post('/api/logical-nodes/add', { ln_key: select.value });
});

connectWebSocket();
fetch('/api/state').then(r => r.json()).then(render);
