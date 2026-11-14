/* The Quant Iron — core: routing, cached loading, formatting, the page helpers and My Teams for lifters.
 * Rebuilt 6 Nov 2026 to the sister sites' depth (the Scrum's sc-core.js is the pattern). Older-browser rule: no
 * optional chaining, no nullish coalescing.
 *
 *   #/                              overview
 *   #/fixtures[/<year>]             a year's meets                       [Meets]
 *   #/event/<id>                    a meet                               [Meets]
 *   #/standings[?s=&cls=&t=]        our rankings                         [Rankings]
 *   #/power[?l=<stream>&g=<class>]  the power rankings                   [Power Rankings]
 *   #/scout[?s=&grp=&view=...]      the Scouting Room                    [Scouting Room]
 *   #/player/<id>                   a lifter                             [Scouting Room]
 *   #/lab[?tab=]                    the Lab                              [Lab]
 *   #/model[?tab=]                  how it works, how we're doing, records, glossary, terms
 *   #/disclaimer
 */
window.IR = (function () {
'use strict';

var QK = window.QK, fmt = QK.fmt, esc = QK.esc, isNum = QK.isNum;
var CACHE = {};
var PAGES = {};
var ROUTES = [];
var SHELL = null;
var LEAVE = [];
var SITE = 'The Quant Iron';
var STREAMS = {
  men_raw: 'Men · Raw', women_raw: 'Women · Raw',
  men_wraps: 'Men · Wraps', women_wraps: 'Women · Wraps',
  men_eq: 'Men · Equipped', women_eq: 'Women · Equipped'
};
var STREAM_KEYS = ['men_raw', 'women_raw', 'men_wraps', 'women_wraps', 'men_eq', 'women_eq'];
var CLASSES = { M: ['59', '66', '74', '83', '93', '105', '120', '120+'], F: ['47', '52', '57', '63', '69', '76', '84', '84+'] };

function addRoute(pattern, name, section) { ROUTES.push({ segs: pattern ? pattern.split('/') : [], name: name, section: section }); }
addRoute('', 'overview', 'overview');
addRoute('fixtures', 'meets', 'fixtures');
addRoute('fixtures/:year', 'meets', 'fixtures');
addRoute('event/:id', 'event', 'fixtures');
addRoute('standings', 'rankings', 'standings');
addRoute('power', 'power', 'power');
addRoute('scout', 'scout', 'scout');
addRoute('players', 'scout', 'scout');
addRoute('player/:id', 'player', 'scout');
addRoute('lab', 'lab', 'value');
addRoute('value', 'lab', 'value');
addRoute('model', 'model', 'model');
addRoute('records', 'records', 'model');
addRoute('disclaimer', 'disclaimer', 'model');

var TITLES = { overview: '', meets: 'Meets', event: 'Meet', rankings: 'Rankings', power: 'Power rankings', scout: 'Scouting Room', player: 'Lifter',
  lab: 'Lab', model: 'Model', records: 'Records', disclaimer: 'Disclaimer and terms' };

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
    CACHE[path] = QK.fetchJSON('data/' + path, { timeout: 25000 }).catch(function (e) { delete CACHE[path]; throw e; });
  }
  return CACHE[path];
}

/* ── formatting ─────────────────────────────────────────────────────── */
function kg(v) { return isNum(v) ? fmt.num(v, v % 1 ? 1 : 0) + ' kg' : '–'; }
function kgn(v) { return isNum(v) ? fmt.num(v, v % 1 ? 1 : 0) : '–'; }
function dots(v) { return isNum(v) ? v.toFixed(1) : '–'; }
function signed(v, d) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d === undefined ? 1 : d) : '–'; }
function pct(p, d) { return isNum(p) ? (p * 100).toFixed(d || 0) + '%' : '–'; }
function pctv(v, d) { return isNum(v) ? v.toFixed(d === undefined ? 0 : d) + '%' : '–'; }
function cls(v) { return isNum(v) ? (v > 0.05 ? 'pos' : v < -0.05 ? 'neg' : '') : ''; }
function year(iso) { return iso ? String(iso).slice(0, 4) : ''; }
function date(iso) {
  if (!iso) return '–';
  var y = String(iso).slice(0, 4), now = new Date(QK.now()).getUTCFullYear();
  return fmt.date(String(iso).slice(0, 10) + 'T12:00:00', y === String(now) ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' });
}
function className(c, sex) { return c ? (String(c).slice(-1) === '+' ? c + ' kg' : c + ' kg') : '–'; }
function sexOf(stream) { return String(stream || '').indexOf('women') === 0 ? 'F' : 'M'; }
function playerHref(pid) { return '#/player/' + encodeURIComponent(pid); }
function eventHref(id) { return '#/event/' + encodeURIComponent(id); }
function playerLink(pid, name, pg) { return pg === false ? esc(name || pid) : '<a href="' + playerHref(pid) + '">' + esc(name || pid) + '</a>'; }
function eventLink(id, name) { return '<a href="' + eventHref(id) + '">' + esc(name || id) + '</a>'; }
var THIN = 5;
function thinTag(n) { return isNum(n) && n < THIN ? '<span class="ir-thin" data-tip="Fewer than ' + THIN + ' scored full-power meets behind this rating: read it with care">thin record</span>' : ''; }
function delta(actual, pred) {
  if (!isNum(actual) || !isNum(pred)) return '';
  var d = actual - pred;
  return '<span class="ir-delta ' + cls(d) + '">' + signed(d, 1) + '</span>';
}
function attempts(a) {
  /* nine attempts (negative = missed) as three groups of chips */
  if (!a || !a.some(isNum)) return '<span class="qk-muted">not reported</span>';
  var out = '';
  for (var g = 0; g < 3; g++) {
    out += '<span class="ir-att">';
    for (var i = 0; i < 3; i++) {
      var v = a[g * 3 + i];
      out += isNum(v) && v !== 0 ? '<i class="' + (v > 0 ? 'ok' : 'x') + '" title="' + (v > 0 ? 'Made ' : 'Missed ') + Math.abs(v) + ' kg">' + fmt.num(Math.abs(v), Math.abs(v) % 1 ? 1 : 0) + '</i>' : '<i class="na">–</i>';
    }
    out += '</span>';
  }
  return '<span class="ir-atts">' + out + '</span>';
}
function col(k) { return QK.cssVar(typeof k === 'number' ? '--c-' + k : '--' + k) || '#8a93a6'; }
function form(f) { return f ? QK.formDots(f, f.length) : ''; }

/* ── data freshness: build.json (tiny) carries the build time of every file in data/; QK.stamp shows it at the
 * right of the section bar and in the footer, and asof() writes the "as of" for cards that read a player or meet
 * file rather than the index ─────────────────────────────────────────── */
var BUILT = null;
var STAMP_WHAT = 'The site checks the OpenPowerlifting archive (published weekly) and rebuilds when it changes.';
function stamp(iso) { try { if (iso && QK.stamp) QK.stamp(iso, { what: STAMP_WHAT, stale: 24 * 8 }); } catch (e) { /* the page stands without it */ } }
function built() {
  return load('build.json').then(function (b) { BUILT = b || null; if (b) stamp(b.updated_at); return BUILT; }, function () { return null; });
}
function asof() {
  var t = BUILT && BUILT.updated_at;
  return t ? 'as of ' + fmt.date(t, { day: 'numeric', month: 'short' }) + ' ' + fmt.time(t) : '';
}

/* ── page helpers (the Scrum's SC.ui) ───────────────────────────────── */
var U = {};
U.head = function (title, sub, kicker, right) {
  return QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', size: 'lg', tag: 'h1', html: true, cls: 'ir-sh' });
};
U.sec = function (kicker, title, sub, body, right, o) {
  o = o || {};
  return '<section class="qk-section ir-sec' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' +
    QK.sectionHead({ kicker: kicker || '', title: esc(title), sub: sub || '', actions: right || '', html: true }) + body + '</section>';
};
U.card = function (title, sub, body, o) {
  o = o || {};
  var head = title || sub || o.right ? '<div class="qk-card-head"><div style="min-width:0"><h2 class="qk-card-title">' + esc(title) + '</h2>' + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '';
  return '<section class="qk-card ir-card' + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' + head +
    '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '">' + body + '</div>' + (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
};
U.chart = function (id, h, label) { return '<div id="' + esc(id) + '" class="qk-chart" style="--h:' + (h || 280) + 'px;height:' + (h || 280) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; };
U.note = function (html) { return '<p class="ir-note">' + html + '</p>'; };
U.table = function (cols, rows, o) { return QK.tableHTML(cols, rows, Object.assign({ sticky: true }, o || {})); };
U.wire = function (el) { QK.sortable(el); };
U.alive = function (el) { return !!el && el.isConnected; };
U.tabs = function (tabs, active) {
  return '<nav class="qk-tabs ir-tabs" aria-label="Views">' + tabs.map(function (t) {
    return '<a class="qk-tab" href="' + esc(t.href) + '"' + (t.key === active ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '>' + esc(t.label) + '</a>';
  }).join('') + '</nav>';
};
U.seg = function (id, items, on, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label) + '">' + items.map(function (x) {
    return '<button type="button" data-value="' + esc(x[0]) + '" aria-pressed="' + (String(x[0]) === String(on)) + '">' + esc(x[1]) + '</button>';
  }).join('') + '</div>';
};
U.streamSel = function (id, on, label) {
  return '<select class="qk-select" id="' + esc(id) + '" aria-label="' + esc(label || 'Stream') + '">' + STREAM_KEYS.map(function (k) {
    return '<option value="' + k + '"' + (k === on ? ' selected' : '') + '>' + esc(STREAMS[k]) + '</option>';
  }).join('') + '</select>';
};
U.missing = function (what, e) { return QK.empty(what + ' did not load', 'The data did not arrive (' + (e && e.message ? e.message : 'error') + '). Try again in a moment.'); };

/* ── My Teams: a lifter as a follow item ('iron:lifter:<pid>') ──────── */
function followItem(pid, name, cc) { return { k: 'iron:lifter:' + pid, name: name || pid, abbr: cc ? String(cc).slice(0, 3).toUpperCase() : '', href: playerHref(pid) }; }
function followStar(pid, name, cc, o) { return QK.followButton ? QK.followButton(followItem(pid, name, cc), Object.assign({ compact: true, cls: 'qk-fl-mini' }, o || {})) : ''; }
function followRows() {
  return load('search.json').then(function (s) {
    return (s.players || []).map(function (p, i) { return { sport: 'powerlifting', t: p[1], s: 'Lifter' + (p[2] ? ' · ' + p[2] : ''), k: 'iron:lifter:' + p[0], href: playerHref(p[0]), abbr: p[2] || '', go: i }; });
  });
}

/* ── router ─────────────────────────────────────────────────────────── */
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
  document.title = (TITLES[name] ? TITLES[name] + ' · ' : '') + SITE;
  var el = document.createElement('div');
  el.className = 'ir-page';
  app.innerHTML = '';
  app.appendChild(el);
  var fn = PAGES[name];
  if (!fn) { el.innerHTML = QK.empty('Not found', 'This page does not exist.'); return; }
  el.innerHTML = QK.skeleton('lines', 6);
  var key = name + '/' + (m.params.id || m.params.year || '');
  if (key !== lastKey) window.scrollTo(0, 0);
  lastKey = key;
  try {
    var r = fn(el, m.params);
    if (r && r.then) r.then(null, function (e) { if (el.isConnected) el.innerHTML = U.missing('This page', e); if (window.console) console.error(e); });
  } catch (e) {
    el.innerHTML = U.missing('This page', e);
    if (window.console) console.error(e);
  }
}

function searchRows() {
  return load('search.json').then(function (s) {
    var out = [];
    (s.players || []).forEach(function (p, i) { out.push({ t: p[1], s: 'Lifter' + (p[2] ? ' · ' + p[2] : ''), href: playerHref(p[0]), sport: 'powerlifting', w: 6000 - i }); });
    (s.events || []).forEach(function (e) { out.push({ t: e[1], s: e[2] + ' · ' + e[3], href: eventHref(e[0]), sport: 'powerlifting' }); });
    out.unshift({ t: 'Power rankings: lifters and weight classes', s: 'Page', href: '#/power', sport: 'powerlifting' });
    return out;
  });
}

/* My Teams cards: the kit's card registry does not list Iron yet (the hub still hides it), so the site registers its
 * own scope at boot: QK.follow.hasCards reads QK.FOLLOW_CARDS at call time, and every lifter page has a card at
 * data/follow/lifter/<id>.json (pages.py _follow). */
function registerCards() {
  try {
    if (QK.FOLLOW_CARDS && !QK.FOLLOW_CARDS.iron) QK.FOLLOW_CARDS.iron = ['lifter'];
    if (QK.FOLLOW_SCOPES && !QK.FOLLOW_SCOPES.lifter) QK.FOLLOW_SCOPES.lifter = 'Lifter';
    /* the metric catalogue (powerlifting.labels.json) is written by the build into data/ (pages.py _labels) */
    if (QK.spec) QK.spec.base = 'data/';
  } catch (e) { /* an older kit: follows stay chips */ }
}

function boot() {
  registerCards();
  var m = parse();
  var secs = QK.sections('powerlifting', { scout: true, value: 'Lab', power: true }).map(function (s) {
    if (s.key === 'value') s.href = '#/lab';
    if (s.key === 'power') s.href = '#/power';
    return s;
  });
  SHELL = QK.shell({ sport: 'powerlifting', section: m ? m.route.section : 'overview', sections: secs, search: { load: searchRows } });
  var foot = document.getElementById('qk-footer');
  if (foot && !foot.querySelector('.ir-credit')) {
    var c = document.createElement('p');
    c.className = 'ir-credit';
    c.innerHTML = 'This page uses data from the OpenPowerlifting project, <a href="https://www.openpowerlifting.org" target="_blank" rel="noopener">https://www.openpowerlifting.org</a>. You may download a copy of the data at <a href="https://data.openpowerlifting.org" target="_blank" rel="noopener">https://data.openpowerlifting.org</a>.';
    foot.appendChild(c);
  }
  window.addEventListener('hashchange', render);
  var fv = document.getElementById('first-visit-notice');
  try {
    if (fv && !localStorage.getItem('ir-fv')) {
      fv.hidden = false;
      document.getElementById('fv-dismiss').addEventListener('click', function () { fv.hidden = true; try { localStorage.setItem('ir-fv', '1'); } catch (e) { /* private mode */ } });
    }
  } catch (e) { /* no storage */ }
  built();
  render();
}

return {
  load: load, page: page, boot: boot, render: render, onLeave: onLeave, parse: parse, esc: esc, isNum: isNum, kg: kg, kgn: kgn, dots: dots,
  signed: signed, pct: pct, pctv: pctv, cls: cls, year: year, date: date, className: className, sexOf: sexOf,
  playerHref: playerHref, eventHref: eventHref, playerLink: playerLink, eventLink: eventLink, thinTag: thinTag, THIN: THIN,
  delta: delta, attempts: attempts, form: form, col: col, ui: U, STREAMS: STREAMS, STREAM_KEYS: STREAM_KEYS, CLASSES: CLASSES, SITE: SITE,
  followItem: followItem, followStar: followStar, followRows: followRows, stamp: stamp, built: built, asof: asof
};
})();
