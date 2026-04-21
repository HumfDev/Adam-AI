'use strict';

// ── Color palette ──────────────────────────────────────────────
const C = {
  gold:   'rgb(204,163,72)',
  teal:   'rgb(74,93,87)',
  green:  '#4caf80',
  red:    '#e05c5c',
  amber:  '#e0a03c',
  purple: '#a07abd',
  dim:    'rgba(255,255,255,0.15)',
  text:   '#e2e2e6',
};

// ── Navigation ─────────────────────────────────────────────────
const PANEL_TITLES = {
  live:       ['Live Print Monitor',         'Layer 1 · LSTM Predictor — 30s window'],
  classifier: ['Failure Classifier',         'Layer 2 · RandomForest — session-level analysis'],
  analytics:  ['Session Analytics & Trends', 'Layer 3 · Pass/Fail · Health · Pattern Mining'],
  sessions:   ['Session Log',                'All recorded print sessions'],
  drift:      ['Drift Detector',             'Layer 3 · Sensor distribution shift & retrain trigger'],
};

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const id = btn.dataset.panel;
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById('panel-' + id).classList.add('active');
    const [title, sub] = PANEL_TITLES[id];
    document.getElementById('panel-title').textContent = title;
    document.querySelector('.topbar-sub').textContent = sub;
  });
});

// ── Clock ──────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toTimeString().slice(0, 8);
}
setInterval(updateClock, 1000);
updateClock();

// ── Sparkline helper ───────────────────────────────────────────
function drawSparkline(canvas, data, color) {
  const ctx = canvas.getContext('2d');
  const w = canvas.offsetWidth || 200;
  const h = canvas.offsetHeight || 44;
  canvas.width = w;
  canvas.height = h;
  ctx.clearRect(0, 0, w, h);

  if (data.length < 2) return;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = w / (data.length - 1);

  ctx.beginPath();
  data.forEach((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // fill under
  ctx.lineTo((data.length - 1) * step, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color.replace(')', ', 0.25)').replace('rgb', 'rgba'));
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad;
  ctx.fill();
}

// ── Sensor simulation state ────────────────────────────────────
const BUFFER_LEN = 30;

function initBuf(fn) { return Array.from({length: BUFFER_LEN}, (_, i) => fn(i)); }

const sensors = {
  therm0: initBuf(i => 37.2 + Math.sin(i * 0.25) * 0.4  + (Math.random() - 0.5) * 0.2),
  therm1: initBuf(i => 36.8 + Math.sin(i * 0.20) * 0.35 + (Math.random() - 0.5) * 0.2),
  force:  initBuf(i => 80   + Math.sin(i * 0.40) * 12   + Math.random() * 5),
  acid0:  initBuf(i => 7.35 + Math.sin(i * 0.15) * 0.06 + (Math.random() - 0.5) * 0.02),
  acid1:  initBuf(i => 7.40 + Math.sin(i * 0.18) * 0.05 + (Math.random() - 0.5) * 0.02),
  conc:   initBuf(i => 88   + Math.sin(i * 0.30) * 3    + (Math.random() - 0.5) * 1.5),
  hp0:    initBuf(i => 45   + Math.sin(i * 0.50) * 5    + (Math.random() - 0.5) * 2),
  hp1:    initBuf(i => 52   + Math.sin(i * 0.45) * 6    + (Math.random() - 0.5) * 2),
};

function pushSensor(arr, val) {
  arr.push(val);
  if (arr.length > BUFFER_LEN) arr.shift();
}

function last(arr) { return arr[arr.length - 1]; }

// ── Main buffer chart (canvas 2D) ─────────────────────────────
const bufCanvas = document.getElementById('buffer-chart');
function drawBufferChart() {
  const w = bufCanvas.offsetWidth || 600;
  const h = 160;
  bufCanvas.width = w;
  bufCanvas.height = h;
  const ctx = bufCanvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);

  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const y = Math.round(h * g / 4) + 0.5;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  function plotLine(data, color) {
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const step = w / (data.length - 1);
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = i * step;
      const y = h - 4 - ((v - min) / range) * (h - 12);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.stroke();
  }

  plotLine(sensors.therm0, '#5ba8a0');
  plotLine(sensors.therm1, '#7ec8c0');
  plotLine(sensors.force,  C.gold);
  plotLine(sensors.acid0,  '#e07ab0');
  plotLine(sensors.acid1,  C.purple);
  plotLine(sensors.conc,   '#6ab0e0');
}

// ── Gauge (half-circle) ───────────────────────────────────────
const gaugeCanvas = document.getElementById('gauge-canvas');
function drawGauge(value) { // 0..1
  const ctx = gaugeCanvas.getContext('2d');
  const W = 260, H = 140;
  gaugeCanvas.width = W; gaugeCanvas.height = H;
  ctx.clearRect(0, 0, W, H);

  const cx = W / 2, cy = H - 10, r = 110;

  // track
  ctx.beginPath();
  ctx.arc(cx, cy, r, Math.PI, 0);
  ctx.lineWidth = 14;
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.stroke();

  // value arc
  const angle = Math.PI + value * Math.PI;
  const color = value < 0.35 ? C.green : value < 0.65 ? C.amber : C.red;
  ctx.beginPath();
  ctx.arc(cx, cy, r, Math.PI, angle);
  ctx.lineWidth = 14;
  ctx.strokeStyle = color;
  ctx.lineCap = 'round';
  ctx.stroke();

  // tick marks
  for (let t = 0; t <= 10; t++) {
    const a = Math.PI + (t / 10) * Math.PI;
    const x1 = cx + (r - 20) * Math.cos(a);
    const y1 = cy + (r - 20) * Math.sin(a);
    const x2 = cx + (r - 26) * Math.cos(a);
    const y2 = cy + (r - 26) * Math.sin(a);
    ctx.beginPath();
    ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
    ctx.strokeStyle = 'rgba(255,255,255,0.2)';
    ctx.lineWidth = t % 5 === 0 ? 2 : 1;
    ctx.stroke();
  }

  // labels
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '11px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('0', cx - r + 6, cy + 14);
  ctx.fillText('1', cx + r - 6, cy + 14);
  ctx.fillText('0.5', cx, cy - r + 18);
}

// ── LSTM counter ──────────────────────────────────────────────
let lstmValue = 0.12;
let lstmCountdown = 5;
function updateLSTM() {
  // simulate slowly changing risk
  const delta = (Math.random() - 0.48) * 0.06;
  lstmValue = Math.max(0, Math.min(1, lstmValue + delta));
  drawGauge(lstmValue);
  document.getElementById('lstm-score').textContent = lstmValue.toFixed(2);
  const label = lstmValue < 0.35 ? 'LOW RISK' : lstmValue < 0.65 ? 'MODERATE RISK' : 'HIGH RISK';
  const el = document.getElementById('lstm-label');
  el.textContent = label;
  el.style.color = lstmValue < 0.35 ? C.green : lstmValue < 0.65 ? C.amber : C.red;
  lstmCountdown = 5;
}

// LSTM countdown display
setInterval(() => {
  lstmCountdown--;
  if (lstmCountdown <= 0) {
    updateLSTM();
  }
  const el = document.getElementById('lstm-tick');
  if (el) el.innerHTML = `Next update in <b>${lstmCountdown}</b>s`;
}, 1000);

// ── Sensor tick (1Hz) ─────────────────────────────────────────
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function sensorTick() {
  const t = Date.now();

  const t0 = clamp(last(sensors.therm0) + (Math.random() - 0.49) * 0.12, 35, 40);
  const t1 = clamp(last(sensors.therm1) + (Math.random() - 0.49) * 0.12, 35, 40);
  const f  = last(sensors.force) + (Math.random() - 0.48) * 4;
  const a0 = clamp(last(sensors.acid0) + (Math.random() - 0.5) * 0.012, 6.8, 7.8);
  const a1 = clamp(last(sensors.acid1) + (Math.random() - 0.5) * 0.012, 6.8, 7.8);
  const co = clamp(last(sensors.conc)  + (Math.random() - 0.49) * 0.8, 70, 100);
  const h0 = clamp(last(sensors.hp0)  + (Math.random() - 0.5) * 1.5,  0, 100);
  const h1 = clamp(last(sensors.hp1)  + (Math.random() - 0.5) * 1.5,  0, 100);

  pushSensor(sensors.therm0, t0);
  pushSensor(sensors.therm1, t1);
  pushSensor(sensors.force,  f);
  pushSensor(sensors.acid0,  a0);
  pushSensor(sensors.acid1,  a1);
  pushSensor(sensors.conc,   co);
  pushSensor(sensors.hp0,    h0);
  pushSensor(sensors.hp1,    h1);

  // text values
  document.getElementById('s-therm0').textContent = t0.toFixed(2);
  document.getElementById('s-therm1').textContent = t1.toFixed(2);
  document.getElementById('s-force').textContent  = f.toFixed(2);
  document.getElementById('s-acid0').textContent  = a0.toFixed(3);
  document.getElementById('s-acid1').textContent  = a1.toFixed(3);
  document.getElementById('s-conc').textContent   = co.toFixed(1);

  // heat pads
  const hp0pct = Math.round(h0);
  const hp1pct = Math.round(h1);
  document.getElementById('hp0-fill').style.width  = hp0pct + '%';
  document.getElementById('hp1-fill').style.width  = hp1pct + '%';
  document.getElementById('hp0-pwm').textContent   = hp0pct + '% PWM';
  document.getElementById('hp1-pwm').textContent   = hp1pct + '% PWM';
  const hp0El = document.getElementById('hp0-state');
  const hp1El = document.getElementById('hp1-state');
  hp0El.textContent = hp0pct > 5 ? 'ON' : 'OFF';
  hp0El.className   = 'heatpad-state' + (hp0pct > 5 ? '' : ' off');
  hp1El.textContent = hp1pct > 5 ? 'ON' : 'OFF';
  hp1El.className   = 'heatpad-state' + (hp1pct > 5 ? '' : ' off');

  // sparklines
  drawSparkline(document.getElementById('spark-therm0'), sensors.therm0, '#5ba8a0');
  drawSparkline(document.getElementById('spark-therm1'), sensors.therm1, '#7ec8c0');
  drawSparkline(document.getElementById('spark-force'),  sensors.force,  C.gold);
  drawSparkline(document.getElementById('spark-acid0'),  sensors.acid0,  '#e07ab0');
  drawSparkline(document.getElementById('spark-acid1'),  sensors.acid1,  C.purple);
  drawSparkline(document.getElementById('spark-conc'),   sensors.conc,   '#6ab0e0');
  drawSparkline(document.getElementById('spark-hp0'),    sensors.hp0,    C.amber);

  drawBufferChart();
}
setInterval(sensorTick, 1000);
sensorTick();
drawGauge(lstmValue);

// ── Classifier bars ───────────────────────────────────────────
const FAILURE_CLASSES = [
  { name: 'Nozzle Clog',        pct: 42 },
  { name: 'Under-extrusion',    pct: 27 },
  { name: 'Temp Drift',         pct: 18 },
  { name: 'Layer Delamination', pct: 8  },
  { name: 'Bioink Degradation', pct: 5  },
];

function renderClassifierBars() {
  const container = document.getElementById('cf-bars');
  container.innerHTML = FAILURE_CLASSES.map(fc => `
    <div class="cf-row">
      <span class="cf-name">${fc.name}</span>
      <div class="cf-bar-bg">
        <div class="cf-bar-fill" style="width:${fc.pct}%"></div>
      </div>
      <span class="cf-pct">${fc.pct}%</span>
    </div>
  `).join('');
}
renderClassifierBars();

// ── Pattern list ──────────────────────────────────────────────
const PATTERNS = [
  { rank: '#1', name: 'Nozzle Clog → Under-extrusion', pct: '34% of failures' },
  { rank: '#2', name: 'Temp Drift → Layer Delamination', pct: '21% of failures' },
  { rank: '#3', name: 'Bioink Degradation (session-end)', pct: '14% of failures' },
  { rank: '#4', name: 'Force spike at layer start', pct: '11% of failures' },
];

function renderPatterns() {
  document.getElementById('pattern-list').innerHTML = PATTERNS.map(p => `
    <div class="pattern-item">
      <span class="pattern-rank">${p.rank}</span>
      <span class="pattern-name">${p.name}</span>
      <span class="pattern-pct">${p.pct}</span>
    </div>
  `).join('');
}
renderPatterns();

// ── Health ring (donut) ───────────────────────────────────────
function drawHealthRing(score) {
  const canvas = document.getElementById('health-ring');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 140, 140);
  const cx = 70, cy = 70, r = 55;

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, 2 * Math.PI);
  ctx.lineWidth = 13;
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + (score / 100) * 2 * Math.PI);
  ctx.lineWidth = 13;
  ctx.strokeStyle = score >= 70 ? C.green : score >= 40 ? C.amber : C.red;
  ctx.lineCap = 'round';
  ctx.stroke();
}
drawHealthRing(84);

// ── Pass/Fail history bar chart ───────────────────────────────
function drawPFHistory() {
  const canvas = document.getElementById('pf-history');
  const w = canvas.offsetWidth || 340;
  canvas.width = w;
  canvas.height = 80;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, 80);

  // fake last 20 sessions pass/fail
  const sessions = [1,1,1,0,1,1,1,1,0,1,1,0,1,1,1,1,0,1,1,1];
  const bw = w / sessions.length - 2;
  sessions.forEach((v, i) => {
    ctx.fillStyle = v ? 'rgba(76,175,128,0.6)' : 'rgba(224,92,92,0.6)';
    const h = v ? 60 : 30;
    ctx.fillRect(i * (bw + 2), 80 - h, bw, h);
  });
}
drawPFHistory();

// ── Trend chart ───────────────────────────────────────────────
function drawTrendChart() {
  const canvas = document.getElementById('trend-chart');
  const w = canvas.offsetWidth || 800;
  canvas.width = w;
  canvas.height = 130;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, 130);

  const scores = [72,68,74,80,77,82,78,85,81,84,79,83,87,85,90,88,84,86,89,84];

  // grid
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  [0,25,50,75,100].forEach(v => {
    const y = Math.round(130 - (v / 100) * 120) + 0.5;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.2)';
    ctx.font = '10px monospace';
    ctx.fillText(v, 2, y - 2);
  });

  const step = w / (scores.length - 1);
  ctx.beginPath();
  scores.forEach((v, i) => {
    const x = i * step;
    const y = 130 - (v / 100) * 120;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = C.gold;
  ctx.lineWidth = 2;
  ctx.stroke();

  // dots
  scores.forEach((v, i) => {
    const x = i * step;
    const y = 130 - (v / 100) * 120;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, 2 * Math.PI);
    ctx.fillStyle = C.gold;
    ctx.fill();
  });
}
drawTrendChart();

// ── Sessions table ────────────────────────────────────────────
const BIOINKS = ['PLA-A3','Alginate-B1','GelMA-C2','PLA-A3','Collagen-D4'];
function buildSessionTable() {
  const tbody = document.getElementById('session-tbody');
  const rows = [];
  for (let i = 40; i >= 21; i--) {
    const pass = Math.random() > 0.22;
    const health = pass ? Math.round(72 + Math.random() * 20) : Math.round(20 + Math.random() * 35);
    const bioink = BIOINKS[Math.floor(Math.random() * BIOINKS.length)];
    const mins = Math.floor(3 + Math.random() * 5);
    const secs = Math.floor(Math.random() * 60).toString().padStart(2, '0');
    const failures = ['Nozzle Clog','Under-extrusion','Temp Drift','Layer Delamination','—'];
    const dom = pass ? '—' : failures[Math.floor(Math.random() * 4)];
    rows.push(`<tr>
      <td>#${String(i).padStart(4,'0')}</td>
      <td>2026-04-${String(Math.floor(Math.random()*20+1)).padStart(2,'0')}</td>
      <td>${bioink}</td>
      <td>${mins}m ${secs}s</td>
      <td style="color:${health>=70?C.green:health>=40?C.amber:C.red};font-weight:700">${health}</td>
      <td class="${pass?'badge-pass':'badge-fail'}">${pass?'PASS':'FAIL'}</td>
      <td style="color:var(--text-dim);font-size:.72rem">${dom}</td>
    </tr>`);
  }
  tbody.innerHTML = rows.join('');
}
buildSessionTable();

// ── Drift sparklines ──────────────────────────────────────────
function genDriftData(baseline, noise, drift) {
  return Array.from({length: 20}, (_, i) => baseline + drift * i / 20 + (Math.random() - 0.5) * noise);
}

function drawDriftSparkline(canvasId, data, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const w = canvas.offsetWidth || 200;
  canvas.width = w; canvas.height = 80;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, 80);
  const min = Math.min(...data) - 0.5;
  const max = Math.max(...data) + 0.5;
  const range = max - min || 1;
  const step = w / (data.length - 1);

  // baseline ref
  const baseY = 80 - ((data[0] - min) / range) * 70;
  ctx.beginPath(); ctx.moveTo(0, baseY); ctx.lineTo(w, baseY);
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.setLineDash([4,4]); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);

  ctx.beginPath();
  data.forEach((v, i) => {
    const x = i * step;
    const y = 80 - ((v - min) / range) * 70;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.8;
  ctx.stroke();
}

drawDriftSparkline('drift-force-chart', genDriftData(80, 5, 2),   C.gold);
drawDriftSparkline('drift-temp-chart',  genDriftData(37.2, 0.2, 0.05), '#5ba8a0');
drawDriftSparkline('drift-color-chart', genDriftData(1.6, 0.08, 0.4),  C.purple);

// ── Re-draw on resize ─────────────────────────────────────────
window.addEventListener('resize', () => {
  drawBufferChart();
  drawPFHistory();
  drawTrendChart();
  drawDriftSparkline('drift-force-chart', genDriftData(80, 5, 2), C.gold);
  drawDriftSparkline('drift-temp-chart',  genDriftData(37.2, 0.2, 0.05), '#5ba8a0');
  drawDriftSparkline('drift-color-chart', genDriftData(1.6, 0.08, 0.4), C.purple);
});
