/* The Quant Bullpen — history (#/history): all-time leaderboards from 1908, era-adjusted.
 *
 * Player seasons come from Retrosheet play-by-play (event files from 1908; Retrosheet's 1901–1907
 * box-score files are not read, so there are no player seasons before 1908; the first season shown is
 * history.json's `first`) and, after the last Retrosheet year, from Statcast; each season is valued by that season's own
 * linear weights, so a run in 1968 and a run in 2000 are each measured against their league.
 * wRC+ = 100 · (wRAA/PA + lgR/PA) / (lgR/PA) and RA9− = 100 · RA9 / lgRA9 (models/history.py);
 * neither is park-adjusted. Careers are recomputed from summed components.
 *
 * Data: data/<L>/history.json (analytics/history.py): {"leaders": {bat_war|bat_wraa|bat_hr|bat_h|bat_wrc_plus|pit_war|pit_k|
 * pit_ra9_minus|all_war: {cols, rows}}, "era": [[season, pa, runs_per_pa, hr_pa, k_pct, bb_pct, ra9]], "meta":
 * {"retrosheet_notice"}, "rules", "first", "last"}. Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const RETRO = 'The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".';
let FIRST = 1908;       // the first season with player history (history.json `first`; Retrosheet event files start in 1908)
const ST = { scope: '', metric: '', from: FIRST, to: 2100, q: '' };
const MLABEL = { k: 'Strikeouts', wrc_plus: 'wRC+', ra9_minus: 'RA9−', war: 'WAR', bwar: 'Bullpen WAR', batting_runs: 'Batting runs', lw_runs: 'Linear-weights runs', hr: 'Home runs', h: 'Hits', sb: 'Stolen bases', so: 'Strikeouts', k: 'Strikeouts', ip: 'Innings', w: 'Wins', sv: 'Saves', woba: 'wOBA', pa: 'Plate appearances', rbi: 'RBI', r: 'Runs', bb: 'Walks', era: 'ERA', fip: 'FIP', runs_above_avg: 'Runs above average', wraa: 'wRAA' };
const LOWER = /ra9_minus|^era$|^fip$|minus/;

/* {scope: {metric: rows}} from the payload's arrangement. */
/* {scope: {metric: {rows, meta}}} from E's leaders ({bat_war: {cols, rows}, ...}) or other arrangements. */
const SCOPE_OF = { bat: 'hitters', pit: 'pitchers', all: 'all' };
function boardsOf(d) {
  const k = K(), out = {};
  if (!d || d.ok === false) return out;
  const put = (scope, metric, rows, meta) => { if (!Array.isArray(rows) || !rows.length) return; (out[scope] = out[scope] || {})[metric] = { rows: rows, meta: meta || {} }; };
  const L = d.leaders || d.boards || {};
  Object.keys(L).forEach(key => {
    const v = L[key];
    const m = /^(bat|pit|all)_(.+)$/.exec(key);
    const rows = Array.isArray(v) ? v : k.colRows(v);
    if (m) put(SCOPE_OF[m[1]], m[2], rows, { sort: m[2] });
    else if (v && typeof v === 'object' && !Array.isArray(v) && !v.cols) Object.keys(v).forEach(mm => put(key, mm, Array.isArray(v[mm]) ? v[mm] : k.colRows(v[mm])));
  });
  return out;
}

function rowOf(r, metric) {
  const k = K();
  if (Array.isArray(r)) return { pid: String(r[0]), name: r[1], v: r[2], season: r[3], n: r[4] };
  const pid = String(r.pid || r.id || r.index || r.batter || r.pitcher || r.player || '');
  const first = r.first, last = r.last;
  const ip = k.isNum(r.ip) ? r.ip : (k.isNum(r.outs) ? r.outs / 3 : null);
  return { pid: pid, name: r.name, v: r[metric], season: k.isNum(first) ? (first === last ? String(first) : first + '–' + last) : (r.season || ''), n: k.isNum(r.pa) ? r.pa : ip, ip: !k.isNum(r.pa) && k.isNum(ip), seasons: r.seasons, raw: r };
}

function fmtM(m, v, meta) {
  const k = K();
  if (meta && meta.fmt) return k.fmtV(v, meta.fmt);
  if (/plus|minus/.test(m)) return k.isNum(v) ? String(Math.round(v)) : '—';
  if (/war|runs|wraa/.test(m)) return k.isNum(v) ? k.num(v, 1) : '—';
  if (/woba|avg|obp|slg/.test(m)) return k.rate3(v);
  if (/era|fip|ra9$/.test(m)) return k.num(v, 2);
  if (m === 'ip') return k.fmtV(v, 'ip');
  return k.isNum(v) ? (Number.isInteger(Number(v)) ? k.int(v) : k.num(v, 1)) : '—';
}
function seasonNum(s) { const m = /(\d{4})/.exec(String(s || '')); return m ? Number(m[1]) : null; }
function seasonEnd(s) { const m = /(\d{4})\D+(\d{2,4})\s*$/.exec(String(s || '')); if (!m) return seasonNum(s); return m[2].length === 2 ? Number(m[1].slice(0, 2) + m[2]) : Number(m[2]); }

function render(el, params) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">All-time leaders, <span id="hi-first">' + FIRST + '</span> to now <span class="card-sub" id="hi-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls"><label>Board<select id="hi-scope"></select></label><label>Metric<select id="hi-metric" class="gq-wide"></select></label>' +
    '<label>From <input id="hi-from" type="number" min="' + FIRST + '" max="2100" step="1" style="width:76px"></label><label>To <input id="hi-to" type="number" min="' + FIRST + '" max="2100" step="1" style="width:76px"></label>' +
    '<label>Era' + k.select('hi-era', [['', 'Any'], ['1908-1919', 'Dead ball (1908–19)'], ['1920-1941', 'Live ball (1920–41)'], ['1942-1960', 'Integration (1942–60)'], ['1961-1976', 'Expansion (1961–76)'], ['1977-1993', 'Free agency (1977–93)'], ['1994-2005', 'High offence (1994–2005)'], ['2006-2014', 'Post-testing (2006–14)'], ['2015-2100', 'Statcast (2015–)']], '') + '</label>' +
    '<label>Highlight<input id="hi-q" class="gq-search" type="search" placeholder="player…"></label></div>' +
    '<div id="hi-chart" style="height:380px"></div><div id="hi-table"></div><div class="pg-note gq-note" id="hi-note"></div><div class="gq-retro">' + k.esc(BP.RETRO_NOTICE || RETRO) + '</div></div>' +
    '<div class="card"><div class="card-header">League by year <span class="card-sub">The run environment each season is measured against: league runs per nine innings, strikeout and home-run rates.</span></div><div id="hi-env" style="height:300px"></div></div>';
  return k.ready().then(() => BP.load('mlb/history.json')).then(d => (k.ok(d) ? d : BP.load('mlb/history.json').then(d2 => d2 || d))).then(d => {
    if (!k.alive(el)) return;
    const $ = id => document.getElementById(id);
    if (d && k.isNum(d.first) && Number(d.first) !== FIRST) {
      if (ST.from === FIRST) ST.from = Number(d.first);
      FIRST = Number(d.first);
      if ($('hi-first')) $('hi-first').textContent = FIRST;
      ['hi-from', 'hi-to'].forEach(x => { if ($(x)) $(x).min = FIRST; });
    }
    const B = boardsOf(d);
    const scopes = Object.keys(B);
    if (!scopes.length) { $('hi-table').innerHTML = k.notBuilt('The all-time leaderboards', d); $('hi-sub').textContent = ''; $('hi-chart').style.display = 'none'; envChart(null); return; }
    const metaOf = k.metaOf((d && d.metrics) || []);
    const SL = { hitters: 'Hitters (career)', pitchers: 'Pitchers (career)', all: 'All players (career WAR)', career: 'Career', season: 'Single season', active: 'Active players' };
    if (scopes.indexOf(ST.scope) < 0) ST.scope = scopes.indexOf('all') >= 0 ? 'all' : scopes[0];
    $('hi-scope').innerHTML = scopes.map(s => '<option value="' + k.esc(s) + '"' + (s === ST.scope ? ' selected' : '') + '>' + k.esc(SL[s] || k.titleCase(s)) + '</option>').join('');
    const qy = params.query || {};
    if (qy.m) ST.metric = qy.m;
    const syncM = () => {
      const ms = Object.keys(B[ST.scope] || {});
      if (ms.indexOf(ST.metric) < 0) ST.metric = ms.indexOf('war') >= 0 ? 'war' : ms.indexOf('wrc_plus') >= 0 ? 'wrc_plus' : ms[0];
      $('hi-metric').innerHTML = ms.map(m => '<option value="' + k.esc(m) + '"' + (m === ST.metric ? ' selected' : '') + '>' + k.esc((metaOf[m] && metaOf[m].label) || ((B[ST.scope][m].meta || {}).label) || MLABEL[m] || k.titleCase(m)) + '</option>').join('');
    };
    const draw = () => {
      const bd = (B[ST.scope] || {})[ST.metric];
      if (!bd) { $('hi-table').innerHTML = k.muted('No board.'); return; }
      const meta = metaOf[ST.metric] || bd.meta || {};
      const lower = meta.lower !== undefined ? !!meta.lower : LOWER.test(ST.metric);
      const q = k.fold(ST.q.trim());
      const rows = bd.rows.map(r => rowOf(r, ST.metric)).filter(r => k.isNum(r.v)).filter(r => { const a = seasonNum(r.season), b = seasonEnd(r.season); return (!k.isNum(a) || b >= ST.from) && (!k.isNum(a) || a <= ST.to); });
      rows.sort((a, b) => (lower ? a.v - b.v : b.v - a.v));
      const lbl = meta.label || MLABEL[ST.metric] || k.titleCase(ST.metric);
      const L = 'mlb';
      const link = r => (r.pid && /^\d+$/.test(r.pid) ? '<a class="ply-link" href="' + k.playerHref(L, r.pid, null, ST.scope === 'pitchers' ? 'pitcher' : null) + '">' + k.esc(r.name || k.name(r.pid)) + '</a>' : '<span>' + k.esc(r.name || r.pid) + '</span>');
      const hits = q ? rows.filter(r => k.fold(r.name || '').indexOf(q) >= 0) : [];
      const extra = ST.scope === 'all' ? [['war_bat', 'Batting WAR'], ['war_pit', 'Pitching WAR']] : ST.scope === 'pitchers' ? [['ra9', 'RA9'], ['k', 'SO']] : [['hr', 'HR'], ['woba', 'wOBA'], ['wrc_plus', 'wRC+']];
      const ex = extra.filter(x => x[0] !== ST.metric && rows.some(r => k.isNum(r.raw && r.raw[x[0]])));
      const hasS = rows.some(r => r.season), hasN = rows.some(r => k.isNum(r.n));
      $('hi-table').innerHTML = rows.length ? k.table([{ label: '#', sortable: false }, { label: 'Player' }].concat(hasS ? [{ label: 'Seasons' }] : []).concat(hasN ? [{ label: rows.some(r => r.ip) ? 'IP' : 'PA', align: 'right' }] : []).concat(ex.map(x => ({ label: x[1], align: 'right' }))).concat([{ label: lbl + (lower ? ' ↓' : ''), align: 'right' }]),
        rows.slice(0, 200).map((r, i) => ({ _class: hits.indexOf(r) >= 0 ? 'gq-hit' : '', cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name || r.pid, html: link(r) }].concat(hasS ? [{ v: seasonNum(r.season), html: k.esc(r.season || '—') }] : []).concat(hasN ? [{ v: r.n, html: k.isNum(r.n) ? (r.ip ? k.num(r.n, 0) : k.int(r.n)) : '—' }] : [])
          .concat(ex.map(x => ({ v: r.raw[x[0]], html: fmtM(x[0], r.raw[x[0]], {}) }))).concat([{ v: r.v, html: '<strong>' + fmtM(ST.metric, r.v, meta) + '</strong>' }]) })), { compact: true, sticky: true })
        : k.muted('Nobody in this window. Widen the years.');
      k.sortable($('hi-table'));
      $('hi-sub').textContent = rows.length + ' on the board · ' + (SL[ST.scope] || ST.scope) + ' · ' + lbl + (ST.from > FIRST || ST.to < 2100 ? ' · ' + ST.from + '–' + Math.min(ST.to, new Date().getFullYear()) : '');
      const top = rows.slice(0, 25);
      const node = $('hi-chart');
      if (top.length && top.some(r => seasonNum(r.season))) {
        node.style.display = '';
        const all = rows.filter(r => seasonNum(r.season));
        k.plot(node, [{ type: 'scatter', mode: 'markers', x: all.map(r => (seasonNum(r.season) + seasonEnd(r.season)) / 2), y: all.map(r => r.v), text: all.map(r => (r.name || r.pid) + ' · ' + r.season), hovertemplate: '%{text}: %{y}<extra></extra>',
          marker: { size: all.map((r, i) => (i < 10 ? 11 : 6)), color: all.map((r, i) => (hits.indexOf(r) >= 0 ? '#ffffff' : i < 10 ? '#f97316' : 'rgba(88,166,255,0.55)')), line: { color: '#0d1117', width: 0.5 } } }],
        k.layout({ margin: { l: 50, r: 10, t: 10, b: 40 }, xaxis: { title: ST.scope === 'career' ? 'Middle of the career' : 'Season' }, yaxis: { title: lbl, autorange: lower ? 'reversed' : true } }));
      } else node.style.display = 'none';
      $('hi-note').innerHTML = 'Era-adjusted metrics compare each season with its own league: wRC+ and RA9− (100 = league average; RA9− lower is better) use that season\'s runs per plate appearance and runs per nine, and neither is park-adjusted. Rate boards need 3,000 PA (wRC+) or 1,500 innings (RA9−). WAR before 2015 is Bullpen WAR\'s historical version: Retrosheet linear-weights batting and baserunning, a range-factor fielding proxy from Lahman putouts, assists and errors (it overrates some dead-ball-era fielders), positional adjustments and RA9-based pitching; it is rougher than the Statcast-era figure, whose batting is regressed expected value rather than results. Player history starts in 1908, the first season of Retrosheet play-by-play (its 1901–1907 box-score files are not read). Click a modern player for his page.';
    };
    $('hi-scope').onchange = e => { ST.scope = e.target.value; syncM(); draw(); };
    $('hi-metric').onchange = e => { ST.metric = e.target.value; draw(); };
    $('hi-from').value = ST.from; $('hi-to').value = Math.min(ST.to, new Date().getFullYear());
    $('hi-from').onchange = e => { ST.from = Number(e.target.value) || FIRST; $('hi-era').value = ''; draw(); };
    $('hi-to').onchange = e => { ST.to = Number(e.target.value) || 2100; $('hi-era').value = ''; draw(); };
    $('hi-era').onchange = e => { const v = e.target.value; if (v) { const p = v.split('-'); ST.from = Number(p[0]); ST.to = Number(p[1]); } else { ST.from = FIRST; ST.to = 2100; } $('hi-from').value = ST.from; $('hi-to').value = Math.min(ST.to, new Date().getFullYear()); draw(); };
    let t = null;
    $('hi-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 200); };
    syncM();
    draw();
    envChart(d && (d.era || d.league || d.eras));
    const nt = document.querySelector('.gq-retro');
    if (nt && d && d.meta && d.meta.retrosheet_notice) nt.textContent = d.meta.retrosheet_notice;
  });
}

/* League environment: {season: {rpg, woba_scale, ...}} or [[season, rpg, scale]] or [{season, rpg}]. */
/* E's era rows [[season, pa, runs_per_pa, hr_pa, k_pct, bb_pct, ra9]]: league RA9 (runs per nine), HR and K rates. */
function envChart(env) {
  const k = K();
  const node = document.getElementById('hi-env');
  if (!node) return;
  const rows = (Array.isArray(env) ? env : []).map(r => (Array.isArray(r) ? { s: r[0], rpa: r[2], hr: r[3], kp: r[4], bb: r[5], ra9: r[6] } : { s: r.season, rpa: r.runs_per_pa, hr: r.hr_pa, kp: r.k_pct, bb: r.bb_pct, ra9: r.ra9 })).filter(r => k.isNum(r.s)).sort((a, b) => a.s - b.s);
  if (!rows.length) { node.innerHTML = k.muted('The league-by-year table is not published yet.'); node.style.height = 'auto'; return; }
  const tr = [];
  if (rows.some(r => k.isNum(r.ra9))) tr.push({ type: 'scatter', mode: 'lines', name: 'League RA9 (runs per 9)', x: rows.map(r => r.s), y: rows.map(r => r.ra9), line: { color: '#f97316', width: 2 } });
  else tr.push({ type: 'scatter', mode: 'lines', name: 'Runs per PA × 38', x: rows.map(r => r.s), y: rows.map(r => (k.isNum(r.rpa) ? 38 * r.rpa : null)), line: { color: '#f97316', width: 2 } });
  tr.push({ type: 'scatter', mode: 'lines', name: 'Strikeout rate', x: rows.map(r => r.s), y: rows.map(r => r.kp), yaxis: 'y2', line: { color: '#58a6ff', width: 1.5 } });
  tr.push({ type: 'scatter', mode: 'lines', name: 'HR per PA', x: rows.map(r => r.s), y: rows.map(r => r.hr), yaxis: 'y2', line: { color: '#bc8cff', width: 1.5, dash: 'dot' } });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 44, r: 50, t: 28, b: 32 }, xaxis: { title: 'Season' }, yaxis: { title: 'Runs per 9' }, yaxis2: { overlaying: 'y', side: 'right', showgrid: false, tickformat: '.0%', title: 'Rate per PA' } }, k.legendTop())));
}

if (typeof BP.route === 'function') { BP.route('history', render); try { BP.route('#/history', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
