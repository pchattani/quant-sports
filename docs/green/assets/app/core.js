/* The Quant Green — core: routing, cached loading, golf formatting and the small HTML builders the pages share.
 * Built on the shared kit (assets/qk: window.QK, window.QKC). Older-browser rule: no optional chaining, no nullish
 * coalescing.
 *
 * Routes (hash). Section in brackets is the item lit in the section nav.
 *   #/                                     overview                       [overview]
 *   #/fixtures[/<tour>[/<season>]]         a tour's season of events      [fixtures: Events]
 *   #/event/<id>[/<tab>]                   an event: leaderboard, forecast, holes, rounds   [fixtures]
 *   #/standings[?s=men|women]              our rankings                   [standings: Rankings]
 *   #/players  #/player/<id>               the player list, a player      [players]
 *   #/model  #/disclaimer                  how it works and how we're doing; terms   [model]
 *
 * A page registers with GR.page(name, fn); fn(el, params) renders into el (a fresh div, detached when the viewer
 * navigates away: test el.isConnected after any await) and may return a Promise. params: the named segments plus
 * params.query. */
window.GR = (function () {
'use strict';

var QK = window.QK, fmt = QK.fmt;
var CACHE = {};
var PAGES = {};
var ROUTES = [];
var SHELL = null;
var TOURS = { pga: 'PGA Tour', eur: 'DP World Tour', liv: 'LIV Golf', lpga: 'LPGA Tour' };
var TOUR_SHORT = { pga: 'PGA', eur: 'DPWT', liv: 'LIV', lpga: 'LPGA' };

function addRoute(pattern, name, section) { ROUTES.push({ segs: pattern ? pattern.split('/') : [], name: name, section: section }); }
addRoute('', 'overview', 'overview');
addRoute('fixtures', 'events', 'fixtures');
addRoute('fixtures/:tour', 'events', 'fixtures');
addRoute('fixtures/:tour/:season', 'events', 'fixtures');
addRoute('event/:id', 'event', 'fixtures');
addRoute('event/:id/:tab', 'event', 'fixtures');
addRoute('standings', 'rankings', 'standings');
addRoute('players', 'players', 'players');
addRoute('player/:id', 'player', 'players');
addRoute('model', 'model', 'model');
addRoute('disclaimer', 'disclaimer', 'model');

var TITLES = { overview: '', events: 'Events', event: 'Event', rankings: 'Rankings', players: 'Players', player: 'Player',
  model: 'Model', disclaimer: 'Disclaimer and terms' };

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

// ── formatting ─────────────────────────────────────────────────────────────

function esc(s) {
  return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function isNum(x) { return typeof x === 'number' && isFinite(x); }
/* a score against par: E, -12 (with a true minus), +3 */
function toPar(v) {
  if (!isNum(v)) return '—';
  return v === 0 ? 'E' : v > 0 ? '+' + v : '−' + Math.abs(v);
}
function toParHTML(v) {
  if (!isNum(v)) return '<span class="gr-muted">—</span>';
  return '<span class="gr-tp ' + (v < 0 ? 'under' : v > 0 ? 'over' : '') + '">' + toPar(v) + '</span>';
}
var STATUS_SHORT = { cut: 'MC', wd: 'WD', dq: 'DQ', mdf: 'MDF', dns: 'DNS' };
function position(p) {
  if (!p) return '—';
  if (STATUS_SHORT[p.st]) return STATUS_SHORT[p.st];
  if (!isNum(p.pos)) return '—';
  return (p.tie ? 'T' : '') + p.pos;
}
function money(v, compact) {
  if (!isNum(v) || v <= 0) return '—';
  if (compact) {
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (v >= 1e3) return '$' + Math.round(v / 1e3) + 'K';
  }
  return '$' + Math.round(v).toLocaleString('en-GB');
}
function rating(v) { return isNum(v) ? fmt.signed(v, 2) : '—'; }
function pct(p) { return isNum(p) ? fmt.pct(p) : '—'; }
function dayMonth(iso) { return iso ? fmt.date(iso + 'T12:00:00', { day: 'numeric', month: 'short' }) : '—'; }
function dates(a, b) {
  if (!a) return '—';
  var da = new Date(a + 'T12:00:00'), db = b ? new Date(b + 'T12:00:00') : null;
  if (!db || a === b) return dayMonth(a) + ' ' + da.getFullYear();
  if (da.getMonth() === db.getMonth()) return da.getDate() + '–' + dayMonth(b) + ' ' + db.getFullYear();
  return dayMonth(a) + ' – ' + dayMonth(b) + ' ' + db.getFullYear();
}
function tourName(t) { return TOURS[t] || t; }
function tourShort(t) { return TOUR_SHORT[t] || t; }
function playerLink(pid, name) { return '<a href="#/player/' + encodeURIComponent(pid) + '">' + esc(name || pid) + '</a>'; }
function eventLink(id, name) { return '<a href="#/event/' + encodeURIComponent(id) + '">' + esc(name || id) + '</a>'; }
/* a rating behind fewer than THIN decayed rounds is flagged: the model shrinks it only lightly (models/ratings.py) */
var THIN = 20;
function thinTag(wt) { return isNum(wt) && wt < THIN ? '<span class="gr-thin" data-tip="Fewer than ' + THIN + ' recent rounds behind this rating: treat it with care">thin record</span>' : ''; }
function statusTag(st) {
  if (st === 'live') return QK.tag('Live', 'live');
  if (st === 'upcoming') return QK.tag('Upcoming');
  if (st === 'final') return QK.tag('Final');
  return '';
}

function card(title, sub, body, o) {
  o = o || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + (o.html ? sub : esc(sub)) + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div></section>';
}
function seg(id, items, on, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label) + '">' + items.map(function (x) {
    return '<button type="button" data-value="' + esc(x[0]) + '" aria-pressed="' + (String(x[0]) === String(on)) + '">' + esc(x[1]) + '</button>';
  }).join('') + '</div>';
}
function failed(el, e) {
  el.innerHTML = QK.empty('Could not load this page', 'The data did not arrive (' + (e && e.message ? e.message : 'error') + '). Try again in a moment.');
}

// ── routing ────────────────────────────────────────────────────────────────

function page(name, fn) { PAGES[name] = fn; }

function render() {
  var app = document.getElementById('app');
  var m = parse();
  if (!m) { location.replace('#/'); return; }
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
  try {
    var r = fn(el, m.params);
    if (r && r.then) r.then(null, function (e) { if (el.isConnected) failed(el, e); if (window.console) console.error(e); });
  } catch (e) {
    failed(el, e);
    if (window.console) console.error(e);
  }
  window.scrollTo(0, 0);
}

function searchRows() {
  return load('search.json').then(function (s) {
    var out = [];
    (s.players || []).forEach(function (p) { out.push({ t: p[1], s: 'Player' + (p[2] ? ' · ' + p[2] : ''), href: '#/player/' + encodeURIComponent(p[0]), sport: 'golf' }); });
    (s.events || []).forEach(function (e) { out.push({ t: e[1], s: e[2] + ' · ' + tourName(e[3]), href: '#/event/' + encodeURIComponent(e[0]), sport: 'golf' }); });
    return out;
  });
}

function boot() {
  var m = parse();
  SHELL = QK.shell({ sport: 'golf', section: m ? m.route.section : 'overview', sections: QK.sections('golf'), search: { load: searchRows } });
  window.addEventListener('hashchange', render);
  var fv = document.getElementById('first-visit-notice');
  try {
    if (fv && !localStorage.getItem('gr-fv')) {
      fv.hidden = false;
      document.getElementById('fv-dismiss').addEventListener('click', function () { fv.hidden = true; try { localStorage.setItem('gr-fv', '1'); } catch (e) { /* private mode */ } });
    }
  } catch (e) { /* no storage */ }
  render();
}

return {
  load: load, page: page, boot: boot, render: render, esc: esc, isNum: isNum, toPar: toPar, toParHTML: toParHTML,
  position: position, money: money, rating: rating, pct: pct, dates: dates, dayMonth: dayMonth, tourName: tourName,
  tourShort: tourShort, TOURS: TOURS, playerLink: playerLink, eventLink: eventLink, thinTag: thinTag, THIN: THIN,
  statusTag: statusTag, card: card, seg: seg, failed: failed
};
})();
