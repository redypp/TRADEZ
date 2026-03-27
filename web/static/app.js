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
    if (btn.dataset.tab === 'journal') renderJournal(window._lastTrades);
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
    { key:'vwap',    label:'VWAP',    type:'Intraday',   cls:'lt-vwap', icon:'V', val:s.vwap },
    { key:'pdh',     label:'PDH',     type:'Prev Day',   cls:'lt-pdh',  icon:'H', val:s.pdh  },
    { key:'pdl',     label:'PDL',     type:'Prev Day',   cls:'lt-pdl',  icon:'L', val:s.pdl  },
    { key:'poc',     label:'VP POC',  type:'Vol Profile',cls:'lt-vp',   icon:'P', val:s.prior_poc },
    { key:'vah',     label:'VP VAH',  type:'Vol Profile',cls:'lt-vp',   icon:'↑', val:s.prior_vah },
    { key:'val',     label:'VP VAL',  type:'Vol Profile',cls:'lt-vp',   icon:'↓', val:s.prior_val },
    { key:'eqh',     label:'Eq. High',type:'SMC Liq.',   cls:'lt-eqh',  icon:'⚡', val:s.eqh },
    { key:'eql',     label:'Eq. Low', type:'SMC Liq.',   cls:'lt-eql',  icon:'⚡', val:s.eql },
    { key:'fvgb',    label:'FVG Bull',type:'FVG Zone',   cls:'lt-fvg',  icon:'▲', val:s.fvg_bull_low },
    { key:'fvgs',    label:'FVG Bear',type:'FVG Zone',   cls:'lt-fvg',  icon:'▼', val:s.fvg_bear_high },
    { key:'shi',     label:'Swing Hi',type:'Swing',      cls:'lt-shi',  icon:'↑', val:s.swing_hi },
    { key:'slo',     label:'Swing Lo',type:'Swing',      cls:'lt-slo',  icon:'↓', val:s.swing_lo },
  ];
  const tbody = $('levels-tbody');
  if (tbody) {
    tbody.innerHTML = rows.filter(r => r.val != null).map(r => {
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
        <td class="lt-type" style="color:var(--text3);font-size:10px">${r.type}</td>
        <td class="mono" style="font-size:12px;font-weight:600">${fp(r.val)}</td>
        <td><div class="lbar-wrap"><div class="lbar" style="width:${pct}%;background:${barClr}"></div></div></td>
        <td ${distCls} style="font-family:var(--mono);font-size:11px;text-align:right">${distTxt}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="6" class="empty-cell">Awaiting data</td></tr>';
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
    // VPOC migration indicator
    const vm = state.vpoc_migration || 'NEUTRAL';
    const vmEl = $('vpoc-migration');
    if (vmEl) {
      const arrow = vm === 'RISING' ? '↑' : vm === 'FALLING' ? '↓' : '→';
      const col   = vm === 'RISING' ? 'var(--green)' : vm === 'FALLING' ? 'var(--red)' : 'var(--text3)';
      vmEl.textContent = `VPOC ${arrow}`;
      vmEl.style.color = col;
    }
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

// ── Render: Entry Filters ─────────────────────────────────────────────────────
function renderFilters(s, settings) {
  const row = $('filters-row'); if (!row) return;
  if (!s) return;

  const etNow = new Date(new Date().toLocaleString('en-US', { timeZone:'America/New_York' }));
  const h = etNow.getHours();
  const lunchStart = settings?.brt_lunch_start ?? 12;
  const lunchEnd   = settings?.brt_lunch_end   ?? 14;
  const sessStart  = settings?.brt_session_start ?? 10;
  const sessEnd    = settings?.brt_session_end   ?? 15;

  const inLunch   = h >= lunchStart && h < lunchEnd;
  const inSession = h >= sessStart && h < sessEnd && !inLunch;
  const sessLabel = inLunch ? `LUNCH (${lunchStart}–${lunchEnd} ET)`
                  : inSession ? `OPEN (${sessStart}–${sessEnd} ET)`
                  : `CLOSED`;
  const sessOk = inSession;

  const adxMin = s.adx_min ?? settings?.brt_adx_min ?? 20;
  const adxOk  = (s.adx ?? 0) >= adxMin;
  const rsiOk  = s.rsi > (settings?.brt_rsi_long_min ?? 35) && s.rsi < (settings?.brt_rsi_long_max ?? 75);
  const emaOk  = s.close != null && s.ema20 != null && s.close > s.ema20;

  const filters = [
    { label:'Session',     val: sessLabel,                        ok: sessOk,   warn: inLunch },
    { label:'Regime',      val: (s.regime||'?') + (s.can_trade===false?' · BLOCKED':' · OK'), ok: s.can_trade !== false, warn: false },
    { label:'ADX',         val: `${f(s.adx,1)} (≥${adxMin})`,    ok: adxOk,    warn: false },
    { label:'RSI',         val: `${f(s.rsi,1)} (${settings?.brt_rsi_long_min??35}–${settings?.brt_rsi_long_max??75})`, ok: rsiOk, warn: !rsiOk },
    { label:'EMA Trend',   val: emaOk ? `+${f(s.close-s.ema20,1)} above` : s.close && s.ema20 ? `${f(s.close-s.ema20,1)} below` : '—', ok: emaOk, warn: false },
    { label:'VSA Filter',  val: settings?.brt_vsa_close ? 'ACTIVE' : 'OFF',    ok: true,     warn: !settings?.brt_vsa_close },
    { label:'Sweep Req',   val: settings?.brt_require_sweep ? 'REQUIRED' : 'OPTIONAL', ok: true, warn: settings?.brt_require_sweep },
  ];

  const passCount = filters.filter(f => f.ok && !f.warn).length;
  const pc = $('filter-pass-count');
  if (pc) { pc.textContent = `${passCount}/${filters.length} passing`; pc.style.color = passCount >= 5 ? 'var(--green)' : 'var(--amber)'; }

  row.innerHTML = filters.map(fil => {
    const cls = fil.warn ? 'warn' : fil.ok ? 'pass' : 'fail';
    const dot = fil.warn ? '⚠' : fil.ok ? '✓' : '✗';
    return `<div class="filter-chip ${cls}">
      <span class="fc-dot">${dot}</span>
      <div class="fc-body">
        <span class="fc-name">${fil.label}</span>
        <span class="fc-val">${fil.val}</span>
      </div>
    </div>`;
  }).join('');
}

// ── Render: Journal ───────────────────────────────────────────────────────────
function renderJournal(trades) {
  if (!$('tab-journal')?.classList.contains('active')) return; // only render if visible

  const cards = $('journal-cards'); if (!cards) return;
  if (!trades?.length) {
    cards.innerHTML = '<div class="journal-empty">No trades recorded yet.</div>';
    return;
  }

  // Stats
  const closed = trades.filter(t => t.pnl != null);
  const wins   = closed.filter(t => t.pnl > 0);
  const losses = closed.filter(t => t.pnl <= 0);
  const sweepWins   = closed.filter(t => t.liquidity_sweep && t.pnl > 0);
  const sweepClosed = closed.filter(t => t.liquidity_sweep);
  const totalPnl    = closed.reduce((a, t) => a + (t.pnl || 0), 0);
  const avgWin  = wins.length   ? wins.reduce((a,t)=>a+t.pnl,0)/wins.length     : null;
  const avgLoss = losses.length ? losses.reduce((a,t)=>a+t.pnl,0)/losses.length : null;

  setText('jst-total',    trades.length);
  const wrEl = $('jst-wr');
  if (wrEl) {
    const wr = closed.length ? Math.round(wins.length/closed.length*100) : 0;
    wrEl.textContent = closed.length ? wr + '%' : '—';
    wrEl.style.color = wr >= 50 ? 'var(--green)' : wr >= 40 ? 'var(--amber)' : 'var(--red)';
  }
  const pnlEl = $('jst-pnl');
  if (pnlEl) { pnlEl.textContent = fmtPnl(totalPnl); pnlEl.style.color = totalPnl >= 0 ? 'var(--green)' : 'var(--red)'; }
  const swEl = $('jst-sweep-wr');
  if (swEl) swEl.textContent = sweepClosed.length ? Math.round(sweepWins.length/sweepClosed.length*100) + '%' : '—';
  const awEl = $('jst-avg-win');
  if (awEl) { awEl.textContent = avgWin != null ? fmtPnl(avgWin) : '—'; awEl.style.color = 'var(--green)'; }
  const alEl = $('jst-avg-loss');
  if (alEl) { alEl.textContent = avgLoss != null ? fmtPnl(avgLoss) : '—'; alEl.style.color = 'var(--red)'; }

  // Trade cards
  cards.innerHTML = trades.map(t => {
    const isOpen  = t.pnl == null;
    const isWin   = !isOpen && t.pnl > 0;
    const isLoss  = !isOpen && t.pnl <= 0;
    const cardCls = isOpen ? 'open' : isWin ? 'win' : 'loss';
    const pnlTxt  = isOpen ? '<span class="jc-open">OPEN</span>' : `<span class="jc-pnl ${isWin?'pos':'neg'}">${fmtPnl(t.pnl)}</span>`;
    const outcome = isOpen ? 'OPEN' : t.exit_reason || (isWin ? 'TP' : 'SL');

    // Confluence checks (infer from stored data)
    const checks = [];
    if (t.level_type) checks.push({ ok: true, text: `Level: ${t.level_type}` });
    if (t.regime)     checks.push({ ok: true, text: `Regime: ${t.regime}` });
    if (t.vix != null) checks.push({ ok: t.vix < 30, warn: t.vix >= 20, text: `VIX: ${f(t.vix,1)}` });
    if (t.liquidity_sweep) checks.push({ ok: true, sweep: true, text: 'Liquidity sweep ✓' });

    const checkHtml = checks.map(c =>
      `<span class="jcc-item ${c.sweep?'sweep':c.warn?'warn':c.ok?'pass':'fail'}">${c.text}</span>`
    ).join('');

    // Failure analysis for losses
    let failHtml = '';
    if (isLoss) {
      const reasons = [];
      if (t.level_type === 'SWING') reasons.push('Swing level — lower institutional significance than VWAP/PDH');
      if (t.vix != null && t.vix >= 20) reasons.push(`Elevated VIX (${f(t.vix,1)}) — wider noise, reduced setup quality`);
      if (!t.liquidity_sweep) reasons.push('No liquidity sweep at entry — stop hunt not confirmed');
      if (reasons.length === 0) reasons.push('Market moved against setup — within normal loss distribution');
      failHtml = `<div class="jc-failure">
        <span class="jcf-label">Analysis:</span>
        ${reasons.map(r => `<span class="jcf-item">• ${r}</span>`).join('')}
      </div>`;
    }

    const rr = t.entry_price && t.stop_loss && t.take_profit
      ? ((t.take_profit - t.entry_price) / (t.entry_price - t.stop_loss)).toFixed(1) + 'R'
      : '—';

    return `<div class="journal-card ${cardCls}">
      <div class="jc-header">
        <div class="jc-left">
          <span class="jc-dir ${t.direction==='LONG'?'long':'short'}">${t.direction||'?'}</span>
          <span class="jc-level">${t.level_type||'—'}</span>
          <span class="jc-time">${shortTs(t.timestamp)}</span>
        </div>
        <div class="jc-right">
          <span class="jc-outcome ${isOpen?'open':isWin?'win':'loss'}">${outcome}</span>
          ${pnlTxt}
        </div>
      </div>
      <div class="jc-prices">
        <div class="jcp-item"><span class="jcp-lbl">Entry</span><span class="jcp-val mono">${fp(t.entry_price)}</span></div>
        <div class="jcp-item"><span class="jcp-lbl">Stop</span><span class="jcp-val mono red">${fp(t.stop_loss)}</span></div>
        <div class="jcp-item"><span class="jcp-lbl">Target</span><span class="jcp-val mono green">${fp(t.take_profit)}</span></div>
        <div class="jcp-item"><span class="jcp-lbl">Exit</span><span class="jcp-val mono">${fp(t.exit_price)}</span></div>
        <div class="jcp-item"><span class="jcp-lbl">R:R</span><span class="jcp-val mono">${rr}</span></div>
        <div class="jcp-item"><span class="jcp-lbl">Size</span><span class="jcp-val mono">${t.contracts||1}×</span></div>
      </div>
      <div class="jc-tags">${checkHtml}</div>
      ${failHtml}
    </div>`;
  }).join('');
}

// ── Render: Trades ────────────────────────────────────────────────────────────
function renderTrades(trades, summary) {
  window._lastTrades = trades;
  if (summary) {
    setText('ps-wins',   `${summary.wins   ?? 0}W`);
    setText('ps-losses', `${summary.losses ?? 0}L`);
    setText('ps-total',  `${summary.total  ?? 0} trades`);
  }
  const tc = $('trade-count');
  if (tc && trades) tc.textContent = trades.length + ' records';
  const tbody = $('trades-tbody'); if (!tbody) return;
  if (!trades?.length) {
    tbody.innerHTML = '<tr><td colspan="12" class="empty-cell">No trades recorded yet</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map(t => {
    const hasPnl = t.pnl != null;
    const pCls   = !hasPnl ? 'pnl-open' : t.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    const pTxt   = !hasPnl ? 'open' : fmtPnl(t.pnl);
    const sweepBadge = t.liquidity_sweep ? '<span class="sweep-badge">SWEEP</span>' : '—';
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
      <td>${sweepBadge}</td>
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
  const lvlCls = { INFO:'fi-info', TRADE:'fi-trade', WARN:'fi-warn', ERROR:'fi-error', AI:'fi-ai' };
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

// ── AI Advisory ───────────────────────────────────────────────────────────────
function renderAdvisory(advisory) {
  const body = $('advisory-body');
  const triggerEl = $('advisory-trigger');
  const tsEl = $('advisory-ts');
  if (!body || !advisory?.available) return;

  const sentiment = (advisory.sentiment || 'NEUTRAL').toUpperCase();
  const quality   = (advisory.signal_quality || 'N/A').toUpperCase();
  const trigger   = (advisory.trigger || 'HOURLY').toUpperCase();
  const flags     = advisory.risk_flags || [];

  const sentimentCls = { BULLISH:'bullish', BEARISH:'bearish', NEUTRAL:'neutral' }[sentiment] || 'neutral';
  const qualityCls   = { HIGH:'advisory-quality-high', MEDIUM:'advisory-quality-medium',
                         LOW:'advisory-quality-low', 'N/A':'advisory-quality-na' }[quality] || 'advisory-quality-na';
  const sentimentIcon = { BULLISH:'▲', BEARISH:'▼', NEUTRAL:'◆' }[sentiment] || '◆';

  if (triggerEl) triggerEl.textContent = trigger;
  if (tsEl) tsEl.textContent = advisory.timestamp || '';

  const flagsHtml = flags.length
    ? `<div class="advisory-flags">${flags.map(f => `<div class="advisory-flag">⚠ ${f}</div>`).join('')}</div>`
    : '';

  const specialistsHtml = (advisory.grok_summary || advisory.gpt4_summary) ? `
    <div class="advisory-specialists">
      ${advisory.grok_summary ? `<div class="advisory-spec">
        <div class="advisory-spec-label">GROK · SENTIMENT</div>
        <div class="advisory-spec-text">${advisory.grok_summary}</div>
      </div>` : ''}
      ${advisory.gpt4_summary ? `<div class="advisory-spec">
        <div class="advisory-spec-label">GPT-4 · MACRO</div>
        <div class="advisory-spec-text">${advisory.gpt4_summary}</div>
      </div>` : ''}
    </div>` : '';

  body.innerHTML = `
    <div class="advisory-headline">${advisory.headline || ''}</div>
    <div class="advisory-meta">
      <span class="advisory-badge ${sentimentCls}">${sentimentIcon} ${sentiment}</span>
      ${quality !== 'N/A' ? `<span class="${qualityCls}">Setup: ${quality}</span>` : ''}
      ${advisory.watch_for && advisory.watch_for !== 'n/a'
        ? `<span style="font-size:11px;color:var(--text3)">Watch: ${advisory.watch_for}</span>` : ''}
    </div>
    ${advisory.brief ? `<div class="advisory-brief">${advisory.brief}</div>` : ''}
    ${flagsHtml}
    ${specialistsHtml}
  `;
}

// ── Full render ───────────────────────────────────────────────────────────────
function render(data) {
  if (!data) return;
  renderState(data.state);
  renderRegime(data.regime, data.state);
  renderFilters(data.state, data.settings);
  renderTrades(data.trades, data.summary);
  renderFeed(data.events);
  updateChart(data.equity);
  renderJournal(data.trades);
  renderAdvisory(data.advisory);
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

// ── Strategy Lab ──────────────────────────────────────────────────────────────

let labEquityChart = null;

// Instrument options per strategy
const LAB_INSTRUMENTS = {
  BRT:      ['MES', 'ES'],
  ORB:      ['MES', 'ES', 'SPY', 'QQQ'],
  DONCHIAN: ['MGC', 'GC', 'SIL'],
  RSI2:     ['SPY', 'QQQ', 'IWM', 'GLD'],
  VWAP_MR:  ['MES', 'ES'],
};

// Timeframe options per strategy (label → value)
const LAB_TIMEFRAMES = {
  BRT:      [['5 min', '5min'], ['15 min', '15min'], ['1 hour', '1h']],
  ORB:      [['5 min', '5min'], ['15 min', '15min'], ['1 hour', '1h']],
  DONCHIAN: [['Daily', '1d']],
  RSI2:     [['Daily', '1d']],
  VWAP_MR:  [['5 min', '5min'], ['15 min', '15min']],
};

const LAB_DEFAULT_TF = {
  BRT: '15min', ORB: '1h', DONCHIAN: '1d', RSI2: '1d', VWAP_MR: '5min',
};

function labUpdateSelects(strat) {
  // instruments
  const symSel = $('lab-symbol');
  symSel.innerHTML = (LAB_INSTRUMENTS[strat] || [])
    .map(s => `<option value="${s}">${s}</option>`).join('');

  // timeframes
  const tfSel  = $('lab-timeframe');
  const defTf  = LAB_DEFAULT_TF[strat] || '';
  tfSel.innerHTML = (LAB_TIMEFRAMES[strat] || [])
    .map(([label, val]) => `<option value="${val}"${val === defTf ? ' selected' : ''}>${label}</option>`)
    .join('');
}

// Update dropdowns when strategy changes
$('lab-strategy') && $('lab-strategy').addEventListener('change', () => {
  labUpdateSelects($('lab-strategy').value);
});

// Initialize dropdowns for the default strategy on page load
$('lab-strategy') && labUpdateSelects($('lab-strategy').value);

$('lab-run-btn') && $('lab-run-btn').addEventListener('click', async () => {
  const strategy  = $('lab-strategy').value;
  const symbol    = $('lab-symbol').value;
  const timeframe = $('lab-timeframe').value;
  const capital   = parseFloat($('lab-capital').value) || 10000;
  const runMC     = $('lab-mc').checked;

  // Show loading, hide old results
  $('lab-results').style.display = 'none';
  $('lab-warning').style.display = 'none';
  $('lab-loading').style.display = 'flex';
  $('lab-run-btn').disabled = true;

  try {
    const res = await fetch('/api/lab/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        strategy, symbol, timeframe,
        initial_capital: capital,
        run_monte_carlo: runMC,
        n_mc_sims: 2000,
      }),
    });
    const data = await res.json();

    if (data.error) {
      $('lab-warning').textContent = '⚠ ' + data.error;
      $('lab-warning').style.display = 'block';
      return;
    }

    labRenderResults(data);

  } catch (err) {
    $('lab-warning').textContent = '⚠ Request failed: ' + err.message;
    $('lab-warning').style.display = 'block';
  } finally {
    $('lab-loading').style.display = 'none';
    $('lab-run-btn').disabled = false;
  }
});

function labRenderResults(data) {
  const m = data.metrics || {};
  const mc = data.monte_carlo;

  // Warning
  if (data.warning) {
    $('lab-warning').textContent = '⚠ ' + data.warning;
    $('lab-warning').style.display = 'block';
  }

  // Metrics
  setText('lm-trades',  data.n_trades);
  setText('lm-trades-sub', `${data.timeframe} · ${data.data_bars} bars`);

  const wr = m.win_rate;
  setText('lm-wr', wr != null ? wr.toFixed(1) + '%' : '—');
  $('lm-wr').className = 'lmc-value ' + (wr >= 50 ? 'val-green' : wr >= 40 ? 'val-yellow' : 'val-red');

  const pf = m.profit_factor;
  setText('lm-pf', pf != null ? pf.toFixed(2) : '—');
  $('lm-pf').className = 'lmc-value ' + (pf >= 2 ? 'val-green' : pf >= 1.3 ? 'val-yellow' : 'val-red');

  const sh = m.sharpe_ratio;
  setText('lm-sharpe', sh != null ? sh.toFixed(2) : '—');
  $('lm-sharpe').className = 'lmc-value ' + (sh >= 1.5 ? 'val-green' : sh >= 0.8 ? 'val-yellow' : 'val-red');

  const ret = m.total_return_pct;
  setText('lm-ret', ret != null ? (ret >= 0 ? '+' : '') + ret.toFixed(1) + '%' : '—');
  $('lm-ret').className = 'lmc-value ' + (ret >= 0 ? 'val-green' : 'val-red');

  const dd = m.max_drawdown_pct;
  setText('lm-dd', dd != null ? dd.toFixed(1) + '%' : '—');
  $('lm-dd').className = 'lmc-value ' + (dd > -10 ? 'val-green' : dd > -20 ? 'val-yellow' : 'val-red');

  // Equity curve
  labRenderEquityChart(data.equity, data.initial_capital || 10000);

  // Monte Carlo
  if (mc && !mc.error && $('lab-mc-section')) {
    $('lab-mc-section').style.display = 'block';
    setText('mc-ruin',    (mc.ruin_probability * 100).toFixed(1) + '%');
    $('mc-ruin').className = 'lmc2-value ' + (mc.ruin_probability < 0.05 ? 'val-green' : 'val-red');

    setText('mc-profit',  (mc.prob_profit * 100).toFixed(1) + '%');
    $('mc-profit').className = 'lmc2-value ' + (mc.prob_profit > 0.70 ? 'val-green' : 'val-yellow');

    setText('mc-median',  '$' + mc.median_final_equity.toLocaleString('en-US', {maximumFractionDigits:0}));
    setText('mc-p05',     '$' + mc.p05_final_equity.toLocaleString('en-US', {maximumFractionDigits:0}));
    $('mc-p05').className = 'lmc2-value ' + (mc.p05_final_equity > (data.metrics?.initial_capital || 10000) ? 'val-green' : 'val-red');

    setText('mc-med-dd',  (mc.median_max_dd * 100).toFixed(1) + '%');
    setText('mc-p95-dd',  (mc.p95_max_dd * 100).toFixed(1) + '%');
    $('mc-p95-dd').className = 'lmc2-value ' + (mc.p95_max_dd < 0.40 ? 'val-green' : 'val-red');

    const verdict = $('mc-verdict');
    if (mc.passes_all_gates) {
      verdict.textContent = '✓ PASSES all Monte Carlo gates — strategy is statistically robust';
      verdict.className = 'mc-verdict verdict-pass';
    } else {
      verdict.textContent = '✗ FAILS Monte Carlo gates — do NOT trade live with these parameters';
      verdict.className = 'mc-verdict verdict-fail';
    }
  } else if (mc && mc.error) {
    $('lab-mc-section') && ($('lab-mc-section').style.display = 'none');
  }

  // Trade table
  const tbody = $('lab-trade-tbody');
  if (tbody) {
    tbody.innerHTML = '';
    (data.trades || []).slice(-50).reverse().forEach(t => {
      const pnl = t.pnl;
      const cls = pnl > 0 ? 'tr-win' : 'tr-loss';
      tbody.insertAdjacentHTML('beforeend', `
        <tr class="${cls}">
          <td>${shortTs(t.entry_time)}</td>
          <td>${shortTs(t.exit_time)}</td>
          <td class="${t.direction === 'LONG' ? 'dir-long' : 'dir-short'}">${t.direction}</td>
          <td>${t.entry.toFixed(2)}</td>
          <td>${t.exit.toFixed(2)}</td>
          <td>${fmtPnl(pnl)}</td>
          <td class="${t.result === 'TP' ? 'res-tp' : 'res-sl'}">${t.result}</td>
        </tr>`);
    });
    setText('lab-trade-count', `(last ${Math.min(50, (data.trades||[]).length)} of ${data.n_trades})`);
  }

  $('lab-results').style.display = 'block';
}

function labRenderEquityChart(points, initialCapital) {
  const ctx = $('lab-equity-chart');
  if (!ctx) return;

  if (labEquityChart) { labEquityChart.destroy(); labEquityChart = null; }

  const labels = points.map(p => p.i);
  const values = points.map(p => p.equity);
  const color  = values[values.length - 1] >= initialCapital ? '#22C55E' : '#EF4444';

  labEquityChart = new Chart(ctx.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: color,
        backgroundColor: color + '18',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.2,
      }],
    },
    options: {
      responsive: true,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: {
          ticks: {
            color: '#9CA3AF',
            callback: v => '$' + v.toLocaleString('en-US', {maximumFractionDigits:0}),
          },
          grid: { color: '#1F2937' },
        },
      },
    },
  });
}

// ── Stack Tab — Broker Status & Setup Checklist ───────────────────────────────

async function fetchBrokerStatus() {
  try {
    const res = await fetch('/api/broker/status');
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

function renderStackRisk(settings) {
  if (!settings) return;
  const pct = v => v != null ? (v * 100).toFixed(1) + '%' : '—';
  const rpt  = settings.risk_per_trade;
  const mdd  = settings.max_daily_drawdown;

  const rptEl  = $('srg-risk-per-trade');
  const mddEl  = $('srg-max-drawdown');
  const heatEl = $('srg-portfolio-heat');
  const rrEl   = $('srg-tp-rr');
  const sessEl = $('srg-session');
  const lunchEl= $('srg-lunch');

  if (rptEl)  { rptEl.textContent  = pct(rpt); rptEl.className = 'srg-val ' + (rpt <= 0.01 ? 'green' : rpt <= 0.02 ? 'amber' : 'red'); }
  if (mddEl)  { mddEl.textContent  = pct(mdd); mddEl.className = 'srg-val ' + (mdd <= 0.03 ? 'green' : mdd <= 0.05 ? 'amber' : 'red'); }
  if (heatEl) heatEl.textContent   = pct(settings.portfolio_heat_max);
  if (rrEl)   rrEl.textContent     = settings.brt_tp_rr != null ? settings.brt_tp_rr + 'R' : '—';
  if (sessEl) sessEl.textContent   = `${settings.brt_session_start ?? 10}:00 – ${settings.brt_session_end ?? 15}:00 ET`;
  if (lunchEl)lunchEl.textContent  = `${settings.brt_lunch_start ?? 12}:00 – ${settings.brt_lunch_end ?? 13}:00 ET`;

  const src = $('risk-config-source');
  if (src) src.textContent = '(live from /api/settings)';
}

function renderSetupChecklist(broker) {
  const el = $('setup-checklist');
  if (!el) return;
  if (!broker) { el.innerHTML = '<div class="sc-loading">Could not fetch status — is the server running?</div>'; return; }

  const items = [
    {
      label: 'Paper trading mode',
      ok: true,
      val: broker.paper_trading ? 'PAPER (safe)' : 'LIVE',
      note: broker.paper_trading ? 'Safe to test — no real money at risk' : '⚠ LIVE mode — real money',
    },
    {
      label: 'Tradovate credentials',
      ok: broker.tradovate?.credentials_set,
      val: broker.tradovate?.credentials_set ? `Set (${broker.tradovate.mode})` : 'Not set — pending',
      note: broker.tradovate?.credentials_set ? null : 'Waiting for Tradovate API subscription',
    },
    {
      label: 'Alpaca credentials',
      ok: broker.alpaca?.credentials_set,
      val: broker.alpaca?.credentials_set ? 'Set' : 'Not set',
      note: broker.alpaca?.credentials_set ? null : 'Required for stock/ETF strategies (SPY, QQQ)',
    },
    {
      label: 'Telegram alerts',
      ok: broker.telegram?.configured,
      val: broker.telegram?.configured ? `Active (chat: ${broker.telegram.chat_id})` : 'Not configured',
      note: broker.telegram?.configured ? null : 'Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env',
    },
    {
      label: 'Risk: per-trade limit',
      ok: (broker.risk?.per_trade_pct ?? 99) <= 1.5,
      val: broker.risk ? broker.risk.per_trade_pct.toFixed(1) + '%' : '—',
      note: (broker.risk?.per_trade_pct ?? 99) > 1.5 ? 'Recommended: 1.0% for paper trading' : null,
    },
    {
      label: 'Risk: daily stop',
      ok: (broker.risk?.daily_stop_pct ?? 99) <= 5,
      val: broker.risk ? broker.risk.daily_stop_pct.toFixed(1) + '%' : '—',
      note: (broker.risk?.daily_stop_pct ?? 99) > 5 ? 'Recommended: 3.0% for paper trading' : null,
    },
    {
      label: 'Active symbols',
      ok: (broker.symbols?.length ?? 0) > 0,
      val: broker.symbols?.join(', ') || '—',
      note: null,
    },
  ];

  el.innerHTML = items.map(item => {
    const cls  = item.ok ? 'sc-item ok' : 'sc-item warn';
    const icon = item.ok ? '✓' : '⚠';
    const iconCls = item.ok ? 'sc-icon ok' : 'sc-icon warn';
    return `<div class="${cls}">
      <span class="${iconCls}">${icon}</span>
      <div class="sc-body">
        <span class="sc-label">${item.label}</span>
        <span class="sc-val">${item.val}</span>
        ${item.note ? `<span class="sc-note">${item.note}</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

async function refreshStackTab() {
  const broker = await fetchBrokerStatus();
  renderSetupChecklist(broker);
  // Also update the broker status badge in the Tradovate card
  const bsEl = $('stack-broker-status');
  if (bsEl && broker?.tradovate) {
    if (broker.tradovate.credentials_set) {
      bsEl.textContent = `✓ Connected — ${broker.tradovate.mode}`;
      bsEl.style.color = 'var(--green)';
    } else {
      bsEl.textContent = '⚠ Credentials not set — fill in .env';
      bsEl.style.color = 'var(--amber)';
    }
  }
}

// Hook into tab switching — refresh Stack tab data when selected
document.querySelectorAll('.tab-btn').forEach(btn => {
  if (btn.dataset.tab === 'stack') {
    btn.addEventListener('click', refreshStackTab);
  }
});

// Also populate Stack risk config whenever we get a data bundle (WebSocket or REST)
const _origRender = render;
render = function(data) {
  _origRender(data);
  if (data?.settings) renderStackRisk(data.settings);
};

// ── Init ──────────────────────────────────────────────────────────────────────
initChart();
connectWS();
pollRest();
setInterval(pollRest, POLL_MS);
// Fetch broker status once on load (Stack tab may be the first thing someone checks)
refreshStackTab();
