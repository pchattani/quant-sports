/* The Quant Ace — the Scouting Room (#/<T>/scout): the Players page and the Lab in one page (round 9, 28 Oct 2026; the
 * Bullpen pilot, bp-scout.js, is the reference). Kit: scout.js (QK.board, QK.leaderCard, QKC.strip, QK.drawer, QK.profile,
 * QK.tray, QK.trayCompare, QK.scoutBar) and quant.js (QK.within, QK.hotRow, QK.pctlBars).
 *
 * Tennis has no positions and no teams: the groups are the surfaces. One control bar drives every view: "Compare within"
 * Broad (the tour, every surface) or Surface (hard, clay or grass: matches on that surface only, the spec's surface peer
 * groups), the season, the minimum matches (the season's qualifying floor, or the spec's surface floor), country, age
 * band (Under 21 is the Next Gen), plays (right- or left-handed, where the registry has it: ATP), and search (the Board keeps the matches; the Chart and the Leaders highlight them).
 * Under the bar, "Top of the tour": the leader on five of the view's metrics.
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips (the group's view: serve and return, results, rating;
 *            "Our models"; every payload group: Results, Serve, Return, Efficiency, Clutch, Form, Ranking, Style ...), any
 *            single metric added, cells on the percentile scale within the peers (the group past the floor), the top 50
 *            then "Show all", "Download CSV" of what is on screen;
 *   chart    the scatter Lab (lab.js, TA.lab.mount): presets, the view's axes, colour, shrink, medians, labelled
 *            corners, the ranked table and "Most like";
 *   leaders  small multiples: the view's key metrics, the top five and the bottom three as bars, over a dot strip of
 *            the whole group with the median and the highlighted players marked.
 * Selecting a player anywhere (a name, a point, a card) opens the profile drawer (?p=<pid>): percentile meters for the
 * view's metrics grouped serve and return / results / rating, the headline numbers, "Most like", and links to the player
 * page, progression, Compare and Head to head. Pin up to four (the + on a row, or "Pin" in the drawer) to the compare
 * tray (?cmp=<pid>,<pid>): side by side on percentile bars.
 * Address: ?view, within=pos&pos=hard|clay|grass, min, ctry, age (u21|21-24|25-29|30p), hand (R|L), q, cols, add (metrics, comma),
 * sort, dir, all, p, cmp, ax / ay / ac (the chart's axes and colour; ?y= stays the year), y (the season).
 * Data: data/<T>/lab.json (every player-season with 10+ tour-level matches, every metric, the surface block; loaded once
 * and shared by the views and the chart). Old routes (#/<T>/players, #/<T>/lab) redirect here (core.js).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (TA) {
'use strict';

const K = () => TA.fk;
const V = () => TA.v2;
const esc = s => TA.esc(s);
const isNum = v => typeof v === 'number' && isFinite(v);

const SURFS = ['hard', 'clay', 'grass'];
/* group code -> [label, plural noun, singular noun] */
const GROUPS = { all: ['Every surface', 'players', 'player'], hard: ['Hard courts', 'hard-court players', 'hard-court player'],
  clay: ['Clay', 'clay-courters', 'clay-courter'], grass: ['Grass', 'grass-courters', 'grass-courter'] };
const SURF_FLOOR = { hard: 10, clay: 8, grass: 5 };
const AGES = [['', 'Any age'], ['u21', 'Under 21 (Next Gen)'], ['21-24', '21 to 24'], ['25-29', '25 to 29'], ['30p', '30 and over']];
const AGE_TEST = { u21: a => a < 21, '21-24': a => a >= 21 && a < 25, '25-29': a => a >= 25 && a < 30, '30p': a => a >= 30 };
/* totals: a bottom three says nothing useful about playing time */
const TOTALS = /^(matches|wins|losses|wins_top10|titles|finals|slam_wins|upsets|upset_losses|wins_over_exp|tb_w|tb_l|dec_w|dec_l|fsd_w|blown|bagels_for|bagels_against|breadsticks_for|breadsticks_against|ret_losses|stats_matches|ch_matches|best_streak|points|race_pts|to_defend|best_rank|rank|elo_rank|proj_rank)$/;
/* ratings a surface row takes from the season's all-surface row (as lab.js) */
const SURF_COPY = /^(name|qualified|rank|age|hand|best_rank|points|elo.*)$/;
/* one metric per family on the quick reads */
const FAMILY = { hold: 'hold', hold_real: 'hold', hold_vs_exp: 'hold', spw_exp: 'hold', serve_rating: 'serve', brk: 'brk', brk_real: 'brk', rpw_exp: 'brk', return_rating: 'return',
  hold_plus_break: 'hpb', sr_total: 'hpb', win_pct: 'win', games_won_pct: 'games', sets_won_pct: 'sets', elo: 'elo', elo_peak: 'elo' };
const fam = id => FAMILY[id] || id;

/* ── state ───────────────────────────────────────────────────────────────── */
const SC = { T: 'atp', S: null, view: 'board', within: 'broad', pg: 'hard', min: null, ctry: '', age: '', hand: '', q: '',
  cols: '', add: [], sort: null, all: false, p: '', cmp: [], ax: '', ay: '', ac: '' };
let D = null, DK = '', TRAY = null, ROOT = null, BOARD = null;

function code() { return SC.within === 'pos' ? SC.pg : 'all'; }
function grp(c) { return GROUPS[c || code()] || GROUPS.all; }
function specGroup(c) { c = c || code(); return V().group(SC.T, c === 'all' ? null : c); }
function specOf(c) { const cat = V().spec; return cat && cat.group ? cat.group(specGroup(c)) : null; }

/* lab.json -> { idx, meta, metrics, years, by: { year: { all: [row], hard: [row] ... } }, skeys } ; row = { id, name, year, n,
   qualified, rank, age, a (the values in the main field layout), surf } */
function prep(raw) {
  const out = { idx: {}, meta: {}, metrics: [], years: [], by: {}, skeys: {} };
  if (!raw || raw.ok === false || !(raw.rows || []).length) return out;
  const fields = raw.fields || [];
  fields.forEach((f, i) => { if (out.idx[f] === undefined) out.idx[f] = i; });
  (raw.metrics || []).forEach(m => { out.meta[m.key] = m; });
  out.metrics = (raw.metrics || []).filter(m => out.idx[m.key] !== undefined);
  out.years = (raw.years || []).slice().map(Number).sort((a, b) => b - a);
  const I = out.idx;
  const mk = (a, y, surf) => ({ id: String(a[I.id]), name: a[I.name] || '', year: y, n: a[I.matches] || 0, qualified: !!a[I.qualified], rank: a[I.rank], age: I.age === undefined ? null : a[I.age], hand: I.hand === undefined ? null : a[I.hand], a: a, surf: surf });
  const main = {};
  (raw.rows || []).forEach(a => {
    const y = Number(a[I.year]);
    const B = out.by[y] || (out.by[y] = { all: [], hard: [], clay: [], grass: [] });
    B.all.push(mk(a, y, 'all'));
    main[a[I.id] + '|' + y] = a;
  });
  const sb = raw.surface && raw.surface.fields && (raw.surface.rows || []).length ? raw.surface : null;
  if (sb) {
    const SI = {};
    sb.fields.forEach((f, i) => { SI[f] = i; out.skeys[f] = 1; });
    fields.forEach(f => { if (SURF_COPY.test(f)) out.skeys[f] = 1; });
    sb.rows.forEach(sr => {
      const sf = sr[SI.surface], y = Number(sr[SI.year]);
      if (SURFS.indexOf(sf) < 0) return;
      const m = main[sr[SI.id] + '|' + y] || null;
      const a = fields.map((f, i) => (SI[f] !== undefined ? sr[SI[f]] : (m && SURF_COPY.test(f) ? m[i] : null)));
      const B = out.by[y] || (out.by[y] = { all: [], hard: [], clay: [], grass: [] });
      B[sf].push(mk(a, y, sf));
    });
  }
  return out;
}
function rowsOf(c) { return (((D || {}).by || {})[SC.S] || {})[c || code()] || []; }
function val(r, id) { const i = D.idx[id]; if (i === undefined) return null; const v = r.a[i]; return isNum(v) ? v : null; }
/* a metric the group's rows carry (a surface row carries only the surface block's metrics and the copied ratings) */
function has(id, c) { c = c || code(); return D.idx[id] !== undefined && (c === 'all' || !!D.skeys[id]); }

/* metric display: the spec's name and explanation, our-model tag, direction, the payload's format */
function mmeta(id) {
  const m = D.meta[id] || { key: id, label: id };
  const cat = V().spec, sm = cat ? cat.metric(id, 'player') : null;
  let label = m.label || id;
  if (sm && sm.label && sm.label !== id && !/ on (hard|clay|grass)$/.test(sm.label)) label = sm.label + (sm.unit === '%' && sm.label.indexOf('%') < 0 && !/ won$| rate$/i.test(sm.label) ? ' %' : '');
  const tip = (sm && sm.explain) || m.desc || '';
  const ours = V().ours(id);
  return { id: id, label: label, tip: tip + (ours ? (tip ? ' ' : '') + 'Our model: ' + ours.name + '.' : ''), ours: ours, lower: !!m.lower, style: !!(sm && sm.style) || m.group === 'Style',
    fmt: v => K().fmtV(v, /^(elo|elo_hard|elo_clay|elo_grass|elo_peak|avg_opp_elo)$/.test(id) ? '0' : m.fmt), group: m.group || 'Other', scope: m.scope || 'all' };
}

/* the floor: the season's qualifying floor for the tour (the fewest matches among qualified players: 20 scaled to the
   share of the season played, at least 8), or the spec's surface floor */
function floor(c) {
  c = c || code();
  if (c !== 'all') { const v = QK.within.floor(specOf(c)); return isNum(v) ? v : SURF_FLOOR[c]; }
  const q = rowsOf('all').filter(r => r.qualified).map(r => r.n);
  return q.length ? Math.min.apply(null, q) : 10;
}
function minNow() { return isNum(SC.min) ? SC.min : floor(); }
function peers(c) { const m = c && c !== code() ? floor(c) : minNow(); return rowsOf(c).filter(r => (r.n || 0) >= m); }
function ctryOf(r) { return K().country(SC.T, r.id) || ''; }
function keep(r) {
  if (SC.ctry && ctryOf(r) !== SC.ctry) return false;
  if (SC.age) { if (!isNum(r.age) || !AGE_TEST[SC.age](r.age)) return false; }
  if (SC.hand && r.hand !== SC.hand) return false;
  return true;
}
function shown() { return peers().filter(keep); }
function fold(t) { return String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function matches(r) { const q = fold(SC.q.trim()); return !!q && fold(r.name + ' ' + ctryOf(r)).indexOf(q) >= 0; }

const PCT = {};
function pctOf(r, id, c) {
  c = c || code();
  const key = SC.T + '|' + SC.S + '|' + c + '|' + (c === code() ? minNow() : floor(c)) + '|' + id;
  let srt = PCT[key];
  if (!srt) srt = PCT[key] = peers(c).map(x => val(x, id)).filter(isNum).sort((a, b) => a - b);
  const v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  const p = QK.pctRank(srt, v);
  return mmeta(id).lower ? 100 - p : p;
}
function clearPct() { Object.keys(PCT).forEach(k => delete PCT[k]); }

/* the view: the spec group's view (serve and return, results, rating) with ids this payload carries for 30%+ of the peers */
function view(c) {
  c = c || code();
  const P = peers(c);
  const okId = id => has(id, c) && P.length > 0 && P.filter(r => isNum(val(r, id))).length >= 0.3 * P.length;
  const sg = specOf(c);
  const v = sg && sg.view && QK.within.view ? QK.within.view(sg, okId) : null;
  if (v) return { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(s => s.ids.length).map(s => ({ key: s.key, label: s.label, ids: s.ids })) };
  const head = (V().set(SC.T, c === 'all' ? null : c) || []).filter(okId);
  return { why: '', x: head[0], y: head[1], color: null, sets: head.length ? [{ key: 'headline', label: 'Headline', ids: head }] : [] };
}
function pickDistinct(out, ids, n) {
  let k = 0;
  ids.forEach(id => { if (k >= n || out.indexOf(id) >= 0 || out.some(x => fam(x) === fam(id))) return; out.push(id); k++; });
}
function keyMetrics(v) {
  const out = [];
  if (v.sets.length === 3) { pickDistinct(out, v.sets[0].ids, 4); pickDistinct(out, v.sets[1].ids, 3); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(s => pickDistinct(out, s.ids, 3));
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders'].indexOf(q.view) >= 0 ? q.view : 'board';
  const w = QK.within.read(q, SURFS);
  SC.within = w.within; SC.pg = w.pos || 'hard';
  const mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.ctry = q.ctry || ''; SC.age = AGE_TEST[q.age] ? q.age : ''; SC.hand = /^[LR]$/.test(q.hand || '') ? q.hand : ''; SC.q = q.q || '';
  SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.ax = q.ax || ''; SC.ay = q.ay || ''; SC.ac = q.ac || '';
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }
function hashNow(year) {
  const q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.within === 'pos') { q.within = 'pos'; q.pos = SC.pg; }
  if (isNum(SC.min)) q.min = SC.min;
  ['ctry', 'age', 'hand', 'q', 'cols'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['ax', 'ay', 'ac'].forEach(k => { if (SC[k]) q[k] = SC[k]; });
  const Y = year || SC.S;
  if (Y && Number(Y) !== TA.currentYear(SC.T)) q.y = Y;
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  return '#/' + SC.T + '/scout' + (qs ? '?' + qs : '');
}

/* ── names and links ─────────────────────────────────────────────────────── */
function href(r) { return TA.playerHref(SC.T, r.id, SC.S); }
function subOf(r) { return [ctryOf(r), isNum(r.rank) ? 'No. ' + r.rank : '', isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · '); }
function findRow(id, c) { const list = rowsOf(c || code()); return list.find(x => x.id === String(id)) || rowsOf('all').find(x => x.id === String(id)) || null; }
function surname(n) { return K().surname(n); }

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, params, state) {
  const k = K();
  SC.T = k.T(params, state);
  SC.S = Number(params.year || TA.currentYear(SC.T));
  ROOT = el;
  readQuery(params.query || {});
  el.innerHTML = '<div class="sc ta-sc"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].map(t => '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>').join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  TA.onLeave(() => { if (QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return k.ready().then(() => Promise.all([TA.load(SC.T + '/lab.json'), k.loadNames(SC.T), V().specP])).then(res => {
    if (!k.alive(el)) return;
    if (DK !== SC.T) { D = prep(res[0]); DK = SC.T; clearPct(); }
    if (!D.years.length) { document.getElementById('sc-view').innerHTML = QK.empty('Not built yet', 'The ' + k.TN(SC.T) + ' scouting file is not available.'); document.getElementById('sc-ctl').innerHTML = ''; return; }
    if (!D.by[SC.S]) SC.S = D.years[0];
    if (SC.within === 'pos' && !rowsOf(SC.pg).length) SC.within = 'broad';
    TA.setMeta(k.TN(SC.T) + ' ' + SC.S + ' · ' + rowsOf('all').length.toLocaleString('en-GB') + ' players with 10+ tour-level matches');
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
  if (!a || a.closest('.qk-pf-acts')) return;
  const m = /#\/(?:atp|wta)\/player\/([^/?#]+)(?:\?|$)/.exec(a.getAttribute('href') || '');
  if (!m || /view=/.test(a.getAttribute('href') || '') || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  const host = document.getElementById('sc-ctl');
  if (!host) return;
  const fl = floor(), mx = Math.max.apply(null, rowsOf().map(r => r.n || 0).concat([20]));
  const within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', pos: 'Surface', groups: SURFS.filter(s => rowsOf(s).length).map(s => [s, GROUPS[s][0]]),
    note: SC.within === 'pos' ? 'Matches on ' + SC.pg + ' only' : esc(K().TN(SC.T)) + ', every surface' });
  const cs = {};
  rowsOf().forEach(r => { const c = ctryOf(r); if (c) cs[c] = (cs[c] || 0) + 1; });
  const opt = (v, t, cur) => '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>';
  const anyAge = rowsOf().some(r => isNum(r.age));
  const anyHand = rowsOf().some(r => r.hand);
  const items = [
    { label: 'Season', html: '<select class="qk-select" id="sc-season">' + D.years.map(y => opt(y, y, SC.S)).join('') + '</select>' },
    { label: 'Min matches', html: '<span class="sc-min"><input type="range" id="sc-min" min="0" max="' + (Math.ceil(mx / 5) * 5) + '" step="1" value="' + minNow() + '" aria-label="Minimum matches"><b class="qk-sbar-v" id="sc-min-v">' + minNow() + '</b></span>', cls: 'sc-minf' },
    { label: 'Country', html: '<select class="qk-select" id="sc-ctry">' + opt('', 'All countries', SC.ctry) + Object.keys(cs).sort().map(c => opt(c, c + ' (' + cs[c] + ')', SC.ctry)).join('') + '</select>' },
    anyAge ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(a => opt(a[0], a[1], SC.age)).join('') + '</select>' } : null,
    anyHand ? { label: 'Plays', html: '<select class="qk-select" id="sc-hand">' + [['', 'Either hand'], ['R', 'Right-handed'], ['L', 'Left-handed']].map(a => opt(a[0], a[1], SC.hand)).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or country…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  const v = view();
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }).replace('<b>Position view.</b>', '<b>' + (SC.within === 'pos' ? 'Surface view.' : 'Tour view.') + '</b>') : '') +
    '<p class="sc-floor">' + esc(SC.within === 'pos' ? K().TN(SC.T) + ' players with ' + minNow() + '+ matches on ' + SC.pg : K().TN(SC.T) + ' players with ' + minNow() + '+ tour-level matches') +
    (isNum(SC.min) && SC.min !== fl ? ' (the floor is ' + fl + ')' : SC.within === 'pos' ? ' (the metrics spec’s floor)' : ' (the season’s qualifying floor)') + '</p>' + QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, w => { SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos; regroup(); }, { id: 'sc-wn' });
  const $ = id => document.getElementById(id);
  $('sc-season').onchange = e => { const y = parseInt(e.target.value, 10); SC.p = ''; SC.min = null; location.hash = hashNow(y); };
  $('sc-min').oninput = e => { $('sc-min-v').textContent = e.target.value; };
  $('sc-min').onchange = e => { SC.min = parseInt(e.target.value, 10); if (SC.min === floor()) SC.min = null; clearPct(); controls(); refresh(); };
  $('sc-ctry').onchange = e => { SC.ctry = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = e => { SC.age = e.target.value; refresh(); };
  if ($('sc-hand')) $('sc-hand').onchange = e => { SC.hand = e.target.value; refresh(); };
  let t = null;
  $('sc-q').oninput = e => { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
/* a new group: the minimum goes back to its floor, the column set, the sort and the chart's axes reset */
function regroup() {
  SC.min = null; SC.cols = ''; SC.ax = ''; SC.ay = ''; SC.ac = ''; SC.sort = null;
  SC.add = SC.add.filter(id => has(id));
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
  return boardView(host);
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* "Top of the tour": the leader on five of the view's metrics among the players on screen */
function topStrip() {
  const host = document.getElementById('sc-top');
  if (!host) return;
  const v = view(), rows = shown(), g = grp();
  /* the view's metrics in order, one per family; five cards, each the true leader of its metric, preferring metrics whose
     leader is not on a card yet (one dominant player would otherwise fill the row) */
  const ids = [];
  v.sets.forEach(s => pickDistinct(ids, s.ids, 99));
  const lead = id => {
    const m = mmeta(id), list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
    return list.length ? { id: id, m: m, r: list[0], nx: list[1] } : null;
  };
  const all = ids.map(lead).filter(Boolean), picked = [], seen = {};
  all.forEach(x => { if (picked.length < 5 && !seen[x.r.id]) { picked.push(x); seen[x.r.id] = 1; } });
  all.forEach(x => { if (picked.length < 5 && picked.indexOf(x) < 0) picked.push(x); });
  picked.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
  const items = picked.map(x => ({ sport: 'tennis', kicker: x.m.label, name: x.r.name, value: x.m.fmt(val(x.r, x.id)), title: subOf(x.r),
    next: x.nx ? { name: x.nx.name, value: x.m.fmt(val(x.nx, x.id)) } : null, expl: shortTip(x.m.tip), href: href(x.r) }));
  const where = SC.within === 'pos' ? ' on ' + SC.pg : '';
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + (SC.within === 'pos' ? GROUPS[SC.pg][1] : 'tour'), title: 'The best' + where + ' in ' + SC.S + ', on what matters',
    sub: 'The leader on five of the group’s key metrics among the ' + rows.length + ' on screen (one card each for as many different leaders as the metrics allow). Tap a name for the profile.' }) + QK.hotRow(items) : '';
}

/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  const k = K(), v = view(), g = grp(), c = code();
  const all = shown();
  const rows = SC.q.trim() ? all.filter(matches) : all;
  const P = peers();
  const sets = [{ key: 'view', label: SC.within === 'pos' ? 'Surface view' : 'Tour view', groups: v.sets.map(s => ({ label: s.label, ids: s.ids })) }];
  const avail = D.metrics.filter(m => has(m.key) && rowsOf().some(r => isNum(val(r, m.key))));
  const oursIds = avail.filter(m => V().ours(m.key)).map(m => m.key);
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  const gnames = [];
  avail.forEach(m => { if (gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(gn => sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: avail.filter(m => (m.group || 'Other') === gn).map(m => m.key) }] }));
  const setKey = sets.some(s => s.key === SC.cols) ? SC.cols : 'view';
  const defSort = v.color || ((v.sets[0] || { ids: [] }).ids[0]);
  let sort = SC.sort && SC.sort.key && (['name', 'n', 'age', 'rank'].indexOf(SC.sort.key) >= 0 || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: sort.key === 'rank' || (['name', 'n', 'age'].indexOf(sort.key) < 0 && mmeta(sort.key).lower) ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  const addable = V().picker(avail, '', k.groups, m => (m.scope === 'wta_stats' ? ' ·stats' : m.scope === 'charted' ? ' ·charted' : ''));
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    esc(k.TN(SC.T)) + ' · ' + esc(g[0]) + ' · ' + SC.S + ' · cells on the percentile scale against the ' + P.length + ' ' + esc(g[1]) + ' with ' + minNow() + '+ matches' + (c === 'all' ? '' : ' on ' + c) + ' (blue worst, red best). Tap a name for the profile; + pins to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>' +
    QK.oursExplain('Elo (overall and by surface) and the serve and return model are ours: the model reads hold and break rates from set scores against the quality of the opposition, and the ratings put them on one scale (0 = tour average). Columns tagged ' + QK.ours({ short: true }) + ' come from them; hover a head for what it measures.');
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', sets: sets, set: setKey, added: SC.add.filter(id => has(id)), sort: sort, all: SC.all, page: 50, noun: g[1],
    nameLabel: 'Player', subLabel: 'Country · ranking · age',
    meta: id => mmeta(id),
    addable: addable,
    lead: [{ key: 'n', label: c === 'all' ? 'Matches' : 'Matches (' + c + ')', tip: 'Tour-level main-draw matches' + (c === 'all' ? '' : ' on ' + c), fmt: row => k.int(row._r.n), val: row => row._r.n },
      { key: 'rank', label: 'Rank', tip: 'Official ranking at the player’s last tour-level match of the season', fmt: row => (isNum(row._r.rank) ? String(row._r.rank) : '—'), val: row => (isNum(row._r.rank) ? -row._r.rank : null) },
      { key: 'age', label: 'Age', fmt: row => (isNum(row._r.age) ? String(Math.floor(row._r.age)) : '—'), val: row => row._r.age }],
    rows: rows.map(r => ({ id: r.id, name: r.name, sub: subOf(r), href: href(r), _r: r })),
    val: (row, id) => val(row._r, id),
    peers: P.map(r => ({ id: r.id, _r: r })),
    hl: row => SC.cmp.indexOf(row.id) >= 0,
    pin: { has: id => !!TRAY && TRAY.has(id), toggle: row => pin(row._r), label: 'Pin to the compare tray' },
    onPick: row => openProfile(row.id),
    onState: st => { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'ace-' + SC.T + '-' + SC.S + '-' + c + '-' + String(setKey).toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.csv',
    empty: SC.q.trim() ? 'No players match “' + SC.q.trim() + '” with these filters.' : 'No players pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(g[2]) + ' past the floor, whatever the country, age or search filters show; a ↓ marks a metric where lower is better (its colours are flipped), and style metrics (rally length, net approaches ...) are neither better nor worse. Hold and break are inferred from set scores; real serve statistics are WTA only (2016 on, not the Slams) and style metrics need charted matches. Every metric in the file is a chip or “Add a metric” away.'
  });
}

/* Chart: the Lab inside the room */
function chartView(host) {
  if (!TA.lab || !TA.lab.mount) { host.innerHTML = QK.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  TA.lab.mount(document.getElementById('sc-chart'), SC.T, {
    year: SC.S, within: SC.within, surf: SC.within === 'pos' ? SC.pg : 'all', min: minNow(), q: SC.q, x: SC.ax, y: SC.ay, color: SC.ac,
    keep: r => keepRaw(r),
    onPick: id => openProfile(id),
    onAxes: ax => { SC.ax = ax.x || ''; SC.ay = ax.y || ''; SC.ac = ax.color && ax.color !== 'country' ? ax.color : ''; writeQuery(); }
  });
}
/* the room's country and age filters on the lab's raw rows (id at the lab's own index) */
function keepRaw(a) {
  const id = String(a[D.idx.id]);
  if (SC.ctry && K().country(SC.T, id) !== SC.ctry) return false;
  if (SC.age) { const ag = D.idx.age === undefined ? null : a[D.idx.age]; if (!isNum(ag) || !AGE_TEST[SC.age](ag)) return false; }
  if (SC.hand && (D.idx.hand === undefined || a[D.idx.hand] !== SC.hand)) return false;
  return true;
}

/* Leaders: small multiples on the view's key metrics, each with a dot strip of the group */
function leadersView(host) {
  const v = view(), rows = shown(), g = grp(), P = peers();
  const ids = keyMetrics(v);
  const hl = r => matches(r) || r.id === SC.p;
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + K().TN(SC.T) + ' · ' + g[0], title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + g[1] + ' on screen on the group’s key metrics. Bars are percentiles against the ' + P.length + ' with ' + minNow() + '+ matches; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map((id, i) => {
      const m = mmeta(id);
      const list = rows.filter(r => isNum(val(r, id))).sort((a, b) => (m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id)));
      if (!list.length) return '';
      const item = (r, rk) => { const p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p }; };
      const top = list.slice(0, 5).map((r, j) => item(r, j + 1));
      const bottom = !TOTALS.test(id) && list.length > 10 ? list.slice(-3).map((r, j) => item(r, list.length - 2 + j)) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + g[1], top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach((id, i) => {
    const el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    const m = mmeta(id);
    const vals = rows.filter(r => isNum(val(r, id))).map(r => ({ v: val(r, id), name: r.name + (ctryOf(r) ? ' · ' + ctryOf(r) : ''), id: r.id, hl: hl(r) }));
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + g[2] + ' on ' + m.label, onClick: d => openProfile(d.id) });
  });
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id) {
  const r = findRow(id);
  if (!r) return;
  const k = K();
  SC.p = r.id; writeQuery();
  const c = r.surf, g = grp(c), v = view(c), P = peers(c);
  const row = id2 => { const m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2, c), value: m.fmt(x), tip: m.tip, style: m.style }; };
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(row).filter(Boolean) }));
  const statIds = [v.color, v.x, v.y].filter((x, i, a) => x && a.indexOf(x) === i);
  const stats = statIds.map(id2 => { const m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2, c), tip: m.tip } : null; }).filter(Boolean);
  const w = val(r, 'wins'), l = val(r, 'losses');
  stats.push({ label: c === 'all' ? 'Record' : 'Record on ' + c, value: isNum(w) && isNum(l) ? w + '-' + l : k.int(r.n) + ' matches' });
  const simKeys = [];
  if (v.sets.length === 3) [4, 3, 2].forEach((n, i) => v.sets[i].ids.filter(x => simKeys.indexOf(x) < 0).slice(0, n).forEach(x => simKeys.push(x)));
  else v.sets.forEach(s => s.ids.slice(0, 3).forEach(x => { if (simKeys.indexOf(x) < 0) simKeys.push(x); }));
  const pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  const near = QK.within.similar(pool, r, simKeys, (rr, key) => val(rr, key), 5);
  const base = href(r), more = TA.playerHref(SC.T, r.id) + '?view=progression';
  const inPeers = P.indexOf(r) >= 0;
  const html = QK.profile({
    kicker: K().TN(SC.T) + ' · ' + (c === 'all' ? 'every surface' : c) + ' · ' + SC.S,
    name: r.name, href: base,
    sub: [ctryOf(r), isNum(r.rank) ? 'No. ' + r.rank : '', isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', r.hand === 'L' ? 'Left-handed' : r.hand === 'R' ? 'Right-handed' : '', k.int(r.n) + ' matches' + (c === 'all' ? '' : ' on ' + c)].filter(Boolean).join(' · '),
    team: { colour: '#5a69b7' }, stats: stats,   /* the tennis rule: no team colours, the player's block is ours in cobalt */
    peer: g[1] + ' with ' + (c === code() ? minNow() : floor(c)) + '+ matches' + (inPeers ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + surname(r.name) + ' · ' + g[1], items: near.map(o => ({ name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) })) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: base }, { label: 'Progression', href: more },
      { label: near.length ? 'Compare with ' + surname(near[0].row.name) : 'Compare', href: near.length ? TA.compareHref(SC.T, r.id, near[0].row.id) : TA.compareHref(SC.T, r.id) },
      { label: 'Head to head', href: TA.h2hHref(SC.T, r.id) }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(g[1]) + ' with ' + (c === code() ? minNow() : floor(c)) + '+ matches in ' + SC.S + '. “Most like” is the nearest five on the group’s serve and return, results and rating.'
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
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(id => findRow(id)), label: 'Compare tray',
    item: id => { const r = findRow(id); return r ? { name: r.name, short: surname(r.name), sub: [ctryOf(r), isNum(r.rank) ? 'No. ' + r.rank : ''].filter(Boolean).join(' · ') } : { name: id }; },
    onChange: ids => { SC.cmp = ids; writeQuery(); },
    href: ids => TA.compareHref(SC.T, ids[0], ids[1]) + (ids[2] ? '?c=' + encodeURIComponent(ids[2]) : ''),
    hrefLabel: 'Full compare',
    body: ids => trayBody(ids)
  });
}
function trayBody(ids) {
  const rs = ids.map(id => findRow(id)).filter(Boolean);
  if (rs.length < 2) return '';
  const c = rs[0].surf, v = view(c);
  const groups = v.sets.map(s => ({ label: s.label, rows: s.ids.map(id => {
    const m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(r => { const x = val(r, id); return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id, r.surf) : null }; }) };
  }) }));
  return QK.trayCompare({ entities: rs.map(r => ({ name: r.name, short: surname(r.name), sub: [ctryOf(r), K().int(r.n) + ' matches'].join(' · '), href: href(r) })),
    groups: groups, note: 'Percentiles: each player against the ' + grp(c)[1] + ' past the floor (' + SC.S + (c === 'all' ? '' : ', ' + c + ' only') + '). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

TA.scout = { render: render };
if (typeof TA.route === 'function') TA.route('scout', render);
})(window.TA || (window.TA = {}));
