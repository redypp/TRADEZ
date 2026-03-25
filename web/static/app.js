'use strict';

// ── Config ────────────────────────────────────────────────────────────────────
const WS_URL      = `ws://${location.host}/ws`;
const POLL_MS     = 8_000;
const RECONNECT   = 3_000;
const REGIME_COLORS = {
  TRENDING:'#22C55E', NORMAL:'#3B82F6',
  CAUTIOUS:'#F59E0B', HIGH_VOL:'#EF4444', NO_TRADE:'#9F1239',
};

// ── State ─────────────────────────────────────────────────────────────────────
let wsAlive    = false;
let wsRetries  = 0;
let lastEvId   = 0;
let equityChart = null;

// ── Utilities ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const f  = (v, dp=2) => v == null ? '—' : Number(v).toFixed(dp);
const fp = v => v == null ? '—' : Number(v).toFixed(2);

function fmtPnl(v) {
  if (v == null) return '$—';
  return (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(2);
}
function shortTs(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month:'2-digit', day:'2-digit',
      hour:'2-digit',  minute:'2-digit',
      hour12: false,   timeZone:'UTC',
    });
  } catch { return iso.slice(0,16); }
}
function relTime(iso) {
  if (!iso) return '';
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 5)   return 'just now';
  if (s < 60)  return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  return `${Math.floor(s/3600)}h ago`;
}

function setText(id, text, cls) {
  const el = $(id); if (!el) return;
  if (el.textContent === String(text)) return;
  el.textContent = String(text);
  if (cls !== undefined) el.className = cls;
  el.classList.add('flash');
  el.addEventListener('animationend', () => el.classList.remove('flash'), { once:true });
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = $(`tab-${btn.dataset.tab}`);
    if (panel) panel.classList.add('active');
  });
});

// ── Clock ─────────────────────────────────────────────────────────────────────
function tickClock() {
  const et = new Intl.DateTimeFormat('en-US', {
    timeZone:'America/New_York',
    hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false,
  }).format(new Date());
  const el = $('clock'); if (el) el.textContent = et + ' ET';
}
setInterval(tickClock, 1000); tickClock();

// ── Next-check helper ─────────────────────────────────────────────────────────
function nextCheck() {
  const et  = new Date(new Date().toLocaleString('en-US', { timeZone:'America/New_York' }));
  const h = et.getHours(), m = et.getMinutes();
  if (h < 10 || h >= 15) return 'Session closed';
  return `~${m < 2 ? (2 - m) : (62 - m)}m`;
}

// ── Connection ────────────────────────────────────────────────────────────────
function setConn(state) {
  const el = $('conn-pill'); if (!el) return;
  const map = { live:'● LIVE', polling:'● POLLING', retry:'● RECONNECTING', dead:'● OFFLINE' };
  const cls = { live:'conn-pill live', polling:'conn-pill live', retry:'conn-pill connecting', dead:'conn-pill offline' };
  el.textContent = map[state] || '● —';
  el.className   = cls[state] || 'conn-pill';

  const dot = document.querySelector('.tab-dot');
  if (dot) dot.className = 'tab-dot' + (state === 'live' || state === 'polling' ? ' live' : '');
}

// ── Chart ─────────────────────────────────────────────────────────────────────
function initChart() {
  const ctx = $('equity-chart')?.getContext('2d'); if (!ctx) return;
  equityChart = new Chart(ctx, {
    type: 'line',
    data: { labels:[], datasets:[{
      data: [], borderColor:'#22C55E', borderWidth:2,
      pointRadius:0, pointHoverRadius:3, tension:0.35, fill:true,
      backgroundColor: c => {
        const g = c.chart.ctx.createLinearGradient(0,0,0,c.chart.height);
        g.addColorStop(0, 'rgba(34,197,94,0.15)');
        g.addColorStop(1, 'rgba(34,197,94,0)');
        return g;
      },
    }]},
    options: {
      responsive:true, maintainAspectRatio:false,
      interaction:{ mode:'index', intersect:false },
      plugins:{
        legend:{ display:false },
        tooltip:{
          backgroundColor:'#191E2B',
          borderColor:'rgba(255,255,255,0.08)', borderWidth:1,
          titleColor:'#8893A8', bodyColor:'#E4EAF6',
          bodyFont:{ family:'JetBrains Mono', size:12 },
          callbacks:{ label: c => ` $${c.parsed.y.toFixed(2)}` },
        },
      },
      scales:{
        x:{ ticks:{ color:'#454E61', font:{size:9}, maxTicksLimit:6 }, grid:{ color:'rgba(255,255,255,0.03)' }, border:{color:'transparent'} },
        y:{ ticks:{ color:'#454E61', font:{size:9, family:'JetBrains Mono'}, callback:v=>`$${v.toFixed(0)}` }, grid:{ color:'rgba(255,255,255,0.03)' }, border:{color:'transparent'} },
      },
    },
  });
}

function updateChart(curve) {
  if (!equityChart || !curve?.length) return;
  const last  = curve[curve.length-1]?.equity ?? 0;
  const color = last >= 0 ? '#22C55E' : '#EF4444';
  equityChart.data.labels   = curve.map(p => shortTs(p.timestamp));
  equityChart.data.datasets[0].data        = curve.map(p => p.equity);
  equityChart.data.datasets[0].borderColor = color;
  equityChart.update('none');
  const ep = $('equity-pnl');
  if (ep) { ep.textContent = fmtPnl(last); ep.style.color = last>=0?'var(--green)':'var(--red)'; }
}

// ── Render: Live state ────────────────────────────────────────────────────────
function renderState(s) {
  if (!s) return;

  // Mode
  const mb = $('mode-badge');
  if (mb) { mb.textContent = s.paper_trading ? 'PAPER' : 'LIVE'; mb.className = 'mode-badge ' + (s.paper_trading ? 'paper' : 'live'); }

  // Bot state pill
  const pill = $('state-pill');
  const stTxt = $('state-text');
  const brt   = s.brt_state || 'NEUTRAL';
  if (stTxt) stTxt.textContent = brt;
  if (pill) {
    pill.className = 'state-pill ';
    if      (brt === 'WATCHING_LONG')  pill.classList.add('watch-long');
    else if (brt === 'WATCHING_SHORT') pill.classList.add('watch-short');
    else                               pill.classList.add('neutral');
  }
  const wl = $('watch-line');
  if (wl) {
    wl.textContent = (s.watch_level && s.watch_ltype)
      ? `${s.watch_ltype} @ ${fp(s.watch_level)}`
      : 'No active setup';
    wl.style.color = brt === 'WATCHING_LONG' ? 'var(--green)' : brt === 'WATCHING_SHORT' ? 'var(--red)' : '';
  }

  // Session / meta
  setText('session-val',  s.session_open ? 'OPEN' : 'CLOSED');
  setText('next-check',   nextCheck());
  setText('last-update',  s.timestamp ? relTime(s.timestamp) : '—');

  // P&L
  const pnl   = s.daily_pnl ?? 0;
  const pnlEl = $('pnl-big');
  if (pnlEl) { pnlEl.textContent = fmtPnl(pnl); pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)'; }

  // Price
  const price = s.close, ema = s.ema20;
  setText('price-big', fp(price));
  setText('ema-val',   fp(ema));
  const distEl = $('ema-dist');
  if (distEl && price && ema) {
    const d = price - ema;
    distEl.textContent = (d >= 0 ? '+' : '') + f(d, 2) + ' pts';
    distEl.style.color = d >= 0 ? 'var(--green)' : 'var(--red)';
  }

  // ADX
  const adxMin = s.adx_min ?? 20;
  const adxOk  = s.adx >= adxMin;
  setText('adx-val', f(s.adx, 1));
  const adxBar    = $('adx-bar');
  const adxThresh = $('adx-thresh');
  const adxBadge  = $('adx-badge');
  if (adxBar)    { adxBar.style.width = Math.min(100,(s.adx/60)*100)+'%'; adxBar.style.background = adxOk?'var(--green)':'var(--red)'; }
  if (adxThresh) adxThresh.style.left = Math.min(95,(adxMin/60)*100)+'%';
  if (adxBadge)  { adxBadge.textContent = adxOk?'PASS':'FAIL'; adxBadge.className = 'il-badge '+(adxOk?'pass':'fail'); }

  // RSI
  const rsiOk = s.rsi > 35 && s.rsi < 75;
  setText('rsi-val', f(s.rsi, 1));
  const rsiBar   = $('rsi-bar');
  const rsiBadge = $('rsi-badge');
  if (rsiBar)   rsiBar.style.width = Math.min(100, s.rsi ?? 50) + '%';
  if (rsiBadge) { rsiBadge.textContent = rsiOk?'PASS':'WARN'; rsiBadge.className = 'il-badge '+(rsiOk?'pass':'warn'); }

  // ATR
  setText('atr-val', f(s.atr, 2));
  const atrBar = $('atr-bar');
  if (atrBar) atrBar.style.width = Math.min(100,((s.atr??0)/20)*100)+'%';

  // Levels table
  const rows = [
    { key:'vwap', label:'VWAP',    cls:'lt-vwap', icon:'V', val:s.vwap },
    { key:'pdh',  label:'PDH',     cls:'lt-pdh',  icon:'H', val:s.pdh  },
    { key:'pdl',  label:'PDL',     cls:'lt-pdl',  icon:'L', val:s.pdl  },
    { key:'shi',  label:'Swing Hi',cls:'lt-shi',  icon:'↑', val:s.swing_hi },
    { key:'slo',  label:'Swing Lo',cls:'lt-slo',  icon:'↓', val:s.swing_lo },
  ];
  const tbody = $('levels-tbody');
  if (tbody) {
    tbody.innerHTML = rows.map(r => {
      const diff = r.val && price ? r.val - price : null;
      const distCls = diff == null ? '' : diff >= 0 ? 'style="color:var(--green)"' : 'style="color:var(--red)"';
      const distTxt = diff == null ? '—' : (diff >= 0 ? '+' : '') + f(diff, 1);
      const pct     = diff == null ? 0 : Math.min(90, Math.abs(diff)/price*100*30);
      const barClr  = diff == null ? 'var(--s3)' : diff >= 0 ? 'var(--green)' : 'var(--red)';
      const isWatch = s.watch_ltype && r.label.includes(s.watch_ltype);
      const rowStyle = isWatch ? `style="background:${diff>=0?'rgba(34,197,94,0.06)':'rgba(239,68,68,0.06)'};border-radius:4px"` : '';
      return `<tr ${rowStyle}>
        <td><span class="lt-icon ${r.cls}">${r.icon}</span></td>
        <td class="lt-name">${r.label}</td>
        <td class="mono" style="font-size:12px;font-weight:600">${fp(r.val)}</td>
        <td><div class="lbar-wrap"><div class="lbar" style="width:${pct}%;background:${barClr}"></div></div></td>
        <td ${distCls} style="font-family:var(--mono);font-size:11px;text-align:right">${distTxt}</td>
      </tr>`;
    }).join('');
  }
}

// ── Render: Regime ────────────────────────────────────────────────────────────
function renderRegime(regime, state) {
  if (!regime) return;
  const r     = regime.regime || 'NORMAL';
  const color = REGIME_COLORS[r] || '#3B82F6';
  setText('rb-name', r);
  const nameEl = $('rb-name'); if (nameEl) nameEl.style.color = color;
  setText('rb-desc', regime.description || '—');

  const bar = document.querySelector('.regime-bar');
  if (bar) bar.style.borderBottom = `2px solid ${color}38`;

  const badge = $('rb-badge');
  if (badge) {
    badge.textContent = regime.can_trade ? '✓ TRADING' : '✗ BLOCKED';
    badge.className   = 'rb-badge ' + (regime.can_trade ? 'ok' : 'off');
  }

  if (state) {
    setText('rc-vix',   state.vix       != null ? f(state.vix, 1)          : '—');
    setText('rc-yield', state.yield_10y != null ? f(state.yield_10y, 3)+'%': '—');
    setText('rc-dxy',   state.dxy       != null ? f(state.dxy, 2)          : '—');
  }

  // Highlight active regime card in Strategies tab
  document.querySelectorAll('.regime-card').forEach(card => {
    card.classList.remove('is-active');
    const b = card.querySelector('.rc-active-badge');
    if (b) b.style.display = 'none';
  });
  const activeCard = document.querySelector(`.regime-card[data-regime="${r}"]`);
  if (activeCard) {
    activeCard.classList.add('is-active');
    activeCard.style.color = color;
    const b = activeCard.querySelector('.rc-active-badge');
    if (b) b.style.display = 'flex';
  }
}

// ── Render: Trades ────────────────────────────────────────────────────────────
function renderTrades(trades, summary) {
  if (summary) {
    setText('ps-wins',   `${summary.wins   ?? 0}W`);
    setText('ps-losses', `${summary.losses ?? 0}L`);
    setText('ps-total',  `${summary.total  ?? 0} trades`);
  }
  const tc = $('trade-count');
  if (tc && trades) tc.textContent = trades.length + ' records';
  const tbody = $('trades-tbody'); if (!tbody) return;
  if (!trades?.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty-cell">No trades recorded yet</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map(t => {
    const hasPnl = t.pnl != null;
    const pCls   = !hasPnl ? 'pnl-open' : t.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    const pTxt   = !hasPnl ? 'open' : fmtPnl(t.pnl);
    return `<tr>
      <td>${shortTs(t.timestamp)}</td>
      <td class="${t.direction==='LONG'?'dir-long':'dir-short'}">${t.direction||'—'}</td>
      <td>${t.level_type||'—'}</td>
      <td>${fp(t.entry_price)}</td>
      <td>${fp(t.stop_loss)}</td>
      <td>${fp(t.take_profit)}</td>
      <td>${fp(t.exit_price)}</td>
      <td style="color:var(--text2)">${t.exit_reason||'—'}</td>
      <td class="${pCls}">${pTxt}</td>
      <td style="color:var(--text3)">${t.regime||'—'}</td>
      <td style="color:var(--text3)">${t.vix!=null?f(t.vix,1):'—'}</td>
    </tr>`;
  }).join('');
}

// ── Render: Activity feed ─────────────────────────────────────────────────────
function renderFeed(events) {
  if (!events?.length) return;
  const feedEl = $('feed-list'); if (!feedEl) return;
  const newEvs = events.filter(e => e.id > lastEvId);
  if (!newEvs.length) return;
  lastEvId = events[0].id;
  const lvlCls = { INFO:'fi-info', TRADE:'fi-trade', WARN:'fi-warn', ERROR:'fi-error' };
  // Remove placeholder
  const placeholder = feedEl.querySelector('.feed-empty');
  if (placeholder) placeholder.remove();
  for (const ev of newEvs) {
    const cls = lvlCls[ev.level] || 'fi-info';
    const div = document.createElement('div');
    div.className = `feed-item ${cls}`;
    div.innerHTML = `<div class="fi-dot"></div>
      <div class="fi-content">
        <span class="fi-msg">${ev.message}</span>
        ${ev.detail ? `<span class="fi-detail">${ev.detail}</span>` : ''}
        <span class="fi-time">${relTime(ev.timestamp)}</span>
      </div>`;
    feedEl.prepend(div);
  }
  while (feedEl.children.length > 40) feedEl.removeChild(feedEl.lastChild);
}

// ── Full render ───────────────────────────────────────────────────────────────
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
  ws.onopen    = () => { wsAlive = true; wsRetries = 0; setConn('live'); };
  ws.onmessage = e => { try { render(JSON.parse(e.data)); } catch(err) { console.warn(err); } };
  ws.onerror   = ()  => ws.close();
  ws.onclose   = () => { wsAlive = false; setConn('retry'); scheduleReconnect(); };
}
function scheduleReconnect() {
  setTimeout(connectWS, Math.min(30_000, RECONNECT * Math.pow(1.5, wsRetries++)));
}

// ── REST fallback ─────────────────────────────────────────────────────────────
async function pollRest() {
  if (wsAlive) return;
  try {
    const res  = await fetch('/api/all'); if (!res.ok) throw new Error();
    render(await res.json());
    setConn('polling');
  } catch { setConn('dead'); }
}

// ── Init ──────────────────────────────────────────────────────────────────────
initChart();
connectWS();
pollRest();
setInterval(pollRest, POLL_MS);
