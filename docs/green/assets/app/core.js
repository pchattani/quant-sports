/* The Quant Green — core: routing, cached loading, golf formatting, the metric catalogue and the HTML builders the
 * pages share. Built on the shared kit (assets/qk: QK, QKC, QKL, scout.js). Older-browser rule: no optional
 * chaining, no nullish coalescing.
 *
 * Routes (hash). The section lit in the nav in brackets.
 *   #/                                     overview                                 [overview]
 *   #/fixtures[/<tour>[/<season>]]         a tour's season of events                [fixtures: Events]
 *   #/event/<id>[/<tab>]                   an event: leaderboard, forecast, course, holes, rounds   [fixtures]
 *   #/course/<id>                          a course: editions, who plays it best, holes, similar courses   [fixtures]
 *   #/standings?s=men|women&tab=ours|points   our rankings and the points ranking     [standings: Rankings]
 *   #/scout?s=men|women&view=board|chart|leaders&grp=...    the Scouting Room       [scout]
 *   #/player/<id>                          a player                                 [scout]
 *   #/value?tab=lab|courses|records        the Lab: what wins, ages, waves, courses, records   [value: Lab]
 *   #/model?tab=method|doing|tests|glossary   how it works and how we're doing      [model]
 *   #/disclaimer                           terms                                    [model]
 *
 * A page registers with GR.page(name, fn); fn(el, params) renders into el (a fresh div, detached when the viewer
 * navigates away: test el.isConnected after any await) and may return a Promise. params: the named segments plus
 * params.query. */
window.GR = (function () {
'use strict';

var QK = window.QK, fmt = QK.fmt;
/* the metric catalogue is the build's (data/spec/golf.labels.json): golf has no kit metrics file */
if (QK.spec) QK.spec.base = 'data/spec/';
var CACHE = {};
var PAGES = {};
var ROUTES = [];
var SHELL = null;
var LEAVE = [];
var TOURS = { pga: 'PGA Tour', eur: 'DP World Tour', liv: 'LIV Golf', ntw: 'Korn Ferry Tour', lpga: 'LPGA Tour' };
var TOUR_SHORT = { pga: 'PGA', eur: 'DPWT', liv: 'LIV', ntw: 'KFT', lpga: 'LPGA' };
var STREAM_OF = { pga: 'men', eur: 'men', liv: 'men', ntw: 'men', lpga: 'women' };

function addRoute(pattern, name, section) { ROUTES.push({ segs: pattern ? pattern.split('/') : [], name: name, section: section }); }
addRoute('', 'overview', 'overview');
addRoute('fixtures', 'events', 'fixtures');
addRoute('fixtures/:tour', 'events', 'fixtures');
addRoute('fixtures/:tour/:season', 'events', 'fixtures');
addRoute('event/:id', 'event', 'fixtures');
addRoute('event/:id/:tab', 'event', 'fixtures');
addRoute('course/:id', 'course', 'fixtures');
addRoute('standings', 'rankings', 'standings');
addRoute('scout', 'scout', 'scout');
addRoute('players', 'scout', 'scout');
addRoute('player/:id', 'player', 'scout');
addRoute('value', 'lab', 'value');
addRoute('model', 'model', 'model');
addRoute('disclaimer', 'disclaimer', 'model');

var TITLES = { overview: '', events: 'Events', event: 'Event', course: 'Course', rankings: 'Rankings', scout: 'Scouting Room', player: 'Player',
  lab: 'Lab', model: 'Model', disclaimer: 'Disclaimer and terms' };

function dec(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
function parse(hash) {
  var h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  var query = {};
  var qi = h.indexOf('?');
  if (qi >= 0) {
    h.slice(qi + 1).split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      query[dec(i >= 0 ? kv.slice(0, i) : kv)] = i >= 0 ? dec(kv.slice(i + 1)) : '';
    });
    h = h.slice(0, qi);
  }
  var parts = h.split('/').filter(function (s) { return s !== ''; }).map(dec);
  for (var r = 0; r < ROUTES.length; r++) {
    var R = ROUTES[r];
    if (R.segs.length !== parts.length) continue;
    var p = {}, ok = true;
    for (var i = 0; i < parts.length; i++) {
      if (R.segs[i].charAt(0) === ':') p[R.segs[i].slice(1)] = parts[i];
      else if (R.segs[i] !== parts[i]) { ok = false; break; }
    }
    if (ok) { p.query = query; return { route: R, params: p }; }
  }
  return null;
}

function load(path) {
  if (!CACHE[path]) {
    CACHE[path] = QK.fetchJSON('data/' + path, { timeout: 20000 }).catch(function (e) { delete CACHE[path]; throw e; });
  }
  return CACHE[path];
}
/* a load that never rejects: null when the file is missing (optional payloads) */
function maybe(path) { return load(path).then(function (j) { return j; }, function () { return null; }); }

// ── formatting ─────────────────────────────────────────────────────────────

function esc(s) {
  return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function isNum(x) { return typeof x === 'number' && isFinite(x); }
var NA = '<span class="gr-muted">n/a</span>';
/* a score against par: E, -12 (with a true minus), +3 */
function toPar(v) {
  if (!isNum(v)) return '';
  return v === 0 ? 'E' : v > 0 ? '+' + v : '−' + Math.abs(v);
}
function toParHTML(v) {
  if (!isNum(v)) return NA;
  return '<span class="gr-tp ' + (v < 0 ? 'under' : v > 0 ? 'over' : '') + '">' + toPar(v) + '</span>';
}
var STATUS_SHORT = { cut: 'MC', wd: 'WD', dq: 'DQ', mdf: 'MDF', dns: 'DNS' };
function position(p) {
  if (!p) return '';
  if (STATUS_SHORT[p.st]) return STATUS_SHORT[p.st];
  if (!isNum(p.pos)) return '';
  return (p.tie ? 'T' : '') + p.pos;
}
function money(v, compact) {
  if (!isNum(v) || v <= 0) return '';
  if (compact) {
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (v >= 1e3) return '$' + Math.round(v / 1e3) + 'K';
  }
  return '$' + Math.round(v).toLocaleString('en-GB');
}
function signed(v, d) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d === undefined ? 2 : d) : ''; }
function rating(v) { return isNum(v) ? signed(v, 2) : ''; }
function pct(p, d) { return isNum(p) ? fmt.pct(p, d) : ''; }
function dayMonth(iso) { return iso ? fmt.date(iso + 'T12:00:00', { day: 'numeric', month: 'short' }) : ''; }
function date(iso) {
  if (!iso) return '';
  var d = new Date(String(iso).slice(0, 10) + 'T12:00:00');
  if (isNaN(d)) return '';
  var t = dayMonth(String(iso).slice(0, 10));
  return d.getFullYear() !== new Date(QK.now()).getFullYear() ? t + ' ' + d.getFullYear() : t;
}
function dates(a, b) {
  if (!a) return '';
  var da = new Date(a + 'T12:00:00'), db = b ? new Date(b + 'T12:00:00') : null;
  if (!db || a === b) return dayMonth(a) + ' ' + da.getFullYear();
  if (da.getMonth() === db.getMonth()) return da.getDate() + '–' + dayMonth(b) + ' ' + db.getFullYear();
  return dayMonth(a) + ' – ' + dayMonth(b) + ' ' + db.getFullYear();
}
function tourName(t) { return TOURS[t] || t || ''; }
function tourShort(t) { return TOUR_SHORT[t] || t || ''; }
function playerHref(pid) { return '#/player/' + encodeURIComponent(pid); }
function playerLink(pid, name) { return '<a href="' + playerHref(pid) + '">' + esc(name || pid) + '</a>'; }
function eventLink(id, name) { return '<a href="#/event/' + encodeURIComponent(id) + '">' + esc(name || id) + '</a>'; }
function courseLink(id, name) { return '<a href="#/course/' + encodeURIComponent(id) + '">' + esc(name || id) + '</a>'; }
/* a rating behind fewer than THIN decayed rounds is flagged: the model shrinks it only lightly (models/ratings.py) */
var THIN = 20;
function thinTag(wt) { return isNum(wt) && wt < THIN ? '<span class="gr-thin" data-tip="Fewer than ' + THIN + ' recent rounds behind this rating: treat it with care">thin record</span>' : ''; }
function statusTag(st) {
  if (st === 'live') return QK.tag('Live', 'live');
  if (st === 'upcoming') return QK.tag('Upcoming');
  if (st === 'final') return QK.tag('Final');
  return '';
}
function surname(n) { return QK.surname ? QK.surname(n || '') : String(n || '').split(' ').slice(-1)[0]; }
/* a player as a kit "team" mark: the tour colour block with initials (golf has no kits) */
var TOUR_COL = { pga: '#1f4fd8', eur: '#0f7b5c', liv: '#5b2a86', ntw: '#8a5a12', lpga: '#a2244f' };
function mark(name, tour) { return { name: name || '', abbr: (fmt.initials ? fmt.initials(name || '') : String(name || '').slice(0, 2)).slice(0, 3), colour: TOUR_COL[tour] || '#3a4356' }; }

/* ── metrics: formats for the analytics ids (oddsmarkets/golf/analytics.py METRICS) ── */
var PCTM = { great: 1, poor: 1, bird: 1, bog: 1, dbl: 1, eag: 1, acc: 1, gir: 1, sand: 1, win: 1, t10: 1, cut: 1 };
function vfmt(id, v) {
  if (!isNum(v)) return '';
  if (PCTM[id]) return (v * 100).toFixed(v < 0.1 && id !== 'cut' ? 1 : 0) + '%';
  if (id === 'dist') return v.toFixed(1);
  if (id === 'ppg') return v.toFixed(3);
  if (id === 'sd') return v.toFixed(2);
  if (id === 'h3' || id === 'h4' || id === 'h5') return signed(v, 3);
  return signed(v, 2);
}
/* QKL.fmtVal codes for the same ids */
function lfmt(id) { return PCTM[id] ? 'pct1' : id === 'dist' ? '1' : id === 'ppg' ? '3' : id === 'sd' ? '2' : (id === 'h3' || id === 'h4' || id === 'h5') ? '+3' : '+2'; }

// ── HTML builders ──────────────────────────────────────────────────────────

function card(title, sub, body, o) {
  o = o || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' + (title || sub || o.right ? '<div class="qk-card-head"><div style="min-width:0"><h2 class="qk-card-title">' + esc(title) + '</h2>' +
    (sub ? '<div class="qk-card-sub">' + (o.html ? sub : esc(sub)) + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '') + '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div></section>';
}
function head(title, sub, kicker, right) {
  return QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', size: 'lg', tag: 'h1', html: true });
}
function sec(kicker, title, sub, body, right) {
  return '<section class="qk-section gr-sec">' + QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', html: true }) + body + '</section>';
}
function chart(id, h, label) { return '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px;height:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; }
function table(cols, rows, o) { return QK.tableHTML(cols, rows, Object.assign({ sticky: true }, o || {})); }
function note(html) { return '<p class="gr-note">' + html + '</p>'; }
function seg(id, items, on, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label) + '">' + items.map(function (x) {
    return '<button type="button" data-value="' + esc(x[0]) + '" aria-pressed="' + (String(x[0]) === String(on)) + '">' + esc(x[1]) + '</button>';
  }).join('') + '</div>';
}
function tabs(items, active) {
  return '<nav class="qk-tabs gr-tabs" aria-label="Views">' + items.map(function (t) {
    return '<a class="qk-tab" href="' + esc(t[2]) + '"' + (t[0] === active ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + esc(t[1]) + '</a>';
  }).join('') + '</nav>';
}
function failed(el, e) {
  el.innerHTML = QK.empty('Could not load this page', 'The data did not arrive (' + (e && e.message ? e.message : 'error') + '). Try again in a moment.');
}
function safe(fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }
function pctChip(p) {
  if (!isNum(p)) return '';
  return ' <span class="qk-pctl" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '">' + Math.round(p) + '</span>';
}
/* "as of Fri 6 Nov 14:02": the build time of a file other than the index (an event or player file), the viewer's clock */
function asOf(iso) {
  if (!iso) return '';
  var t = Date.parse(iso);
  if (!isFinite(t)) return '';
  var d = new Date(t), yr = d.getFullYear() !== new Date(QK.now()).getFullYear();
  return 'as of ' + fmt.date(t, yr ? { day: 'numeric', month: 'short', year: 'numeric' } : undefined) + ' ' + fmt.time(t);
}
/* what a chance means in plain words: 0.04 -> "about 1 time in 25" */
function oneIn(p) {
  if (!isNum(p) || p <= 0) return '';
  /* from the chance as shown (fmt.pct: one decimal under 1%), so "1%" reads "1 time in 100", not "in 95" */
  var v = p * 100, q = (v < 1 ? Math.round(v * 10) / 10 : Math.round(v)) / 100;
  if (q <= 0) q = p;
  if (q >= 0.5) return 'about ' + Math.round(q * 10) + ' times in 10';
  return 'about 1 time in ' + fmt.num(Math.max(2, Math.round(1 / q)));
}
/* an event's name without the sponsor's tail ("Austin Championship pres. by ...", "The ANNIKA driven by ...") */
function shortEvent(n) { return String(n || '').replace(/\s+(pres\.|presented|driven|powered|hosted|supported)\s+by\s+.*$/i, '') || String(n || ''); }
/* a course or event monogram for the hero's outlined face: up to three initials, words in brackets and small words out */
function code(name) {
  var w = String(name || '').replace(/\(.*?\)/g, ' ').replace(/[^A-Za-zÀ-ÿ0-9 ]/g, ' ').split(/\s+/).filter(function (x) { return x && !/^(the|at|of|de|del|la|le|and|by|pres)$/i.test(x); });
  return w.slice(0, 3).map(function (x) { return x.charAt(0).toUpperCase(); }).join('') || '?';
}
/* where a chance ranked: 1 -> "the best", 4 -> "the 4th best" */
function nthBest(k) { return k === 1 ? 'the best' : 'the ' + QK.ordinal(k) + ' best'; }
/* the rating scale a stream is measured on */
function scaleOf(stream) { return stream === 'women' ? 'an average LPGA Tour player' : 'an average PGA Tour player'; }

/* My Players: a golfer as a follow item ('green:golfm:<pid>'), its star */
function followItem(pid, name, stream) {
  return { k: 'green:' + (stream === 'women' ? 'golfw' : 'golfm') + ':' + pid, name: name || pid, abbr: mark(name).abbr, href: '#/player/' + encodeURIComponent(pid) };
}
function followStar(pid, name, stream) { return QK.followButton ? QK.followButton(followItem(pid, name, stream), { compact: true, cls: 'qk-fl-mini' }) : ''; }
function followed() {
  var list = [];
  try { list = QK.follow && QK.follow.forSite ? QK.follow.forSite('green') : []; } catch (e) { list = []; }
  return (list || []).map(function (x) { var p = String(x.k || '').split(':'); return { pid: p[2], stream: p[1] === 'golfw' ? 'women' : 'men', name: x.name }; }).filter(function (x) { return x.pid; });
}

// ── routing ────────────────────────────────────────────────────────────────

function page(name, fn) { PAGES[name] = fn; }
function onLeave(fn) { if (typeof fn === 'function') LEAVE.push(fn); }

var lastKey = '';
function render() {
  var app = document.getElementById('app');
  var m = parse();
  if (!m) { location.replace('#/'); return; }
  LEAVE.splice(0).forEach(function (fn) { try { fn(); } catch (e) { /* gone */ } });
  var name = m.route.name;
  if (SHELL) SHELL.setSection(m.route.section);
  document.title = (TITLES[name] ? TITLES[name] + ' · ' : '') + 'The Quant Green';
  var el = document.createElement('div');
  el.className = 'gr-page';
  app.innerHTML = '';
  app.appendChild(el);
  var fn = PAGES[name];
  if (!fn) { el.innerHTML = QK.empty('Not found', 'This page does not exist.'); return; }
  el.innerHTML = QK.skeleton('line', 6);
  var key = name + '/' + (m.params.id || '') + '/' + (m.params.tab || '');
  if (key !== lastKey) window.scrollTo(0, 0);
  lastKey = key;
  try {
    var r = fn(el, m.params);
    if (r && r.then) r.then(null, function (e) { if (el.isConnected) failed(el, e); if (window.console) console.error(e); });
  } catch (e) {
    failed(el, e);
    if (window.console) console.error(e);
  }
}
/* replace the address without a re-render (the Scouting Room's state) */
function setQuery(path, q) {
  try { history.replaceState(null, '', '#/' + path + (q ? '?' + q : '')); } catch (e) { /* no history API */ }
}

function searchRows() {
  return load('search.json').then(function (s) {
    var out = [];
    (s.players || []).forEach(function (p) { out.push({ t: p[1], s: 'Player' + (p[2] ? ' · ' + p[2] : ''), href: '#/player/' + encodeURIComponent(p[0]), sport: 'golf' }); });
    (s.events || []).forEach(function (e) { out.push({ t: e[1], s: e[2] + ' · ' + tourName(e[3]), href: '#/event/' + encodeURIComponent(e[0]), sport: 'golf' }); });
    (s.courses || []).forEach(function (c) { out.push({ t: c[1], s: 'Course · ' + tourName(c[2]), href: '#/course/' + encodeURIComponent(c[0]), sport: 'golf' }); });
    return out;
  });
}

function boot() {
  var m = parse();
  SHELL = QK.shell({ sport: 'golf', section: m ? m.route.section : 'overview', sections: QK.sections('golf', { scout: true, value: 'Lab' }), search: { load: searchRows } });
  window.addEventListener('hashchange', render);
  var fv = document.getElementById('first-visit-notice');
  try {
    if (fv && !localStorage.getItem('gr-fv')) {
      fv.hidden = false;
      document.getElementById('fv-dismiss').addEventListener('click', function () { fv.hidden = true; try { localStorage.setItem('gr-fv', '1'); } catch (e) { /* private mode */ } });
    }
  } catch (e) { /* no storage */ }
  render();
  /* data freshness: the index's build time, once (QK.stamp keeps the newest) */
  load('index.json').then(function (ix) {
    if (ix && ix.updated_at && QK.stamp) QK.stamp(ix.updated_at, { what: 'Leaderboards and live chances refresh through each event day; ratings, rankings and the Scouting Room after each event.' });
  }, function () { /* the page says so itself */ });
}

return {
  load: load, maybe: maybe, page: page, boot: boot, render: render, onLeave: onLeave, setQuery: setQuery, parse: parse,
  esc: esc, isNum: isNum, NA: NA, toPar: toPar, toParHTML: toParHTML, position: position, money: money, signed: signed,
  rating: rating, pct: pct, date: date, dates: dates, dayMonth: dayMonth, tourName: tourName, tourShort: tourShort, TOURS: TOURS,
  STREAM_OF: STREAM_OF, TOUR_COL: TOUR_COL, playerHref: playerHref, playerLink: playerLink, eventLink: eventLink, courseLink: courseLink,
  thinTag: thinTag, THIN: THIN, statusTag: statusTag, surname: surname, mark: mark, vfmt: vfmt, lfmt: lfmt, PCTM: PCTM,
  card: card, head: head, sec: sec, chart: chart, table: table, note: note, seg: seg, tabs: tabs, failed: failed, safe: safe,
  pctChip: pctChip, followItem: followItem, followStar: followStar, followed: followed, asOf: asOf, oneIn: oneIn, code: code, scaleOf: scaleOf, shortEvent: shortEvent, nthBest: nthBest
};
})();
