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
  ['consistency', 'Consistency', ['consistency', 'cons'], 'pct', 'Share of calls agreeing with the umpire\'s own fitted zone'],
  ['zone_size', 'Zone size', ['zone_size', 'strikes_ae', 'zone', 'zone_100'], 'signed', 'Strikes above expected per 100 called pitches (positive = a big zone)'],
  ['run_impact', 'Run impact', ['run_impact', 'runs', 'rv_missed', 'impact'], 'runs', 'Runs moved by missed calls (absolute, per game where the payload says so)'],
  ['favour', 'Home favour', ['favour', 'favor', 'home_favour', 'fav'], 'signed2', 'Runs the missed calls gave home batters minus away batters, per game'],
  ['abs_over', 'ABS overturned', ['abs_overturned', 'overturned', 'abs_rate', 'overturn_rate'], 'pct', 'Share of ABS challenges against the umpire\'s calls that were overturned (2026)']
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
  const U = BP.ui;
  const L = k.L(params, state);
  el.innerHTML = QK.sectionHead({ kicker: 'Umpires · ' + k.LN(L), title: 'Behind the plate', sub: 'Every home-plate umpire against the rule-book zone, against what the pitches seen made likely, and the runs the missed calls moved.' }) +
    '<div id="um-kpis"></div>' +
    '<section class="qk-card"><div class="qk-card-body"><div class="bp-ctl"><label>Search<input id="um-q" class="gq-search" type="search" placeholder="umpire…"></label><label>Min games <b id="um-min-v"></b><input type="range" id="um-min" min="0" max="40" step="1" value="10"></label></div></div></section>' +
    '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-7">' + U.card2('Accuracy and consistency', 'Right: more accurate than the pitches seen made likely; up: more consistent with the umpire\'s own zone; size is games, colour the accuracy percentile', U.chart('um-chart', 420, 'Accuracy above expected against consistency')) + '</div>' +
    '<div class="qk-span-5">' + U.card2('ABS challenges', '2026: who challenged, how often calls were overturned, and what an overturn was worth', '<div id="um-abs"></div>') + '</div></div>' +
    '<section class="qk-section"><div id="um-card"></div></section>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return k.loadY(L, S, 'umpires.json').then(d => ({ S: S, d: d }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, $ = id => document.getElementById(id);
    const rows = umpsOf(d);
    if (!rows.length) { $('um-card').innerHTML = U.card2('Umpires', '', QK.empty('Not built yet', 'The ' + S + ' umpire tables are not available.')); absPanel(null); $('um-chart').innerHTML = ''; return; }
    const cols = colsOf(d, rows);
    const pr = pctRanks(rows, cols);
    const g = r => k.val(r, ['games', 'g', 'n_games']) || 0;
    const maxG = Math.max.apply(null, rows.map(g).concat([10]));
    $('um-min').max = String(maxG);
    let min = Math.min(10, Math.round(maxG / 3)), q = '';
    $('um-min').value = min; $('um-min-v').textContent = min;
    const lg = d.league || {};
    const ae = r => k.val(r, ['acc_above_x', 'acc_ae']);
    const ri = r => k.val(r, ['run_impact', 'runs', 'rv_missed', 'impact']);
    const quali = rows.filter(r => g(r) >= min);
    const best = quali.filter(r => k.isNum(ae(r))).sort((a, b) => ae(b) - ae(a))[0];
    const calm = quali.filter(r => k.isNum(ri(r))).sort((a, b) => ri(a) - ri(b))[0];
    const abs = d.abs || d.abs_challenges || {};
    $('um-kpis').innerHTML = '<div class="bp-kpis">' + QK.stats([
      k.isNum(lg.accuracy) ? { label: 'League accuracy', value: k.pct(lg.accuracy, 1), sub: 'calls matching the rule-book zone' } : null,
      best ? { label: 'Most accurate v expected', value: k.surname(best.name || k.umpName(best.id)) + ' ' + k.signed(100 * ae(best), 1), unit: 'pts', signal: true, sub: 'accuracy above expected · ' + g(best) + ' games', href: k.umpHref(best.id) } : null,
      calm ? { label: 'Fewest runs moved', value: k.surname(calm.name || k.umpName(calm.id)) + ' ' + k.num(ri(calm), 2), sub: 'run impact of missed calls', href: k.umpHref(calm.id) } : null,
      k.isNum(abs.overturn_rate) ? { label: 'ABS overturns', value: k.pct(abs.overturn_rate, 1), sub: k.isNum(abs.n) ? k.int(abs.n) + ' challenges' : 'of challenged calls' } : null
    ]) + '</div>';
    const draw = () => {
      const list = rows.filter(r => g(r) >= min && (!q || k.fold(r.name || k.umpName(r.id)).indexOf(q) >= 0));
      const sk = r => { const v = ae(r); return k.isNum(v) ? v : -1; };
      list.sort((a, b) => sk(b) - sk(a));
      $('um-card').innerHTML = U.card2('Every umpire', list.length + ' of ' + rows.length + ' home-plate umpires, ' + S + ' · cells coloured by percentile among umpires (100 = best); expected accuracy and zone size describe style, so they are grey', '<div id="um-table"></div>', { flush: true,
        foot: '<span class="bp-fn">Rule-book zone: |plate_x| ≤ 0.83 ft between sz_bot − 0.12 and sz_top + 0.12 ft. Expected accuracy comes from the called-strike model without the umpire\'s own effect.</span>' });
      if (!list.length) { $('um-table').innerHTML = QK.empty('Nobody here', 'Lower the minimum games.'); scatter([], pr, cols); return; }
      QK.leaderboard($('um-table'), { dense: true, rank: true, maxHeight: 620, rowHref: r => k.umpHref(r.id), columns: [{ key: 'name', label: 'Umpire', type: 'entity', href: r => k.umpHref(r.id) }]
        .concat(cols.map(c => (/^(games|called)$/.test(c[0]) || c[3] === 'int' ? { key: 'c_' + c[0], label: c[1], num: true, fmt: v => fmtC(c, v), tip: c[4] }
          : { key: 'c_' + c[0], label: c[1] + (c[5] ? ' ↓' : ''), type: 'pctl', pctl: 'p_' + c[0], style: /x_accuracy|exp_accuracy|zone_size|zone_effect|strikes_ae|zone_100/.test(c[0]), fmt: v => fmtC(c, v), tip: c[4] }))),
        rows: list.map(r => { const o2 = { id: r.id, name: r.name || k.umpName(r.id) }; cols.forEach(c => { const v = k.val(r, c[2]); o2['c_' + c[0]] = v; o2['p_' + c[0]] = pr[c[0]](v, r); }); return o2; }) });
      scatter(list, pr, cols);
    };
    $('um-min').oninput = e => { min = Number(e.target.value); $('um-min-v').textContent = min; };
    $('um-min').onchange = draw;
    let t = null;
    $('um-q').oninput = e => { q = k.fold(e.target.value.trim()); clearTimeout(t); t = setTimeout(draw, 150); };
    draw();
    absPanel(d.abs || d.abs_challenges, L);
    BP.setMeta(k.isNum(lg.accuracy) ? 'League accuracy ' + k.pct(lg.accuracy, 1) : '');
  });
}

function scatter(list, pr, cols) {
  const k = K();
  const node = document.getElementById('um-chart');
  if (!node) return;
  const c0 = (cols || []).find(c => /acc_above_x|acc_ae/.test(c[0]));
  const pts = list.map(r => ({ r: r, x: k.val(r, ['acc_above_x', 'acc_ae', 'accuracy_ae']), y: k.val(r, ['consistency', 'cons']), g: k.val(r, ['games', 'g']) || 1 })).filter(p => k.isNum(p.x) && k.isNum(p.y));
  if (pts.length < 3) { node.innerHTML = QK.empty('Not enough umpires', 'Too few umpires have both numbers.'); return; }
  const maxG = Math.max.apply(null, pts.map(p => p.g));
  QKC.scatter('#um-chart', { points: pts.map(p => ({ x: 100 * p.x, y: 100 * p.y, name: (p.r.name || k.umpName(p.r.id)) + ' · ' + p.g + ' games', label: k.surname(p.r.name || k.umpName(p.r.id)), color: QK.pctHex(c0 && pr[c0[0]] ? pr[c0[0]](p.x, p.r) : 50), size: 6 + 12 * Math.sqrt(p.g / maxG), href: k.umpHref(p.r.id) })),
    xName: 'Accuracy above expected (points)', yName: 'Consistency (%)', xFmt: v => k.signed(v, 1), yFmt: v => k.num(v, Math.abs(v - Math.round(v)) > 0.01 ? 1 : 0), refX: 0, labelTop: 6, pad: '10%', quadrants: ['Consistent, misses more', 'Accurate and consistent', '', 'Accurate, own zone moves'], label: 'Umpire accuracy and consistency' });
}

function absPanel(a, Lv) {
  const k = K();
  const host = document.getElementById('um-abs');
  if (!host) return;
  if (!a || a.ok === false || !Object.keys(a).length) { host.innerHTML = k.muted('No ABS challenge data for this season (the challenge system is in use from 2026)' + (a && a.reason ? ': ' + k.esc(a.reason) : '') + '.'); return; }
  if (a.challengers || a.by_batting_team || a.teams) {
    const L2 = Lv || (BP.state || {}).level || 'mlb';
    const num = (r, keys) => { const v = k.val(r, keys); return k.isNum(v) ? v : null; };
    const runs = r => num(r, ['runs', 'value']);
    const tm = k.colRows(a.by_batting_team || a.teams);
    const tiles = [];
    if (k.isNum(a.n) || k.isNum(a.used)) tiles.push(k.tile('Challenges', k.int(k.isNum(a.n) ? a.n : a.used), a.source === 'store' ? 'from the game records' : 'plate-appearance-ending calls'));
    const wonAll = k.isNum(a.won) ? a.won : (tm.length && tm.every(r => k.isNum(r.won)) ? tm.reduce((s, r) => s + r.won, 0) : null);
    if (k.isNum(a.overturn_rate)) tiles.push(k.tile('Overturned', k.pct(a.overturn_rate, 1), k.isNum(wonAll) ? k.int(wonAll) + ' calls' : ''));
    const vo = k.isNum(a.value_per_overturn) ? a.value_per_overturn : a.mean_value_overturned;
    if (k.isNum(vo)) tiles.push(k.tile('Value of an overturn', k.signed(vo, 2) + ' <span class="kpi-dim">runs</span>', 'run expectancy gained by the challenging side'));
    let h2 = tiles.length ? '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>' : '';
    const ROLE = { batter: 'Batters', catcher: 'Catchers', pitcher: 'Pitchers' };
    const br = a.by_role && typeof a.by_role === 'object' ? Object.keys(a.by_role).filter(r => ROLE[r]) : [];
    if (br.length) h2 += '<div class="gq-sub-head">Who challenges</div>' + k.table([{ label: 'Challenger' }, { label: 'Challenges', align: 'right' }, { label: 'Overturned', align: 'right' }, { label: 'Runs', align: 'right', title: 'Run expectancy gained from overturned calls' }],
      br.map(r => { const x = a.by_role[r] || {}; return [{ v: ROLE[r] }, { v: x.n, html: k.int(x.n) }, { v: x.overturn_rate, html: k.pct(x.overturn_rate, 0) }, { v: x.runs, html: k.isNum(x.runs) ? k.num(x.runs, 1) : '—' }]; }), { compact: true });
    const ch = k.colRows(a.challengers);
    if (ch.length) {
      const best = ch.filter(r => (r.n || 0) >= 3);
      h2 += '<div class="gq-sub-head">Challengers (3+ challenges)</div>' + k.table([{ label: 'Player' }, { label: 'Challenges', align: 'right' }, { label: 'Won', align: 'right', cls: 'hide-sm' }, { label: 'Rate', align: 'right' }, { label: 'Runs', align: 'right', title: 'Run expectancy gained from overturned calls' }],
        best.slice(0, 15).map(r => { const pid = r.challenger === null || r.challenger === undefined ? '' : String(r.challenger); const nm = r.name || (pid ? k.name(pid) : '');
          return [{ v: nm, html: (pid && /^\d+$/.test(pid) ? k.playerLink(L2, pid, nm, null, r.role === 'pitcher' ? 'pitcher' : null) : k.esc(nm || pid || '—')) + (r.role ? '<span class="pl-pos hide-sm">' + k.esc(r.role) + '</span>' : '') },
            { v: r.n, html: k.int(r.n) }, { v: r.won, html: k.int(r.won), cls: 'hide-sm' }, { v: r.rate, html: k.pct(r.rate, 0) }, { v: runs(r), html: k.isNum(runs(r)) ? k.signed(runs(r), 2) : '—' }]; }), { compact: true });
    }
    const um = k.colRows(a.umpires).filter(r => (r.n || 0) >= 10).sort((x, y) => (y.rate || 0) - (x.rate || 0));
    if (um.length) h2 += '<div class="gq-sub-head">Umpires most overturned (10+ challenges)</div>' + k.table([{ label: 'Umpire' }, { label: 'Challenges', align: 'right' }, { label: 'Overturned', align: 'right' }, { label: 'Rate', align: 'right' }],
      um.slice(0, 8).map(r => { const id = String(r.ump); const nm = r.name || k.umpName(id);
        return [{ v: nm, html: '<a class="ump-link" href="' + k.umpHref(id) + '">' + k.esc(nm) + '</a>' }, { v: r.n, html: k.int(r.n) }, { v: r.overturned, html: k.int(r.overturned) }, { v: r.rate, html: k.pct(r.rate, 0) }]; }), { compact: true });
    if (tm.length) h2 += '<div class="gq-sub-head">By team</div>' + k.table([{ label: 'Team' }, { label: 'Challenges', align: 'right' }, { label: 'Overturned', align: 'right' }, { label: 'Runs', align: 'right', title: 'Run expectancy gained from overturned calls' }],
      tm.map(r => { const t = r.bat_team || r.team; const tid = r.tid || (k.TEAMS[String(t)] ? t : null);
        const n = k.isNum(r.n) ? r.n : (k.isNum(r.size) ? r.size : r.used); const rate = k.isNum(r.rate) ? r.rate : r.mean;
        return [{ v: t, html: tid ? k.teamChip(L2, tid) : k.esc(t) }, { v: n, html: k.int(n) }, { v: rate, html: k.pct(rate, 0) }, { v: runs(r), html: k.isNum(runs(r)) ? k.num(runs(r), 1) : '—' }]; }), { compact: true });
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
  const L = Lv || (BP.state && BP.state.level) || 'mlb';
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
  const U = BP.ui;
  let L = k.L(params, state);
  const id = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = QK.skeleton('card', 2);
  const has = d => umpsOf(d).some(r => r.id === id);
  return k.ready().then(() => {
    const S = k.S(params, state);
    // the umpire route is global: an umpire of the other level (an MLB link while Triple-A is selected) loads that level
    return k.loadY(L, S, 'umpires.json').then(d => {
      if (has(d) || (L !== 'mlb' && L !== 'aaa')) return { S: S, d: d, L: L };
      const L2 = L === 'aaa' ? 'mlb' : 'aaa';
      return k.loadY(L2, S, 'umpires.json').then(d2 => (has(d2) ? { S: S, d: d2, L: L2 } : { S: S, d: d, L: L }), () => ({ S: S, d: d, L: L }));
    });
  }).then(o => {
    L = o.L;
    if (!k.alive(el)) return;
    const S = o.S, rows = umpsOf(o.d);
    const u = rows.find(r => r.id === id);
    if (!u) { el.innerHTML = U.card2('Umpire', '', QK.empty('Not found', 'No ' + S + ' scorecards for ' + k.umpName(id) + '.'), { foot: '<span></span><a href="#/umpires">All umpires →</a>' }); return; }
    const cols = colsOf(o.d, rows);
    const pr = pctRanks(rows, cols);
    const name = u.name || k.umpName(id);
    document.title = name + ' · ' + BP.SITE;
    const v = c => k.val(u, c[2]);
    const games = k.val(u, ['games', 'g']);
    const metricCols = cols.filter(c => !/^(games|called)$/.test(c[0]) && c[3] !== 'int');
    /* style, not quality: the accuracy his pitches made likely, and the size and lean of his zone get no percentile */
    const STYLE = /x_accuracy|exp_accuracy|zone_size|zone_effect|strikes_ae|zone_100/;
    const pq = c => (STYLE.test(c[0]) ? null : pr[c[0]](v(c), u));
    const absU = k.colRows(((o.d || {}).abs || {}).umpires).filter(r => String(r.ump) === id)[0];
    const hero = QK.playerHeader({ name: name, pos: 'Home-plate umpire', kicker: k.LN(L) + ' ' + S,
      meta: [k.isNum(games) ? ['Games behind the plate', k.int(games)] : null, k.isNum(k.val(u, ['called', 'n_called'])) ? ['Called pitches', k.int(k.val(u, ['called', 'n_called']))] : null,
        absU && k.isNum(absU.n) ? ['ABS challenges', k.int(absU.overturned) + ' of ' + k.int(absU.n) + ' overturned'] : null],
      stats: metricCols.slice(0, 3).map(c => ({ label: c[1], value: fmtC(c, v(c)) })) });
    const tiles = metricCols.slice(0, 5).map((c, i) => ({ label: c[1], value: fmtC(c, v(c)), pctl: pq(c), signal: i === 0, tip: c[4] }));
    const pcard = QK.pctCard({ title: 'Against the other umpires', peer: 'MLB home-plate umpires', sample: (k.isNum(games) ? games + ' games · ' : '') + '100 = best',
      groups: [{ label: 'Calling the zone', rows: metricCols.filter(c => !STYLE.test(c[0])).map(c => ({ label: c[1], pctl: pq(c), value: fmtC(c, v(c)), tip: c[4] })) },
        { label: 'Style (not better or worse)', rows: metricCols.filter(c => STYLE.test(c[0])).map(c => ({ label: c[1], pctl: pr[c[0]](v(c), u), value: fmtC(c, v(c)), tip: c[4], style: true })) }],
      note: 'Grey rows describe the pitches seen and the zone, not the quality of the calls.' });
    el.innerHTML = '<div class="qk-kicker" style="margin-bottom:10px"><a href="#/umpires">← Umpires</a></div>' + hero +
      '<div class="bp-kpis" style="margin-top:var(--sp-5)">' + QK.stats(tiles) + '</div>' +
      '<div class="qk-grid"><div class="qk-span-5">' + pcard + '</div><div class="qk-span-7"><div class="bp-stack">' +
      U.card2('Game by game', 'Accuracy against the accuracy expected for the pitches seen', U.chart('u-trend', 260, 'Accuracy by game')) +
      U.card2('Runs moved', 'The run impact of the missed calls in each game', U.chart('u-imp', 220, 'Run impact by game')) + '</div></div></div>' +
      '<section class="qk-section">' + U.card2('Scorecards', 'Each game: calls, misses, the runs they moved and the side they favoured; a row opens the game centre with the full scorecard', '<div id="u-cards"></div>', { flush: true }) + '</section>';
    const gcols = (o.d && o.d.games_cols) || ['gpk', 'date', 'home', 'away', 'called', 'missed', 'accuracy', 'x_accuracy', 'home_favour', 'favoured', 'impact'];
    const cards = (u.games_list || u.scorecards || u.cards || []).map(r => { if (!Array.isArray(r)) return r; const x = {}; gcols.forEach((c, i) => { x[c] = r[i]; }); return x; });
    const imp = r => k.val(r, ['impact', 'run_impact', 'runs', 'rv']);
    if (cards.length) {
      const srt = cards.slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
      const T = QKC.tokens();
      QKC.line('#u-trend', { x: srt.map(r => r.date), xType: 'time', series: [{ name: 'Accuracy', data: srt.map(r => k.val(r, ['accuracy', 'acc'])), color: T.model, width: 2, symbols: true }, { name: 'Expected', data: srt.map(r => k.val(r, ['x_accuracy'])), color: T.ink3, dash: true, width: 1 }],
        yFmt: x => k.pct(x, 0), yMin: Math.max(0, Math.floor(20 * Math.min.apply(null, srt.map(r => k.val(r, ['x_accuracy'])).concat(srt.map(r => k.val(r, ['accuracy', 'acc']))).filter(k.isNum).concat([0.9]))) / 20 - 0.05), yMax: 1, yName: 'Share of calls right', xName: 'Game date', endLabels: true, label: 'Accuracy by game' });
      QKC.bar('#u-imp', { cats: srt.map(r => k.short(r.date)), series: [{ name: 'Run impact', data: srt.map(imp), color: T.cat[1] }], fmt: x => k.num(x, 2), valName: 'Runs moved by missed calls', catName: 'Game', label: 'Run impact by game' });
      QK.leaderboard(document.getElementById('u-cards'), { dense: true, maxHeight: 520, sort: { key: 'date', dir: 'desc' }, rowHref: r => (r.gpk ? k.href(r.level || L, 'game/' + r.gpk, S) : null), columns: [
        { key: 'date', label: 'Date', fmt: x => k.esc(k.short(x)) }, { key: 'game', label: 'Game' },
        { key: 'called', label: 'Called', num: true, fmt: x => k.int(x) }, { key: 'acc', label: 'Accuracy', num: true, fmt: x => k.fmtV(x, 'pct') }, { key: 'xacc', label: 'Expected', num: true, fmt: x => k.fmtV(x, 'pct') },
        { key: 'missed', label: 'Missed', num: true, fmt: x => k.int(x) }, { key: 'imp', label: 'Run impact', type: 'bar', fmt: x => k.num(x, 2) }, { key: 'fav', label: 'Favoured', sort: false }],
        rows: cards.map(r => {
          const fav = r.favoured || r.favored || r.fav;
          const favR = k.val(r, ['home_favour', 'favour', 'favor', 'fav_runs']);
          return { gpk: r.gpk, level: r.level, date: r.date, game: r.away && r.home ? k.teamAbbr(r.away) + ' @ ' + k.teamAbbr(r.home) : (r.gpk ? '#' + r.gpk : '—'), called: k.val(r, ['called', 'n']), acc: k.val(r, ['accuracy', 'acc']), xacc: r.x_accuracy,
            missed: k.val(r, ['missed', 'misses', 'n_missed']), imp: imp(r), fav: fav ? k.teamAbbr(fav) + (k.isNum(favR) ? ' ' + k.signed(Math.abs(favR), 2) : '') : (k.isNum(favR) ? (Math.abs(favR) <= 0.005 ? 'neither' : (favR > 0 ? 'home ' : 'away ') + k.num(Math.abs(favR), 2)) : '—') };
        }) });
    } else {
      ['u-trend', 'u-imp', 'u-cards'].forEach(x => { const n = document.getElementById(x); if (n) n.innerHTML = QK.empty('No per-game scorecards yet'); });
    }
    if (typeof BP.setMeta === 'function') { try { BP.setMeta(k.esc(name)); } catch (e) { /* optional */ } }
  });
}

if (typeof BP.route === 'function') {
  [['umpires', renderList], ['#/umpires', renderList], ['umpire', renderOne], ['#/umpire/<id>', renderOne]].forEach(r => { try { BP.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.BP || (window.BP = {}));
