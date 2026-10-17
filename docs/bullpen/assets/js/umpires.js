/* The Quant Bullpen — umpires (#/umpires) and one umpire (#/umpire/<id>).
 *
 * Home-plate umpires from the called-strike model (models/umpire.py on models/framing.py):
 * accuracy against the rule-book zone, the accuracy the model expects for his mix of pitches,
 * consistency with his own zone, zone size, the run impact of his missed calls and which side
 * they favoured, the per-game scorecards, and the 2026 automated ball-strike (ABS) challenges.
 *
 * Data: data/<L>/<S>/umpires.json ({"umpires": {id: {...}} | [...], "abs": {...}, "league": {...}}).
 * Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const COLS = [
  ['games', 'Games', ['games', 'g', 'n_games'], 'int', ''],
  ['called', 'Called', ['called', 'n_called', 'calls', 'pitches'], 'int', 'Called pitches'],
  ['accuracy', 'Accuracy', ['accuracy', 'acc'], 'pct', 'Share of calls matching the rule-book zone (|x| ≤ 0.83 ft, sz_bot − 0.12 to sz_top + 0.12 ft)'],
  ['x_accuracy', 'Expected', ['x_accuracy', 'exp_accuracy', 'acc_exp', 'xacc'], 'pct', 'Accuracy an average umpire would have on the same pitches'],
  ['acc_ae', 'Above exp.', ['acc_ae', 'accuracy_ae', 'acc_above_exp', 'aae', 'acc_oe'], 'pctpp', 'Accuracy minus expected accuracy'],
  ['consistency', 'Consistency', ['consistency', 'cons'], 'pct', 'Share of calls agreeing with his own fitted zone'],
  ['zone_size', 'Zone size', ['zone_size', 'strikes_ae', 'zone', 'zone_100'], 'signed', 'Strikes above expected per 100 called pitches (positive = a big zone)'],
  ['run_impact', 'Run impact', ['run_impact', 'runs', 'rv_missed', 'impact'], 'runs', 'Runs moved by missed calls (absolute, per game where the payload says so)'],
  ['favour', 'Home favour', ['favour', 'favor', 'home_favour', 'fav'], 'signed2', 'Runs his misses gave home batters minus away batters, per game'],
  ['abs_over', 'ABS overturned', ['abs_overturned', 'overturned', 'abs_rate', 'overturn_rate'], 'pct', 'Share of ABS challenges against his calls that were overturned (2026)']
];
const LOWER = { run_impact: 1, abs_over: 1 };
function umpsOf(d) {
  if (!d || d.ok === false) return [];
  const U = d.umpires || d.rows || d;
  const flat = (id, u) => Object.assign({}, u.values || {}, u, { id: String(id), pct: u.pct || {} });
  if (Array.isArray(U)) return U.map(u => flat(u.id || u.ump || u.umpire || u.pid, u));
  return Object.keys(U || {}).filter(id => U[id] && typeof U[id] === 'object' && (U[id].name || U[id].values)).map(id => flat(id, U[id]));
}
/* Column definitions from the payload's metrics when it has them (key, label, fmt, lower, desc), else the built-in list. */
function colsOf(d, rows) {
  const k = K();
  const ms = (d && d.metrics) || [];
  if (ms.length) return ms.filter(m => rows.some(r => k.isNum(r[m.key]))).map(m => [m.key, m.label, [m.key], m.key === 'acc_above_x' ? 'pctpp' : m.fmt, m.desc || '', !!m.lower]);
  return COLS.filter(c => rows.some(r => k.isNum(k.val(r, c[2])))).map(c => c.concat([!!LOWER[c[0]]]));
}
function fmtC(c, v) {
  const k = K();
  if (c[3] === 'pctpp') return k.isNum(v) ? k.signed(100 * v, 1) + ' pp' : '—';
  if (c[3] === 'runs') return k.isNum(v) ? k.num(v, 2) : '—';
  return k.fmtV(v, c[3]);
}
function pctRanks(rows, cols) {
  const k = K(), out = {};
  cols.forEach(c => {
    if (rows.some(r => r.pct && k.isNum(r.pct[c[0]]))) { out[c[0]] = (v, r) => (r && r.pct ? r.pct[c[0]] : null); return; }
    const vals = rows.map(r => k.val(r, c[2])).filter(k.isNum).sort((a, b) => a - b);
    out[c[0]] = v => {
      if (!k.isNum(v) || vals.length < 5) return null;
      let lo = 0; while (lo < vals.length && vals[lo] < v) lo++;
      let hi = lo; while (hi < vals.length && vals[hi] === v) hi++;
      const p = 100 * ((lo + hi) / 2) / vals.length;
      return c[5] ? 100 - p : p;
    };
  });
  return out;
}

function renderList(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">Umpires <span class="card-sub" id="um-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls"><label>Search<input id="um-q" class="gq-search" type="search" placeholder="umpire…"></label><label>Min games <span id="um-min-v"></span><input type="range" id="um-min" min="0" max="40" step="1" value="10"></label></div>' +
    '<div id="um-table"></div><div class="pg-note gq-note" id="um-note"></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Accuracy above expected against consistency <span class="card-sub">Right is more accurate than his pitches made likely; up is more consistent with his own zone. Size is games.</span></div><div id="um-chart" style="height:400px"></div></div>' +
    '<div class="card"><div class="card-header">ABS challenges <span class="card-sub">2026: who challenged, how often calls were overturned, and what an overturn was worth.</span></div><div id="um-abs"></div></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return k.loadY(L, S, 'umpires.json').then(d => ({ S: S, d: d }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, $ = id => document.getElementById(id);
    const rows = umpsOf(d);
    if (!rows.length) { $('um-table').innerHTML = k.notBuilt('The ' + S + ' umpire tables', d); $('um-sub').textContent = ''; absPanel(null); $('um-chart').innerHTML = ''; return; }
    const cols = colsOf(d, rows);
    const pr = pctRanks(rows, cols);
    const g = r => k.val(r, ['games', 'g', 'n_games']) || 0;
    const maxG = Math.max.apply(null, rows.map(g).concat([10]));
    $('um-min').max = String(maxG);
    let min = Math.min(10, Math.round(maxG / 3)), q = '';
    $('um-min').value = min; $('um-min-v').textContent = min;
    const draw = () => {
      const list = rows.filter(r => g(r) >= min && (!q || k.fold(r.name || k.umpName(r.id)).indexOf(q) >= 0));
      const sk = r => { const v = k.val(r, ['acc_above_x', 'acc_ae']); return k.isNum(v) ? v : -1; };
      list.sort((a, b) => sk(b) - sk(a));
      $('um-table').innerHTML = k.table([{ label: '#', sortable: false }, { label: 'Umpire' }].concat(cols.map(c => ({ label: c[1] + (c[5] ? ' ↓' : ''), align: 'right', title: c[4] }))),
        list.map((r, i) => ({ _href: k.umpHref(r.id), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name || k.umpName(r.id), html: '<a href="' + k.umpHref(r.id) + '">' + k.esc(r.name || k.umpName(r.id)) + '</a>' }]
          .concat(cols.map(c => { const v = k.val(r, c[2]); return { v: v, html: fmtC(c, v) + (/^(games|called)$/.test(c[0]) || c[3] === 'int' ? '' : ' ' + k.pill(pr[c[0]](v, r))), align: 'right' }; })) })), { compact: true, sticky: true });
      k.sortable($('um-table'));
      $('um-sub').textContent = list.length + ' of ' + rows.length + ' home-plate umpires, ' + S;
      scatter(list);
    };
    $('um-min').oninput = e => { min = Number(e.target.value); $('um-min-v').textContent = min; };
    $('um-min').onchange = draw;
    let t = null;
    $('um-q').oninput = e => { q = k.fold(e.target.value.trim()); clearTimeout(t); t = setTimeout(draw, 150); };
    draw();
    const lg = d.league || {};
    $('um-note').innerHTML = 'Pills are percentiles among umpires with ' + k.int((d && d.min_called) || 500) + '+ called pitches (100 = best: more accurate, more consistent, fewer missed calls and less run impact; zone size and zone effect are ranked high-to-low, not better-to-worse). ' +
      (k.isNum(lg.accuracy) ? 'League accuracy ' + k.pct(lg.accuracy, 1) + '. ' : '') + 'The rule-book zone is |plate_x| ≤ 0.83 ft (half the 17-inch plate plus a ball radius) between sz_bot − 0.12 and sz_top + 0.12 ft. Expected accuracy comes from the called-strike model without his own effect, so an umpire who sees more borderline pitches is not penalised for it. A missed call costs the run value of the count change it causes (see the <a href="#/methodology/umpires">methodology</a>).';
    absPanel(d.abs || d.abs_challenges);
  });
}

function scatter(list) {
  const k = K();
  const node = document.getElementById('um-chart');
  if (!node) return;
  const pts = list.map(r => ({ r: r, x: k.val(r, ['acc_above_x', 'acc_ae', 'accuracy_ae']), y: k.val(r, ['consistency', 'cons']), g: k.val(r, ['games', 'g']) || 1 })).filter(p => k.isNum(p.x) && k.isNum(p.y));
  if (pts.length < 3) { node.innerHTML = k.muted('Not enough umpires with both numbers.'); node.style.height = 'auto'; return; }
  const maxG = Math.max.apply(null, pts.map(p => p.g));
  k.plot(node, [{ type: 'scatter', mode: 'markers', x: pts.map(p => p.x * 100), y: pts.map(p => p.y * 100), text: pts.map(p => p.r.name || k.umpName(p.r.id)), customdata: pts.map(p => p.r.id),
    hovertemplate: '%{text}<br>above expected %{x:+.2f} pp · consistency %{y:.1f}%<extra></extra>',
    marker: { size: pts.map(p => 6 + 12 * Math.sqrt(p.g / maxG)), color: pts.map(p => p.x), colorscale: k.DIVERGE, cmid: 0, line: { color: '#0d1117', width: 0.6 } } }],
  k.layout({ margin: { l: 50, r: 10, t: 10, b: 44 }, xaxis: { title: 'Accuracy above expected (pp)', zeroline: true }, yaxis: { title: 'Consistency (%)' } }));
  if (node.on) node.on('plotly_click', ev => { const id = ev.points && ev.points[0] && ev.points[0].customdata; if (id) location.hash = k.umpHref(id); });
}

function absPanel(a) {
  const k = K();
  const host = document.getElementById('um-abs');
  if (!host) return;
  if (!a || a.ok === false || !Object.keys(a).length) { host.innerHTML = k.muted('No ABS challenge data for this season (the challenge system is in use from 2026)' + (a && a.reason ? ': ' + k.esc(a.reason) : '') + '.'); return; }
  if (a.challengers || a.by_batting_team || a.teams) {
    const tiles = [];
    if (k.isNum(a.n) || k.isNum(a.used)) tiles.push(k.tile('Challenges', k.int(k.isNum(a.n) ? a.n : a.used), a.source === 'store' ? 'from the game records' : 'plate-appearance-ending calls'));
    if (k.isNum(a.overturn_rate)) tiles.push(k.tile('Overturned', k.pct(a.overturn_rate, 1), k.isNum(a.won) ? k.int(a.won) + ' calls' : ''));
    if (k.isNum(a.mean_value_overturned)) tiles.push(k.tile('Value of an overturn', k.signed(a.mean_value_overturned, 3) + ' <span class="kpi-dim">runs</span>', 'mean run-expectancy swing'));
    let h2 = tiles.length ? '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>' : '';
    const ch = k.colRows(a.challengers);
    if (ch.length) {
      const best = ch.filter(r => (r.n || 0) >= 3);
      h2 += '<div class="gq-sub-head">Challengers (3+ challenges)</div>' + k.table([{ label: 'Challenger' }, { label: 'Challenges', align: 'right' }, { label: 'Won', align: 'right' }, { label: 'Rate', align: 'right' }, { label: 'Runs', align: 'right' }],
        best.slice(0, 15).map(r => [{ v: r.challenger, html: k.esc(r.challenger || r.name || '—') }, { v: r.n, html: k.int(r.n) }, { v: r.won, html: k.int(r.won) }, { v: r.rate, html: k.pct(r.rate, 0) }, { v: r.value, html: k.isNum(r.value) ? k.signed(r.value, 2) : '—' }]), { compact: true });
    }
    const tm = k.colRows(a.by_batting_team || a.teams);
    if (tm.length) h2 += '<div class="gq-sub-head">By team</div>' + k.table([{ label: 'Team' }, { label: 'Challenges', align: 'right' }, { label: 'Overturned', align: 'right' }],
      tm.map(r => { const t = r.bat_team || r.team; const n = k.isNum(r.size) ? r.size : r.used; const rate = k.isNum(r.mean) ? r.mean : r.rate;
        return [{ v: t, html: k.TEAMS[String(t)] ? k.teamChip((BP.state || {}).level || 'mlb', t) : k.esc(t) }, { v: n, html: k.int(n) }, { v: rate, html: k.pct(rate, 0) }]; }), { compact: true });
    host.innerHTML = h2 || k.muted('No ABS tables yet.');
    k.sortable(host);
    return;
  }
  const tiles = [];
  [['n', 'Challenges', 'int', ['n', 'challenges', 'total']], ['overturn_rate', 'Overturned', 'pct', ['overturn_rate', 'overturned_pct', 'rate']], ['value', 'Value of an overturn', 'signed2', ['value', 'value_per', 'rv_per_overturn', 'run_value']],
    ['batter_rate', 'Batters\' success', 'pct', ['batter_rate', 'batter_success']], ['catcher_rate', 'Catchers\' success', 'pct', ['catcher_rate', 'catcher_success']], ['pitcher_rate', 'Pitchers\' success', 'pct', ['pitcher_rate', 'pitcher_success']]].forEach(x => {
    const v = k.val(a, x[3]);
    if (k.isNum(v)) tiles.push(k.tile(x[1], k.fmtV(v, x[2]) + (x[0] === 'value' ? ' <span class="kpi-dim">runs</span>' : ''), ''));
  });
  let h = tiles.length ? '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>' : '';
  const L = (BP.state && BP.state.level) || 'mlb';
  const lst = (x, title) => {
    const rows = (Array.isArray(x) ? x : Object.keys(x || {}).map(id => Object.assign({ pid: id }, x[id]))).map(r => (Array.isArray(r) ? { pid: String(r[0]), n: r[1], won: r[2], value: r[3] } : r));
    if (!rows.length) return '';
    return '<div class="gq-sub-head">' + k.esc(title) + '</div>' + k.table([{ label: 'Player' }, { label: 'Challenges', align: 'right' }, { label: 'Won', align: 'right' }, { label: 'Rate', align: 'right' }, { label: 'Runs', align: 'right' }],
      rows.slice(0, 10).map(r => { const pid = String(r.pid || r.id), n = k.val(r, ['n', 'challenges']), w = k.val(r, ['won', 'overturned', 'success']); const rate = k.isNum(n) && n ? w / n : k.val(r, ['rate']);
        return [{ v: k.name(pid), html: k.playerLink(L, pid, r.name) }, { v: n, html: k.int(n) }, { v: w, html: k.int(w) }, { v: rate, html: k.fmtV(rate, 'pct') }, { v: k.val(r, ['value', 'runs', 'rv']), html: k.fmtV(k.val(r, ['value', 'runs', 'rv']), 'signed2') }]; }), { compact: true });
  };
  h += lst(a.best || a.best_challengers, 'Best challengers (3+ challenges)') + lst(a.worst || a.worst_challengers, 'Worst challengers');
  const teams = a.teams || a.by_team;
  if (teams && typeof teams === 'object') h += '<div class="gq-sub-head">By team</div>' + K().rowsTable(teams, null, { first: 'Team', keyLabel: x => k.teamAbbr(x) });
  host.innerHTML = h || k.muted('No ABS tables yet.');
}

// ── one umpire ─────────────────────────────────────────────────────────────

function renderOne(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  const id = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return k.loadY(L, S, 'umpires.json').then(d => ({ S: S, d: d }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, rows = umpsOf(o.d);
    const u = rows.find(r => r.id === id);
    if (!u) { el.innerHTML = k.card('Umpire', '', k.notBuilt('The page for ' + k.umpName(id), o.d) + '<div class="pg-note gq-note"><a href="#/umpires">All umpires →</a></div>'); return; }
    const cols = colsOf(o.d, rows);
    const pr = pctRanks(rows, cols);
    const name = u.name || k.umpName(id);
    let h = k.head(k.esc(name), '<span class="chip">Home plate · ' + S + '</span>' + (k.isNum(k.val(u, ['games', 'g'])) ? ' <span>' + k.int(k.val(u, ['games', 'g'])) + ' games behind the plate</span>' : ''), '<a href="#/umpires">All umpires →</a>', 'UMP');
    h += k.tiles(cols.filter(c => c[0] !== 'called' && c[0] !== 'games').slice(0, 6).map(c => { const v = k.val(u, c[2]), p = pr[c[0]](v, u); return k.tile(c[1], fmtC(c, v), (k.isNum(p) ? k.ordinal(p) + ' percentile' : '')); }));
    h += '<div class="card"><div class="card-header">Game by game <span class="card-sub">Accuracy against the accuracy expected for his pitches, and the run impact of the missed calls in each game.</span></div><div id="u-trend" style="height:300px"></div></div>';
    h += '<div class="card"><div class="card-header">Scorecards <span class="card-sub">Each game: calls, misses, the runs they moved and the team they favoured. Click a row for the game centre with the full scorecard.</span></div><div id="u-cards"></div></div>';
    el.innerHTML = h;
    const gcols = (o.d && o.d.games_cols) || ['gpk', 'date', 'home', 'away', 'called', 'missed', 'accuracy', 'x_accuracy', 'home_favour', 'favoured', 'impact'];
    const cards = (u.games_list || u.scorecards || u.cards || []).map(r => { if (!Array.isArray(r)) return r; const x = {}; gcols.forEach((c, i) => { x[c] = r[i]; }); return x; });
    const imp = r => k.val(r, ['impact', 'run_impact', 'runs', 'rv']);
    if (cards.length) {
      const srt = cards.slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
      k.plot('u-trend', [{ type: 'scatter', mode: 'lines+markers', name: 'Accuracy', x: srt.map(r => r.date), y: srt.map(r => k.val(r, ['accuracy', 'acc'])), line: { color: '#58a6ff' }, hovertemplate: '%{x}: %{y:.1%}<extra>accuracy</extra>' },
        { type: 'scatter', mode: 'lines', name: 'Expected', x: srt.map(r => r.date), y: srt.map(r => k.val(r, ['x_accuracy'])), line: { color: '#8b949e', dash: 'dot', width: 1.2 }, hovertemplate: '%{x}: %{y:.1%}<extra>expected</extra>' },
        { type: 'bar', name: 'Run impact', x: srt.map(r => r.date), y: srt.map(imp), yaxis: 'y2', marker: { color: 'rgba(248,81,73,0.45)' }, hovertemplate: '%{x}: %{y:.2f} runs<extra></extra>' }],
      k.layout(Object.assign({ margin: { l: 48, r: 48, t: 28, b: 32 }, yaxis: { title: 'Accuracy', tickformat: '.0%' }, yaxis2: { title: 'Runs', overlaying: 'y', side: 'right', showgrid: false } }, k.legendTop())));
      document.getElementById('u-cards').innerHTML = k.table([{ label: 'Date' }, { label: 'Game' }, { label: 'Called', align: 'right' }, { label: 'Accuracy', align: 'right' }, { label: 'Expected', align: 'right' }, { label: 'Missed', align: 'right' }, { label: 'Run impact', align: 'right' }, { label: 'Favoured', align: 'right' }],
        cards.slice().sort((a, b) => String(b.date).localeCompare(String(a.date))).map(r => {
          const fav = r.favoured || r.favored || r.fav;
          const favR = k.val(r, ['home_favour', 'favour', 'favor', 'fav_runs']);
          return { _href: r.gpk ? k.href(r.level || L, 'game/' + r.gpk, S) : '', cells: [{ v: r.date, html: k.esc(k.short(r.date)) }, { v: (r.away || '') + (r.home || ''), html: r.away && r.home ? k.esc(k.teamAbbr(r.away)) + ' @ ' + k.esc(k.teamAbbr(r.home)) : (r.gpk ? '#' + k.esc(r.gpk) : '—') },
            { v: k.val(r, ['called', 'n']), html: k.int(k.val(r, ['called', 'n'])) }, { v: k.val(r, ['accuracy', 'acc']), html: k.fmtV(k.val(r, ['accuracy', 'acc']), 'pct') }, { v: r.x_accuracy, html: k.fmtV(r.x_accuracy, 'pct') },
            { v: k.val(r, ['missed', 'misses', 'n_missed']), html: k.int(k.val(r, ['missed', 'misses', 'n_missed'])) }, { v: imp(r), html: k.num(imp(r), 2) },
            { v: favR, html: fav ? k.esc(k.teamAbbr(fav)) + (k.isNum(favR) ? ' ' + k.signed(Math.abs(favR), 2) : '') : (k.isNum(favR) ? (Math.abs(favR) <= 0.005 ? 'neither' : (favR > 0 ? 'home ' : 'away ') + k.num(Math.abs(favR), 2)) : '—') }] };
        }), { compact: true, sticky: true });
      k.sortable(document.getElementById('u-cards'));
    } else {
      document.getElementById('u-trend').innerHTML = k.muted('No per-game scorecards yet.');
      document.getElementById('u-cards').innerHTML = k.muted('No per-game scorecards yet.');
    }
    if (typeof BP.setMeta === 'function') { try { BP.setMeta(k.esc(name)); } catch (e) { /* optional */ } }
  });
}

if (typeof BP.route === 'function') {
  [['umpires', renderList], ['#/umpires', renderList], ['umpire', renderOne], ['#/umpire/<id>', renderOne]].forEach(r => { try { BP.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.BP || (window.BP = {}));
