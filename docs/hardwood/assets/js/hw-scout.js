/* The Quant Hardwood — the Scouting Room (#/<L>/scout): the Players pages (leaders, the catalogue, any metric) and the
 * Lab in one page (round 9, 28 Oct 2026; the Bullpen pilot, bp-scout.js, is the reference). Kit: scout.js (QK.board,
 * QK.leaderCard, QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare, QK.scoutBar) and quant.js (QK.within,
 * QK.hotRow, QK.pctlBars).
 *
 * One control bar drives every view: "Compare within" Broad (every player) or Position (guards, wings, bigs: the spec's
 * role groups, the lab's `role`), the season, the minimum minutes (default: the season's qualified players, the
 * catalogue's minutes floor), team, age band (where the payload has ages) and search (the Board keeps the matches; the
 * Chart and the Leaders highlight them). Under the bar, "Top of the group": the leader on five of the view's metrics.
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips ("Position view" = the role's view: what makes the role
 *            good, its scoring, its value; "Our models"; every payload group), any metric added, cells on the percentile
 *            scale within the peers (lower-is-better flipped, style metrics grey), top 50 then "Show all", CSV;
 *   chart    the scatter Lab (lab.js, HW.lab.mount): presets, the role's view, colour, shrink, medians, labels, the
 *            ranked table and "Most like";
 *   leaders  small multiples: for the view's key metrics, the top five and the bottom three, over a dot strip of the
 *            whole group with the median;
 *   clutch   (round 9, Phase 4) the late-game board: the last five minutes with the margin within five (the play-by-play
 *            clutch fields of the player detail data, in lab.json): who scores, shoots, swings the win chance and lifts
 *            the team then, among players with enough clutch minutes (35% of the most played, at least 8), with the
 *            whole-game number beside it so a clutch star and a star are told apart.
 * A name anywhere opens the profile drawer (?p=<pid>): percentile meters for the view's metrics, the headline numbers,
 * "Most like", and links to the player page, Progression and Compare. Pin up to four to the compare tray
 * (?cmp=<pid>,<pid>): side by side on percentile bars; "Compare progression" opens the deep year-by-year compare.
 * Address: ?view, within=pos&pos=G|W|B, min, team, age (u23|23-26|27-30|31p), q, cols, add, sort, dir, all, p, cmp, x,
 * y, color, s. Data: data/<L>/lab.json (every player-season past half the minutes floor, column-oriented, shared with
 * the Chart; ~8 MB NBA, loaded once). Old routes (#/<L>/players, leaders, lab) redirect here (core.js scoutRedirect).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const U = () => HW.ui;
const esc = HW.esc, isNum = HW.isNum;
const FX = () => HW.fx;

/* peer groups: code -> [name, plural noun, singular] */
const GROUPS = { A: ['All players', 'players', 'player'], G: ['Guards', 'guards', 'guard'], W: ['Wings', 'wings', 'wing'], B: ['Bigs', 'bigs', 'big'] };
const SPEC_ID = { G: 'guards', W: 'wings', B: 'bigs' };
const POOL_ROLE = { G: 'G', C: 'B', F: 'W' };
const POSN = ['G', 'W', 'B'];
const AGES = [['', 'Any age'], ['u23', 'Under 23'], ['23-26', '23 to 26'], ['27-30', '27 to 30'], ['31p', '31 and over']];
const AGE_TEST = { u23: a => a < 23, '23-26': a => a >= 23 && a < 27, '27-30': a => a >= 27 && a < 31, '31p': a => a >= 31 };
/* Broad (every player, no spec view): impact first, then scoring, then the rest of the floor game */
const BROAD = [
  { key: 'excellence', label: 'Impact', ids: ['hpm', 'hpm_o', 'hpm_d', 'war', 'rapm', 'box_impact'] },
  { key: 'production', label: 'Scoring', ids: ['pts100', 'ts_add', 'ts', 'pox100', 'fta100', 'usg'] },
  { key: 'aggregate', label: 'Playmaking, defence and the glass', ids: ['ast_pct', 'ast_tov', 'tov_pct', 'stl_pct', 'blk_pct', 'trb_pct'] }
];
/* totals: a bottom three says nothing useful about playing time */
const TOTALS = /^(war|gp|min|pts|reb|ast|stl|blk|tpm|fgm|fga|ftm|fta)$/;
const FAMILY = { hpm: 'hpm', rapm: 'hpm', box_impact: 'hpm', on_off: 'hpm', ts: 'ts', efg: 'ts', ts_add: 'ts_add', pts100: 'pts', pts_g: 'pts', pts36: 'pts' };
const fam = id => FAMILY[id] || id;

const SC = { L: 'nba', S: null, view: 'board', within: 'broad', pg: 'G', min: null, team: '', age: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', color: '' };
let D = null, DK = '', TRAY = null, ROOT = null, BOARD = null;

function code() { return SC.within === 'pos' ? SC.pg : 'A'; }
function grp(c) { return GROUPS[c || code()] || GROUPS.A; }

/* lab.json -> { idx, meta, metrics, years, rows (this season): [{ id, name, team, pool, gp, min, q, role, age, a }] } */
function prep(raw, S) {
  if (!raw || raw.ok === false || !Array.isArray(raw.rows)) return null;
  const idx = {};
  (raw.fields || []).forEach((f, i) => { if (idx[f] === undefined) idx[f] = i; });
  const meta = {};
  const O = HW.ours;
  (raw.metrics || []).forEach(m => {
    const r = O && O.row ? O.row(m.key, 'player') : null;
    meta[m.key] = r ? Object.assign({}, m, { label: r[0], desc: r[6] || m.desc, lower: r[2] === 'lower' ? true : !!m.lower }) : m;
  });
  const g = (r, f) => (idx[f] === undefined ? null : r[idx[f]]);
  const rows = raw.rows.filter(r => Number(g(r, 'season')) === Number(S)).map(r => {
    const role = g(r, 'role') || POOL_ROLE[g(r, 'pool')] || 'W';
    return { id: String(g(r, 'id')), name: g(r, 'name') || '', team: g(r, 'team') === null ? '' : String(g(r, 'team')), pool: g(r, 'pool') || '', gp: g(r, 'gp') || 0, min: g(r, 'min') || 0,
      q: g(r, 'qualified') !== false, role: role, age: g(r, 'age'), a: r };
  });
  const years = (raw.years || []).slice().sort((a, b) => b - a);
  const metrics = (raw.metrics || []).filter(m => idx[m.key] !== undefined && rows.some(r => isNum(r.a[idx[m.key]]))).map(m => meta[m.key]);
  return { idx: idx, meta: meta, rows: rows, years: years, metrics: metrics };
}
function val(r, id) { const i = D.idx[id]; if (i === undefined) return null; const v = r.a[i]; return isNum(v) ? v : null; }
function has(id) { return D.idx[id] !== undefined && D.metrics.some(m => m.key === id); }

function mmeta(id) {
  const m = (D && D.meta[id]) || {};
  const ours = HW.ours ? HW.ours.of(id) : null;
  const tip = (m.desc || '') + (ours ? ((m.desc ? ' ' : '') + 'Our model: ' + ours.name + '.') : '');
  const mm = U().MSET && U().MSET.meta[id];
  return { id: id, label: m.label || (mm ? mm[0] : id), tip: tip, ours: ours ? { name: ours.name, about: ours.about } : null, lower: !!m.lower,
    style: !!(mm && mm[3]), fmt: v => FX().fmtV(v, m.fmt || '2'), group: m.group || 'Other' };
}

/* the peers: the group past the floor (the season's qualified players unless a minimum is set) */
function inGroup(r, c) { c = c || code(); return c === 'A' || r.role === c; }
function past(r) { return isNum(SC.min) ? r.min >= SC.min : r.q; }
function peers(c) { return D.rows.filter(r => inGroup(r, c) && past(r)); }
function keep(get) {
  if (SC.team && String(get('team')) !== SC.team) return false;
  if (SC.age) { const a = get('age'); if (!isNum(a) || !AGE_TEST[SC.age](a)) return false; }
  return true;
}
function rowKeep(r) { return keep(f => (f === 'team' ? r.team : f === 'age' ? r.age : val(r, f))); }
function shown() { return peers().filter(rowKeep); }
function fold(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function matches(r) { const q = fold(SC.q.trim()); return !!q && fold(r.name + ' ' + HW.teamAbbr(SC.L, r.team) + ' ' + HW.teamName(SC.L, r.team)).indexOf(q) >= 0; }

const PCT = {};
function pctOf(r, id, c) {
  c = c || code();
  const key = c + '|' + SC.min + '|' + id;
  let srt = PCT[key];
  if (!srt) srt = PCT[key] = peers(c).map(x => val(x, id)).filter(isNum).sort((a, b) => a - b);
  const v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  const p = QK.pctRank(srt, v);
  return mmeta(id).lower ? 100 - p : p;
}
function clearPct() { Object.keys(PCT).forEach(k => delete PCT[k]); }

/* the view: the spec group's Position view (ids this payload carries for 30%+ of the peers); Broad: BROAD */
function view(c) {
  c = c || code();
  const P = peers(c);
  const okId = id => has(id) && P.length > 0 && P.filter(r => isNum(val(r, id))).length >= 0.3 * P.length;
  const cat = HW.ours && HW.ours.cat ? HW.ours.cat() : null;
  const sg = c !== 'A' && cat && cat.group ? cat.group(SC.L + '_' + SPEC_ID[c]) : null;
  const v = sg && sg.view && QK.within && QK.within.view ? QK.within.view(sg, okId) : null;
  if (v) return { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(s => s.ids.length), display: sg.display || GROUPS[c][0] };
  const sets = BROAD.map(s => ({ key: s.key, label: s.label, ids: s.ids.filter(okId) })).filter(s => s.ids.length);
  return { why: '', x: 'hpm_o', y: 'hpm_d', color: has('war') ? 'war' : 'hpm', sets: sets, display: 'All players' };
}
function pickDistinct(out, ids, n) {
  let k = 0;
  ids.forEach(id => { if (k >= n || out.indexOf(id) >= 0 || out.some(x => fam(x) === fam(id))) return; out.push(id); k++; });
}
function keyMetrics(v) {
  const out = [];
  if (v.sets.length >= 3) { pickDistinct(out, v.sets[0].ids, 3); pickDistinct(out, v.sets[1].ids, 4); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(s => pickDistinct(out, s.ids, 3));
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders', 'clutch'].indexOf(q.view) >= 0 ? q.view : 'board';
  if (q.within === 'pos' && POSN.indexOf(q.pos) >= 0) { SC.within = 'pos'; SC.pg = q.pos; } else SC.within = 'broad';
  const mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team || ''; SC.age = AGE_TEST[q.age] ? q.age : '';
  SC.q = q.q || ''; SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.color = q.color || '';
}
function hashNow() {
  const q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.within === 'pos') { q.within = 'pos'; q.pos = SC.pg; }
  if (isNum(SC.min)) q.min = SC.min;
  ['team', 'age', 'q', 'cols'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['x', 'y', 'color'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.S && Number(SC.S) !== Number(HW.currentSeason(SC.L))) q.s = SC.S;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  return '#/' + SC.L + '/scout' + (qs ? '?' + qs : '');
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }

/* ── names, links ────────────────────────────────────────────────────────── */
function href(r) { return HW.playerHref(SC.L, r.id, SC.S); }
function teamOf(r) { return { abbr: HW.teamAbbr(SC.L, r.team), colour: HW.teamColourRaw(SC.L, r.team), alt: HW.teamAlt(SC.L, r.team), name: HW.teamName(SC.L, r.team) }; }
function subOf(r) { return [(U().ROLE1 || {})[r.role] || r.pool, HW.teamAbbr(SC.L, r.team), isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · '); }
function findRow(id) { return D ? D.rows.find(x => x.id === String(id)) || null : null; }
function codeOf(r) { return SC.within === 'pos' ? r.role : 'A'; }
function seasonLabel(S) { return HW.seasonLabel(SC.L, S); }

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, params) {
  SC.L = U().L(params);
  ROOT = el;
  readQuery(params.query || {});
  el.innerHTML = U().secHead('Scouting Room', 'Every player and every metric, judged against the same role: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare.', null, null, U().kicker(SC.L, U().S(params))) +
    '<div class="sc"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders'], ['clutch', 'Clutch']].map(t => '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>').join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  HW.onLeave(() => { if (QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return FX().ready().then(() => {
    const S = U().S(params);
    return Promise.all([FX().first([SC.L + '/lab.json', FX().path(SC.L, S, 'lab.json')]), HW.ours ? HW.ours.load() : null]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!U().alive(el)) return;
    const raw = o.res[0];
    const years = raw && raw.years ? raw.years.slice().sort((a, b) => b - a) : [];
    /* a season with no rows yet (before the first games): the latest season that has some, said so */
    let S = o.S;
    const hasS = s => raw && Array.isArray(raw.rows) && raw.rows.some(r => Number(r[(raw.fields || []).indexOf('season')]) === Number(s));
    SC.asked = null;
    if (raw && !hasS(S)) { const prev = years.filter(y => y < S && hasS(y))[0]; if (prev) { SC.asked = S; S = prev; } }
    SC.S = S;
    const key = SC.L + '/' + S;
    if (DK !== key) { D = prep(raw, S); DK = key; clearPct(); }
    if (!D || !D.rows.length) { document.getElementById('sc-view').innerHTML = QK.empty('Not built yet', 'The ' + HW.leagueName(SC.L) + ' ' + seasonLabel(S) + ' scouting file is not available.'); document.getElementById('sc-ctl').innerHTML = ''; return; }
    HW.setMeta(HW.leagueName(SC.L) + ' ' + seasonLabel(S) + ' · ' + D.rows.length.toLocaleString('en-GB') + ' players · ' + D.metrics.length + ' metrics each');
    controls();
    tabs();
    tray();
    refresh();
    if (SC.p) { const r = findRow(SC.p); if (r) openProfile(r.id); }
  });
}

function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  const a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || a.closest('.qk-drawer')) return;
  const m = /#\/(?:nba|wnba)\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function floorText() {
  const q = D.rows.filter(r => inGroup(r) && r.q).map(r => r.min);
  return q.length ? Math.min.apply(null, q) : 0;
}
function controls() {
  const host = document.getElementById('sc-ctl');
  if (!host) return;
  const within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', groups: POSN.map(c => [c, (view(c).display || GROUPS[c][0])]),
    note: SC.within === 'pos' ? 'Role from play style (the value model): what makes the role good, its scoring and its value' : 'Every player on one scale' });
  const teams = Array.from(new Set(D.rows.map(r => r.team).filter(Boolean))).sort((a, b) => HW.teamName(SC.L, a).localeCompare(HW.teamName(SC.L, b)));
  const opt = (v, t, cur) => '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>';
  const anyAge = D.rows.some(r => isNum(r.age));
  const mx = Math.max.apply(null, D.rows.map(r => r.min).concat([100]));
  const fl = floorText();
  const minNow = isNum(SC.min) ? SC.min : fl;
  const items = [
    { label: 'Season', html: '<select class="qk-select" id="sc-season">' + D.years.map(y => opt(y, seasonLabel(y), SC.S)).join('') + '</select>' },
    { label: 'Min minutes', html: '<span class="sc-min"><input type="range" id="sc-min" min="0" max="' + (Math.ceil(mx / 50) * 50) + '" step="25" value="' + minNow + '" aria-label="Minimum minutes"><b class="qk-sbar-v" id="sc-min-v">' + minNow + '</b></span>', cls: 'sc-minf' },
    { label: 'Team', html: '<select class="qk-select" id="sc-team">' + opt('', 'All teams', SC.team) + teams.map(t => opt(t, HW.teamName(SC.L, t), SC.team)).join('') + '</select>' },
    anyAge ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(a => opt(a[0], a[1], SC.age)).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or team…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  const v = view();
  host.innerHTML = (SC.asked ? '<p class="qk-note" style="margin:0 0 10px">No ' + esc(seasonLabel(SC.asked)) + ' games in the file yet: these are the final ' + esc(seasonLabel(SC.S)) + ' numbers.</p>' : '') +
    within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">' + esc(grp()[0]) + (isNum(SC.min) ? ' with ' + SC.min + '+ minutes (the qualified floor is ' + fl + ')' : ' who qualify: ' + fl + '+ minutes, the season’s floor (a fifth of the most played)') + '</p>' +
    QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, w => { SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos; regroup(); }, { id: 'sc-wn' });
  const $ = id => document.getElementById(id);
  $('sc-season').onchange = e => { SC.S = parseInt(e.target.value, 10); SC.p = ''; SC.min = null; location.hash = hashNow(); };
  $('sc-min').oninput = e => { $('sc-min-v').textContent = e.target.value; };
  $('sc-min').onchange = e => { SC.min = parseInt(e.target.value, 10); if (SC.min === fl) SC.min = null; clearPct(); controls(); refresh(); };
  $('sc-team').onchange = e => { SC.team = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = e => { SC.age = e.target.value; refresh(); };
  let t = null;
  $('sc-q').oninput = e => { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
function regroup() {
  SC.cols = ''; SC.x = ''; SC.y = ''; SC.color = ''; SC.sort = null;
  clearPct();
  controls();
  refresh();
}

/* ── views ───────────────────────────────────────────────────────────────── */
function tabs() {
  const bar = ROOT.querySelector('.sc-tabs');
  QK.$$('[role="tab"]', bar).forEach((b, i, all) => {
    b.addEventListener('click', () => select(b.getAttribute('data-view')));
    b.addEventListener('keydown', e => {
      const j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : null;
      if (j === null) return;
      e.preventDefault();
      const n = all[(j + all.length) % all.length]; n.focus(); select(n.getAttribute('data-view'));
    });
  });
  function select(v) {
    SC.view = v;
    QK.$$('[role="tab"]', bar).forEach(b => { const on = b.getAttribute('data-view') === v; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
    document.getElementById('sc-view').setAttribute('aria-labelledby', 'sc-tab-' + v);
    drawView();
  }
}
function refresh() {
  if (!ROOT || !ROOT.isConnected) return;
  topStrip();
  drawView();
}
function drawView() {
  writeQuery();
  const host = document.getElementById('sc-view');
  if (!host) return;
  BOARD = null;
  if (SC.view === 'chart') return chartView(host);
  if (SC.view === 'leaders') return leadersView(host);
  if (SC.view === 'clutch') return clutchView(host);
  return boardView(host);
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

function topStrip() {
  const host = document.getElementById('sc-top');
  if (!host) return;
  const v = view(), rows = shown(), g = grp();
  const ids = [];
  if (v.sets.length >= 3) { pickDistinct(ids, v.sets[0].ids, 2); pickDistinct(ids, v.sets[1].ids, 2); pickDistinct(ids, v.sets[2].ids, 1); }
  else v.sets.forEach(s => pickDistinct(ids, s.ids, 2));
  const items = ids.slice(0, 5).map(id => {
    const m = mmeta(id), list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
    if (!list.length) return null;
    const r = list[0], nx = list[1];
    return { sport: 'basketball', kicker: m.label, name: r.name, value: m.fmt(val(r, id)), title: HW.teamAbbr(SC.L, r.team) + ' · ' + ((U().ROLE1 || {})[r.role] || ''), next: nx ? { name: nx.name, value: m.fmt(val(nx, id)) } : null,
      expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + g[1], title: SC.within === 'pos' ? 'The best ' + g[1] + ', on what matters there' : 'The best players right now', sub: 'The leader on five of the ' + (SC.within === 'pos' ? 'role' : 'group') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}

function boardView(host) {
  const v = view(), g = grp();
  const all = shown();
  const rows = SC.q.trim() ? all.filter(matches) : all;
  const P = peers();
  const sets = [{ key: 'view', label: SC.within === 'pos' ? 'Position view' : 'Headline', groups: v.sets.map(s => ({ label: s.label, ids: s.ids })) }];
  const oursIds = D.metrics.filter(m => HW.ours && HW.ours.of(m.key)).map(m => m.key);
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  const gnames = [];
  D.metrics.forEach(m => { if (gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(gn => sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: D.metrics.filter(m => (m.group || 'Other') === gn).map(m => m.key) }] }));
  const setKey = sets.some(s => s.key === SC.cols) ? SC.cols : 'view';
  const ag = v.sets.length >= 3 ? v.sets[2].ids : [];
  const defSort = v.color || ag[0] || (v.sets[0] || { ids: [] }).ids[0];
  const LEAD = ['name', 'gp', 'min', 'age'];
  let sort = SC.sort && SC.sort.key && (LEAD.indexOf(SC.sort.key) >= 0 || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: LEAD.indexOf(sort.key) < 0 && mmeta(sort.key).lower ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  const groups = HW.ours ? HW.ours.groups(D.metrics) : [{ name: 'Metrics', items: D.metrics }];
  const addable = groups.map(gr => '<optgroup label="' + esc(gr.name) + '">' + gr.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    esc(g[0]) + ' · ' + esc(seasonLabel(SC.S)) + ' · cells on the percentile scale against the ' + P.length + ' ' + esc(g[1]) + ' past the floor (blue worst, red best). Tap a name for the profile; + pins to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>' +
    (HW.ours ? HW.ours.explain([].concat.apply([], v.sets.map(s => s.ids)).filter(id => HW.ours.of(id)).slice(0, 2), { label: id => mmeta(id).label }) : '');
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', sets: sets, set: setKey, added: SC.add.filter(id => has(id)), sort: sort, all: SC.all, page: 50, noun: g[1],
    nameLabel: 'Player', subLabel: 'Role · team · age',
    meta: id => mmeta(id),
    addable: addable,
    lead: [{ key: 'gp', label: 'GP', tip: 'Games played', fmt: row => String(row._r.gp), val: row => row._r.gp },
      { key: 'min', label: 'Min', tip: 'Minutes played', fmt: row => Number(Math.round(row._r.min)).toLocaleString('en-GB'), val: row => row._r.min },
      { key: 'age', label: 'Age', fmt: row => (isNum(row._r.age) ? String(Math.floor(row._r.age)) : '—'), val: row => row._r.age }],
    rows: rows.map(r => ({ id: r.id, name: r.name, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r })),
    val: (row, id) => val(row._r, id),
    peers: P.map(r => ({ id: r.id, _r: r })),
    hl: row => SC.cmp.indexOf(row.id) >= 0,
    pin: { has: id => !!TRAY && TRAY.has(id), toggle: row => pin(row._r), label: 'Pin to the compare tray' },
    onPick: row => openProfile(row.id),
    onState: st => { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'hardwood-' + SC.L + '-' + SC.S + '-' + code().toLowerCase() + '-' + String(setKey || 'view').toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.csv',
    empty: SC.q.trim() ? 'No ' + g[1] + ' match “' + SC.q.trim() + '” with these filters.' : 'No ' + g[1] + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(g[2]) + ' past the floor, whatever the team or age filters show; a ↓ marks a metric where lower is better (its colours are flipped) and grey cells are style (neither better nor worse). Every metric in the file is a chip or “Add a metric” away.'
  });
}

function chartView(host) {
  if (!HW.lab || !HW.lab.mount) { host.innerHTML = QK.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  HW.lab.mount(document.getElementById('sc-chart'), SC.L, SC.S, {
    within: SC.within, role: SC.pg, min: isNum(SC.min) ? SC.min : null, q: SC.q, x: SC.x, y: SC.y, color: SC.color,
    keep: keep,
    onPick: id => openProfile(id),
    onAxes: ax => { SC.x = ax.x || ''; SC.y = ax.y || ''; SC.color = ax.color && ax.color !== 'team' ? ax.color : ''; writeQuery(); }
  });
}

function leadersView(host) {
  const v = view(), rows = shown(), g = grp(), P = peers();
  const ids = keyMetrics(v);
  const hl = r => matches(r) || r.id === SC.p;
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + g[0], title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + g[1] + ' on screen on the ' + (SC.within === 'pos' ? 'role' : 'group') + '’s key metrics. Bars are percentiles against the ' + P.length + ' past the floor; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map((id, i) => {
      const m = mmeta(id);
      const list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
      if (!list.length) return '';
      const item = (r, rk) => { const p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      const top = list.slice(0, 5).map((r, j) => item(r, j + 1));
      const bottom = !TOTALS.test(id) && list.length > 10 ? list.slice(-3).map((r, j) => item(r, list.length - 2 + j)) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + g[1], top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach((id, i) => {
    const el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    const m = mmeta(id);
    const vals = rows.filter(r => isNum(val(r, id))).map(r => ({ v: val(r, id), name: r.name + ' · ' + HW.teamAbbr(SC.L, r.team), id: r.id, hl: hl(r) }));
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + g[2] + ' on ' + m.label, onClick: d => openProfile(d.id) });
  });
}

/* Clutch: the last five minutes, margin within five (lab.json clutch_* from the play-by-play) */
const CLUTCH = [['clutch_wpa', 'wpa', 'Clutch win probability added', 'How much the player moved the team’s win chance in clutch time, in wins'],
  ['clutch_pts', 'pts_g', 'Clutch points', 'Points scored in clutch time this season'],
  ['clutch_ts', 'ts', 'Clutch true shooting', 'Points per shot in clutch time, threes and free throws counted'],
  ['clutch_net', 'hpm', 'Clutch on-floor net rating', 'The team’s points per 100 possessions better than its opponents with the player on in clutch time (noisy: few possessions)']];
function clutchView(host) {
  const g = grp();
  if (!has('clutch_min')) { host.innerHTML = QK.empty('No clutch numbers', 'Clutch time needs play-by-play, which starts about 2017.'); return; }
  const base = D.rows.filter(r => inGroup(r) && rowKeep(r) && isNum(val(r, 'clutch_min')));
  const mx = Math.max.apply(null, base.map(r => val(r, 'clutch_min')).concat([0]));
  const fl = Math.max(8, Math.round(0.35 * mx));
  const rows = base.filter(r => val(r, 'clutch_min') >= fl);
  if (rows.length < 5) { host.innerHTML = QK.empty('Too early for clutch time', 'Fewer than five ' + g[1] + ' have ' + fl + '+ clutch minutes yet.'); return; }
  const hl = r => matches(r) || r.id === SC.p;
  const ids = CLUTCH.filter(c => has(c[0]));
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Clutch · ' + g[0], title: 'Who delivers late', sub: 'Clutch time is the last five minutes of the fourth quarter or overtime with the margin within five. ' + rows.length + ' ' + g[1] + ' with ' + fl + '+ clutch minutes this season (35% of the most played). Beside each clutch number, the same player’s whole-game number: a clutch star stands out in the first, not only in the second.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map((c, i) => {
      const m = mmeta(c[0]), mw = has(c[1]) ? mmeta(c[1]) : null;
      const list = rows.filter(r => isNum(val(r, c[0]))).sort((a, b) => val(b, c[0]) - val(a, c[0]));
      const srt = list.map(r => val(r, c[0])).sort((a, b) => a - b);
      const item = (r, rk) => { const p = QK.pctRank(srt, val(r, c[0])); return { id: r.id, rank: rk, name: r.name, sub: HW.teamAbbr(SC.L, r.team) + (mw && isNum(val(r, c[1])) ? ' · all game ' + mw.fmt(val(r, c[1])) : ''), href: href(r), text: m.fmt(val(r, c[0])), w: p, pctl: p, mark: teamOf(r) }; };
      return QK.leaderCard({ title: c[2], tip: c[3], count: list.length + ' ' + g[1], top: list.slice(0, 5).map((r, j) => item(r, j + 1)), bottom: c[0] === 'clutch_pts' ? [] : list.slice(-3).map((r, j) => item(r, list.length - 2 + j)), bottomLabel: 'At the bottom', stripId: 'sc-cl-' + i });
    }).join('') + '</div>' +
    QK.explain('Clutch samples are small: a player sees about 2 to 4 clutch minutes in a close game and none in a blow-out, so a season is a few hundred possessions at most. Read the leaders as who has been trusted and delivered so far, not as a skill that repeats; the whole-game numbers are the better guide to next season.', { title: 'How sure are we?' });
  ids.forEach((c, i) => {
    const el = document.getElementById('sc-cl-' + i);
    if (!el) return;
    const m = mmeta(c[0]);
    QKC.strip(el, { values: rows.filter(r => isNum(val(r, c[0]))).map(r => ({ v: val(r, c[0]), name: r.name + ' · ' + HW.teamAbbr(SC.L, r.team), id: r.id, hl: hl(r) })), xName: c[2], fmt: m.fmt, label: 'Every ' + g[2] + ' on ' + c[2], onClick: d => openProfile(d.id) });
  });
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id) {
  const r = findRow(id);
  if (!r) return;
  SC.p = r.id; writeQuery();
  const c = inGroup(r) ? code() : codeOf(r);
  const g = grp(c), v = view(c), P = peers(c);
  const row = id2 => { const m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2, c), value: m.fmt(x), tip: m.tip, style: m.style }; };
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(row).filter(Boolean) }));
  const t = teamOf(r);
  const statIds = [v.color, v.y, v.x].filter((x, i, a) => x && a.indexOf(x) === i);
  const stats = statIds.map(id2 => { const m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2, c), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Minutes', value: Number(Math.round(r.min)).toLocaleString('en-GB'), sub: r.gp + ' games' });
  const simKeys = [];
  if (v.sets.length >= 3) [4, 4, 2].forEach((n, i) => v.sets[i].ids.filter(x => simKeys.indexOf(x) < 0).slice(0, n).forEach(x => simKeys.push(x)));
  else v.sets.forEach(s => s.ids.slice(0, 3).forEach(x => { if (simKeys.indexOf(x) < 0) simKeys.push(x); }));
  const pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  const near = QK.within.similar(pool, r, simKeys, (rr, key) => val(rr, key), 5);
  const base = href(r), sep = base.indexOf('?') >= 0 ? '&' : '?';
  const cmpH = near.length ? '#/' + SC.L + '/compare/players/' + encodeURIComponent(r.id) + '/' + encodeURIComponent(near[0].row.id) + (Number(SC.S) !== Number(HW.currentSeason(SC.L)) ? '?s=' + SC.S : '') : '#/' + SC.L + '/compare';
  const inPeers = P.indexOf(r) >= 0;
  const html = QK.profile({
    kicker: ((U().ROLE1 || {})[r.role] || r.pool) + ' · ' + (t.name || t.abbr),
    name: r.name, href: base,
    sub: [isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', r.gp + ' games', Number(Math.round(r.min)).toLocaleString('en-GB') + ' min', seasonLabel(SC.S)].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: g[1] + ' past the floor' + (inPeers ? '' : ' (this player is under it: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + QK.surname(r.name) + ' · ' + g[1], items: near.map(o => ({ name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) })) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: base }, { label: 'Progression', href: base + sep + 'tab=progression' }, { label: near.length ? 'Compare with ' + QK.surname(near[0].row.name) : 'Compare', href: cmpH }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(g[1]) + ' past the floor in ' + esc(seasonLabel(SC.S)) + '. “Most like” is the nearest five on the ' + (SC.within === 'pos' ? 'role view’s' : 'group’s') + ' metrics.'
  });
  const inner = QK.drawer.open({ html: html, label: r.name + ': profile', onClose: () => { SC.p = ''; writeQuery(); } });
  const pb = inner.querySelector('#sc-pf-pin');
  if (pb) pb.addEventListener('click', () => { pin(r); openProfile(r.id); });
  QK.$$('[data-pick]', inner).forEach(a => a.addEventListener('click', ev => {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'));
  }));
}

/* ── the compare tray ───────────────────────────────────────────────────── */
function pin(r) {
  if (!TRAY) return;
  TRAY.toggle(r.id);
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(b => { const on = TRAY.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  const sq = Number(SC.S) !== Number(HW.currentSeason(SC.L)) ? 's=' + SC.S : '';
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(id => findRow(id)), label: 'Compare tray',
    item: id => { const r = findRow(id); return r ? { name: r.name, short: QK.surname(r.name), sub: ((U().ROLE1 || {})[r.role] || '') + ' · ' + HW.teamAbbr(SC.L, r.team), colour: teamOf(r).colour } : { name: id }; },
    onChange: ids => { SC.cmp = ids; writeQuery(); },
    href: ids => '#/' + SC.L + '/compare/players/' + ids.map(encodeURIComponent).join('/') + (sq ? '?' + sq : ''),
    hrefLabel: 'Full compare',
    body: ids => trayBody(ids)
  });
}
function trayBody(ids) {
  const rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  const codes = rs.map(codeOf);
  const v = view(codes[0]);
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(id => {
    const m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map((r, i) => { const x = val(r, id); return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id, codes[i]) : null }; }) };
  }) }));
  /* compare progression: the deep year-by-year compare (hw-progression.js) for the players in the tray */
  const prog = '#/' + SC.L + '/compare/progression/' + rs.map(r => encodeURIComponent(r.id)).join('/');
  return QK.trayCompare({ entities: rs.map(r => { const t = teamOf(r); return { name: r.name, short: QK.surname(r.name), sub: ((U().ROLE1 || {})[r.role] || '') + ' · ' + t.abbr + ' · ' + Number(Math.round(r.min)).toLocaleString('en-GB') + ' min', colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own ' + (SC.within === 'pos' ? 'role' : 'group') + '’s peers past the floor (' + esc(seasonLabel(SC.S)) + '). The volt underline marks the best of the ' + rs.length + ' on each row. <a class="qk-link" href="' + esc(prog) + '">Compare progression, season by season →</a>' });
}

HW.page('scout', render);
HW.scout = { view: view, mmeta: mmeta };
})(window.HW);
