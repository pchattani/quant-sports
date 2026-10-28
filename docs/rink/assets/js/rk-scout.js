/* The Quant Rink — the Scouting Room (#/scout): the Players pages (leaders, skaters, goalies, every leaderboard) and the
 * Lab in one page built for quick analysis (round 9, 28 Oct 2026, after the Bullpen pilot bp-scout.js). Kit: scout.js
 * (QK.board, QK.leaderCard, QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare, QK.scoutBar) and quant.js
 * (QK.within, QK.hotRow, QK.pctlBars).
 *
 * One control bar drives every view: "Compare within" Broad (skaters, goalies) or Position (the metrics spec's peer
 * groups: forwards, defence, goaltenders, each with its Position view), the season, the minimum sample (skaters: 5v5
 * minutes; goalies: minutes in net; the default is the spec floor the payload's `qualified` flag applies: 250 5v5
 * minutes over a full season prorated by games, a quarter of the team's minutes for goalies), team, age band, shoots /
 * catches, and search (the Board keeps the matches; the Chart and the Leaders highlight them). Under the bar, "Top of
 * the group": the leader on five of the view's metrics. Views (?view=):
 *   board    (default) the deep table: column sets as chips (the Position view's driving play / defending /
 *            shot-stopping, scoring or results and value sets; "Our models"; every payload group), any metric added,
 *            cells on the percentile scale within the peers (the group past the floor; lower-is-better flipped), the
 *            top 50 then "Show all", "Download CSV" of what is on screen;
 *   chart    the scatter Lab (lab.js, RK.lab.mount): presets, the Position view's axes, colour, shrink, medians, the
 *            ranked table and "Most like";
 *   leaders  small multiples: for the view's key metrics, the top five and the bottom three as bars, over a dot strip of
 *            the whole group with the median and the highlighted players marked.
 * Selecting a player anywhere (a name, a point, a card) opens the profile drawer (?p=<pid>): percentile meters for the
 * view's metrics, headline numbers, "Most like", links to the player page, progression and Compare. Pin up to four (the +
 * on a row, or "Pin" in the drawer) to the compare tray (?cmp=<pid>,<pid>): side by side on percentile bars.
 * Address: ?view, kind (s|g), within=pos&pos=F|D|G, min, team, age (u23|23-27|28-31|32p), hand (L|R), q, cols, add,
 * sort, dir, all, p, cmp, x, y, color, s (season). Data: <S>/lab.json only (every metric of every player, column-oriented,
 * about 0.5-1 MB; never the 3-4 MB catalogues), and glossary.json through the Chart. Old routes (#/players?tab=,
 * #/skaters, #/goalies, #/leaders, #/lab) redirect here (core.js); the lines moved to Teams.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);
const K = () => RK.fk;

/* peer groups: code -> [kind, spec group id, name, plural noun, test(pos group)] */
const GROUPS = {
  S: ['S', null, 'Skaters', 'skaters', g => g === 'F' || g === 'D'],
  G: ['G', 'goalies', 'Goaltenders', 'goalies', g => g === 'G'],
  F: ['S', 'forwards', 'Forwards', 'forwards', g => g === 'F'],
  D: ['S', 'defence', 'Defence', 'defencemen', g => g === 'D']
};
const SING = { S: 'skater', G: 'goalie', F: 'forward', D: 'defenceman' };
const BROAD = ['S', 'G'], POSN = ['F', 'D', 'G'];
const AGES = [['', 'Any age'], ['u23', 'Under 23'], ['23-27', '23 to 27'], ['28-31', '28 to 31'], ['32p', '32 and over']];
const AGE_TEST = { u23: a => a < 23, '23-27': a => a >= 23 && a < 28, '28-31': a => a >= 28 && a < 32, '32p': a => a >= 32 };
/* the Broad skater view (no spec view for all skaters): the headline sets of the old player card */
const BROAD_S = [{ key: 'excellence', label: 'Value and scoring', ids: ['gar_60', 'p60', 'ixg60_all', 'icf60'] }, { key: 'production', label: 'Play driving (5v5)', ids: ['adj_xgf_pct', 'xgf60_rel', 'rapm_net', 'rapm_def'] },
  { key: 'aggregate', label: 'Value', ids: ['gar', 'war', 'p', 'g'] }];
/* totals: a bottom three says nothing useful about playing time */
const TOTALS = /^(gar|war|g|a|a1|a2|p|gp|gs|sog|iff|icf|ixg|hits|blocks|pim|fo_taken|toi5|toi|sa|ga|w|l|otl|gsax|gsax_.*|pp_p|sh_p|gax|gax_onice)$/;
const FAMILY = { gar: 'gar_rate', war: 'gar_rate', gar_60: 'gar_rate', rapm_net: 'rapm', p: 'p60', g: 'g60', gsax: 'gsax100', sv_pct_5v5: 'sv_pct', gaa: 'sv_pct' };
const fam = id => FAMILY[id] || id;

/* ── state ───────────────────────────────────────────────────────────────── */
const SC = { S: null, view: 'board', within: 'broad', bg: 'S', pg: 'F', min: null, team: '', age: '', hand: '', q: '',
  cols: '', add: [], sort: null, sortDef: null, all: false, p: '', cmp: [], x: '', y: '', color: '' };
let D = null, DK = '', TRAY = null, ROOT = null, BOARD = null, CAT = null;

function code() { return SC.within === 'pos' ? SC.pg : SC.bg; }
function grp(c) { return GROUPS[c || code()] || GROUPS.S; }
function kind(c) { return grp(c)[0]; }
function nUnit(kd) { return (kd || kind()) === 'G' ? 'min' : '5v5 min'; }
function nLong(kd) { return (kd || kind()) === 'G' ? 'minutes in net' : 'minutes at 5-on-5'; }

/* lab.json -> { S: { cols, rows, meta }, G: ... }; row = { id, name, team, pos, g (F|D|G), gp, n, age, hand, q, i, kind } */
function prep(raw) {
  const out = {};
  if (!raw || raw.ok === false) return out;
  [['S', 'skaters'], ['G', 'goalies']].forEach(x => {
    const X = raw[x[1]];
    if (!X || !Array.isArray(X.ids) || !X.data) return;
    const nCol = x[0] === 'G' ? 'toi' : 'toi5';
    const cols = (X.cols || Object.keys(X.data)).filter(c => Array.isArray(X.data[c]));
    const rows = X.ids.map((id, i) => {
      const pos = (X.pos || [])[i] || (x[0] === 'G' ? 'G' : '');
      const gpv = (X.data.gp || [])[i], nv = (X.data[nCol] || [])[i];
      return { id: String(id), name: (X.name || [])[i] || RK.playerName(id), team: (X.team || [])[i] || '', pos: pos, g: x[0] === 'G' ? 'G' : (RK.posInfo(pos).group || 'F'),
        gp: isNum(gpv) ? gpv : 0, n: isNum(nv) ? nv : 0, age: (X.age || [])[i], hand: (X.hand || [])[i] || null, q: !!(X.qualified || [])[i], i: i, kind: x[0] };
    });
    const lab = X.labels || {};
    const meta = {};
    /* the NHL EDGE product name stays in the descriptions; labels say what the metric measures (as core.js copyFix) */
    const fix = t => String(t || '').replace(/^EDGE tracking$/, 'Puck and player tracking').replace(/^EDGE /, 'Tracked ');
    cols.forEach(c => { const L = lab[c]; meta[c] = { key: c, label: L ? fix(L[0]) : c, fmt: L ? L[1] : '', lower: L ? !!L[2] : false, group: L ? fix(L[3] || 'Other') : 'Other' }; });
    const qn = rows.filter(r => r.q).map(r => r.n).filter(isNum);
    out[x[0]] = { X: X, cols: cols.filter(c => rows.some(r => isNum(X.data[c][r.i]))), rows: rows, meta: meta, floor: qn.length ? Math.floor(Math.min.apply(null, qn)) : 0 };
  });
  return out;
}
function KD(kd) { return (D || {})[kd || kind()] || { cols: [], rows: [], meta: {}, floor: 0, X: { data: {} } }; }
function val(r, id) { const g = KD(r.kind), c = g.X.data[id]; if (!c) return null; const v = c[r.i]; return isNum(v) ? v : null; }
function has(id, kd) { return !!KD(kd).X.data[id]; }

/* metric display: the spec's name and explanation, our-model tag, direction, style, the payload's format */
const LABEL_FIX = { toi_gp: 'Ice time per game' };
function mmeta(id, kd) {
  kd = kd || kind();
  const m = KD(kd).meta[id] || { key: id, label: id };
  const sm = CAT ? CAT.metric(id, 'player') : null;
  const ours = RK.ours && RK.ours.of ? RK.ours.of(id) : null;
  const label = (sm && sm.label && sm.label !== id ? sm.label : null) || LABEL_FIX[id] || m.label || id;
  const tip0 = (sm && sm.explain) || m.desc || '';
  return { id: id, label: label, short: m.label && m.label.length < label.length ? m.label : label, tip: tip0 + (ours ? (tip0 ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''),
    ours: ours, lower: !!(m.lower || (sm && sm.dir === 'lower')), style: !!(sm && sm.style), fmt: v => K().fmtV(v, m.fmt), group: m.group || 'Other' };
}

/* rows: the group past the floor (the peers), then the room's filters */
function inGroup(r, c) { const g = grp(c); return g[0] === r.kind && g[4](r.g); }
function floor(c) { return KD(kind(c)).floor || 0; }
function minNow() { return isNum(SC.min) ? SC.min : floor(); }
function peers(c) { const m = c && c !== code() ? floor(c) : minNow(); return KD(kind(c)).rows.filter(r => inGroup(r, c) && (r.n || 0) >= m); }
function keep(get) {
  if (SC.team && String(get('team')) !== SC.team) return false;
  if (SC.age) { const a = get('age'); if (!isNum(a) || !AGE_TEST[SC.age](a)) return false; }
  if (SC.hand && String(get('hand') || '') !== SC.hand) return false;
  return true;
}
function rowKeep(r) { return keep(f => (f === 'team' ? r.team : f === 'age' ? r.age : f === 'hand' ? r.hand : val(r, f))); }
function shown() { return peers().filter(rowKeep); }
function matches(r) { const q = K().fold(SC.q.trim()); return !!q && K().fold(r.name + ' ' + RK.teamAbbr(r.team)).indexOf(q) >= 0; }
const PCT = {};
function pctOf(r, id, c) {
  c = c || code();
  const key = c + '|' + minNow() + '|' + id;
  let srt = PCT[key];
  if (!srt) srt = PCT[key] = peers(c).map(x => val(x, id)).filter(isNum).sort((a, b) => a - b);
  const v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  const p = QK.pctRank(srt, v);
  return mmeta(id, kind(c)).lower ? 100 - p : p;
}
function clearPct() { Object.keys(PCT).forEach(k => delete PCT[k]); }

/* the view: the spec group's Position view with ids this payload carries for 30%+ of the peers; Broad skaters take
   the headline sets */
function view(c) {
  c = c || code();
  const g = grp(c), P = peers(c);
  const okId = id => has(id, g[0]) && P.length > 0 && P.filter(r => isNum(val(r, id))).length >= 0.3 * P.length;
  const sg = CAT && g[1] ? CAT.group(g[1]) : null;
  const v = sg && sg.view && QK.within && QK.within.view ? QK.within.view(sg, okId) : null;
  if (v) return { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(s => s.ids.length).map(s => ({ key: s.key, label: s.label, ids: s.ids })) };
  const sets = BROAD_S.map(s => ({ key: s.key, label: s.label, ids: s.ids.filter(okId) })).filter(s => s.ids.length);
  return { why: '', x: (sets[0] || { ids: [] }).ids[0], y: (sets[1] || { ids: [] }).ids[0], color: (sets[2] || { ids: [] }).ids[0] || null, sets: sets };
}
function pickDistinct(out, ids, n) {
  let k = 0;
  ids.forEach(id => { if (k >= n || out.indexOf(id) >= 0 || out.some(x => fam(x) === fam(id))) return; out.push(id); k++; });
}
function keyMetrics(v) {
  const out = [];
  if (v.sets.length === 3) { pickDistinct(out, v.sets[0].ids, 3); pickDistinct(out, v.sets[1].ids, 4); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(s => pickDistinct(out, s.ids, 3));
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders'].indexOf(q.view) >= 0 ? q.view : 'board';
  if (q.within === 'pos' && POSN.indexOf(q.pos) >= 0) { SC.within = 'pos'; SC.pg = q.pos; }
  else { SC.within = 'broad'; SC.bg = /^g/i.test(q.kind || '') ? 'G' : 'S'; }
  const mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team ? RK.canonTeam(q.team) : ''; SC.age = AGE_TEST[q.age] ? q.age : ''; SC.hand = /^[LR]$/.test(q.hand || '') ? q.hand : '';
  SC.q = q.q || ''; SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.color = q.color || '';
}
function hashNow() {
  const q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.within === 'pos') { q.within = 'pos'; q.pos = SC.pg; } else if (SC.bg === 'G') q.kind = 'g';
  if (isNum(SC.min)) q.min = SC.min;
  ['team', 'age', 'hand', 'q', 'cols'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['x', 'y', 'color'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.S && SC.S !== RK.currentSeason()) q.s = SC.S;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  return '#/scout' + (qs ? '?' + qs : '');
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }

/* ── names, links, colours ──────────────────────────────────────────────── */
function href(r) { return RK.playerHref(r.id) + (SC.S && SC.S !== RK.currentSeason() ? '' : ''); }
function teamOf(r) { return { abbr: RK.teamAbbr(r.team), colour: RK.teamColourRaw(r.team), alt: RK.teamAlt(r.team), name: RK.teamName(r.team) }; }
function posLabel(r) { return r.kind === 'G' ? 'G' : K().posLabel(r.pos); }
function subOf(r) { return [posLabel(r), RK.teamAbbr(r.team), isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · '); }
function findRow(id, kd) {
  const order = kd ? [kd, kd === 'G' ? 'S' : 'G'] : [kind(), kind() === 'G' ? 'S' : 'G'];
  for (let i = 0; i < order.length; i++) { const r = KD(order[i]).rows.find(x => x.id === String(id)); if (r) return r; }
  return null;
}
/* the group a row belongs to in the current mode */
function codeOf(r) { if (r.kind === 'G') return 'G'; if (SC.within !== 'pos') return 'S'; return r.g === 'D' ? 'D' : 'F'; }

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, params) {
  ROOT = el;
  readQuery(params.query || {});
  SC.S = Number(params.season) || RK.currentSeason();
  const tabs = [{ key: 'scout', label: 'Scouting Room', href: '#/scout' + (U.sq(SC.S) ? '?' + U.sq(SC.S) : '') }, { key: 'compare', label: 'Compare', href: '#/compare' }];
  const body = U.section(el, { section: 'scout', title: 'Scouting Room', sub: 'Every skater and goalie on every metric, judged against the same position: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare.', tabs: tabs, active: 'scout' });
  body.innerHTML = '<div class="sc"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].map(t => '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>').join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  RK.onLeave(() => { if (QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return Promise.all([RK.loadYear('lab.json', SC.S), RK.ours ? RK.ours.load() : Promise.resolve(null)]).then(res => {
    if (!U.alive(el)) return;
    CAT = res[1] || (QK.spec ? QK.spec.get('hockey') : null);
    const key = String(SC.S);
    if (DK !== key) { D = prep(res[0]); DK = key; clearPct(); }
    if (!D.S && !D.G) { document.getElementById('sc-view').innerHTML = QK.empty('Not built yet', 'The ' + RK.seasonLabel(SC.S) + ' scouting file is not available.'); document.getElementById('sc-ctl').innerHTML = ''; return; }
    if (!D[kind()]) { SC.within = 'broad'; SC.bg = D.S ? 'S' : 'G'; }
    RK.setMeta('NHL ' + RK.seasonLabel(SC.S) + ' · ' + (KD('S').rows.length + KD('G').rows.length).toLocaleString('en-GB') + ' players');
    controls();
    tabs2();
    tray();
    refresh();
    if (SC.p) { const r = findRow(SC.p); if (r) openProfile(r.id, r.kind); }
  });
}

/* a click on a player link anywhere in the room opens the drawer (a modified click follows the link) */
function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  const a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || (ROOT && !ROOT.contains(a))) return;
  const m = /#\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  const host = document.getElementById('sc-ctl');
  if (!host) return;
  const avail = c => !!D[GROUPS[c][0]];
  const fl = floor(), mx = Math.max.apply(null, KD().rows.filter(r => inGroup(r)).map(r => r.n || 0).concat([50]));
  const broadSeg = '<div class="qk-seg" id="sc-kind" role="group" aria-label="Group">' + BROAD.filter(avail).map(c => '<button type="button" data-value="' + c + '" aria-pressed="' + (SC.bg === c) + '">' + (c === 'S' ? 'Skaters' : 'Goalies') + '</button>').join('') + '</div>';
  const within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', groups: POSN.filter(avail).map(c => [c, (CAT && CAT.group(GROUPS[c][1]) && CAT.group(GROUPS[c][1]).display) || GROUPS[c][2]]), note: SC.within === 'pos' ? '' : broadSeg });
  const teams = Array.from(new Set(KD().rows.map(r => r.team).filter(Boolean))).sort((a, b) => RK.teamName(a).localeCompare(RK.teamName(b)));
  const opt = (v, t, cur) => '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>';
  const anyHand = KD().rows.some(r => r.hand), anyAge = KD().rows.some(r => isNum(r.age));
  const hands = kind() === 'G' ? [['', 'Either hand'], ['L', 'Catches left'], ['R', 'Catches right']] : [['', 'Either side'], ['L', 'Shoots left'], ['R', 'Shoots right']];
  const step = mx > 400 ? 10 : 5;
  const items = [
    { label: 'Season', html: '<select class="qk-select" id="sc-season">' + RK.seasons().map(y => opt(y, RK.seasonLabel(y), SC.S)).join('') + '</select>' },
    { label: 'Min ' + nUnit(), html: '<span class="sc-min"><input type="range" id="sc-min" min="0" max="' + (Math.ceil(mx / step) * step) + '" step="' + step + '" value="' + minNow() + '" aria-label="Minimum ' + esc(nLong()) + '"><b class="qk-sbar-v" id="sc-min-v">' + minNow() + '</b></span>', cls: 'sc-minf' },
    { label: 'Team', html: '<select class="qk-select" id="sc-team">' + opt('', 'All teams', SC.team) + teams.map(t => opt(t, RK.teamName(t), SC.team)).join('') + '</select>' },
    anyAge ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(a => opt(a[0], a[1], SC.age)).join('') + '</select>' } : null,
    anyHand ? { label: kind() === 'G' ? 'Catches' : 'Shoots', html: '<select class="qk-select" id="sc-hand">' + hands.map(a => opt(a[0], a[1], SC.hand)).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or team…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  const v = view();
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">' + esc(grp()[2]) + ' with ' + minNow() + '+ ' + esc(nLong()) + (isNum(SC.min) && SC.min !== fl ? ' (the spec floor is ' + fl + ')' : ' (the metrics spec’s floor: ' + (kind() === 'G' ? 'a quarter of the team’s minutes in net' : '250 5v5 minutes over a full season') + ', prorated to the games played)') + '</p>' +
    QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, w => {
    if (w.within === 'pos' && SC.within !== 'pos') w.pos = SC.bg === 'G' ? 'G' : 'F';
    if (w.within !== 'pos' && SC.within === 'pos') SC.bg = SC.pg === 'G' ? 'G' : 'S';
    const kd0 = kind();
    SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos;
    regroup(kd0);
  }, { id: 'sc-wn' });
  const seg = document.getElementById('sc-kind');
  if (seg) QK.seg(seg, x => { if (!GROUPS[x]) return; const kd0 = kind(); SC.bg = x; regroup(kd0); });
  const $ = id => document.getElementById(id);
  $('sc-season').onchange = e => { SC.S = parseInt(e.target.value, 10); SC.p = ''; SC.min = null; SC.cmp = []; location.hash = hashNow(); };
  $('sc-min').oninput = e => { $('sc-min-v').textContent = e.target.value; };
  $('sc-min').onchange = e => { SC.min = parseInt(e.target.value, 10); if (SC.min === floor()) SC.min = null; clearPct(); controls(); refresh(); };
  $('sc-team').onchange = e => { SC.team = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = e => { SC.age = e.target.value; refresh(); };
  if ($('sc-hand')) $('sc-hand').onchange = e => { SC.hand = e.target.value; refresh(); };
  let t = null;
  $('sc-q').oninput = e => { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
/* a new group: the minimum goes back to its floor; a new kind drops the hand, the added metrics, the sort and the
   chart's axes; a new group drops the column set (each group has its own view) */
function regroup(kd0) {
  SC.min = null; SC.cols = ''; SC.x = ''; SC.y = ''; SC.color = ''; SC.sort = null;
  if (kind() !== kd0) { SC.hand = ''; SC.add = []; }
  clearPct();
  controls();
  refresh();
}

/* ── views ───────────────────────────────────────────────────────────────── */
function tabs2() {
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
  return boardView(host);
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* "Top of the group": the leader on five of the view's metrics among the players on screen */
function topStrip() {
  const host = document.getElementById('sc-top');
  if (!host) return;
  const v = view(), rows = shown(), g = grp();
  const ids = [];
  if (v.sets.length === 3) { pickDistinct(ids, v.sets[0].ids, 2); pickDistinct(ids, v.sets[1].ids, 2); pickDistinct(ids, v.sets[2].ids, 1); }
  else v.sets.forEach(s => pickDistinct(ids, s.ids, 2));
  const items = ids.slice(0, 5).map(id => {
    const m = mmeta(id), list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
    if (!list.length) return null;
    const r = list[0], nx = list[1];
    return { sport: 'hockey', kicker: m.label, name: r.name, value: m.fmt(val(r, id)), title: RK.teamAbbr(r.team) + ' · ' + posLabel(r), next: nx ? { name: nx.name, value: m.fmt(val(nx, id)) } : null, expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  const noun = g[3];
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + (SC.within === 'pos' ? 'position' : 'group'), title: SC.within === 'pos' ? 'The best ' + noun + ', on what matters there' : 'The best ' + noun + ' right now',
    sub: 'The leader on five of the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}

/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  const k = K(), v = view(), kd = kind(), g = grp();
  const all = shown();
  const rows = SC.q.trim() ? all.filter(matches) : all;
  const P = peers();
  const sets = [{ key: 'view', label: SC.within === 'pos' ? 'Position view' : 'Headline', groups: v.sets.map(s => ({ label: s.label, ids: s.ids })) }];
  const cols = KD().cols;
  const oursIds = cols.filter(id => RK.ours && RK.ours.of(id));
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  const gnames = [];
  cols.forEach(id => { const gn = KD().meta[id].group || 'Other'; if (gnames.indexOf(gn) < 0) gnames.push(gn); });
  gnames.forEach(gn => sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: cols.filter(id => (KD().meta[id].group || 'Other') === gn) }] }));
  const setKey = sets.some(s => s.key === SC.cols) ? SC.cols : 'view';
  const ag = v.sets.length === 3 ? v.sets[2].ids : [];
  const defSort = v.color || ag[0] || (v.sets[0] || { ids: [] }).ids[0];
  const leadKeys = ['name', 'gp', 'n', 'age'];
  let sort = SC.sort && SC.sort.key && (leadKeys.indexOf(SC.sort.key) >= 0 || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: leadKeys.indexOf(sort.key) < 0 && mmeta(sort.key).lower ? 'asc' : (sort.key === 'name' ? 'asc' : 'desc') };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  const items = cols.map(id => ({ value: id, key: id, label: mmeta(id).label }));
  const addable = QK.optgroups ? QK.optgroups(items, CAT, { entity: 'player' }) : items.map(o => '<option value="' + esc(o.value) + '">' + esc(o.label) + '</option>').join('');
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    esc(g[2]) + ' · ' + esc(RK.seasonLabel(SC.S)) + ' · cells on the percentile scale against the ' + P.length + ' ' + esc(g[3]) + ' with ' + minNow() + '+ ' + esc(nLong()) + ' (blue worst, red best). Tap a name for the profile; + pins to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>' +
    (RK.ours && RK.ours.explain ? RK.ours.explain([].concat.apply([], v.sets.map(s => s.ids)).filter(id => RK.ours.of(id)).slice(0, 2), { label: id => mmeta(id).label }) : '');
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', sets: sets, set: setKey, added: SC.add.filter(id => has(id)), sort: sort, all: SC.all, page: 50, noun: g[3],
    nameLabel: kd === 'G' ? 'Goalie' : 'Skater', subLabel: 'Position · team · age',
    meta: id => mmeta(id), addable: addable,
    lead: [{ key: 'gp', label: 'GP', tip: 'Games played', fmt: row => String(row._r.gp || 0), val: row => row._r.gp },
      { key: 'n', label: kd === 'G' ? 'Min' : '5v5 min', tip: kd === 'G' ? 'Minutes in net' : 'Minutes at 5-on-5', fmt: row => k.int(row._r.n), val: row => row._r.n },
      { key: 'age', label: 'Age', fmt: row => (isNum(row._r.age) ? String(Math.floor(row._r.age)) : '—'), val: row => row._r.age }],
    rows: rows.map(r => ({ id: r.id, name: r.name, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r })),
    val: (row, id) => val(row._r, id),
    peers: P.map(r => ({ id: r.id, _r: r })),
    hl: row => SC.cmp.indexOf(row.id) >= 0,
    pin: { has: id => !!TRAY && TRAY.has(id), toggle: row => pin(row._r), label: 'Pin to the compare tray' },
    onPick: row => openProfile(row.id, row._r.kind),
    onState: st => { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'rink-' + SC.S + '-' + code().toLowerCase() + '-' + String(setKey).toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.csv',
    empty: SC.q.trim() ? 'No ' + g[3] + ' match “' + SC.q.trim() + '” with these filters.' : 'No ' + g[3] + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(SING[code()]) + ' past the floor, whatever the team, age or hand filters show; a ↓ marks a metric where lower is better (its colours are flipped), and grey cells are style (neither better nor worse). Every metric in the file is a chip or “Add a metric” away.'
  });
}

/* Chart: the Lab inside the room */
function chartView(host) {
  if (!RK.lab || !RK.lab.mount) { host.innerHTML = QK.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  const m = minNow(), c = code();
  RK.lab.mount(document.getElementById('sc-chart'), SC.S, {
    within: SC.within, bg: SC.bg, pg: SC.pg, q: SC.q, x: SC.x, y: SC.y, color: SC.color,
    keep: get => {
      const pos = get('pos'), g = kind() === 'G' ? 'G' : (RK.posInfo(pos).group || 'F');
      if (!GROUPS[c][4](g)) return false;
      const n = get(kind() === 'G' ? 'toi' : 'toi5');
      return (isNum(n) ? n : 0) >= m && keep(get);
    },
    onPick: id => openProfile(id),
    onAxes: ax => { SC.x = ax.x || ''; SC.y = ax.y || ''; SC.color = ax.color && ax.color !== 'team' ? ax.color : ''; writeQuery(); }
  });
}

/* Leaders: small multiples on the view's key metrics, each with a dot strip of the group */
function leadersView(host) {
  const v = view(), rows = shown(), g = grp(), P = peers();
  const ids = keyMetrics(v);
  const hl = r => matches(r) || r.id === SC.p;
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + g[2], title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + g[3] + ' on screen on the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics. Bars are percentiles against the ' + P.length + ' with ' + minNow() + '+ ' + nLong() + '; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map((id, i) => {
      const m = mmeta(id);
      const list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
      if (!list.length) return '';
      const item = (r, rk) => { const p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      const top = list.slice(0, 5).map((r, j) => item(r, j + 1));
      const bottom = !TOTALS.test(id) && list.length > 10 ? list.slice(-3).map((r, j) => item(r, list.length - 2 + j)) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + g[3], top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>' +
    QK.explain('<b>Totals too.</b> Season totals (points, goals, Rink value) are on the Board: pick “Production” or “Our models” and sort by any column.', { html: true });
  ids.forEach((id, i) => {
    const el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    const m = mmeta(id);
    const vals = rows.filter(r => isNum(val(r, id))).map(r => ({ v: val(r, id), name: r.name + ' · ' + RK.teamAbbr(r.team), id: r.id, hl: hl(r) }));
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + SING[code()] + ' on ' + m.label, onClick: d => openProfile(d.id) });
  });
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id, kd) {
  const r = findRow(id, kd);
  if (!r) return;
  const k = K();
  SC.p = r.id; writeQuery();
  const c = r.kind === kind() && inGroup(r) ? code() : codeOf(r);
  const g = grp(c), v = view(c), P = peers(c);
  const pr = id2 => pctOf(r, id2, c);
  const row = id2 => { const m = mmeta(id2, r.kind), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pr(id2), value: m.fmt(x), tip: m.tip, style: m.style }; };
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(row).filter(Boolean) }));
  const t = teamOf(r);
  const statIds = [v.color, v.y, v.x].filter((x, i, a) => x && a.indexOf(x) === i);
  const stats = statIds.map(id2 => { const m = mmeta(id2, r.kind), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pr(id2), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Games', value: String(r.gp || 0) });
  const simKeys = [];
  if (v.sets.length === 3) [4, 4, 2].forEach((n, i) => v.sets[i].ids.filter(x => simKeys.indexOf(x) < 0).slice(0, n).forEach(x => simKeys.push(x)));
  else v.sets.forEach(s => s.ids.slice(0, 3).forEach(x => { if (simKeys.indexOf(x) < 0) simKeys.push(x); }));
  const pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  const near = QK.within.similar(pool, r, simKeys, (rr, key) => val(rr, key), 5);
  const base = href(r);
  const cmpH = near.length ? RK.compareHref(r.id, near[0].row.id) : RK.compareHref(r.id);
  const hand = r.hand ? (r.kind === 'G' ? 'Catches ' : 'Shoots ') + (r.hand === 'L' ? 'left' : 'right') : '';
  const inPeers = P.indexOf(r) >= 0;
  const posName = r.kind === 'G' ? 'Goalie' : ({ C: 'Centre', L: 'Left wing', R: 'Right wing', D: 'Defence' }[String(r.pos).toUpperCase()] || r.pos);
  const html = QK.profile({
    kicker: posName + ' · ' + (t.name || t.abbr),
    name: r.name, href: base,
    sub: [isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', hand, (r.gp || 0) + ' GP', k.int(r.n) + ' ' + nUnit(r.kind), RK.seasonLabel(SC.S)].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: g[3] + ' with ' + floorFor(c) + '+ ' + nLong(r.kind) + (inPeers ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + K().surname(r.name) + ' · ' + g[3], items: near.map(o => ({ name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) })) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: base }, { label: 'Progression', href: base + '?view=progression' }, { label: near.length ? 'Compare with ' + K().surname(near[0].row.name) : 'Compare', href: cmpH }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(g[3]) + ' with ' + floorFor(c) + '+ ' + esc(nLong(r.kind)) + ' in ' + RK.seasonLabel(SC.S) + '. “Most like” is the nearest five on the ' + (SC.within === 'pos' ? 'position view’s' : 'group’s') + ' metrics.'
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
  if (first && first.kind !== r.kind && !TRAY.has(r.id)) TRAY.clear();     // skaters and goalies share no scale
  TRAY.toggle(r.id);
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(b => { const on = TRAY.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(id => findRow(id)), label: 'Compare tray',
    item: id => { const r = findRow(id); return r ? { name: r.name, short: K().surname(r.name), sub: posLabel(r) + ' · ' + RK.teamAbbr(r.team), colour: teamOf(r).colour } : { name: id }; },
    onChange: ids => { SC.cmp = ids; writeQuery(); },
    href: ids => '#/compare/' + ids.slice(0, 3).map(encodeURIComponent).join('/'),
    hrefLabel: 'Full compare',
    body: ids => trayBody(ids)
  });
}
function trayBody(ids) {
  const rs = ids.map(id => findRow(id)).filter(Boolean);
  if (rs.length < 2) return '';
  const k0 = rs[0].kind, codes = rs.map(codeOf), v = view(codes[0]);
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(id => {
    const m = mmeta(id, k0);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map((r, i) => { const x = r.kind === k0 ? val(r, id) : null; return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id, codes[i]) : null }; }) };
  }) }));
  return QK.trayCompare({ entities: rs.map(r => { const t = teamOf(r); return { name: r.name, short: K().surname(r.name), sub: posLabel(r) + ' · ' + t.abbr + ' · ' + (r.gp || 0) + ' GP', colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own ' + (SC.within === 'pos' ? 'position' : 'group') + '’s peers past the floor (' + RK.seasonLabel(SC.S) + '). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

RK.page('scout', render);
})(window.RK);
