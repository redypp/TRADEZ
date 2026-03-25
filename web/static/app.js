/* ═══════════════════════════════════════════════════════
   TRADEZ Dashboard  ·  app.js
   WebSocket-first, REST fallback, live animations
   ═══════════════════════════════════════════════════════ */

'use strict';

// ── Config ────────────────────────────────────────────────────────────────────
const WS_URL      = `ws://${location.host}/ws`;
const POLL_MS     = 8_000;   // REST fallback interval
const RECONNECT_MS = 3_000;  // WS reconnect delay

const REGIME_COLORS = {
  TRENDING: '#10D078',
  NORMAL:   '#4B9EFF',
  CAUTIOUS: '#F59E0B',
  HIGH_VOL: '#FF4D57',
  NO_TRADE: '#FF1744',
};

// ── State ─────────────────────────────────────────────────────────────────────
let prevValues  = {};   // track changes to animate flashes
let equityChart = null;
let wsAlive     = false;
let wsRetries   = 0;

// ── Helpers ───────────────────────────────────────────────────────────────────
const $     = id => document.getElementById(id);
const fmt   = (v, dp = 2) => v == null ? '—' : Number(v).toFixed(dp);
const fmtPx = v => v == null ? '—' : Number(v).toFixed(2);

function fmtPnl(v) {
  if (v == null) return '—';
  return (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(2);
}

function shortTs(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
      hour12: false, timeZone: 'UTC',
    });
  } catch { return iso.slice(0, 16); }
}

function relTime(iso) {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 5)   return 'just now';
  if (diff < 60)  return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// Flash a value element yellow when it changes
function setVal(id, text, extraClass = '') {
  const el = $(id);
  if (!el) return;
  if (prevValues[id] !== text) {
    prevValues[id] = text;
    el.textContent = text;
    if (extraClass) {
      el.className = el.className.replace(/\btext-\w+/g, '') + ' ' + extraClass;
    }
    el.classList.remove('val-flash');
    void el.offsetWidth; // reflow to restart animation
    el.classList.add('val-flash');
  }
}

function setClass(el, remove, add) {
  if (!el) return;
  if (typeof remove === 'string') el.classList.remove(...remove.split(' '));
  if (typeof add    === 'string') el.classList.add(...add.split(' '));
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function tickClock() {
  const now = new Date();
  const et  = new Intl.DateTimeFormat('en-US', {
    timeZone:    'America/New_York',
    hour:        '2-digit',
    minute:      '2-digit',
    second:      '2-digit',
    hour12:      false,
  }).format(now);
  const clockEl = $('clock');
  if (clockEl) clockEl.textContent = et + ' ET';
}
setInterval(tickClock, 1000);
tickClock();

// ── Session progress bar ──────────────────────────────────────────────────────
function updateSessionBar() {
  const now  = new Date();
  const et   = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric', minute: 'numeric', hour12: false,
  }).format(now);
  const [h, m]  = et.split(':').map(Number);
  const minutes = h * 60 + m;
  const start   = 10 * 60;   // 10:00
  const end     = 15 * 60;   // 15:00
  const pct     = Math.max(0, Math.min(100, (minutes - start) / (end - start) * 100));
  const bar     = $('session-progress');
  if (bar) bar.style.width = (minutes >= start && minutes < end) ? pct + '%' : '0%';
}
setInterval(updateSessionBar, 30_000);
updateSessionBar();

// ── Next check countdown ──────────────────────────────────────────────────────
function nextCheckLabel() {
  const now = new Date();
  const et  = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const h   = et.getHours(), m = et.getMinutes();
  if (h < 10 || h >= 15) return 'Session closed';
  // Next :02 past the hour
  const minsLeft = m < 2 ? (2 - m) : (62 - m);
  return `Next check ~${minsLeft}m`;
}

// ── Connection indicator ──────────────────────────────────────────────────────
function setConn(state) {
  const dot   = $('conn-indicator');
  const label = $('conn-label');
  if (!dot || !label) return;
  dot.className = 'conn-dot';
  if (state === 'live')        { dot.classList.add('conn-live');        label.textContent = 'LIVE'; }
  else if (state === 'polling'){ dot.classList.add('conn-live');        label.textContent = 'POLLING'; }
  else if (state === 'retry')  { dot.classList.add('conn-connecting');  label.textContent = 'RECONNECTING'; }
  else                         { dot.classList.add('conn-dead');        label.textContent = 'OFFLINE'; }
}

// ── Equity Chart ──────────────────────────────────────────────────────────────
function initChart() {
  const ctx = $('equity-chart')?.getContext('2d');
  if (!ctx) return;

  equityChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{
      label: 'Equity',
      data:  [],
      borderColor: '#10D078',
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      pointHoverBackgroundColor: '#10D078',
      tension: 0.35,
      fill: true,
      backgroundColor: (ctx) => {
        const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
        g.addColorStop(0, 'rgba(16,208,120,0.18)');
        g.addColorStop(1, 'rgba(16,208,120,0)');
        return g;
      },
    }]},
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#181C25',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          titleColor: '#8B95A8',
          bodyColor: '#E2E8F4',
          bodyFont: { family: 'JetBrains Mono', size: 12 },
          callbacks: { label: ctx => ` $${ctx.parsed.y.toFixed(2)}` },
        },
      },
      scales: {
        x: {
          ticks: { color: '#4A5568', font: { size: 10 }, maxTicksLimit: 8 },
          grid:  { color: 'rgba(255,255,255,0.04)' },
          border: { color: 'transparent' },
        },
        y: {
          ticks: {
            color: '#4A5568',
            font: { size: 10, family: 'JetBrains Mono' },
            callback: v => `$${v.toFixed(0)}`,
          },
          grid:  { color: 'rgba(255,255,255,0.04)' },
          border: { color: 'transparent' },
        },
      },
    },
  });
}

function updateChart(curve) {
  if (!equityChart || !curve?.length) return;
  const last = curve[curve.length - 1]?.equity ?? 0;
  const color = last >= 0 ? '#10D078' : '#FF4D57';

  equityChart.data.labels = curve.map(p => shortTs(p.timestamp));
  equityChart.data.datasets[0].data = curve.map(p => p.equity);
  equityChart.data.datasets[0].borderColor = color;
  equityChart.update('none');

  const cp = $('chart-pnl');
  if (cp) {
    cp.textContent = fmtPnl(last);
    cp.className   = 'chart-pnl ' + (last >= 0 ? 'text-green' : 'text-red');
  }
}

// ── Render: State ─────────────────────────────────────────────────────────────
function renderState(s) {
  if (!s) return;

  // Mode badge
  const mb = $('mode-badge');
  if (mb) {
    mb.textContent = s.paper_trading ? 'PAPER' : 'LIVE';
    mb.className   = 'mode-badge ' + (s.paper_trading ? 'mode-paper' : 'mode-live');
  }

  // Bot state
  const stateBadge = $('s-state');
  const stateText  = $('s-state-text');
  const brtState   = s.brt_state || 'NEUTRAL';
  if (stateText) stateText.textContent = brtState;
  if (stateBadge) {
    stateBadge.className = 'state-badge ';
    if      (brtState === 'WATCHING_LONG')  stateBadge.classList.add('state-watching-long');
    else if (brtState === 'WATCHING_SHORT') stateBadge.classList.add('state-watching-short');
    else                                    stateBadge.classList.add('state-neutral');
  }
  const watchEl = $('s-watch');
  if (watchEl) {
    if (s.watch_level && s.watch_ltype) {
      watchEl.textContent = `Watching ${s.watch_ltype} @ ${fmtPx(s.watch_level)}`;
      watchEl.style.color = brtState === 'WATCHING_LONG' ? 'var(--green)' : 'var(--red)';
    } else {
      watchEl.textContent = 'No active setup';
      watchEl.style.color = '';
    }
  }
  const nextEl = $('s-next-check');
  if (nextEl) nextEl.textContent = nextCheckLabel();

  // Session
  const sessEl = $('s-session');
  if (sessEl) {
    if (s.session_open) {
      sessEl.textContent = 'OPEN';
      sessEl.className   = 'metric-large text-green';
    } else {
      sessEl.textContent = 'CLOSED';
      sessEl.className   = 'metric-large text-muted';
    }
  }

  // P&L
  const pnl = s.daily_pnl ?? 0;
  const pnlEl = $('s-pnl');
  if (pnlEl) {
    pnlEl.textContent = fmtPnl(pnl);
    pnlEl.className   = 'metric-large ' + (pnl >= 0 ? 'text-green' : 'text-red');
  }

  // Price
  const price = s.close;
  setVal('s-price', fmtPx(price));
  const ema   = s.ema20;
  if (price && ema) {
    const diff = price - ema;
    const distEl = $('s-ema-dist');
    if (distEl) {
      distEl.textContent = (diff >= 0 ? '+' : '') + fmt(diff, 2) + ' pts';
      distEl.className   = 'price-ema-dist ' + (diff >= 0 ? 'text-green' : 'text-red');
    }
  }

  // ADX
  const adxMin = s.adx_min ?? 20;
  const adxEl  = $('i-adx-req');
  if (adxEl) adxEl.textContent = `min ${adxMin}`;
  setVal('i-adx', fmt(s.adx, 1));
  const adxOk = s.adx >= adxMin;
  const adxBadge = $('i-adx-status');
  if (adxBadge) {
    adxBadge.textContent  = adxOk ? 'PASS' : 'FAIL';
    adxBadge.className    = 'ind-badge ' + (adxOk ? 'ind-badge-pass' : 'ind-badge-fail');
  }
  const adxFill = $('i-adx-fill');
  if (adxFill) {
    adxFill.style.width      = Math.min(100, (s.adx / 60) * 100) + '%';
    adxFill.className        = 'ind-fill ' + (adxOk ? 'ind-fill-green' : 'ind-fill-red');
  }
  const adxThresh = $('i-adx-thresh');
  if (adxThresh) adxThresh.style.left = Math.min(95, (adxMin / 60) * 100) + '%';

  // RSI
  setVal('i-rsi', fmt(s.rsi, 1));
  const rsiOk = s.rsi > 35 && s.rsi < 75;
  const rsiBadge = $('i-rsi-status');
  if (rsiBadge) {
    rsiBadge.textContent = rsiOk ? 'PASS' : 'WARN';
    rsiBadge.className   = 'ind-badge ' + (rsiOk ? 'ind-badge-pass' : 'ind-badge-warn');
  }
  const rsiFill = $('i-rsi-fill');
  if (rsiFill) rsiFill.style.width = Math.min(100, s.rsi ?? 50) + '%';

  // ATR
  setVal('i-atr', fmt(s.atr, 2));
  const atrFill = $('i-atr-fill');
  if (atrFill) atrFill.style.width = Math.min(100, ((s.atr ?? 0) / 20) * 100) + '%';

  // EMA
  setVal('i-ema', fmtPx(ema));
  const aboveEma = price > ema;
  const emaBadge = $('i-ema-trend');
  const emaFoot  = $('i-ema-foot');
  if (emaBadge) {
    emaBadge.textContent = aboveEma ? '↑ ABOVE' : '↓ BELOW';
    emaBadge.className   = 'ind-badge ' + (aboveEma ? 'ind-badge-pass' : 'ind-badge-fail');
  }
  if (emaFoot) {
    emaFoot.textContent = aboveEma ? 'bullish alignment' : 'bearish alignment';
    emaFoot.className   = 'ind-foot ' + (aboveEma ? 'text-green' : 'text-red');
  }
  const emaFill = $('i-ema-fill');
  if (emaFill) {
    emaFill.className = 'ind-fill ' + (aboveEma ? 'ind-fill-green' : 'ind-fill-red');
    emaFill.style.width = '100%';
  }

  // Levels
  renderLevel('vwap', s.vwap, price, 'above');
  renderLevel('pdh',  s.pdh,  price, 'above');
  renderLevel('pdl',  s.pdl,  price, 'below');
  renderLevel('shi',  s.swing_hi, price, 'above');
  renderLevel('slo',  s.swing_lo, price, 'below');

  // Highlight watched level row
  ['vwap','pdh','pdl','shi','slo'].forEach(k => {
    const row = $(`lrow-${k}`);
    if (!row) return;
    row.classList.remove('level-row-active', 'level-row-active-short');
  });
  if (s.watch_ltype && brtState !== 'NEUTRAL') {
    const map = { VWAP:'vwap', PDH:'pdh', PDL:'pdl', 'SWING':'shi' };
    const key = map[s.watch_ltype];
    if (key) {
      $(`lrow-${key}`)?.classList.add(
        brtState === 'WATCHING_LONG' ? 'level-row-active' : 'level-row-active-short'
      );
    }
  }

  // Params
  setVal('p-adx',  s.adx_min  != null ? String(s.adx_min)      : '—');
  setVal('p-sl',   s.sl_buffer != null ? `${s.sl_buffer}×ATR`  : '—');
  setVal('p-tp',   s.tp_rr    != null ? `${s.tp_rr}R`          : '—');
  setVal('p-bars', s.max_retest_bars != null ? String(s.max_retest_bars) : '—');
}

function renderLevel(key, val, price, side) {
  const priceEl = $(`l-${key}`);
  const barEl   = $(`lb-${key}`);
  const distEl  = $(`ld-${key}`);
  if (!priceEl) return;

  priceEl.textContent = fmtPx(val);
  if (!val || !price) { if (distEl) distEl.textContent = '—'; return; }

  const diff = val - price;
  const absPct = Math.min(100, Math.abs(diff) / price * 100 * 50);  // visual scale

  if (distEl) {
    distEl.textContent = (diff >= 0 ? '+' : '') + fmt(diff, 1);
    distEl.className   = 'lrow-dist ' + (diff >= 0 ? 'text-green' : 'text-red');
  }
  if (barEl) {
    barEl.style.width      = Math.min(95, absPct) + '%';
    barEl.style.background = diff >= 0 ? 'var(--green)' : 'var(--red)';
    barEl.style.opacity    = '0.5';
  }
}

// ── Render: Regime ────────────────────────────────────────────────────────────
function renderRegime(regime, state) {
  if (!regime) return;
  const r      = regime.regime || 'NORMAL';
  const color  = REGIME_COLORS[r] || '#4B9EFF';
  const nameEl = $('r-name');
  const descEl = $('r-desc');
  const badgeEl= $('r-trade-ok');
  const strip  = document.querySelector('.regime-strip');

  if (nameEl) { nameEl.textContent = r; nameEl.style.color = color; }
  if (descEl)  descEl.textContent  = regime.description || '—';
  if (strip)   strip.style.borderBottom = `2px solid ${color}40`;

  if (badgeEl) {
    if (regime.can_trade) {
      badgeEl.textContent = '✓ TRADING';
      badgeEl.className   = 'regime-trade-badge trade-ok';
    } else {
      badgeEl.textContent = '✗ BLOCKED';
      badgeEl.className   = 'regime-trade-badge trade-off';
    }
  }

  // Macro chips
  if (state) {
    setVal('m-vix',   state.vix     != null ? fmt(state.vix, 1)      : '—');
    setVal('m-yield', state.yield_10y != null ? fmt(state.yield_10y, 3) + '%' : '—');
    setVal('m-dxy',   state.dxy     != null ? fmt(state.dxy, 2)      : '—');
    setVal('m-vol',   state.spy_vol_ratio != null ? fmt(state.spy_vol_ratio, 2) + 'x' : '—');
  }

  // Macro conditions list
  const macroEl = $('macro-list');
  if (!macroEl || !state) return;
  const hw = state.headwinds ? state.headwinds.split(' | ').filter(Boolean) : [];
  const tw = state.tailwinds ? state.tailwinds.split(' | ').filter(Boolean) : [];
  const items = [
    ...tw.map(t => ({ cls: 'macro-item-tail', text: t })),
    ...hw.map(h => ({ cls: 'macro-item-head', text: h })),
  ];
  if (!items.length) items.push({ cls: 'macro-item-neutral', text: 'No active headwinds or tailwinds' });
  macroEl.innerHTML = items.map(i =>
    `<div class="macro-item ${i.cls}">${i.text}</div>`
  ).join('');
}

// ── Render: Trades ────────────────────────────────────────────────────────────
function renderTrades(trades, summary) {
  const tbody    = $('trades-body');
  const countEl  = $('trades-count');

  if (summary) {
    const winsEl   = $('s-wins');
    const lossesEl = $('s-losses');
    const totEl    = $('s-trades');
    if (winsEl)   winsEl.textContent   = `${summary.wins ?? 0}W`;
    if (lossesEl) lossesEl.textContent = `${summary.losses ?? 0}L`;
    if (totEl)    totEl.textContent    = ` (${summary.total ?? 0} trades)`;
  }

  if (countEl && trades) countEl.textContent = `${trades.length} records`;

  if (!tbody) return;
  if (!trades?.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="table-empty">No trades recorded yet</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const hasPnl   = t.pnl != null;
    const pnlClass = !hasPnl ? 'pnl-open' : t.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    const pnlText  = !hasPnl ? 'open' : fmtPnl(t.pnl);
    const dirClass = t.direction === 'LONG' ? 'dir-long' : 'dir-short';
    return `<tr>
      <td>${shortTs(t.timestamp)}</td>
      <td class="${dirClass}">${t.direction || '—'}</td>
      <td>${t.level_type || '—'}</td>
      <td>${fmtPx(t.entry_price)}</td>
      <td>${fmtPx(t.stop_loss)}</td>
      <td>${fmtPx(t.take_profit)}</td>
      <td>${fmtPx(t.exit_price)}</td>
      <td style="color:var(--text-2)">${t.exit_reason || '—'}</td>
      <td class="${pnlClass}">${pnlText}</td>
      <td style="color:var(--text-3)">${t.regime || '—'}</td>
      <td style="color:var(--text-3)">${t.vix != null ? fmt(t.vix, 1) : '—'}</td>
    </tr>`;
  }).join('');
}

// ── Render: Activity Feed ─────────────────────────────────────────────────────
let lastEventId = 0;

function renderFeed(events) {
  if (!events?.length) return;
  const feedEl  = $('feed-list');
  const countEl = $('feed-count');
  if (!feedEl) return;

  // Only process new events
  const newEvents = events.filter(e => e.id > lastEventId);
  if (!newEvents.length) return;
  lastEventId = events[0].id;   // events come newest-first

  const levelClass = { INFO: 'feed-info', TRADE: 'feed-trade', WARN: 'feed-warn', ERROR: 'feed-error' };

  // Prepend new events
  for (const ev of newEvents) {
    const cls  = levelClass[ev.level] || 'feed-info';
    const time = relTime(ev.timestamp);
    const div  = document.createElement('div');
    div.className = `feed-item ${cls}`;
    div.innerHTML = `
      <span class="feed-dot"></span>
      <div class="feed-content">
        <span class="feed-msg">${ev.message}</span>
        ${ev.detail ? `<span class="feed-detail">${ev.detail}</span>` : ''}
        <span class="feed-time">${time}</span>
      </div>`;
    feedEl.prepend(div);
  }

  // Trim to 40 items
  while (feedEl.children.length > 40) feedEl.removeChild(feedEl.lastChild);
  if (countEl) countEl.textContent = `${feedEl.children.length} events`;
}

// ── Full render from payload ──────────────────────────────────────────────────
function render(data) {
  if (!data) return;
  renderState(data.state);
  renderRegime(data.regime, data.state);
  renderTrades(data.trades, data.summary);
  renderFeed(data.events);
  updateChart(data.equity);
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWS() {
  setConn('retry');
  let ws;
  try { ws = new WebSocket(WS_URL); }
  catch { scheduleReconnect(); return; }

  ws.onopen = () => {
    wsAlive   = true;
    wsRetries = 0;
    setConn('live');
  };

  ws.onmessage = e => {
    try { render(JSON.parse(e.data)); }
    catch (err) { console.warn('WS parse error:', err); }
  };

  ws.onerror  = ()  => ws.close();
  ws.onclose  = () => {
    wsAlive = false;
    setConn('retry');
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  const delay = Math.min(30_000, RECONNECT_MS * Math.pow(1.5, wsRetries++));
  setTimeout(connectWS, delay);
}

// ── REST fallback (if WS unavailable) ────────────────────────────────────────
async function pollRest() {
  if (wsAlive) return;
  try {
    const res  = await fetch('/api/all');
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    render(data);
    setConn('polling');
  } catch {
    setConn('dead');
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
initChart();
connectWS();
pollRest();
setInterval(pollRest, POLL_MS);
