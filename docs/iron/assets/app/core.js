/* The Quant Iron — core: routing, cached loading, formatting. Older-browser rule: no optional chaining, no nullish coalescing.
 *
 *   #/                              overview
 *   #/fixtures[/<year>]             a year's meets                         [fixtures: Meets]
 *   #/event/<id>                    a meet                                 [fixtures]
 *   #/standings[?s=stream]          our rankings                           [standings: Rankings]
 *   #/players  #/player/<id>        lifters                                [players]
 *   #/model  #/disclaimer           how it works; terms                    [model]
 */
window.IR = (function () {
'use strict';

var QK = window.QK, fmt = QK.fmt;
var CACHE = {};
var PAGES = {};
var ROUTES = [];
var SHELL = null;
var STREAMS = {
  men_raw: 'Men · Raw', women_raw: 'Women · Raw',
  men_wraps: 'Men · Wraps', women_wraps: 'Women · Wraps',
  men_eq: 'Men · Equipped', women_eq: 'Women · Equipped'
};

function addRoute(pattern, name, section) { ROUTES.push({ segs: pattern ? pattern.split('/') : [], name: name, section: section }); }
addRoute('', 'overview', 'overview');
addRoute('fixtures', 'meets', 'fixtures');
addRoute('fixtures/:year', 'meets', 'fixtures');
addRoute('event/:id', 'event', 'fixtures');
addRoute('standings', 'rankings', 'standings');
addRoute('players', 'players', 'players');
addRoute('player/:id', 'player', 'players');
addRoute('model', 'model', 'model');
addRoute('disclaimer', 'disclaimer', 'model');

var TITLES = { overview: '', meets: 'Meets', event: 'Meet', rankings: 'Rankings', players: 'Lifters', player: 'Lifter',
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

function esc(s) {
  return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function isNum(x) { return typeof x === 'number' && isFinite(x); }
function kg(v) { return isNum(v) ? fmt.num(v, v >= 100 ? 0 : 1) + ' kg' : '—'; }
function dots(v) { return isNum(v) ? v.toFixed(1) : '—'; }
function rating(v) { return isNum(v) ? v.toFixed(1) : '—'; }
function dayMonth(iso) { return iso ? fmt.date(iso + 'T12:00:00', { day: 'numeric', month: 'short' }) : '—'; }
function playerLink(pid, name) { return '<a href="#/player/' + encodeURIComponent(pid) + '">' + esc(name || pid) + '</a>'; }
function eventLink(id, name) { return '<a href="#/event/' + encodeURIComponent(id) + '">' + esc(name || id) + '</a>'; }
var THIN = 8;
function thinTag(wt) { return isNum(wt) && wt < THIN ? '<span class="ir-thin" data-tip="Fewer than ' + THIN + ' recent meets behind this rating: treat it with care">thin record</span>' : ''; }
function delta(actual, pred) {
  if (!isNum(actual) || !isNum(pred)) return '';
  var d = actual - pred;
  var cls = d > 1 ? 'up' : d < -1 ? 'down' : '';
  return '<span class="ir-delta ' + cls + '">' + (d > 0 ? '+' : '') + d.toFixed(1) + '</span>';
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

function page(name, fn) { PAGES[name] = fn; }

function render() {
  var app = document.getElementById('app');
  var m = parse();
  if (!m) { location.replace('#/'); return; }
  var name = m.route.name;
  if (SHELL) SHELL.setSection(m.route.section);
  document.title = (TITLES[name] ? TITLES[name] + ' · ' : '') + 'The Quant Iron';
  var el = document.createElement('div');
  el.className = 'ir-page';
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
    (s.players || []).forEach(function (p) { out.push({ t: p[1], s: 'Lifter' + (p[2] ? ' · ' + p[2] : ''), href: '#/player/' + encodeURIComponent(p[0]), sport: 'powerlifting' }); });
    (s.events || []).forEach(function (e) { out.push({ t: e[1], s: e[2] + ' · ' + e[3], href: '#/event/' + encodeURIComponent(e[0]), sport: 'powerlifting' }); });
    return out;
  });
}

function boot() {
  var m = parse();
  SHELL = QK.shell({ sport: 'powerlifting', section: m ? m.route.section : 'overview', sections: QK.sections('powerlifting'), search: { load: searchRows } });
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
  render();
}

return {
  load: load, page: page, boot: boot, render: render, esc: esc, isNum: isNum, kg: kg, dots: dots, rating: rating,
  dayMonth: dayMonth, playerLink: playerLink, eventLink: eventLink, thinTag: thinTag, THIN: THIN, delta: delta,
  card: card, seg: seg, failed: failed, STREAMS: STREAMS
};
})();
