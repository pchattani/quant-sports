/* The Quant Iron — the Scouting Room (#/scout), on the kit's scout.js (QK.board, QK.leaderCard, QKC.strip, QK.drawer,
 * QK.profile, QK.tray, QK.trayCompare, QK.scoutBar) as the Scrum's sc-scout.js does.
 *
 * One control bar drives every view: the stream (sex and equipment), "Lifters" (All classes, then each IPF weight
 * class: the peer group the percentiles are taken over), tested, country, age band, the minimum meets and search.
 * Under the bar, "Top of the group": the leader on five key metrics. Views (?view=):
 *   board    (default) the deep table: column sets as chips, any metric added, percentile bars within the peers, CSV;
 *   chart    any two metrics (presets first), coloured by class, by tested or by a metric's percentile, medians,
 *            labelled axes, the search ringed and the five most like it;
 *   leaders  small multiples on the key metrics: the top five and the bottom three over a dot strip.
 * A name opens the profile drawer (?p=<id>); pin up to four to the compare tray (?cmp=).
 * Address: ?s, view, grp=all|<class>, min, t, cc, age, q, cols, add, sort, dir, all, p, cmp, x, y, c.
 * Data: scout/<stream>.json (the highest-rated active lifters of the stream, column-oriented; analytics.METRICS).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;

var VIEW = {
  all: [['Strength', ['rt', 'dots', 'gl', 'total', 'rel']], ['The three lifts', ['squat', 'bench', 'dead', 'rel_s', 'rel_b', 'rel_d']], ['Meet day', ['make', 'third', 'beat', 'value', 'cons', 'bomb', 'prog']], ['rel', 'make']],
  cls: [['Strength', ['rt', 'dots', 'total', 'squat', 'bench', 'dead']], ['Meet day', ['make', 'third', 'beat', 'value', 'cons', 'bomb']], ['Shape and progress', ['sh_s', 'sh_b', 'sh_d', 'jump3', 'prog', 'meets']], ['total', 'make']]
};
var FAMILY_NAME = { rating: 'Our rating', points: 'Points', lifts: 'Lifts', relative: 'Relative strength', shape: 'Shape (styles)', attempts: 'Attempts', 'meet day': 'Meet day', progress: 'Progress' };
var AGES = [['', 'Any age'], ['u24', 'Under 24'], ['24-34', '24 to 34'], ['35-44', '35 to 44'], ['45p', '45 and over']];
var AGE_TEST = { u24: function (a) { return a < 24; }, '24-34': function (a) { return a >= 24 && a < 35; }, '35-44': function (a) { return a >= 35 && a < 45; }, '45p': function (a) { return a >= 45; } };
var CCOL = ['var(--c-1)', 'var(--c-2)', 'var(--c-3)', 'var(--c-4)', 'var(--c-5)', 'var(--c-6)', 'var(--c-7)', 'var(--c-8)'];

var ST = { s: 'men_raw', view: 'board', grp: 'all', min: null, t: '', cc: '', age: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', c: '' };
var D = null, DK = '', ROOT = null, TRAY = null, BOARD = null, PC = {};

function prep(d) {
  var cols = d.cols || [], rows = [];
  (d.rows || []).forEach(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; rows.push(o); });
  var M = {};
  (d.metrics || []).forEach(function (m) { M[m.id] = m; });
  var mets = (d.metrics || []).filter(function (m) { return rows.some(function (r) { return isNum(r[m.id]); }); });
  return { rows: rows, M: M, metrics: mets, classes: d.classes || [], from: d.from, label: d.label };
}
function val(r, id) { var v = r[id]; return isNum(v) ? v : null; }
function has(id) { return !!(D && D.M[id]); }
function mmeta(id) {
  var m = (D && D.M[id]) || { id: id, label: id };
  return { id: id, label: m.label || id, short: m.short || m.label, tip: m.tip || '', lower: m.dir === 'lower', style: m.dir === 'style',
    ours: id === 'rt' ? { name: 'Iron rating', about: 'The DOTS we expect at the lifter’s next meet' } : id === 'value' || id === 'beat' ? { name: 'Against our forecast', about: 'Measured against our pre-meet expectation' } : null,
    fmt: function (v) { return IR.vfmt(id, v, D.M); }, family: m.family || 'other', unitShort: m.unit || '' };
}
function isAll(g) { return (g || ST.grp) === 'all'; }
function grpName(g) { g = g || ST.grp; return isAll(g) ? 'All classes' : g + ' kg'; }
function grpNoun(g) { g = g || ST.grp; return isAll(g) ? 'lifters' : g + ' kg lifters'; }
function inGroup(r, g) { g = g || ST.grp; return isAll(g) || r.cls === g; }
function past(r) { return (r.meets || 0) >= (isNum(ST.min) ? ST.min : 2); }
function peers(g) { g = g || ST.grp; return D.rows.filter(function (r) { return inGroup(r, g) && past(r); }); }
function keep(r) {
  if (ST.t === '1' && !(isNum(r.tested) && r.tested >= 0.5)) return false;
  if (ST.t === '0' && !(isNum(r.tested) && r.tested < 0.5)) return false;
  if (ST.cc && r.cc !== ST.cc) return false;
  if (ST.age) { if (!isNum(r.age) || !AGE_TEST[ST.age](r.age)) return false; }
  return true;
}
function shown() { return peers().filter(keep); }
function fold(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function matches(r) { var q = fold(String(ST.q || '').trim()); return q.length > 1 && fold(r.n + ' ' + r.cc).indexOf(q) >= 0; }
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
function floorText() { return (isNum(ST.min) ? ST.min : 2) + '+ meets in two years'; }
function view(g) {
  g = g || ST.grp;
  var v = isAll(g) ? VIEW.all : VIEW.cls, P = peers(g);
  var ok = function (id) { return has(id) && P.filter(function (r) { return isNum(val(r, id)); }).length >= Math.max(3, 0.25 * P.length); };
  var sets = v.slice(0, 3).map(function (s, i) { return { key: ['aggregate', 'excellence', 'production'][i], label: s[0], ids: s[1].filter(ok) }; }).filter(function (s) { return s.ids.length; });
  return { x: ok(v[3][0]) ? v[3][0] : 'rt', y: ok(v[3][1]) ? v[3][1] : 'dots', sets: sets };
}
function keyMetrics(v) {
  var out = [];
  v.sets.forEach(function (s) { s.ids.forEach(function (id) { if (out.indexOf(id) < 0 && out.length < 10 && !mmeta(id).style) out.push(id); }); });
  return out;
}

function readQuery(q) {
  q = q || {};
  ST.s = IR.STREAMS[q.s] ? q.s : (ST.s || 'men_raw');
  ST.view = ['board', 'chart', 'leaders'].indexOf(q.view) >= 0 ? q.view : 'board';
  ST.grp = q.grp || 'all';
  var mn = parseInt(q.min, 10); ST.min = isNaN(mn) ? null : mn;
  ST.t = q.t === '1' || q.t === '0' ? q.t : ''; ST.cc = q.cc || ''; ST.age = AGE_TEST[q.age] ? q.age : '';
  ST.q = q.q || ''; ST.cols = q.cols || ''; ST.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  ST.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  ST.all = q.all === '1'; ST.p = q.p || ''; ST.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  ST.x = q.x || ''; ST.y = q.y || ''; ST.c = q.c || '';
}
function hashNow() {
  var q = [];
  var add = function (k, v) { if (v !== '' && v !== null && v !== undefined) q.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); };
  if (ST.s !== 'men_raw') add('s', ST.s);
  if (ST.view !== 'board') add('view', ST.view);
  if (ST.grp !== 'all') add('grp', ST.grp);
  if (isNum(ST.min)) add('min', ST.min);
  ['t', 'cc', 'age', 'q', 'cols'].forEach(function (k) { add(k, ST[k]); });
  if (ST.add.length) add('add', ST.add.join(','));
  if (ST.sort && ST.sort.key && !(ST.sortDef && ST.sortDef.key === ST.sort.key && ST.sortDef.dir === ST.sort.dir)) { add('sort', ST.sort.key); add('dir', ST.sort.dir); }
  if (ST.all) add('all', '1');
  add('p', ST.p);
  if (ST.cmp.length) add('cmp', ST.cmp.join(','));
  if (ST.view === 'chart') { add('x', ST.x); add('y', ST.y); add('c', ST.c); }
  return '#/scout' + (q.length ? '?' + q.join('&') : '');
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }

function href(r) { return r.pg ? IR.playerHref(r.id) : null; }
function markOf(r) { return { abbr: r.cc ? String(r.cc).slice(0, 3).toUpperCase() : '', colour: '' }; }
function subOf(r) { return [r.cls ? r.cls + ' kg' : '', r.cc, isNum(r.age) ? 'age ' + Math.floor(r.age) : '', r.meets + ' meets', isNum(r.tested) ? (r.tested >= 0.5 ? 'tested' : 'untested') : ''].filter(Boolean).join(' · '); }
function findRow(id) { var s = String(id); for (var i = 0; i < D.rows.length; i++) if (String(D.rows[i].id) === s) return D.rows[i]; return null; }
function grpOf(r) { return isAll() ? 'all' : r.cls; }

function render(page, P) {
  ROOT = page;
  readQuery(P.query || {});
  page.innerHTML = U.head('Scouting Room', 'Every ranked lifter on every metric, judged against the same weight class: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare. Two years of meets; rates like attempts made and beating our forecast are shrunk toward the average, so one meet cannot top a list.', 'The Quant Iron') +
    '<div class="qk-room"><section class="qk-card ir-ctl"><div class="qk-card-body" id="sr-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="ir-top" id="sr-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs ir-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].map(function (t) { return '<button type="button" class="qk-tab" role="tab" id="sr-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (ST.view === t[0]) + '" tabindex="' + (ST.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>'; }).join('') +
    '</div><div id="sr-view" class="ir-view" role="tabpanel" aria-labelledby="sr-tab-' + ST.view + '"></div></div>';
  IR.onLeave(function () { if (QK.drawer && QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  return loadStream(ST.s).then(function () {
    if (!U.alive(page)) return;
    controls(); tabs(); tray(); refresh();
    if (ST.p) { var r = findRow(ST.p); if (r) openProfile(r.id); }
  });
}
function loadStream(s) {
  return IR.load('scout/' + s + '.json').then(function (d) {
    if (DK !== s) { D = prep(d); DK = s; clearPct(); }
    if (!isAll(ST.grp) && D.classes.indexOf(ST.grp) < 0) ST.grp = 'all';
  });
}

function controls() {
  var host = document.getElementById('sr-ctl');
  if (!host) return;
  var opt = function (v, t, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>'; };
  var grpSel = '<select class="qk-select" id="sr-grp" aria-label="Lifters to compare">' + opt('all', 'All classes', ST.grp) +
    '<optgroup label="By IPF weight class">' + D.classes.map(function (c) { return opt(c, c + ' kg', ST.grp); }).join('') + '</optgroup></select>';
  var ccs = {};
  D.rows.forEach(function (r) { if (r.cc) ccs[r.cc] = (ccs[r.cc] || 0) + 1; });
  var ccl = Object.keys(ccs).sort(function (a, b) { return ccs[b] - ccs[a]; });
  var items = [
    { label: 'Stream', html: U.streamSel('sr-s', ST.s) },
    { label: 'Lifters', html: grpSel },
    { label: 'Min meets', html: '<span class="ir-min"><input type="range" id="sr-min" min="2" max="12" step="1" value="' + (isNum(ST.min) ? ST.min : 2) + '" aria-label="Minimum meets"><b class="qk-sbar-v" id="sr-min-v">' + (isNum(ST.min) ? ST.min : 2) + '</b></span>' },
    { label: 'Testing', html: '<select class="qk-select" id="sr-t">' + opt('', 'Tested or not', ST.t) + opt('1', 'Mostly tested', ST.t) + opt('0', 'Mostly untested', ST.t) + '</select>' },
    { label: 'Country', html: '<select class="qk-select" id="sr-cc">' + opt('', 'Every country', ST.cc) + ccl.map(function (c) { return opt(c, c + ' (' + ccs[c] + ')', ST.cc); }).join('') + '</select>' },
    { label: 'Age', html: '<select class="qk-select" id="sr-age">' + AGES.map(function (a) { return opt(a[0], a[1], ST.age); }).join('') + '</select>' },
    { label: 'Search', html: '<input class="qk-input" id="sr-q" type="search" placeholder="Lifter or country…" value="' + esc(ST.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  host.innerHTML = '<p class="ir-floor">' + esc(D.label) + ' · ' + esc(grpName()) + ', ' + esc(floorText()) + ' · ' + peers().length + ' in the peer group (the ' + D.rows.length + ' highest-rated active lifters of the stream, meets since ' + esc(IR.date(D.from)) + '). ' +
    'Percentiles are against the peer group, whatever the testing, country or age filters show.</p>' + QK.scoutBar(items);
  var $ = function (id) { return document.getElementById(id); };
  $('sr-s').onchange = function (e) { ST.s = e.target.value; ST.grp = 'all'; ST.cc = ''; ST.p = ''; ST.cmp = []; loadStream(ST.s).then(function () { regroup(); tray(); }); };
  $('sr-grp').onchange = function (e) { ST.grp = e.target.value; regroup(); };
  $('sr-min').oninput = function (e) { $('sr-min-v').textContent = e.target.value; };
  $('sr-min').onchange = function (e) { var n = Number(e.target.value); ST.min = n > 2 ? n : null; clearPct(); controls(); refresh(); };
  $('sr-t').onchange = function (e) { ST.t = e.target.value; refresh(); };
  $('sr-cc').onchange = function (e) { ST.cc = e.target.value; refresh(); };
  $('sr-age').onchange = function (e) { ST.age = e.target.value; refresh(); };
  var t = null;
  $('sr-q').oninput = function (e) { ST.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
function regroup() { ST.cols = ''; ST.x = ''; ST.y = ''; ST.c = ''; ST.sort = null; ST.add = []; clearPct(); controls(); refresh(); }

function tabs() {
  var bar = ROOT.querySelector('.ir-tabs');
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
  var rows = shown(), ids = ['rt', 'total', 'rel', 'make', 'prog'].filter(has);
  var items = ids.map(function (id) {
    var m = mmeta(id);
    var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
    if (!list.length) return null;
    var r = list[0], nx = list[1];
    return { sport: 'powerlifting', kicker: m.label, name: r.n, value: m.fmt(val(r, id)), title: subOf(r), next: nx ? { name: nx.n, value: m.fmt(val(nx, id)) } : null, expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the group', title: 'The best ' + grpNoun() + ', on what matters', sub: 'The leader on five key metrics among the ' + rows.length + ' on screen. Tap a name for the lifter page.' }) + QK.hotRow(items) : '';
}

function boardView(host) {
  var v = view(), P = peers();
  var all = shown();
  var rows = String(ST.q || '').trim() ? all.filter(matches) : all;
  var sets = [{ key: 'view', label: isAll() ? 'Headline' : 'Class view', groups: v.sets.map(function (s) { return { label: s.label, ids: s.ids }; }) }];
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var fams = [];
  D.metrics.forEach(function (m) { if (fams.indexOf(m.family) < 0 && okAny(m.id)) fams.push(m.family); });
  fams.forEach(function (f) { sets.push({ key: f.replace(/ /g, '_'), label: FAMILY_NAME[f] || f, groups: [{ label: FAMILY_NAME[f] || f, ids: D.metrics.filter(function (m) { return m.family === f && okAny(m.id); }).map(function (m) { return m.id; }) }] }); });
  var setKey = QK.board.pick(sets, ST.cols, 'view');
  var LEAD = ['name', 'meets', 'bw', 'age'];
  var sort = ST.sort && ST.sort.key && (LEAD.indexOf(ST.sort.key) >= 0 || has(ST.sort.key)) ? ST.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: LEAD.indexOf(sort.key) < 0 && mmeta(sort.key).lower ? 'asc' : 'desc' };
  ST.sortDef = { key: 'rt', dir: 'desc' };
  if (!sort) sort = ST.sortDef;
  var addable = fams.map(function (f) { return '<optgroup label="' + esc(FAMILY_NAME[f] || f) + '">' + D.metrics.filter(function (m) { return m.family === f && okAny(m.id); }).map(function (m) { return '<option value="' + esc(m.id) + '">' + esc(m.label) + (m.dir === 'lower' ? ' ↓' : '') + '</option>'; }).join('') + '</optgroup>'; }).join('');
  var noun = grpNoun();
  host.innerHTML = '<section class="qk-card ir-board"><div class="qk-card-head"><div style="min-width:0"><h2 class="qk-card-title">The board</h2><div class="qk-card-sub">' +
    esc(grpName()) + ' · the bar under each number is its percentile against the ' + P.length + ' ' + esc(noun) + ', ' + esc(floorText()) + ': the top 10% in red, the bottom 10% in blue (lift shares and jump size are styles: never coloured). Tap a name for the profile; tick the box to pin it to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sr-board"></div></div></section>';
  BOARD = QK.board(document.getElementById('sr-board'), {
    id: 'sr-bd', summary: 'rt', sets: sets, set: setKey, added: ST.add.filter(has), sort: sort, all: ST.all, page: 50, noun: noun, entity: 'player',
    nameLabel: 'Lifter', subLabel: 'Class · country · age · meets',
    meta: mmeta, addable: addable, family: function (id) { return mmeta(id).family; },
    lead: [{ key: 'meets', label: 'Meets', tip: 'Scored full-power meets in two years', fmt: function (row) { return String(row._r.meets); }, val: function (row) { return row._r.meets; } },
      { key: 'bw', label: 'BW', tip: 'Bodyweight at the last meet (kg)', fmt: function (row) { return IR.kgn(row._r.bw); }, val: function (row) { return row._r.bw; } }],
    rows: rows.map(function (r) { return { id: r.id, name: r.n, sub: subOf(r), mark: markOf(r), href: href(r), _r: r }; }),
    val: function (row, id) { return val(row._r, id); },
    peers: P.map(function (r) { return { id: r.id, _r: r }; }),
    hl: function (row) { return ST.cmp.indexOf(String(row.id)) >= 0; },
    pin: { has: function (id) { return !!TRAY && TRAY.has(String(id)); }, toggle: function (row) { pin(row._r); }, label: 'Pin to the compare tray' },
    onPick: function (row) { openProfile(row.id); },
    onState: function (st) { ST.cols = st.set === 'view' ? '' : st.set; ST.add = st.added; ST.sort = st.sort; ST.all = st.all; writeQuery(); },
    csv: 'iron-' + ST.s + '-' + ST.grp + '.csv',
    empty: String(ST.q || '').trim() ? 'No ' + noun + ' match “' + ST.q.trim() + '” with these filters.' : 'No ' + noun + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Two years of meets. Attempts made, third attempts, beating our forecast, meet value, spread and bomb-outs are shrunk toward the stream average; progress is shrunk toward zero for a short span. A ↓ marks a metric where lower is better (its bar is flipped). Every metric is under “Columns” or “Add a metric”.'
  });
}

function chartView(host) {
  var v = view(), P = peers(), rows = shown();
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var list = D.metrics.filter(function (m) { return okAny(m.id); });
  var x = has(ST.x) && okAny(ST.x) ? ST.x : v.x, y = has(ST.y) && okAny(ST.y) ? ST.y : v.y;
  var c = ST.c === 'cls' || ST.c === 'tested' ? ST.c : has(ST.c) && okAny(ST.c) ? ST.c : (isAll() ? 'cls' : 'rt');
  var presets = [{ x: v.x, y: v.y, c: 'rt' }, { x: 'rel', y: 'rt', c: 'cls' }, { x: 'make', y: 'beat', c: 'rt' }, { x: 'sh_s', y: 'sh_b', c: 'cls' }, { x: 'jump3', y: 'third', c: 'rt' }, { x: 'prog', y: 'rt', c: 'cls' }, { x: 'cons', y: 'value', c: 'rt' }, { x: 'rel_d', y: 'rel_s', c: 'cls' }];
  presets = presets.filter(function (pr, i, a) { return okAny(pr.x) && okAny(pr.y) && a.findIndex(function (q) { return q.x === pr.x && q.y === pr.y; }) === i; });
  var pi = -1; presets.forEach(function (pr, i) { if (pi < 0 && pr.x === x && pr.y === y) pi = i; });
  var grouped = {};
  list.forEach(function (m) { (grouped[m.family] = grouped[m.family] || []).push(m); });
  var sel = function (id, cur, colour) {
    return '<select class="qk-select" id="' + id + '">' + (colour ? '<option value="cls"' + (cur === 'cls' ? ' selected' : '') + '>Weight class</option><option value="tested"' + (cur === 'tested' ? ' selected' : '') + '>Tested or not</option>' : '') +
      Object.keys(grouped).map(function (f) { return '<optgroup label="' + esc(FAMILY_NAME[f] || f) + '">' + grouped[f].map(function (m) { return '<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + esc(m.label) + '</option>'; }).join('') + '</optgroup>'; }).join('') + '</select>';
  };
  var mx = mmeta(x), my = mmeta(y), mc = c !== 'cls' && c !== 'tested' ? mmeta(c) : null;
  host.innerHTML = '<section class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
    presets.length ? { label: 'Preset', html: '<select class="qk-select" id="sr-preset">' + presets.map(function (pr, i) { return '<option value="' + i + '"' + (i === pi ? ' selected' : '') + '>' + esc(mmeta(pr.y).label + ' against ' + mmeta(pr.x).label) + '</option>'; }).join('') + '<option value="-1"' + (pi < 0 ? ' selected' : '') + '>Any two metrics</option></select>', cls: 'grow' } : null,
    { label: 'Across', html: sel('sr-x', x) }, { label: 'Up', html: sel('sr-y', y) }, { label: 'Colour', html: sel('sr-c', c, true) }]) +
    '<h3 class="ir-chart-t">' + esc(my.label) + ' against ' + esc(mx.label) + '</h3>' +
    U.chart('sr-sc', 520, my.label + ' against ' + mx.label) + '<p class="ir-note" id="sr-ckey"></p><div id="sr-legend"></div><div id="sr-sim"></div></div></section>';
  var pts = rows.filter(function (r) { return isNum(val(r, x)) && isNum(val(r, y)); });
  var hits = String(ST.q || '').trim().length > 1 ? pts.filter(matches) : [];
  var med = function (a) { var b = a.slice().sort(function (p, q) { return p - q; }), n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
  var noC = QK.cssVar('--ink-3') || '#939bab';
  var cols = {};
  D.classes.forEach(function (k, i) { cols[k] = QK.cssVar(CCOL[i % CCOL.length].replace(/^var\(|\)$/g, '')) || noC; });
  var colour = function (r) {
    if (c === 'cls') return cols[r.cls] || noC;
    if (c === 'tested') return isNum(r.tested) ? (r.tested >= 0.5 ? (QK.cssVar('--c-1') || '#7d93ff') : (QK.cssVar('--c-5') || '#ff9f43')) : noC;
    var p0 = pctOf(r, c); return isNum(p0) ? QK.pctHex(p0) : noC;
  };
  var nf = function (id) { return function (v0) { return IR.vfmt(id, v0, D.M); }; };
  QKC.scatter(document.getElementById('sr-sc'), {
    points: pts.map(function (r) { var hit = hits.indexOf(r) >= 0; return { x: val(r, x), y: val(r, y), name: r.n + ' · ' + subOf(r) + (mc ? ' · ' + mc.label + ' ' + mc.fmt(val(r, c)) : ''), label: QK.surname(r.n), color: colour(r), size: hit ? 20 : (pts.length > 600 ? 5 : pts.length > 250 ? 7 : 10), href: href(r), id: r.id }; }),
    xName: mx.label + (mx.unitShort ? ' (' + mx.unitShort + ')' : '') + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.unitShort ? ' (' + my.unitShort + ')' : '') + (my.lower ? ' (lower is better: flipped)' : ''),
    xFmt: nf(x), yFmt: nf(y), xInverse: mx.lower, yInverse: my.lower, labelTop: 10, pad: '8%',
    refX: pts.length > 2 ? med(pts.map(function (r) { return val(r, x); })) : null, refY: pts.length > 2 ? med(pts.map(function (r) { return val(r, y); })) : null,
    quadrants: mx.style || my.style ? ['', '', '', ''] : ['', 'Better on both', 'Behind on both', ''],
    onClick: function (pt) { openProfile(pt.id); }, label: my.label + ' against ' + mx.label });
  document.getElementById('sr-ckey').innerHTML = pts.length + ' ' + esc(grpNoun()) + ' on the chart (' + esc(floorText()) + '); dashed lines are their medians' + (mx.style || my.style ? '.' : ', better is up and to the right.') + ' ' +
    (c === 'cls' ? 'Colour: the weight class (key below).' : c === 'tested' ? 'Colour: mostly tested meets (blue) or mostly untested (orange).' : 'Colour: <b>' + esc(mc.label) + '</b>, each lifter’s percentile in the peer group (blue low, red high; grey: none).') + ' Tap a point for the profile.';
  if (c === 'cls') document.getElementById('sr-legend').innerHTML = '<div class="qk-legend ir-legend">' + D.classes.filter(function (k) { return pts.some(function (r) { return r.cls === k; }); }).map(function (k) { return '<span><i style="background:' + cols[k] + '"></i>' + esc(k) + ' kg</span>'; }).join('') + '</div>';
  var sim = document.getElementById('sr-sim');
  if (hits.length) {
    var t = hits[0];
    var near = QK.within.similar(P.indexOf(t) >= 0 ? P : P.concat([t]), t, keyMetrics(v), function (r, k) { return val(r, k); }, 5);
    sim.innerHTML = QK.within.simHtml('Most like ' + t.n + ' · ' + grpNoun(), near.map(function (o) { return { name: o.row.n, href: href(o.row), sub: subOf(o.row) }; }));
  } else sim.innerHTML = '<p class="ir-note">Search a name in the bar above to ring the lifter and list the five most like them.</p>';
  var $ = function (id) { return document.getElementById(id); };
  var go = function () { ST.x = $('sr-x').value; ST.y = $('sr-y').value; ST.c = $('sr-c').value; drawView(); };
  ['sr-x', 'sr-y', 'sr-c'].forEach(function (id) { $(id).onchange = go; });
  if ($('sr-preset')) $('sr-preset').onchange = function (e) { var pr = presets[Number(e.target.value)]; if (!pr) return; ST.x = pr.x; ST.y = pr.y; ST.c = pr.c; drawView(); };
}

function leadersView(host) {
  var v = view(), rows = shown(), P = peers(), noun = grpNoun();
  var ids = keyMetrics(v).concat(['bomb', 'cons']).filter(function (id, i, a) { return a.indexOf(id) === i && has(id); }).slice(0, 12);
  host.innerHTML = '<div class="ir-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + grpName(), title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + esc(noun) + ' on screen. Bars are percentiles against the ' + P.length + ' in the peer group; the strip under each card is everyone on screen, with the median dashed' + (String(ST.q || '').trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
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
    var m = mmeta(id);
    var vals = rows.filter(function (r) { return isNum(val(r, id)); }).map(function (r) { return { v: val(r, id), name: r.n + ' · ' + (r.cls || '') + ' kg', id: r.id, hl: matches(r) || String(r.id) === ST.p }; });
    QKC.strip(el, { values: vals, xName: m.label + (m.unitShort ? ' (' + m.unitShort + ')' : ''), fmt: m.fmt, lower: m.lower, label: 'Every lifter on ' + m.label, onClick: function (d) { openProfile(d.id); } });
  });
}

function openProfile(id) {
  var r = findRow(id);
  if (!r) return;
  ST.p = String(r.id); writeQuery();
  var g = grpOf(r), v = view(g), P = peers(g);
  var row = function (id2) { var m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2, g), value: m.fmt(x), tip: m.tip }; };
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(row).filter(function (x) { return x && isNum(x.pctl); }) }; }).filter(function (s) { return s.rows.length; });
  var stats = ['rt', 'total', 'make'].filter(has).map(function (id2) { var m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2, g), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Meets', value: String(r.meets), sub: 'in two years' });
  var pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  var near = QK.within.similar(pool, r, keyMetrics(v), function (rr, k) { return val(rr, k); }, 5);
  var html = QK.profile({
    kicker: IR.STREAMS[ST.s] + ' · ' + (r.cls ? r.cls + ' kg' : ''), name: r.n, href: href(r),
    sub: [isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', r.cc, isNum(r.bw) ? IR.kg(r.bw) : '', r.meets + ' meets in two years'].filter(Boolean).join(' · '),
    team: markOf(r), stats: stats, peer: grpNoun(g) + ', ' + floorText(), groups: groups,
    similar: { label: 'Most like ' + QK.surname(r.n) + ' · ' + grpNoun(g), items: near.map(function (o) { return { name: o.row.n, href: href(o.row), id: o.row.id, sub: subOf(o.row) }; }) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(String(r.id)) ? ' solid' : ' primary') + '" id="sr-pf-pin">' + (TRAY && TRAY.has(String(r.id)) ? '✓ In the tray' : '+ Pin to compare') + '</button> ' + IR.followStar(r.id, r.n, r.cc),
    links: r.pg ? [{ label: 'Full lifter page', href: href(r), primary: true }] : [],
    note: 'Percentiles against the ' + P.length + ' ' + esc(grpNoun(g)) + ' in the peer group. “Most like” is the nearest five on the key metrics.'
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
    item: function (id) { var r = findRow(id); return r ? { name: r.n, short: QK.surname(r.n), sub: (r.cls || '') + ' kg · ' + (r.cc || '') } : { name: id }; },
    onChange: function (ids) { ST.cmp = ids; writeQuery(); },
    href: function () { return null; },
    body: trayBody
  });
}
function trayBody(ids) {
  var rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  var gs = rs.map(grpOf);
  var v = view(gs[0]);
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(function (id) {
    var m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(function (r, i) { var x = val(r, id); return { text: isNum(x) ? m.fmt(x) : '–', pctl: isNum(x) && !m.style ? pctOf(r, id, gs[i]) : null }; }) };
  }) }; });
  return QK.trayCompare({ entities: rs.map(function (r) { return { name: r.n, short: QK.surname(r.n), sub: (r.cls || '') + ' kg · ' + (r.cc || '') + ' · ' + r.meets + ' meets', href: href(r) }; }),
    groups: groups, note: 'Percentiles: each lifter against their own peer group past the floor (two years of meets).' });
}

IR.page('scout', render);
})();
