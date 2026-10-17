/* The Quant Hardwood — leaders (#/<L>/leaders): the season's leader boards and a ranked
 * table of any catalogue metric, raw or per 100 possessions, with games and minutes floors.
 *
 * Data: data/<L>/<S>/season.json (leaders: {stat: [[pid, value] x10]}),
 * data/<L>/<S>/players.json (the catalogue). */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const BOARD_LABEL = { pts: 'Points a game', reb: 'Rebounds a game', ast: 'Assists a game', stl: 'Steals a game', blk: 'Blocks a game', '3pm': 'Threes a game', tpm: 'Threes a game', hpm: 'HPM', ts: 'True shooting' };
const BOARD_FMT = { ts: 'pct', hpm: 'pm' };
// Suffixes that mark the same stat on another basis; the base is what is left.
const SUFFIX = /(_?per_?100|_?100|_p100|_?per_?36|_?36|_pg|_per_?game|_g|_tot|_total)$/;
const BASIS = k => (/(per_?100|100|_p100)$/.test(k) ? '100' : /(per_?36|36)$/.test(k) ? '36' : /(_tot|_total)$/.test(k) ? 'tot' : /(_pg|_per_?game|_g)$/.test(k) ? 'g' : 'raw');
const BASIS_LABEL = { raw: 'Raw', g: 'Per game', '36': 'Per 36', '100': 'Per 100', tot: 'Totals' };

let LS = { metric: '', minGp: null, minMin: null, pool: 'all', n: 50 };

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    el.innerHTML = '<div class="card"><div class="card-header">Leaders ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">The top ten in the headline categories (qualified players).</span></div><div id="ld-boards">' + fx.muted('Loading…') + '</div></div>' +
      '<div class="card"><div class="card-header">Any metric <span class="card-sub" id="ld-sub"></span></div>' +
      '<div class="lab-controls hf-controls">' +
      '<label>Metric<select id="ld-metric"></select></label>' +
      '<label>Basis<span id="ld-basis"></span></label>' +
      '<label>Position pool<select id="ld-pool"><option value="all">All</option><option value="G">Guards</option><option value="F">Forwards</option><option value="C">Centres</option></select></label>' +
      '<label>Min games <span id="ld-gp-v"></span><input id="ld-gp" type="range" min="0" max="82" step="1"></label>' +
      '<label>Min minutes <span id="ld-min-v"></span><input id="ld-min" type="range" min="0" max="2500" step="25"></label>' +
      '<label>Show<select id="ld-n"><option value="25">Top 25</option><option value="50">Top 50</option><option value="100">Top 100</option><option value="0">All</option></select></label>' +
      '</div><div id="ld-table"></div><div class="pg-note" id="ld-note"></div></div>';
    return Promise.all([fx.season(L, S)]).then(res => {
      if (!fx.alive(el)) return;
      const cat = res[0][0], season = res[0][2];
      drawBoards(L, S, season, cat);
      if (!fx.ok(cat) || !cat.players) { document.getElementById('ld-table').innerHTML = fx.notBuilt('The ' + fx.seasonLabel(L, S) + ' player catalogue', cat); return; }
      const metrics = (cat.metrics || []).filter(m => Object.keys(cat.players).some(id => fx.isNum((cat.players[id].values || {})[m.key])));
      const meta = fx.metaOf(metrics);
      if (!LS.metric || !meta[LS.metric]) LS.metric = fx.pick(metrics, ['pts_g', 'pts_pg', 'ppg', 'pts', /^pts/, 'hpm']) || (metrics[0] || {}).key;
      if (params.query && params.query.m && meta[params.query.m]) LS.metric = params.query.m;
      const P = cat.players, ids = Object.keys(P);
      const maxGp = Math.max.apply(null, ids.map(id => P[id].gp || 0).concat([1]));
      const maxMin = Math.max.apply(null, ids.map(id => P[id].min || 0).concat([25]));
      const $ = id => document.getElementById(id);
      $('ld-gp').max = String(maxGp); $('ld-min').max = String(Math.ceil(maxMin / 25) * 25);
      if (LS.minGp === null || LS.minGp > maxGp) LS.minGp = Math.min(maxGp, Math.round(maxGp * 0.5));
      if (LS.minMin === null || LS.minMin > maxMin) LS.minMin = fx.isNum(cat.min_floor) ? Math.min(cat.min_floor, maxMin) : 0;
      $('ld-gp').value = LS.minGp; $('ld-gp-v').textContent = LS.minGp; $('ld-min').value = LS.minMin; $('ld-min-v').textContent = LS.minMin;
      $('ld-pool').value = LS.pool; $('ld-n').value = String(LS.n);
      $('ld-metric').innerHTML = fx.groups(metrics).map(g => '<optgroup label="' + fx.esc(g.name) + '">' + g.items.map(m => '<option value="' + fx.esc(m.key) + '">' + fx.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      const draw = () => drawTable(L, S, cat, metrics, meta);
      $('ld-metric').onchange = e => { LS.metric = e.target.value; draw(); };
      $('ld-pool').onchange = e => { LS.pool = e.target.value; draw(); };
      $('ld-n').onchange = e => { LS.n = Number(e.target.value); draw(); };
      $('ld-gp').oninput = e => { LS.minGp = Number(e.target.value); $('ld-gp-v').textContent = LS.minGp; };
      $('ld-gp').onchange = draw;
      $('ld-min').oninput = e => { LS.minMin = Number(e.target.value); $('ld-min-v').textContent = LS.minMin; };
      $('ld-min').onchange = draw;
      draw();
    });
  });
}

function drawBoards(L, S, season, cat) {
  const fx = FX();
  const ld = (fx.ok(season) && season.leaders) || {};
  const P = ((cat || {}).players) || {};
  const keys = Object.keys(ld).filter(k => (ld[k] || []).length);
  const host = document.getElementById('ld-boards');
  if (!keys.length) { host.innerHTML = fx.muted('No leader boards yet: they fill in once games are played.'); return; }
  host.innerHTML = '<div class="hf-boards">' + keys.map(k => {
    const list = ld[k].slice(0, 10);
    const top = list[0] || [];
    return '<div class="hf-board"><div class="hf-board-head">' + fx.esc(BOARD_LABEL[k] || BOARD_LABEL[k.replace(/_.*$/, '')] || k.toUpperCase()) + '</div>' +
      list.map((x, i) => { const pid = Array.isArray(x) ? x[0] : x.id, v = Array.isArray(x) ? x[1] : x.value; const p = P[pid] || {};
        const f = BOARD_FMT[k] || (Math.abs(v) <= 1.5 && /ts|pct|%/.test(k) ? 'pct' : '1');
        return '<div class="hf-board-row' + (i === 0 ? ' top' : '') + '"><span class="r">' + (i + 1) + '</span>' + fx.playerLink(L, pid, p.name, p.team) + '<span class="v">' + fx.fmtV(v, f) + '</span></div>'; }).join('') +
      (top.length ? '' : '') + '</div>';
  }).join('') + '</div>';
}

function drawTable(L, S, cat, metrics, meta) {
  const fx = FX();
  const P = cat.players;
  const m = meta[LS.metric];
  const sel = document.getElementById('ld-metric');
  if (sel) sel.value = LS.metric;
  // Family of the metric on other bases.
  const base = LS.metric.replace(SUFFIX, '');
  const fam = metrics.filter(x => x.key === base || x.key.replace(SUFFIX, '') === base);
  const basisHost = document.getElementById('ld-basis');
  if (fam.length > 1) {
    basisHost.innerHTML = fx.toggle('ld-basis-t', fam.map(x => [x.key, BASIS_LABEL[BASIS(x.key)] || x.label]), LS.metric);
    fx.wireToggle(basisHost, 'ld-basis-t', v => { LS.metric = v; drawTable(L, S, cat, metrics, meta); });
  } else basisHost.innerHTML = '<span class="muted-inline hf-basis-none">' + fx.esc(BASIS_LABEL[BASIS(LS.metric)] || 'Raw') + ' only</span>';
  const ids = Object.keys(P).filter(id => {
    const p = P[id];
    return (p.gp || 0) >= LS.minGp && (p.min || 0) >= LS.minMin && (LS.pool === 'all' || p.pool === LS.pool) && fx.isNum((p.values || {})[LS.metric]);
  });
  ids.sort((a, b) => (m.lower ? 1 : -1) * (P[a].values[LS.metric] - P[b].values[LS.metric]));
  const shown = LS.n ? ids.slice(0, LS.n) : ids;
  const vals = ids.map(id => P[id].values[LS.metric]);
  const mx = Math.max.apply(null, vals.map(v => Math.abs(v)).concat([1e-9]));
  const host = document.getElementById('ld-table');
  host.innerHTML = shown.length ? HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'GP', align: 'right' }, { label: 'Min', align: 'right' }, { label: m.label, align: 'right' }, { label: '', sortable: false }, { label: 'League pct', align: 'center' }, { label: 'Pool pct', align: 'center' }],
    shown.map((id, i) => { const p = P[id], v = p.values[LS.metric];
      return { _href: fx.playerHref(L, id), cells: [i + 1, { v: p.name, html: fx.playerLink(L, id, p.name, p.team) }, { v: fx.teamAbbr(L, p.team), html: fx.teamLink(L, p.team, { abbr: true }) }, p.pos || p.pool || '', p.gp, { v: p.min, html: fx.num(p.min, 0) },
        { v: v, html: '<strong>' + fx.fmt(m, v) + '</strong>' }, { v: v, html: '<span class="hf-lbar"><span style="width:' + (100 * Math.abs(v) / mx).toFixed(1) + '%;background:' + (v < 0 ? fx.C.red : fx.teamColour(L, p.team)) + '"></span></span>' },
        { v: (p.pct || {})[LS.metric], html: fx.pill((p.pct || {})[LS.metric]) }, { v: (p.pct_pool || {})[LS.metric], html: fx.pill((p.pct_pool || {})[LS.metric]) }] }; }), { compact: true, sticky: true })
    : fx.muted('No player passes these filters.');
  HW.sortable(host);
  document.getElementById('ld-sub').innerHTML = ids.length + ' players with ' + LS.minGp + '+ games and ' + LS.minMin + '+ minutes' + (LS.pool !== 'all' ? ' in the ' + LS.pool + ' pool' : '') + (m.lower ? ' · lower is better, so the lowest ranks first' : '');
  document.getElementById('ld-note').innerHTML = '<strong>' + fx.glossLink(m.key, fx.esc(m.label)) + '</strong>' + (m.desc ? ': ' + fx.esc(m.desc).replace(/\.?$/, '.') : '.') + (m.scope === 'pbp' ? ' Play-by-play metric (about 2017 on).' : '') +
    ' Per-100 figures are per 100 team possessions with the player on the floor; per-game and totals are raw. The <a href="' + fx.href(L, 'lab') + '">lab</a> plots any two of these against each other.';
}

HW.route('leaders', render);
})(window.HW);
