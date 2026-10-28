/* The Quant — progression pages (round 6): the player page's Progression tab and the Compare progression page, laid out
 * the same way on Gridiron, Footballer, Campus, Ace and Paddock (the Bullpen and Rink adapters' layout). A page module
 * on top of the kit's assets/qk/progression.js (QKC.progression, QK.progressionGrid, QK.progressionDeltas,
 * QK.careerArc, QK.compareProgression, QK.prog.ref); each site's adapter turns its player files into the kit's shapes
 * (P, M) and calls:
 *
 *   QPV.metrics(keys, cat, o)   [M] from the deep set's ids and the spec catalogue (QK.spec): label, unit, direction
 *                               (style metrics neutral), the "Our model" tag, the tooltip, head (a headline metric of the
 *                               group, o.head [ids]); o.fmt(id, unit) a site format; o.extra [[id, label, unit, dir]]
 *                               metrics outside the spec (box scores)
 *   QPV.tab(el, o)              renders the tab: o = { P, metrics: [M] (deep), head: [M], peer: 'quarterbacks', tabs:
 *                               [[key, label, href]], title, kicker, sub, actions (HTML), key: M (the anchor tile),
 *                               nUnit, ref: (S, id) -> {q, n}, compare: { sims: [{ id, name }], href: (ids, q) -> '#/..' },
 *                               note (HTML under the chart), empty: 'text' }
 *   QPV.compare(el, o)          renders the compare page: o = { players: [P], metrics, cat, metric, x, y, ref: (P, S, id),
 *                               peerName: P -> text, suggest, cyNote, title, kicker, sub, actions (HTML), href: (ids, qs),
 *                               names: [[id, label]] (the add-a-player list), extraQs: 'kind=..' }
 * Copy is neutral (no pronouns, no betting words). ES5, no optional chaining. */
(function (root) {
'use strict';

var QK = root.QK, QKC = root.QKC;
if (!QK || !QKC || !QK.prog) return;
var esc = QK.esc, isNum = QK.isNum;
var QPV = {};

function card(title, sub, body, o) {
  o = o || {};
  return '<section class="qk-card' + (o.cls ? ' ' + o.cls : '') + '"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div><div class="qk-card-body">' + body + '</div></section>';
}
QPV.card = card;
function find(list, f) { for (var i = 0; i < list.length; i++) if (f(list[i], i)) return list[i]; return null; }
function alive(el) { return !!(el && (el.isConnected === undefined ? document.body.contains(el) : el.isConnected)); }
QPV.alive = alive;

QPV.metrics = function (keys, cat, o) {
  o = o || {};
  var head = o.head || [], out = [];
  (keys || []).forEach(function (id) {
    if (find(out, function (m) { return m.id === id; })) return;
    var m = cat ? cat.metric(id, o.entity || 'player') : null;
    var lab = (o.labels || {})[id] || (m && m.label && m.label !== id ? m.label : id.replace(/_/g, ' '));
    var unit = m && m.unit && m.unit !== 'rate' ? m.unit : ((o.units || {})[id] || '');
    var dir = (o.dirs || {})[id] || (m ? (m.style ? 'neutral' : m.dir) : 'higher');
    out.push({ id: id, label: lab, unit: unit, dir: dir, ours: m && m.ours ? m.ours : null, tip: cat ? cat.tip(id, o.entity || 'player', (o.tips || {})[id] || '') : ((o.tips || {})[id] || ''),
      head: head.indexOf(id) >= 0, fmt: o.fmt ? o.fmt(id, unit) : undefined });
  });
  (o.extra || []).forEach(function (b) {
    if (!find(out, function (m) { return m.id === b[0]; })) out.push({ id: b[0], label: b[1], unit: b[2] || '', dir: b[3] || 'higher', ours: null, tip: b[4] || '', head: false, box: true, fmt: o.fmt ? o.fmt(b[0], b[2]) : undefined });
  });
  return out;
};

function tabsNav(tabs, cur) {
  if (!tabs || !tabs.length) return '';
  return '<nav class="qk-tabs qpv-tabs" aria-label="Player views">' + tabs.map(function (t) {
    return '<a class="qk-tab" href="' + esc(t[2]) + '" aria-selected="' + (t[0] === cur) + '"' + (t[0] === cur ? ' aria-current="page"' : '') + '>' + esc(t[1]) + '</a>';
  }).join('') + '</nav>';
}
QPV.tabsNav = tabsNav;

QPV.tab = function (el, o) {
  var P = o.P, ms = o.metrics || [], peer = o.peer || 'peers', sur = P.short || QK.surname(P.name || '') || 'The player';
  var head = (o.head && o.head.length ? o.head : ms.filter(function (m) { return m.head; }));
  if (!head.length) head = ms.filter(function (m) { return !m.box; }).slice(0, 8);
  var deep = ms.filter(function (m) { return !m.box; });
  var h = tabsNav(o.tabs, 'progression');
  h += QK.sectionHead({ kicker: o.kicker || 'Progression', title: o.title || P.name, size: 'lg', tag: 'h1', sub: o.sub || '', html: true, actions: o.actions || '' });
  if (!P.seasons.length) { el.innerHTML = h + QK.empty('No seasons in the data yet', o.empty || 'The progression appears once a season is in the data.'); return; }
  var arc = QK.careerArc({ player: P, metrics: head, all: deep, key: o.key || null, peerName: peer });
  h += arc.html + QK.explain(esc(arc.text), { title: 'The short version.' });
  var avail = ms.filter(function (m) { return P.seasons.some(function (s) { return isNum((s.values || {})[m.id]); }); });
  /* the opening metric: the headline one with the most seasons of data (ties to the spec's order) */
  var nOf = function (m) { return P.seasons.filter(function (s) { return isNum((s.values || {})[m.id]); }).length; };
  var m0 = null;
  head.forEach(function (m) { if (avail.indexOf(m) >= 0 && (!m0 || nOf(m) > nOf(m0))) m0 = m; });
  m0 = m0 || avail[0] || ms[0];
  var hasAge = P.seasons.some(function (s) { return isNum(s.age); });
  h += '<section class="qk-section">' + card('Career progression', 'One number through the seasons against the middle half of ' + esc(peer) + ' that season, or the headline set as percentiles',
    '<div class="qkp-ctl"><label for="qpv-m">Metric <select class="qk-select" id="qpv-m">' + QK.optgroups(avail.map(function (m) { return { value: m.id, key: m.id, label: m.label }; }), o.cat || null, { selected: m0 ? m0.id : '' }) + '</select></label>' +
    '<div class="qk-seg" role="group" aria-label="Show" id="qpv-y"><button type="button" data-value="value" aria-pressed="true">Value</button><button type="button" data-value="pct" aria-pressed="false">Percentile</button><button type="button" data-value="head" aria-pressed="false">Headline set</button></div>' +
    (hasAge ? '<div class="qk-seg" role="group" aria-label="Along" id="qpv-x"><button type="button" data-value="season" aria-pressed="true">By season</button><button type="button" data-value="age" aria-pressed="false">By age</button></div>' : '') + '</div>' +
    '<div id="qpv-chart" style="height:360px"></div><div id="qpv-key"></div><p class="qkp-note" id="qpv-note"></p>') + '</section>';
  var gridP = { id: P.id, name: P.name, seasons: P.seasons.filter(function (s) { return !s.box; }) };
  var groups = o.groups || [{ label: 'The headline set', ids: head.map(function (m) { return m.id; }) }, { label: 'Deeper', ids: deep.filter(function (m) { return head.indexOf(m) < 0; }).map(function (m) { return m.id; }) }];
  if (gridP.seasons.length) {
    h += '<section class="qk-section">' + card('Every season, every number', 'Percentile against ' + esc(peer) + ' each season (100 = best); the value, the sample and the peers in each cell’s tooltip. The headline numbers first, then the deeper set.',
      QK.progressionGrid({ player: gridP, metrics: deep.concat(ms.filter(function (m) { return m.box; })), groups: groups, peerName: peer })) + '</section>';
  }
  var cmp = o.compare || {}, sims = (cmp.sims || []).slice(0, 3), href = cmp.href;
  var chips = '';
  if (href) {
    if (sims.length) chips += '<a class="qk-chip" href="' + esc(href([P.id].concat(sims.slice(0, 2).map(function (s) { return s.id; })), hasAge ? 'x=age' : '')) + '">' + esc([sur].concat(sims.slice(0, 2).map(function (s) { return s.name; })).join(', ')) + (hasAge ? ' by age' : ' by season') + '</a>';
    chips += sims.map(function (s) { return '<a class="qk-chip" href="' + esc(href([P.id, s.id], '')) + '">v ' + esc(s.name) + '</a>'; }).join('');
    chips += '<a class="qk-chip" href="' + esc(href([P.id], '')) + '">Pick a player</a>';
  }
  h += '<section class="qk-section"><div class="qk-g75"><div>' + card('Biggest jumps and drops', 'Season to season, in percentile points, both seasons above the sample floor', QK.progressionDeltas({ player: P, metrics: deep, limit: 4, peerName: peer })) + '</div>' +
    '<div>' + card('Compare the careers', 'Line ' + esc(sur) + ' up with anyone by season' + (hasAge ? ', by age' : '') + ' or by career year',
      '<p style="margin:0 0 12px;color:var(--ink-2)">' + (sims.length ? 'The closest matches on the profile, or pick anyone on the compare page.' : 'Pick anyone on the compare page.') + '</p><div class="qk-chips">' + chips + '</div>') + '</div></div></section>';
  if (o.foot) h += o.foot;
  el.innerHTML = h;
  var st = { m: m0 ? m0.id : null, y: 'value', x: 'season' };
  function draw() {
    if (!alive(el)) return;
    var M = find(ms, function (m) { return m.id === st.m; }) || ms[0];
    var mode = st.y === 'head' ? 'pct' : st.y;
    var list = st.y === 'head' ? head.slice(0, 4) : [M];
    QKC.progression(el.querySelector('#qpv-chart'), { player: P, metrics: list, mode: mode, x: st.x, ref: o.ref, peerName: peer });
    var pl = mode === 'value' && P.seasons.some(function (s) { return isNum((s.pct || {})[M.id]); });
    el.querySelector('#qpv-key').innerHTML = QK.progressionKey({ mode: mode, name: sur, peerName: peer, pctLine: pl, band: !M.box && !!o.ref, nUnit: o.nUnit || 'games' });
    el.querySelector('#qpv-note').innerHTML = (st.y === 'head' ? 'The first four headline numbers as percentiles against ' + esc(peer) + ' each season; the shaded band is the middle half.' :
      (M.tip ? '<b>' + esc(M.label) + (M.ours ? ' (our model)' : '') + ':</b> ' + esc(M.tip) : '') + (M.box ? ' Box score: no peer band.' : '')) + (o.note ? ' ' + o.note : '');
  }
  var sel = el.querySelector('#qpv-m');
  sel.addEventListener('change', function () {
    st.m = sel.value;
    if (st.y === 'head') { st.y = 'value'; Array.prototype.forEach.call(el.querySelectorAll('#qpv-y button'), function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-value') === 'value')); }); }
    draw();
  });
  QK.seg(el.querySelector('#qpv-y'), function (v) { st.y = v; draw(); });
  if (hasAge) QK.seg(el.querySelector('#qpv-x'), function (v) { st.x = v; draw(); });
  draw();
};

QPV.compare = function (el, o) {
  var Ps = (o.players || []).slice(0, 4), ms = o.metrics || [];
  var names = Ps.map(function (P) { return P.short || QK.surname(P.name || ''); });
  var st = { metric: o.metric, x: o.x === 'age' || o.x === 'year' ? o.x : 'season', y: o.y === 'pct' ? 'pct' : 'value' };
  var qs = function () { return (o.extraQs ? o.extraQs + '&' : '') + 'm=' + encodeURIComponent(st.metric || '') + '&x=' + st.x + '&y=' + st.y; };
  var opts = o.names || [];
  var uid = 'qpvc' + Math.random().toString(36).slice(2, 7);
  el.innerHTML = QK.sectionHead({ kicker: o.kicker || 'Compare progression', title: o.title || (names.length > 1 ? names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?' : (names[0] || 'Compare progression')),
      size: 'lg', tag: 'h1', html: true, sub: o.sub || 'Two to four careers on one chart: by season, by age or by career year, on any number of the deep set, as the value or as a percentile against that season’s peers. Hollow dots are seasons under the sample floor.',
      actions: o.actions || '' }) +
    '<article class="qk-card"><div class="qk-card-body"><div id="' + uid + '-w"></div>' +
    '<form class="qkp-ctl" id="' + uid + '-add" style="margin:16px 0 0" autocomplete="off"><label for="' + uid + '-in">Add or swap a player <input class="qk-input" id="' + uid + '-in" list="' + uid + '-dl" placeholder="Type a name" style="min-width:0;width:min(260px,60vw)"></label><datalist id="' + uid + '-dl">' +
    opts.map(function (x) { return '<option value="' + esc(x[1]) + '"></option>'; }).join('') + '</datalist><button class="qk-btn" type="submit">Add</button>' +
    Ps.map(function (P) { return '<a class="qk-chip" href="' + esc(o.href(Ps.filter(function (x) { return x !== P; }).map(function (x) { return x.id; }), o.extraQs || '')) + '" aria-label="Remove ' + esc(P.name) + '">✕ ' + esc(P.short || P.name) + '</a>'; }).join('') + '</form></div></article>' + (o.foot || '');
  var w = el.querySelector('#' + uid + '-w');
  if (!Ps.length) w.innerHTML = QK.empty('Pick a player', 'Type a name below.');
  else QK.compareProgression(w, { players: Ps, metrics: ms, cat: o.cat, metric: st.metric, x: st.x, y: st.y, ref: o.ref, peerName: o.peerName, suggest: (o.suggest || []).slice(0, 5), cyNote: o.cyNote,
    onState: function (s) { st.metric = s.metric; st.x = s.x; st.y = s.y; try { history.replaceState(null, '', o.href(Ps.map(function (P) { return P.id; }), qs())); } catch (e) { /* file:// */ } } });
  el.querySelector('#' + uid + '-add').addEventListener('submit', function (e) {
    e.preventDefault();
    var v = String(el.querySelector('#' + uid + '-in').value || '').trim().toLowerCase();
    if (!v) return;
    var hit = find(opts, function (x) { return String(x[1]).toLowerCase() === v; }) || find(opts, function (x) { return String(x[1]).toLowerCase().indexOf(v) >= 0; });
    if (!hit) return;
    var next = Ps.map(function (P) { return P.id; }).filter(function (id) { return String(id) !== String(hit[0]); });
    if (next.length >= 4) next.pop();
    location.hash = o.href(next.concat([hit[0]]), qs());
  });
};

/* helpers the adapters share */
QPV.zip = function (keys, arr) { var o = {}; (arr || []).forEach(function (x, j) { if (isNum(x) && keys[j]) o[keys[j]] = x; }); return o; };
QPV.ageAt = function (dob, year, month) {
  var d = dob ? new Date(String(dob).slice(0, 10) + 'T00:00:00Z') : null;
  if (!d || isNaN(d.getTime())) return null;
  return (Date.UTC(Number(year), month === undefined ? 6 : month, 1) - d.getTime()) / (365.25 * 864e5);
};
QPV.hrefFor = function (base) {
  return function (ids, q) { return base + ids.map(function (x) { return encodeURIComponent(x); }).join('/') + (q ? '?' + q : ''); };
};

root.QPV = QPV;
})(window);
