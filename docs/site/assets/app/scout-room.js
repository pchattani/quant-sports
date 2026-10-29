/* The Quant Footballer — the Scouting Room (#/scout): the Players pages (search, leaders across competitions) and the
 * Lab in one page built for quick analysis (round 9, 28 Oct 2026; the Bullpen pilot's design, bp-scout.js). Kit:
 * assets/qk/scout.js (QK.board, QK.leaderCard, QKC.strip, QK.drawer, QK.profile, QK.tray, QK.trayCompare,
 * QK.scoutBar) and quant.js (QK.within, QK.hotRow, QK.pctlBars).
 *
 * One control bar drives every view: "Compare within" Broad (goalkeepers, defenders, midfielders, forwards, or every
 * outfield player, by the line the payload ranks on) or Position (the metrics spec's formation-role groups: GK, CB,
 * FB/WB, DM/CM, AM/W, ST, on the rows' `role`), the season or window (this season, last season, the last 12 months,
 * the calendar year), the competitions (every competition, club football, national-team football or one
 * competition), the minimum minutes (the view's floor, and the spec's 450 / 900 in Position mode), club, age band and
 * search (the Board keeps the matches; the Chart and the Leaders highlight them). Under the bar, "Top of the
 * position": the leader on five of the view's metrics. Preferred foot is not a filter: fewer than 1 player in 20 has
 * it on record (people/<pid>.json `foot`, from the archive's profiles).
 * Views (?view=):
 *   board    (default) the deep table: column sets as chips ("Position view" = the spec view's excellence, attacking or
 *            on-the-ball output and value; "Our models"; every payload group: Scoring ... Rating), any single metric
 *            added, cells on the percentile scale within the peers (the group past the minimum; lower-is-better
 *            flipped), the top 50 then "Show all", "Download CSV" of what is on screen;
 *   chart    the Lab (lab.js, FB.lab.mount): presets, the Position view's axes, size, colour, shrinkage, league
 *            adjustment, medians, the ranked table and "Most like"; a dot opens the profile;
 *   leaders  small multiples: for the view's key metrics, the top five and the bottom three as bars, over a dot strip
 *            of the whole group with the median and the highlighted players marked.
 * Selecting a player anywhere (a name, a dot, a card) opens the profile drawer (?p=<pid>): percentile meters for the
 * view's sets, a line of headline numbers, "Most like", and links to the player page, the Progression tab and the full
 * Compare page. Pin up to four (the + on a row, or "Pin" in the drawer) to the compare tray (?cmp=<pid>,<pid>): side
 * by side on percentile bars, each against their own group's peers.
 * Address: ?view, w, c, within=pos&pos=<code> | grp=<G|D|M|F|O>, min, team, age, q, cols, add, sort, dir, all, p, cmp
 * and the chart's x, y, color, size, preset: links share.
 * Data: data/lab/index.json and data/lab/<window>/<scope>.json (UNIFIED_PAYLOADS 14: one row per person, every metric,
 * age, role, GAR/90 and GAR), loaded once per view and shared by the three views. The old routes (#/players,
 * #/players/leaders, #/lab/...) redirect here with their parameters (core.js).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum;

/* Broad: the position letters the payload ranks on; Position: the spec's formation-role groups. */
var BROAD = [['O', 'Outfield', 'outfield players', 'outfield player'], ['F', 'Forwards', 'forwards', 'forward'], ['M', 'Midfielders', 'midfielders', 'midfielder'],
  ['D', 'Defenders', 'defenders', 'defender'], ['G', 'Goalkeepers', 'goalkeepers', 'goalkeeper']];
/* [address code, spec group, display, role codes, line letter, minimum minutes, singular] */
var ROLES = [['GK', 'gk', 'Goalkeepers', ['GK'], 'G', 900, 'goalkeeper'], ['CB', 'cb', 'Centre-backs', ['CB'], 'D', 450, 'centre-back'],
  ['FB', 'fb', 'Full-backs and wing-backs', ['FB'], 'D', 450, 'full-back'], ['DM-CM', 'dm_cm', 'Defensive and central midfielders', ['DM', 'CM'], 'M', 450, 'central midfielder'],
  ['AM-W', 'am_w', 'Attacking midfielders and wingers', ['AM', 'W'], 'F', 450, 'attacking midfielder or winger'], ['ST', 'st', 'Strikers', ['ST'], 'F', 450, 'striker']];
var ROLE_CODES = ROLES.map(function (r) { return r[0]; });
var LETTER_ROLE = { G: 'GK', D: 'CB', M: 'DM-CM', F: 'ST', O: 'CB' };
var ROLE_LETTER_GROUPS = { F: ['st', 'am_w'], M: ['dm_cm', 'am_w'], D: ['cb', 'fb'], G: ['gk'], O: ['cb', 'fb', 'dm_cm', 'am_w', 'st'] };
var AGES = [['', 'Any age'], ['u21', 'Under 21'], ['21-24', '21 to 24'], ['25-28', '25 to 28'], ['29-32', '29 to 32'], ['33p', '33 and over']];
var AGE_TEST = { u21: function (a) { return a < 21; }, '21-24': function (a) { return a >= 21 && a < 25; }, '25-28': function (a) { return a >= 25 && a < 29; },
  '29-32': function (a) { return a >= 29 && a < 33; }, '33p': function (a) { return a >= 33; } };
var WIN_ORDER = ['season', 'last', '365', 'ytd'];
/* totals: a bottom three says nothing useful about playing time */
var TOTALS = { gar: 1, minutes: 1 };
/* our model metrics on the lab rows (value_fields.py), the fallbacks when the spec has no entry */
var OURS = { gar90: ['Value added (GAR/90)', '2'], gar: ['Goals above replacement (GAR)', '1'] };

/* The Value column set (round 9: Value › Players lives here): our value model's projection and four-season valuation,
   the fair fee and Sofascore's market value, from value/players.json (5 MB: read only when the set is opened), joined on
   the person id. [key in the board, payload field, label, format, explanation] */
var VALUE_COLS = [['v_par', 'par', 'Points above replacement (PAR)', '1', 'GAR times the points a goal of goal difference is worth, last 12 months of club football.'],
  ['v_proj', 'proj', 'Projected GAR/90', '2', 'GAR/90 shrunk toward replacement by 900 minutes: our projection of the next minutes.'],
  ['v_v2', 'v2', 'Valuation (points over four seasons)', '1', 'Expected points above replacement over the next four seasons (valuation v2).'],
  ['v_fee', 'fee', 'Fair fee (€)', 'money', 'The fee model fitted on real transfer fees: what a club like the player’s own would pay.'],
  ['v_mv', 'mv', 'Sofascore market value (€)', 'money', 'Sofascore’s proposed market value, a reference only.']];
var VAL = null, VAL_P = null;
function loadValue() {
  if (VAL) return Promise.resolve(VAL);
  if (VAL_P) return VAL_P;
  VAL_P = FB.load('value/players.json').then(function (d) {
    var out = {};
    FB.rows(d).forEach(function (r) { out[FB.personId(r.id)] = r; });
    VAL = out;
    return VAL;
  });
  return VAL_P;
}
var SC = { view: 'board', w: 'season', c: 'all', within: 'broad', bg: 'O', pg: 'ST', min: null, team: '', age: '', q: '', cols: '', add: [], sort: null, all: false, p: '', cmp: [],
  x: '', y: '', color: '', size: '', preset: '' };
var IX = null, V = null, VK = '', SPEC = null, ROOT = null, TRAY = null, BOARD = null, PCT = {};

function single() { return !FB.LAB_SCOPES[SC.c]; }
function role(code) { var r = ROLES.filter(function (x) { return x[0] === code; })[0] || ROLES[5]; var sg = SPEC && SPEC.group ? SPEC.group(r[1]) : null;
  return { code: r[0], id: r[1], name: (sg && sg.display) || r[2], codes: (sg && sg.codes && sg.codes.length) ? sg.codes : r[3], letter: r[4], min: sg && sg.min && isNum(sg.min.value) ? sg.min.value : r[5], one: r[6] }; }
function broad(code) { return BROAD.filter(function (x) { return x[0] === code; })[0] || BROAD[0]; }
function code() { return SC.within === 'pos' ? SC.pg : SC.bg; }
function noun(c) { c = c || code(); return SC.within === 'pos' && ROLE_CODES.indexOf(c) >= 0 ? role(c).name.toLowerCase() : broad(c)[2]; }
function one(c) { c = c || code(); return SC.within === 'pos' && ROLE_CODES.indexOf(c) >= 0 ? role(c).one : broad(c)[3]; }
function isGk(c) { c = c || code(); return c === 'G' || c === 'GK'; }

/* ── the payload ─────────────────────────────────────────────────────────── */
function I(k) { return V ? V.idx[k] : undefined; }
function raw(r, k) {
  if (k.charAt(0) === 'v' && k.charAt(1) === '_') { var vc = VALUE_COLS.filter(function (x) { return x[0] === k; })[0], vr = VAL && vc ? VAL[rid(r)] : null; return vr && isNum(vr[vc[1]]) ? Number(vr[vc[1]]) : null; }
  var i = I(k); if (i === undefined) return null; var v = r[i]; return isNum(v) ? Number(v) : null;
}
function rid(r) { return String(r[I('player_id')]); }
function rname(r) { return r[I('name')] || ''; }
function rmin(r) { return r[I('minutes')] || 0; }
function rage(r) { var a = r[I('age')]; return isNum(a) ? Number(a) : null; }
function rrole(r) { var i = I('role'); return i === undefined ? '' : (r[i] || ''); }
function rpos(r) { return r[I('position')] || ''; }
function rtid(r) { return r[I('tid')]; }
function rteam(r) { return r[I('team')] || ''; }
function inGroup(r, c) {
  c = c || code();
  if (ROLE_CODES.indexOf(c) >= 0) return role(c).codes.indexOf(rrole(r)) >= 0;
  var p = rpos(r);
  return c === 'O' ? !!p && p !== 'G' : p === c;
}
function defMin(c) {
  c = c || code();
  var f = (V && V.floor) || 90, m = Math.max(90, single() ? f : Math.min(f, 450));
  return ROLE_CODES.indexOf(c) >= 0 ? Math.max(m, role(c).min) : m;
}
function minNow() { return isNum(SC.min) ? SC.min : defMin(); }
function floorFor(c) { return c === code() ? minNow() : defMin(c); }
function peers(c) { c = c || code(); var m = floorFor(c); return V.rows.filter(function (r) { return inGroup(r, c) && rmin(r) >= m; }); }
function keep(r) {
  if (SC.team && String(rtid(r)) !== SC.team) return false;
  if (SC.age) { var a = rage(r); if (!isNum(a) || !AGE_TEST[SC.age](a)) return false; }
  return true;
}
function shown() { return peers().filter(keep); }
function fold(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function matches(r) { var q = fold(SC.q.trim()); return !!q && fold(rname(r) + ' ' + rteam(r)).indexOf(q) >= 0; }
function findRow(id) { var s = String(id); return V ? V.rows.filter(function (r) { return rid(r) === s; })[0] || null : null; }

/* metric display: the spec's name and explanation, our-model tag, direction, the payload's format */
function mmeta(id) {
  var vc = VALUE_COLS.filter(function (x) { return x[0] === id; })[0];
  if (vc) return { id: id, label: vc[2], short: vc[2], tip: vc[4], ours: vc[3] === 'money' && id === 'v_mv' ? null : { name: 'Player value model', about: '' }, lower: false, group: 'Value', scope: 'all',
    fmt: function (v) { return !isNum(v) ? '—' : vc[3] === 'money' ? FB.money(v) : FB.signed(v, Number(vc[3])); } };
  var m = (V && V.meta[id]) || {};
  var lab = FB.labOurs ? FB.labOurs.label(id, m.label || (OURS[id] || [id])[0]) : (m.label || id);
  var o = FB.labOurs ? FB.labOurs.oursOf(id) : null;
  var tip = FB.labOurs ? FB.labOurs.tip(id, m.desc || '') : (m.desc || '');
  var fmt = m.fmt || (OURS[id] || [])[1] || '2';
  return { id: id, label: lab, short: lab, tip: tip, ours: o ? { name: o.name, about: o.about } : null, lower: !!m.lower, group: m.group || 'Other', scope: m.scope || 'all',
    fmt: function (v) { return !isNum(v) ? '—' : id === 'gar90' ? FB.signed(v, 2) : id === 'gar' ? FB.signed(v, 1) : FB.fmtMetric(v, fmt); } };
}
function offered(id, c) { var s = mmeta(id).scope; return isGk(c) ? s !== 'out' : s !== 'gk'; }
function has(id) { return id.charAt(0) === 'v' && id.charAt(1) === '_' ? !!VAL : I(id) !== undefined; }

/* percentile of a row on a metric against a group's peers (the group past its minimum), better = higher */
function pctOf(r, id, c) {
  c = c || code();
  var key = c + '|' + floorFor(c) + '|' + id, srt = PCT[key];
  if (!srt) srt = PCT[key] = peers(c).map(function (x) { return raw(x, id); }).filter(isNum).sort(function (a, b) { return a - b; });
  var v = raw(r, id);
  if (!isNum(v) || srt.length < 5 || !offered(id, c)) return null;
  var p = QK.pctRank(srt, v);
  return mmeta(id).lower ? 100 - p : p;
}
function clearPct() { PCT = {}; }

/* The view: in Position mode the spec group's view (excellence, production, value) with ids this payload carries for
   30%+ of the peers; in Broad mode the spec's headline metrics of the line's role groups, then value. */
function view(c) {
  c = c || code();
  var P = peers(c), base = P.length >= 3 ? P : V.rows.filter(function (r) { return inGroup(r, c); });
  var memo = {};
  var okId = function (id) {
    if (memo[id] !== undefined) return memo[id];
    if (!has(id) || id === 'minutes' || id === 'age' || !offered(id, c)) return (memo[id] = false);
    if (!base.length) return (memo[id] = true);
    var n = base.filter(function (r) { return isNum(raw(r, id)); }).length;
    return (memo[id] = n >= 0.3 * base.length);
  };
  if (ROLE_CODES.indexOf(c) >= 0 && SPEC && SPEC.group) {
    var g = SPEC.group(role(c).id);
    var v = g && g.view && QK.within && QK.within.view ? QK.within.view(g, okId) : null;
    if (v) return { why: v.why, x: v.x, y: v.y, color: v.color, sets: v.sets.filter(function (s) { return s.ids.length; }).map(function (s) { return { key: s.key, label: s.label, ids: s.ids }; }) };
  }
  var head = [];
  (ROLE_LETTER_GROUPS[c] || ROLE_LETTER_GROUPS.O).forEach(function (gid) { (SPEC && SPEC.headline ? SPEC.headline(gid) : []).forEach(function (k) { if (head.indexOf(k) < 0 && k !== 'gar90' && okId(k)) head.push(k); }); });
  var val = ['gar90', 'gar', 'rating'].filter(okId);
  var sets = [{ key: 'head', label: 'Headline', ids: head.slice(0, 12) }, { key: 'aggregate', label: 'Value', ids: val }].filter(function (s) { return s.ids.length; });
  return { why: '', x: head[0], y: head[1], color: val[0] || null, sets: sets };
}
/* one metric per family on the quick reads */
var FAMILY = { gar: 'gar90', xg_90: 'npxg_90', goals_90: 'npg_90', assists_90: 'xa_90', saves_90: 'save_pct' };
function fam(id) { return FAMILY[id] || id; }
function pickDistinct(out, ids, n) { var k = 0; ids.forEach(function (id) { if (k >= n || out.indexOf(id) >= 0 || out.some(function (x) { return fam(x) === fam(id); })) return; out.push(id); k++; }); }
function keyMetrics(v) {
  var out = [];
  if (v.sets.length >= 3 && v.sets[0].key === 'excellence') { pickDistinct(out, v.sets[0].ids, 3); pickDistinct(out, v.sets[1].ids, 4); pickDistinct(out, v.sets[2].ids, 2); }
  else v.sets.forEach(function (s) { pickDistinct(out, s.ids, s.key === 'aggregate' ? 2 : 7); });
  return out.slice(0, 9);
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQuery(q) {
  q = q || {};
  SC.view = ['board', 'chart', 'leaders'].indexOf(q.view) >= 0 ? q.view : 'board';
  SC.w = WIN_ORDER.indexOf(q.w) >= 0 ? q.w : 'season';
  SC.c = q.c || 'all';
  if (q.within === 'pos' && ROLE_CODES.indexOf(q.pos) >= 0) { SC.within = 'pos'; SC.pg = q.pos; }
  else { SC.within = 'broad'; SC.bg = broad(q.grp || q.pos).length && BROAD.some(function (b) { return b[0] === (q.grp || q.pos); }) ? (q.grp || q.pos) : 'O'; }
  var mn = parseInt(q.min, 10); SC.min = isNaN(mn) ? null : mn;
  SC.team = q.team || ''; SC.age = AGE_TEST[q.age] ? q.age : '';
  SC.q = q.q || ''; SC.cols = q.cols || ''; SC.add = q.add ? String(q.add).split(',').filter(Boolean) : [];
  SC.sort = q.sort ? { key: q.sort, dir: q.dir === 'asc' ? 'asc' : q.dir === 'desc' ? 'desc' : '' } : null;
  SC.all = q.all === '1'; SC.p = q.p || ''; SC.cmp = q.cmp ? String(q.cmp).split(',').filter(Boolean).slice(0, 4) : [];
  SC.x = q.x || ''; SC.y = q.y || ''; SC.color = q.color || ''; SC.size = q.size || ''; SC.preset = q.preset || '';
}
function hashNow() {
  var q = {};
  if (SC.view !== 'board') q.view = SC.view;
  if (SC.w !== 'season') q.w = SC.w;
  if (SC.c !== 'all') q.c = SC.c;
  if (SC.within === 'pos') { q.within = 'pos'; q.pos = SC.pg; } else if (SC.bg !== 'O') q.grp = SC.bg;
  if (isNum(SC.min)) q.min = SC.min;
  ['team', 'age', 'q', 'cols'].forEach(function (k) { if (SC[k]) q[k] = SC[k]; });
  if (SC.add.length) q.add = SC.add.join(',');
  if (SC.sort && SC.sort.key && !(SC.sortDef && SC.sortDef.key === SC.sort.key && SC.sortDef.dir === SC.sort.dir)) { q.sort = SC.sort.key; if (SC.sort.dir) q.dir = SC.sort.dir; }
  if (SC.all) q.all = '1';
  if (SC.p) q.p = SC.p;
  if (SC.cmp.length) q.cmp = SC.cmp.join(',');
  if (SC.view === 'chart') ['x', 'y', 'color', 'size', 'preset'].forEach(function (k) { if (SC[k] !== '' && SC[k] !== null && SC[k] !== undefined) q[k] = SC[k]; });
  return '#/scout' + FB.qs(q);
}
function writeQuery() { FB.setHashQuiet(hashNow()); }

/* ── names, links, marks ─────────────────────────────────────────────────── */
function personQ() { return single() ? { c: SC.c } : SC.c === 'club' ? { scope: 'club' } : SC.c === 'intl' ? { scope: 'intl' } : null; }
function href(r) { return FB.href.player(rid(r), personQ()); }
function teamOf(r) { var tid = rtid(r), nm = (tid && FB.clubName(tid)) || rteam(r); return { abbr: nm ? FB.clubCode(nm) : '', colour: tid ? FB.clubColour(tid) : null, alt: tid ? FB.clubAlt(tid) : null, name: nm, logo: tid ? FB.crestUrl(tid) : null }; }
function posLabel(r) { return rrole(r) || rpos(r) || '—'; }
function subOf(r) { var t = teamOf(r); return [posLabel(r), t.abbr, isNum(rage(r)) ? 'age ' + Math.floor(rage(r)) : ''].filter(Boolean).join(' · '); }
/* the group a row belongs to in the current mode */
function codeOf(r) {
  if (SC.within === 'pos') { var c = ROLE_CODES.filter(function (k) { return role(k).codes.indexOf(rrole(r)) >= 0; })[0]; if (c) return c; }
  var p = rpos(r);
  return p === 'G' ? 'G' : SC.within === 'pos' ? 'O' : (SC.bg === 'O' ? 'O' : (p || 'O'));
}

/* ── render ──────────────────────────────────────────────────────────────── */
FB.route('scout', function (el, p) {
  ROOT = el;
  readQuery(p.query || {});
  el.innerHTML = FB.pageHead('Scouting Room', 'Every player, every metric', 'Judged against the same position: sort the board, chart any two numbers, scan the leaders, open a profile, pin up to four to compare. One row per player over every competition, club football, national-team football or one competition, this season or a window.') +
    '<div class="sc qk-room"><section class="qk-card sc-ctl"><div class="qk-card-body" id="sc-ctl">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="sc-top" id="sc-top" aria-label="Top of the group"></section>' +
    '<div class="qk-tabs sc-tabs" role="tablist" aria-label="Scouting Room views">' +
    [['board', 'Board'], ['chart', 'Chart'], ['leaders', 'Leaders']].map(function (t) { return '<button type="button" class="qk-tab" role="tab" id="sc-tab-' + t[0] + '" data-view="' + t[0] + '" aria-selected="' + (SC.view === t[0]) + '" tabindex="' + (SC.view === t[0] ? 0 : -1) + '">' + t[1] + '</button>'; }).join('') +
    '</div><div id="sc-view" class="sc-view" role="tabpanel" aria-labelledby="sc-tab-' + SC.view + '"></div></div>';
  FB.onLeave(function () { if (QK.drawer && QK.drawer.isOpen()) QK.drawer.close(true); if (TRAY) { TRAY.destroy(); TRAY = null; } ROOT = null; BOARD = null; });
  el.addEventListener('click', pickClick);
  return load().then(function () {
    if (!FB.alive(el)) return;
    if (!V) { FB.set('sc-view', FB.empty('Not built yet', 'The player views (data/lab/) are written by the next build.')); FB.set('sc-ctl', ''); return; }
    controls(); tabs(); tray(); refresh();
    if (SC.p) openProfile(SC.p);
  });
});
function load() {
  return Promise.all([FB.labIndex(), FB.labOurs ? FB.labOurs.load() : Promise.resolve(null), FB.clubsIndex()]).then(function (arr) {
    IX = arr[0]; SPEC = arr[1];
    if (!IX || !IX.scopes) { V = null; return; }
    var haveW = IX.scopes[SC.w] ? SC.w : (IX.scopes.season ? 'season' : Object.keys(IX.scopes)[0]);
    SC.w = haveW;
    var have = IX.scopes[SC.w] || {};
    if (!have[SC.c]) SC.c = have.all ? 'all' : Object.keys(have)[0];
    var key = SC.w + '/' + SC.c;
    if (V && VK === key) return;
    return FB.labView(SC.w, SC.c).then(function (v) {
      if (!v) { V = null; return; }
      var meta = {};
      (IX.metrics || []).forEach(function (m) { meta[m.key] = m; });
      Object.keys(OURS).forEach(function (k) { if (!meta[k]) meta[k] = { key: k, label: OURS[k][0], fmt: OURS[k][1], group: 'Our models', scope: 'all' }; });
      V = { idx: v.idx, rows: v.rows, floor: v.floor, meta: meta, metrics: Object.keys(meta).filter(function (k) { return v.idx[k] !== undefined; }) };
      VK = key; clearPct();
    });
  });
}
function reload() {
  return load().then(function () { if (!ROOT || !FB.alive(ROOT)) return; if (!V) return; SC.min = null; controls(); tray(); refresh(); });
}

/* a click on a player link anywhere in the room opens the drawer (a modified click follows the link) */
function pickClick(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
  var a = ev.target.closest ? ev.target.closest('a[href]') : null;
  if (!a || (a.closest && a.closest('.qk-pf-acts, .qk-pf-h, .qk-tray'))) return;
  var m = /^#\/player\/([^/?#]+)/.exec(a.getAttribute('href') || '');
  if (!m || !findRow(decodeURIComponent(m[1]))) return;
  ev.preventDefault();
  openProfile(decodeURIComponent(m[1]));
}

/* ── the control bar ─────────────────────────────────────────────────────── */
function controls() {
  var host = document.getElementById('sc-ctl');
  if (!host) return;
  var within = QK.within.html({ within: SC.within, pos: SC.pg }, { id: 'sc-wn', groups: ROLES.map(function (r) { return [r[0], role(r[0]).name]; }),
    note: SC.within === 'pos' ? 'formation role (the one started in most) · the metrics spec’s minimum ' + FB.int(role(SC.pg).min) + ' minutes' : FB.seg('sc-grp', BROAD.map(function (b) { return [b[0], b[1]]; }), SC.bg, 'Group') });
  var wins = WIN_ORDER.filter(function (k) { return (IX.scopes || {})[k] && (IX.windows || []).some(function (w) { return w.key === k; }); }).map(function (k) {
    var w = (IX.windows || []).filter(function (x) { return x.key === k; })[0]; return [k, k === 'season' ? 'This season' : w.label];
  });
  var inG = V.rows.filter(function (r) { return inGroup(r); });
  var tset = {};
  inG.forEach(function (r) { var t = rtid(r); if (t !== null && t !== undefined && !tset[t]) tset[t] = (FB.clubName(t) || rteam(r)); });
  var teams = Object.keys(tset).sort(function (a, b) { return String(tset[a]).localeCompare(String(tset[b])); });
  var mx = Math.max.apply(null, inG.map(rmin).concat([900]));
  var opt = function (v, t, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>'; };
  var items = [
    { label: 'Season', html: FB.select('sc-w', wins, SC.w, 'Season or window') },
    { label: 'Competitions', html: FB.select('sc-c', FB.labScopeOptions(IX, SC.w), SC.c, 'Which competitions count', 'fb-pl-wide') },
    { label: 'Min minutes', html: '<span class="sc-min"><input type="range" id="sc-min" min="90" max="' + (Math.ceil(mx / 90) * 90) + '" step="45" value="' + minNow() + '" aria-label="Minimum minutes"><b class="qk-sbar-v" id="sc-min-v">' + minNow() + '\'</b></span>', cls: 'sc-minf' },
    { label: SC.c === 'intl' ? 'National team' : 'Club', html: '<select class="qk-select" id="sc-team">' + opt('', SC.c === 'intl' ? 'Every team' : 'Every club', SC.team) + teams.map(function (t) { return opt(t, tset[t], SC.team); }).join('') + '</select>' },
    V.rows.some(function (r) { return isNum(rage(r)); }) ? { label: 'Age', html: '<select class="qk-select" id="sc-age">' + AGES.map(function (a) { return opt(a[0], a[1], SC.age); }).join('') + '</select>' } : null,
    { label: 'Search', html: '<input class="qk-input" id="sc-q" type="search" placeholder="Player or club…" value="' + esc(SC.q) + '" autocomplete="off">', cls: 'grow' }
  ];
  var v = view();
  host.innerHTML = within + (v.why ? QK.within.viewWhy({ why: v.why }) : '') +
    '<p class="sc-floor">' + esc(cap(noun())) + ' with ' + FB.int(minNow()) + '+ minutes · ' + esc(FB.labScopeName(SC.c, IX)) + ' · ' + esc(FB.labWindowText((IX.windows || []).filter(function (w) { return w.key === SC.w; })[0])) +
    (isNum(SC.min) && SC.min !== defMin() ? ' (the default is ' + FB.int(defMin()) + ')' : '') + '</p>' + QK.scoutBar(items);
  QK.within.wire(host, { within: SC.within, pos: SC.pg }, function (w) {
    if (w.within === 'pos' && SC.within !== 'pos') w.pos = role(SC.pg).letter === SC.bg ? SC.pg : LETTER_ROLE[SC.bg];
    if (w.within !== 'pos' && SC.within === 'pos') SC.bg = role(SC.pg).letter;
    SC.within = w.within; if (w.within === 'pos') SC.pg = w.pos;
    regroup();
  }, { id: 'sc-wn' });
  FB.wireSeg(host, 'sc-grp', function (x) { SC.bg = x; regroup(); });
  var $ = function (id) { return document.getElementById(id); };
  $('sc-w').onchange = function (e) { SC.w = e.target.value; SC.p = ''; reload(); };
  $('sc-c').onchange = function (e) { SC.c = e.target.value; SC.p = ''; SC.team = ''; reload(); };
  $('sc-min').oninput = function (e) { $('sc-min-v').textContent = e.target.value + '\''; };
  $('sc-min').onchange = function (e) { SC.min = parseInt(e.target.value, 10); if (SC.min === defMin()) SC.min = null; clearPct(); controls(); refresh(); };
  $('sc-team').onchange = function (e) { SC.team = e.target.value; refresh(); };
  if ($('sc-age')) $('sc-age').onchange = function (e) { SC.age = e.target.value; refresh(); };
  var t = null;
  $('sc-q').oninput = function (e) { SC.q = e.target.value; clearTimeout(t); t = setTimeout(refresh, 260); };
}
function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
/* a new group: the minimum back to its floor, the column set, the sort and the chart's axes (each group has its own view) */
function regroup() {
  SC.min = null; SC.cols = ''; SC.sort = null; SC.x = ''; SC.y = ''; SC.color = ''; SC.preset = '';
  if (SC.add.some(function (id) { return !offered(id); })) SC.add = [];
  clearPct(); controls(); refresh();
}

/* ── views ───────────────────────────────────────────────────────────────── */
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
    SC.view = v;
    QK.$$('[role="tab"]', bar).forEach(function (b) { var on = b.getAttribute('data-view') === v; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
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
  var host = document.getElementById('sc-view');
  if (!host) return;
  BOARD = null;
  if (SC.view === 'chart') return chartView(host);
  if (SC.view === 'leaders') return leadersView(host);
  return boardView(host);
}

/* "Top of the position": the leader on five of the view's metrics among the players on screen */
function topStrip() {
  var host = document.getElementById('sc-top');
  if (!host) return;
  var v = view(), rows = shown(), ids = [];
  if (v.sets.length >= 3 && v.sets[0].key === 'excellence') { pickDistinct(ids, v.sets[0].ids, 2); pickDistinct(ids, v.sets[1].ids, 2); pickDistinct(ids, v.sets[2].ids, 1); }
  else v.sets.forEach(function (s) { pickDistinct(ids, s.ids, s.key === 'aggregate' ? 1 : 4); });
  var items = ids.slice(0, 5).map(function (id) {
    var m = mmeta(id), list = rows.filter(function (r) { return isNum(raw(r, id)); }).sort(function (a, b) { return m.lower ? raw(a, id) - raw(b, id) : raw(b, id) - raw(a, id); });
    if (!list.length) return null;
    var r = list[0], nx = list[1];
    return { sport: 'football', kicker: m.label, name: rname(r), value: m.fmt(raw(r, id)), title: teamOf(r).abbr + ' · ' + posLabel(r), next: nx ? { name: rname(nx), value: m.fmt(raw(nx, id)) } : null,
      expl: shortTip(m.tip), href: href(r) };
  }).filter(Boolean);
  host.innerHTML = items.length ? QK.sectionHead({ kicker: 'Top of the ' + noun(), title: SC.within === 'pos' ? 'The best ' + noun() + ', on what matters there' : 'The best ' + noun() + ' right now',
    sub: 'The leader on five of the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics among the ' + rows.length + ' on screen. Tap a name for the profile.' }) + QK.hotRow(items) : '';
}
function shortTip(t) { t = String(t || '').replace(/ Our model: .*$/, ''); return t.length > 110 ? t.slice(0, 107).replace(/\s+\S*$/, '') + '…' : t; }

/* one-line board heads (round 10) for payload keys the metrics spec does not carry; the spec's own come through
   QK.spec (`short`). A value is the head, or [head, unit]. */
var BOARD_ABBR = {
  "gar": "GAR", "v_par": "PAR", "v_proj": "Proj GAR/90", "v_v2": "Valuation", "v_mv": ["Market value", "EUR"],
  "carry_dist_90": ["Carry dist", "m/90"], "dispossessed_90": ["Dispossessed", "/90"], "poss_lost_90": ["Poss lost",
  "/90"], "tackle_pct": "Tackle %", "km_90": ["Distance", "km/90"], "top_speed": ["Top speed", "km/h"],
  "placement": "Placement", "xa_per_kp": "xA/key pass", "def_actions_90": ["Def actions", "/90"], "duels_90": ["Duels",
  "/90"], "aerials_90": ["Aerials", "/90"]
};
/* Board: column sets as chips, percentile cells, paging, CSV */
function boardView(host) {
  var v = view(), all = shown();
  var rows = SC.q.trim() ? all.filter(matches) : all;
  var P = peers();
  var sets = [{ key: 'view', label: SC.within === 'pos' ? 'Position view' : 'Headline', groups: v.sets.map(function (s) { return { label: s.label, ids: s.ids }; }) }];
  var oursIds = V.metrics.filter(function (k) { return FB.labOurs && FB.labOurs.oursOf(k); });
  if (oursIds.length) sets.push({ key: 'ours', label: 'Our models', groups: [{ label: 'Our models', ids: oursIds }] });
  /* the Value set: what was Value › Players (GAR here; PAR, projection, valuation and fees from value/players.json) */
  sets.push({ key: 'value', label: 'Value', groups: [{ label: 'This view', ids: ['gar90', 'gar'].filter(function (k) { return I(k) !== undefined; }) },
    { label: 'Our value model, last 12 months', ids: VALUE_COLS.slice(0, 3).map(function (x) { return x[0]; }) }, { label: 'Fees and market', ids: VALUE_COLS.slice(3).map(function (x) { return x[0]; }) }] });
  if (SC.cols === 'value' && !VAL) { loadValue().then(function () { if (ROOT && ROOT.isConnected && SC.view === 'board') drawView(); }); }
  var gnames = [];
  (IX.metrics || []).forEach(function (m) { if (has(m.key) && offered(m.key) && gnames.indexOf(m.group || 'Other') < 0) gnames.push(m.group || 'Other'); });
  gnames.forEach(function (gn) { sets.push({ key: gn, label: gn, groups: [{ label: gn, ids: (IX.metrics || []).filter(function (m) { return (m.group || 'Other') === gn && has(m.key) && offered(m.key); }).map(function (m) { return m.key; }) }] }); });
  var setKey = QK.board.pick(sets, SC.cols, 'view');
  var defSort = v.color || (v.sets[0] || { ids: [] }).ids[0];
  var sort = SC.sort && SC.sort.key && (SC.sort.key === 'name' || SC.sort.key === 'min' || SC.sort.key === 'age' || has(SC.sort.key)) ? SC.sort : null;
  if (sort && !sort.dir) sort = { key: sort.key, dir: sort.key !== 'name' && sort.key !== 'min' && sort.key !== 'age' && mmeta(sort.key).lower ? 'asc' : 'desc' };
  SC.sortDef = defSort ? { key: defSort, dir: mmeta(defSort).lower ? 'asc' : 'desc' } : null;
  if (!sort && SC.sortDef) sort = SC.sortDef;
  var groups = {};
  V.metrics.filter(function (k) { return offered(k); }).forEach(function (k) { var m = mmeta(k), g = m.ours ? 'Our models' : m.group; (groups[g] = groups[g] || []).push(k); });
  var addable = Object.keys(groups).sort(function (a, b) { return a === 'Our models' ? -1 : b === 'Our models' ? 1 : 0; }).map(function (g) {
    return '<optgroup label="' + esc(g) + '">' + groups[g].map(function (k) { return '<option value="' + esc(k) + '">' + esc(mmeta(k).label) + '</option>'; }).join('') + '</optgroup>';
  }).join('');
  host.innerHTML = '<section class="qk-card sc-board"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">The board</div><div class="qk-card-sub">' +
    esc(cap(noun())) + ' · ' + esc(FB.labScopeName(SC.c, IX)) + ' · the bar under each number is its percentile against the ' + P.length + ' ' + esc(noun()) + ' with ' + FB.int(minNow()) + '+ minutes: the top 10% in red, the bottom 10% in blue. Tap a name for the profile; tick the box beside it to pin it to the compare tray.</div></div></div>' +
    '<div class="qk-card-body"><div id="sc-board"></div></div></section>';
  BOARD = QK.board(document.getElementById('sc-board'), {
    id: 'sc-bd', summary: defSort, abbr: BOARD_ABBR, sets: sets, set: setKey, added: SC.add.filter(function (id) { return has(id); }), sort: sort, all: SC.all, page: 50, noun: noun(),
    nameLabel: 'Player', subLabel: 'Role · club · age',
    meta: function (id) { return mmeta(id); },
    addable: addable,
    lead: [{ key: 'min', label: 'Min', tip: 'Minutes in the view', fmt: function (row) { return FB.int(rmin(row._r)); }, val: function (row) { return rmin(row._r); } },
      { key: 'age', label: 'Age', fmt: function (row) { return isNum(rage(row._r)) ? String(Math.floor(rage(row._r))) : '—'; }, val: function (row) { return rage(row._r); } }],
    rows: rows.map(function (r) { return { id: rid(r), name: rname(r), sub: subOf(r), mark: teamOf(r), href: href(r), _r: r }; }),
    val: function (row, id) { return raw(row._r, id); },
    peers: P.map(function (r) { return { id: rid(r), _r: r }; }),
    ranked: function (row, id) { return offered(id); },
    hl: function (row) { return SC.cmp.indexOf(row.id) >= 0; },
    pin: { has: function (id) { return !!TRAY && TRAY.has(id); }, toggle: function (row) { pin(row._r); }, label: 'Pin to the compare tray' },
    onPick: function (row) { openProfile(row.id); },
    onState: function (st) {
      var was = SC.cols;
      SC.cols = st.set === 'view' ? '' : st.set; SC.add = st.added; SC.sort = st.sort; SC.all = st.all; writeQuery();
      if (st.set === 'value' && was !== 'value' && !VAL) loadValue().then(function () { if (ROOT && ROOT.isConnected && SC.view === 'board') drawView(); });
    },
    csv: 'footballer-' + SC.w + '-' + SC.c + '-' + code().toLowerCase() + '-' + String(setKey).toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.csv',
    empty: SC.q.trim() ? 'No ' + noun() + ' match “' + SC.q.trim() + '” with these filters.' : 'No ' + noun() + ' pass these filters: lower the minimum or clear a filter.',
    note: 'Percentiles are against every ' + esc(one()) + ' past the minimum in the view, whatever the club or age filters show; a ↓ marks a metric where lower is better (its bar is flipped). Rates are per 90 minutes; GAR/90 and GAR are our player value model. Every metric in the file is under “Columns” or “Add a metric”.'
  });
}

/* Chart: the Lab inside the room */
function chartView(host) {
  if (!FB.lab || !FB.lab.mount) { host.innerHTML = FB.empty('The chart did not load', 'Reload the page.'); return; }
  host.innerHTML = '<div id="sc-chart"></div>';
  var letter = SC.within === 'pos' ? role(SC.pg).letter : SC.bg;
  FB.lab.mount(document.getElementById('sc-chart'), {
    comp: SC.c, pos: letter,
    query: { w: SC.w, within: SC.within === 'pos' ? 'pos' : null, pos: SC.within === 'pos' ? SC.pg : null, x: SC.x, y: SC.y, color: SC.color || undefined, size: SC.size || undefined,
      preset: SC.preset || undefined, min: isNum(SC.min) ? SC.min : undefined, q: SC.q },
    onPick: function (pid) { openProfile(pid); },
    onState: function (st) {
      var chg = st.w !== SC.w || st.c !== SC.c;
      SC.w = st.w; SC.c = st.c;
      if (st.within === 'pos') { SC.within = 'pos'; SC.pg = st.role; } else { SC.within = 'broad'; SC.bg = st.pos; }
      SC.x = st.x; SC.y = st.y; SC.color = st.color === 'none' ? 'none' : st.color; SC.size = st.size; SC.preset = st.preset; SC.q = st.q;
      SC.min = st.min === '' ? null : st.min;
      writeQuery();
      if (chg) load().then(function () { controls(); topStrip(); });
      else { controls(); topStrip(); }
    }
  });
}

/* Leaders: small multiples on the view's key metrics, each with a dot strip of the group */
function leadersView(host) {
  var v = view(), rows = shown(), P = peers();
  var ids = keyMetrics(v);
  var hl = function (r) { return matches(r) || rid(r) === SC.p; };
  host.innerHTML = '<div class="sc-lead-head">' + QK.sectionHead({ kicker: 'Leaders · ' + cap(noun()), title: 'Quick reads, metric by metric', sub: 'The top five and the bottom three of the ' + rows.length + ' ' + noun() + ' on screen on the ' + (SC.within === 'pos' ? 'position' : 'group') + '’s key metrics. Bars are percentiles against the ' + P.length + ' with ' + FB.int(minNow()) + '+ minutes; the strip under each card is everyone on screen, with the median dashed' + (SC.q.trim() ? ' and your search ringed' : '') + '.' }) + '</div>' +
    '<div class="qk-lc-grid">' + ids.map(function (id, i) {
      var m = mmeta(id);
      var list = rows.filter(function (r) { return isNum(raw(r, id)); }).sort(function (a, b) { return m.lower ? raw(a, id) - raw(b, id) : raw(b, id) - raw(a, id); });
      if (!list.length) return '';
      var item = function (r, rk) { var p = pctOf(r, id); return { id: rid(r), rank: rk, name: rname(r), sub: subOf(r), href: href(r), text: m.fmt(raw(r, id)), w: p, pctl: p, mark: teamOf(r) }; };
      var top = list.slice(0, 5).map(function (r, j) { return item(r, j + 1); });
      var bottom = !TOTALS[id] && list.length > 10 ? list.slice(-3).map(function (r, j) { return item(r, list.length - 2 + j); }) : [];
      return QK.leaderCard({ title: m.label, tip: m.tip, ours: m.ours, lower: m.lower, count: list.length + ' ' + noun(), top: top, bottom: bottom, bottomLabel: 'At the bottom', stripId: 'sc-strip-' + i });
    }).join('') + '</div>';
  ids.forEach(function (id, i) {
    var el = document.getElementById('sc-strip-' + i);
    if (!el) return;
    var m = mmeta(id);
    var vals = rows.filter(function (r) { return isNum(raw(r, id)); }).map(function (r) { return { v: raw(r, id), name: rname(r) + ' · ' + teamOf(r).abbr, id: rid(r), hl: hl(r) }; });
    QKC.strip(el, { values: vals, xName: m.label, fmt: m.fmt, lower: m.lower, label: 'Every ' + one() + ' on ' + m.label, onClick: function (d) { openProfile(d.id); } });
  });
}

/* ── the profile drawer ─────────────────────────────────────────────────── */
function openProfile(id) {
  var r = findRow(id);
  if (!r) return;
  SC.p = rid(r); writeQuery();
  var c = inGroup(r) ? code() : codeOf(r);
  var v = view(c), P = peers(c);
  var row = function (id2) { var m = mmeta(id2), x = raw(r, id2); if (!isNum(x)) return null; return { label: m.label, pctl: pctOf(r, id2, c), value: m.fmt(x), tip: m.tip }; };
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(row).filter(Boolean) }; });
  var t = teamOf(r);
  var statIds = [v.color, v.y, v.x].filter(function (x, i, a) { return x && a.indexOf(x) === i; });
  var stats = statIds.map(function (id2) { var m = mmeta(id2), x = raw(r, id2); return isNum(x) ? { label: m.label, value: m.fmt(x), pctl: pctOf(r, id2, c), tip: m.tip } : null; }).filter(Boolean);
  stats.push({ label: 'Minutes', value: FB.int(rmin(r)) });
  var simKeys = [];
  if (v.sets.length >= 3 && v.sets[0].key === 'excellence') [4, 4, 2].forEach(function (n, i) { v.sets[i].ids.filter(function (x) { return simKeys.indexOf(x) < 0; }).slice(0, n).forEach(function (x) { simKeys.push(x); }); });
  else v.sets.forEach(function (s) { s.ids.slice(0, 6).forEach(function (x) { if (simKeys.indexOf(x) < 0) simKeys.push(x); }); });
  var pool = P.indexOf(r) >= 0 ? P : P.concat([r]);
  var near = QK.within.similar(pool, r, simKeys, function (rr, k) { return raw(rr, k); }, 5);
  var base = FB.href.player(rid(r), personQ());
  var prog = FB.href.player(rid(r), FB.merge(personQ() || {}, { view: 'progression' }));
  var cmpH = near.length ? '#/compare/players/' + FB.enc(rid(r)) + '/' + FB.enc(rid(near[0].row)) : '#/compare/players/' + FB.enc(rid(r));
  var inPeers = P.indexOf(r) >= 0;
  var mix = r[I('mix')];
  var html = QK.profile({
    kicker: posLabel(r) + ' · ' + (t.name || ''),
    name: rname(r), href: base,
    sub: [isNum(rage(r)) ? 'Age ' + Math.floor(rage(r)) : '', FB.int(rmin(r)) + ' minutes', mix ? String(mix) : ''].filter(Boolean).join(' · '),
    team: t, stats: stats,
    peer: noun(c) + ' with ' + FB.int(floorFor(c)) + '+ minutes' + (inPeers ? '' : ' (this player is under the minimum: read with care)'),
    groups: groups,
    similar: { label: 'Most like ' + FB.surname(rname(r)) + ' · ' + noun(c), items: near.map(function (o) { return { name: rname(o.row), href: href(o.row), id: rid(o.row), sub: subOf(o.row) }; }) },
    actions: '<button type="button" class="qk-btn sm' + (TRAY && TRAY.has(rid(r)) ? ' solid' : ' primary') + '" id="sc-pf-pin">' + (TRAY && TRAY.has(rid(r)) ? '✓ In the tray' : '+ Pin to compare') + '</button>',
    links: [{ label: 'Full player page', href: base }, { label: 'Progression', href: prog }, { label: near.length ? 'Compare with ' + FB.surname(rname(near[0].row)) : 'Compare', href: cmpH }],
    note: 'Percentiles against the ' + P.length + ' ' + esc(noun(c)) + ' with ' + FB.int(floorFor(c)) + '+ minutes in ' + esc(FB.labScopeName(SC.c, IX).toLowerCase()) + '. “Most like” is the nearest five on the ' + (SC.within === 'pos' ? 'position view’s' : 'group’s') + ' metrics.'
  });
  var inner = QK.drawer.open({ html: html, label: rname(r) + ': profile', onClose: function () { SC.p = ''; writeQuery(); } });
  var pb = inner.querySelector('#sc-pf-pin');
  if (pb) pb.addEventListener('click', function () { pin(r); openProfile(rid(r)); });
  QK.$$('[data-pick]', inner).forEach(function (a) { a.addEventListener('click', function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
    ev.preventDefault(); openProfile(a.getAttribute('data-pick'));
  }); });
}

/* ── the compare tray ───────────────────────────────────────────────────── */
function pin(r) {
  if (!TRAY) return;
  var first = SC.cmp.length ? findRow(SC.cmp[0]) : null;
  if (first && (rpos(first) === 'G') !== (rpos(r) === 'G') && !TRAY.has(rid(r))) TRAY.clear();     // keepers and outfield players share no scale
  TRAY.toggle(rid(r));
  if (BOARD) QK.$$('[data-pin="' + rid(r) + '"]', ROOT).forEach(function (b) { var on = TRAY.has(rid(r)); b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.textContent = on ? '✓' : '+'; });
}
function tray() {
  if (TRAY) TRAY.destroy();
  TRAY = QK.tray({
    max: 4, ids: SC.cmp.filter(function (id) { return findRow(id); }), label: 'Compare tray',
    item: function (id) { var r = findRow(id); return r ? { name: rname(r), short: FB.surname(rname(r)), sub: posLabel(r) + ' · ' + teamOf(r).abbr, colour: teamOf(r).colour } : { name: id }; },
    onChange: function (ids) { SC.cmp = ids; writeQuery(); },
    href: function (ids) { return '#/compare/players/' + FB.enc(ids[0]) + '/' + FB.enc(ids[1]) + (ids[2] ? '?p3=' + FB.enc(ids[2]) : ''); },
    hrefLabel: 'Full compare',
    body: function (ids) { return trayBody(ids); }
  });
}
function trayBody(ids) {
  var rs = ids.map(findRow).filter(Boolean);
  if (rs.length < 2) return '';
  var codes = rs.map(function (r) { return inGroup(r) ? code() : codeOf(r); });
  var v = view(codes[0]);
  var groups = v.sets.map(function (s) { return { label: s.label, rows: s.ids.map(function (id) {
    var m = mmeta(id);
    return { label: m.label, tip: m.tip, ours: m.ours, cells: rs.map(function (r, i) { var x = raw(r, id); return { text: isNum(x) ? m.fmt(x) : '—', pctl: isNum(x) ? pctOf(r, id, codes[i]) : null }; }) };
  }) }; });
  return QK.trayCompare({ entities: rs.map(function (r) { var t = teamOf(r); return { name: rname(r), short: FB.surname(rname(r)), sub: posLabel(r) + ' · ' + t.abbr + ' · ' + FB.int(rmin(r)) + '\'', colour: t.colour, href: href(r) }; }),
    groups: groups, note: 'Percentiles: each player against their own ' + (SC.within === 'pos' ? 'position' : 'group') + '’s peers past the minimum (' + esc(FB.labScopeName(SC.c, IX).toLowerCase()) + '). The volt underline marks the best of the ' + rs.length + ' on each row.' });
}

})(window.FB);
