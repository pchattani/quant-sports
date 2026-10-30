/* The Quant Campus — core: data loading, router, shell, level switch, shared helpers (window.CC).
 *
 * Routes (level first; oddsmarkets/college/PAYLOADS.md "Front end"):
 *   #/                      the level in season (remembered choice first)        #/<L>            overview
 *   #/<L>/games             games by week (cfb) or day (basketball)              #/<L>/game/<gid> game centre
 *   #/<L>/standings?tab=    conferences | polls | playoff | bowls (cfb) | bracket | conftourneys (basketball)
 *   #/<L>/teams  #/<L>/team/<tid>  #/<L>/scout (the Scouting Room: Players and the Lab in one, round 9)  #/<L>/player/<pid>
 *   #/<L>/compare?p=<pid>,<pid>  #/<L>/compare/progression/<pid>/<pid>
 *   #/<L>/value?tab=position|value|transfers   #/<L>/fantasy   #/<L>/model?tab=method|calibration|market|moves|glossary|terms
 *   old routes redirect (CC.redirect): #/<L>/players -> scout, #/<L>/lab -> scout?view=chart | teams (style map) | compare
 *   ?season=S (or a trailing /S: #/<L>/<S> or #/<L>/<sec>/<id>/<S>) for a past season;  #/disclaimer
 * Data: data/index.json, data/<L>/..., data/<L>/<S>/... (PAYLOADS.md). In local preview only, ?data=<path> points
 * the page at another data folder (the development fixture).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (root) {
'use strict';

var CC = root.CC = {};
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt;
CC.esc = esc; CC.isNum = isNum;
CC.LEVELS = ['cfb', 'mbb', 'wbb', 'mch', 'wch'];
CC.LNAME = { cfb: 'College Football', mbb: "Men's College Basketball", wbb: "Women's College Basketball", mch: "Men's College Hockey", wch: "Women's College Hockey" };
CC.LSHORT = { cfb: 'CFB', mbb: 'MBB', wbb: 'WBB', mch: 'MCH', wch: 'WCH' };
CC.fb = function (L) { return L === 'cfb'; };
/* college hockey (30 Oct 2026; cc-hockey.js holds its own pages): men's mch, women's wch */
CC.hk = function (L) { return L === 'mch' || L === 'wch'; };

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
var TEAMS = { cfb: {}, mbb: {}, wbb: {}, mch: {}, wch: {} }, CONFS = { cfb: {}, mbb: {}, wbb: {}, mch: {}, wch: {} }, PLAYERS = { cfb: {}, mbb: {}, wbb: {}, mch: {}, wch: {} };
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
/* v4: the raw kit colour and the alternate (payload alt, else alt_colour; absent until the data agent adds it, when the
 * kit's fallbacks apply: QK.color.blockPair gives a clash slate with the kit as its rule) for blocks and heroes */
CC.traw = function (L, tid) { var t = CC.team(L, tid); return t && QK.color.parse(t.colour) ? t.colour : null; };
CC.talt = function (L, tid) { var t = CC.team(L, tid) || {}; var a = t.alt || t.alt_colour; return QK.color.parse(a) ? a : null; };
/* Line colours for several teams on one chart (kit rule: two team colours on one chart kept apart): each team's colour
 * lifted for the card, else, when it is too close to one already used (QK.color.distinct), the next chart slot. */
CC.lineColours = function (L, tids) {
  var used = [], cat = (window.QKC && QKC.tokens ? QKC.tokens().cat : null) || ['#7d93ff', '#ff6b4a', '#38d2e6', '#d4ff3a', '#c78cff', '#ffb347', '#5ee6a8', '#ff7eb6'], k = 0;
  return (tids || []).map(function (t) {
    var c = CC.tcol(L, t);
    var clash = function (x) { return used.some(function (u) { return QK.color.distinct ? !QK.color.distinct(u, x) : u === x; }); };
    while (clash(c) && k < cat.length * 2) c = cat[k++ % cat.length];
    used.push(c);
    return c;
  });
};
CC.tcol = function (L, tid) { var t = CC.team(L, tid); return t && QK.color.parse(t.colour) ? QK.color.team(t.colour) : QK.cssVar('--c-other'); };
/* Season payload: season.json for (L, S) with its teams and conferences registered. */
CC.season = function (L, S) {
  return CC.load(CC.path(L, S, 'season.json')).then(function (d) {
    if (CC.ok(d)) { CC.addTeams(L, d.teams); CC.addConfs(L, d.conferences); CC.addRecords(L, S, d.standings); }
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
/* the Scouting Room (#/<L>/scout) and the full compare page (#/<L>/compare?p=<pid>,<pid>[,<pid>]) */
CC.scoutHref = function (L, S, query) { return CC.href(L, 'scout', null, S, query); };
CC.compareHref = function (L, S, ids) { return CC.href(L, 'compare', null, S, 'p=' + (ids || []).map(encodeURIComponent).join(',')); };

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
  var s = fmt.date(iso);   /* the kit's en-GB convention: "Mon 19 Oct" */
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
  return { name: rankTag(c, side) + (t.short || t.name || ('Team ' + tid)), abbr: t.abbr, colour: t.colour, alt: CC.talt(L, tid) || undefined, full: t.name || undefined, href: CC.teamHref(L, tid, S || c.season) };
};
CC.game = function (c, L) {
  if (c && !c.season && CC.state && CC.state.S) c = Object.assign({ season: CC.state.S }, c);
  var st = CC.status(c), m = c.model || {}, mk = c.market || null;
  var tag = CC.roundLabel(c);
  var per = isNum(c.period) ? (CC.fb(L) ? (c.period > 4 ? 'OT' : 'Q' + c.period) : CC.hk(L) ? (c.period > 3 ? 'OT' : 'P' + c.period) : (L === 'mbb' || Number(c.season) < 2016 ? (c.period > 2 ? 'OT' : 'H' + c.period) : (c.period > 4 ? 'OT' : 'Q' + c.period))) : null;
  /* hockey keeps ties: our chance of a tie travels as the kit's draw (CC.card says "Tie") */
  var hk = CC.hk(L) && isNum(m.p_tie);
  return {
    sport: 'college', id: c.id, start: CC.gameDate(c), status: st, tba: CC.tba(c),
    league: CC.LSHORT[L] + (tag ? ' · ' + tag : (c.conf_game ? ' · Conference' : '')) + (c.neutral && !tag ? ' · Neutral' : ''),
    home: CC.side(L, c, 'home'), away: CC.side(L, c, 'away'), hs: isNum(c.hs) ? c.hs : null, as: isNum(c.as) ? c.as : null,
    p_home: isNum(m.p_home) ? m.p_home : null, p_draw: hk && c.stype !== 'ncaa' && c.stype !== 'conf' ? m.p_tie : undefined, p_away: hk && isNum(m.p_away) ? m.p_away : undefined,
    market_home: mk && isNum(mk.p_home) ? mk.p_home : null, market_src: mk ? CC.mkSource(mk) || undefined : undefined,
    /* no live chance in the payload: a live game shows our pre-game call, labelled so (kit v3) */
    pre_only: st === 'live' ? true : undefined, neutral: c.neutral ? true : undefined,
    note: '', period: per, clock: c.clock, href: CC.gameHref(L, c.id, c.season)
  };
};
/* Records (W-L) for the game cards, registered from each season's standings. */
var RECS = { cfb: {}, mbb: {}, wbb: {}, mch: {}, wch: {} };
CC.addRecords = function (L, S, standings) {
  var k = String(S);
  RECS[L][k] = RECS[L][k] || {};
  Object.keys(standings || {}).forEach(function (c) { (standings[c] || []).forEach(function (r) { if (r && isNum(r.w) && isNum(r.l)) RECS[L][k][String(r.team)] = r.w + '-' + r.l + (CC.hk(L) && isNum(r.t) ? '-' + r.t : ''); }); });
};
CC.rec = function (L, S, tid) { var m = RECS[L][String(S)]; return (m && m[String(tid)]) || ''; };
var MK_SRC = { kalshi: 'Kalshi', polymarket: 'Polymarket', espn_close: 'ESPN closing line', espn: 'ESPN line' };
CC.mkSource = function (mk) { return mk && mk.source ? (MK_SRC[mk.source] || mk.source) : ''; };
/* A game card (kit v3): our chance per team, the favourite in blue, records, the team-colour bar with a key, and, before
 * the start, the market's chance small and grey under ours with its source on hover (round 6: market 'quiet';
 * o.market: false hides it). o.why adds the italic one-line reason (QK.whyLine). */
CC.card = function (c, L, o) {
  o = o || {};
  var g = CC.game(c, L), S = c.season || (CC.state && CC.state.S);
  g.home.record = CC.rec(L, S, c.home); g.away.record = CC.rec(L, S, c.away);
  var h = QK.gameCard(g, { sport: false, why: !!o.why, market: o.market === false ? false : 'quiet' });
  /* the kit's badge prints the start time: a TBA game shows its day and "TBA" instead of the midnight placeholder */
  if (g.tba) h = h.replace(QK.statusBadge(g), '<span class="qk-badge">' + esc(fmt.relDay(g.start)) + ' · TBA</span>');
  if (CC.hk(L)) h = CC.tieWords(h);
  return h;
};
/* the kit says "Draw"; college hockey says "tie" */
CC.tieWords = function (h) {
  return String(h).replace(/>Draw </g, '>Tie <').replace(/Draw <b>/g, 'Tie <b>').replace(/A draw\./g, 'A tie.');
};
/* The game model's calibration record for "How sure are we?": a level's calibration.json in the kit's shape
 * (QK.calib.find), else the builder's own (calibration: [{lo, hi, n, p_mean, y_mean}], summary.model {n, brier}).
 * null when the file is not there or has no buckets: the module is then left out. */
CC.calib = function (j) {
  if (!CC.ok(j)) return null;
  var c = QK.calib.find(j);
  if (c && c.bins && c.bins.length) return c;
  var b = (Array.isArray(j.calibration) ? j.calibration : []).filter(function (r) { return r && isNum(r.p_mean) && isNum(r.y_mean) && isNum(r.n); })
    .map(function (r) { return { lo: r.lo, hi: r.hi, n: r.n, mean_p: r.p_mean, freq: r.y_mean }; });
  if (!b.length) return null;
  var m = (j.summary || {}).model || {};
  return { n: isNum(m.n) ? m.n : b.reduce(function (a, x) { return a + x.n; }, 0), brier: m.brier, logloss: m.logloss, bins: b };
};
/* Unit names for display: the football defensive front is written "DL/edge" in the payloads. */
CC.unit = function (s) { return String(s || '').replace(/DL\/edge/gi, 'Defensive front'); };
/* Payload copy in our voice (headlines written by the builder): "title odds" -> "title chances". Still needed for the
 * local payloads: index.json headlines and the basketball season.json say "title odds" (23 Oct 2026; the deployed
 * index.json is clean, so this goes after the next local rebuild). DL/edge (CC.unit) is the payloads' unit name and stays. */
CC.copy = function (s) { return CC.uk(String(s || '').replace(/\btitle odds\b/gi, 'title chances').replace(/\bodds\b/gi, 'chances')); };
/* British spelling for payload labels (round 9): the builders write "Offence" / "Defence" from 28 Oct 2026; payloads
 * built before that still say "Offense" / "Defense" until their next build. */
CC.uk = function (s) { return String(s === undefined || s === null ? '' : s).replace(/\b(O|o)ffense/g, '$1ffence').replace(/\b(D|d)efense/g, '$1efence').replace(/\bCenters?\b/g, 'Centre'); };
/* One player's position in words, singular ("Guard", not the catalogue's plural group name "Guards"). */
var POS_NAME = { QB: 'Quarterback', RB: 'Running back', WR: 'Wide receiver', TE: 'Tight end', OL: 'Offensive line', DL: 'Defensive line', LB: 'Linebacker', DB: 'Defensive back',
  K: 'Kicker', P: 'Punter', G: 'Guard', F: 'Forward', C: 'Centre', W: 'Wing', B: 'Big' };
var POS_HK = { F: 'Forward', D: 'Defenceman', G: 'Goalie' };
CC.posName = function (L, pos) { if (CC.hk(L)) return POS_HK[String(pos || '').toUpperCase()] || String(pos || ''); return POS_NAME[String(pos || '').toUpperCase()] || String(pos || ''); };
/* Does a game have its own page? Game pages are written for the current season and the previous season's
 * postseason (PAYLOADS.md size budget; football's conference title games are not among them). Other games link to
 * the recap card on the game route, which then reads the schedule only (no 404 for a file never built). */
CC.hasPage = function (L, c, S) {
  var s = Number((c && c.season) || S);
  if (CC.isCur(L, s)) return true;
  if (s !== Number(CC.cur(L)) - 1 || !c) return false;
  var st = c.stype || 'reg';
  return st !== 'reg' && st !== 'pre' && st !== 'exh' && !(CC.fb(L) && st === 'conf');
};

/* ── comparison metric sets (METRICS_SPEC.md; assets/js/cc-metrics.js, generated from docs/_design/metrics/college.json) ──
 * Loaded on demand by the pages that compare (players, player, teams, team, lab), so first loads do not grow. */
var MET_P = null;
CC.metrics = function () {
  if (CC.METRICS) return Promise.resolve(CC.METRICS);
  if (MET_P) return MET_P;
  MET_P = new Promise(function (resolve) {
    var s = document.createElement('script');
    s.src = 'assets/js/cc-metrics.js';
    s.onload = function () { resolve(CC.METRICS || []); };
    s.onerror = function () { MET_P = null; resolve([]); };
    document.head.appendChild(s);
  });
  return MET_P;
};
/* The peer group of a player row (by the group's payload field: pos for football, role for basketball) or of a team. */
CC.group = function (L, kind, row) {
  var gs = CC.METRICS || [];
  for (var i = 0; i < gs.length; i++) {
    var g = gs[i];
    if (g.L !== L || g.e !== kind) continue;
    if (kind === 'team') return g;
    if (row && g.pf && (g.pc || []).indexOf(row[g.pf]) >= 0) return g;
  }
  return null;
};
/* The minimum in words, from the spec's note ("db >= 12.5 per team game (150 over 12 games); ..."). */
CC.groupFloor = function (g) {
  var n = ((g && g.min) || {}).n || '';
  n = n.split(';')[0].replace(/\bdb\b/g, 'dropbacks').replace(/>=/g, '≥').replace(/players\.json `?qualified`?:\s*/i, '');
  return n.replace(/\s*\([^)]*\)\s*$/, '');
};
/* The sample a metric settles in (the spec's m50 unit), for one catalogue row. */
CC.sampleIn = function (row, unit) {
  var v = (row && row.values) || {};
  if (unit === 'games') return isNum(row.gp) ? row.gp : null;
  if (unit === 'dropbacks') return isNum(v.db) ? v.db : null;
  if (unit === 'carries') return isNum(v.rush_car) ? v.rush_car : null;
  if (unit === 'targets') return isNum(v.tgt) ? v.tgt : null;
  if (unit === 'FGA') return isNum(v.fga) ? v.fga : null;
  if (unit === 'punts') return isNum(v.punts) ? v.punts : null;
  if (unit === 'minutes') return isNum(v.min) && isNum(row.gp) ? v.min * row.gp : null;
  return null;
};
/* Spec rows for a catalogue row: [{ m (spec metric), label, pctl, value, tip, early, style }] for the set ('h' | 's'),
 * only where the payload carries both the value and the group's percentile. meta: payload metrics by key (format). */
CC.specRows = function (g, row, set, meta) {
  if (!g || !row) return [];
  var pc = row[g.pct] || {}, v = row.values || {};
  return g.m.filter(function (m) { return m.set === set && isNum(v[m.id]) && isNum(pc[m.id]); }).map(function (m) {
    var n = m.m50 ? CC.sampleIn(row, m.mu) : null;
    return { m: m, label: m.d, pctl: pc[m.id], value: CC.fmtMetric((meta || {})[m.id] || { fmt: /pct|rate|share/.test(m.id) && v[m.id] <= 1 ? 'pct' : '2' }, v[m.id]),
      tip: (m.x || m.d) + (CC.ours(m.id) ? ' Our model: ' + CC.ours(m.id).name + '.' : '') + (m.style ? ' Describes playing style, not how well: shown in grey.' : '') + (m.m50 ? ' Settles after about ' + Math.round(m.m50) + ' ' + m.mu + '.' : ''),
      early: isNum(n) && m.m50 && n < m.m50, style: !!m.style };
  });
};

/* ── our metrics (round 5) ──────────────────────────────────────────────
 * The spec's labels file (assets/qk/metrics/college.labels.json through QK.spec) names the metrics that come from our
 * own models (team ratings and their offence / defence split, the value model, opponent-adjusted EPA, the box
 * rating). Names, units and explanations come from the level's own spec groups (cc-metrics.js), because college.json
 * reuses ids across football and basketball. CC.ours(k) -> { key, name, about } | null; CC.oursTag(k, short, about);
 * CC.oursHeads(box, map) tags the heads of our metrics (map: header text or data-k -> key; re-applied when a table
 * re-renders); CC.specMeta(L, e, k) -> the level's spec entry { d, x, u, low, style, set } | null; CC.orderMetrics(L, e,
 * list) -> [{ label, items }]: "Our models", then the spec's headline box-score metrics, then the rest by group. */
CC.spec = null;
CC.specP = (window.QK && QK.spec ? QK.spec.load('college') : Promise.resolve(null)).then(function (c) { CC.spec = c; return c; }, function () { return null; });
CC.ours = function (k) { return CC.spec ? CC.spec.ours(k) : null; };
CC.oursTag = function (k, short, about) { var o = CC.ours(k); return o ? QK.ours({ short: !!short, model: o.name, about: about || o.about }) : ''; };
CC.specMeta = function (L, e, k) {
  var gs = CC.METRICS || [], best = null;
  for (var i = 0; i < gs.length; i++) {
    var g = gs[i];
    if (g.L !== L || g.e !== e) continue;
    for (var j = 0; j < (g.m || []).length; j++) {
      var m = g.m[j];
      if (m.id !== k) continue;
      if (m.set === 'h') return m;
      if (!best) best = m;
    }
  }
  return best;
};
CC.oursHeads = function (box, map) {
  if (!box) return;
  var apply = function () {
    if (!CC.spec) return;
    QK.$$('th', box).forEach(function (th) {
      if (th.querySelector('.qk-ours')) return;
      var dk = th.getAttribute('data-k'), txt = (th.textContent || '').replace(/[\u2191\u2193\u2195\u25b2\u25bc\u25b4\u25be\u21c5]/g, '').trim();
      var key = map ? (map[dk] || map[txt]) : dk;
      if (!key || !CC.ours(key)) return;
      (th.querySelector('button') || th).insertAdjacentHTML('beforeend', CC.oursTag(key, true));
    });
  };
  CC.specP.then(apply);
  apply();
  if (window.MutationObserver && !box._qkOurs) {
    box._qkOurs = new MutationObserver(function () { apply(); });
    box._qkOurs.observe(box, { childList: true, subtree: true });
  }
};
CC.orderMetrics = function (L, e, list) {
  var ours = [], head = [], rest = [];
  (list || []).forEach(function (m, i) {
    var sm = CC.specMeta(L, e, m.key);
    var o = { m: m, i: i, h: sm && sm.set === 'h' ? 1 : 0 };
    (CC.ours(m.key) ? ours : o.h ? head : rest).push(o);
  });
  var byH = function (a, b) { return (b.h - a.h) || (a.i - b.i); };
  var out = [];
  if (ours.length) out.push({ label: 'Our models', items: ours.sort(byH).map(function (x) { return x.m; }) });
  if (head.length) out.push({ label: 'Box score: headline', items: head.map(function (x) { return x.m; }) });
  var gs = [];
  rest.forEach(function (x) { var gn = x.m.group || 'Other', g = gs.filter(function (y) { return y.n === gn; })[0]; if (!g) { g = { n: gn, items: [] }; gs.push(g); } g.items.push(x.m); });
  gs.forEach(function (g) { out.push({ label: 'Box score: ' + g.n, items: g.items }); });
  return out;
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
/* Page head (v2): QK.sectionHead, large, h1. sub is HTML (callers escape payload text). */
U.head = function (title, sub, kicker, right) {
  return QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', size: 'lg', tag: 'h1', html: true, cls: 'cc-sh' });
};
/* Stat tiles (v2): ours first with signal: true. */
U.stats = function (list) { return '<div class="cc-kpis">' + QK.stats(list) + '</div>'; };
/* A leaderboard into a fresh node, returned as HTML with an id to mount after the page is written. */
U.lb = function (id) { return '<div id="' + esc(id) + '" class="cc-lb"></div>'; };
U.mark = function (L, tid) { var t = CC.team(L, tid) || { name: tid ? 'Team ' + tid : '?' }; return { name: t.name, abbr: t.abbr, colour: t.colour, alt: CC.talt(L, tid) || undefined }; };
U.tabs = function (L, sec, list, S, active) {
  return U.tabsHTML(list.map(function (x, i) { return { key: x[0], label: x[1], href: CC.href(L, sec, null, S, i ? 'tab=' + x[0] : '') }; }), active);
};
U.tab = function (params, keys, dflt) { var t = (params.query || {}).tab; return keys.indexOf(t) >= 0 ? t : dflt; };
U.card = function (title, sub, body, o) {
  o = o || {};
  var head = title || sub || o.right ? '<div class="qk-card-head"><div><h2 class="qk-card-title">' + esc(title) + '</h2>' + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '';
  return '<section class="qk-card cc-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' + head + '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
U.section = function (title, sub, body, right, kicker) {
  return '<section class="qk-section cc-sec">' + QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', html: true }) + body + '</section>';
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
/* A payload that is not there yet. Before a season's first games the builder writes {ok: false, reason}: say so in
 * plain words and offer last season (the same section), rather than an error. */
U.missing = function (what, d) {
  var st = CC.state || {}, L = st.L, S = st.S;
  var prev = L ? CC.seasons(L).filter(function (s) { return s < Number(S); })[0] : null;
  var sec = { games: 'games', game: 'games', team: 'teams', player: 'scout', compare: 'scout' }[st.sec] || st.sec;
  var link = prev && sec ? '<div class="cc-empty-act"><a class="qk-btn" href="' + esc(CC.href(L, sec, st.sec === 'team' ? st.id : st.sec === 'player' ? null : null, prev)) + '">See ' + esc(CC.seasonLabel(L, prev)) + '</a></div>' : '';
  if (d && d.ok === false && !d.missing) return QK.empty(what + ' starts once games are played', L && CC.isCur(L, S) ? 'Nothing has been played in ' + CC.seasonLabel(L, S) + ' yet; the numbers appear after the first games.' : (d.reason ? 'For ' + CC.seasonLabel(L, S) + ': ' + d.reason + '.' : 'Nothing was played this season.')) + link;
  return QK.empty(what + ' is not published for this season', 'It has not been built for the season shown.') + link;
};
/* A probability cell shaded by its value (tokens only): heat tables of P(reach round) and the like. */
U.heat = function (p, d) {
  if (!isNum(p)) return { v: -1, html: '<span class="qk-muted">—</span>' };
  var a = Math.round(Math.min(1, Math.max(0, p)) * 60);
  return { v: p, html: CC.pct(p, d), style: 'background:color-mix(in srgb, var(--signal) ' + a + '%, transparent)' + (a > 42 ? ';color:var(--ink-1);font-weight:600' : '') };
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
var SEC_OF = { overview: 'overview', games: 'fixtures', game: 'fixtures', standings: 'standings', teams: 'teams', team: 'teams', scout: 'scout',
  player: 'scout', compare: 'scout', value: 'value', fantasy: 'fantasy', model: 'model', disclaimer: 'model' };
/* Round 9: the old Players and Lab routes open the Scouting Room or the Teams page, their parameters mapped
   (players?pos=, lab?kind=players|teams|compare&x=&y=&within=&pos=&q=&c=). Returns the new hash, or null. */
var POS_GROUP = { QB: 'QB', RB: 'RB', WR: 'WR', TE: 'TE', DL: 'DL', LB: 'LB', DB: 'DB', K: 'K', P: 'P', G: 'G', C: 'B', W: 'W', B: 'B' };
CC.redirect = function (r) {
  if (r.sec !== 'players' && r.sec !== 'lab') return null;
  var q = r.query || {}, out = [], L = r.L, S = r.S;
  var add = function (k, v) { if (v !== undefined && v !== null && v !== '') out.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); };
  if (r.sec === 'lab' && q.kind === 'compare') return CC.compareHref(L, S, String(q.p || '').split(',').filter(Boolean));
  if (r.sec === 'lab' && q.kind !== 'players') {
    if (q.x && q.y) { add('map', '-1'); add('mx', q.x); add('my', q.y); }
    return CC.href(L, 'teams', null, S, out.join('&'));
  }
  if (r.sec === 'lab') add('view', 'chart');
  var pos = q.within === 'pos' ? q.pos : q.pos && q.pos !== 'all' ? q.pos : null;
  if (pos && POS_GROUP[String(pos).toUpperCase()]) { add('within', 'pos'); add('pos', POS_GROUP[String(pos).toUpperCase()]); }
  if (r.sec === 'lab') { add('x', q.x); add('y', q.y); add('c', q.c); }
  add('q', q.q);
  return CC.scoutHref(L, S, out.join('&'));
};
/* clean-up work a page registers (the drawer, the tray): run when the next page renders */
var LEAVE = [];
CC.onLeave = function (fn) { if (typeof fn === 'function') LEAVE.push(fn); };
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
    /* a trailing year is the season only in #/<L>/<S> and #/<L>/<sec>/<id>/<S>: in #/cfb/team/2390 it is the id */
    if ((parts.length === 1 || parts.length === 3) && /^\d{4}$/.test(parts[parts.length - 1])) r.S = Number(parts.pop());
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
  var map = { overview: '', fixtures: 'games', standings: 'standings', teams: 'teams', scout: 'scout', value: 'value', fantasy: 'fantasy', model: 'model' };
  QK.$$('.qk-secnav a[data-sec]').forEach(function (a) { var k = a.getAttribute('data-sec'); a.setAttribute('href', '#/' + L + (map[k] ? '/' + map[k] : '')); if (k === 'fantasy') { a.hidden = CC.hk(L); a.style.display = CC.hk(L) ? 'none' : ''; } });
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
  var rd = CC.redirect({ L: L, S: S, sec: r.sec, query: r.query });
  if (rd) { root.location.replace(rd); return; }
  LEAVE.splice(0).forEach(function (fn) { try { fn(); } catch (e) { /* gone */ } });
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
    sections: QK.sections('college', { scout: true }),
    search: { load: function () { return CC.load('search.json').then(function (rows) { return Array.isArray(rows) ? rows.map(function (r) { return { sport: 'college', t: r.t, s: r.s, href: r.href, w: r.w }; }) : []; }); } }
  });
  QK.seg(QK.$('#cc-level'), function (L) {
    var st = CC.state, sec = st.sec;
    var keep = { overview: 1, games: 1, standings: 1, teams: 1, scout: 1, value: 1, fantasy: 1, model: 1 };
    var to = { game: 'games', team: 'teams', player: 'scout', compare: 'scout' }[sec] || (keep[sec] ? sec : 'overview');
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
    if (meta) meta.textContent = 'Data built ' + fmt.ago(idx.updated_at) + ' (' + fmt.date(idx.updated_at) + ' ' + fmt.time(idx.updated_at) + ').';
    root.addEventListener('hashchange', render);
    render();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else setTimeout(boot, 0);

})(window);
