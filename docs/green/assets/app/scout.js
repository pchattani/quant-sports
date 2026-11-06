/* The Quant Green — the Scouting Room (#/scout), on the kit's scout.js the way Scrum and Campus use it: QK.board,
 * QK.leaderCard, QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare, QK.scoutBar, QK.within.similar.
 *
 * One control bar drives every view: men or women; "Players" (All players, or one tour: PGA Tour, DP World Tour, LIV,
 * Korn Ferry); the minimum rounds (default: the regulars, 30+ rounds in the last two years); country; age band;
 * search. Under it, "Top of the group". Views (?view=): board (column sets, any metric added, percentile cells, CSV,
 * pin), chart (any two metrics, colour by tour or by a metric's percentile, medians, the search ringed and the five
 * most like it), leaders (top five and bottom three over a dot strip). A name opens the profile drawer (?p=); pin up to
 * four to the compare tray (?cmp=). Data: scout/<men|women>.json (depth.py scout). */
(function () {
'use strict';
var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;

var GROUPS = { men: ['all', 'pga', 'eur', 'liv', 'ntw'], women: ['all'] };
var BASE = [['Scoring', ['sg', 'form', 'sg_e', 'sg_w', 'sd', 'great', 'poor']], ['Hole by hole', ['h3', 'h4', 'h5', 'bird', 'bog', 'dbl', 'eag']], ['Results', ['win', 't10', 'cut', 'rt']]];
var STRIKE = ['Ball striking', ['dist', 'acc', 'gir', 'ppg', 'sand', 'c_ott', 'c_app', 'c_arg', 'c_putt']];
var FAMILY_NAME = { value: 'Rating and form', scoring: 'Scoring', holes: 'Hole by hole', striking: 'Ball striking', categories: 'Strokes gained by category (estimate)', outcomes: 'Results' };
var AGES = [['', 'Any age'], ['u25', 'Under 25'], ['25-29', '25 to 29'], ['30-34', '30 to 34'], ['35p', '35 and over']];
var AGE_TEST = { u25: function (a) { return a < 25; }, '25-29': function (a) { return a >= 25 && a < 30; }, '30-34': function (a) { return a >= 30 && a < 35; }, '35p': function (a) { return a >= 35; } };

var ST = { s: 'men', view: 'board', grp: 'all', min: null, cc: '', age: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', c: '' };
var D = null, DK = '', ROOT = null, TRAY = null, BOARD = null, PC = {};

function prep(d) {
  var cols = d.cols || [], rows = [];
  (d.rows || []).forEach(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; rows.push(o); });
  var M = {};
  (d.metrics || []).forEach(function (m) { M[m.id] = m; });
  return { rows: rows, M: M, metrics: (d.metrics || []).filter(function (m) { return rows.some(function (r) { return isNum(r[m.id]); }); }), minQ: d.min_q || 30, from: d.from,
    maxR: Math.max.apply(null, rows.map(function (r) { return r.rounds || 0; }).concat([60])) };
}
function val(r, id) { var v = r[id]; return isNum(v) ? v : null; }
function has(id) { return !!(D && D.M[id]); }
function mmeta(id) {
  var m = (D && D.M[id]) || { id: id, label: id };
  return { id: id, label: m.label || id, short: m.short || m.label, tip: m.tip || '', lower: m.dir === 'lower', style: false,
    ours: id === 'rt' || id === 'sg' ? { name: 'Strokes gained', about: 'Our measure: strokes a round better than an average field, from every round against the field that played it' } : null,
    fmt: function (v) { return GR.vfmt(id, v); }, family: m.family || 'other' };
}
function grpName(g) { g = g || ST.grp; return g === 'all' ? (ST.s === 'women' ? 'LPGA players' : 'Every men’s tour') : GR.tourName(g); }
function grpNoun(g) { g = g || ST.grp; return g === 'all' ? 'players' : GR.tourShort(g) + ' players'; }
function inGroup(r, g) { g = g || ST.grp; return g === 'all' || r.tour === g; }
function past(r) { return isNum(ST.min) ? (r.rounds || 0) >= ST.min : !!r.q; }
function peers(g) { g = g || ST.grp; return D.rows.filter(function (r) { return inGroup(r, g) && past(r); }); }
function keep(r) {
  if (ST.cc && String(r.cc) !== ST.cc) return false;
  if (ST.age) { if (!isNum(r.age) || !AGE_TEST[ST.age](r.age)) return false; }
  return true;
}
function shown() { return peers().filter(keep); }
function fold(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function matches(r) { var q = fold(String(ST.q || '').trim()); return q.length > 1 && fold(r.n + ' ' + (r.cc || '')).indexOf(q) >= 0; }
function pctOf(r, id, g) {
  g = g || ST.grp;
  var key = g + '|' + ST.min + '|' + id, srt = PC[key];
  if (!srt) srt = PC[key] = peers(g).map(function (x) { return val(x, id); }).filter(isNum).sort(function (a, b) { return a - b; });
  var v = val(r, id);
  if (!isNum(v) || srt.length < 5) return null;
  var p = QK.pctRank(srt, v);
  return mmeta(id).lower ? 100 - p : p;
}
function clearPct() { PC = {}; }
function floorText() { return isNum(ST.min) ? ST.min + '+ rounds' : 'regulars (' + D.minQ + '+ rounds)'; }

function view(g) {
  g = g || ST.grp;
  var P = peers(g);
  var ok = function (id) { return has(id) && P.filter(function (r) { return isNum(val(r, id)); }).length >= Math.max(3, 0.3 * P.length); };
  var sets = BASE.slice();
  if (ST.s === 'men' && (g === 'pga' || g === 'all')) sets = [BASE[0], STRIKE, BASE[1], BASE[2]];
  sets = sets.map(function (s, i) { return { key: ['excellence', 'production', 'aggregate', 'extra'][i], label: s[0], ids: s[1].filter(ok) }; }).filter(function (s) { return s.ids.length; });
  var x = ok('dist') && g !== 'all' ? 'dist' : 'sg', y = ok('acc') && g !== 'all' ? 'acc' : 'bird';
  if (!ok(y)) y = 'sg_w';
  return { x: ok(x) ? x : null, y: ok(y) ? y : null, sets: sets };
}
function keyMetrics(v) {
  var out = [];
  v.sets.forEach(function (s) { s.ids.forEach(function (id) { if (out.indexOf(id) < 0 && out.length < 9) out.push(id); }); });
  return out.slice(0, 9);
}

function readQuery(q) {
  q = q || {};
  ST.s = q.s === 'women' ? 'women' : 'men';
  ST.view = ['board', 'chart', 'leaders'].indexOf(q.view) >= 0 ? q.view : 'board';
  ST.grp = GROUPS[ST.s].indexOf(q.grp) >= 0 ? q.grp : 'all';
  var mn = parseInt(q.min, 10); ST.min = isNaN(mn) ? null : mn;
  ST.cc = q.cc || ''; ST.age = AGE_TEST[q.age] ? q.age : '';
  ST.q = q.q || ''; ST.cols = q.cols || ''; ST.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  ST.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  ST.all = q.all === '1'; ST.p = q.p || ''; ST.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  ST.x = q.x || ''; ST.y = q.y || ''; ST.c = q.c || '';
}
function queryNow() {
  var q = [];
  var add = function (k, v) { if (v !== '' && v !== null && v !== undefined) q.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); };
  if (ST.s !== 'men') add('s', ST.s);
  if (ST.view !== 'board') add('view', ST.view);
  if (ST.grp !== 'all') add('grp', ST.grp);
  if (isNum(ST.min)) add('min', ST.min);
  ['cc', 'age', 'q', 'cols'].forEach(function (k) { add(k, ST[k]); });
  if (ST.add.length) add('add', ST.add.join(','));
  if (ST.sort && ST.sort.key && !(ST.sort.key === 'sg' && ST.sort.dir === 'desc')) { add('sort', ST.sort.key); add('dir', ST.sort.dir); }
  if (ST.all) add('all', '1');
  add('p', ST.p);
  if (ST.cmp.length) add('cmp', ST.cmp.join(','));
  if (ST.view === 'chart') { add('x', ST.x); add('y', ST.y); add('c', ST.c); }
  return q.join('&');
}
function writeQuery() { GR.setQuery('scout', queryNow()); }

function href(r) { return GR.playerHref(r.id); }
function markOf(r) { var m = GR.mark(r.n, r.tour); return { abbr: GR.tourShort(r.tour), colour: m.colour, name: GR.tourName(r.tour) }; }
function subOf(r) { return [GR.tourShort(r.tour), r.cc || '', isNum(r.age) ? 'age ' + Math.floor(r.age) : '', r.rounds + ' rounds'].filter(Boolean).join(' · '); }
function findRow(id) { var s = String(id); for (var i = 0; i < D.rows.length; i++) if (String(D.rows[i].id) === s) return D.rows[i]; return null; }

function render(page, P) {
  ROOT = page;
  readQuery(P.query || {});
  page.innerHTML = GR.head('Scouting Room', 'Every player and every number, judged against the same peers: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare. The last two years, every rate shrunk toward the average so a short record cannot top a list.', ST.s === 'women' ? 'LPGA' : 'Men’s golf') +
    '<div class="gr-controls">' + GR.seg('sr-s', [['men', 'Men'], ['women', 'Women']], ST.s, 'Men or women') + '</div>' +
    '<div class="qk-room"><section class="qk-card gr-ctl"><div class="qk-card-body" id="sr-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="gr-top" id="sr-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs gr-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].map(function (t) { return '<button type="button" class="qk-tab" role="tab" id="sr-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (ST.view === t[0]) + '" tabindex="' + (ST.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>'; }).join('') +
    '</div><div id="sr-view" role="tabpanel" aria-labelledby="sr-tab-' + ST.view + '"></div></div>';
  GR.onLeave(function () { if (QK.drawer && QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  QK.seg(page.querySelector('#sr-s'), function (v) { location.hash = '#/scout' + (v === 'women' ? '?s=women' : ''); });
  page.addEventListener('click', pickClick);
  return GR.load('scout/' + ST.s + '.json').then(function (d) {
    if (!page.isConnected) return;
    if (DK !== ST.s) { D = prep(d); DK = ST.s; clearPct(); }
    controls(); tabs(); tray(); refresh();
    if (ST.p) { var r = findRow(ST.p); if (r) openProfile(r.id); }
  });
}

function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  var a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || !D || a.closest('.qk-drawer')) return;
  var m = /#\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

function controls() {
  var host = document.getElementById('sr-ctl');
  if (!host) return;
  var opt = function (v, t, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>'; };
  var grpSel = '<select class="qk-select" id="sr-grp" aria-label="Players to compare">' + GROUPS[ST.s].map(function (g) { return opt(g, g === 'all' ? (ST.s === 'women' ? 'All players (LPGA)' : 'All players') : GR.tourName(g), ST.grp); }).join('') + '</select>';
  var ccs = Array.from(new Set(D.rows.filter(function (r) { return inGroup(r); }).map(function (r) { return String(r.cc || ''); }).filter(Boolean))).sort();
  var mx = Math.ceil(D.maxR / 10) * 10;
  var items = [
    { label: 'Players', html: grpSel },
    { label: 'Min rounds', html: '<span class="gr-min"><input type="range" id="sr-min" min="0" max="' + mx + '" step="5" value="' + (isNum(ST.min) ? ST.min : 0) + '" aria-label="Minimum rounds"><b class="qk-sbar-v" id="sr-min-v">' + (isNum(ST.min) ? ST.min : 'Regulars') + '</b></span>' },
    { label: 'Country', html: '<select class="qk-select" id="sr-cc">' + opt('', 'Every country', ST.cc) + ccs.map(function (c) { return opt(c, c, ST.cc); }).join('') + '</select>' },
    D.rows.some(function (r) { return isNum(r.age); }) ? { label: 'Age', html: '<select class="qk-select" id="sr-age">' + AGES.map(function (a) { return opt(a[0], a[1], ST.age); }).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sr-q" type="search" placeholder="Player or country…" value="' + esc(ST.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  host.innerHTML = '<p class="gr-floor">' + esc(grpName()) + ', ' + esc(floorText()) + ' · ' + peers().length + ' in the peer group · rounds since ' + esc(GR.date(D.from)) +
    '. Percentiles are against the peer group, whatever the country or age filters show. Drag the slider for any number of rounds; back to 0 is the regulars’ floor.</p>' + QK.scoutBar(items);
  var $ = function (id) { return document.getElementById(id); };
  $('sr-grp').onchange = function (e) { ST.grp = e.target.value; ST.cols = ''; ST.x = ''; ST.y = ''; ST.c = ''; ST.sort = null; ST.add = []; clearPct(); controls(); refresh(); };
  $('sr-min').oninput = function (e) { $('sr-min-v').textContent = Number(e.target.value) ? e.target.value : 'Regulars'; };
  $('sr-min').onchange = function (e) { var n = Number(e.target.value); ST.min = n > 0 ? n : null; clearPct(); controls(); refresh(); };
  $('sr-cc').onchange = function (e) { ST.cc = e.target.value; refresh(); };
  if ($('sr-age')) $('sr-age').onchange = function (e) { ST.age = e.target.value; refresh(); };
  var t = null;
  $('sr-q').oninput = function (e) { ST.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}

function tabs() {
  var bar = ROOT.querySelector('.gr-tabs');
  QK.$$('[role="tab"]', bar).forEach(function (b, i, all) {
    b.addEventListener('click', function () { select(b.getAttribute('data-view')); });
    b.addEventListener('keydown', function (e) {
      var j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : null;
      if (j === null) return;
      e.preventDefault();
      var n = all[(j + all.length) % all.length]; n.focus(); select(n.getAttribute('data-view'));
    });
  });
  function select(v) {
    ST.view = v;
    QK.$$('[role="tab"]', bar).forEach(function (b) { var on = b.getAttribute('data-view') === v; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
    document.getElementById('sr-view').setAttribute('aria-labelledby', 'sr-tab-' + v);
    drawView();
  }
}
function refresh() { if (!ROOT || !ROOT.isConnected) return; topStrip(); drawView(); }
function drawView() {
  writeQuery();
  var host = document.getElementById('sr-view');
  if (!host) return;
  BOARD = null;
  if (ST.view === 'chart') return chartView(host);
  if (ST.view === 'leaders') return leadersView(host);
  return boardView(host);
}
function shortTip(t) { t = String(t || ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

function topStrip() {
  var host = document.getElementById('sr-top');
  if (!host) return;
  var v = view(), rows = shown(), ids = keyMetrics(v).slice(0, 5);
  var items = ids.map(function (id) {
    var m = mmeta(id);
    var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
    if (!list.length) return null;
    var r = list[0], nx = list[1];
    return { sport: 'golf', kicker: m.label, name: r.n, value: m.fmt(val(r, id)), title: GR.tourShort(r.tour) + (r.cc ? ' · ' + r.cc : ''), next: nx ? { name: nx.n, value: m.fmt(val(nx, id)) } : null, expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the group', title: 'The best ' + grpNoun() + ', on what matters',
    sub: 'The leader on five key numbers among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}

function boardView(host) {
  var v = view(), P = peers();
  var all = shown();
  var rows = String(ST.q || '').trim() ? all.filter(matches) : all;
  var sets = [{ key: 'view', label: 'Headline', groups: v.sets.map(function (s) { return { label: s.label, ids: s.ids }; }) }];
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var fams = [];
  D.metrics.forEach(function (m) { if (fams.indexOf(m.family) < 0 && okAny(m.id)) fams.push(m.family); });
  fams.forEach(function (f) { sets.push({ key: f, label: FAMILY_NAME[f] || f, groups: [{ label: FAMILY_NAME[f] || f, ids: D.metrics.filter(function (m) { return m.family === f && okAny(m.id); }).map(function (m) { return m.id; }) }] }); });
  var setKey = QK.board.pick(sets, ST.cols, 'view');
  var LEAD = ['name', 'rounds', 'events', 'rank'];
  var sort = ST.sort && ST.sort.key && (LEAD.indexOf(ST.sort.key) >= 0 || has(ST.sort.key)) ? ST.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: LEAD.indexOf(sort.key) < 0 && mmeta(sort.key).lower ? 'asc' : 'desc' };
  if (!sort) sort = { key: 'sg', dir: 'desc' };
  var addable = fams.map(function (f) { return '<optgroup label="' + esc(FAMILY_NAME[f] || f) + '">' + D.metrics.filter(function (m) { return m.family === f && okAny(m.id); }).map(function (m) { return '<option value="' + esc(m.id) + '">' + esc(mmeta(m.id).label) + (m.dir === 'lower' ? ' ↓' : '') + '</option>'; }).join('') + '</optgroup>'; }).join('');
  var noun = grpNoun();
  host.innerHTML = '<section class="qk-card"><div class="qk-card-head"><div style="min-width:0"><h2 class="qk-card-title">The board</h2><div class="qk-card-sub">' +
    esc(grpName()) + ' · the bar under each number is its percentile against the ' + P.length + ' ' + esc(noun) + ', ' + esc(floorText()) + ': the top 10% in red, the bottom 10% in blue. Tap a name for the profile; tick the box to pin it to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sr-board"></div></div></section>';
  BOARD = QK.board(document.getElementById('sr-board'), {
    id: 'sr-bd', summary: 'sg', sets: sets, set: setKey, added: ST.add.filter(has), sort: sort, all: ST.all, page: 50, noun: noun,
    nameLabel: 'Player', subLabel: 'Tour · country · age · rounds',
    meta: mmeta, addable: addable,
    lead: [{ key: 'rank', label: 'Rank', tip: 'Our ranking', fmt: function (row) { return isNum(row._r.rank) ? String(row._r.rank) : ''; }, val: function (row) { return isNum(row._r.rank) ? row._r.rank : 9999; } },
      { key: 'rounds', label: 'Rds', tip: 'Rounds in the last two years', fmt: function (row) { return String(row._r.rounds); }, val: function (row) { return row._r.rounds; } }],
    rows: rows.map(function (r) { return { id: r.id, name: r.n, sub: subOf(r), mark: markOf(r), href: href(r), _r: r }; }),
    val: function (row, id) { return val(row._r, id); },
    peers: P.map(function (r) { return { id: r.id, _r: r }; }),
    hl: function (row) { return ST.cmp.indexOf(String(row.id)) >= 0; },
    pin: { has: function (id) { return !!TRAY && TRAY.has(String(id)); }, toggle: function (row) { pin(row._r); }, label: 'Pin to the compare tray' },
    onPick: function (row) { openProfile(row.id); },
    onState: function (st) { ST.cols = st.set === 'view' ? '' : st.set; ST.add = st.added; ST.sort = st.sort; ST.all = st.all; writeQuery(); },
    csv: 'green-' + ST.s + '-' + ST.grp + '.csv',
    empty: String(ST.q || '').trim() ? 'No ' + noun + ' match “' + ST.q.trim() + '” with these filters.' : 'No ' + noun + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Strokes gained are per round against an average field, shrunk toward the average with 12 rounds of weight; hole rates with 72 holes; results with 10 starts. Ball striking is PGA Tour season statistics (ESPN, 2017 on). A ↓ marks a number where lower is better (its bar is flipped).'
  });
}

function chartView(host) {
  var v = view(), P = peers(), rows = shown();
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var list = D.metrics.filter(function (m) { return okAny(m.id); });
  var x = has(ST.x) && okAny(ST.x) ? ST.x : v.x, y = has(ST.y) && okAny(ST.y) ? ST.y : v.y;
  var c = ST.c === 'tour' ? 'tour' : has(ST.c) && okAny(ST.c) ? ST.c : (ST.grp === 'all' && ST.s === 'men' ? 'tour' : 'sg');
  if (!x || !y) { host.innerHTML = QK.empty('Nothing to chart', 'This group has too few numbers with values.'); return; }
  var presets = [];
  if (v.x && v.y) presets.push({ x: v.x, y: v.y, c: 'sg' });
  presets.push({ x: 'dist', y: 'acc', c: 'sg' }, { x: 'gir', y: 'ppg', c: 'sg' }, { x: 'bird', y: 'bog', c: 'sg' }, { x: 'sg', y: 'sd', c: 'tour' }, { x: 'sg_e', y: 'sg_w', c: 'tour' }, { x: 'h4', y: 'h5', c: 'sg' }, { x: 'sg', y: 't10', c: 'tour' });
  presets = presets.filter(function (pr, i, a) { return okAny(pr.x) && okAny(pr.y) && a.findIndex(function (q) { return q.x === pr.x && q.y === pr.y; }) === i; });
  var pi = -1; presets.forEach(function (pr, i) { if (pi < 0 && pr.x === x && pr.y === y) pi = i; });
  var grouped = {};
  list.forEach(function (m) { (grouped[m.family] = grouped[m.family] || []).push(m); });
  var sel = function (id, cur, colour) {
    return '<select class="qk-select" id="' + id + '">' + (colour ? '<option value="tour"' + (cur === 'tour' ? ' selected' : '') + '>Tour</option>' : '') +
      Object.keys(grouped).map(function (f) { return '<optgroup label="' + esc(FAMILY_NAME[f] || f) + '">' + grouped[f].map(function (m) { return '<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + esc(mmeta(m.id).label) + '</option>'; }).join('') + '</optgroup>'; }).join('') + '</select>';
  };
  var mx = mmeta(x), my = mmeta(y), mc = c !== 'tour' ? mmeta(c) : null;
  host.innerHTML = '<section class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
    presets.length ? { label: 'Preset', html: '<select class="qk-select" id="sr-preset">' + presets.map(function (pr, i) { return '<option value="' + i + '"' + (i === pi ? ' selected' : '') + '>' + esc(mmeta(pr.y).label + ' against ' + mmeta(pr.x).label) + '</option>'; }).join('') + '<option value="-1"' + (pi < 0 ? ' selected' : '') + '>Any two numbers</option></select>', cls: 'grow' } : null,
    { label: 'Across', html: sel('sr-x', x) }, { label: 'Up', html: sel('sr-y', y) }, { label: 'Colour', html: sel('sr-c', c, true) }]) +
    '<h3 class="gr-chart-t">' + esc(my.label) + ' against ' + esc(mx.label) + '</h3>' +
    GR.chart('sr-sc', 520, my.label + ' against ' + mx.label) + '<p class="gr-note" id="sr-ckey"></p><div id="sr-legend"></div><div id="sr-sim"></div></div></section>';
  var pts = rows.filter(function (r) { return isNum(val(r, x)) && isNum(val(r, y)); });
  var hits = String(ST.q || '').trim().length > 1 ? pts.filter(matches) : [];
  var med = function (a) { var b = a.slice().sort(function (p, q) { return p - q; }), n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
  var noC = QK.cssVar('--ink-3') || '#939bab';
  var colour = function (r) {
    if (c === 'tour') return GR.TOUR_COL[r.tour] || noC;
    var p0 = pctOf(r, c); return isNum(p0) ? QK.pctHex(p0) : noC;
  };
  var sc = function (id, v0) { return GR.PCTM[id] ? v0 * 100 : v0; };
  var f = function (id) { return GR.PCTM[id] ? function (v0) { return fmt.num(v0, 0) + '%'; } : function (v0) { return GR.vfmt(id, v0); }; };
  QKC.scatter(document.getElementById('sr-sc'), {
    points: pts.map(function (r) { var hit = hits.indexOf(r) >= 0; return { x: sc(x, val(r, x)), y: sc(y, val(r, y)), name: r.n + ' · ' + GR.tourShort(r.tour) + (mc ? ' · ' + mc.label + ' ' + mc.fmt(val(r, c)) : ''), label: GR.surname(r.n), color: colour(r), size: hit ? 20 : (pts.length > 250 ? 7 : 10), href: href(r), id: r.id }; }),
    xName: mx.label + (GR.PCTM[x] ? ' (%)' : '') + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (GR.PCTM[y] ? ' (%)' : '') + (my.lower ? ' (lower is better: flipped)' : ''),
    xFmt: f(x), yFmt: f(y), xInverse: mx.lower, yInverse: my.lower, labelTop: 10, pad: '8%',
    refX: pts.length > 2 ? sc(x, med(pts.map(function (r) { return val(r, x); }))) : null, refY: pts.length > 2 ? sc(y, med(pts.map(function (r) { return val(r, y); }))) : null,
    quadrants: ['', 'Better on both', 'Behind on both', ''],
    onClick: function (pt) { openProfile(pt.id); }, label: my.label + ' against ' + mx.label });
  document.getElementById('sr-ckey').innerHTML = pts.length + ' ' + esc(grpNoun()) + ' on the chart (' + esc(floorText()) + '); dashed lines are their medians, better is up and to the right. ' +
    (c === 'tour' ? 'Colour: each player’s main tour (key below).' : 'Colour: <b>' + esc(mc.label) + '</b>, each player’s percentile in the peer group (blue low, red high; grey: none).') + ' Tap a point for the profile.';
  if (c === 'tour') document.getElementById('sr-legend').innerHTML = '<div class="qk-legend">' + Object.keys(GR.TOUR_COL).filter(function (t) { return pts.some(function (r) { return r.tour === t; }); }).map(function (t) { return '<span><i style="background:' + GR.TOUR_COL[t] + '"></i>' + esc(GR.tourName(t)) + '</span>'; }).join('') + '</div>';
  var sim = document.getElementById('sr-sim');
  if (hits.length) {
    var t = hits[0];
    var near = QK.within.similar(P.indexOf(t) >= 0 ? P : P.concat([t]), t, keyMetrics(v), function (r, k) { return val(r, k); }, 5);
    sim.innerHTML = QK.within.simHtml('Most like ' + t.n, near.map(function (o) { return { name: o.row.n, href: href(o.row), sub: subOf(o.row) }; }));
  } else sim.innerHTML = '<p class="gr-note">Search a name in the bar above to ring the player and list the five most like them.</p>';
  var $ = function (id) { return document.getElementById(id); };
  var go = function () { ST.x = $('sr-x').value; ST.y = $('sr-y').value; ST.c = $('sr-c').value; drawView(); };
  ['sr-x', 'sr-y', 'sr-c'].forEach(function (id) { $(id).onchange = go; });
  if ($('sr-preset')) $('sr-preset').onchange = function (e) { var pr = presets[Number(e.target.value)]; if (!pr) return; ST.x = pr.x; ST.y = pr.y; ST.c = pr.c; drawView(); };
}

function leadersView(host) {
  var v = view(), rows = shown(), P = peers(), noun = grpNoun();
  var ids = keyMetrics(v).concat(['win', 't10', 'cut', 'poor']).filter(function (id, i, a) { return a.indexOf(id) === i && has(id); }).slice(0, 12);
  host.innerHTML = '<div class="gr-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + grpName(), title: 'Quick reads, number by number', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + esc(noun) + ' on screen. Bars are percentiles against the ' + P.length + ' in the peer group; the strip under each card is everyone on screen, with the median dashed' + (String(ST.q || '').trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map(function (id, i) {
      var m = mmeta(id);
      var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
      if (!list.length) return '';
      var item = function (r, rk) { var p = pctOf(r, id); return { id: r.id, rank: rk, name: r.n, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: markOf(r) }; };
      var top = list.slice(0, 5).map(function (r, j) { return item(r, j + 1); });
      var bottom = list.length > 10 ? list.slice(-3).map(function (r, j) { return item(r, list.length - 2 + j); }) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + noun, top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sr-strip-' + i });
    }).join('') + '</div>';
  ids.forEach(function (id, i) {
    var el = document.getElementById('sr-strip-' + i);
    if (!el) return;
    var m = mmeta(id), pc = GR.PCTM[id];
    var vals = rows.filter(function (r) { return isNum(val(r, id)); }).map(function (r) { return { v: pc ? val(r, id) * 100 : val(r, id), name: r.n + ' · ' + GR.tourShort(r.tour), id: r.id, hl: matches(r) || String(r.id) === ST.p }; });
    GR.safe(function () { QKC.strip(el, { values: vals, xName: m.label + (pc ? ' (%)' : ''), fmt: pc ? function (v0) { return fmt.num(v0, 1) + '%'; } : m.fmt, lower: m.lower, label: 'Every player on ' + m.label, onClick: function (d) { openProfile(d.id); } }); });
  });
}

function openProfile(id) {
  var r = findRow(id);
  if (!r) return;
  ST.p = String(r.id); writeQuery();
  var g = inGroup(r) ? ST.grp : 'all', v = view(g), P = peers(g);
  var row = function (id2) { var m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2, g), value: m.fmt(x), tip: m.tip }; };
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(row).filter(Boolean) }; }).filter(function (x) { return x.rows.length; });
  var stats = ['sg', 'form', 'rt'].map(function (id2) { var m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2, g), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Rounds', value: String(r.rounds), sub: r.events + ' events' });
  var pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  var near = QK.within.similar(pool, r, keyMetrics(v), function (rr, k) { return val(rr, k); }, 5);
  var html = QK.profile({
    kicker: GR.tourName(r.tour) + (isNum(r.rank) ? ' · ranked ' + r.rank : ''),
    name: r.n, href: href(r),
    sub: [r.cc || '', isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', r.rounds + ' rounds', 'the last two years'].filter(Boolean).join(' · '),
    team: markOf(r), stats: stats,
    peer: grpNoun(g) + ', ' + floorText() + (P.indexOf(r) >= 0 ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + GR.surname(r.n), items: near.map(function (o) { return { name: o.row.n, href: href(o.row), id: o.row.id, sub: subOf(o.row) }; }) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(String(r.id)) ? ' solid' : ' primary') + '" id="sr-pf-pin">' + (TRAY && TRAY.has(String(r.id)) ? '✓ In the tray' : '+ Pin to compare') + '</button>' + GR.followStar(r.id, r.n, ST.s),
    links: [{ label: 'Full player page', href: href(r), primary: true }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(grpNoun(g)) + ' in the peer group. “Most like” is the nearest five on the group’s key numbers.'
  });
  var inner = QK.drawer.open({ html: html, label: r.n + ': profile', onClose: function () { ST.p = ''; writeQuery(); } });
  var pb = inner.querySelector('#sr-pf-pin');
  if (pb) pb.addEventListener('click', function () { pin(r); openProfile(r.id); });
  QK.$$('[data-pick]', inner).forEach(function (a) { a.addEventListener('click', function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'));
  }); });
}

function pin(r) {
  if (!TRAY) return;
  TRAY.toggle(String(r.id));
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(function (b) { var on = TRAY.has(String(r.id)); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: ST.cmp.filter(function (id) { return findRow(id); }), label: 'Compare tray',
    item: function (id) { var r = findRow(id); return r ? { name: r.n, short: GR.surname(r.n), sub: GR.tourShort(r.tour), colour: markOf(r).colour } : { name: id }; },
    onChange: function (ids) { ST.cmp = ids; writeQuery(); },
    href: function () { return null; },
    body: trayBody
  });
}
function trayBody(ids) {
  var rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  var v = view('all');
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(function (id) {
    var m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(function (r) { var x = val(r, id); return { text: isNum(x) ? m.fmt(x) : 'n/a', pctl: isNum(x) ? pctOf(r, id, 'all') : null }; }) };
  }) }; });
  return QK.trayCompare({ entities: rs.map(function (r) { return { name: r.n, short: GR.surname(r.n), sub: GR.tourShort(r.tour) + ' · ' + r.rounds + ' rounds', colour: markOf(r).colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against every regular of the last two years. The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

GR.page('scout', render);
})();
