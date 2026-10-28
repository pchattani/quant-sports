/* The Quant Gridiron — the Scouting Room (#/scout): the Players, Leaders and Lab pages in one page built for quick
 * analysis (round 9, 28 Oct 2026; the Bullpen's bp-scout.js is the reference). Kit: scout.js (QK.board, QK.leaderCard,
 * QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare, QK.scoutBar) and quant.js (QK.within, QK.hotRow).
 *
 * One control bar drives every view: "Compare within" Broad (quarterbacks, running backs, wide receivers, tight ends,
 * every defender together, kickers, punters) or Position (the metrics spec's peer groups: QB, RB, WR, TE, outside pass
 * rushers, interior linemen, linebackers, cornerbacks, safeties, K, P; the defenders split by our value model's role),
 * the season, the minimum sample (qualified players by default: the payload's floor; or a plays slider), team, age band
 * and search (the Board keeps the matches; the Chart and the Leaders highlight them). NFL has no handedness in the data.
 * Under the bar, "Top of the group": the leader on five of the view's metrics.
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips ("Position view" = the spec view's excellence, production and
 *            value metrics; "Our models"; every payload group), any metric added, cells on the percentile scale within
 *            the peers (lower-is-better flipped, style metrics grey), the top 50 then "Show all", "Download CSV";
 *   chart    the scatter Lab (lab.js, GI.lab.mount): presets, the Position view's axes, colour, shrink, medians, corners,
 *            the ranked table and "Most like";
 *   leaders  small multiples: the view's key metrics, the top five and the bottom three as bars, over a dot strip of
 *            the whole group with the median;
 *   alltime  (round 9, phase 2) the single-season and career boards since 1999 (history.js, GI.history.mount).
 * Selecting a player anywhere (a name, a dot, a card) opens the profile drawer (?p=<pid>): percentile meters for the
 * view's metrics, a line of headline numbers, "Most like", and links to the player page, progression and Compare. Pin up
 * to four (the + on a row, or "Pin" in the drawer) to the compare tray (?cmp=<pid>,<pid>).
 * Address: ?view, kind (QB|RB|WR|TE|DEF|K|P), within=pos&pos=<code>, min, team, age (u25|25-28|29-32|33p), q, cols,
 * add, sort, dir, all, p, cmp, x, y, color, s. Data: <S>/lab.json and <S>/value.json (Gridiron Value and the defensive
 * roles), read through GI.lab.prep so the Chart and the Board agree. Old routes (#/players, #/leaders, #/lab) redirect
 * here (core.js). Older-browser rule: no optional chaining, no nullish coalescing. */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;

/* code -> [lab group, spec group id, name, plural noun, singular] */
const GROUPS = {
  QB: ['QB', 'qb', 'Quarterbacks', 'quarterbacks', 'quarterback'],
  RB: ['RB', 'rb', 'Running backs', 'running backs', 'running back'],
  WR: ['WR', 'wr', 'Wide receivers', 'wide receivers', 'wide receiver'],
  TE: ['TE', 'te', 'Tight ends', 'tight ends', 'tight end'],
  DEF: ['DEF', null, 'Defenders', 'defenders', 'defender'],
  K: ['K', 'k', 'Kickers', 'kickers', 'kicker'],
  P: ['P', 'p', 'Punters', 'punters', 'punter'],
  EDGE: ['DEF', 'edge', 'Outside pass rushers', 'outside pass rushers', 'outside pass rusher'],
  DL: ['DEF', 'idl', 'Interior linemen', 'interior linemen', 'interior lineman'],
  LB: ['DEF', 'lb', 'Linebackers', 'linebackers', 'linebacker'],
  CB: ['DEF', 'cb', 'Cornerbacks', 'cornerbacks', 'cornerback'],
  S: ['DEF', 's', 'Safeties', 'safeties', 'safety']
};
const BROAD = ['QB', 'RB', 'WR', 'TE', 'DEF', 'K', 'P'];
const POSN = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P'];
const ROLE_CODE = { edge: 'EDGE', idl: 'DL', lb: 'LB', cb: 'CB', s: 'S' };
const AGES = [['', 'Any age'], ['u25', 'Under 25'], ['25-28', '25 to 28'], ['29-32', '29 to 32'], ['33p', '33 and over']];
const AGE_TEST = { u25: a => a < 25, '25-28': a => a >= 25 && a < 29, '29-32': a => a >= 29 && a < 33, '33p': a => a >= 33 };
/* season totals: a bottom three says nothing useful about playing time */
const TOTALS = /^(games|att|pass_yds|pass_td|ints|carries|rush_yds|rush_td|targets|rec|rec_yds|rec_td|rec_epa|epa_total|tackles|sacks|qb_hits|tfl|pd|ff|fga|fgm|fg_50|punts|value|gvar|def_value|pts_oe|fg_oe)$/;
/* one metric per family on the quick reads */
const FAMILY = { gvar: 'gvar_pg', value: 'gvar_pg', def_value: 'gvar_pg', composite_epa: 'composite', epa_play: 'epa_db', anya: 'epa_db', sacks: 'pressures_pg', qb_hits: 'pressures_pg', sacks_pg: 'pressures_pg',
  tackles: 'tackles_pg', tfl: 'tfl_pg', pd: 'pd_pg', ints: 'ints_pg', rush_epa: 'ryoe', rec_epa: 'rec_epa_tgt' };
const fam = id => FAMILY[id] || id;

/* ── state ───────────────────────────────────────────────────────────────── */
const SC = { S: null, view: 'board', within: 'broad', bg: 'QB', pg: 'QB', min: null, team: '', age: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', color: '' };
let D = null, DK = '', TRAY = null, ROOT = null, BOARD = null;
const VIEWS = [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders'], ['alltime', 'All-time']];

function code() { return SC.within === 'pos' ? SC.pg : SC.bg; }
function grp(c) { return GROUPS[c || code()] || GROUPS.QB; }
function kind(c) { return grp(c)[0]; }
function KD(k) { return (D || {})[k || kind()] || { idx: {}, meta: {}, metrics: [], rows: [], nKey: 'games', nLabel: 'Games', R: [] }; }
function nLabel(c) { return KD(kind(c)).nLabel || 'Games'; }

/* lab.json via GI.lab.prep -> per lab group { idx, meta, metrics, rows (arrays), nKey, nLabel }; R = row objects */
function prepRows(kinds) {
  Object.keys(kinds).forEach(k => {
    if (k === 'TEAM') return;
    const g = kinds[k], ix = g.idx;
    const get = (r, f) => (ix[f] === undefined ? null : r[ix[f]]);
    g.R = g.rows.map(r => ({ id: String(get(r, 'pid')), name: get(r, 'name') || GI.playerName(get(r, 'pid')), team: get(r, 'team') || '', pos: get(r, 'pos') || '', age: get(r, 'age'),
      n: isNum(get(r, g.nKey)) ? Number(get(r, g.nKey)) : 0, games: get(r, 'games'), qualified: get(r, 'qualified'), grp: get(r, '_grp'), a: r, kind: k }));
  });
  return kinds;
}
function val(r, id) { const g = KD(r.kind), i = g.idx[id]; if (i === undefined) return null; const v = r.a[i]; return isNum(v) ? Number(v) : null; }
function has(id, k) { return KD(k).idx[id] !== undefined; }

/* metric display: the spec's name and explanation, the our-model tag, direction, style, the payload's format */
function mmeta(id, k) {
  const m = KD(k || kind()).meta[id] || {};
  const cat = QK.spec && QK.spec.get ? QK.spec.get('nfl') : null, sm = cat ? cat.metric(id, 'player') : null;
  const label = GI.SP.specLabel(id, m.label || id);
  const ours = GI.SP.ours(id);
  /* the peer group's own words first (value per game reads "a replacement outside pass rusher", not "back") */
  const sgm = (k || kind()) === kind() ? ((GI.SP.BY[grp()[1]] || { m: [] }).m.filter(x => x[0] === id)[0] || null) : null;
  const tip = String((sgm && sgm[5]) || (sm && sm.explain) || GI.cleanDesc(m.desc || '')).replace(/\s*\((?:[a-z_]+\.json|leaderboards)\)/g, '').replace(/\s*Our model:.*$/, '');
  return { id: id, label: label, short: String(m.label || label).length < label.length ? String(m.label) : label, tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''),
    ours: ours, lower: !!m.lower, style: !!(sm && sm.style), fmt: v => GI.fmtVal(v, m.fmt), group: m.group || 'Other' };
}

/* the group, the floor, the filters */
function inGroup(r, c) { const g = grp(c); return r.kind === g[0] && (!g[1] || g[0] !== 'DEF' || r.grp === g[1]); }
/* the default floor: the payload's own qualification (the spec minimum); the slider value it implies is the smallest
   sample among the qualified, for the label */
function qualFloor(c) { const ns = KD(kind(c)).R.filter(r => inGroup(r, c) && r.qualified !== false && r.qualified !== null).map(r => r.n).filter(isNum); return ns.length ? Math.min.apply(null, ns) : 0; }
function peers(c) {
  c = c || code();
  const own = c === code() && isNum(SC.min);
  return KD(kind(c)).R.filter(r => inGroup(r, c) && (own ? r.n >= SC.min : r.qualified !== false));
}
function rowKeep(r) {
  if (SC.team && GI.canonTeam(r.team) !== SC.team) return false;
  if (SC.age) { if (!isNum(r.age) || !AGE_TEST[SC.age](r.age)) return false; }
  return true;
}
function keepGet(get) { return rowKeep({ team: get('team') || '', age: get('age') }); }
function shown() { return peers().filter(rowKeep); }
function matches(r) { const q = GI.fold(SC.q.trim()); return !!q && GI.fold(r.name + ' ' + GI.teamAbbr(r.team)).indexOf(q) >= 0; }

const PCT = {};
function pctOf(r, id, c) {
  c = c || code();
  const key = c + '|' + SC.min + '|' + id;
  let srt = PCT[key];
  if (!srt) srt = PCT[key] = peers(c).map(x => val(x, id)).filter(isNum).sort((a, b) => a - b);
  const v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  const p = QK.pctRank(srt, v);
  return mmeta(id, kind(c)).lower ? 100 - p : p;
}
function clearPct() { Object.keys(PCT).forEach(k => delete PCT[k]); }

/* the view: the spec group's Position view (excellence, production, value) with ids this payload carries for 30%+ of the
   peers; Broad defenders (no single spec group) take value, pass rush, and run and coverage */
const DEF_SETS = [['excellence', 'Value', ['gvar_pg', 'def_value', 'splash_pg']], ['production', 'Pass rush', ['pressures_pg', 'sacks_pg', 'sacks', 'qb_hits']], ['aggregate', 'Run and coverage', ['tfl_pg', 'tackles_pg', 'pd_pg', 'ints_pg', 'ff_pg']]];
const VC = {};
function view(c) {
  c = c || code();
  const vk = SC.S + '|' + c + '|' + SC.min;
  if (VC[vk]) return VC[vk];
  const g = grp(c), P = peers(c), k = g[0];
  const okId = id => has(id, k) && P.length > 0 && P.filter(r => isNum(val(r, id))).length >= 0.3 * P.length;
  const cat = QK.spec && QK.spec.get ? QK.spec.get('nfl') : null;
  const sg = cat && g[1] ? cat.group(g[1]) : null;
  const v = sg && sg.view ? QK.within.view(sg, okId) : null;
  let out;
  if (v) out = { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(s => s.ids.length).map(s => ({ key: s.key, label: s.label, ids: s.ids })) };
  else {
    const sets = DEF_SETS.map(s => ({ key: s[0], label: s[1], ids: s[2].filter(okId) })).filter(s => s.ids.length);
    out = { why: '', x: (sets[1] || sets[0] || { ids: [] }).ids[0], y: (sets[0] || { ids: [] }).ids[0], color: (sets[0] || { ids: [] }).ids[0] || null, sets: sets };
  }
  VC[vk] = out;
  return out;
}
function clearView() { Object.keys(VC).forEach(k => delete VC[k]); }
function pickDistinct(out, ids, n) { let k = 0; ids.forEach(id => { if (k >= n || out.indexOf(id) >= 0 || out.some(x => fam(x) === fam(id))) return; out.push(id); k++; }); }
function keyMetrics(v) {
  const out = [];
  if (v.sets.length === 3) { pickDistinct(out, v.sets[0].ids, 3); pickDistinct(out, v.sets[1].ids, 4); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(s => pickDistinct(out, s.ids, 3));
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = VIEWS.some(v => v[0] === q.view) ? q.view : 'board';
  const kq = String(q.kind || '').toUpperCase();
  if (q.within === 'pos' && POSN.indexOf(q.pos) >= 0) { SC.within = 'pos'; SC.pg = q.pos; }
  else { SC.within = 'broad'; SC.bg = BROAD.indexOf(kq) >= 0 ? kq : 'QB'; }
  const mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team ? GI.canonTeam(q.team) : ''; SC.age = AGE_TEST[q.age] ? q.age : '';
  SC.q = q.q || ''; SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.color = q.color || '';
}
function hashNow() {
  const q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.within === 'pos') { q.within = 'pos'; q.pos = SC.pg; } else if (SC.bg !== 'QB') q.kind = SC.bg;
  if (isNum(SC.min)) q.min = SC.min;
  ['team', 'age', 'q', 'cols'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['x', 'y', 'color'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.S && SC.S !== GI.currentSeason()) q.s = SC.S;
  return '#/scout' + GI.qs(q);
}
function writeQuery() { GI.setHashQuiet(hashNow()); }

/* ── names, links, colours ──────────────────────────────────────────────── */
function href(r) { return GI.playerHref(r.id, SC.S); }
function progHref(r) { const h = href(r); return h + (h.indexOf('?') >= 0 ? '&' : '?') + 'view=progression'; }
function teamOf(r) { const t = GI.teamInfo(r.team); return { abbr: GI.teamAbbr(r.team), colour: t.colour || '', alt: t.alt || '', name: t.name || '' }; }
function posLabel(r) { if (r.kind === 'DEF' && r.grp && ROLE_CODE[r.grp]) return GI.posLabel(ROLE_CODE[r.grp] === 'DL' ? 'IDL' : ROLE_CODE[r.grp]); return GI.posLabel(r.pos || r.kind); }
function subOf(r) { return [posLabel(r), GI.teamAbbr(r.team), isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · '); }
function findRow(id) {
  const ks = [kind()].concat(Object.keys(D || {}).filter(k => k !== kind() && k !== 'TEAM'));
  for (let i = 0; i < ks.length; i++) { const r = KD(ks[i]).R.find(x => x.id === String(id)); if (r) return r; }
  return null;
}
/* the group a row belongs to in the current mode (Position: its own; Broad: its lab group) */
function codeOf(r) {
  if (SC.within !== 'pos') return r.kind;
  if (r.kind !== 'DEF') return r.kind;
  return ROLE_CODE[r.grp] || 'EDGE';
}
function seasonsList() { return GI.seasons().filter(y => y >= 1999); }

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, params) {
  SC.S = Number(params.season) || GI.currentSeason();
  ROOT = el;
  readQuery(params.query || {});
  el.innerHTML = GI.pageHead('Scouting Room · ' + SC.S, 'The Scouting Room', 'Every player, every metric, one control bar: the board, a chart, the leaders and the all-time lists. Tap a name for the profile; + pins to the compare tray.') +
    GI.sectionNav('scout', 'scout') +
    '<div class="sc"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    VIEWS.map(t => '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>').join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  GI.onLeave(() => { if (QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return GI.lab.load(SC.S).then(all => {
    if (!el.isConnected) return;
    const key = String(SC.S);
    if (DK !== key) { D = prepRows(GI.lab.prep(all[0], all[1])); DK = key; clearPct(); clearView(); }
    const any = BROAD.some(c => KD(GROUPS[c][0]).R.length);
    if (!any) { GI.set('sc-view', GI.notBuilt('The ' + SC.S + ' scouting file', all[0])); GI.set('sc-ctl', ''); return; }
    if (!KD().R.length) { SC.within = 'broad'; SC.bg = BROAD.filter(c => KD(GROUPS[c][0]).R.length)[0]; }
    controls();
    tabs();
    tray();
    refresh();
    if (SC.p) { const r = findRow(SC.p); if (r) openProfile(r.id); }
  });
}

/* a click on a player link anywhere in the room opens the drawer (a modified click follows the link) */
function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  const a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || (a.closest && a.closest('.qk-drawer'))) return;
  const m = /#\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  const host = document.getElementById('sc-ctl');
  if (!host) return;
  const avail = c => KD(GROUPS[c][0]).R.some(r => inGroup(r, c));
  const fl = qualFloor(), mx = Math.max.apply(null, KD().R.filter(r => inGroup(r)).map(r => r.n || 0).concat([20]));
  const nl = nLabel().toLowerCase();
  const broadSeg = GI.seg('sc-kind', BROAD.filter(avail).map(c => [c, c === 'DEF' ? 'Defenders' : c]), SC.bg, 'Group');
  const within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', groups: [{ group: 'Offence', items: ['QB', 'RB', 'WR', 'TE'].filter(avail).map(c => [c, GROUPS[c][2]]) },
    { group: 'Defence (by our value model’s role)', items: ['EDGE', 'DL', 'LB', 'CB', 'S'].filter(avail).map(c => [c, GROUPS[c][2]]) }, { group: 'Specialists', items: ['K', 'P'].filter(avail).map(c => [c, GROUPS[c][2]]) }],
    note: SC.within === 'pos' ? '' : broadSeg });
  const teams = Array.from(new Set(KD().R.map(r => GI.canonTeam(r.team)).filter(Boolean))).sort((a, b) => GI.teamName(a).localeCompare(GI.teamName(b)));
  const opt = (v, t, cur) => '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>';
  const cur = isNum(SC.min) ? SC.min : fl;
  const items = [
    { label: 'Season', html: '<select class="qk-select" id="sc-season">' + seasonsList().map(y => opt(y, y, SC.S)).join('') + '</select>' },
    { label: 'Min ' + nl, html: '<span class="sc-min"><input type="range" id="sc-min" min="0" max="' + (Math.ceil(mx / 10) * 10) + '" step="1" value="' + cur + '" aria-label="Minimum ' + esc(nl) + '"><b class="qk-sbar-v" id="sc-min-v">' + (isNum(SC.min) ? SC.min : 'Qualified') + '</b></span>', cls: 'sc-minf' },
    { label: 'Team', html: '<select class="qk-select" id="sc-team">' + opt('', 'All teams', SC.team) + teams.map(t => opt(t, GI.teamName(t), SC.team)).join('') + '</select>' },
    KD().R.some(r => isNum(r.age)) ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(a => opt(a[0], a[1], SC.age)).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or team…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  const v = view();
  const sg = GI.SP.BY[grp()[1]];
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">' + esc(grp()[2]) + (isNum(SC.min) ? ' with ' + SC.min + '+ ' + esc(nl) + ' (the qualified floor is ' + fl + '+)' : ', qualified: the metrics spec’s floor' + (sg ? ' (' + esc(GI.SP.minLine(sg)) + ')' : '') + ', ' + fl + '+ ' + esc(nl) + ' so far') +
    (GI.SP.NOTE[grp()[1]] ? ' · ' + esc(GI.SP.NOTE[grp()[1]]) : '') + '</p>' + QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, w => {
    if (w.within === 'pos' && SC.within !== 'pos') w.pos = SC.bg === 'DEF' ? 'EDGE' : (POSN.indexOf(SC.bg) >= 0 ? SC.bg : 'QB');
    if (w.within !== 'pos' && SC.within === 'pos') SC.bg = GROUPS[SC.pg][0];
    const k0 = kind();
    SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos;
    regroup(k0);
  }, { id: 'sc-wn' });
  GI.wireSeg(host, 'sc-kind', x => { if (!GROUPS[x]) return; const k0 = kind(); SC.bg = x; regroup(k0); });
  const $ = id => document.getElementById(id);
  $('sc-season').onchange = e => { SC.S = parseInt(e.target.value, 10); SC.p = ''; SC.min = null; SC.cmp = []; GI.go(hashNow()); };
  $('sc-min').oninput = e => { $('sc-min-v').textContent = e.target.value; };
  $('sc-min').onchange = e => { SC.min = parseInt(e.target.value, 10); clearPct(); clearView(); controls(); refresh(); };
  $('sc-team').onchange = e => { SC.team = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = e => { SC.age = e.target.value; refresh(); };
  let t = null;
  $('sc-q').oninput = e => { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
/* a new group: the minimum goes back to the floor, the column set, the sort and the chart's axes reset (each group has
   its own view); a new lab group also drops the added metrics (they name another group's metrics) */
function regroup(k0) {
  SC.min = null; SC.cols = ''; SC.x = ''; SC.y = ''; SC.color = ''; SC.sort = null;
  if (kind() !== k0) SC.add = [];
  clearPct(); clearView();
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
    refresh();
  }
}
function refresh() {
  if (!ROOT || !ROOT.isConnected) return;
  const top = document.getElementById('sc-top');
  if (SC.view === 'alltime') { if (top) top.innerHTML = ''; } else topStrip();
  drawView();
}
function drawView() {
  writeQuery();
  const host = document.getElementById('sc-view');
  if (!host) return;
  BOARD = null;
  if (SC.view === 'chart') return chartView(host);
  if (SC.view === 'leaders') return leadersView(host);
  if (SC.view === 'alltime') return alltimeView(host);
  return boardView(host);
}

/* "Top of the group": the leader on five of the view's metrics among the players on screen */
function topStrip() {
  const host = document.getElementById('sc-top');
  if (!host) return;
  const v = view(), rows = shown(), g = grp();
  const ids = [];
  if (v.sets.length === 3) { pickDistinct(ids, v.sets[0].ids, 2); pickDistinct(ids, v.sets[1].ids, 2); pickDistinct(ids, v.sets[2].ids, 1); }
  else v.sets.forEach(s => pickDistinct(ids, s.ids, 2));
  const items = ids.slice(0, 5).map(id => {
    const m = mmeta(id);
    if (m.style) return null;
    const list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
    if (!list.length) return null;
    const r = list[0], nx = list[1];
    return { sport: 'nfl', kicker: m.label, name: r.name, value: m.fmt(val(r, id)), title: GI.teamAbbr(r.team) + ' · ' + posLabel(r), next: nx ? { name: nx.name, value: m.fmt(val(nx, id)) } : null,
      expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  const noun = g[3];
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + noun, title: SC.within === 'pos' ? 'The best ' + noun + ', on what matters there' : 'The best ' + noun + ' right now', sub: 'The leader on five of the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  const v = view(), g = grp(), k = kind();
  const all = shown();
  const rows = SC.q.trim() ? all.filter(matches) : all;
  const P = peers();
  const sets = [{ key: 'view', label: SC.within === 'pos' ? 'Position view' : 'Headline', groups: v.sets.map(s => ({ label: s.label, ids: s.ids })) }];
  const metrics = KD().metrics.filter(m => P.some(r => isNum(val(r, m.key))));
  const oursIds = metrics.filter(m => GI.SP.ours(m.key)).map(m => m.key);
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  const gnames = [];
  metrics.forEach(m => { if (gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(gn => sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: metrics.filter(m => (m.group || 'Other') === gn).map(m => m.key) }] }));
  const setKey = sets.some(s => s.key === SC.cols) ? SC.cols : 'view';
  const ag = v.sets.length === 3 && v.sets[2].key === 'aggregate' ? v.sets[2].ids : [];
  const defSort = v.color || ag[0] || (v.sets[0] || { ids: [] }).ids[0];
  let sort = SC.sort && SC.sort.key && (SC.sort.key === 'name' || SC.sort.key === 'n' || SC.sort.key === 'age' || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: sort.key !== 'name' && sort.key !== 'n' && sort.key !== 'age' && mmeta(sort.key).lower ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  const addable = GI.SP.orderOpts(metrics.map(m => ({ key: m.key, label: mmeta(m.key).label, lower: m.lower, group: m.group })), '', GI.SP.headIds(g[1] ? g[1] : 'DEF'));
  const floorTxt = isNum(SC.min) ? SC.min + '+ ' + nLabel().toLowerCase() : 'the qualified floor';
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    esc(g[2]) + ' · ' + SC.S + ' · cells on the percentile scale against the ' + P.length + ' ' + esc(g[3]) + ' past ' + esc(floorTxt) + ' (blue worst, red best). Tap a name for the profile; + pins to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>' +
    GI.SP.oursNote([].concat.apply([], v.sets.map(s => s.ids)).filter(id => GI.SP.ours(id)).slice(0, 3).map(id => [id, mmeta(id).label]));
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', sets: sets, set: setKey, added: SC.add.filter(id => has(id)), sort: sort, all: SC.all, page: 50, noun: g[3],
    nameLabel: 'Player', subLabel: 'Position · team · age',
    meta: id => mmeta(id),
    addable: addable,
    lead: [{ key: 'n', label: KD().nLabel, tip: KD().nLabel + ' this season', fmt: row => GI.int(row._r.n), val: row => row._r.n },
      { key: 'age', label: 'Age', fmt: row => (isNum(row._r.age) ? String(Math.floor(row._r.age)) : '—'), val: row => row._r.age }],
    rows: rows.map(r => ({ id: r.id, name: r.name, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r })),
    val: (row, id) => val(row._r, id),
    peers: P.map(r => ({ id: r.id, _r: r })),
    hl: row => SC.cmp.indexOf(row.id) >= 0,
    pin: { has: id => !!TRAY && TRAY.has(id), toggle: row => pin(row._r), label: 'Pin to the compare tray' },
    onPick: row => openProfile(row.id),
    onState: st => { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'gridiron-' + SC.S + '-' + code().toLowerCase() + '-' + String(setKey || 'view').toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.csv',
    empty: SC.q.trim() ? 'No ' + g[3] + ' match “' + SC.q.trim() + '” with these filters.' : 'No ' + g[3] + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(g[4]) + ' past the floor, whatever the team, age or search filters show; a ↓ marks a metric where lower is better (its colours are flipped) and grey cells are style (neither better nor worse). Every metric in the file is a chip or “Add a metric” away.'
  });
}

/* Chart: the Lab inside the room */
function chartView(host) {
  if (!GI.lab || !GI.lab.mount) { host.innerHTML = QK.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  GI.lab.mount(document.getElementById('sc-chart'), SC.S, {
    within: SC.within, kind: SC.bg, pos: SC.pg, min: isNum(SC.min) ? SC.min : null, q: SC.q, x: SC.x, y: SC.y, color: SC.color,
    keep: keepGet,
    onPick: id => openProfile(id),
    onAxes: ax => { SC.x = ax.x || ''; SC.y = ax.y || ''; SC.color = ax.color || ''; writeQuery(); }
  });
}

/* Leaders: small multiples on the view's key metrics, each with a dot strip of the group */
function leadersView(host) {
  const v = view(), rows = shown(), g = grp(), P = peers();
  const ids = keyMetrics(v).filter(id => !mmeta(id).style);
  const hl = r => matches(r) || r.id === SC.p;
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + g[2], title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + g[3] + ' on screen on the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics. Bars are percentiles against the ' + P.length + ' past the floor; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map((id, i) => {
      const m = mmeta(id);
      const list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
      if (!list.length) return '';
      const item = (r, rk) => { const p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      const top = list.slice(0, 5).map((r, j) => item(r, j + 1));
      const bottom = !TOTALS.test(id) && list.length > 10 ? list.slice(-3).map((r, j) => item(r, list.length - 2 + j)) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + g[3], top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach((id, i) => {
    const el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    const m = mmeta(id);
    const vals = rows.filter(r => isNum(val(r, id))).map(r => ({ v: val(r, id), name: r.name + ' · ' + GI.teamAbbr(r.team), id: r.id, hl: hl(r) }));
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + g[4] + ' on ' + m.label, onClick: d => openProfile(d.id) });
  });
}

/* All-time: history.js's boards inside the room (phase 2) */
function alltimeView(host) {
  if (!GI.history || !GI.history.mount) { host.innerHTML = QK.empty('All-time lists', 'The all-time boards did not load. Reload the page.'); return; }
  host.innerHTML = '<div id="sc-alltime"></div>';
  GI.history.mount(document.getElementById('sc-alltime'), { group: SC.within === 'pos' ? GROUPS[SC.pg][0] : SC.bg, q: SC.q });
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id) {
  const r = findRow(id);
  if (!r) return;
  SC.p = r.id; writeQuery();
  const c = inGroup(r) ? code() : codeOf(r);
  const g = grp(c), v = view(c), P = peers(c);
  const row = id2 => { const m = mmeta(id2, r.kind), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: m.style ? null : pctOf(r, id2, c), value: m.fmt(x), tip: m.tip, style: m.style }; };
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(row).filter(Boolean) }));
  const t = teamOf(r);
  const statIds = [v.color, v.y, v.x].filter((x, i, a) => x && a.indexOf(x) === i);
  const stats = statIds.map(id2 => { const m = mmeta(id2, r.kind), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: m.style ? null : pctOf(r, id2, c), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: KD(r.kind).nLabel, value: GI.int(r.n) });
  const simKeys = [];
  if (v.sets.length === 3) [4, 4, 2].forEach((n, i) => v.sets[i].ids.filter(x => simKeys.indexOf(x) < 0).slice(0, n).forEach(x => simKeys.push(x)));
  else v.sets.forEach(s => s.ids.slice(0, 3).forEach(x => { if (simKeys.indexOf(x) < 0) simKeys.push(x); }));
  const pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  const near = QK.within.similar(pool, r, simKeys, (rr, key) => val(rr, key), 5);
  const cmpH = GI.compareHref(r.id, near.length ? near[0].row.id : null) + (SC.S !== GI.currentSeason() ? '?s=' + SC.S : '');
  const inPeers = P.indexOf(r) >= 0;
  const html = QK.profile({
    kicker: GI.posLong(posLabel(r) === 'ED' ? 'EDGE' : posLabel(r)) + ' · ' + (t.name || t.abbr),
    name: r.name, href: href(r),
    sub: [isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', GI.int(r.n) + ' ' + KD(r.kind).nLabel.toLowerCase(), isNum(r.games) ? r.games + ' games' : '', SC.S].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: g[3] + (isNum(SC.min) && c === code() ? ' with ' + SC.min + '+ ' + nLabel(c).toLowerCase() : ', qualified') + (inPeers ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + GI.surnameOf(r.name) + ' · ' + g[3], items: near.map(o => ({ name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) })) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: href(r) }, { label: 'Progression', href: progHref(r) }, { label: near.length ? 'Compare with ' + GI.surnameOf(near[0].row.name) : 'Compare', href: cmpH }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(g[3]) + ' past the floor in ' + SC.S + '. “Most like” is the nearest five on the ' + (SC.within === 'pos' ? 'position view’s' : 'group’s') + ' metrics.' + (GI.SP.NOTE[g[1]] ? ' ' + esc(GI.SP.NOTE[g[1]]) : '')
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
  const first = SC.cmp.length ? findRow(SC.cmp[0]) : null;
  if (first && first.kind !== r.kind && !TRAY.has(r.id)) TRAY.clear();     // a quarterback and a corner share no scale
  TRAY.toggle(r.id);
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(b => { const on = TRAY.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(id => findRow(id)), label: 'Compare tray',
    item: id => { const r = findRow(id); return r ? { name: r.name, short: GI.surnameOf(r.name), sub: posLabel(r) + ' · ' + GI.teamAbbr(r.team), colour: teamOf(r).colour } : { name: id }; },
    onChange: ids => { SC.cmp = ids; writeQuery(); },
    href: ids => GI.compareHref(ids[0], ids[1], ids[2]) + (SC.S !== GI.currentSeason() ? '?s=' + SC.S : ''),
    hrefLabel: 'Full compare',
    body: ids => trayBody(ids)
  });
}
function trayBody(ids) {
  const rs = ids.map(id => findRow(id)).filter(Boolean);
  if (rs.length < 2) return '';
  const k0 = rs[0].kind;
  const codes = rs.map(r => (inGroup(r) ? code() : codeOf(r)));
  const v = view(codes[0]);
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(id => {
    const m = mmeta(id, k0);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map((r, i) => { const x = r.kind === k0 ? val(r, id) : null; return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) && !m.style ? pctOf(r, id, codes[i]) : null }; }) };
  }) }));
  return QK.trayCompare({ entities: rs.map(r => { const t = teamOf(r); return { name: r.name, short: GI.surnameOf(r.name), sub: posLabel(r) + ' · ' + t.abbr + ' · ' + GI.int(r.n) + ' ' + KD(r.kind).nLabel.toLowerCase(), colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own ' + (SC.within === 'pos' ? 'position' : 'group') + '’s peers past the floor (' + SC.S + '). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

GI.route('scout', render);
GI.scout = { GROUPS: GROUPS, BROAD: BROAD, POSN: POSN };
})(window.GI);
