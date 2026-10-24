/* The Quant Bullpen — leaderboards (#/<L>/leaders), on kit v4 "Broadcast": the black power list, controls, the top 15 as a chart coloured by
 * percentile, the board as a v2 leaderboard with percentile heat cells, and top-five cards on the spec's headline metrics.
 *
 * Any catalogue metric for hitters or pitchers, or any per-pitch arsenal metric for one pitch
 * type, with a sample floor, a qualified-only switch, a team filter, best or worst first and the
 * league's distribution drawn behind the leaders. "At a glance" shows the builder's own
 * pre-filtered boards (leaders.json) when they exist.
 *
 * Address: ?k=hitter|pitcher|pitch&m=<metric>&pt=<pitch type> presets the board.
 * Data: data/<L>/<S>/hitters.json, pitchers.json ("arsenal"), leaders.json. Uses BP.gk.
 * Round 5: the metric picker lists our model metrics first (BP.ui.metricOpts), the board and its head carry the cobalt
 * "Our model" tag with a strip naming the model, and the top-five cards lead with Bullpen WAR and Stuff+. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const S0 = { kind: 'hitter', metric: '', pt: 'FF', floor: null, qual: true, team: '', dir: 'best', n: 50 };
const ARS_METRICS = [['stuff_plus', 'Stuff+', 'plus'], ['location_plus', 'Location+', 'plus'], ['pitching_plus', 'Pitching+', 'plus'], ['velo', 'Velocity', '1'], ['ivb', 'Induced vertical break', '1'], ['hb', 'Horizontal break', '1'],
  ['spin', 'Spin rate', 'rpm'], ['vaa', 'Vertical approach angle', '1'], ['ext', 'Extension', '1'], ['whiff_pct', 'Whiff%', 'pct'], ['csw_pct', 'CSW%', 'pct'], ['rv', 'Run value', 'signed'], ['rv100', 'Run value per 100', 'signed2'], ['usage', 'Usage', 'pct'], ['xwoba_plus', 'xwOBA+ against', '3']];
const ALIAS = { stuff_plus: ['stuff_plus', 'stuff'], location_plus: ['location_plus', 'location'], pitching_plus: ['pitching_plus', 'pitching'], velo: ['velo', 'velocity', 'release_speed'], ivb: ['ivb', 'induced_vb'], hb: ['hb', 'horz_break'],
  spin: ['spin', 'spin_rate'], vaa: ['vaa'], ext: ['ext', 'extension'], whiff_pct: ['whiff_pct', 'whiff'], csw_pct: ['csw_pct', 'csw'], rv: ['rv', 'run_value'], rv100: ['rv100', 'rv_per_100'], usage: ['usage', 'usage_pct'], xwoba_plus: ['xwoba_plus', 'xwoba', 'xwoba_against'] };
const LOWER_ARS = { xwoba_plus: true };

/* v4: Who's hot, the black power list: the top name on five boards (the index's leaders, as on the overview) */
function hotBand(L) {
  const src = L === 'mlb' ? (BP.index() || {}) : (BP.levelInfo(L) || {});
  const hot = BP.ui.hotItems ? BP.ui.hotItems(src.leaders || {}, L) : [];
  return hot.length ? QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, board by board', sub: 'The top name on five boards, the next best behind, and a line on what the number means.' }) + QK.hotRow(hot)) : '';
}
function render(el, params, state) {
  const k = K();
  const U = BP.ui;
  const L = k.L(params, state);
  const q = params.query || {};
  if (q.k && /^(hitter|pitcher|pitch)$/.test(q.k)) S0.kind = q.k;
  if (q.m) S0.metric = q.m;
  if (q.pt) S0.pt = q.pt;
  el.innerHTML = QK.sectionHead({ kicker: 'Leaderboards · ' + k.LN(L), title: 'Leaderboards', sub: 'Any metric for hitters, pitchers or one pitch type, best or worst first, with the sample floor in your hands. Percentile cells rank each player against everyone past the floor (100 = best).' }) +
    QK.note('A <b>90th percentile</b> means better than 90 in 100 of the players past the floor. Rates need a sample: early in a season the floor is prorated, so small samples are kept out.') +
    hotBand(L) +
    '<section class="qk-card"><div class="qk-card-body"><div class="bp-ctl">' +
    U.seg('ld-kind', 'Board', [['hitter', 'Hitters'], ['pitcher', 'Pitchers'], ['pitch', 'Pitch types']], S0.kind) +
    '<label id="ld-pt-l">Pitch type<select id="ld-pt"></select></label>' +
    '<label>Metric<select id="ld-metric" class="gq-wide"></select></label>' +
    '<label>Team<select id="ld-team"><option value="">All teams</option></select></label>' +
    '<label>Order' + k.select('ld-dir', [['best', 'Best first'], ['worst', 'Worst first']], S0.dir) + '</label>' +
    '<label>Show' + k.select('ld-n', [[25, 'Top 25'], [50, 'Top 50'], [100, 'Top 100'], [1000, 'All']], S0.n) + '</label>' +
    '<label>Min <span id="ld-floor-u"></span> <b id="ld-floor-v"></b><input id="ld-floor" type="range" min="0" max="700" step="5"></label>' +
    '<label class="bp-check"><input type="checkbox" id="ld-qual"> past the floor for the position or role</label>' +
    '</div></div></section>' +
    '<div id="ld-ours" style="margin-top:var(--sp-4)"></div><div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-5"><div id="ld-chart-card"></div></div><div class="qk-span-7"><div id="ld-board-card"></div></div></div>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'At a glance', title: 'Top five', sub: 'Our models first (Bullpen WAR, Stuff+), then the headline metrics from the metrics spec; players past the floor for their position or role.' }) + '<div class="qk-grid" id="ld-glance"></div></section>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json'), k.loadY(L, S, 'leaders.json'), k.loadNames(), U.specReady()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, hc = k.catOf(o.res[0], 'hitters'), pc = k.catOf(o.res[1], 'pitchers'), lead = o.res[2];
    if (hc) k.learnCat(hc);
    if (pc) k.learnCat(pc);
    const $ = id => document.getElementById(id);
    if (!hc && !pc) { $('ld-board-card').innerHTML = U.card2('Leaderboard', '', QK.empty('Not built yet', 'The ' + k.LN(L) + ' ' + S + ' catalogues are not available.')); glance(L, S, lead, null, null); return; }
    const ars = (pc && pc.arsenal) || {};
    const pts = {};
    Object.keys(ars).forEach(pid => Object.keys(ars[pid] || {}).forEach(pt => { if (pt !== 'all' && pt !== 'ALL') pts[pt] = (pts[pt] || 0) + 1; }));
    const ptList = Object.keys(pts).sort((a, b) => pts[b] - pts[a]);
    $('ld-pt').innerHTML = ptList.map(pt => '<option value="' + k.esc(pt) + '"' + (pt === S0.pt ? ' selected' : '') + '>' + k.esc(k.pitchName(pt)) + ' (' + pts[pt] + ')</option>').join('');
    if (!ptList.length) { const b = $('ld-kind').querySelector('button[data-value=pitch]'); if (b) b.style.display = 'none'; }
    const teams = {};
    [hc, pc].forEach(c => { if (c) Object.keys(c.players).forEach(id => { const t = c.players[id].team; if (t) teams[t] = 1; }); });
    $('ld-team').innerHTML = '<option value="">All teams</option>' + Object.keys(teams).sort((a, b) => k.teamAbbr(a).localeCompare(k.teamAbbr(b))).map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamAbbr(t)) + '</option>').join('');
    $('ld-qual').checked = S0.qual;
    const sync = () => {
      const kind = S0.kind;
      $('ld-pt-l').style.display = kind === 'pitch' ? '' : 'none';
      if (kind === 'pitch') {
        if (ptList.indexOf(S0.pt) < 0) S0.pt = ptList[0];
        const avail = ARS_METRICS.filter(m => Object.keys(ars).some(pid => { const r = (ars[pid] || {})[S0.pt]; return r && k.isNum(k.val(r, ALIAS[m[0]] || [m[0]])); }));
        if (!avail.find(m => m[0] === S0.metric)) S0.metric = (avail[0] || ARS_METRICS[0])[0];
        const aO = avail.filter(m => U.ours(m[0])), aB = avail.filter(m => !U.ours(m[0])), aOpt = m => '<option value="' + m[0] + '"' + (m[0] === S0.metric ? ' selected' : '') + '>' + k.esc(m[1]) + '</option>';
        $('ld-metric').innerHTML = (aO.length ? '<optgroup label="Our models">' + aO.map(aOpt).join('') + '</optgroup>' : '') + (aB.length ? '<optgroup label="Box score">' + aB.map(aOpt).join('') + '</optgroup>' : '');
        $('ld-floor-u').textContent = 'pitches';
      } else {
        const cat = kind === 'pitcher' ? pc : hc;
        const ms = (cat && cat.metrics) || [];
        if (!ms.find(m => m.key === S0.metric)) S0.metric = (k.headline(ms, kind === 'pitcher' ? k.PIT_PREFS : k.HIT_PREFS, 1)[0] || {}).key || '';
        $('ld-metric').innerHTML = U.metricOpts(ms, S0.metric, kind);
        $('ld-floor-u').textContent = kind === 'pitcher' ? 'BF' : 'PA';
      }
      const maxN = kind === 'pitch' ? Math.max.apply(null, Object.keys(ars).map(pid => { const r = (ars[pid] || {})[S0.pt]; return r ? (k.val(r, ['n', 'pitches', 'count']) || 0) : 0; }).concat([100]))
        : Math.max.apply(null, Object.keys(((kind === 'pitcher' ? pc : hc) || { players: {} }).players).map(id => k.sampleOf((kind === 'pitcher' ? pc : hc).players[id], kind)).concat([100]));
      $('ld-floor').max = String(Math.ceil(maxN / 10) * 10);
      if (S0.floor === null || S0.floor > maxN) S0.floor = kind === 'pitch' ? Math.min(100, Math.round(maxN * 0.1)) : 0;
      $('ld-floor').value = S0.floor; $('ld-floor-v').textContent = S0.floor;
      $('ld-qual').parentNode.style.display = kind === 'pitch' ? 'none' : '';
    };
    const draw = () => drawBoard(L, S, hc, pc);
    QK.seg($('ld-kind'), v => { S0.kind = v; S0.floor = null; sync(); draw(); });
    $('ld-pt').onchange = e => { S0.pt = e.target.value; S0.floor = null; sync(); draw(); };
    $('ld-metric').onchange = e => { S0.metric = e.target.value; draw(); };
    $('ld-floor').oninput = e => { S0.floor = Number(e.target.value); $('ld-floor-v').textContent = S0.floor; };
    $('ld-floor').onchange = draw;
    $('ld-qual').onchange = e => { S0.qual = e.target.checked; draw(); };
    $('ld-team').onchange = e => { S0.team = e.target.value; draw(); };
    $('ld-dir').onchange = e => { S0.dir = e.target.value; draw(); };
    $('ld-n').onchange = e => { S0.n = Number(e.target.value); draw(); };
    sync();
    draw();
    glance(L, S, lead, hc, pc);
  });
}

function drawBoard(L, S, hc, pc) {
  const k = K();
  const U = BP.ui;
  const kind = S0.kind;
  let rows = [], m, lower = false, fmt = '';
  if (kind === 'pitch') {
    const ars = (pc && pc.arsenal) || {};
    const def = ARS_METRICS.find(x => x[0] === S0.metric) || ARS_METRICS[0];
    m = { key: def[0], label: def[1] + ' · ' + k.pitchName(S0.pt), fmt: def[2] };
    lower = !!LOWER_ARS[def[0]]; fmt = def[2];
    Object.keys(ars).forEach(pid => {
      const r = (ars[pid] || {})[S0.pt];
      if (!r) return;
      const v = k.val(r, ALIAS[def[0]] || [def[0]]), n = k.val(r, ['n', 'pitches', 'count']) || 0;
      if (!k.isNum(v) || n < S0.floor) return;
      const p = ((pc || {}).players || {})[pid] || {};
      if (S0.team && String(p.team) !== S0.team) return;
      const key = k.pick(r, ALIAS[def[0]] || [def[0]]);
      rows.push({ pid: pid, v: v, n: n, team: p.team, pct: key === 'stuff' ? r.stuff_pct : key === 'whiff' ? r.whiff_pct_type : (r.pct || {})[key], name: p.name || k.name(pid), sub: BP.teamAbbr(p.team), href: k.pitcherHref(L, pid, S) });
    });
  } else {
    const cat = kind === 'pitcher' ? pc : hc;
    if (!cat) { document.getElementById('ld-board-card').innerHTML = U.card2('Leaderboard', '', QK.empty('Not built yet')); return; }
    m = Object.assign({}, k.metaOf(cat.metrics)[S0.metric] || { key: S0.metric, label: S0.metric });
    m.label = U.label(kind, m.key, m.label);
    lower = !!m.lower; fmt = m.fmt;
    Object.keys(cat.players).forEach(pid => {
      const p = cat.players[pid], v = (p.values || {})[m.key], n = k.sampleOf(p, kind);
      if (!k.isNum(v) || n < S0.floor) return;
      const okp = U.meets(p, U.setFor(kind, p), cat.team_games);
      if (S0.qual && !okp) return;
      if (S0.team && String(p.team) !== S0.team) return;
      const pc0 = okp && U.metricOk(p, m.key, 'ALL', cat.team_games) ? (p.pct || {})[m.key] : null;
      rows.push({ pid: pid, v: v, n: n, team: p.team, pct: pc0, name: p.name || k.name(pid), sub: (kind === 'pitcher' ? k.roleOf(p) : (p.pos || '')) + ' · ' + BP.teamAbbr(p.team), href: kind === 'pitcher' ? k.pitcherHref(L, pid, S) : k.hitterHref(L, pid, S) });
    });
  }
  const all = rows.map(r => r.v);
  const good = (S0.dir === 'best') !== lower;
  rows.sort((a, b) => (good ? b.v - a.v : a.v - b.v) || b.n - a.n);
  const shown = rows.slice(0, S0.n);
  const unit = kind === 'pitch' ? 'Pitches' : kind === 'pitcher' ? 'BF' : 'PA';
  const med = k.median(all);
  const sub = rows.length + ' with a value · ' + (S0.dir === 'best' ? 'best' : 'worst') + ' first · median ' + k.fmtV(med, fmt) + (lower ? ' · lower is better' : '');
  document.getElementById('ld-board-card').innerHTML = U.card2(m.label, U.oursTag(m.key) + (U.ours(m.key) ? ' ' : '') + esc0(sub) + (m.desc ? ' · ' + esc0(m.desc) : ''), '<div id="ld-table"></div>', { flush: true });
  const oursBox = document.getElementById('ld-ours');
  if (oursBox) oursBox.innerHTML = U.oursNote(kind === 'pitch' ? 'pitcher' : kind, [m.key]);
  const host = document.getElementById('ld-table');
  if (!shown.length) host.innerHTML = QK.empty('Nobody here', 'Lower the floor or untick the position floor.');
  else QK.leaderboard(host, { dense: true, rank: true, maxHeight: 640, rowHref: r => r.href, columns: [
    { key: 'name', label: kind === 'hitter' ? 'Hitter' : 'Pitcher', type: 'entity', sub: 'sub', mark: r => U.team(r.team, L, S), href: r => r.href },
    { key: 'n', label: unit, num: true, fmt: x => k.int(x) },
    { key: 'v', label: m.label.split(' · ')[0] + (lower ? ' ↓' : ''), type: 'pctl', pctl: 'pct', fmt: x => k.fmtV(x, fmt), tip: (m.desc || '') + ' The cell colour is the percentile (100 = best).' }],
    rows: shown.slice() });
  if (shown.length) U.tagHeads(host, { v: m.key });
  const top = shown.slice(0, 15);
  document.getElementById('ld-chart-card').innerHTML = U.card2('The top ' + top.length, 'Coloured by percentile; the median past the floor is ' + k.fmtV(med, fmt), top.length ? U.chart('ld-chart', Math.max(260, 22 * top.length + 70), 'Leaders: ' + m.label) : QK.empty('Nobody here'));
  if (top.length) QKC.bar('#ld-chart', { cats: top.map(r => k.surname(r.name) + ' · ' + k.teamAbbr(r.team)), series: [{ name: m.label, data: top.map(r => r.v) }], horizontal: true, labels: true, fmt: x => k.fmtV(x, fmt),
    colors: top.map(r => QK.pctHex(k.isNum(r.pct) ? r.pct : 50)), hrefs: top.map(r => r.href), labelWidth: 140, valName: m.label + (lower ? ' (lower is better)' : ''), catName: kind === 'hitter' ? 'Hitter' : 'Pitcher', label: 'Leaders' });
}
function esc0(s) { return BP.esc(s); }

/* The builder's boards (leaders.json: {hitters|pitchers: {metric: [[pid, v]]}} or {metric: [[pid, v]]}), else computed. */
function glance(L, S, lead, hc, pc) {
  const k = K();
  const U = BP.ui;
  const host = document.getElementById('ld-glance');
  if (!host) return;
  const boards = [];
  const want = kind0 => (kind0 === 'pitcher' ? ['war', 'stuff_plus'] : ['war']).concat((kind0 === 'pitcher' ? k.PIT_PREFS : k.HIT_PREFS).filter(x => typeof x === 'string')).slice(0, 7);
  [[hc, 'hitter'], [pc, 'pitcher']].forEach(x => {
    if (!x[0]) return;
    k.headline(x[0].metrics, want(x[1]), 6).map(m0 => Object.assign({}, m0, { label: U.label(x[1], m0.key, m0.label) })).forEach(m => {
      const rows = Object.keys(x[0].players).filter(pid => U.meets(x[0].players[pid], U.setFor(x[1], x[0].players[pid]), x[0].team_games) && k.isNum((x[0].players[pid].values || {})[m.key]))
        .map(pid => ({ pid: pid, v: x[0].players[pid].values[m.key] })).sort((a, b) => (m.lower ? a.v - b.v : b.v - a.v)).slice(0, 5);
      if (rows.length) boards.push({ m: m, kind: x[1], rows: rows });
    });
  });
  if (!boards.length && lead && lead.ok !== false) {
    const src = lead.leaders || lead;
    Object.keys(src).filter(key => Array.isArray(src[key]) && src[key].length).slice(0, 8).forEach(key => boards.push({ m: { key: key, label: key, fmt: '' }, kind: /^p_/.test(key) ? 'pitcher' : 'hitter', rows: src[key].slice(0, 5).map(r => ({ pid: String(r[0]), v: r[1] })) }));
  }
  host.innerHTML = boards.length ? boards.map(b => '<div class="qk-span-3">' + U.card2(b.m.label || b.m.key, (b.kind === 'pitcher' ? 'Pitchers' : 'Hitters') + U.oursTag(b.m.key), '<ul class="bp-list bp-lead">' +
    b.rows.map((r, i) => '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(r.pid, L, BP.teamAbbr(BP.player(r.pid).team), b.kind) + '<span class="v">' + k.fmtV(r.v, b.m.fmt) + '</span></li>').join('') + '</ul>', { flush: true }) + '</div>').join('')
    : '<div class="qk-span-12">' + QK.empty('No leaderboards yet') + '</div>';
}

if (typeof BP.route === 'function') { BP.route('leaders', render); try { BP.route('#/<L>/leaders', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
