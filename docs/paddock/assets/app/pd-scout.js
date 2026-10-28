/* The Quant Paddock — the Scouting Room (#/scout): the Drivers list and the Lab in one page (round 9, 28 Oct 2026; the
 * Bullpen pilot bp-scout.js is the reference). Kit: scout.js (QK.board, QK.leaderCard, QKC.strip, QK.drawer, QK.profile,
 * QK.tray, QK.trayCompare, QK.scoutBar) and quant.js (QK.within, QK.hotRow, QK.pctlBars).
 *
 * F1 has one peer group: every race driver of the season with the starts floor (f1.json "drivers"; PD.v2.floors). One
 * control bar drives every view: "Compare within" Broad (the headline set: against the team-mate, against the field) or
 * Position (the driver view: what makes a driver excellent with the car taken out, racecraft, then results and value;
 * the spec has no view block for F1, so the site names the three sets), the season (2018 on, lab.json), the minimum
 * starts (the spec floor), constructor, age band (lab.json `age`: age on 1 July of the season), and search. Under the
 * bar, "Top of the grid": the leader on five of the view's metrics.
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips (the view, our models, every lab.json group), any metric
 *            added, percentile cells against the peers, the top 50 then "Show all", "Download CSV";
 *   chart    the Lab (lab.js, PD.lab.mount): presets, any two metrics, size, colour, shrink, medians, the ranked table;
 *   leaders  small multiples: the top five and the bottom three on the view's key metrics over a dot strip of the grid;
 *   alltime  the hall of fame and the greatest seasons by our driver model since 1950 (the team-mate Elo, hall_of_fame.json:
 *            round 9, Phase 4), then the all-time Elo boards (peak against the field), moved here from the Drivers list.
 * Selecting a driver anywhere (a name, a point, a card) opens the profile drawer (?p=<id>): percentile meters for the
 * view's sets, headline numbers, "Most like" and links to the driver page, progression and Compare. Pin up to four (the +
 * on a row, or the drawer's button) to the compare tray (?cmp=<id>,<id>): side by side on percentile bars; "Full compare"
 * opens #/compare/drivers/<a>/<b>.
 * Address: ?view, within=pos, s (season), min, team, age (u23|23-27|28-32|33p), q, cols, add, sort, dir, all, p, cmp, x,
 * y, color (the chart's axes): links share. Old routes (#/drivers[/<y>], #/lab?x=&y=&q=, #/compare[/drivers[/<a>]])
 * redirect here (core.js ROUTE_MAP).
 * Data: lab.json (every driver-season since 2018 with every catalogue metric, loaded once and shared by the views),
 * <s>/season.json (rounds done, for the floor), elo.json (the All-time view).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;

/* the driver view (the Position default view's shape: excellence, production, aggregate) */
var VIEW = {
  why: 'F1 hides the driver inside the car. The driver view leads with what takes the car out (pace and head-to-heads against the team-mate), then racecraft against the field, then points and Elo.',
  sets: [
    { key: 'excellence', label: 'The car taken out', ids: ['driver_effect', 'quali_driver_effect', 'race_h2h', 'quali_h2h', 'race_pace_tm_delta', 'elo_teammate'] },
    { key: 'production', label: 'Racecraft', ids: ['race_pace', 'lap1_gain', 'net_overtakes', 'pos_gained', 'tyre_mgmt', 'consistency'] },
    { key: 'aggregate', label: 'Results and value', ids: ['points_per_race', 'team_points_share', 'points_v_expected', 'elo'] }
  ],
  x: 'driver_effect', y: 'race_pace', color: 'points_per_race'
};
var AGES = [['', 'Any age'], ['u23', 'Under 23'], ['23-27', '23 to 27'], ['28-32', '28 to 32'], ['33p', '33 and over']];
var AGE_TEST = { u23: function (a) { return a < 23; }, '23-27': function (a) { return a >= 23 && a < 28; }, '28-32': function (a) { return a >= 28 && a < 33; }, '33p': function (a) { return a >= 33; } };
/* totals: a bottom three says nothing about them */
var TOTALS = /^(wins|podiums|poles|points|laps_led|fastest_laps|penalties|dnfs?|dnf_\w+|dns|sprint_points|overtakes_made|overtakes_suffered|races)$/;
var FAMILY = { race_h2h: 'h2h', race_pace_h2h: 'h2h', quali_h2h: 'qh2h', quali_gap_tm_pct: 'qh2h', race_pace_tm_delta: 'driver_effect', points_rate: 'points_per_race', elo: 'elo_teammate' };
function fam(id) { return FAMILY[id] || id; }

/* ── state ───────────────────────────────────────────────────────────────── */
var SC = { view: 'board', within: 'broad', S: null, min: null, team: '', age: '', q: '', cols: '', add: [], sort: null, sortDef: null, all: false, p: '', cmp: [], x: '', y: '', color: '' };
var LAB = null, ROWS = [], META = {}, METRICS = [], SEASON = null, TRAY = null, ROOT = null, BOARD = null;

function V() { return PD.v2; }
function floor() { return V().floors(SEASON, 'drivers').n; }
function minNow() { return isNum(SC.min) ? SC.min : floor(); }

/* lab.json -> rows of one season: { id, name, team, year, n (starts), age, a (the raw array) } */
function prep(raw) {
  var idx = {};
  (raw.fields || []).forEach(function (f, i) { if (idx[f] === undefined) idx[f] = i; });
  var meta = {};
  (raw.metrics || []).forEach(function (m) { meta[m.key] = m; });
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(function (m) { return idx[m.key] !== undefined; }), rows: raw.rows || [],
    years: (raw.rows || []).map(function (r) { return r[idx.year]; }).filter(function (v, i, a) { return isNum(v) && a.indexOf(v) === i; }).sort(function (a, b) { return b - a; }) };
}
function seasonRows() {
  var I = LAB.idx;
  return LAB.rows.filter(function (r) { return r[I.year] === SC.S; }).map(function (r) {
    return { id: String(r[I.driver]), name: r[I.name] || PD.driverName(r[I.driver]), team: r[I.team] || '', year: r[I.year], n: r[I.races] || 0, age: I.age !== undefined ? r[I.age] : null, a: r };
  });
}
function val(r, id) { var i = LAB.idx[id]; if (i === undefined) return null; var v = r.a[i]; return isNum(v) ? v : null; }
function has(id) { return LAB && LAB.idx[id] !== undefined && METRICS.some(function (m) { return m.key === id; }); }

/* metric display: the spec's names and explanations (PD.v2), our-model tag, direction, the payload's format */
function mmeta(id) {
  var m = LAB.meta[id] || {}, o = V().ours(id);
  var label = V().label(LAB.meta, id);
  return { id: id, label: label, short: label, tip: V().tip(LAB.meta, id), ours: o ? { name: o.name, about: o.about } : null, lower: !!m.lower, style: false,
    fmt: function (v) { return m.fmt === 'prob' ? PD.pct(v, 0) : PD.fmtVal(v, m.fmt); }, group: m.group || 'Other' };
}

/* peers: the season's drivers with the floor of starts; shown: the peers through the room's filters */
function peers() { var m = minNow(); return ROWS.filter(function (r) { return r.n >= m; }); }
function keepRow(r) {
  if (SC.team && r.team !== SC.team) return false;
  if (SC.age) { if (!isNum(r.age) || !AGE_TEST[SC.age](r.age)) return false; }
  return true;
}
function shown() { return peers().filter(keepRow); }
function fold(s) { return String(s || '').toLowerCase().normalize ? String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '') : String(s || '').toLowerCase(); }
function matches(r) { var q = fold(SC.q.trim()); return !!q && fold(r.name + ' ' + PD.teamName(r.team) + ' ' + PD.driverCode(r.id)).indexOf(q) >= 0; }
var PCT = {};
function pctOf(r, id) {
  var key = SC.S + '|' + minNow() + '|' + id;
  var srt = PCT[key];
  if (!srt) srt = PCT[key] = peers().map(function (x) { return val(x, id); }).filter(isNum).sort(function (a, b) { return a - b; });
  var v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  var p = QK.pctRank(srt, v);
  return mmeta(id).lower ? 100 - p : p;
}
function clearPct() { Object.keys(PCT).forEach(function (k) { delete PCT[k]; }); }

/* the view: Position = the driver view; Broad = the headline set (PD.v2.DRIVER_SET), ids the season carries for 30%+ */
function view() {
  var P = peers();
  var ok = function (id) { return has(id) && P.length > 0 && P.filter(function (r) { return isNum(val(r, id)); }).length >= 0.3 * P.length; };
  if (SC.within === 'pos') return { why: VIEW.why, x: VIEW.x, y: VIEW.y, color: VIEW.color, sets: VIEW.sets.map(function (s) { return { key: s.key, label: s.label, ids: s.ids.filter(ok) }; }).filter(function (s) { return s.ids.length; }) };
  var sets = V().DRIVER_SET.map(function (g, i) { return { key: 'h' + i, label: g[0], ids: g[1].filter(ok) }; }).filter(function (s) { return s.ids.length; });
  return { why: '', x: 'driver_effect', y: 'race_pace', color: 'points_per_race', sets: sets };
}
function pickDistinct(out, ids, n) {
  var k = 0;
  ids.forEach(function (id) { if (k >= n || out.indexOf(id) >= 0 || out.some(function (x) { return fam(x) === fam(id); })) return; out.push(id); k++; });
}
function keyMetrics(v) {
  var out = [];
  if (v.sets.length === 3) { pickDistinct(out, v.sets[0].ids, 3); pickDistinct(out, v.sets[1].ids, 4); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(function (s) { pickDistinct(out, s.ids, 4); });
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders', 'alltime'].indexOf(q.view) >= 0 ? q.view : 'board';
  SC.within = q.within === 'pos' ? 'pos' : 'broad';
  var s = parseInt(q.s, 10); SC.S = isNaN(s) ? null : s;
  var mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team || ''; SC.age = AGE_TEST[q.age] ? q.age : ''; SC.q = q.q || ''; SC.cols = q.cols || '';
  SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.color = q.color || '';
}
function hashNow() {
  var q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.within === 'pos') q.within = 'pos';
  if (SC.S && SC.S !== PD.currentSeason()) q.s = SC.S;
  if (isNum(SC.min)) q.min = SC.min;
  ['team', 'age', 'q', 'cols'].forEach(function (k) { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['x', 'y', 'color'].forEach(function (k) { if (SC[k]) q[k] = SC[k]; });
  return '#/scout' + PD.qs(q);
}
function writeQuery() { PD.setHashQuiet(hashNow()); }

/* ── names, links, colours ──────────────────────────────────────────────── */
function href(r) { return PD.driverHref(r.id, r.year); }
function teamOf(r) { return { abbr: PD.teamAbbr(r.team), colour: PD.teamColourRaw(r.team) || '', alt: PD.teamAlt(r.team) || '', name: PD.teamName(r.team) }; }
function subOf(r) { return [PD.teamAbbr(r.team), isNum(r.age) ? 'age ' + r.age : '', r.n + ' start' + (r.n === 1 ? '' : 's')].filter(Boolean).join(' · '); }
function findRow(id) { for (var i = 0; i < ROWS.length; i++) if (ROWS[i].id === String(id)) return ROWS[i]; return null; }
function surname(n) { var w = String(n || '').split(' '); return w[w.length - 1]; }

/* ── render ──────────────────────────────────────────────────────────────── */
function render(el, params) {
  ROOT = el;
  readQuery(params.query || {});
  var tabs = [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders'], ['alltime', 'All-time']];
  el.innerHTML = PD.pageHead('Scouting Room', 'Every driver, every number', '<span id="sc-meta">Loading…</span>') +
    '<div class="sc"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the grid"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    tabs.map(function (t) { return '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>'; }).join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  PD.onLeave(function () { if (QK.drawer && QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return PD.load('lab.json').then(function (raw) {
    if (!PD.alive(el)) return null;
    if (!raw || raw.ok === false || !(raw.rows || []).length) { PD.set('sc-view', QK.empty('Not built yet', 'The scouting file (lab.json) is not available.')); PD.set('sc-ctl', ''); return null; }
    if (!LAB) LAB = prep(raw);
    if (!SC.S || LAB.years.indexOf(SC.S) < 0) SC.S = LAB.years.indexOf(PD.currentSeason()) >= 0 ? PD.currentSeason() : LAB.years[0];
    PD.setYear(SC.S, true);
    return Promise.all([PD.load(SC.S + '/season.json'), PD.v2.specP]);
  }).then(function (res) {
    if (!res || !PD.alive(el)) return;
    SEASON = PD.ok(res[0]) ? res[0] : null;
    ROWS = seasonRows();
    METRICS = LAB.metrics.filter(function (m) { return ROWS.some(function (r) { return isNum(val(r, m.key)); }); });
    clearPct();
    PD.set('sc-meta', SC.S + ' · ' + ROWS.length + ' drivers who started a race · ' + METRICS.length + ' metrics each, from our models and the timing data');
    controls();
    tabs2();
    tray();
    refresh();
    if (SC.p && findRow(SC.p)) openProfile(SC.p);
  });
}

/* a click on a driver link anywhere in the room opens the drawer (a modified click follows the link) */
function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  var a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || (a.closest && a.closest('.sc-alltime'))) return;
  var m = /#\/driver\/([^/?#]+)(?:\/(\d{4}))?/.exec(a.getAttribute('href') || '');
  if (!m) return;
  var id = decodeURIComponent(m[1]);
  if (m[2] && parseInt(m[2], 10) !== SC.S) return;
  if (!findRow(id)) return;
  ev.preventDefault();
  openProfile(id);
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  var host = document.getElementById('sc-ctl');
  if (!host) return;
  var fl = floor(), mx = Math.max.apply(null, ROWS.map(function (r) { return r.n; }).concat([10]));
  var opt = function (v, t, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>'; };
  var teams = ROWS.map(function (r) { return r.team; }).filter(function (t, i, a) { return t && a.indexOf(t) === i; }).sort(function (a, b) { return PD.teamName(a).localeCompare(PD.teamName(b)); });
  var anyAge = ROWS.some(function (r) { return isNum(r.age); });
  var within = QK.within.html({ within: SC.within, pos: 'drivers' }, { id: 'sc-wn', groups: [['drivers', 'Race drivers (one group)']], broad: 'Broad', pos: 'Position',
    note: SC.within === 'pos' ? 'F1 has one peer group: the driver view reorders the numbers, the peers stay the same.' : 'The headline set: against the team-mate, then against the field.' });
  var items = [
    { label: 'Season', html: '<select class="qk-select" id="sc-season">' + LAB.years.map(function (y) { return opt(y, y, SC.S); }).join('') + '</select>' },
    { label: 'Min starts', html: '<span class="sc-min"><input type="range" id="sc-min" min="1" max="' + mx + '" step="1" value="' + minNow() + '" aria-label="Minimum starts"><b class="qk-sbar-v" id="sc-min-v">' + minNow() + '</b></span>', cls: 'sc-minf' },
    { label: 'Constructor', html: '<select class="qk-select" id="sc-team">' + opt('', 'All constructors', SC.team) + teams.map(function (t) { return opt(t, PD.teamName(t), SC.team); }).join('') + '</select>' },
    anyAge ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(function (a) { return opt(a[0], a[1], SC.age); }).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Driver or constructor…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  var v = view();
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">Drivers with ' + minNow() + '+ starts in ' + SC.S + (isNum(SC.min) && SC.min !== fl ? ' (the spec floor is ' + fl + ')' : ' (the metrics spec’s floor' + (SEASON && !SEASON.finished && SEASON.championship ? ', scaled to the rounds run so far' : '') + ')') + '</p>' +
    QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: 'drivers' }, function (w) { SC.within = w.within; SC.cols = ''; SC.sort = null; clearPct(); controls(); refresh(); }, { id: 'sc-wn' });
  var $ = function (id) { return document.getElementById(id); };
  $('sc-season').onchange = function (e) { SC.S = parseInt(e.target.value, 10); SC.p = ''; SC.min = null; SC.team = ''; location.hash = hashNow(); };
  $('sc-min').oninput = function (e) { $('sc-min-v').textContent = e.target.value; };
  $('sc-min').onchange = function (e) { SC.min = parseInt(e.target.value, 10); if (SC.min === floor()) SC.min = null; clearPct(); controls(); refresh(); };
  $('sc-team').onchange = function (e) { SC.team = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = function (e) { SC.age = e.target.value; refresh(); };
  var t = null;
  $('sc-q').oninput = function (e) { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}

/* ── views ───────────────────────────────────────────────────────────────── */
function tabs2() {
  var bar = ROOT.querySelector('.sc-tabs');
  var all = QK.$$('[role="tab"]', bar);
  function select(v) {
    SC.view = v;
    all.forEach(function (b) { var on = b.getAttribute('data-view') === v; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
    document.getElementById('sc-view').setAttribute('aria-labelledby', 'sc-tab-' + v);
    drawView();
  }
  all.forEach(function (b, i) {
    b.addEventListener('click', function () { select(b.getAttribute('data-view')); });
    b.addEventListener('keydown', function (e) {
      var j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : null;
      if (j === null) return;
      e.preventDefault();
      var n = all[(j + all.length) % all.length]; n.focus(); select(n.getAttribute('data-view'));
    });
  });
}
function refresh() {
  if (!ROOT || !ROOT.isConnected) return;
  topStrip();
  drawView();
}
function drawView() {
  writeQuery();
  var host = document.getElementById('sc-view');
  if (!host) return;
  BOARD = null;
  ['sc-ctl', 'sc-top'].forEach(function (id) { var n = document.getElementById(id); var box = n ? (n.closest('.sc-ctl') || n) : null; if (box) box.style.display = SC.view === 'alltime' ? 'none' : ''; });
  if (SC.view === 'alltime') return allTime(host);
  if (SC.view === 'chart') return chartView(host);
  if (SC.view === 'leaders') return leadersView(host);
  return boardView(host);
}

/* "Top of the grid": the leader on five of the view's metrics among the drivers on screen */
function topStrip() {
  var host = document.getElementById('sc-top');
  if (!host) return;
  var v = view(), rows = shown(), ids = [];
  if (v.sets.length === 3) { pickDistinct(ids, v.sets[0].ids, 2); pickDistinct(ids, v.sets[1].ids, 2); pickDistinct(ids, v.sets[2].ids, 1); }
  else v.sets.forEach(function (s) { pickDistinct(ids, s.ids, 3); });
  var items = ids.slice(0, 5).map(function (id) {
    var m = mmeta(id), list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
    if (!list.length) return null;
    var r = list[0], nx = list[1];
    return { sport: 'f1', kicker: m.label, name: r.name, value: m.fmt(val(r, id)), title: PD.teamAbbr(r.team) + ' · ' + r.n + ' starts', next: nx ? { name: nx.name, value: m.fmt(val(nx, id)) } : null,
      expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the grid', title: SC.within === 'pos' ? 'The best drivers, with the car taken out' : 'The best drivers right now', sub: 'The leader on five of the view’s key metrics among the ' + rows.length + ' drivers on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  var v = view(), all = shown();
  var rows = SC.q.trim() ? all.filter(matches) : all;
  var P = peers();
  var sets = [{ key: 'view', label: SC.within === 'pos' ? 'Driver view' : 'Headline', groups: v.sets.map(function (s) { return { label: s.label, ids: s.ids }; }) }];
  var oursIds = METRICS.filter(function (m) { return V().ours(m.key); }).map(function (m) { return m.key; });
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  var gnames = [];
  METRICS.forEach(function (m) { if (gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(function (gn) { sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: METRICS.filter(function (m) { return (m.group || 'Other') === gn; }).map(function (m) { return m.key; }) }] }); });
  var setKey = sets.some(function (s) { return s.key === SC.cols; }) ? SC.cols : 'view';
  var defSort = v.color && has(v.color) ? v.color : ((v.sets[0] || { ids: [] }).ids[0]);
  var sort = SC.sort && SC.sort.key && (SC.sort.key === 'name' || SC.sort.key === 'n' || SC.sort.key === 'age' || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: sort.key !== 'name' && sort.key !== 'n' && sort.key !== 'age' && mmeta(sort.key).lower ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  var addable = V().picker(METRICS.map(function (m) { return { key: m.key, label: mmeta(m.key).label, group: m.group, lower: m.lower }; }), '', 'driver');
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    'Drivers · ' + SC.S + ' · cells on the percentile scale against the ' + P.length + ' drivers with ' + minNow() + '+ starts (blue worst, red best). Tap a name for the profile; + pins to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>' +
    '<div class="pd-ours">' + QK.oursExplain('The driver ratings (race and qualifying pace against the team-mate, the car taken out), race and qualifying pace against the field, Elo and points against our forecast come from our models; columns tagged ' + QK.ours({ short: true }) + ' are theirs.') + '</div>';
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', sets: sets, set: setKey, added: SC.add.filter(has), sort: sort, all: SC.all, page: 50, noun: 'drivers',
    nameLabel: 'Driver', subLabel: 'Constructor · age · starts',
    meta: mmeta, addable: addable,
    lead: [{ key: 'n', label: 'Starts', tip: 'Grand Prix starts this season', fmt: function (row) { return String(row._r.n); }, val: function (row) { return row._r.n; } },
      { key: 'age', label: 'Age', tip: 'Age on 1 July of the season', fmt: function (row) { return isNum(row._r.age) ? String(row._r.age) : '—'; }, val: function (row) { return row._r.age; } }],
    rows: rows.map(function (r) { return { id: r.id, name: r.name, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r }; }),
    val: function (row, id) { return val(row._r, id); },
    peers: P.map(function (r) { return { id: r.id, _r: r }; }),
    hl: function (row) { return SC.cmp.indexOf(row.id) >= 0; },
    pin: { has: function (id) { return !!TRAY && TRAY.has(id); }, toggle: function (row) { pin(row._r); }, label: 'Pin to the compare tray' },
    onPick: function (row) { openProfile(row.id); },
    onState: function (st) { SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery(); },
    csv: 'paddock-' + SC.S + '-drivers-' + String(setKey).toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.csv',
    empty: SC.q.trim() ? 'No driver matches “' + SC.q.trim() + '” with these filters.' : 'No driver passes these filters: lower the minimum starts or clear a filter.',
    note: 'Percentiles are against every driver past the floor, whatever the constructor or age filter shows; a ↓ marks a metric where lower is better (its colours are flipped). Every metric in the file is a chip or “Add a metric” away.'
  });
}

/* Chart: the Lab inside the room */
function chartView(host) {
  if (!PD.lab || !PD.lab.mount) { host.innerHTML = QK.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  var v = view();
  PD.lab.mount(document.getElementById('sc-chart'), {
    year: SC.S, min: minNow(), q: SC.q, x: SC.x || (SC.within === 'pos' ? v.x : ''), y: SC.y || (SC.within === 'pos' ? v.y : ''), color: SC.color,
    keep: function (o) { return keepRow({ team: o.team, age: o.age }); },
    onPick: function (id, y) { if (y === SC.S && findRow(id)) openProfile(id); else location.hash = PD.driverHref(id, y); },
    onAxes: function (ax) { SC.x = ax.x || ''; SC.y = ax.y || ''; SC.color = ax.color && ax.color !== 'team' ? ax.color : ''; writeQuery(); }
  });
}

/* Leaders: small multiples on the view's key metrics, each over a dot strip of the grid */
function leadersView(host) {
  var v = view(), rows = shown(), P = peers();
  var ids = keyMetrics(v);
  var hl = function (r) { return matches(r) || r.id === SC.p; };
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + SC.S, title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' drivers on screen on the view’s key metrics. Bars are percentiles against the ' + P.length + ' with ' + minNow() + '+ starts; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map(function (id, i) {
      var m = mmeta(id);
      var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
      if (!list.length) return '';
      var item = function (r, rk) { var p = pctOf(r, id); return { id: r.id, rank: rk, name: r.name, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      var top = list.slice(0, 5).map(function (r, j) { return item(r, j + 1); });
      var bottom = !TOTALS.test(id) && list.length > 10 ? list.slice(-3).map(function (r, j) { return item(r, list.length - 2 + j); }) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' drivers', top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach(function (id, i) {
    var el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    var m = mmeta(id);
    var vals = rows.filter(function (r) { return isNum(val(r, id)); }).map(function (r) { return { v: val(r, id), name: r.name + ' · ' + PD.teamAbbr(r.team), id: r.id, hl: hl(r) }; });
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every driver on ' + m.label, onClick: function (d) { openProfile(d.id); } });
  });
  QK.$$('[data-pick]', host).forEach(function (a) { a.addEventListener('click', function (ev) { if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return; ev.preventDefault(); openProfile(a.getAttribute('data-pick')); }); });
}

/* All-time: Elo since 1950 (peak against the field, the team-mate and in qualifying), moved from the Drivers list */
function allTime(host) {
  host.innerHTML = '<div class="sc-alltime"><div id="sc-hall"></div>' + QK.sectionHead({ kicker: 'All-time', title: 'The best ever, by Elo', sub: 'Our Elo from every head-to-head since 1950: against the whole field, against the team-mate only, and in qualifying. 1500 is average; the peak is the highest a driver reached.' }) +
    PD.grid(PD.card('Peak field Elo, top 15', '', PD.chartBox('sc-elo', 420, 'All-time peak Elo'), { span: 5 }) +
      PD.card('The top 50', 'Sortable; tap a name for the driver page.', '<div id="sc-elo-t"></div>', { span: 7, flush: true })) + '</div>';
  hall();
  PD.load('elo.json').then(function (elo) {
    if (!host.isConnected) return;
    var at = ((elo || {}).all_time || []).slice();
    var cur = PD.currentSeason();
    PD.ch.hbars('sc-elo', at.slice().sort(function (a, b) { return (b.peak_field || 0) - (a.peak_field || 0); }).slice(0, 15).map(function (x) { return { label: x.name, value: x.peak_field, href: PD.driverHref(x.driver, cur), colour: PD.col('teal'), sub: (x.years || []).join('–') + ' · ' + x.races + ' races' }; }),
      { fmt: function (v) { return PD.num(v, 0); }, min: 1500, name: 'Peak field Elo', emptyText: 'No Elo history.', label: 'All-time Elo' });
    if (!at.length) { PD.set('sc-elo-t', PD.muted('No Elo history.')); return; }
    PD.table('sc-elo-t', [
      { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.driver, { name: v, dot: false, y: cur }); } },
      { key: 'span', label: 'Years', sort: false },
      { key: 'races', label: 'Races', num: true },
      { key: 'peak_field', label: 'Peak field', num: true, fmt: function (v) { return '<b>' + PD.num(v, 0) + '</b>'; } },
      { key: 'peak_teammate', label: 'Peak v team-mate', num: true, fmt: function (v) { return PD.num(v, 0); } },
      { key: 'peak_quali', label: 'Peak quali', num: true, fmt: function (v) { return PD.num(v, 0); } }
    ], at.slice(0, 50).map(function (x) { return Object.assign({ span: (x.years || []).join('–') }, x); }), { sort: { key: 'peak_field', dir: 'desc' }, rank: true, maxHeight: 520 });
    PD.v2.oursHeads(document.getElementById('sc-elo-t'), { 'Peak field': 'elo', 'Peak v team-mate': 'elo_teammate', 'Peak quali': 'elo' });
  });
}

/* The hall of fame and the greatest seasons (hall_of_fame.json): our driver model across every era is the team-mate Elo
   (same car, same day; the lap-time ratings start in the 1990s). A season's rating is the team-mate Elo after its last
   race (8+ starts); "Biggest climb" is how far one season moved it, kinder to short careers. */
var HALL_MODE = 'rating';
function hall() {
  var host = document.getElementById('sc-hall');
  if (!host) return;
  PD.load('hall_of_fame.json').then(function (H) {
    if (!host.isConnected) return;
    if (!H || !H.ok) { host.innerHTML = ''; return; }
    var cur = PD.currentSeason();
    var top = (H.hall || []).slice(0, 12);
    host.innerHTML = QK.sectionHead({ kicker: 'Hall of fame', title: 'The greatest drivers, by our driver model', sub: 'Our team-mate Elo from every Grand Prix since 1950: a rating from head-to-heads in the same car, the fairest test across eras (1500 is average). Ranked by the peak each driver reached; 20+ starts.' }) +
      '<div class="pd-hall">' + top.map(function (r, i) {
        var t = (r.teams || [])[r.teams.length - 1];
        return '<a class="pd-hall-c" href="' + esc(PD.driverHref(r.driver, cur)) + '"><span class="rk qk-outline">' + (i + 1) + '</span><b>' + esc(r.name) + '</b><span class="v num">' + PD.num(r.peak_tm, 0) + '</span>' +
          '<small>' + esc((r.years || []).join('–')) + ' · ' + r.titles + ' title' + (r.titles === 1 ? '' : 's') + ' · ' + r.wins + ' wins · ' + r.starts + ' starts</small></a>';
      }).join('') + '</div>' +
      '<section class="qk-section pd-sec">' + QK.sectionHead({ kicker: 'Greatest seasons', title: HALL_MODE === 'climb' ? 'The biggest single-season climbs' : 'The highest-rated seasons', sub: HALL_MODE === 'climb' ? 'How far one season moved a driver’s team-mate Elo: beating a rated team-mate counts most.' : 'The team-mate Elo after the season’s last race, 8+ starts.',
        actions: PD.seg('sc-hm', [['rating', 'Highest rating'], ['climb', 'Biggest climb']], HALL_MODE, 'Greatest seasons') }) +
      PD.card('', '', PD.chartBox('sc-hall-c', 560, 'Greatest seasons'), {}) + '</section>';
    var list = (HALL_MODE === 'climb' ? H.climbs : H.seasons) || [];
    list = list.slice(0, 20);
    PD.ch.hbars('sc-hall-c', list.map(function (r) { return { label: r.name + ' ' + r.year, value: HALL_MODE === 'climb' ? r.gain : r.tm_elo, href: PD.driverHref(r.driver, r.year), colour: PD.teamColour(r.team),
      sub: PD.teamName(r.team) + ' · ' + r.starts + ' starts · ' + (r.wins || 0) + ' wins' + (r.pos ? ' · P' + r.pos + ' in the championship' : '') + ' · team-mate Elo ' + PD.num(r.tm_elo, 0) }; }),
      { fmt: function (v) { return HALL_MODE === 'climb' ? PD.signed(v, 0) : PD.num(v, 0); }, min: HALL_MODE === 'climb' ? 0 : 1500, name: HALL_MODE === 'climb' ? 'Team-mate Elo gained' : 'Team-mate Elo', xName: HALL_MODE === 'climb' ? 'Team-mate Elo gained in the season' : 'Team-mate Elo after the season', label: 'Greatest seasons' });
    PD.wireSeg(host, 'sc-hm', function (v) { HALL_MODE = v; hall(); });
  });
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id) {
  var r = findRow(id);
  if (!r) return;
  SC.p = r.id; writeQuery();
  var v = view(), P = peers(), inPeers = P.indexOf(r) >= 0;
  var row = function (id2) { var m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2), value: m.fmt(x), tip: m.tip }; };
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(row).filter(Boolean) }; });
  var t = teamOf(r);
  var stats = ['driver_effect', 'race_pace', 'points_per_race'].filter(has).map(function (id2) { var m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Starts', value: String(r.n) });
  var simKeys = (V().spec ? V().spec.headline('drivers') : []).filter(has);
  if (!simKeys.length) simKeys = [].concat.apply([], v.sets.map(function (s) { return s.ids.slice(0, 3); }));
  var pool = inPeers ? P : P.concat([r]);
  var near = QK.within.similar(pool, r, simKeys, function (rr, k) { return val(rr, k); }, 5);
  var yq = SC.S !== PD.currentSeason() ? '?y=' + SC.S : '';
  var cmpH = near.length ? '#/compare/drivers/' + encodeURIComponent(r.id) + '/' + encodeURIComponent(near[0].row.id) + yq : '#/scout?cmp=' + encodeURIComponent(r.id);
  var html = QK.profile({
    kicker: 'Driver · ' + (t.name || t.abbr), name: r.name, href: href(r),
    sub: [isNum(r.age) ? 'Age ' + r.age : '', r.n + ' start' + (r.n === 1 ? '' : 's'), String(SC.S)].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: 'drivers with ' + minNow() + '+ starts' + (inPeers ? '' : ' (this driver is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + surname(r.name) + ' in ' + SC.S, items: near.map(function (o) { return { name: o.row.name, href: href(o.row), id: o.row.id, sub: subOf(o.row) }; }) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(r.id) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(r.id) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full driver page', href: href(r) }, { label: 'Progression', href: PD.driverHref(r.id) + '?view=progression' }, { label: near.length ? 'Compare with ' + surname(near[0].row.name) : 'Compare', href: cmpH }],
    note: 'Percentiles against the ' + P.length + ' drivers with ' + minNow() + '+ starts in ' + SC.S + '. “Most like” is the nearest five on the spec’s headline driver metrics.'
  });
  var inner = QK.drawer.open({ html: html, label: r.name + ': profile', onClose: function () { SC.p = ''; writeQuery(); } });
  var pb = inner.querySelector('#sc-pf-pin');
  if (pb) pb.addEventListener('click', function () { pin(r); openProfile(r.id); });
  QK.$$('[data-pick]', inner).forEach(function (a) { a.addEventListener('click', function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'));
  }); });
}

/* ── the compare tray ───────────────────────────────────────────────────── */
function pin(r) {
  if (!TRAY) return;
  TRAY.toggle(r.id);
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(function (b) { var on = TRAY.has(r.id); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(function (id) { return findRow(id); }), label: 'Compare tray',
    item: function (id) { var r = findRow(id); return r ? { name: r.name, short: surname(r.name), sub: PD.teamAbbr(r.team) + ' · ' + r.n + ' starts', colour: teamOf(r).colour } : { name: id }; },
    onChange: function (ids) { SC.cmp = ids; writeQuery(); },
    href: function (ids) { return '#/compare/drivers/' + encodeURIComponent(ids[0]) + '/' + encodeURIComponent(ids[1]) + (SC.S !== PD.currentSeason() ? '?y=' + SC.S : ''); },
    hrefLabel: 'Full compare',
    body: trayBody
  });
}
function trayBody(ids) {
  var rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  var v = view();
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(function (id) {
    var m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(function (r) { var x = val(r, id); return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id) : null }; }) };
  }) }; });
  return QK.trayCompare({ entities: rs.map(function (r) { var t = teamOf(r); return { name: r.name, short: surname(r.name), sub: t.abbr + ' · ' + r.n + ' starts', colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles against the drivers with ' + minNow() + '+ starts in ' + SC.S + '. The volt underline marks the best of the ' + rs.length + ' on each row; team-mates share a car, so the first rows are the fairest test.' });
}

PD.route('scout', render);
})(window.PD);
