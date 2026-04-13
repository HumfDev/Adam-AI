const URL_PARAMS = new URLSearchParams(window.location.search);
// Klipper object suffix must match [ads1115_sensor <name>] in printer.cfg
// Back-compat: ?sensor=thermistor1 sets sensor0
const SENSOR0_SECTION = URL_PARAMS.get('sensor0') || URL_PARAMS.get('sensor') || 'thermistor1';
const SENSOR1_SECTION = URL_PARAMS.get('sensor1') || 'thermistor2';
const ADS0_OBJECT_KEY = `ads1115_sensor ${SENSOR0_SECTION}`;
const ADS1_OBJECT_KEY = `ads1115_sensor ${SENSOR1_SECTION}`;
const LOADCELL_SECTION = URL_PARAMS.get('loadcell') || 'loadcell1';
const HX711_OBJECT_KEY = `hx711 ${LOADCELL_SECTION}`;

// Default off until [hx711 …] exists; add ?hx711=1 to subscribe
const ENABLE_HX711 = URL_PARAMS.get('hx711') === '1';

const MOONRAKER_HOST = window.location.hostname || 'adampi.local';

const tempEl = document.getElementById('temp');
const voltEl = document.getElementById('voltage');
const volt1El = document.getElementById('voltage-1');
const updatedEl = document.getElementById('updated');
const statusEl = document.getElementById('status');
const hxRawEl = document.getElementById('hx-raw');
const hxWeightEl = document.getElementById('hx-weight');
const hxGainEl = document.getElementById('hx-gain');
const hxBarFill = document.getElementById('hx-bar-fill');
const hxErrorsEl = document.getElementById('hx-errors');
const hxUpdatedEl = document.getElementById('hx-updated');

let rpcId = 0;
let reconnectTimer = null;
let ws = null;

function sendRpc(method, params) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ jsonrpc: '2.0', method, params, id: ++rpcId }));
  }
}

function subscribeObjects() {
  const o = { [ADS0_OBJECT_KEY]: null, [ADS1_OBJECT_KEY]: null };
  if (ENABLE_HX711) o[HX711_OBJECT_KEY] = null;
  return o;
}

function formatTime() {
  return new Date().toLocaleTimeString(undefined, { hour12: false });
}

function applyAdsStatus(slice) {
  if (!slice || typeof slice !== 'object') return;
  const d0 = slice[ADS0_OBJECT_KEY];
  const d1 = slice[ADS1_OBJECT_KEY];

  // A0 card
  if (d0 && typeof d0.temperature === 'number' && tempEl) tempEl.textContent = d0.temperature.toFixed(3);
  if (d0 && typeof d0.voltage === 'number' && voltEl) voltEl.textContent = d0.voltage.toFixed(3);

  // A1 card
  if (d1 && typeof d1.voltage === 'number' && volt1El) volt1El.textContent = d1.voltage.toFixed(3);

  if ((d0 || d1) && updatedEl) updatedEl.textContent = formatTime();
}

function rawToBarPercent(raw) {
  const r = Math.abs(Number(raw) || 0);
  const cap = 8388607;
  return Math.min(100, (Math.log10(1 + r) / Math.log10(1 + cap)) * 100);
}

function applyHx711Status(slice) {
  if (!slice || typeof slice !== 'object') return;
  const data = slice[HX711_OBJECT_KEY];
  if (!data) return;
  if (hxRawEl && typeof data.raw === 'number') hxRawEl.textContent = String(data.raw);
  if (hxGainEl && typeof data.gain === 'number') hxGainEl.textContent = String(data.gain);
  if (hxWeightEl) hxWeightEl.textContent = typeof data.weight_g === 'number' ? data.weight_g.toFixed(2) : '—';
  if (typeof data.errors === 'number' && hxErrorsEl) hxErrorsEl.textContent = String(data.errors);
  if (hxBarFill && typeof data.raw === 'number') hxBarFill.style.width = `${rawToBarPercent(data.raw).toFixed(1)}%`;
  if (hxUpdatedEl) hxUpdatedEl.textContent = formatTime();
}

function applyStatusSlice(slice) {
  applyAdsStatus(slice);
  applyHx711Status(slice);
}

function connect() {
  ws = new WebSocket(`ws://${MOONRAKER_HOST}:7125/websocket`);

  ws.onopen = () => {
    statusEl.textContent = 'Connected ✓';
    statusEl.style.color = '#00ff99';
    const objects = subscribeObjects();
    sendRpc('printer.objects.subscribe', { objects });
    sendRpc('printer.objects.query', { objects });
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (msg.result?.status) { applyStatusSlice(msg.result.status); return; }
    if (msg.method === 'notify_status_update' && msg.params?.[0]) {
      applyStatusSlice(msg.params[0]);
    }
  };

  ws.onclose = () => {
    statusEl.textContent = 'Disconnected — reconnecting...';
    statusEl.style.color = '#ff4444';
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    statusEl.textContent = 'Error';
    statusEl.style.color = '#ff4444';
  };
}

connect();
