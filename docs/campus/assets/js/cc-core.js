/* The Quant Campus — core: data loading, router, shell, level switch, shared helpers (window.CC).
 *
 * Routes (level first; oddsmarkets/college/PAYLOADS.md "Front end"):
 *   #/                      the level in season (remembered choice first)        #/<L>            overview
 *   #/<L>/games             games by week (cfb) or day (basketball)              #/<L>/game/<gid> game centre
 *   #/<L>/standings?tab=    conferences | polls | playoff | bowls (cfb) | bracket | conftourneys (basketball)
 *   #/<L>/teams  #/<L>/team/<tid>  #/<L>/players  #/<L>/player/<pid>
 *   #/<L>/value?tab=value|position|transfers   #/<L>/fantasy   #/<L>/lab   #/<L>/model?tab=method|calibration|glossary|terms
 *   ?season=S (or a trailing /S) for a past season;  #/disclaimer
 * Data: data/index.json, data/<L>/..., data/<L>/<S>/... (PAYLOADS.md). In local preview only, ?data=<path> points
 * the page at another data folder (the development fixture).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (root) {
'use strict';

var CC = root.CC = {};
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt;
CC.esc = esc; CC.isNum = isNum;
CC.LEVELS = ['cfb', 'mbb', 'wbb'];
CC.LNAME = { cfb: 'College Football', mbb: "Men's College Basketball", wbb: "Women's College Basketball" };
CC.LSHORT = { cfb: 'CFB', mbb: 'MBB', wbb: 'WBB' };
CC.fb = function (L) { return L === 'cfb'; };

/* ── data ────────────────────────────────────────────────────────────── */
CC.DATA = 'data/';
(function () {
  var m = /[?&]data=([^&#]+)/.exec(root.location.search || '');
  if (m && QK.localBase()) CC.DATA = decodeURIComponent(m[1]).replace(/\/?$/, '/');
})();
var CACHE = {};
/* Packed lists (oddsmarkets/college/packing.py): {$cols: [key], $rows: [[v]]} is a list of records, and with
 * $keys: [id] a map id -> record; a dotted column ("model.p_home") is one level of nesting; a null value is an absent
 * key. unpack(payload) expands every packed list in place, so the pages read packed and plain payloads alike. */
function unpackRows(o) {
  var cols = o.$cols, keys = Array.isArray(o.$keys) ? o.$keys : null, out = keys ? {} : [];
  var split = cols.map(function (k) { var i = String(k).indexOf('.'); return i > 0 ? [k.slice(0, i), k.slice(i + 1)] : null; });
  o.$rows.forEach(function (row, j) {
    var r = {};
    for (var i = 0; i < cols.length; i++) {
      var v = row[i];
      if (v === null || v === undefined) continue;
      if (v && typeof v === 'object') v = CC.unpack(v);
      var sp = split[i];
      if (sp) { if (!r[sp[0]] || typeof r[sp[0]] !== 'object') r[sp[0]] = {}; r[sp[0]][sp[1]] = v; } else r[cols[i]] = v;
    }
    if (keys) out[keys[j]] = r; else out.push(r);
  });
  return out;
}
CC.unpack = function (o) {
  if (!o || typeof o !== 'object') return o;
  if (Array.isArray(o)) {
    for (var i = 0; i < o.length; i++) if (o[i] && typeof o[i] === 'object') o[i] = CC.unpack(o[i]);
    return o;
  }
  if (Array.isArray(o.$cols) && Array.isArray(o.$rows)) return unpackRows(o);
  Object.keys(o).forEach(function (k) { if (o[k] && typeof o[k] === 'object') o[k] = CC.unpack(o[k]); });
  return o;
};
/* load(path) -> Promise of the payload; a missing or broken file resolves to {ok: false, reason} (never rejects). */
CC.load = function (path) {
  if (CACHE[path]) return CACHE[path];
  var p = QK.fetchJSON(CC.DATA + path, { timeout: 20000 }).then(function (j) {
    j = CC.unpack(j);
    if (j && typeof j === 'object' && !Array.isArray(j) && j.ok === undefined) j.ok = true;
    return j;
  }, function (e) { delete CACHE[path]; return { ok: false, reason: String((e && e.message) || e), missing: true }; });
  CACHE[path] = p;
  return p;
};
CC.ok = function (d) { return !!d && typeof d === 'object' && d.ok !== false; };
CC.path = function (L, S, f) { return L + '/' + S + '/' + f; };
CC.lpath = function (L, f) { return L + '/' + f; };

/* ── levels, seasons, teams ──────────────────────────────────────────── */
CC.index = null;
CC.info = function (L) { return (CC.index && CC.index.levels && CC.index.levels[L]) || {}; };
CC.cur = function (L) { var i = CC.info(L); return i.current_season || null; };
CC.seasons = function (L) { var i = CC.info(L); return (i.seasons || []).slice().sort(function (a, b) { return b - a; }); };
CC.isCur = function (L, S) { return Number(S) === Number(CC.cur(L)); };
CC.seasonLabel = function (L, S) {
  S = Number(S);
  if (!S) return '';
  return CC.fb(L) ? String(S) : (S - 1) + '–' + String(S).slice(2);
};
var TEAMS = { cfb: {}, mbb: {}, wbb: {} }, CONFS = { cfb: {}, mbb: {}, wbb: {} }, PLAYERS = { cfb: {}, mbb: {}, wbb: {} };
CC.addTeams = function (L, map) { Object.keys(map || {}).forEach(function (k) { var t = map[k]; if (t && t.name) TEAMS[L][String(k)] = Object.assign({}, TEAMS[L][String(k)] || {}, t); }); };
CC.addConfs = function (L, map) { Object.keys(map || {}).forEach(function (k) { if (map[k]) CONFS[L][String(k)] = Object.assign({}, CONFS[L][String(k)] || {}, map[k]); }); };
CC.addPlayers = function (L, map) { Object.keys(map || {}).forEach(function (k) { var p = map[k]; if (p && p.name) PLAYERS[L][String(k)] = p; }); };
CC.team = function (L, tid) { return TEAMS[L][String(tid)] || null; };
CC.tname = function (L, tid) { var t = CC.team(L, tid); return t ? t.name : (tid ? 'Team ' + tid : '—'); };
CC.tshort = function (L, tid) { var t = CC.team(L, tid); return t ? (t.short || t.name) : (tid ? String(tid) : '—'); };
CC.tabbr = function (L, tid) { var t = CC.team(L, tid); return t ? (t.abbr || fmt.initials(t.short || t.name)) : (tid ? String(tid).slice(0, 4) : '—'); };
CC.conf = function (L, cid) { return CONFS[L][String(cid)] || null; };
CC.cname = function (L, cid) { var c = CC.conf(L, cid); return c ? (c.short || c.name) : (cid ? 'Conf ' + cid : 'Independent'); };
CC.pname = function (L, pid) { var p = PLAYERS[L][String(pid)]; return p ? p.name : 'Player ' + pid; };
/* A team colour for marks and chart series on the current theme (the kit lifts dark kits to 3:1). */
CC.tcol = function (L, tid) { var t = CC.team(L, tid); return t && QK.color.parse(t.colour) ? QK.color.team(t.colour) : QK.cssVar('--c-other'); };
/* Season payload: season.json for (L, S) with its teams and conferences registered. */
CC.season = function (L, S) {
  return CC.load(CC.path(L, S, 'season.json')).then(function (d) {
    if (CC.ok(d)) { CC.addTeams(L, d.teams); CC.addConfs(L, d.conferences); }
    return d;
  });
};

/* ── hrefs ───────────────────────────────────────────────────────────── */
CC.href = function (L, sec, id, S, query) {
  var h = '#/' + L + (sec && sec !== 'overview' ? '/' + sec : '') + (id ? '/' + encodeURIComponent(id) : '');
  var q = [];
  if (S && !CC.isCur(L, S)) q.push('season=' + S);
  if (query) q.push(query);
  return h + (q.length ? '?' + q.join('&') : '');
};
CC.teamHref = function (L, tid, S) { return CC.href(L, 'team', tid, S); };
CC.playerHref = function (L, pid, S) { return CC.href(L, 'player', pid, S); };
CC.gameHref = function (L, gid, S) { return CC.href(L, 'game', gid, S); };

/* ── formatting ──────────────────────────────────────────────────────── */
CC.f = function (v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; };
CC.pct = function (p, d) { return fmt.pct(isNum(p) ? Number(p) : null, d); };
CC.signed = function (v, d) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d === undefined ? 1 : d) : '—'; };
CC.spread = function (v) { return isNum(v) ? (v === 0 ? 'PK' : (v > 0 ? '+' : '−') + Math.abs(v).toFixed(1)) : '—'; };
CC.fmtMetric = function (m, v) {
  if (!isNum(v)) return '—';
  var f = (m && m.fmt) || '1';
  if (f === 'int') return fmt.num(v, 0);
  if (f === 'pct' || f === 'prob') return CC.pct(v, 1);
  if (f === 'signed1') return CC.signed(v, 1);
  if (f === 'signed2') return CC.signed(v, 2);
  var d = parseInt(f, 10);
  return isNum(d) ? Number(v).toFixed(d) : String(v);
};
CC.record = function (w, l) { return isNum(w) && isNum(l) ? w + '–' + l : '—'; };
CC.date = function (iso, withTime) {
  var d = iso ? new Date(iso) : null;
  if (!d || isNaN(d)) return '—';
  var s = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  return withTime ? s + ' ' + fmt.time(iso) : s;
};
/* Start time not set (TBA): the payload's `tba` flag, else ESPN's placeholder time, midnight US Eastern, on a game not
 * yet played (oddsmarkets/college/canon.py time_tba; ESPN writes real late Hawaii tip-offs as 04:59Z). */
var ETF = null;
function etParts(d) {
  try {
    if (!ETF) ETF = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
    var o = {};
    ETF.formatToParts(d).forEach(function (x) { o[x.type] = x.value; });
    return o;
  } catch (e) { return null; }
}
CC.tba = function (c) {
  if (!c || (c.status && c.status !== 'pre')) return false;
  if (c.tba) return true;
  var d = c.date ? new Date(c.date) : null;
  if (!d || isNaN(d)) return false;
  var p = etParts(d);
  if (!p) return /T0[45]:00(:00)?(\.0+)?Z$/.test(String(c.date));
  return (p.hour === '00' || p.hour === '24') && p.minute === '00' && p.second === '00';
};
/* The instant a list files a game under: for a TBA game noon UTC of its US Eastern date, so the day reads right in
 * every US time zone (the placeholder midnight Eastern is the evening before on the west coast). */
CC.gameDate = function (c) {
  if (!CC.tba(c)) return c.date;
  var p = etParts(new Date(c.date));
  return (p && p.year ? p.year + '-' + p.month + '-' + p.day : String(c.date).slice(0, 10)) + 'T12:00:00Z';
};
/* "Sat 28 Nov 7:30 PM", or "Sat 28 Nov · time TBA" */
CC.when = function (c) { return CC.tba(c) ? CC.date(CC.gameDate(c)) + ' · time TBA' : CC.date(c.date, true); };
CC.cls = function (v) { return isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : ''; };
CC.p = function (x) { return isNum(x) ? Number(x) : null; };

/* ── games: CARD (PAYLOADS.md) -> kit game shape ─────────────────────── */
CC.status = function (c) { return c.status === 'in' ? 'live' : c.status === 'post' ? 'final' : 'pre'; };
CC.roundLabel = function (c) {
  if (!c) return '';
  if (c.stype === 'cfp') return 'CFP · ' + (c.round || 'Playoff');
  if (c.stype === 'ncaa') return 'NCAA · ' + (c.round || '') + (c.region ? ' · ' + c.region : '');
  if (c.stype === 'bowl') return c.round || c.note || 'Bowl';
  if (c.stype === 'conf') return (c.round ? 'Conf. ' + c.round : 'Conference tournament');
  if (c.stype === 'nit' || c.stype === 'wbit') return c.stype.toUpperCase() + (c.round ? ' · ' + c.round : '');
  return '';
};
function rankTag(c, side) {
  var seed = side === 'home' ? c.hseed : c.aseed, rk = side === 'home' ? c.hr : c.ar;
  if (isNum(seed) && (c.stype === 'ncaa' || c.stype === 'cfp')) return '(' + seed + ') ';
  return isNum(rk) && rk <= 25 ? '#' + rk + ' ' : '';
}
CC.side = function (L, c, side, S) {
  var tid = c[side], t = CC.team(L, tid) || {};
  return { name: rankTag(c, side) + (t.short || t.name || ('Team ' + tid)), abbr: t.abbr, colour: t.colour, href: CC.teamHref(L, tid, S || c.season) };
};
CC.game = function (c, L) {
  if (c && !c.season && CC.state && CC.state.S) c = Object.assign({ season: CC.state.S }, c);
  var st = CC.status(c), m = c.model || {}, mk = c.market || null;
  var tag = CC.roundLabel(c);
  var per = isNum(c.period) ? (CC.fb(L) ? (c.period > 4 ? 'OT' : 'Q' + c.period) : (L === 'mbb' || Number(c.season) < 2016 ? (c.period > 2 ? 'OT' : 'H' + c.period) : (c.period > 4 ? 'OT' : 'Q' + c.period))) : null;
  return {
    sport: 'college', id: c.id, start: CC.gameDate(c), status: st, tba: CC.tba(c),
    league: CC.LSHORT[L] + (tag ? ' · ' + tag : (c.conf_game ? ' · Conference' : '')) + (c.neutral && !tag ? ' · Neutral' : ''),
    home: CC.side(L, c, 'home'), away: CC.side(L, c, 'away'), hs: isNum(c.hs) ? c.hs : null, as: isNum(c.as) ? c.as : null,
    p_home: isNum(m.p_home) ? m.p_home : null, market_home: mk && isNum(mk.p_home) ? mk.p_home : null,
    note: '', period: per, clock: c.clock, href: CC.gameHref(L, c.id, c.season)
  };
};
CC.card = function (c, L) {
  var g = CC.game(c, L), h = QK.matchCard(g, { sport: false });
  /* the kit's badge prints the start time: a TBA game shows its day and "TBA" instead of the midnight placeholder */
  if (g.tba) h = h.replace(QK.statusBadge(g), '<span class="qk-badge">' + esc(fmt.relDay(g.start)) + ' · TBA</span>');
  return h;
};

/* ── UI pieces ───────────────────────────────────────────────────────── */
var U = CC.ui = {};
U.tabsHTML = function (tabs, active) {
  if (!tabs || !tabs.length) return '';
  return '<nav class="qk-tabs cc-tabs" aria-label="Views">' + tabs.map(function (t) {
    return '<a class="qk-tab" href="' + esc(t.href) + '"' + (t.key === active ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + esc(t.label) + '</a>';
  }).join('') + '</nav>';
};
U.kicker = function (L, S) {
  var i = CC.info(L), P = { preseason: 'Preseason', regular: 'Regular season', conf_champ: 'Championship week', bowls: 'Bowl season', playoff: 'Playoff',
    offseason: 'Offseason', conf_tourneys: 'Conference tournaments', ncaa: 'NCAA tournament' };
  var ph = CC.isCur(L, S) ? i.phase : null;
  return CC.LNAME[L] + ' · ' + CC.seasonLabel(L, S) + (ph ? ' · ' + (P[ph] || ph) : '') + (CC.isCur(L, S) && CC.fb(L) && i.week && ph === 'regular' ? ' · Week ' + i.week : '');
};
U.head = function (title, sub, kicker, right) {
  return '<header class="cc-head"><div>' + (kicker ? '<div class="qk-kicker">' + esc(kicker) + '</div>' : '') + '<h1>' + esc(title) + '</h1>' +
    (sub ? '<div class="qk-sub">' + sub + '</div>' : '') + '</div>' + (right || '') + '</header>';
};
U.tabs = function (L, sec, list, S, active) {
  return U.tabsHTML(list.map(function (x, i) { return { key: x[0], label: x[1], href: CC.href(L, sec, null, S, i ? 'tab=' + x[0] : '') }; }), active);
};
U.tab = function (params, keys, dflt) { var t = (params.query || {}).tab; return keys.indexOf(t) >= 0 ? t : dflt; };
U.card = function (title, sub, body, o) {
  o = o || {};
  return '<section class="qk-card cc-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-card-head"><div><h2 class="qk-card-title">' + esc(title) + '</h2>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
U.section = function (title, sub, body, right) {
  return '<section class="qk-section cc-sec"><div class="qk-section-head"><div><h2>' + esc(title) + '</h2>' + (sub ? '<div class="qk-sub">' + sub + '</div>' : '') + '</div>' + (right || '') + '</div>' + body + '</section>';
};
U.chart = function (id, h, label) { return '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; };
U.link = function (href, text) { return '<a class="cc-link" href="' + esc(href) + '">' + esc(text) + ' →</a>'; };
U.note = function (html) { return '<p class="cc-note">' + html + '</p>'; };
U.teamEnt = function (L, tid, o) {
  o = o || {};
  if (!tid) return '<span class="qk-muted">—</span>';
  var t = CC.team(L, tid) || { name: 'Team ' + tid };
  return '<a class="cc-ent" href="' + esc(CC.teamHref(L, tid, o.season)) + '">' + QK.teamMark({ name: t.name, abbr: t.abbr, colour: t.colour }, 'sm') +
    '<span class="nm">' + esc(o.abbr ? CC.tabbr(L, tid) : (o.full ? t.name : (t.short || t.name))) + '</span>' + (o.sub ? '<span class="sb">' + esc(o.sub) + '</span>' : '') + '</a>';
};
U.playerEnt = function (L, pid, name, tid, sub, S) {
  return '<a class="cc-ent" href="' + esc(CC.playerHref(L, pid, S)) + '">' + (tid ? QK.teamMark(CC.team(L, tid) || { name: '?' }, 'sm') : '') +
    '<span class="nm">' + esc(name || CC.pname(L, pid)) + '</span>' + (sub ? '<span class="sb">' + esc(sub) + '</span>' : '') + '</a>';
};
U.grade = function (g) { return g ? '<span class="cc-grade" data-g="' + esc(String(g).charAt(0).toUpperCase()) + '">' + esc(g) + '</span>' : '—'; };
U.empty = function (t, s) { return QK.empty(t, s); };
U.missing = function (what, d) {
  return QK.empty(what + ' not available yet', d && d.reason && !d.missing ? d.reason : 'This payload has not been built for the season shown.');
};
/* A probability cell shaded by its value (tokens only): heat tables of P(reach round) and the like. */
U.heat = function (p, d) {
  if (!isNum(p)) return { v: -1, html: '<span class="qk-muted">—</span>' };
  var a = Math.round(Math.min(1, Math.max(0, p)) * 70);
  return { v: p, html: CC.pct(p, d), style: 'background:color-mix(in srgb, var(--c-1) ' + a + '%, transparent)' + (a > 42 ? ';color:var(--ink-1);font-weight:600' : '') };
};
U.bar = function (p, col) { return '<span class="cc-pbar" role="img" aria-label="' + CC.pct(p) + '"><span style="width:' + (isNum(p) ? Math.max(1, Math.min(100, p * 100)) : 0) + '%;' + (col ? 'background:' + col : '') + '"></span></span>'; };
U.alive = function (el) { return !!el && el.isConnected; };
U.table = function (cols, rows, o) { return QK.tableHTML(cols, rows, Object.assign({ sticky: true }, o || {})); };
U.wire = function (el) { QK.sortable(el); };

/* Seasons a page can show, newest first, as <option>s. */
function seasonOptions(L, S) {
  return CC.seasons(L).map(function (s) { return '<option value="' + s + '"' + (Number(s) === Number(S) ? ' selected' : '') + '>' + esc(CC.seasonLabel(L, s)) + (CC.isCur(L, s) ? ' (current)' : '') + '</option>'; }).join('');
}

/* ── router ──────────────────────────────────────────────────────────── */
var ROUTES = {};
CC.route = function (name, fn) { ROUTES[name] = fn; };
CC.state = { L: null, S: null, sec: 'overview' };
var SEC_OF = { overview: 'overview', games: 'fixtures', game: 'fixtures', standings: 'standings', teams: 'teams', team: 'teams', players: 'players',
  player: 'players', value: 'value', fantasy: 'fantasy', lab: 'lab', model: 'model', disclaimer: 'model' };
var shell = null;
CC.parse = function (hash) {
  var h = String(hash || '').replace(/^#\/?/, '');
  var qi = h.indexOf('?'), qs = qi >= 0 ? h.slice(qi + 1) : '', path = qi >= 0 ? h.slice(0, qi) : h;
  var query = {};
  qs.split('&').forEach(function (kv) { if (!kv) return; var p = kv.split('='); query[decodeURIComponent(p[0])] = decodeURIComponent(p.slice(1).join('=') || ''); });
  var parts = path.split('/').filter(function (x) { return x !== ''; }).map(decodeURIComponent);
  var r = { L: null, sec: 'overview', id: null, S: null, query: query };
  if (parts[0] === 'disclaimer') { r.sec = 'disclaimer'; return r; }
  if (CC.LEVELS.indexOf(parts[0]) >= 0) {
    r.L = parts.shift();
    if (parts.length && /^\d{4}$/.test(parts[parts.length - 1])) r.S = Number(parts.pop());
    if (parts[0]) r.sec = parts[0];
    if (parts[1]) r.id = parts[1];
  }
  if (query.season && /^\d{4}$/.test(query.season)) r.S = Number(query.season);
  return r;
};
CC.defaultLevel = function () {
  var saved = QK.store('qc-level');
  if (CC.LEVELS.indexOf(saved) >= 0 && CC.info(saved).ok !== false) return saved;
  var live = function (L) { var p = CC.info(L).phase; return CC.info(L).ok !== false && p && p !== 'offseason' && p !== 'preseason'; };
  var m = new Date().getMonth();
  if (live('cfb') && (m >= 7 || m === 0)) return 'cfb';
  if (live('mbb')) return 'mbb';
  if (live('cfb')) return 'cfb';
  if (live('wbb')) return 'wbb';
  return m >= 7 || m === 0 ? 'cfb' : 'mbb';
};
function sectionHrefs(L) {
  var map = { overview: '', fixtures: 'games', standings: 'standings', teams: 'teams', players: 'players', value: 'value', fantasy: 'fantasy', lab: 'lab', model: 'model' };
  QK.$$('.qk-secnav a[data-sec]').forEach(function (a) { var k = a.getAttribute('data-sec'); a.setAttribute('href', '#/' + L + (map[k] ? '/' + map[k] : '')); });
}
function paintCtx(L, S) {
  QK.$$('#cc-level button').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-value') === L ? 'true' : 'false'); });
  var sel = QK.$('#cc-season');
  if (sel) { sel.innerHTML = seasonOptions(L, S); sel.disabled = CC.seasons(L).length < 2; }
}
function render() {
  var r = CC.parse(root.location.hash);
  if (r.sec === 'disclaimer') {
    shell.setSection('model');
    var main0 = QK.$('#app');
    var t = document.getElementById('disclaimer-template');
    main0.innerHTML = '<div class="cc-page">' + U.head('Disclaimer and terms', '', 'The Quant Campus') + (t ? t.innerHTML : '') + '</div>';
    root.scrollTo(0, 0);
    return;
  }
  if (!r.L) { root.location.replace('#/' + CC.defaultLevel()); return; }
  var L = r.L;
  if (CC.info(L).ok === false && !CC.info(L).current_season) {
    shell.setSection(SEC_OF[r.sec] || 'overview');
    QK.$('#app').innerHTML = '<div class="cc-page">' + U.head(CC.LNAME[L], '', 'The Quant Campus') + QK.empty(CC.LNAME[L] + ' is not available yet', CC.info(L).reason || 'Its payloads have not been built.') + '</div>';
    return;
  }
  var S = r.S && CC.seasons(L).indexOf(r.S) >= 0 ? r.S : (r.S || CC.cur(L));
  CC.state = { L: L, S: S, sec: r.sec, id: r.id };
  QK.store('qc-level', L);
  document.documentElement.setAttribute('data-level', L);
  sectionHrefs(L); paintCtx(L, S);
  shell.setSection(SEC_OF[r.sec] || 'overview');
  var fn = ROUTES[r.sec];
  var el = QK.$('#app');
  el.innerHTML = '<div class="cc-page"></div>';
  var page = el.firstChild;
  if (!fn) { page.innerHTML = QK.empty('Page not found', 'Try the sections above.'); return; }
  var prevKey = render.key, key = L + '/' + r.sec + '/' + (r.id || '') + '/' + S;
  render.key = key;
  if (prevKey !== key) root.scrollTo(0, 0);
  try {
    var pr = fn(page, { L: L, S: S, id: r.id, query: r.query, sec: r.sec });
    if (pr && pr.then) pr.then(null, function (e) { console.error(e); page.innerHTML = QK.empty('This page could not be shown', String(e && e.message || e)); });
  } catch (e) { console.error(e); page.innerHTML = QK.empty('This page could not be shown', String(e && e.message || e)); }
  document.title = (r.sec === 'overview' ? CC.LSHORT[L] + ' ' : '') + 'The Quant Campus';
}
CC.go = function (h) { if (root.location.hash === h) render(); else root.location.hash = h; };
CC.rerender = render;

function boot() {
  var ctx = '<div class="cc-ctx"><div class="qk-seg" id="cc-level" role="group" aria-label="Level">' + CC.LEVELS.map(function (L) {
    return '<button type="button" data-value="' + L + '" aria-pressed="false" title="' + esc(CC.LNAME[L]) + '">' + CC.LSHORT[L] + '</button>';
  }).join('') + '</div><select class="qk-select" id="cc-season" aria-label="Season"></select></div>';
  shell = QK.shell({
    sport: 'college', section: 'overview', ctx: ctx,
    sections: QK.sections('college'),
    search: { load: function () { return CC.load('search.json').then(function (rows) { return Array.isArray(rows) ? rows.map(function (r) { return { sport: 'college', t: r.t, s: r.s, href: r.href, w: r.w }; }) : []; }); } }
  });
  QK.seg(QK.$('#cc-level'), function (L) {
    var st = CC.state, sec = st.sec;
    var keep = { overview: 1, games: 1, standings: 1, teams: 1, players: 1, value: 1, fantasy: 1, lab: 1, model: 1 };
    var to = { game: 'games', team: 'teams', player: 'players' }[sec] || (keep[sec] ? sec : 'overview');
    CC.go('#/' + L + (to !== 'overview' ? '/' + to : ''));
  });
  QK.$('#cc-season').addEventListener('change', function (e) {
    var st = CC.state, S = Number(e.target.value);
    var to = { game: 'games' }[st.sec] || st.sec;
    var id = to === st.sec && (st.sec === 'team' || st.sec === 'player') ? st.id : null;
    CC.go(CC.href(st.L, to, id, S));
  });
  QK.$('#app').innerHTML = QK.skeleton('lines', 6);
  CC.load('index.json').then(function (idx) {
    if (!CC.ok(idx) || !idx.levels) {
      QK.$('#app').innerHTML = QK.empty('The site data did not load', (idx && idx.reason) || 'index.json is missing.');
      return;
    }
    CC.index = idx;
    CC.LEVELS.forEach(function (L) { var i = idx.levels[L] || {}; CC.addTeams(L, i.teams); CC.addConfs(L, i.conferences); });
    var meta = QK.$('#meta-line');
    if (meta) meta.textContent = 'Data built ' + fmt.ago(idx.updated_at) + ' (' + new Date(idx.updated_at).toLocaleString() + ').';
    root.addEventListener('hashchange', render);
    render();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else setTimeout(boot, 0);

})(window);
