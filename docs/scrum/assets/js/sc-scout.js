/* The Quant Scrum — the Scouting Room (#/<S>/scout), rebuilt 2 Nov 2026 to the other sites' standard (cc-scout.js and
 * hw-scout.js are the references). Kit: scout.js (QK.board, QK.leaderCard, QKC.strip, QK.drawer, QK.profile, QK.tray,
 * QK.trayCompare, QK.scoutBar) and quant.js (QK.within.similar / viewPresets, QK.hotRow).
 *
 * One control bar drives every view: "Players" (All players, Forwards, Backs, then each position group: front row,
 * locks, back row, half-backs, centres, back three), the minimum minutes (default: the regulars, 160+ minutes in the
 * last two years), side, tier, age band and search. Under the bar, "Top of the group": the leader on five of the
 * group's key metrics. Views (?view=):
 *   board    (default) the deep table: column sets as chips (the group's view, then every metric family), any metric
 *            added, cells on the percentile scale within the peers (the group past the floor; lower-is-better flipped),
 *            top 50 then "Show all", CSV;
 *   chart    any two metrics (the group's presets first), coloured by team, by position group or by a metric's
 *            percentile, medians, the corners named, the search ringed and "Most like" it;
 *   leaders  small multiples on the group's key metrics: the top five and the bottom three over a dot strip.
 * A name anywhere opens the profile drawer (?p=<id>); pin up to four to the compare tray (?cmp=).
 * Address: ?view, grp=all|fwd|back|<group>, min, team, tier, age, q, cols, add, sort, dir, all, p, cmp, x, y, c.
 * Data: <S>/players.json (every player with 40+ minutes in the window, column-oriented: the shrunk per-80 rates).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;

var GROUPS = ['front_row', 'lock', 'back_row', 'halves', 'centres', 'back_three'];
var BROAD = { all: ['All players', null, 'players'], fwd: ['Forwards', ['front_row', 'lock', 'back_row'], 'forwards'], back: ['Backs', ['halves', 'centres', 'back_three'], 'backs'] };
/* each group's view (the same sets as the rugby spec, scripts/scrum_spec.py VIEW): what makes it good, its output, its value */
var VIEW = {
  all: [['Value and work', ['val80', 'inv']], ['Attack', ['m', 'cb', 'db', 'tries', 'ta', 'off', 'mpc']], ['Defence and discipline', ['tk', 'tkpct', 'mt', 'pc', 'cards', 'toc']], ['inv', 'val80']],
  fwd: [['Value and work', ['val80', 'inv', 'rk']], ['Carrying', ['car', 'm', 'db', 'off', 'mpc']], ['Defence and the set piece', ['tk', 'tkpct', 'mt', 'pc', 'lopct', 'ml']], ['tk', 'car']],
  back: [['Value', ['val80', 'ta', 'tries']], ['Attack', ['m', 'cb', 'db', 'off', 'mpc', 'pas']], ['Kicking and defence', ['kfh', 'gkp', 'kpct', 'tk', 'tkpct', 'mt']], ['m', 'cb']],
  front_row: [['Work and the set piece', ['tkpct', 'lopct', 'rk', 'mt', 'pc']], ['Carrying and tackling', ['tk', 'car', 'm', 'inv', 'ml']], ['tk', 'car']],
  lock: [['Work and discipline', ['tkpct', 'rk', 'mt', 'pc', 'ml']], ['Carrying and tackling', ['tk', 'car', 'm', 'inv', 'db']], ['tk', 'car']],
  back_row: [['Contact and discipline', ['tkpct', 'db', 'mpc', 'mt', 'pc']], ['Carrying and tackling', ['tk', 'car', 'm', 'inv', 'off', 'rk']], ['tk', 'm']],
  halves: [['Control', ['kpct', 'ta', 'pas', 'mt', 'toc']], ['Points and the kicking game', ['pts', 'gkp', 'kfh', 'm', 'tk']], ['pas', 'kfh']],
  centres: [['Breaking the line', ['cb', 'db', 'mpc', 'tkpct', 'off']], ['Output', ['m', 'car', 'ta', 'tries', 'tk']], ['m', 'cb']],
  back_three: [['Breaking the line', ['cb', 'db', 'mpc', 'tkpct']], ['Output', ['m', 'tries', 'kfh', 'car', 'ta']], ['m', 'cb']]
};
var PCT = { tkpct: 1, kpct: 1, lopct: 1 };
var FAMILY_NAME = { value: 'Value', scoring: 'Scoring', creating: 'Creating', carrying: 'Carrying', defence: 'Defence', 'set piece': 'Set piece', breakdown: 'Breakdown and work', discipline: 'Discipline and handling', kicking: 'Kicking' };
var AGES = [['', 'Any age'], ['u23', 'Under 23'], ['23-26', '23 to 26'], ['27-30', '27 to 30'], ['31p', '31 and over']];
var AGE_TEST = { u23: function (a) { return a < 23; }, '23-26': function (a) { return a >= 23 && a < 27; }, '27-30': function (a) { return a >= 27 && a < 31; }, '31p': function (a) { return a >= 31; } };
var GCOL = { front_row: 'var(--c-1)', lock: 'var(--c-2)', back_row: 'var(--c-3)', halves: 'var(--c-4)', centres: 'var(--c-5)', back_three: 'var(--c-6)' };

var ST = { S: 'men', view: 'board', grp: 'all', min: null, team: '', tier: '', age: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [], x: '', y: '', c: '' };
var D = null, DK = '', ROOT = null, TRAY = null, BOARD = null, PC = {}, CAT = null;

/* ── data ────────────────────────────────────────────────────────────── */
function prep(d) {
  var cols = d.cols || [], rows = [];
  (d.rows || []).forEach(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; rows.push(o); });
  var M = {};
  (d.metrics || []).forEach(function (m) { M[m.id] = m; });
  var mets = (d.metrics || []).filter(function (m) { return rows.some(function (r) { return isNum(r[m.id]); }); });
  return { rows: rows, M: M, metrics: mets, minQ: d.min_q || 160, from: d.from, maxMin: Math.max.apply(null, rows.map(function (r) { return r.min || 0; }).concat([200])) };
}
function val(r, id) { var v = r[id]; return isNum(v) ? v : null; }
function has(id) { return !!(D && D.M[id]); }
function mmeta(id) {
  var m = (D && D.M[id]) || { id: id, label: id };
  var spec = CAT && CAT.metric ? CAT.metric(id, 'player') : null;
  var tip = CAT && CAT.tip ? CAT.tip(id, 'player', m.label || id) : m.label;
  return { id: id, label: (spec && spec.label) || m.label || id, short: m.short || m.label, tip: tip || '', lower: m.dir === 'lower', style: false,
    ours: id === 'val80' ? { name: 'Scrum value', about: 'Our player value model: points of margin per 80 minutes above a replacement-level player of the position' } : null,
    fmt: function (v) { return SC.vfmt(id, v); }, family: m.family || 'other' };
}

/* ── groups, the floor, peers ────────────────────────────────────────── */
function isBroad(g) { return !!BROAD[g || ST.grp]; }
function grpName(g) { g = g || ST.grp; return BROAD[g] ? BROAD[g][0] : SC.GROUP[g] || g; }
function grpNoun(g) { g = g || ST.grp; return BROAD[g] ? BROAD[g][2] : (SC.GROUP[g] || g).toLowerCase(); }
function inGroup(r, g) { g = g || ST.grp; if (BROAD[g]) return !BROAD[g][1] || BROAD[g][1].indexOf(r.grp) >= 0; return r.grp === g; }
function past(r) { return isNum(ST.min) ? (r.min || 0) >= ST.min : !!r.q; }
function peers(g) { g = g || ST.grp; return D.rows.filter(function (r) { return inGroup(r, g) && past(r); }); }
function keep(r) {
  if (ST.team && String(r.team) !== ST.team) return false;
  if (ST.tier && String(r.tier) !== ST.tier) return false;
  if (ST.age) { if (!isNum(r.age) || !AGE_TEST[ST.age](r.age)) return false; }
  return true;
}
function shown() { return peers().filter(keep); }
function fold(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function matches(r) { var q = fold(String(ST.q || '').trim()); return q.length > 1 && fold(r.n + ' ' + SC.tname(ST.S, r.team) + ' ' + SC.tabbr(ST.S, r.team)).indexOf(q) >= 0; }
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
function floorText() { return isNum(ST.min) ? ST.min + '+ minutes' : 'regulars (' + D.minQ + '+ minutes)'; }

function view(g) {
  g = g || ST.grp;
  var v = VIEW[g] || VIEW.all, P = peers(g);
  var ok = function (id) { return has(id) && P.filter(function (r) { return isNum(val(r, id)); }).length >= Math.max(3, 0.3 * P.length); };
  var sets;
  if (BROAD[g]) sets = v.slice(0, 3).map(function (s, i) { return { key: ['aggregate', 'excellence', 'production'][i], label: s[0], ids: s[1].filter(ok) }; });
  else sets = [{ key: 'excellence', label: v[0][0], ids: v[0][1].filter(ok) }, { key: 'production', label: v[1][0], ids: v[1][1].filter(ok) }, { key: 'aggregate', label: 'Value', ids: ['val80'].filter(ok) }];
  sets = sets.filter(function (s) { return s.ids.length; });
  var axes = BROAD[g] ? v[3] : v[2];
  return { x: ok(axes[0]) ? axes[0] : null, y: ok(axes[1]) ? axes[1] : null, color: 'val80', sets: sets };
}
function keyMetrics(v) {
  var out = [];
  v.sets.forEach(function (s) { s.ids.forEach(function (id) { if (out.indexOf(id) < 0 && out.length < 9) out.push(id); }); });
  if (out.indexOf('val80') < 0 && has('val80')) out.unshift('val80');
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  ST.view = ['board', 'chart', 'leaders'].indexOf(q.view) >= 0 ? q.view : 'board';
  ST.grp = BROAD[q.grp] || GROUPS.indexOf(q.grp) >= 0 ? q.grp : 'all';
  var mn = parseInt(q.min, 10); ST.min = isNaN(mn) ? null : mn;
  ST.team = q.team || ''; ST.tier = /^[123]$/.test(q.tier || '') ? q.tier : ''; ST.age = AGE_TEST[q.age] ? q.age : '';
  ST.q = q.q || ''; ST.cols = q.cols || ''; ST.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  ST.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  ST.all = q.all === '1'; ST.p = q.p || ''; ST.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  ST.x = q.x || ''; ST.y = q.y || ''; ST.c = q.c || '';
}
function hashNow() {
  var q = [];
  var add = function (k, v) { if (v !== '' && v !== null && v !== undefined) q.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); };
  if (ST.view !== 'board') add('view', ST.view);
  if (ST.grp !== 'all') add('grp', ST.grp);
  if (isNum(ST.min)) add('min', ST.min);
  ['team', 'tier', 'age', 'q', 'cols'].forEach(function (k) { add(k, ST[k]); });
  if (ST.add.length) add('add', ST.add.join(','));
  if (ST.sort && ST.sort.key && !(ST.sortDef && ST.sortDef.key === ST.sort.key && ST.sortDef.dir === ST.sort.dir)) { add('sort', ST.sort.key); add('dir', ST.sort.dir); }
  if (ST.all) add('all', '1');
  add('p', ST.p);
  if (ST.cmp.length) add('cmp', ST.cmp.join(','));
  if (ST.view === 'chart') { add('x', ST.x); add('y', ST.y); add('c', ST.c); }
  return SC.href(ST.S, 'scout', null, q.join('&'));
}
function writeQuery() { try { history.replaceState(null, '', hashNow()); } catch (e) { /* no history API */ } }

/* ── names, links ────────────────────────────────────────────────────── */
function href(r) { return SC.playerHref(ST.S, r.id); }
function teamOf(r) { var t = SC.team(ST.S, r.team) || {}; return { abbr: t.abbr || '', colour: t.colour || '', alt: t.alt || '', name: t.name || '' }; }
function subOf(r) { return [SC.posName(r.pos), SC.tabbr(ST.S, r.team), isNum(r.age) ? 'age ' + Math.floor(r.age) : '', r.gp + ' tests'].filter(Boolean).join(' · '); }
function findRow(id) { var s = String(id); for (var i = 0; i < D.rows.length; i++) if (String(D.rows[i].id) === s) return D.rows[i]; return null; }
function grpOf(r) { return isBroad() && inGroup(r) ? ST.grp : r.grp; }

/* ── render ──────────────────────────────────────────────────────────── */
function render(page, P) {
  ST.S = P.S;
  ROOT = page;
  readQuery(P.query || {});
  page.innerHTML = U.head('Scouting Room', 'Every player and every metric, judged against the same position: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare. Rates per 80 minutes over the last two years, shrunk toward the position so a cameo cannot top a list.', SC.SNAME[ST.S]) +
    '<div class="sc qk-room"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sr-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sr-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].map(function (t) { return '<button type="button" class="qk-tab" role="tab" id="sr-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (ST.view === t[0]) + '" tabindex="' + (ST.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>'; }).join('') +
    /* the full player compare page (sc-compare.js): the tray's players when two or more are pinned, else its defaults */
    '<a class="qk-tab" id="sr-tab-compare" href="' + esc(SC.href(ST.S, 'compare', null, 'view=players')) + '" aria-selected="false">Compare</a>' +
    '<a class="qk-tab" href="' + esc(SC.href(ST.S, 'progression', null, 'view=players')) + '" aria-selected="false">Progression</a>' +
    '</div><div id="sr-view" class="sc-view" role="tabpanel" aria-labelledby="sr-tab-' + ST.view + '"></div></div>';
  SC.onLeave(function () { if (QK.drawer && QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  page.addEventListener('click', pickClick);
  return Promise.all([SC.load(ST.S + '/players.json'), QK.spec && QK.spec.load ? QK.spec.load('rugby') : Promise.resolve(null)]).then(function (res) {
    if (!U.alive(page)) return;
    CAT = res[1];
    if (!SC.ok(res[0])) { QK.$('#sr-ctl', page).innerHTML = ''; QK.$('#sr-view', page).innerHTML = U.missing('The Scouting Room', res[0]); return; }
    if (DK !== ST.S) { D = prep(res[0]); DK = ST.S; clearPct(); }
    controls(); tabs(); tray(); cmpTab(); refresh();
    if (ST.p) { var r = findRow(ST.p); if (r) openProfile(r.id); }
  });
}

function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  var a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || !D || a.closest('.qk-drawer')) return;
  var m = /#\/(?:men|women)\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────── */
function controls() {
  var host = document.getElementById('sr-ctl');
  if (!host) return;
  var opt = function (v, t, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>'; };
  var grpSel = '<select class="qk-select" id="sr-grp" aria-label="Players to compare">' + ['all', 'fwd', 'back'].map(function (g) { return opt(g, BROAD[g][0], ST.grp); }).join('') +
    '<optgroup label="By position">' + GROUPS.map(function (g) { return opt(g, SC.GROUP[g], ST.grp); }).join('') + '</optgroup></select>';
  var teams = Array.from(new Set(D.rows.filter(function (r) { return inGroup(r); }).map(function (r) { return String(r.team || ''); }).filter(Boolean)))
    .sort(function (a, b) { return SC.tname(ST.S, a).localeCompare(SC.tname(ST.S, b)); });
  var mx = Math.ceil(D.maxMin / 40) * 40;
  var items = [
    { label: 'Players', html: grpSel },
    { label: 'Min minutes', html: '<span class="sc-min"><input type="range" id="sr-min" min="0" max="' + mx + '" step="20" value="' + (isNum(ST.min) ? ST.min : 0) + '" aria-label="Minimum minutes"><b class="qk-sbar-v" id="sr-min-v">' + (isNum(ST.min) ? ST.min : 'Regulars') + '</b></span>', cls: 'sc-minf' },
    { label: 'Side', html: '<select class="qk-select" id="sr-team">' + opt('', 'Every side', ST.team) + teams.map(function (t) { return opt(t, SC.tname(ST.S, t), ST.team); }).join('') + '</select>' },
    { label: 'Tier', html: '<select class="qk-select" id="sr-tier">' + opt('', 'Every tier', ST.tier) + opt('1', 'Tier one', ST.tier) + opt('2', 'Tier two', ST.tier) + opt('3', 'Tier three', ST.tier) + '</select>' },
    D.rows.some(function (r) { return isNum(r.age); }) ? { label: 'Age', html: '<select class="qk-select" id="sr-age">' + AGES.map(function (a) { return opt(a[0], a[1], ST.age); }).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sr-q" type="search" placeholder="Player or side…" value="' + esc(ST.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  host.innerHTML = '<p class="sc-floor">' + esc(grpName()) + ', ' + esc(floorText()) + ' · ' + peers().length + ' in the peer group' + (D.from ? ' · tests since ' + esc(SC.date(D.from)) : '') +
    '. Percentiles are against the peer group, whatever the side, tier or age filters show. Drag the slider for any number of minutes; back to 0 is the regulars’ floor.</p>' + QK.scoutBar(items);
  var $ = function (id) { return document.getElementById(id); };
  $('sr-grp').onchange = function (e) { ST.grp = e.target.value; regroup(); };
  $('sr-min').oninput = function (e) { $('sr-min-v').textContent = Number(e.target.value) ? e.target.value : 'Regulars'; };
  $('sr-min').onchange = function (e) { var n = Number(e.target.value); ST.min = n > 0 ? n : null; clearPct(); controls(); refresh(); };
  $('sr-team').onchange = function (e) { ST.team = e.target.value; refresh(); };
  $('sr-tier').onchange = function (e) { ST.tier = e.target.value; refresh(); };
  if ($('sr-age')) $('sr-age').onchange = function (e) { ST.age = e.target.value; refresh(); };
  var t = null;
  $('sr-q').oninput = function (e) { ST.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
function regroup() { ST.cols = ''; ST.x = ''; ST.y = ''; ST.c = ''; ST.sort = null; ST.add = []; clearPct(); controls(); refresh(); }

/* ── views ───────────────────────────────────────────────────────────── */
function tabs() {
  var bar = ROOT.querySelector('.sc-tabs');
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
    return { sport: 'rugby', kicker: m.label, name: r.n, value: m.fmt(val(r, id)), title: SC.tabbr(ST.S, r.team) + ' · ' + SC.posName(r.pos), next: nx ? { name: nx.n, value: m.fmt(val(nx, id)) } : null, expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + (isBroad() ? 'group' : 'position'), title: 'The best ' + grpNoun() + ', on what matters there',
    sub: 'The leader on five of the ' + (isBroad() ? 'group' : 'position') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}

/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  var v = view(), P = peers();
  var all = shown();
  var rows = String(ST.q || '').trim() ? all.filter(matches) : all;
  var sets = [{ key: 'view', label: isBroad() ? 'Headline' : 'Position view', groups: v.sets.map(function (s) { return { label: s.label, ids: s.ids }; }) }];
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var fams = [];
  D.metrics.forEach(function (m) { if (fams.indexOf(m.family) < 0 && okAny(m.id)) fams.push(m.family); });
  fams.forEach(function (f) { sets.push({ key: f, label: FAMILY_NAME[f] || f, groups: [{ label: FAMILY_NAME[f] || f, ids: D.metrics.filter(function (m) { return m.family === f && okAny(m.id); }).map(function (m) { return m.id; }) }] }); });
  var setKey = QK.board.pick(sets, ST.cols, 'view');
  var LEAD = ['name', 'gp', 'min', 'age'];
  var sort = ST.sort && ST.sort.key && (LEAD.indexOf(ST.sort.key) >= 0 || has(ST.sort.key)) ? ST.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: LEAD.indexOf(sort.key) < 0 && mmeta(sort.key).lower ? 'asc' : 'desc' };
  ST.sortDef = { key: 'val80', dir: 'desc' };
  if (!sort) sort = ST.sortDef;
  var addable = fams.map(function (f) { return '<optgroup label="' + esc(FAMILY_NAME[f] || f) + '">' + D.metrics.filter(function (m) { return m.family === f && okAny(m.id); }).map(function (m) { return '<option value="' + esc(m.id) + '">' + esc(mmeta(m.id).label) + (m.dir === 'lower' ? ' ↓' : '') + '</option>'; }).join('') + '</optgroup>'; }).join('');
  var noun = grpNoun();
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><h2 class="qk-card-title">The board</h2><div class="qk-card-sub">' +
    esc(grpName()) + ' · the bar under each number is its percentile against the ' + P.length + ' ' + esc(noun) + ', ' + esc(floorText()) + ': the top 10% in red, the bottom 10% in blue. Tap a name for the profile; tick the box beside it to pin it to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sr-board"></div></div></section>';
  BOARD = QK.board(document.getElementById('sr-board'), {
    id: 'sr-bd', summary: 'val80', sets: sets, set: setKey, added: ST.add.filter(has), sort: sort, all: ST.all, page: 50, noun: noun,
    nameLabel: 'Player', subLabel: 'Position · side · age · tests',
    meta: mmeta, addable: addable,
    lead: [{ key: 'gp', label: 'Tests', tip: 'Tests in the window', fmt: function (row) { return String(row._r.gp); }, val: function (row) { return row._r.gp; } },
      { key: 'min', label: 'Min', tip: 'Minutes in the window', fmt: function (row) { return fmt.num(row._r.min); }, val: function (row) { return row._r.min; } }],
    rows: rows.map(function (r) { return { id: r.id, name: r.n, sub: subOf(r), mark: teamOf(r), href: href(r), _r: r }; }),
    val: function (row, id) { return val(row._r, id); },
    peers: P.map(function (r) { return { id: r.id, _r: r }; }),
    hl: function (row) { return ST.cmp.indexOf(String(row.id)) >= 0; },
    pin: { has: function (id) { return !!TRAY && TRAY.has(String(id)); }, toggle: function (row) { pin(row._r); }, label: 'Pin to the compare tray' },
    onPick: function (row) { openProfile(row.id); },
    onState: function (st) { ST.cols = st.set === 'view' ? '' : st.set; ST.add = st.added; ST.sort = st.sort; ST.all = st.all; writeQuery(); },
    csv: 'scrum-' + ST.S + '-' + ST.grp + '.csv',
    empty: String(ST.q || '').trim() ? 'No ' + noun + ' match “' + ST.q.trim() + '” with these filters.' : 'No ' + noun + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Rates per 80 minutes over the last two years, shrunk toward the position average with 240 minutes of weight. Percentiles are against every player in the peer group; a ↓ marks a metric where lower is better (its bar is flipped). Every metric is under “Columns” or “Add a metric”.'
  });
}

/* Chart: any two metrics, the group's presets first; colour by team, position group or a metric's percentile */
function chartView(host) {
  var v = view(), P = peers(), rows = shown();
  var okAny = function (id) { return P.some(function (r) { return isNum(val(r, id)); }); };
  var list = D.metrics.filter(function (m) { return okAny(m.id); });
  var x = has(ST.x) && okAny(ST.x) ? ST.x : v.x, y = has(ST.y) && okAny(ST.y) ? ST.y : v.y;
  var c = ST.c === 'team' || ST.c === 'grp' ? ST.c : has(ST.c) && okAny(ST.c) ? ST.c : (isBroad() ? 'grp' : 'val80');
  if (!x || !y) { host.innerHTML = QK.empty('Nothing to chart', 'This group has too few metrics with values.'); return; }
  var presets = [];
  if (v.x && v.y) presets.push({ x: v.x, y: v.y, c: 'val80' });
  presets.push({ x: 'tk', y: 'tkpct', c: 'val80' }, { x: 'car', y: 'mpc', c: 'val80' }, { x: 'pc', y: 'val80', c: 'grp' }, { x: 'inv', y: 'val80', c: 'grp' }, { x: 'm', y: 'cb', c: 'val80' });
  presets = presets.filter(function (pr, i, a) { return okAny(pr.x) && okAny(pr.y) && a.findIndex(function (q) { return q.x === pr.x && q.y === pr.y; }) === i; });
  var pi = -1; presets.forEach(function (pr, i) { if (pi < 0 && pr.x === x && pr.y === y) pi = i; });
  var grouped = {};
  list.forEach(function (m) { (grouped[m.family] = grouped[m.family] || []).push(m); });
  var sel = function (id, cur, colour) {
    return '<select class="qk-select" id="' + id + '">' + (colour ? '<option value="team"' + (cur === 'team' ? ' selected' : '') + '>Team colours</option><option value="grp"' + (cur === 'grp' ? ' selected' : '') + '>Position group</option>' : '') +
      Object.keys(grouped).map(function (f) { return '<optgroup label="' + esc(FAMILY_NAME[f] || f) + '">' + grouped[f].map(function (m) { return '<option value="' + esc(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + esc(mmeta(m.id).label) + '</option>'; }).join('') + '</optgroup>'; }).join('') + '</select>';
  };
  var mx = mmeta(x), my = mmeta(y), mc = c !== 'team' && c !== 'grp' ? mmeta(c) : null;
  host.innerHTML = '<section class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
    presets.length ? { label: 'Preset', html: '<select class="qk-select" id="sr-preset">' + presets.map(function (pr, i) { return '<option value="' + i + '"' + (i === pi ? ' selected' : '') + '>' + esc(mmeta(pr.y).label + ' against ' + mmeta(pr.x).label) + '</option>'; }).join('') + '<option value="-1"' + (pi < 0 ? ' selected' : '') + '>Any two metrics</option></select>', cls: 'grow' } : null,
    { label: 'Across', html: sel('sr-x', x) }, { label: 'Up', html: sel('sr-y', y) }, { label: 'Colour', html: sel('sr-c', c, true) }]) +
    '<h3 class="sc-chart-t">' + esc(my.label) + ' against ' + esc(mx.label) + '</h3>' +
    U.chart('sr-sc', 520, my.label + ' against ' + mx.label) + '<p class="sc-note" id="sr-ckey"></p><div id="sr-legend"></div><div id="sr-sim"></div></div></section>';
  var pts = rows.filter(function (r) { return isNum(val(r, x)) && isNum(val(r, y)); });
  var hits = String(ST.q || '').trim().length > 1 ? pts.filter(matches) : [];
  var med = function (a) { var b = a.slice().sort(function (p, q) { return p - q; }), n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
  var noC = QK.cssVar('--ink-3') || '#939bab';
  var colour = function (r) {
    if (c === 'team') return SC.tcol(ST.S, r.team);
    if (c === 'grp') return QK.cssVar(GCOL[r.grp].replace(/^var\(|\)$/g, '')) || noC;
    var p0 = pctOf(r, c); return isNum(p0) ? QK.pctHex(p0) : noC;
  };
  var sc = function (id, v0) { return PCT[id] ? v0 * 100 : v0; };
  var lo0 = function (k) { var m0 = Math.min.apply(null, pts.map(function (r) { return val(r, k); })); return m0 >= 0 ? 0 : undefined; };
  QKC.scatter(document.getElementById('sr-sc'), {
    points: pts.map(function (r) { var hit = hits.indexOf(r) >= 0; return { x: sc(x, val(r, x)), y: sc(y, val(r, y)), name: r.n + ' · ' + SC.tabbr(ST.S, r.team) + ' · ' + SC.posName(r.pos) + (mc ? ' · ' + mc.label + ' ' + mc.fmt(val(r, c)) : ''), label: QK.surname(r.n), color: colour(r), size: hit ? 20 : (pts.length > 250 ? 7 : 10), href: href(r), id: r.id }; }),
    xName: mx.label + (PCT[x] ? ' (%)' : '') + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (PCT[y] ? ' (%)' : '') + (my.lower ? ' (lower is better: flipped)' : ''),
    xFmt: PCT[x] ? function (v0) { return Math.round(v0) + '%'; } : function (v0) { return fmt.num(v0, Math.abs(v0) >= 20 ? 0 : 1); },
    yFmt: PCT[y] ? function (v0) { return Math.round(v0) + '%'; } : function (v0) { return fmt.num(v0, Math.abs(v0) >= 20 ? 0 : 1); },
    xInverse: mx.lower, yInverse: my.lower, labelTop: 10, pad: '8%', xMin: pts.length && !PCT[x] ? lo0(x) : undefined, yMin: pts.length && !PCT[y] ? lo0(y) : undefined,
    refX: pts.length > 2 ? sc(x, med(pts.map(function (r) { return val(r, x); }))) : null, refY: pts.length > 2 ? sc(y, med(pts.map(function (r) { return val(r, y); }))) : null,
    quadrants: ['', 'Better on both', 'Behind on both', ''],
    onClick: function (pt) { openProfile(pt.id); }, label: my.label + ' against ' + mx.label });
  document.getElementById('sr-ckey').innerHTML = pts.length + ' ' + esc(grpNoun()) + ' on the chart (' + esc(floorText()) + '); dashed lines are their medians, better is up and to the right. ' +
    (c === 'team' ? 'Colour: each player’s side.' : c === 'grp' ? 'Colour: the position group (key below).' : 'Colour: <b>' + esc(mc.label) + '</b>, each player’s percentile in the peer group (blue low, red high; grey: none).') + ' Tap a point for the profile.';
  if (c === 'grp') document.getElementById('sr-legend').innerHTML = '<div class="qk-legend sc-legend">' + GROUPS.filter(function (g) { return pts.some(function (r) { return r.grp === g; }); }).map(function (g) { return '<span><i style="background:' + GCOL[g] + '"></i>' + esc(SC.GROUP[g]) + '</span>'; }).join('') + '</div>';
  var sim = document.getElementById('sr-sim');
  if (hits.length) {
    var t = hits[0];
    var near = QK.within.similar(P.indexOf(t) >= 0 ? P : P.concat([t]), t, keyMetrics(v), function (r, k) { return val(r, k); }, 5);
    sim.innerHTML = QK.within.simHtml('Most like ' + t.n + ' · ' + grpNoun(), near.map(function (o) { return { name: o.row.n, href: href(o.row), sub: subOf(o.row) }; }));
  } else sim.innerHTML = '<p class="sc-note">Search a name in the bar above to ring the player and list the five most like them.</p>';
  var $ = function (id) { return document.getElementById(id); };
  var go = function () { ST.x = $('sr-x').value; ST.y = $('sr-y').value; ST.c = $('sr-c').value; drawView(); };
  ['sr-x', 'sr-y', 'sr-c'].forEach(function (id) { $(id).onchange = go; });
  if ($('sr-preset')) $('sr-preset').onchange = function (e) { var pr = presets[Number(e.target.value)]; if (!pr) return; ST.x = pr.x; ST.y = pr.y; ST.c = pr.c; drawView(); };
}

/* Leaders: small multiples on the group's key metrics, each with a dot strip of the group */
function leadersView(host) {
  var v = view(), rows = shown(), P = peers(), noun = grpNoun();
  var ids = keyMetrics(v).concat(['pc', 'cards']).filter(function (id, i, a) { return a.indexOf(id) === i && has(id); }).slice(0, 12);
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + grpName(), title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + esc(noun) + ' on screen on the group’s key metrics. Bars are percentiles against the ' + P.length + ' in the peer group; the strip under each card is everyone on screen, with the median dashed' + (String(ST.q || '').trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map(function (id, i) {
      var m = mmeta(id);
      var list = rows.filter(function (r) { return isNum(val(r, id)); }).sort(function (a, b) { return m.lower ? val(a, id) - val(b, id) : val(b, id) - val(a, id); });
      if (!list.length) return '';
      var item = function (r, rk) { var p = pctOf(r, id); return { id: r.id, rank: rk, name: r.n, sub: subOf(r), href: href(r), text: m.fmt(val(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      var top = list.slice(0, 5).map(function (r, j) { return item(r, j + 1); });
      var bottom = list.length > 10 ? list.slice(-3).map(function (r, j) { return item(r, list.length - 2 + j); }) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + noun, top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sr-strip-' + i });
    }).join('') + '</div>';
  ids.forEach(function (id, i) {
    var el = document.getElementById('sr-strip-' + i);
    if (!el) return;
    var m = mmeta(id);
    var vals = rows.filter(function (r) { return isNum(val(r, id)); }).map(function (r) { return { v: PCT[id] ? val(r, id) * 100 : val(r, id), name: r.n + ' · ' + SC.tabbr(ST.S, r.team), id: r.id, hl: matches(r) || String(r.id) === ST.p }; });
    QKC.strip(el, { values: vals, xName: m.label + (PCT[id] ? ' (%)' : ''), fmt: PCT[id] ? function (v0) { return Math.round(v0) + '%'; } : m.fmt, lower: m.lower, label: 'Every ' + noun.replace(/s$/, '') + ' on ' + m.label, onClick: function (d) { openProfile(d.id); } });
  });
}

/* ── the profile drawer ──────────────────────────────────────────────── */
function openProfile(id) {
  var r = findRow(id);
  if (!r) return;
  ST.p = String(r.id); writeQuery();
  var g = grpOf(r), v = view(g), P = peers(g);
  var row = function (id2) { var m = mmeta(id2), x = val(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2, g), value: m.fmt(x), tip: m.tip }; };
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(row).filter(Boolean) }; });
  var t = teamOf(r);
  var stats = ['val80', v.x, v.y].filter(function (x, i, a) { return x && a.indexOf(x) === i; }).map(function (id2) { var m = mmeta(id2), x = val(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2, g), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Minutes', value: fmt.num(r.min), sub: r.gp + ' tests' });
  var pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  var near = QK.within.similar(pool, r, keyMetrics(v), function (rr, k) { return val(rr, k); }, 5);
  var inPeers = P.indexOf(r) >= 0;
  var html = QK.profile({
    kicker: SC.posName(r.pos) + ' · ' + (t.name || t.abbr),
    name: r.n, href: href(r),
    sub: [isNum(r.age) ? 'Age ' + Math.floor(r.age) : '', r.gp + ' tests', fmt.num(r.min) + ' min', 'the last two years'].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: grpNoun(g) + ', ' + floorText() + (inPeers ? '' : ' (this player is under the floor: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + QK.surname(r.n) + ' · ' + grpNoun(g), items: near.map(function (o) { return { name: o.row.n, href: href(o.row), id: o.row.id, sub: subOf(o.row) }; }) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(String(r.id)) ? ' solid' : ' primary') + '" id="sr-pf-pin">' + (TRAY && TRAY.has(String(r.id)) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: href(r), primary: true }, { label: SC.tname(ST.S, r.team), href: SC.teamHref(ST.S, r.team) }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(grpNoun(g)) + ' in the peer group. “Most like” is the nearest five on the group’s key metrics.'
  });
  var inner = QK.drawer.open({ html: html, label: r.n + ': profile', onClose: function () { ST.p = ''; writeQuery(); } });
  var pb = inner.querySelector('#sr-pf-pin');
  if (pb) pb.addEventListener('click', function () { pin(r); openProfile(r.id); });
  QK.$$('[data-pick]', inner).forEach(function (a) { a.addEventListener('click', function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'));
  }); });
}

/* ── the compare tray ────────────────────────────────────────────────── */
function pin(r) {
  if (!TRAY) return;
  TRAY.toggle(String(r.id));
  if (BOARD) QK.$$('[data-pin="' + r.id + '"]', ROOT).forEach(function (b) { var on = TRAY.has(String(r.id)); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: ST.cmp.filter(function (id) { return findRow(id); }), label: 'Compare tray',
    item: function (id) { var r = findRow(id); return r ? { name: r.n, short: QK.surname(r.n), sub: SC.posName(r.pos) + ' · ' + SC.tabbr(ST.S, r.team), colour: teamOf(r).colour } : { name: id }; },
    onChange: function (ids) { ST.cmp = ids; writeQuery(); cmpTab(); },
    href: function (ids) { return ids.length >= 2 ? SC.cmpHref(ST.S, 'p', ids.slice(0, 3)) : null; },
    body: trayBody
  });
}
/* the Compare tab opens the pinned players (two or three) when there are any, else the compare page's defaults */
function cmpTab() {
  var a = document.getElementById('sr-tab-compare');
  if (!a) return;
  var ids = ST.cmp.filter(function (id) { return findRow(id); }).slice(0, 3);
  a.setAttribute('href', ids.length ? SC.cmpHref(ST.S, 'p', ids) : SC.href(ST.S, 'compare', null, 'view=players'));
}
function trayBody(ids) {
  var rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  var gs = rs.map(grpOf);
  var v = view(gs[0]);
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(function (id) {
    var m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(function (r, i) { var x = val(r, id); return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id, gs[i]) : null }; }) };
  }) }; });
  return QK.trayCompare({ entities: rs.map(function (r) { var t = teamOf(r); return { name: r.n, short: QK.surname(r.n), sub: SC.posName(r.pos) + ' · ' + t.abbr + ' · ' + fmt.num(r.min) + ' min', colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own group’s peers past the floor (the last two years). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

SC.route('scout', render);
SC.scout = { view: view, mmeta: mmeta };
})();
