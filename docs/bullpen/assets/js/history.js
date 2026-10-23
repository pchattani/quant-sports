/* The Quant Bullpen — history (#/history): all-time leaderboards from 1908, era-adjusted.
 *
 * Player seasons come from Retrosheet play-by-play (event files from 1908; Retrosheet's 1901–1907
 * box-score files are not read, so there are no player seasons before 1908; the first season shown is
 * history.json's `first`) and, after the last Retrosheet year, from Statcast; each season is valued by that season's own
 * linear weights, so a run in 1968 and a run in 2000 are each measured against their league.
 * wRC+ = 100 · (wRAA/PA + lgR/PA) / (lgR/PA) and RA9− = 100 · RA9 / lgRA9 (models/history.py);
 * neither is park-adjusted. Careers are recomputed from summed components.
 *
 * Design System 2.0: stat tiles, controls, a when-they-played chart, a v2 leaderboard and the run environment by year.
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
  const U = BP.ui;
  const ERAS = [['', 'Any'], ['1908-1919', 'Dead ball (1908–19)'], ['1920-1941', 'Live ball (1920–41)'], ['1942-1960', 'Integration (1942–60)'], ['1961-1976', 'Expansion (1961–76)'], ['1977-1993', 'Free agency (1977–93)'], ['1994-2005', 'High offence (1994–2005)'], ['2006-2014', 'Post-testing (2006–14)'], ['2015-2100', 'Statcast (2015–)']];
  el.innerHTML = QK.sectionHead({ kicker: 'All-time · MLB', title: 'Every season since <span id="hi-first">' + FIRST + '</span>', html: true, sub: 'Careers and seasons measured against their own league, so a run in 1968 and a run in 2000 each count against the run environment of the day.' }) +
    '<div id="hi-kpis"></div>' +
    '<section class="qk-card"><div class="qk-card-body"><div class="bp-ctl"><label>Board<select id="hi-scope"></select></label><label>Metric<select id="hi-metric" class="gq-wide"></select></label>' +
    '<label>From<input id="hi-from" type="number" min="' + FIRST + '" max="2100" step="1" style="width:84px"></label><label>To<input id="hi-to" type="number" min="' + FIRST + '" max="2100" step="1" style="width:84px"></label>' +
    '<label>Era' + k.select('hi-era', ERAS, '') + '</label><label>Highlight<input id="hi-q" class="gq-search" type="search" placeholder="player…"></label></div></div></section>' +
    '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-5"><div id="hi-chart-card"></div></div><div class="qk-span-7"><div id="hi-board-card"></div></div></div>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'League by year', title: 'The run environment', sub: 'What each season is measured against: league runs per nine innings, and the strikeout and home-run rates.' }) +
    '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Runs per nine innings', 'League RA9 by season', U.chart('hi-env', 280, 'League runs per nine by season')) + '</div><div class="qk-span-6">' +
    U.card2('Strikeouts and home runs', 'Share of plate appearances, by season', U.chart('hi-env2', 280, 'League strikeout and home-run rates by season')) + '</div></div></section>' +
    '<p class="bp-note gq-retro">' + k.esc(BP.RETRO_NOTICE || RETRO) + '</p>';
  return k.ready().then(() => BP.load('mlb/history.json')).then(d => {
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
    if (!scopes.length) { $('hi-board-card').innerHTML = U.card2('All-time leaders', '', QK.empty('Not built yet', 'The all-time leaderboards are not available.')); envChart(null); return; }
    const metaOf = k.metaOf((d && d.metrics) || []);
    const SL = { hitters: 'Hitters (career)', pitchers: 'Pitchers (career)', all: 'All players (career WAR)', career: 'Career', season: 'Single season', active: 'Active players' };
    const lead = (scope, metric) => { const bd = (B[scope] || {})[metric]; if (!bd) return null; const rs = bd.rows.map(r => rowOf(r, metric)).filter(r => k.isNum(r.v)); rs.sort((a, b) => (LOWER.test(metric) ? a.v - b.v : b.v - a.v)); return rs[0] || null; };
    const t1 = lead('all', 'war') || lead('hitters', 'war'), t2 = lead('hitters', 'wrc_plus'), t3 = lead('pitchers', 'ra9_minus'), t4 = lead('pitchers', 'war');
    $('hi-kpis').innerHTML = '<div class="bp-kpis">' + QK.stats([
      t1 ? { label: 'Career WAR leader', value: k.surname(t1.name || t1.pid) + ' ' + fmtM('war', t1.v, {}), signal: true, sub: String(t1.season || ''), tip: 'Bullpen WAR, the historical version before 2015' } : null,
      t2 ? { label: 'Best career wRC+', value: k.surname(t2.name || t2.pid) + ' ' + fmtM('wrc_plus', t2.v, {}), sub: (t2.season || '') + ' · 3,000+ PA', tip: 'Runs created per PA against the league, 100 = average' } : null,
      t3 ? { label: 'Best career RA9−', value: k.surname(t3.name || t3.pid) + ' ' + fmtM('ra9_minus', t3.v, {}), sub: (t3.season || '') + ' · 1,500+ IP', tip: 'Runs allowed per nine against the league, 100 = average, lower is better' } : null,
      t4 ? { label: 'Pitching WAR leader', value: k.surname(t4.name || t4.pid) + ' ' + fmtM('war', t4.v, {}), sub: String(t4.season || '') } : null
    ]) + '</div>';
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
      if (!bd) { $('hi-board-card').innerHTML = U.card2('All-time leaders', '', QK.empty('No board')); return; }
      const meta = metaOf[ST.metric] || bd.meta || {};
      const lower = meta.lower !== undefined ? !!meta.lower : LOWER.test(ST.metric);
      const q = k.fold(ST.q.trim());
      const rows = bd.rows.map(r => rowOf(r, ST.metric)).filter(r => k.isNum(r.v)).filter(r => { const a = seasonNum(r.season), b = seasonEnd(r.season); return (!k.isNum(a) || b >= ST.from) && (!k.isNum(a) || a <= ST.to); });
      rows.sort((a, b) => (lower ? a.v - b.v : b.v - a.v));
      const lbl = meta.label || MLABEL[ST.metric] || k.titleCase(ST.metric);
      const L = 'mlb';
      const hrefOf = r => (r.pid && /^\d+$/.test(r.pid) ? k.playerHref(L, r.pid, null, ST.scope === 'pitchers' ? 'pitcher' : null) : null);
      const hits = q ? rows.filter(r => k.fold(r.name || '').indexOf(q) >= 0) : [];
      const extra = ST.scope === 'all' ? [['war_bat', 'Batting WAR'], ['war_pit', 'Pitching WAR']] : ST.scope === 'pitchers' ? [['ra9', 'RA9'], ['k', 'SO']] : [['hr', 'HR'], ['woba', 'wOBA'], ['wrc_plus', 'wRC+']];
      const ex = extra.filter(x => x[0] !== ST.metric && rows.some(r => k.isNum(r.raw && r.raw[x[0]])));
      const hasN = rows.some(r => k.isNum(r.n)), ipb = rows.some(r => r.ip);
      const window0 = ST.from > FIRST || ST.to < 2100 ? ST.from + '–' + Math.min(ST.to, new Date().getFullYear()) : FIRST + ' to now';
      $('hi-board-card').innerHTML = U.card2(lbl + (lower ? ' (lower is better)' : ''), rows.length + ' on the board · ' + k.esc(SL[ST.scope] || ST.scope) + ' · ' + window0, '<div id="hi-table"></div>', { flush: true });
      if (!rows.length) $('hi-table').innerHTML = QK.empty('Nobody in this window', 'Widen the years.');
      else QK.leaderboard($('hi-table'), { dense: true, rank: true, maxHeight: 620, rowClass: r => (hits.indexOf(r._r) >= 0 ? 'is-me' : ''), rowHref: r => r.href, columns: [
        { key: 'name', label: 'Player', type: 'entity', sub: 'season', href: r => r.href }]
        .concat(hasN ? [{ key: 'n', label: ipb ? 'IP' : 'PA', num: true, fmt: x => (k.isNum(x) ? (ipb ? k.num(x, 0) : k.int(x)) : '—') }] : [])
        .concat(ex.map(x => ({ key: 'x_' + x[0], label: x[1], num: true, fmt: v => fmtM(x[0], v, {}) })))
        .concat([{ key: 'v', label: lbl + (lower ? ' ↓' : ''), type: 'bar', fmt: v => fmtM(ST.metric, v, meta) }]),
        rows: rows.slice(0, 200).map(r => { const o2 = { _r: r, name: r.name || k.name(r.pid) || r.pid, season: r.season || '', n: r.n, v: r.v, href: hrefOf(r) }; ex.forEach(x => { o2['x_' + x[0]] = (r.raw || {})[x[0]]; }); return o2; }) });
      const all = rows.filter(r => seasonNum(r.season));
      if (all.length) {
        $('hi-chart-card').innerHTML = U.card2('When they played', 'Each player at the middle of the ' + (ST.scope === 'season' ? 'season' : 'career') + '; the top ten in blue' + (hits.length ? ', your highlight in white' : ''), U.chart('hi-chart', 420, lbl + ' by era'));
        const T = QKC.tokens();
        QKC.scatter('#hi-chart', { points: all.slice(0, 400).map((r, i) => ({ x: Math.round((seasonNum(r.season) + seasonEnd(r.season)) / 2), y: r.v, name: (r.name || r.pid) + ' · ' + r.season, label: i < 5 || hits.indexOf(r) >= 0 ? k.surname(r.name || r.pid) : ' ', color: hits.indexOf(r) >= 0 ? T.ink1 : i < 10 ? T.model : QKC.hexA(T.ink3, 0.55), size: i < 10 || hits.indexOf(r) >= 0 ? 11 : 6, href: hrefOf(r) })),
          xName: ST.scope === 'season' ? 'Season' : 'Middle of the career', yName: lbl, xFmt: x => String(Math.round(x)), yFmt: v => fmtM(ST.metric, v, meta), labelAll: true, yInverse: lower, label: lbl + ' by era' });
      } else $('hi-chart-card').innerHTML = '';
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
    BP.setMeta('Era-adjusted: wRC+ and RA9− use each season\'s league; neither is park-adjusted');
  });
}

/* League environment rows [[season, pa, runs_per_pa, hr_pa, k_pct, bb_pct, ra9]] (or objects). */
function envChart(env) {
  const k = K();
  const rows = (Array.isArray(env) ? env : []).map(r => (Array.isArray(r) ? { s: r[0], rpa: r[2], hr: r[3], kp: r[4], bb: r[5], ra9: r[6] } : { s: r.season, rpa: r.runs_per_pa, hr: r.hr_pa, kp: r.k_pct, bb: r.bb_pct, ra9: r.ra9 })).filter(r => k.isNum(r.s)).sort((a, b) => a.s - b.s);
  if (!rows.length) { ['hi-env', 'hi-env2'].forEach(id => { const n = document.getElementById(id); if (n) n.innerHTML = QK.empty('Not published yet'); }); return; }
  const T = QKC.tokens();
  const ra = rows.some(r => k.isNum(r.ra9));
  QKC.line('#hi-env', { x: rows.map(r => r.s), xType: 'value', series: [{ name: ra ? 'League RA9' : 'Runs per PA × 38', data: rows.map(r => (ra ? r.ra9 : (k.isNum(r.rpa) ? 38 * r.rpa : null))), color: T.model, width: 2 }],
    yFmt: v => k.num(v, 1), xFmt: v => String(Math.round(v)), yName: 'Runs per nine innings', xName: 'Season', endLabels: true, label: 'League runs per nine' });
  QKC.line('#hi-env2', { x: rows.map(r => r.s), xType: 'value', series: [{ name: 'Strikeouts', data: rows.map(r => r.kp), color: T.cat[0], width: 2 }, { name: 'Home runs', data: rows.map(r => r.hr), color: T.cat[2], width: 2 }],
    yFmt: v => Math.round(v * 100) + '%', xFmt: v => String(Math.round(v)), yName: 'Share of plate appearances', xName: 'Season', endLabels: true, label: 'League strikeout and home-run rates' });
}

if (typeof BP.route === 'function') { BP.route('history', render); try { BP.route('#/history', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
