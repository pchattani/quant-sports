/* The Quant Scrum — core: data loading, router, shell, the men / women switch, shared helpers (window.SC).
 *
 * Routes (scope first: men | women; docs/scrum/DATA_PIPELINE.md "Front end"):
 *   #/                         the remembered scope, else men            #/<S>                 overview
 *   #/<S>/fixtures?tab=upcoming|results|year&y=YYYY                      #/<S>/match/<id>      match page
 *   #/<S>/standings?tab=nc|six|trc|rwc&view=table|chances|bracket|history
 *   #/<S>/rankings?tab=wr|ours                                           (the Rankings section: World Rugby replica, ours)
 *   #/<S>/teams   #/<S>/team/<id>   #/<S>/scout?view=board|leaders&grp=  #/<S>/player/<id>
 *   #/<S>/model?tab=method|doing|lab|records|glossary|terms              #/disclaimer
 *   #/<S>/compare?t=<a>,<b> | ?p=<a>,<b>[,<c>] | #/<S>/compare/players (player compare with defaults)                         #/<S>/progression?t=..|?p=.. (sc-compare.js)
 * Data: data/index.json, data/<S>/... (oddsmarkets/rugby/pages.py). Older-browser rule: no optional chaining, no
 * nullish coalescing. */
(function (root) {
'use strict';

var SC = root.SC = {};
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt;
SC.esc = esc; SC.isNum = isNum;
SC.SCOPES = ['men', 'women'];
SC.SNAME = { men: 'Men’s tests', women: 'Women’s tests' };
SC.SSHORT = { men: 'Men', women: 'Women' };
SC.SITE = 'The Quant Scrum';
SC.COMP = { six: 'Six Nations', trc: 'Rugby Championship', nc: 'Nations Championship', rwc: 'Rugby World Cup', test: 'Test',
  lions: 'Lions tour', tri20: 'Tri Nations', wrwc: 'Women’s World Cup', oly7m: 'Olympic sevens', oly7w: 'Olympic sevens',
  w6n: 'Women’s Six Nations', wxv: 'WXV' };
SC.POS = { P: 'Prop', H: 'Hooker', L: 'Lock', FL: 'Flanker', N8: 'Number 8', SH: 'Scrum-half', FH: 'Fly-half', C: 'Centre', W: 'Wing', FB: 'Full-back', R: 'Replacement' };
SC.GROUP = { front_row: 'Front row', lock: 'Locks', back_row: 'Back row', halves: 'Half-backs', centres: 'Centres', back_three: 'Back three' };
SC.GROUP1 = { front_row: 'front-rower', lock: 'lock', back_row: 'back-rower', halves: 'half-back', centres: 'centre', back_three: 'back-three player' };

/* ── data ────────────────────────────────────────────────────────────── */
SC.DATA = 'data/';
(function () {
  var m = /[?&]data=([^&#]+)/.exec(root.location.search || '');
  if (m && QK.localBase()) SC.DATA = decodeURIComponent(m[1]).replace(/\/?$/, '/');
})();
var CACHE = {};
SC.load = function (path) {
  if (CACHE[path]) return CACHE[path];
  var p = QK.fetchJSON(SC.DATA + path, { timeout: 20000 }).then(function (j) {
    if (j && typeof j === 'object' && !Array.isArray(j) && j.ok === undefined) j.ok = true;
    /* the live feed (QK.live, the same file the home page reads) laid over every payload: scores and finals do
       not wait for the hourly build */
    try { if (QK.live) QK.live.watch(path, 'rugby', j, { id: 'id', need: ['home', 'away'], period: 'period', clock: 'clock' }); } catch (e) { /* the built payload stands */ }
    return j;
  }, function (e) { delete CACHE[path]; return { ok: false, reason: String((e && e.message) || e), missing: true }; });
  CACHE[path] = p;
  return p;
};
SC.ok = function (d) { return !!d && typeof d === 'object' && d.ok !== false; };
SC.index = null;
SC.info = function (S) { return (SC.index && SC.index.scopes && SC.index.scopes[S]) || {}; };

/* ── teams ───────────────────────────────────────────────────────────── */
SC.team = function (S, id) { var t = (SC.info(S).teams || {})[String(id)]; return t || null; };
SC.tname = function (S, id) { var t = SC.team(S, id); return t ? t.name : (id ? 'Team ' + id : '—'); };
SC.tabbr = function (S, id) { var t = SC.team(S, id); return t ? (t.abbr || fmt.initials(t.name)) : String(id || '—'); };
SC.byName = function (S, name) {
  var ts = SC.info(S).teams || {}, ks = Object.keys(ts);
  for (var i = 0; i < ks.length; i++) if (ts[ks[i]].name === name) return ks[i];
  return null;
};
SC.traw = function (S, id) { var t = SC.team(S, id); return t && QK.color.parse(t.colour) ? t.colour : null; };
SC.talt = function (S, id) { var t = SC.team(S, id); return t && QK.color.parse(t.alt) ? t.alt : null; };
SC.tcol = function (S, id) { var c = SC.traw(S, id); return c ? QK.color.team(c) : QK.cssVar('--c-other'); };
SC.mark = function (S, id) { var t = SC.team(S, id) || { name: String(id) }; return { name: t.name, abbr: t.abbr, colour: t.colour, alt: t.alt }; };
SC.lineColours = function (S, ids) {
  var used = [], cat = (root.QKC && QKC.tokens ? QKC.tokens().cat : null) || ['#7d93ff', '#ff6a4d', '#38d2e6', '#d4ff3a', '#c78cff', '#ffb347'], k = 0;
  return (ids || []).map(function (t) {
    var c = SC.tcol(S, t);
    var clash = function (x) { return used.some(function (u) { return QK.color.distinct ? !QK.color.distinct(u, x) : u === x; }); };
    while (clash(c) && k < cat.length * 2) c = cat[k++ % cat.length];
    used.push(c);
    return c;
  });
};

/* ── hrefs ───────────────────────────────────────────────────────────── */
SC.href = function (S, sec, id, query) {
  return '#/' + S + (sec && sec !== 'overview' ? '/' + sec : '') + (id ? '/' + encodeURIComponent(id) : '') + (query ? '?' + query : '');
};
SC.teamHref = function (S, id) { return SC.href(S, 'team', id); };
SC.playerHref = function (S, id) { return SC.href(S, 'player', id); };
SC.matchHref = function (S, id) { return SC.href(S, 'match', id); };
/* My Teams: a side as a follow item ('scrum:<S>:<id>'), its star, and every side as picker rows */
SC.FOLLOW_GO = { men: 0, women: 1 };
SC.followItem = function (S, id) {
  return { k: 'scrum:' + S + ':' + id, name: SC.tname(S, id), abbr: SC.tabbr(S, id), colour: SC.traw(S, id) || '', alt: SC.talt(S, id) || '', href: '#/' + S + '/team/' + encodeURIComponent(id) };
};
SC.followStar = function (S, id, cls) { var t = SC.team(S, id); if (!t || !t.active) return ''; return QK.followButton ? QK.followButton(SC.followItem(S, id), { compact: true, cls: cls || 'qk-fl-mini' }) : ''; };
SC.followRows = function () {
  var out = [];
  SC.SCOPES.forEach(function (S) {
    var ts = SC.info(S).teams || {};
    Object.keys(ts).forEach(function (id) {
      var t = ts[id];
      if (!t || !t.name || !t.active) return;
      out.push({ sport: 'rugby', t: t.name, s: SC.SNAME[S], k: 'scrum:' + S + ':' + id, href: '#/' + S + '/team/' + id, abbr: t.abbr,
        colour: t.colour, alt: t.alt, go: SC.FOLLOW_GO[S] * 10 + (t.tier || 3) });
    });
  });
  return out;
};

/* ── formatting ──────────────────────────────────────────────────────── */
SC.f = function (v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; };
SC.pct = function (p, d) { return fmt.pct(isNum(p) ? Number(p) : null, d); };
SC.signed = function (v, d) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d === undefined ? 1 : d) : '—'; };
SC.date = function (iso, withTime) {
  if (!iso) return '—';
  var s = String(iso);
  var d = s.length === 10 ? new Date(s + 'T12:00:00Z') : new Date(s);
  if (isNaN(d)) return '—';
  var t = fmt.date(d.toISOString());
  /* a date outside the current year carries its year (a 2015 last test must not read as this October) */
  if (d.getUTCFullYear() !== new Date(QK.now()).getUTCFullYear() && !/\d{4}/.test(t)) t += ' ' + d.getUTCFullYear();
  return withTime && s.length > 10 ? t + ' ' + fmt.time(s) : t;
};
SC.year = function (iso) { return String(iso || '').slice(0, 4); };
SC.cls = function (v) { return isNum(v) ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : ''; };
SC.compName = function (k) { return SC.COMP[k] || 'Test'; };
/* a score as text: before 1891 there was no common points system, so those tests carry the result only (W–L, home
   or "us" first) */
SC.scoreText = function (a, b, ro) {
  if (!isNum(a) || !isNum(b)) return 'v';
  if (ro) return a > b ? 'W–L' : a < b ? 'L–W' : 'D–D';
  return a + '–' + b;
};
SC.posName = function (p) { return SC.POS[p] || p || ''; };

/* ── matches: the payload card -> the kit's game shape ───────────────── */
SC.side = function (S, id) {
  var t = SC.team(S, id) || {};
  return { name: t.name || ('Team ' + id), abbr: t.abbr, colour: t.colour, alt: t.alt, full: t.name, href: SC.teamHref(S, id) };
};
SC.game = function (S, c) {
  var p = c.p || [];
  var st = c.status === 'final' ? 'final' : c.status === 'live' ? 'live' : 'pre';
  return { sport: 'rugby', id: c.id, start: c.date, status: st, tba: !!c.tba,
    league: SC.compName(c.comp) + (c.neutral ? ' · Neutral' : ''), home: SC.side(S, c.home), away: SC.side(S, c.away),
    hs: isNum(c.hs) && !c.ro ? c.hs : null, as: isNum(c.as) && !c.ro ? c.as : null, p_home: isNum(p[0]) ? p[0] : null, p_draw: isNum(p[1]) ? p[1] : null,
    p_away: isNum(p[2]) ? p[2] : null, neutral: c.neutral ? true : undefined, pre_only: st === 'live' ? true : undefined,
    note: c.ro ? ((c.hs > c.as ? SC.tname(S, c.home) + ' won' : c.hs < c.as ? SC.tname(S, c.away) + ' won' : 'Drawn') + ' (no points system before 1891: the result only)') : (c.note || ''),
    href: SC.matchHref(S, c.id), ro: c.ro ? true : undefined };
};
SC.card = function (S, c, o) { o = o || {}; return QK.gameCard(SC.game(S, c), { sport: false, why: !!o.why, homeFirst: true, market: false, form: false }); };
SC.margin = function (S, c) {
  if (!c || !isNum(c.m)) return '';
  var fav = c.m >= 0 ? c.home : c.away;
  return SC.tabbr(S, fav) + ' by ' + Math.max(1, Math.round(Math.abs(c.m)));
};
/* The power board's bar (QK.powerBars parts): attack and defence when the model splits a side's rating, else the one
   rating. Our model rates a side as one number today (attack and defence are each half of it: two equal halves that
   say nothing), so the bar is the rating itself until a split model ships. */
SC.powerParts = function (rows) {
  var split = (rows || []).some(function (r) { return isNum(r.att) && isNum(r.dfn) && Math.abs(r.att - r.dfn) > 0.05; });
  return split ? { parts: [{ key: 'att', label: 'Attack', color: 'var(--c-1)' }, { key: 'dfn', label: 'Defence', color: 'var(--c-3)' }], of: function (r) { return { att: r.att, dfn: r.dfn }; } }
    : { parts: [{ key: 'rating', label: 'Points v an average side', color: 'var(--signal-deep)' }], of: function (r) { return { rating: r.rating }; } };
};
/* "How sure are we?" for a test before the start, in words that hold at the ends (a 99% favourite fails to win about
   1 test in 100, not "1 time in 10"): the note for QK.previewCard, or undefined to keep the kit's own */
SC.howSure = function (S, c, extra) {
  var p = (c && c.p) || [];
  if (!c || c.status === 'final' || !isNum(p[0]) || !isNum(p[2])) return undefined;
  var pf = Math.max(p[0], p[2]), q = 1 - pf, k10 = Math.round(q * 10);
  /* "1 time in N" with a round N (12, 15, 20, 30, 50, 100 ...): the chance is an estimate, not a count */
  var n = q > 0 ? 1 / q : Infinity, nn = n < 12 ? Math.round(n) : n < 30 ? Math.round(n / 5) * 5 : n < 100 ? Math.round(n / 10) * 10 : Math.round(n / 50) * 50;
  var freq = q >= 0.095 ? 'about ' + k10 + ' time' + (k10 === 1 ? '' : 's') + ' in 10' : q >= 0.002 ? 'about 1 time in ' + nn : 'fewer than 1 time in 500';
  return '<b>How sure are we?</b> ' + SC.pct(pf) + ' means ' + esc(SC.tname(S, p[0] >= p[2] ? c.home : c.away)) + ' fail to win a test like this ' + freq + '.' + (extra ? ' ' + extra : '');
};
SC.result = function (S, c, tid) {
  if (!isNum(c.hs)) return '';
  var home = String(c.home) === String(tid), us = home ? c.hs : c.as, th = home ? c.as : c.hs;
  return us > th ? 'W' : us < th ? 'L' : 'D';
};

/* ── UI pieces ───────────────────────────────────────────────────────── */
var U = SC.ui = {};
U.tabs = function (tabs, active) {
  return '<nav class="qk-tabs sc-tabs" aria-label="Views">' + tabs.map(function (t) {
    return '<a class="qk-tab" href="' + esc(t.href) + '"' + (t.key === active ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + esc(t.label) + '</a>';
  }).join('') + '</nav>';
};
U.tab = function (params, keys, dflt) { var t = (params.query || {}).tab; return keys.indexOf(t) >= 0 ? t : dflt; };
U.head = function (title, sub, kicker, right) {
  return QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', size: 'lg', tag: 'h1', html: true, cls: 'sc-sh' });
};
U.sec = function (kicker, title, sub, body, right, o) {
  o = o || {};
  return '<section class="qk-section sc-sec' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' +
    QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', html: true }) + body + '</section>';
};
U.card = function (title, sub, body, o) {
  o = o || {};
  var head = title || sub || o.right ? '<div class="qk-card-head"><div><h2 class="qk-card-title">' + esc(title) + '</h2>' + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '';
  return '<section class="qk-card sc-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' + head +
    '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' + (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
U.chart = function (id, h, label) { return '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; };
U.note = function (html) { return '<p class="sc-note">' + html + '</p>'; };
U.link = function (href, text) { return '<a class="sc-link" href="' + esc(href) + '">' + esc(text) + ' →</a>'; };
U.teamEnt = function (S, id, o) {
  o = o || {};
  if (!id) return '<span class="qk-muted">—</span>';
  var t = SC.team(S, id) || { name: 'Team ' + id };
  var tag = t.active ? 'a' : 'span';   /* a side with no test in ten years has no team page */
  return '<' + tag + ' class="sc-ent"' + (t.active ? ' href="' + esc(SC.teamHref(S, id)) + '"' : '') + '>' + QK.teamMark({ name: t.name, abbr: t.abbr, colour: t.colour }, 'sm') +
    '<span class="nm">' + esc(o.abbr ? (t.abbr || t.name) : t.name) + '</span>' + (o.sub ? '<span class="sb">' + esc(o.sub) + '</span>' : '') + '</' + tag + '>';
};
U.playerEnt = function (S, pid, name, tid, sub) {
  return '<a class="sc-ent" href="' + esc(SC.playerHref(S, pid)) + '">' + (tid ? QK.teamMark(SC.mark(S, tid), 'sm') : '') +
    '<span class="nm">' + esc(name || ('Player ' + pid)) + '</span>' + (sub ? '<span class="sb">' + esc(sub) + '</span>' : '') + '</a>';
};
U.table = function (cols, rows, o) { return QK.tableHTML(cols, rows, Object.assign({ sticky: true }, o || {})); };
U.wire = function (el) { QK.sortable(el); };
U.alive = function (el) { return !!el && el.isConnected; };
U.missing = function (what, d) {
  return QK.empty(what + ' is not available yet', d && d.reason ? String(d.reason) : 'It has not been built yet.');
};
U.form = function (f) { return QK.formDots ? QK.formDots(f, (f || '').length) : esc(f || ''); };
U.heat = function (p, d) {
  if (!isNum(p)) return { v: -1, html: '<span class="qk-muted">—</span>' };
  var a = Math.round(Math.min(1, Math.max(0, p)) * 60);
  return { v: p, html: SC.pct(p, d), style: 'background:color-mix(in srgb, var(--signal) ' + a + '%, transparent)' + (a > 42 ? ';color:var(--ink-1);font-weight:600' : '') };
};

/* ── router ──────────────────────────────────────────────────────────── */
var ROUTES = {};
SC.route = function (name, fn) { ROUTES[name] = fn; };
SC.state = { S: null, sec: 'overview' };
var SEC_OF = { overview: 'overview', fixtures: 'fixtures', match: 'fixtures', standings: 'standings', teams: 'teams', team: 'teams',
  scout: 'scout', player: 'scout', rankings: 'value', model: 'model', disclaimer: 'model', compare: 'teams', progression: 'teams' };
var LEAVE = [];
SC.onLeave = function (fn) { if (typeof fn === 'function') LEAVE.push(fn); };
var shell = null;
SC.parse = function (hash) {
  var h = String(hash || '').replace(/^#\/?/, '');
  var qi = h.indexOf('?'), qs = qi >= 0 ? h.slice(qi + 1) : '', path = qi >= 0 ? h.slice(0, qi) : h;
  var query = {};
  qs.split('&').forEach(function (kv) { if (!kv) return; var p = kv.split('='); query[decodeURIComponent(p[0])] = decodeURIComponent(p.slice(1).join('=') || ''); });
  var parts = path.split('/').filter(function (x) { return x !== ''; }).map(decodeURIComponent);
  var r = { S: null, sec: 'overview', id: null, query: query };
  if (parts[0] === 'disclaimer') { r.sec = 'disclaimer'; return r; }
  if (SC.SCOPES.indexOf(parts[0]) >= 0) {
    r.S = parts.shift();
    if (parts[0]) r.sec = parts[0];
    if (parts[1]) r.id = parts[1];
  }
  return r;
};
SC.defaultScope = function () {
  var saved = QK.store('qs-scope');
  if (SC.SCOPES.indexOf(saved) >= 0 && SC.info(saved).ok !== false) return saved;
  return 'men';
};
function sectionHrefs(S) {
  var map = { overview: '', fixtures: 'fixtures', standings: 'standings', teams: 'teams', scout: 'scout', value: 'rankings', model: 'model' };
  QK.$$('.qk-secnav a[data-sec]').forEach(function (a) { var k = a.getAttribute('data-sec'); if (k in map) a.setAttribute('href', '#/' + S + (map[k] ? '/' + map[k] : '')); });
}
function paintCtx(S) {
  QK.$$('#sc-scope button').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-value') === S ? 'true' : 'false'); });
}
function render() {
  var r = SC.parse(root.location.hash);
  if (r.sec === 'disclaimer') {
    shell.setSection('model');
    var t = document.getElementById('disclaimer-template');
    QK.$('#app').innerHTML = '<div class="sc-page">' + U.head('Disclaimer and terms', '', SC.SITE) + (t ? t.innerHTML : '') + '</div>';
    root.scrollTo(0, 0);
    return;
  }
  if (!r.S) { root.location.replace('#/' + SC.defaultScope()); return; }
  var S = r.S;
  LEAVE.splice(0).forEach(function (fn) { try { fn(); } catch (e) { /* gone */ } });
  SC.state = { S: S, sec: r.sec, id: r.id, query: r.query };
  QK.store('qs-scope', S);
  document.documentElement.setAttribute('data-scope', S);
  sectionHrefs(S); paintCtx(S);
  /* compare and progression sit under Teams, or under the Scouting Room when they show players (?p= / view=players /
     #/<S>/compare/players) */
  var pl = (r.sec === 'compare' || r.sec === 'progression') && ((r.query.p !== undefined && r.query.t === undefined) || r.query.view === 'players' || r.id === 'players');
  shell.setSection(pl ? 'scout' : (SEC_OF[r.sec] || 'overview'));
  var el = QK.$('#app');
  el.innerHTML = '<div class="sc-page"></div>';
  var page = el.firstChild;
  if (SC.info(S).ok === false && r.sec !== 'model') {
    page.innerHTML = U.head(SC.SNAME[S], '', SC.SITE) + QK.empty(SC.SNAME[S] + ' are not available yet', SC.info(S).reason || 'Its payloads have not been built.');
    return;
  }
  var fn = ROUTES[r.sec];
  if (!fn) { page.innerHTML = QK.empty('Page not found', 'Try the sections above.'); return; }
  var prevKey = render.key, key = S + '/' + r.sec + '/' + (r.id || '');
  render.key = key;
  if (prevKey !== key) root.scrollTo(0, 0);
  try {
    var pr = fn(page, { S: S, id: r.id, query: r.query, sec: r.sec });
    if (pr && pr.then) pr.then(null, function (e) { if (root.console) console.error(e); page.innerHTML = QK.empty('This page could not be shown', String(e && e.message || e)); });
  } catch (e) { if (root.console) console.error(e); page.innerHTML = QK.empty('This page could not be shown', String(e && e.message || e)); }
  document.title = (r.sec === 'overview' ? SC.SSHORT[S] + ' · ' : '') + SC.SITE;
}
SC.go = function (h) { if (root.location.hash === h) render(); else root.location.hash = h; };
SC.rerender = render;

function boot() {
  var ctx = '<div class="sc-ctx"><div class="qk-seg" id="sc-scope" role="group" aria-label="Men or women">' + SC.SCOPES.map(function (S) {
    return '<button type="button" data-value="' + S + '" aria-pressed="false" title="' + esc(SC.SNAME[S]) + '">' + esc(SC.SSHORT[S]) + '</button>';
  }).join('') + '</div></div>';
  shell = QK.shell({
    sport: 'rugby', section: 'overview', ctx: ctx,
    sections: QK.sections('rugby', { scout: true }),
    search: { load: function () { return SC.load('search.json').then(function (rows) { return Array.isArray(rows) ? rows.map(function (r) { return { sport: 'rugby', t: r.t, s: r.s, href: r.href, w: r.w }; }) : []; }); } }
  });
  QK.seg(QK.$('#sc-scope'), function (S) {
    var st = SC.state, sec = st.sec;
    var keep = { overview: 1, fixtures: 1, standings: 1, teams: 1, scout: 1, rankings: 1, model: 1, compare: 1, progression: 1 };
    var to = { match: 'fixtures', team: 'teams', player: 'scout' }[sec] || (keep[sec] ? sec : 'overview');
    /* a player compare or progression stays on players (the ids are per scope, so the defaults fill in) */
    var q0 = st.query || {}, plv = (to === 'compare' || to === 'progression') && ((q0.p !== undefined && q0.t === undefined) || q0.view === 'players' || st.id === 'players');
    SC.go('#/' + S + (to !== 'overview' ? '/' + to : '') + (plv ? '?view=players' : ''));
  });
  QK.$('#app').innerHTML = QK.skeleton('lines', 6);
  SC.load('index.json').then(function (idx) {
    if (!SC.ok(idx) || !idx.scopes) {
      QK.$('#app').innerHTML = QK.empty('The site data did not load', (idx && idx.reason) || 'index.json is missing.');
      return;
    }
    SC.index = idx;
    /* a source switched off at build time (index.json "sources") takes its credit off the footer and the terms */
    Object.keys(idx.sources || {}).forEach(function (k) { if (idx.sources[k] === false) document.documentElement.setAttribute('data-nosrc-' + k, ''); });
    var meta = QK.$('#meta-line');
    if (meta) meta.textContent = 'Data built ' + fmt.ago(idx.updated_at) + ' (' + fmt.date(idx.updated_at) + ' ' + fmt.time(idx.updated_at) + '). ' + (idx.credit || '');
    /* the data-freshness line (kit QK.stamp): index.json's build time, the file every page loads first */
    if (QK.stamp && idx.updated_at) QK.stamp(idx.updated_at, { what: 'The site rebuilds about once an hour: results, ratings, our chances and every page. Live scores come from a separate feed while tests are on.' });
    root.addEventListener('hashchange', render);
    if (QK.live) QK.live.attach(function () { if (!document.hidden && /^(overview|fixtures|match)$/.test((SC.state && SC.state.sec) || 'overview')) render(); });
    render();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else setTimeout(boot, 0);

})(window);
