/* The Quant Bullpen — the Scouting Room (#/<L>/scout): the Players pages (hitters, pitchers, leaderboards) and the Lab
 * in one page built for quick analysis (round 8, 28 Oct 2026; the pilot for the other seven sites). Kit: scout.js
 * (QK.board, QK.leaderCard, QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare, QK.scoutBar) and quant.js
 * (QK.within, QK.hotRow, QK.pctlBars).
 *
 * One control bar drives every view: "Compare within" Broad (hitters, starters, relievers: starters and relievers are
 * never pooled) or Position (C ... DH, SP, RP; the spec groups' Position view), the season, the minimum sample (the spec
 * floor prorated by team games), team, age band, bats / throws, and search (the Board keeps the matches; the Chart and the
 * Leaders highlight them). Under the bar, "Top of the position": the leader on five of the view's metrics.
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips ("Position view" = the view's excellence, hitting or run
 *            prevention and value metrics; "Our models"; every payload group: Traditional ... Projection), any single
 *            metric added, cells on the percentile scale within the peers (the group past the floor; lower-is-better
 *            and style metrics handled), the top 50 then "Show all", "Download CSV" of what is on screen;
 *   chart    the scatter Lab (lab.js, BP.lab.mount): presets, the Position view's axes, colour, shrink, medians,
 *            labelled corners, the ranked table and "Most like";
 *   leaders  small multiples: for the view's key metrics, the top five and the bottom three as bars, over a dot strip
 *            of the whole group with the median and the highlighted players marked.
 * Selecting a player anywhere (a name, a point, a card) opens the profile drawer (?p=<pid>): percentile meters for the
 * view's metrics grouped excellence / hitting or run prevention / value, a line of headline numbers, "Most like", and
 * links to the player page, progression and Compare. Pin up to four (the + on a row, or "Pin" in the drawer) to the
 * compare tray (?cmp=<pid>,<pid>): side by side on percentile bars, each against their own group's peers.
 * Address: ?view, kind (hitter|sp|rp), within=pos&pos=<code>, min, team, age (u25|25-29|30-34|35p), hand (L|R|S), q,
 * cols (a column set), add (metrics, comma), sort, dir, all, p, cmp, x, y, color (the chart's axes): links share.
 * Data: data/<L>/<S>/lab.json (every metric of every player with 50+ PA / BF, loaded once and shared by the views),
 * season.json (team games, for prorating). Old routes (#/<L>/hitters, pitchers, leaders, lab) redirect here (core.js).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const U = () => BP.ui;
const esc = s => BP.esc(s);
const isNum = v => typeof v === 'number' && isFinite(v);

/* Peer groups: code -> [kind, BP.ui.SETS key, name, plural noun, test(position)] (as lab.js) */
const POSU = p => String(p || '').toUpperCase();
const ROLEP = p => (U().ROLE_OF_POS || {})[POSU(p)] || '';
const GROUPS = {
  H: ['hitter', 'ALL', 'Hitters', 'hitters', () => true],
  SP: ['pitcher', 'SP', 'Starting pitchers', 'starters', p => POSU(p) === 'SP'],
  RP: ['pitcher', 'RP', 'Relief pitchers', 'relievers', p => POSU(p) === 'RP'],
  C: ['hitter', 'C', 'Catchers', 'catchers', p => ROLEP(p) === 'C'],
  '1B': ['hitter', '1B', 'First basemen', 'first basemen', p => ROLEP(p) === '1B'],
  '2B': ['hitter', '2B', 'Second basemen', 'second basemen', p => ROLEP(p) === '2B'],
  '3B': ['hitter', '3B', 'Third basemen', 'third basemen', p => ROLEP(p) === '3B'],
  SS: ['hitter', 'SS', 'Shortstops', 'shortstops', p => ROLEP(p) === 'SS'],
  CF: ['hitter', 'CF', 'Centre fielders', 'centre fielders', p => ROLEP(p) === 'CF'],
  'LF-RF': ['hitter', 'LF/RF', 'Corner outfielders', 'corner outfielders', p => ROLEP(p) === 'LF/RF'],
  DH: ['hitter', 'DH', 'Designated hitters', 'designated hitters', p => ROLEP(p) === 'DH']
};
const SING = { H: 'hitter', SP: 'starter', RP: 'reliever', C: 'catcher', '1B': 'first baseman', '2B': 'second baseman', '3B': 'third baseman', SS: 'shortstop',
  CF: 'centre fielder', 'LF-RF': 'corner outfielder', DH: 'designated hitter' };
const BROAD = ['H', 'SP', 'RP'];
const POSN = ['C', '1B', '2B', '3B', 'SS', 'CF', 'LF-RF', 'DH', 'SP', 'RP'];
const POS_LONG = { C: 'Catcher', '1B': 'First base', '2B': 'Second base', '3B': 'Third base', SS: 'Shortstop', CF: 'Centre field', LF: 'Left field', RF: 'Right field', OF: 'Outfield', DH: 'Designated hitter', TWP: 'Two-way', SP: 'Starter', RP: 'Reliever' };
const AGES = [['', 'Any age'], ['u25', 'Under 25'], ['25-29', '25 to 29'], ['30-34', '30 to 34'], ['35p', '35 and over']];
const AGE_TEST = { u25: a => a < 25, '25-29': a => a >= 25 && a < 30, '30-34': a => a >= 30 && a < 35, '35p': a => a >= 35 };
/* totals: a bottom three says nothing useful about playing time */
const TOTALS = /^(war|war_x|war_results|rar|oaa|fielding_runs|framing_runs|framing_savant|bsr|wsb|ebt_runs|re24|wpa|batting_runs|batting_results|pos_runs|repl_runs|hr|so|sb|w|sv|ip|g|gs|pa|ab|h|b1|b2|b3|bb|ibb|hbp|sf|sh|gidp|cs|bf|r|l|pitches|dv)$/;

/* ── state ───────────────────────────────────────────────────────────────── */
const SC = { L: 'mlb', S: null, view: 'board', within: 'broad', bg: 'H', pg: 'SS', min: null, team: '', age: '', hand: '', q: '',
  cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', color: '' };
let D = null, DK = '', TG = null, TRAY = null, ROOT = null, BOARD = null;

function code() { return SC.within === 'pos' ? SC.pg : SC.bg; }
function grp(c) { return GROUPS[c || code()] || GROUPS.H; }
function kind() { return grp()[0]; }
function nUnit(kd) { return (kd || kind()) === 'pitcher' ? 'BF' : 'PA'; }
function floor(c) { const g = grp(c); const f = U().floorOf ? U().floorOf(g[1], TG) : null; return f ? f.value : 0; }
function minNow() { return isNum(SC.min) ? SC.min : floor(); }

/* lab.json -> { hitter: { idx, meta, metrics, rows: [row] }, pitcher: ... }; row = { id, name, team, pos, n, age, hand,
   chances, called, a (the raw array), kind } */
function prep(raw) {
  const out = {};
  if (!raw || raw.ok === false || !raw.rows || Array.isArray(raw.rows)) return out;
  Object.keys(raw.rows).forEach(kd => {
    const ms = (raw.metrics || {})[kd] || [];
    const fields = (raw.fields || ['pid', 'name', 'team', 'pos', 'n']).concat(ms.map(m => m.key));
    const idx = {};
    fields.forEach((f, i) => { if (idx[f] === undefined) idx[f] = i; });
    const kk = /pit/.test(kd) ? 'pitcher' : 'hitter';
    const get = (r, f) => (idx[f] === undefined ? null : r[idx[f]]);
    const rows = (raw.rows[kd] || []).map(r => ({ id: String(get(r, 'pid')), name: get(r, 'name') || '', team: get(r, 'team') === null ? '' : String(get(r, 'team')), pos: get(r, 'pos') || '',
      n: get(r, 'n') || 0, age: get(r, 'age'), hand: get(r, 'hand'), chances: get(r, 'chances'), called: get(r, 'called'), a: r, kind: kk }));
    const meta = {};
    ms.forEach(m => { meta[m.key] = m; });
    out[kk] = { idx: idx, meta: meta, rows: rows, metrics: ms.filter(m => rows.some(r => isNum(r.a[idx[m.key]]))) };
  });
  return out;
}
function KD(kd) { return (D || {})[kd || kind()] || { idx: {}, meta: {}, rows: [], metrics: [] }; }
function val(r, id) { const g = KD(r.kind), i = g.idx[id]; if (i === undefined) return null; const v = r.a[i]; return isNum(v) ? v : null; }
function has(id, kd) { return KD(kd).idx[id] !== undefined; }

/* metric display: the spec's name and explanation, our-model tag, direction, style, the payload's format */
function mmeta(id, kd) {
  kd = kd || kind();
  const m = KD(kd).meta[id] || {};
  const cat = U().SPEC, sm = cat ? cat.metric(id, 'player') : null;
  const label = U().label(kd, id, m.label || id);
  const short = String(m.label || label).replace(/ \(ours\)$/, '');
  const tip = (U().MDESC[kd] || {})[id] ? (U().MDESC[kd][id][1] || '') : (sm && sm.explain) || m.desc || '';
  const ours = U().ours(id);
  return { id: id, label: label, short: short.length < label.length ? short : label, tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''),
    ours: ours, lower: !!m.lower, style: !!(sm && sm.style), fmt: v => K().fmtV(v, m.fmt), group: m.group || 'Other', raw: m };
}

/* rows: the group past the floor (the peers), then the room's filters */
function inGroup(r, c) { const g = grp(c); return g[0] === r.kind && g[4](r.pos); }
function peers(c) { const m = c && c !== code() ? floor(c) : minNow(); return KD(grp(c)[0]).rows.filter(r => inGroup(r, c) && (r.n || 0) >= m); }
function keep(get) {
  if (SC.team && String(get('team')) !== SC.team) return false;
  if (SC.age) { const a = get('age'); if (!isNum(a) || !AGE_TEST[SC.age](a)) return false; }
  if (SC.hand && String(get('hand') || '') !== SC.hand) return false;
  return true;
}
function rowKeep(r) { return keep(f => (f === 'team' ? r.team : f === 'age' ? r.age : f === 'hand' ? r.hand : val(r, f))); }
function shown() { return peers().filter(rowKeep); }
function matches(r) { const q = K().fold(SC.q.trim()); return !!q && K().fold(r.name + ' ' + K().teamAbbr(r.team)).indexOf(q) >= 0; }

/* fielding and framing: ranked only inside the position group and past their own floors (BP.ui.metricOk) */
function ranked(r, id, setKey) {
  const sk = setKey || grp()[1];
  if (U().FIELDING[id] && sk === 'ALL') return false;
  const x = U().EXTRA_MIN[id];
  if (!x) return true;
  const n = x[0] === 'chances' ? r.chances : x[0] === 'called' ? r.called : null;
  const tg = isNum(TG) && TG > 0 ? Math.min(162, TG) : 162;
  return isNum(n) && n >= Math.round(x[1] * tg / 162);
}
const PCT = {};
function pctOf(r, id, c) {
  c = c || code();
  const key = c + '|' + minNow() + '|' + id;
  let srt = PCT[key];
  if (!srt) {
    const sk = grp(c)[1];
    srt = PCT[key] = peers(c).filter(x => ranked(x, id, sk)).map(x => val(x, id)).filter(isNum).sort((a, b) => a - b);
  }
  const v = val(r, id);
  if (!isNum(v) || srt.length < 5 || !ranked(r, id, grp(c)[1])) return null;
  const p = QK.pctRank(srt, v);
  return mmeta(id, grp(c)[0]).lower ? 100 - p : p;
}
function clearPct() { Object.keys(PCT).forEach(k => delete PCT[k]); }

/* the view: the spec group's Position view (excellence, production, value) with ids this payload carries for 30%+ of the
   peers; Broad hitters (no view in the spec) take the headline groups (Bat, Approach, Glove, Value) */
function view(c) {
  c = c || code();
  const g = grp(c), set = U().SETS[g[1]] || {}, cat = U().SPEC;
  const P = peers(c);
  const okId = id => has(id, g[0]) && P.length > 0 && P.filter(r => isNum(val(r, id))).length >= 0.3 * P.length;
  const sg = cat && set.spec ? cat.group(set.spec) : null;
  const v = sg && sg.view && QK.within && QK.within.view ? QK.within.view(sg, okId) : null;
  if (v) return { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(s => s.ids.length).map(s => ({ key: s.key, label: s.label, ids: s.ids })) };
  const sets = (set.head || []).map(x => ({ key: x[0], label: x[0], ids: x[1].map(y => y[0]).filter(okId) })).filter(s => s.ids.length);
  const flat = [].concat.apply([], sets.map(s => s.ids));
  const agg = sets.filter(s => /value/i.test(s.key)).map(s => s.ids)[0] || [];
  return { why: '', x: flat[0], y: flat[1], color: agg[0] || null, sets: sets };
}
/* one metric per family on the quick reads (OAA per chance, not also OAA and fielding runs, which are its totals) */
const FAMILY = { oaa: 'sra', fielding_runs: 'sra', oaa_savant: 'sra', framing_runs: 'framing_rate', framing_savant: 'framing_rate', war: 'war_rate', war_600: 'war_rate',
  war_200: 'war_rate', war_x: 'war_rate', war_results: 'war_rate', xfip: 'fip', woba: 'woba', xwoba_n: 'xwoba', xwoba_plus: 'xwoba' };
const fam = id => FAMILY[id] || id;
function pickDistinct(out, ids, n) {
  let k = 0;
  ids.forEach(id => { if (k >= n || out.indexOf(id) >= 0 || out.some(x => fam(x) === fam(id))) return; out.push(id); k++; });
}
function keyMetrics(v) {
  const out = [];
  const add = (ids, n) => pickDistinct(out, ids, n);
  if (v.sets.length === 3 && v.sets[0].key === 'excellence') { add(v.sets[0].ids, 3); add(v.sets[1].ids, 4); add(v.sets[2].ids, 2); }
  else v.sets.forEach(s => add(s.ids, 3));
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders', 'alltime'].indexOf(q.view) >= 0 ? q.view : 'board';
  SC.m = q.m || ''; SC.scope = q.scope || '';
  const KQ = { hitter: 'H', hitters: 'H', sp: 'SP', pitcher: 'SP', pitchers: 'SP', rp: 'RP' };
  if (q.within === 'pos' && POSN.indexOf(q.pos) >= 0) { SC.within = 'pos'; SC.pg = q.pos; }
  else { SC.within = 'broad'; SC.bg = KQ[q.kind] || 'H'; }
  const mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team || ''; SC.age = AGE_TEST[q.age] ? q.age : ''; SC.hand = /^[LRS]$/.test(q.hand || '') ? q.hand : '';
  SC.q = q.q || ''; SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.color = q.color || '';
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }
function hashNow() {
  const q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.within === 'pos') { q.within = 'pos'; q.pos = SC.pg; } else if (SC.bg !== 'H') q.kind = SC.bg === 'SP' ? 'sp' : 'rp';
  if (isNum(SC.min)) q.min = SC.min;
  ['team', 'age', 'hand', 'q', 'cols'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['x', 'y', 'color'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.view === 'alltime') { if (SC.m) q.m = SC.m; if (SC.scope) q.scope = SC.scope; }
  if (SC.S && SC.S !== K().curSeason(SC.L)) q.s = SC.S;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  return '#/' + SC.L + '/scout' + (qs ? '?' + qs : '');
}

/* ── names, links, colours ──────────────────────────────────────────────── */
function href(r) { return r.kind === 'pitcher' ? K().pitcherHref(SC.L, r.id, SC.S) : K().hitterHref(SC.L, r.id, SC.S); }
function teamOf(r) { const t = BP.teamInfo(r.team) || {}; return { abbr: K().teamAbbr(r.team), colour: t.colour || '', alt: t.alt || '', name: t.name || '' }; }
function posLabel(r) { return r.kind === 'pitcher' ? (POSU(r.pos) === 'RP' ? 'RP' : 'SP') : POSU(r.pos) || '—'; }
function subOf(r) { return [posLabel(r), K().teamAbbr(r.team), isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · '); }
function findRow(id, kd) {
  const order = kd ? [kd, kd === 'pitcher' ? 'hitter' : 'pitcher'] : [kind(), kind() === 'pitcher' ? 'hitter' : 'pitcher'];
  for (let i = 0; i < order.length; i++) { const r = KD(order[i]).rows.find(x => x.id === String(id)); if (r) return r; }
  return null;
}
/* the group a row belongs to in the current mode (Position: its own position; Broad: hitters, starters or relievers) */
function codeOf(r) {
  if (r.kind === 'pitcher') return POSU(r.pos) === 'RP' ? 'RP' : 'SP';
  if (SC.within !== 'pos') return 'H';
  return POSN.find(c => GROUPS[c][0] === 'hitter' && GROUPS[c][4](r.pos)) || 'H';
}

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, params, state) {
  const k = K();
  SC.L = k.L(params, state);
  ROOT = el;
  readQuery(params.query || {});
  el.innerHTML = '<div class="sc qk-room"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders'], ['alltime', 'All-time']].map(t => '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>').join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  BP.onLeave(() => { if (QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return k.ready().then(() => {
    SC.S = k.S(params, state);
    return Promise.all([k.loadY(SC.L, SC.S, 'lab.json'), k.loadY(SC.L, SC.S, 'season.json'), U().specReady(), k.loadNames()]);
  }).then(res => {
    if (!k.alive(el)) return;
    const key = SC.L + '/' + SC.S;
    if (DK !== key) { D = prep(res[0]); DK = key; clearPct(); }
    TG = (res[1] && res[1].team_games) || null;
    if (!D.hitter && !D.pitcher) { document.getElementById('sc-view').innerHTML = QK.empty('Not built yet', 'The ' + k.LN(SC.L) + ' ' + SC.S + ' scouting file is not available.'); document.getElementById('sc-ctl').innerHTML = ''; return; }
    if (!D[kind()]) { SC.within = 'broad'; SC.bg = D.hitter ? 'H' : 'SP'; }
    BP.setMeta(k.LN(SC.L) + ' ' + SC.S + ' · ' + (KD('hitter').rows.length + KD('pitcher').rows.length).toLocaleString('en-GB') + ' players with 50+ PA or BF');
    controls();
    tabs();
    tray();
    refresh();
    if (SC.p) { const r = findRow(SC.p); if (r) openProfile(r.id, r.kind); }
  });
}

/* a click on a player link anywhere in the room opens the drawer (a modified click follows the link) */
function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  const a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a) return;
  const m = /#\/(?:mlb|aaa)\/(hitter|pitcher)\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[2]), m[1])) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[2]), m[1]);
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  const k = K(), host = document.getElementById('sc-ctl');
  if (!host) return;
  const avail = c => !!D[GROUPS[c][0]];
  const fl = floor(), mx = Math.max.apply(null, KD().rows.filter(r => inGroup(r)).map(r => r.n || 0).concat([50]));
  const broadSeg = U().seg('sc-kind', 'Group', BROAD.filter(avail).map(c => [c, c === 'H' ? 'Hitters' : c === 'SP' ? 'Starters' : 'Relievers']), SC.bg);
  const within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', groups: [{ group: 'Hitters', items: POSN.filter(c => avail(c) && GROUPS[c][0] === 'hitter').map(c => [c, GROUPS[c][2]]) },
    { group: 'Pitchers (never pooled)', items: POSN.filter(c => avail(c) && GROUPS[c][0] === 'pitcher').map(c => [c, GROUPS[c][2]]) }],
    note: SC.within === 'pos' ? '' : broadSeg });
  const teams = Array.from(new Set(KD().rows.map(r => r.team).filter(Boolean))).sort((a, b) => k.teamName(a).localeCompare(k.teamName(b)));
  const hands = kind() === 'pitcher' ? [['', 'Either hand'], ['L', 'Left-handed'], ['R', 'Right-handed']] : [['', 'Any side'], ['L', 'Bats left'], ['R', 'Bats right'], ['S', 'Switch']];
  const seasons = k.seasons(SC.L);
  const opt = (v, t, cur) => '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>';
  const anyHand = KD().rows.some(r => r.hand);
  const anyAge = KD().rows.some(r => isNum(r.age));
  const items = [
    { label: 'Season', html: '<select class="qk-select" id="sc-season">' + seasons.map(y => opt(y, y, SC.S)).join('') + '</select>' },
    { label: 'Min ' + nUnit(), html: '<span class="sc-min"><input type="range" id="sc-min" min="0" max="' + (Math.ceil(mx / 10) * 10) + '" step="5" value="' + minNow() + '" aria-label="Minimum ' + nUnit() + '"><b class="qk-sbar-v" id="sc-min-v">' + minNow() + '</b></span>', cls: 'sc-minf' },
    { label: 'Team', html: '<select class="qk-select" id="sc-team">' + opt('', 'All teams', SC.team) + teams.map(t => opt(t, k.teamName(t), SC.team)).join('') + '</select>' },
    anyAge ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(a => opt(a[0], a[1], SC.age)).join('') + '</select>' } : null,
    anyHand ? { label: kind() === 'pitcher' ? 'Throws' : 'Bats', html: '<select class="qk-select" id="sc-hand">' + hands.map(a => opt(a[0], a[1], SC.hand)).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or team…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  const v = view();
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">' + esc(grp()[2]) + ' with ' + minNow() + '+ ' + nUnit() + (isNum(SC.min) && SC.min !== fl ? ' (the spec floor is ' + fl + ')' : ' (the metrics spec’s floor' + (TG && TG < 162 ? ', prorated to ' + TG + ' team games' : '') + ')') + '</p>' +
    QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, w => {
    if (w.within === 'pos' && SC.within !== 'pos' && (SC.bg === 'SP' || SC.bg === 'RP')) w.pos = SC.bg;
    if (w.within !== 'pos' && SC.within === 'pos') SC.bg = SC.pg === 'SP' || SC.pg === 'RP' ? SC.pg : 'H';
    const kd0 = kind();
    SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos;
    regroup(kd0);
  }, { id: 'sc-wn' });
  const seg = document.getElementById('sc-kind');
  if (seg) QK.seg(seg, x => { if (!GROUPS[x]) return; const kd0 = kind(); SC.bg = x; regroup(kd0); });
  const $ = id => document.getElementById(id);
  $('sc-season').onchange = e => { SC.S = parseInt(e.target.value, 10); SC.p = ''; SC.min = null; location.hash = hashNow(); };
  $('sc-min').oninput = e => { $('sc-min-v').textContent = e.target.value; };
  $('sc-min').onchange = e => { SC.min = parseInt(e.target.value, 10); if (SC.min === floor()) SC.min = null; clearPct(); controls(); refresh(); };
  $('sc-team').onchange = e => { SC.team = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = e => { SC.age = e.target.value; refresh(); };
  if ($('sc-hand')) $('sc-hand').onchange = e => { SC.hand = e.target.value; refresh(); };
  let t = null;
  $('sc-q').oninput = e => { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
/* a new group: the minimum goes back to its floor; a new kind drops the hand filter, the added metrics, the sort and the
   chart's axes (they name another kind's metrics); a new group drops the column set (each group has its own view) */
function regroup(kd0) {
  SC.min = null; SC.cols = ''; SC.x = ''; SC.y = ''; SC.color = '';
  if (kind() !== kd0) { SC.hand = ''; SC.add = []; SC.sort = null; }
  else SC.sort = null;
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
  /* the all-time careers (history.js) have their own controls: the season bar and "Top of the group" step aside */
  ['sc-ctl', 'sc-top'].forEach(id => { const n = document.getElementById(id); const box = n ? (n.closest('.sc-ctl') || n) : null; if (box) box.style.display = SC.view === 'alltime' ? 'none' : ''; });
  if (SC.view === 'alltime') {
    host.innerHTML = '';
    if (BP.allTime) BP.allTime(host, { level: 'mlb', query: { m: SC.m, scope: SC.scope } });
    else host.innerHTML = QK.empty('Not available', 'The all-time boards did not load.');
    return;
  }
  if (SC.view === 'chart') return chartView(host);
  if (SC.view === 'leaders') return leadersView(host);
  return boardView(host);
}

/* "Top of the position": the leader on five of the view's metrics among the players on screen */
function topStrip() {
  const host = document.getElementById('sc-top');
  if (!host) return;
  const v = view(), rows = shown(), g = grp();
  const ids = [];
  const add = (list, n) => pickDistinct(ids, list, n);
  if (v.sets.length === 3 && v.sets[0].key === 'excellence') { add(v.sets[0].ids, 2); add(v.sets[1].ids, 2); add(v.sets[2].ids, 1); }
  else v.sets.forEach(s => add(s.ids, 2));
  const items = ids.slice(0, 5).map(id => {
    const m = mmeta(id), list = rows.filter(r => isNum(val(r, id)) && ranked(r, id)).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
    if (!list.length) return null;
    const r = list[0], nx = list[1];
    return { sport: 'baseball', kicker: m.label, name: r.name, value: m.fmt(val(r, id)), title: K().teamAbbr(r.team) + ' · ' + posLabel(r), next: nx ? { name: nx.name, value: m.fmt(val(nx, id)) } : null,
      expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  const noun = g[3];
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + noun, title: SC.within === 'pos' ? 'The best ' + noun + ', on what matters there' : 'The best ' + noun + ' right now', sub: 'The leader on five of the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* one-line board heads (round 10) for payload keys the metrics spec does not carry; the spec's own come through
   QK.spec (`short`). A value is the head, or [head, unit]. */
var BOARD_ABBR = {
  "g": "Games", "cstr_pct": "CStr%", "fp_swing_pct": "F-Swing%", "fp_strike_pct": "F-Strike%",
  "s2_whiff_pct": "2S Whiff%", "chase_zone_swing_pct": "Chase-zn sw%", "dv": "Decision RV", "dv_zone": "Zone dec.",
  "dv_chase": "Chase dec.", "x_swing_pct": "xSwing%", "swing_oe": "Swing% OE", "should_swing_pct": "Bad-take%",
  "should_take_pct": "Bad-swing%", "la_sd": "LA SD", "solid_pct": "Solid%", "flare_pct": "Flare/burner",
  "fb_dist": "Fly dist", "xwoba_diff": "xwOBA+ - Sav", "woba_minus_x": "wOBA - xw", "xwobacon_savant": "xwOBAcon Sav",
  "cent_pct": "Straight%", "bat_speed_adj": "Adj bat spd", "swing_length_adj": "Adj sw len", "sq_swing": "SqUp%/swing",
  "sq_oe": "SqUp% OE", "path_mismatch": "Path miss", "path_matched_pct": "Path match%",
  "attack_direction": "Attack dir", "swing_tilt": "Swing tilt", "intercept_rel": "Contact pt", "fb_xwoba": "FB xwOBA",
  "fb_whiff_pct": "FB Whiff%", "fb_rv100": "FB RV/100", "fb_chase_pct": "FB Chase%", "br_xwoba": "Brk xwOBA",
  "br_whiff_pct": "Brk Whiff%", "br_rv100": "Brk RV/100", "br_chase_pct": "Brk Chase%", "os_xwoba": "OS xwOBA",
  "os_whiff_pct": "OS Whiff%", "os_rv100": "OS RV/100", "os_chase_pct": "OS Chase%", "v95_xwoba": "95+ xwOBA",
  "v95_whiff_pct": "95+ Whiff%", "v90_xwoba": "90-95 xwOBA", "v90_whiff_pct": "90-95 Whiff%", "vlo_xwoba": "<90 xwOBA",
  "vlo_whiff_pct": "<90 Whiff%", "heart_rv100": "Heart RV", "shadow_rv100": "Shadow RV", "chase_rv100": "Chase RV",
  "waste_rv100": "Waste RV", "shadow_swing_pct": "Shadow sw%", "pa_vl_share": "PA% v LHP", "woba_hilev": "wOBA hi-lev",
  "hp_to_1b": ["Home to 1st", "s"], "ebt_runs": "XBT runs", "oaa_back": "OAA back", "oaa_in": "OAA in",
  "oaa_3b": "OAA to 3B", "oaa_1b": "OAA to 1B", "war_results": "WAR (res.)", "batting_results": "Bat runs res",
  "pos_runs": "Pos runs", "repl_runs": "Repl runs", "proj_woba": "Proj wOBA", "proj_iso": "Proj ISO",
  "proj_babip": "Proj BABIP", "proj_bb_pct": "Proj BB%", "proj_hr_pa": "Proj HR/PA", "pre_woba": "Pre wOBA", "r": "R",
  "fb_stuff": "FB Stuff+", "fb_location": "FB Loc+", "fb_pitching": "FB Pitch+",
  "best_secondary_stuff": "Best 2nd St+", "fb_spin": ["FB spin", "rpm"], "fb_hb": ["FB arm run", "in"],
  "fb_spin_eff": "FB spin eff", "fb_axis_dev": "FB SSW", "velo_gap": ["Velo gap", "mph"], "rel_height": ["Rel height",
  "ft"], "rel_spread": "Rel spread", "rel_type_spread": "Rel gap", "tunnel_in": "Tunnel (in)", "fb_ahead": "FB% ahead",
  "fb_behind": "FB% behind", "fb_even": "FB% even", "br_two": "Brk% 2 strk", "fb_vl": "FB% v LHB",
  "fb_vr": "FB% v RHB", "os_vl": "OS% v LHB", "br_vr": "Brk% v RHB", "o_contact_pct": "O-Contact%",
  "bf_vl_share": "BF% v LHB", "fb_csw_pct": "FB CSW%", "br_csw_pct": "Brk CSW%", "os_csw_pct": "OS CSW%",
  "xwoba_tto1": "TTO1 xwOBA", "xwoba_tto2": "TTO2 xwOBA", "xwoba_tto3": "TTO3+ xwOBA", "velo_per100": ["Velo fade",
  "/100 p"], "spin_per100": ["Spin fade", "/100 p"], "velo_last3": "Velo last 3", "spin_last3": "Spin last 3",
  "rel_z_last3": "Rel drift", "velo_trend_30d": "Velo 30d", "workload_flag": "Workload", "proj_hr_bf": "Proj HR/BF"
};
/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  const k = K(), v = view(), kd = kind(), g = grp();
  const all = shown();
  const rows = SC.q.trim() ? all.filter(matches) : all;
  const P = peers();
  const vlabel = SC.within === 'pos' ? 'Position view' : (g[0] === 'pitcher' && v.sets.length === 3 && v.sets[0].key === 'excellence' ? 'Role view' : 'Headline');
  const sets = [{ key: 'view', label: vlabel, groups: v.sets.map(s => ({ label: s.label, ids: s.ids })) }];
  const oursIds = KD().metrics.filter(m => U().ours(m.key)).map(m => m.key);
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  const gnames = [];
  KD().metrics.forEach(m => { if (gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(gn => sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: KD().metrics.filter(m => (m.group || 'Other') === gn).map(m => m.key) }] }));
  const setKey = QK.board.pick(sets, SC.cols, 'view');
  const ag = v.sets.length === 3 && v.sets[2].key === 'aggregate' ? v.sets[2].ids : [];
  const defSort = v.color || ag[0] || (v.sets[0] || { ids: [] }).ids[0];
  let sort = SC.sort && SC.sort.key && (SC.sort.key === 'name' || SC.sort.key === 'n' || SC.sort.key === 'age' || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: sort.key !== 'name' && sort.key !== 'n' && sort.key !== 'age' && mmeta(sort.key).lower ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  const addable = U().metricOpts(KD().metrics, '', kd, { set: g[1] });
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    esc(g[2]) + ' · ' + SC.S + ' · the bar under each number is its percentile against the ' + P.length + ' ' + esc(g[3]) + ' with ' + minNow() + '+ ' + nUnit() + ': the top 10% in red, the bottom 10% in blue. Tap a name for the profile; tick the box beside it to pin it to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>' +
    (v.sets.some(s => s.ids.some(id => U().ours(id))) ? U().oursNote(kd, [].concat.apply([], v.sets.map(s => s.ids)).filter(id => U().ours(id)).slice(0, 3)) : '');
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', summary: defSort, abbr: BOARD_ABBR, family: fam, sets: sets, set: setKey, added: SC.add.filter(id => has(id)), sort: sort, all: SC.all, page: 50, noun: g[3],
    nameLabel: kd === 'pitcher' ? 'Pitcher' : 'Hitter', subLabel: 'Position · team · age',
    meta: id => mmeta(id),
    addable: addable,
    lead: [{ key: 'n', label: nUnit(), tip: kd === 'pitcher' ? 'Batters faced' : 'Plate appearances', fmt: row => k.int(row._r.n), val: row => row._r.n },
      { key: 'age', label: 'Age', fmt: row => (isNum(row._r.age) ? String(Math.floor(row._r.age)) : '—'), val: row => row._r.age }],
    rows: rows.map(r => ({ id: r.id, name: r.name, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r })),
    val: (row, id) => val(row._r, id),
    peers: P.map(r => ({ id: r.id, _r: r })),
    ranked: (row, id) => ranked(row._r, id),
    hl: row => SC.cmp.indexOf(row.id) >= 0,
    pin: { has: id => !!TRAY && TRAY.has(id), toggle: row => pin(row._r), label: 'Pin to the compare tray' },
    onPick: row => openProfile(row.id, row._r.kind),
    onState: st => { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'bullpen-' + SC.L + '-' + SC.S + '-' + code().toLowerCase() + '-' + st0(setKey) + '.csv',
    empty: SC.q.trim() ? 'No ' + g[3] + ' match “' + SC.q.trim() + '” with these filters.' : 'No ' + g[3] + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(SING[code()]) + ' past the floor, whatever the team, age or hand filters show; a ↓ marks a metric where lower is better (its bar is flipped), style metrics (neither better nor worse) are never coloured, and fielding and framing are ranked only within a position and past their own chances. Every metric in the file is under “Columns” or “Add a metric”.'
  });
}
function st0(s) { return String(s || 'view').toLowerCase().replace(/[^a-z0-9]+/g, '-'); }

/* Chart: the Lab inside the room */
function chartView(host) {
  if (!BP.lab || !BP.lab.mount) { host.innerHTML = QK.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  BP.lab.mount(document.getElementById('sc-chart'), SC.L, SC.S, {
    within: SC.within, bg: SC.bg, pg: SC.pg, min: isNum(SC.min) ? SC.min : null, q: SC.q, x: SC.x, y: SC.y, color: SC.color, tg: TG,
    keep: keep,
    onPick: (id, kd) => openProfile(id, kd),
    onAxes: ax => { SC.x = ax.x || ''; SC.y = ax.y || ''; SC.color = ax.color && ax.color !== 'team' ? ax.color : ''; writeQuery(); }
  });
}

/* Leaders: small multiples on the view's key metrics, each with a dot strip of the group */
function leadersView(host) {
  const v = view(), rows = shown(), g = grp(), P = peers();
  const ids = keyMetrics(v);
  const hl = r => matches(r) || r.id === SC.p;
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + g[2], title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + g[3] + ' on screen on the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics. Bars are percentiles against the ' + P.length + ' with ' + minNow() + '+ ' + nUnit() + '; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map((id, i) => {
      const m = mmeta(id);
      const list = rows.filter(r => isNum(val(r, id)) && ranked(r, id)).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
      if (!list.length) return '';
      const item = (r, rk) => { const p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      const top = list.slice(0, 5).map((r, j) => item(r, j + 1));
      const total = TOTALS.test(id);
      const bottom = !total && list.length > 10 ? list.slice(-3).map((r, j) => item(r, list.length - 2 + j)) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + g[3], top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach((id, i) => {
    const el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    const m = mmeta(id);
    const vals = rows.filter(r => isNum(val(r, id)) && ranked(r, id)).map(r => ({ v: val(r, id), name: r.name + ' · ' + K().teamAbbr(r.team), id: r.id, hl: hl(r), kind: r.kind }));
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + SING[code()] + ' on ' + m.label, onClick: d => openProfile(d.id, kind()) });
  });
  bestByPosition(host);
}
/* "The best at each position" (round 9, moved here from Value): the three most valuable players at each position by
   Bullpen WAR, each past the position's floor, with the WAR percentile within the position (the team, age and hand
   filters apply). */
function bestByPosition(host) {
  const war = c => (has('war', grp(c)[0]) ? 'war' : null);
  const cards = POSN.filter(c => D[grp(c)[0]] && war(c)).map(c => {
    const list = peers(c).filter(rowKeep).filter(r => isNum(val(r, 'war'))).sort((a, b) => val(b, 'war') - val(a, 'war')).slice(0, 3);
    if (!list.length) return '';
    return '<div class="sc-best-c"><div class="qk-kicker">' + esc(GROUPS[c][2]) + '</div><ol class="bp-list bp-lead">' + list.map((r, i) => {
      const p = pctOf(r, 'war', c);
      return '<li><span class="n">' + (i + 1) + '</span><span style="min-width:0;flex:1"><a href="' + esc(href(r)) + '">' + esc(r.name) + '</a> <span class="qk-muted">' + esc(K().teamAbbr(r.team)) + '</span></span>' +
        '<span class="v">' + K().num(val(r, 'war'), 1) + '</span>' + (isNum(p) ? QK.pctlChip(Math.round(p)) : '') + '</li>';
    }).join('') + '</ol></div>';
  }).filter(Boolean);
  if (!cards.length) return;
  host.insertAdjacentHTML('beforeend', '<section class="qk-section">' + QK.sectionHead({ kicker: 'By position', title: 'The best at each position', sub: 'Bullpen WAR this season, players whose primary position it is (pitchers by role), each past the position’s sample floor; the chip is the WAR percentile within the position.' }) +
    '<div class="sc-best">' + cards.join('') + '</div></section>');
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id, kd) {
  const r = findRow(id, kd);
  if (!r) return;
  const k = K();
  SC.p = r.id; writeQuery();
  const c = r.kind === kind() && inGroup(r) ? code() : codeOf(r);
  const g = grp(c), v = view(c), P = peers(c);
  const pr = (rr, id2) => pctOf(rr, id2, c);
  const row = id2 => { const m = mmeta(id2, r.kind), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pr(r, id2), value: m.fmt(x), tip: m.tip, style: m.style }; };
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(row).filter(Boolean) }));
  const t = teamOf(r);
  const statIds = [v.color, v.y, v.x].filter((x, i, a) => x && a.indexOf(x) === i);
  const stats = statIds.map(id2 => { const m = mmeta(id2, r.kind), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pr(r, id2), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: r.kind === 'pitcher' ? 'Batters faced' : 'Plate appearances', value: k.int(r.n) });
  const simKeys = [];
  if (v.sets.length === 3 && v.sets[0].key === 'excellence') [4, 4, 2].forEach((n, i) => v.sets[i].ids.filter(x => simKeys.indexOf(x) < 0).slice(0, n).forEach(x => simKeys.push(x)));
  else v.sets.forEach(s => s.ids.slice(0, 3).forEach(x => { if (simKeys.indexOf(x) < 0) simKeys.push(x); }));
  const pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  const near = QK.within.similar(pool, r, simKeys, (rr, key) => val(rr, key), 5);
  const base = href(r), more = base + (base.indexOf('?') >= 0 ? '&' : '?') + 'view=progression';
  const cmpH = near.length ? BP.compareHref(r.id, near[0].row.id) + (r.kind === 'pitcher' ? '?kind=pitcher' : '') : BP.compareHref(r.id);
  const hand = r.hand ? (r.kind === 'pitcher' ? 'Throws ' + r.hand : 'Bats ' + (r.hand === 'S' ? 'both' : r.hand)) : '';
  const inPeers = P.indexOf(r) >= 0;
  const html = QK.profile({
    kicker: (POS_LONG[posLabel(r)] || posLabel(r)) + ' · ' + (t.name || t.abbr),
    name: r.name, href: base,
    sub: [isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', hand, k.int(r.n) + ' ' + nUnit(r.kind), SC.S].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: g[3] + ' with ' + floorFor(c) + '+ ' + nUnit(r.kind) + (inPeers ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + K().surname(r.name) + ' · ' + g[3], items: near.map(o => ({ name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) })) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: base }, { label: 'Progression', href: more }, { label: near.length ? 'Compare with ' + K().surname(near[0].row.name) : 'Compare', href: cmpH }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(g[3]) + ' on screen with ' + floorFor(c) + '+ ' + nUnit(r.kind) + ' in ' + SC.S + '. “Most like” is the nearest five on the ' + (SC.within === 'pos' ? 'position view’s' : 'group’s') + ' metrics.'
  });
  const inner = QK.drawer.open({ html: html, label: r.name + ': profile', onClose: () => { SC.p = ''; writeQuery(); } });
  const pb = inner.querySelector('#sc-pf-pin');
  if (pb) pb.addEventListener('click', () => { pin(r); openProfile(r.id, r.kind); });
  QK.$$('[data-pick]', inner).forEach(a => a.addEventListener('click', ev => {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'), r.kind);
  }));
}
function floorFor(c) { return c === code() ? minNow() : floor(c); }

/* ── the compare tray ───────────────────────────────────────────────────── */
function pin(r) {
  if (!TRAY) return;
  const first = SC.cmp.length ? findRow(SC.cmp[0]) : null;
  if (first && first.kind !== r.kind && !TRAY.has(r.id)) TRAY.clear();     // hitters and pitchers share no scale
  TRAY.toggle(r.id);
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(b => { const on = TRAY.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(id => findRow(id)), label: 'Compare tray',
    item: id => { const r = findRow(id); return r ? { name: r.name, short: K().surname(r.name), sub: posLabel(r) + ' · ' + K().teamAbbr(r.team), colour: teamOf(r).colour } : { name: id }; },
    onChange: ids => { SC.cmp = ids; writeQuery(); },
    href: ids => { const r0 = findRow(ids[0]); return BP.compareHref(ids[0], ids[1]) + '?' + (ids[2] ? 'c=' + encodeURIComponent(ids[2]) + '&' : '') + 'kind=' + (r0 && r0.kind === 'pitcher' ? 'pitcher' : 'hitter'); },
    hrefLabel: 'Full compare',
    body: ids => trayBody(ids)
  });
}
function trayBody(ids) {
  const rs = ids.map(id => findRow(id)).filter(Boolean);
  if (rs.length < 2) return '';
  const k0 = rs[0].kind;
  const codes = rs.map(codeOf);
  const v = view(codes[0]);
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(id => {
    const m = mmeta(id, k0);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map((r, i) => { const x = r.kind === k0 ? val(r, id) : null; return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id, codes[i]) : null }; }) };
  }) }));
  return QK.trayCompare({ entities: rs.map(r => { const t = teamOf(r); return { name: r.name, short: K().surname(r.name), sub: posLabel(r) + ' · ' + t.abbr + ' · ' + K().int(r.n) + ' ' + nUnit(r.kind), colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own ' + (SC.within === 'pos' ? 'position' : 'group') + '’s peers past the floor (' + SC.S + '). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

if (typeof BP.route === 'function') { BP.route('scout', render); try { BP.route('#/<L>/scout', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
