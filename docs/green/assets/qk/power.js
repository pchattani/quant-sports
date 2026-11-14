/* The Quant — power rankings (kit round 13): QKR draws the uniform power files every site publishes
 * (docs/<site>/data/power/<league>.json and the index data/power.json; the shape is oddsmarkets/common/power.py).
 * Needs quant.js only (Home loads it without scout.js or league.js).
 *
 *   QKR.fmt(v, code)                    "0" "1" "2" decimals, "+1" "+2" signed, "pct0" "pct1" a 0-1 share
 *   QKR.mountBump(el, doc, o)           the climb: a bump chart of the current top N's rank at every snapshot, in team
 *                                       colours, end labels with the move; hover, focus or tap a line to pick it out.
 *                                       o: { top, base (a URL prefix for the site's hash routes, Home), compact }
 *   QKR.mountSpectrum(el, groups, o)    best and worst at every position: one dot per qualified player on the group's
 *                                       headline metric (worse left, better right), the top three in team colour, the
 *                                       bottom three in coral, the No. 1 and the last named; a row opens its top five
 *                                       and bottom three with their numbers. o: { base, max (rows), open }
 *   QKR.list(doc, o) -> html            the ranked list: rank, the move, the side, a rating bar split into its parts,
 *                                       the record, form, headline chance and one line on why
 *   QKR.groupTables(group, o) -> html   a position's top ten and bottom five with every stat (tables: CSV through the kit)
 *   QKR.page(el, o)                     a site's #/power page from o.url (or o.doc): head, league chips (o.leagues), the
 *                                       movers, the climb, the list, the players; o.base for hrefs
 *   QKR.home(el, P, o)                  Home's section from home.json's `power` block: the No. 1 in every sport, then a
 *                                       sport (and league) picker over the climb and the position spectrum, each sport's
 *                                       file fetched from its own site when picked
 * Everything degrades: a missing file says so in one line; no players block hides the spectrum. */
(function (root) {
'use strict';
var QK = root.QK;
if (!QK) return;
var esc = QK.esc, isNum = QK.isNum;
var QKR = {};
var MINUS = '−';

/* ───────────────────────────── numbers */
/* a value that rounds to zero is plain 0.00: never "−0.00" */
function sgn(x, d) { var a = Math.abs(x).toFixed(d); if (+a === 0) return a; return (x > 0 ? '+' : MINUS) + a; }
QKR.fmt = function (v, code) {
  if (!isNum(v)) return '—';
  var c = String(code || '1');
  if (c === 'pct0' || c === 'pct1') return (v * 100).toFixed(c === 'pct1' ? 1 : 0) + '%';
  if (c.charAt(0) === '+') return sgn(v, parseInt(c.slice(1), 10) || 0);
  var d = parseInt(c, 10); if (!isFinite(d)) d = 1;
  var s = Math.abs(v) >= 1000 && d === 0 ? Math.round(v).toLocaleString('en-GB') : v.toFixed(d);
  if (+s.replace(/,/g, '') === 0) return Math.abs(0).toFixed(d);
  return v < 0 ? MINUS + s.replace('-', '') : s;
};
function ord(n) { return QK.ordinal ? QK.ordinal(n) : n + 'th'; }
function rel(base, href) { if (!href) return null; return base && href.charAt(0) === '#' ? base + href : href; }
function col(c) { return QK.color && QK.color.parse(c) ? QK.color.team(c) : 'var(--ink-3)'; }
function mark(t) { return QK.teamMark({ abbr: t.abbr || t.team || '', colour: t.colour, name: t.name }, 'sm'); }
function short(t) { return t.short || t.name || t.abbr || ''; }
/* the move since the previous snapshot as a chip: up, down, level, new */
function moveChip(t, o) {
  o = o || {};
  if (t.prev === null || t.prev === undefined) return t.path && t.path.length > 1 ? '<span class="qkp-mv new" title="Not ranked at the last snapshot">New</span>' : '';
  var m = t.move;
  if (!isNum(m) || m === 0) return '<span class="qkp-mv eq" title="Same place as at the last snapshot">' + (o.word ? 'Level' : '–') + '</span>';
  return '<span class="qkp-mv ' + (m > 0 ? 'up' : 'dn') + '" title="' + (m > 0 ? 'Up ' : 'Down ') + Math.abs(m) + ' since the last snapshot (was ' + ord(t.prev) + ')">' +
    (m > 0 ? '▲' : '▼') + Math.abs(m) + '</span>';
}
QKR.moveChip = moveChip;
var STEP = { week: 'last week', race: 'the last race', round: 'the last round', month: 'last month', event: 'the last event', test: 'the last window' };
function sinceWord(doc) { return STEP[doc && doc.step] || 'the last update'; }

/* ───────────────────────────── a tooltip shared by the charts (the kit's look) */
var tipEl = null;
function tip(html, x, y) {
  if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'qk-tip qkp-tip'; tipEl.setAttribute('role', 'tooltip'); document.body.appendChild(tipEl); }
  if (!html) { tipEl.classList.remove('show'); return; }
  tipEl.innerHTML = html;
  tipEl.classList.add('show');
  var w = tipEl.offsetWidth, hh = tipEl.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
  var left = Math.min(vw - w - 8, Math.max(8, x + 14)), top = y - hh - 12;
  if (top < 8) top = y + 18;
  if (top + hh > vh - 8) top = vh - hh - 8;
  tipEl.style.left = left + 'px'; tipEl.style.top = top + 'px';
}
function hideTip() { tip(null); }

/* redraw on width changes only (a phone's toolbar hiding does not redraw) */
function onWidth(el, fn) {
  var w0 = el.clientWidth, t = null;
  function chk() { if (!el.isConnected) { window.removeEventListener('resize', h); return; } var w = el.clientWidth; if (Math.abs(w - w0) > 4) { w0 = w; fn(); } }
  function h() { if (t) clearTimeout(t); t = setTimeout(chk, 120); }
  window.addEventListener('resize', h);
}

/* ───────────────────────────── the climb: a bump chart */
QKR.mountBump = function (el, doc, o) {
  o = o || {};
  if (!el) return;
  function draw() { el.innerHTML = bumpHTML(el, doc, o); wireBump(el, doc, o); if (o.onDraw) o.onDraw(el._qkrN || 0); }
  draw();
  onWidth(el, draw);
};
function lanesAt(teams, i) {
  /* every side's lane at snapshot i: the order by rank there (ties broken by today's order), 1 = top */
  var xs = teams.filter(function (t) { return t.path && isNum(t.path[i]); }).slice();
  xs.sort(function (a, b) { return (a.path[i] - b.path[i]) || (a.rank - b.rank); });
  var m = {};
  xs.forEach(function (t, k) { m[t.id] = k + 1; });
  return m;
}
function bumpHTML(el, doc, o) {
  var all = doc.teams || [], snaps = doc.snapshots || [];
  if (!all.length || snaps.length < 2) return '<p class="qk-sub">The climb starts once there are two weekly snapshots.</p>';
  var W = Math.max(300, el.clientWidth || 640), narrow = W < 560;
  var nS = Math.min(snaps.length, narrow ? 6 : (o.snaps || 9)), off = snaps.length - nS;
  var N = Math.min(all.length, narrow ? Math.min(o.top || 8, 8) : (o.top || 10));
  el._qkrN = N;
  var lanes = []; for (var i = off; i < snaps.length; i++) lanes.push(lanesAt(all, i));
  var shown = all.filter(function (t) { return t.rank && lanes[nS - 1][t.id] <= N; }).sort(function (a, b) { return lanes[nS - 1][a.id] - lanes[nS - 1][b.id]; });
  var outside = shown.some(function (t) { for (var k = 0; k < nS; k++) { var l = lanes[k][t.id]; if (!l || l > N) return true; } return false; });
  var nL = N + (outside ? 1 : 0);
  /* the end labels' room: the move chip, the mark, the longest name (about 8.4 px a character in Barlow Condensed caps)
     and, on wide screens, the rating; never more than about two fifths of the chart */
  var labName = function (t) { return short(t); };   /* phones drop the mark (the line's colour edges the name) */
  var longest = Math.max.apply(null, shown.map(function (t) { return String(labName(t)).length; }).concat([3]));
  var padR = Math.round(Math.max(narrow ? 86 : 178, Math.min(W * (narrow ? 0.4 : 0.42), (narrow ? 52 : 132) + longest * 8.4)));
  var padL = 26, padT = 12, padB = 30, laneH = narrow ? 27 : (o.compact ? 28 : 31);
  var H = padT + (nL - 1) * laneH + padB + 4, plotW = W - padL - padR;
  function x(k) { return padL + (nS === 1 ? plotW / 2 : k * plotW / (nS - 1)); }
  function y(l) { return padT + (Math.min(l || nL, nL) - 1) * laneH; }
  var s = '<svg class="qkp-bump-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' +
    esc('Rank of the current top ' + N + ' at each of the last ' + nS + ' snapshots, ' + snaps[off].label + ' to ' + snaps[snaps.length - 1].label) + '">';
  /* lanes: faint rules, rank numbers on the left; the bottom lane is "outside the top N" */
  for (var l = 1; l <= nL; l++) {
    var yy = y(l);
    s += '<line class="qkp-b-rule" x1="' + padL + '" x2="' + (W - padR + 6) + '" y1="' + yy + '" y2="' + yy + '"/>';
    s += '<text class="qkp-b-ax" x="' + (padL - 10) + '" y="' + (yy + 4) + '" text-anchor="end">' + (l > N ? (narrow ? '' : N + 1 + '+') : l) + '</text>';
  }
  if (outside) s += '<text class="qkp-b-out" x="' + (padL + 4) + '" y="' + (y(nL) - 6) + '">' + esc('outside the top ' + N) + '</text>';
  /* snapshot labels, thinned to fit */
  var every = Math.max(1, Math.ceil(nS / Math.max(2, Math.floor(plotW / 54))));
  for (var k = 0; k < nS; k++) {
    if (k !== nS - 1 && (nS - 1 - k) % every) continue;
    s += '<text class="qkp-b-x' + (k === nS - 1 ? ' now' : '') + '" x="' + x(k) + '" y="' + (H - 8) + '" text-anchor="' + (k === 0 && nS > 1 ? 'start' : k === nS - 1 ? 'middle' : 'middle') + '">' + esc(snaps[off + k].label) + '</text>';
  }
  /* lines, the lowest first so the leaders sit on top */
  shown.slice().reverse().forEach(function (t) {
    var c = col(t.colour), pts = [];
    for (var k = 0; k < nS; k++) { var ln = lanes[k][t.id]; pts.push({ x: x(k), y: y(ln && ln <= N ? ln : nL), out: !ln || ln > N, k: k }); }
    var g = '<g class="qkp-b-t" data-id="' + esc(t.id) + '" style="--tc:' + c + '">';
    for (var k2 = 1; k2 < pts.length; k2++) {
      var a = pts[k2 - 1], b = pts[k2], mx = (a.x + b.x) / 2;
      g += '<path class="qkp-b-seg' + (a.out || b.out ? ' out' : '') + '" d="M' + a.x.toFixed(1) + ' ' + a.y + 'C' + mx.toFixed(1) + ' ' + a.y + ' ' + mx.toFixed(1) + ' ' + b.y + ' ' + b.x.toFixed(1) + ' ' + b.y + '"/>';
    }
    g += '<path class="qkp-b-hit" d="M' + pts.map(function (p) { return p.x.toFixed(1) + ' ' + p.y; }).join('L') + '"/>';
    pts.forEach(function (p) {
      var last = p.k === nS - 1;
      g += '<circle class="qkp-b-pt' + (p.out ? ' out' : '') + (last ? ' last' : '') + '" cx="' + p.x.toFixed(1) + '" cy="' + p.y + '" r="' + (last ? 6 : 4) + '" data-k="' + (off + p.k) + '"/>';
    });
    s += g + '</g>';
  });
  s += '</svg>';
  /* end labels in HTML: the move, the mark, the name; each a link to the side's page */
  var labs = shown.map(function (t) {
    var ly = y(lanes[nS - 1][t.id]);
    var href = rel(o.base, t.href);
    var inner = moveChip(t) + (narrow ? '' : mark(t)) + '<span class="qkp-b-nm"' + (narrow ? ' style="border-left:3px solid ' + col(t.colour) + ';padding-left:5px"' : '') + '>' + esc(labName(t)) + '</span>' +
      (narrow ? '' : '<span class="qkp-b-v">' + esc(QKR.fmt(t.rating, (doc.rating || {}).fmt || '+1')) + '</span>');
    return (href ? '<a' : '<span') + ' class="qkp-b-lab" data-id="' + esc(t.id) + '" style="top:' + (ly - 12) + 'px;left:' + (W - padR + 12) + 'px;width:' + (padR - 14) + 'px"' +
      (href ? ' href="' + esc(href) + '"' : ' tabindex="0"') + ' aria-label="' + esc(ord(t.rank) + ', ' + t.name + (isNum(t.move) && t.move ? (t.move > 0 ? ', up ' : ', down ') + Math.abs(t.move) : '')) + '">' + inner + (href ? '</a>' : '</span>');
  }).join('');
  return '<div class="qkp-bump" style="height:' + H + 'px">' + s + labs + '</div>';
}
function wireBump(el, doc, o) {
  var box = el.querySelector('.qkp-bump');
  if (!box) return;
  var byId = {}; (doc.teams || []).forEach(function (t) { byId[t.id] = t; });
  var snaps = doc.snapshots || [], fmtR = (doc.rating || {}).fmt || '+1', pinned = null;
  function on(id) {
    box.classList.toggle('hl', !!id);
    box.querySelectorAll('[data-id]').forEach(function (n) { n.classList.toggle('on', n.getAttribute('data-id') === id); });
  }
  function pick(ev) { var n = ev.target.closest ? ev.target.closest('[data-id]') : null; return n ? n.getAttribute('data-id') : null; }
  box.addEventListener('mouseover', function (ev) { var id = pick(ev); if (id) on(id); });
  box.addEventListener('mouseleave', function () { on(pinned); hideTip(); });
  box.addEventListener('focusin', function (ev) { var id = pick(ev); if (id) on(id); });
  box.addEventListener('focusout', function () { on(pinned); });
  box.addEventListener('mousemove', function (ev) {
    var c = ev.target.closest ? ev.target.closest('circle[data-k]') : null;
    if (!c) { hideTip(); return; }
    var t = byId[c.parentNode.getAttribute('data-id')], k = +c.getAttribute('data-k');
    if (!t) return;
    var r = t.path ? t.path[k] : null, v = t.rpath ? t.rpath[k] : null;
    tip('<b>' + esc(t.name) + '</b><br>' + esc(snaps[k] ? snaps[k].label : '') + ': ' + (isNum(r) ? esc(ord(r)) : 'unranked') +
      (isNum(v) ? ' · ' + esc((doc.rating || {}).short || 'rating') + ' ' + esc(QKR.fmt(v, fmtR)) : ''), ev.clientX, ev.clientY);
  });
  /* touch: a tap on a line pins it (a tap on a label still follows the link) */
  box.addEventListener('click', function (ev) {
    if (ev.target.closest && ev.target.closest('a')) return;
    var id = pick(ev);
    pinned = id && id !== pinned ? id : null;
    on(pinned);
  });
}

/* ───────────────────────────── best and worst at every position: the spectrum */
QKR.mountSpectrum = function (el, groups, o) {
  o = o || {};
  if (!el) return;
  groups = (groups || []).filter(function (g) { return g && g.dist && g.dist.length >= 3; });
  if (o.max) groups = groups.slice(0, o.max);
  if (!groups.length) { el.innerHTML = ''; return; }
  var openKey = o.open || null;
  function draw() {
    var compact = (el.clientWidth || 800) < 760 && (window.innerWidth || 1000) > 640;   /* phones have their own stacked rows */
    el.innerHTML = '<div class="qkp-sp' + (compact ? ' compact' : '') + '" role="list">' + groups.map(function (g) { return spRow(g, o, openKey === g.key); }).join('') + '</div>';
    groups.forEach(function (g) { var t = el.querySelector('.qkp-sp-row[data-g="' + g.key + '"] .qkp-sp-track'); if (t) t.innerHTML = spStrip(t, g); });
    wireSp(el, groups, o, function (k) { openKey = openKey === k ? null : k; draw(); });
  }
  draw();
  onWidth(el, draw);
};
function pname(p, n) { var s = String(p.name || ''); if (n && s.length > n) { var parts = s.split(' '); s = parts.length > 1 ? parts[0].charAt(0) + '. ' + parts.slice(1).join(' ') : s; } return s; }
function spRow(g, o, open) {
  var m = g.metric || {}, best = (g.top || [])[0], worst = (g.bottom || []).length ? g.bottom[g.bottom.length - 1] : null;
  function who(p, cls, lab) {
    if (!p) return '<span class="qkp-sp-who ' + cls + '"></span>';
    var href = rel(o.base, p.href);
    return '<span class="qkp-sp-who ' + cls + '"><small>' + esc(lab) + '</small>' + (href ? '<a href="' + esc(href) + '">' : '<span>') + esc(pname(p, 16)) + (href ? '</a>' : '</span>') +
      '<b class="num">' + esc(QKR.fmt(p.value, m.fmt)) + '</b><i>' + esc(p.team || '') + '</i></span>';
  }
  var det = open ? '<div class="qkp-sp-det">' + spDetail(g, o) + '</div>' : '';
  return '<div class="qkp-sp-row' + (open ? ' open' : '') + '" role="listitem" data-g="' + esc(g.key) + '">' +
    '<button type="button" class="qkp-sp-lab" aria-expanded="' + (open ? 'true' : 'false') + '" title="' + esc((g.label || '') + ': ' + (m.label || '') + (m.unit ? ' (' + m.unit + ')' : '') + '. Tap for the top five and bottom three.') + '">' +
      '<b>' + esc(g.short || g.label) + '</b><small>' + esc(m.label || '') + '</small></button>' +
    who(worst, 'lo', 'Last of ' + g.n) +
    '<div class="qkp-sp-track" aria-hidden="true"></div>' +
    who(best, 'hi', 'No. 1') + det + '</div>';
}
function spDetail(g, o) {
  var m = g.metric || {}, st = (g.stats || []).slice(0, 3);
  function line(p) {
    var href = rel(o.base, p.href);
    return '<li><span class="qkp-sd-rk num">' + esc(p.rank) + '</span>' + mark({ abbr: p.team, colour: p.colour, name: p.team }) +
      (href ? '<a href="' + esc(href) + '">' : '<span>') + esc(p.name) + (href ? '</a>' : '</span>') +
      '<b class="num">' + esc(QKR.fmt(p.value, m.fmt)) + '</b>' +
      '<span class="qkp-sd-st">' + st.map(function (s, i) { return '<span><small>' + esc(s.label) + '</small>' + esc(QKR.fmt((p.stats || [])[i], s.fmt)) + '</span>'; }).join('') + '</span></li>';
  }
  var top = (g.top || []).slice(0, 5), bot = (g.bottom || []).slice(-3);
  return '<div class="qkp-sd"><div><div class="qkp-sd-h up">Top five</div><ol>' + top.map(line).join('') + '</ol></div>' +
    (bot.length ? '<div><div class="qkp-sd-h dn">Bottom three</div><ol>' + bot.map(line).join('') + '</ol></div>' : '') + '</div>' +
    '<p class="qkp-sd-foot">' + esc(g.n + ' qualified' + (g.min ? ' (' + g.min + ')' : '') + '. ' + (m.label || '') + (m.dir === 'lower' ? ': lower is better.' : '.')) + '</p>';
}
function spScale(g, w) {
  /* dist runs worst to best (for a lower-is-better metric that is high to low), so the worst sits left either way */
  var d = g.dist, lo = d[0], hi = d[d.length - 1], pad = 7;
  if (lo === hi) { lo -= 1; hi += 1; }
  return function (v) { var f = (v - lo) / (hi - lo); return pad + Math.max(0, Math.min(1, f)) * (w - 2 * pad); };
}
function spStrip(track, g) {
  var w = Math.max(120, track.clientWidth || 240), h = 36, r = 2.6, mid = h / 2;
  var X = spScale(g, w), d = g.dist;
  /* a small beeswarm: stack dots that would overlap in columns, alternating above and below the middle */
  var cols = {}, s = '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">';
  s += '<line class="qkp-sp-base" x1="4" x2="' + (w - 4) + '" y1="' + mid + '" y2="' + mid + '"/>';
  var med = d[Math.floor(d.length / 2)];
  s += '<line class="qkp-sp-med" x1="' + X(med).toFixed(1) + '" x2="' + X(med).toFixed(1) + '" y1="4" y2="' + (h - 4) + '"/>';
  d.forEach(function (v, i) {
    var px = X(v), c = Math.round(px / (2 * r + 0.6)), n = cols[c] || 0; cols[c] = n + 1;
    var off = n === 0 ? 0 : Math.ceil(n / 2) * (2 * r + 0.4) * (n % 2 ? -1 : 1);
    if (Math.abs(off) > mid - r - 1) off = (off > 0 ? 1 : -1) * (mid - r - 1) * ((n % 3) / 3);
    s += '<circle class="qkp-sp-dot" cx="' + px.toFixed(1) + '" cy="' + (mid + off).toFixed(1) + '" r="' + r + '" data-i="' + i + '"/>';
  });
  (g.bottom || []).slice(-3).forEach(function (p) { if (isNum(p.value)) s += '<circle class="qkp-sp-lo" cx="' + X(p.value).toFixed(1) + '" cy="' + mid + '" r="4.6" data-p="b' + esc(p.id) + '"/>'; });
  (g.top || []).slice(0, 3).reverse().forEach(function (p, i) {
    if (!isNum(p.value)) return;
    var one = p.rank === 1 && i === Math.min(3, (g.top || []).length) - 1;
    s += (one ? '<circle class="qkp-sp-ring" cx="' + X(p.value).toFixed(1) + '" cy="' + mid + '" r="8.5"/>' : '') +
      '<circle class="qkp-sp-hi" style="--tc:' + col(p.colour) + '" cx="' + X(p.value).toFixed(1) + '" cy="' + mid + '" r="5.2" data-p="t' + esc(p.id) + '"/>';
  });
  return s + '</svg>';
}
function wireSp(el, groups, o, toggle) {
  var byKey = {}; groups.forEach(function (g) { byKey[g.key] = g; });
  el.querySelectorAll('.qkp-sp-lab').forEach(function (b) { b.addEventListener('click', function () { toggle(b.parentNode.getAttribute('data-g')); }); });
  el.querySelectorAll('.qkp-sp-track').forEach(function (t) {
    var g = byKey[t.parentNode.getAttribute('data-g')];
    if (!g) return;
    var named = {}; (g.top || []).concat(g.bottom || []).forEach(function (p) { named[p.id] = p; });
    var m = g.metric || {};
    t.addEventListener('mousemove', function (ev) {
      var svg = t.querySelector('svg'); if (!svg) return;
      var bx = svg.getBoundingClientRect(), X = spScale(g, bx.width), px = ev.clientX - bx.left;
      /* the nearest named player within 10 px wins, else the nearest dot */
      var best = null, bd = 11;
      Object.keys(named).forEach(function (id) { var p = named[id]; if (!isNum(p.value)) return; var dd = Math.abs(X(p.value) - px); if (dd < bd) { bd = dd; best = p; } });
      if (best) {
        tip('<b>' + esc(best.name) + '</b> · ' + esc(best.team || '') + '<br>' + esc(m.label || '') + ' ' + esc(QKR.fmt(best.value, m.fmt)) + ' · ' + esc(ord(best.rank)) + ' of ' + g.n +
          ((g.stats || []).length ? '<br>' + g.stats.slice(0, 4).map(function (s, i) { return esc(s.label) + ' ' + esc(QKR.fmt((best.stats || [])[i], s.fmt)); }).join(' · ') : ''), ev.clientX, ev.clientY);
        return;
      }
      var d = g.dist, bi = 0, bv = Infinity;
      for (var i = 0; i < d.length; i++) { var q = Math.abs(X(d[i]) - px); if (q < bv) { bv = q; bi = i; } }
      if (bv > 12) { hideTip(); return; }
      var rk = Math.max(1, Math.round(g.n - bi * (g.n - 1) / Math.max(1, d.length - 1)));
      tip(esc(m.label || '') + ' ' + esc(QKR.fmt(d[bi], m.fmt)) + '<br>' + (g.sampled ? 'about ' : '') + esc(ord(rk)) + ' of ' + g.n + ' ' + esc((g.label || '').toLowerCase()), ev.clientX, ev.clientY);
    });
    t.addEventListener('mouseleave', hideTip);
  });
}

/* ───────────────────────────── the No. 1 in every sport (Home) */
QKR.no1Strip = function (items, o) {
  o = o || {};
  return '<div class="qkp-no1s" role="list">' + (items || []).map(function (it) {
    var t = it.top, sp = QK.sport(it.sport) || {};
    if (!t) return '';
    var deep = QK.color && QK.color.parse(t.colour) ? QK.color.deep(t.colour) : '#1d2230';
    var line = t.prev === undefined || t.prev === null ? (it.kind === 'players' ? 'Top of our ratings' : 'Top of our ratings')
      : t.move > 0 ? 'New No. 1, up from ' + ord(t.prev) : (t.weeks >= 2 ? 'No. 1 for ' + t.weeks + ' ' + (it.step === 'race' ? 'races' : it.step === 'round' ? 'rounds' : it.step === 'month' ? 'months' : it.step === 'event' ? 'events' : 'weeks') : 'No. 1 this ' + (it.step === 'race' ? 'race' : it.step || 'week'));
    if (it.phase === 'offseason') line = 'Final ranking · ' + (it.season_label || '');
    return '<button type="button" class="qkp-no1' + (o.active === it.sport ? ' on' : '') + '" role="listitem" data-sport="' + esc(it.sport) + '" style="--tc:' + deep + ';--acc:' + (sp.accent || 'var(--volt)') + '" aria-label="' + esc(it.label + ': ' + t.name + ' is No. 1 in our ratings') + '">' +
      '<span class="qkp-no1-k">' + esc(it.label) + '</span>' +
      '<span class="qkp-no1-r">1</span>' +
      '<span class="qkp-no1-m">' + mark(t) + '</span>' +
      '<span class="qkp-no1-n">' + esc(short(t)) + '</span>' +
      '<span class="qkp-no1-s">' + esc(line) + '</span>' +
      (isNum(t.rating) ? '<span class="qkp-no1-v num">' + esc(QKR.fmt(t.rating, (it.rating || {}).fmt || '+1')) + '<small>' + esc((it.rating || {}).short || 'rating') + '</small></span>' : '') +
      '</button>';
  }).join('') + '</div>';
};

/* ───────────────────────────── the ranked list (site pages) */
QKR.list = function (doc, o) {
  o = o || {};
  var teams = doc.teams || [], parts = doc.parts || [], fmtR = (doc.rating || {}).fmt || '+1';
  var PC = ['var(--c-2)', 'var(--c-3)', 'var(--c-5)', 'var(--c-4)'];
  var fmtD = /^[0-9]$/.test(fmtR) ? '+' + fmtR : fmtR;   /* a change is always signed */
  var Z = isNum((doc.rating || {}).zero) ? doc.rating.zero : 0;   /* the bar's baseline: 0, or an average Elo */
  var max = 0.5;
  teams.forEach(function (t) {
    var pos = 0, neg = 0;
    parts.forEach(function (p) { var v = (t.parts || {})[p.key]; if (isNum(v)) { if (v > 0) pos += v; else neg += v; } });
    max = Math.max(max, Math.abs(pos), Math.abs(neg), Math.abs(isNum(t.rating) ? t.rating - Z : 0));
  });
  max *= 1.06;
  function X(v) { return 50 + 50 * Math.max(-1, Math.min(1, v / max)); }
  function bar(t) {
    var segs = '', pa = 0, na = 0;
    parts.forEach(function (p, i) {
      var v = (t.parts || {})[p.key]; if (!isNum(v)) return;
      var a, b; if (v >= 0) { a = X(pa); pa += v; b = X(pa); } else { b = X(na); na += v; a = X(na); }
      segs += '<i style="left:' + a.toFixed(2) + '%;width:' + Math.max(0.4, b - a).toFixed(2) + '%;background:' + PC[i % PC.length] + '" title="' + esc(p.label + ' ' + QKR.fmt(v, fmtR)) + '"></i>';
    });
    if (!parts.length && isNum(t.rating)) {
      var a0 = X(Math.min(0, t.rating - Z)), b0 = X(Math.max(0, t.rating - Z));
      segs = '<i style="left:' + a0.toFixed(2) + '%;width:' + Math.max(0.4, b0 - a0).toFixed(2) + '%;background:' + col(t.colour) + '"></i>';
    }
    return '<div class="qkp-bar"><span class="z"></span>' + segs + (isNum(t.rating) ? '<b style="left:' + X(t.rating - Z).toFixed(2) + '%"></b>' : '') + '</div>';
  }
  var key = parts.length ? '<div class="qkp-key">' + parts.map(function (p, i) { return '<span><i style="background:' + PC[i % PC.length] + '"></i>' + esc(p.label) + '</span>'; }).join('') +
    '<span><b></b>' + esc((doc.rating || {}).label || 'Our rating') + '</span><span class="sc">Bar ends at ' + esc(QKR.fmt(-max, fmtR)) + ' and ' + esc(QKR.fmt(max, fmtR)) + '</span></div>' : '';
  var rows = teams.slice(0, o.n || teams.length).map(function (t) {
    var href = rel(o.base, t.href);
    var sub = [t.record, t.group].filter(Boolean).join(' · ');
    var meta = (t.chance && isNum(t.chance.p) ? '<span class="qkp-ch">' + esc(t.chance.label) + ' <b>' + esc(QK.fmt.pct(t.chance.p)) + '</b></span>' : '') +
      (t.stats || []).map(function (c) { return '<span class="qkp-st"><small>' + esc(c.label) + '</small>' + esc(c.text) + '</span>'; }).join('') +
      (t.form ? '<span class="qkp-fm">' + QK.formDots(t.form, 5) + '</span>' : '');
    return '<li class="qkp-row' + (t.rank <= 3 ? ' top' : '') + '">' +
      '<span class="qkp-rk num">' + esc(t.rank) + '</span>' + (moveChip(t, { word: false }) || '<span class="qkp-mv eq" title="No earlier snapshot yet">–</span>') +
      (href ? '<a class="qkp-who" href="' + esc(href) + '">' : '<span class="qkp-who">') + mark(t) + '<span><b>' + esc(t.name) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</span>' + (href ? '</a>' : '</span>') +
      bar(t) + '<span class="qkp-val num">' + esc(QKR.fmt(t.rating, fmtR)) + (isNum(t.delta) && !/^[+−±]?0(\.0+)?$/.test(QKR.fmt(t.delta, fmtD)) ? '<small class="' + (t.delta > 0 ? 'up' : 'dn') + '">' + esc(QKR.fmt(t.delta, fmtD)) + '</small>' : '') + '</span>' +
      '<span class="qkp-meta">' + meta + '</span>' +
      (t.note ? '<p class="qkp-note">' + esc(t.note) + '</p>' : '') + '</li>';
  }).join('');
  return key + '<ol class="qkp-list">' + rows + '</ol>';
};

/* ───────────────────────────── a position's tables (site pages) */
QKR.groupTables = function (g, o) {
  o = o || {};
  var m = g.metric || {}, st = g.stats || [];
  function table(rows, cap) {
    var C = o.cols || {};
    return '<table class="qk-table qkp-gt"><caption>' + esc(cap) + '</caption><thead><tr><th class="num">Rk</th><th>' + esc(C.player || 'Player') + '</th><th>' + esc(C.team || 'Team') + '</th>' +
      '<th class="num" title="' + esc(m.tip || m.label || '') + '">' + esc(m.label || '') + (m.unit ? ' (' + esc(m.unit) + ')' : '') + '</th>' +
      st.map(function (s) { return '<th class="num"' + (s.tip ? ' title="' + esc(s.tip) + '"' : '') + '>' + esc(s.label) + '</th>'; }).join('') + '<th class="num" title="Percentile in the group: 100 is the best">Pctl</th></tr></thead><tbody>' +
      rows.map(function (p) {
        var href = rel(o.base, p.href);
        return '<tr><td class="num">' + esc(p.rank) + '</td><td>' + (href ? '<a href="' + esc(href) + '">' + esc(p.name) + '</a>' : esc(p.name)) + (p.sub ? ' <small class="qk-sub">' + esc(p.sub) + '</small>' : '') + '</td><td>' + esc(p.team || '') + '</td>' +
          '<td class="num"><b>' + esc(QKR.fmt(p.value, m.fmt)) + '</b></td>' + st.map(function (s, i) { return '<td class="num">' + esc(QKR.fmt((p.stats || [])[i], s.fmt)) + '</td>'; }).join('') +
          '<td class="num">' + esc(isNum(p.pct) ? p.pct : '—') + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  return '<div class="qkp-gts"><div class="qkp-gt-w">' + table(g.top || [], 'Top ' + (g.top || []).length + ': ' + (g.label || '')) + '</div>' +
    ((g.bottom || []).length ? '<div class="qkp-gt-w">' + table(g.bottom, 'Bottom ' + g.bottom.length + ': ' + (g.label || '')) + '</div>' : '') + '</div>' +
    '<p class="qkp-sd-foot">' + esc(g.n + ' qualified' + (g.min ? ' (' + g.min + ')' : '') + '. Ranked on ' + (m.label || 'the headline metric') + (m.dir === 'lower' ? ', lower is better' : '') + '. ' + (m.tip || '')) + '</p>';
};

/* ───────────────────────────── movers (site pages) */
function movers(doc) {
  var ts = (doc.teams || []).filter(function (t) { return isNum(t.move); });
  var up = ts.filter(function (t) { return t.move > 0; }).sort(function (a, b) { return (b.move - a.move) || (a.rank - b.rank); }).slice(0, 3);
  var dn = ts.filter(function (t) { return t.move < 0; }).sort(function (a, b) { return (a.move - b.move) || (a.rank - b.rank); }).slice(0, 3);
  return { up: up, dn: dn };
}
function moversHTML(doc, o) {
  var mv = movers(doc), one = (doc.teams || [])[0];
  if (!one && !mv.up.length && !mv.dn.length) return '';
  function card(t, kind) {
    var href = rel(o.base, t.href);
    return (href ? '<a class="qkp-mvc ' + kind + '" href="' + esc(href) + '"' : '<span class="qkp-mvc ' + kind + '"') + ' style="--tc:' + col(t.colour) + '">' +
      '<span class="qkp-mvc-n num">' + (t.move > 0 ? '▲' : '▼') + Math.abs(t.move) + '</span>' + mark(t) +
      '<span class="qkp-mvc-w"><b>' + esc(short(t)) + '</b><small>' + esc(ord(t.prev) + ' → ' + ord(t.rank)) + '</small></span>' + (href ? '</a>' : '</span>');
  }
  return '<div class="qkp-movers">' +
    (one ? '<div class="qkp-mv-col"><div class="qkp-mv-h">No. 1</div>' + card(Object.assign({}, one, { move: one.move || 0 }), 'one').replace(/<span class="qkp-mvc-n num">[^<]*<\/span>/, '<span class="qkp-mvc-n num">1</span>') + '</div>' : '') +
    (mv.up.length ? '<div class="qkp-mv-col"><div class="qkp-mv-h up">Climbing since ' + esc(sinceWord(doc)) + '</div>' + mv.up.map(function (t) { return card(t, 'up'); }).join('') + '</div>' : '') +
    (mv.dn.length ? '<div class="qkp-mv-col"><div class="qkp-mv-h dn">Sliding</div>' + mv.dn.map(function (t) { return card(t, 'dn'); }).join('') + '</div>' : '') + '</div>';
}

/* ───────────────────────────── a site's power page */
QKR.page = function (el, o) {
  o = o || {};
  if (!el) return;
  var st = { top: 10, g: null };
  el.innerHTML = '<div class="qkp-page">' + QK.skeleton('lines', 4) + '</div>';
  var go = o.doc ? Promise.resolve(o.doc) : QK.fetchJSON(o.url);
  return go.then(function (doc) {
    if (!el.isConnected) return;
    if (!doc || !doc.teams || !doc.teams.length) { el.innerHTML = QK.empty('Power rankings are not built yet', 'They appear after the next build of this site.'); return; }
    var groups = ((doc.players || {}).groups || []);
    /* doc.players.head {kicker, title, sub, home}: a sport without positions names its own split (F1, tennis, golf) */
    var PH = (doc.players || {}).head || {};
    st.g = groups.length ? (o.group && groups.some(function (g) { return g.key === o.group; }) ? o.group : groups[0].key) : null;
    var r = doc.rating || {}, snaps = doc.snapshots || [], noun = doc.noun || 'teams';
    var one1 = noun.replace(/s$/, '');
    var chips = (o.leagues || []).length > 1 ? '<nav class="qk-chips scroll qkp-lg" aria-label="League">' + o.leagues.map(function (l) {
      return '<a class="qk-chip" href="' + esc(l.href) + '" aria-pressed="' + (l.key === doc.league ? 'true' : 'false') + '">' + esc(l.label) + '</a>'; }).join('') + '</nav>' : '';
    var nTop = Math.min(doc.teams.length, 10);
    var one = snaps.length < 2;
    var segTop = doc.teams.length > 12 && !one ? '<div class="qk-seg" id="qkp-top" role="group" aria-label="How many lines"><button type="button" aria-pressed="true" data-value="10">Top 10</button><button type="button" aria-pressed="false" data-value="20">Top 20</button></div>' : '';
    el.innerHTML = '<div class="qkp-page">' + (o.head || '') + chips +
      QK.sectionHead({ kicker: 'Power rankings · ' + doc.label + ' · ' + (doc.season_label || doc.season || ''), title: doc.phase === 'offseason' ? 'Final ranking: every ' + one1 : doc.phase === 'preseason' ? 'Preseason ranking: every ' + one1 : 'Every ' + one1 + ', ranked', size: 'lg',
        sub: 'Ranked by ' + lc1(r.label || 'our rating') + (r.unit ? ' (' + r.unit + ')' : '') + ', the model’s view of who is best now, not the table. The arrows are the move since ' + sinceWord(doc) + '. ' + (doc.phase === 'offseason' ? 'The season is over: this is where it finished.' : '') }) +
      moversHTML(doc, o) +
      '<section class="qk-section qkp-sec"><header class="qk-sh"><div class="qk-sh-main"><div class="qk-sh-kicker">The climb</div><h2 class="qk-sh-title">How the top <span class="qkr-n">' + nTop + '</span> got here</h2><p class="qk-sh-sub">' + (one ? 'Rank at each snapshot. The climb starts with the next one, a ' + esc(doc.step || 'week') + ' from now.' : 'Rank at each snapshot, ' + esc(snaps[0].label + ' to ' + snaps[snaps.length - 1].label) + '. Hover or tap a line to follow one ' + esc(noun.replace(/s$/, '')) + '.') + '</p></div>' + (segTop ? '<div class="qk-sh-actions">' + segTop + '</div>' : '') + '</header>' +
        '<div class="qk-card"><div class="qk-card-body"><div id="qkp-bump"></div></div></div></section>' +
      '<section class="qk-section qkp-sec"><header class="qk-sh"><div class="qk-sh-main"><div class="qk-sh-kicker">The rankings</div><h2 class="qk-sh-title">All ' + doc.teams.length + ' ' + esc(noun) + '</h2>' +
        '<p class="qk-sh-sub">' + esc((r.tip || '') + ' The small number under the rating is its change since ' + sinceWord(doc) + '.') + '</p></div></header>' +
        '<div class="qk-card"><div class="qk-card-body">' + QKR.list(doc, o) + '</div></div></section>' +
      (groups.length ? '<section class="qk-section qkp-sec"><header class="qk-sh"><div class="qk-sh-main"><div class="qk-sh-kicker">' + esc(PH.kicker || ((doc.players.noun === 'players' ? 'Players' : cap(doc.players.noun || 'Players')) + ' by position')) + '</div><h2 class="qk-sh-title">' + esc(PH.title || 'Best and worst at every position') + '</h2>' +
        '<p class="qk-sh-sub">' + esc(PH.sub || 'Every dot is a qualified player on the position’s headline number, worse to the left, better to the right; the top three in their team colour, the bottom three in coral. Tap a position for its top five and bottom three.') + '</p></div></header>' +
        '<div class="qk-card"><div class="qk-card-body"><div id="qkp-sp"></div></div></div>' +
        '<div class="qk-chips scroll qkp-gch" id="qkp-gch" role="group" aria-label="' + esc(PH.chips || 'Position') + '">' + groups.map(function (g) { return '<button type="button" class="qk-chip" data-value="' + esc(g.key) + '" aria-pressed="' + (g.key === st.g ? 'true' : 'false') + '">' + esc(g.label) + '</button>'; }).join('') + '</div>' +
        '<div class="qk-card"><div class="qk-card-body" id="qkp-gt"></div></div></section>' : '') +
      ((doc.notes || []).length ? '<p class="qk-sub qkp-notes">' + doc.notes.map(esc).join(' ') + '</p>' : '') + '</div>';
    if (QK.stamp) QK.stamp(doc.updated_at, { what: 'The power rankings are rebuilt with the rest of the site after each round of games.' });
    var setN = function (n) { var s = el.querySelector('.qkr-n'); if (s && n) s.textContent = n; };
    QKR.mountBump(el.querySelector('#qkp-bump'), doc, { base: o.base, top: st.top, onDraw: setN });
    var seg = el.querySelector('#qkp-top');
    if (seg) QK.seg(seg, function (v) { st.top = +v; QKR.mountBump(el.querySelector('#qkp-bump'), doc, { base: o.base, top: st.top, onDraw: setN }); });
    if (groups.length) {
      QKR.mountSpectrum(el.querySelector('#qkp-sp'), groups, { base: o.base });
      var gt = el.querySelector('#qkp-gt');
      var paint = function () { var g = groups.filter(function (x) { return x.key === st.g; })[0]; gt.innerHTML = g ? QKR.groupTables(g, { base: o.base, cols: (doc.players || {}).cols }) : ''; if (o.onGroup) o.onGroup(st.g); };
      paint();
      QK.chips(el.querySelector('#qkp-gch'), function (v) { st.g = v[0] || st.g; paint(); });
    }
    return doc;
  }, function () {
    if (el.isConnected) el.innerHTML = QK.empty('Power rankings did not load', 'The file is missing or the connection dropped. Try again in a minute.');
  });
};
function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
/* lower-case the first letter only, and leave an acronym or a name ("Elo", "DOTS") alone */
function lc1(s) { s = String(s || ''); return /^(Our|The|A|An|Rating|Expected)/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s; }
var BY = { week: 'week by week', race: 'race by race', round: 'round by round', month: 'month by month', event: 'event by event', test: 'window by window' };

/* ───────────────────────────── Home: the No. 1 in every sport, then the climb and the spectrum for one sport */
QKR.home = function (el, P, o) {
  o = o || {};
  if (!el) return;
  var sports = ((P || {}).sports || []).filter(function (s) { return s && s.leagues && s.leagues.length && QK.sport(s.sport) && QK.visible(QK.sport(s.sport)); });
  if (!sports.length) { el.innerHTML = ''; el.hidden = true; return; }
  var st = { sport: o.sport || sports[0].sport, league: null };
  var cache = {};
  function sp() { return sports.filter(function (s) { return s.sport === st.sport; })[0] || sports[0]; }
  function lg() { var s = sp(); var l = s.leagues.filter(function (x) { return x.league === st.league; })[0]; return l || s.leagues.filter(function (x) { return x.league === s.default; })[0] || s.leagues[0]; }
  var strip = sports.map(function (s) { var l = s.leagues.filter(function (x) { return x.league === s.default; })[0] || s.leagues[0];
    return { sport: s.sport, label: s.label + (s.leagues.length > 1 ? ' · ' + l.label : ''), top: (l.top || [])[0], kind: l.kind, step: l.step, phase: l.phase, season_label: l.season_label, rating: l.rating }; });
  el.innerHTML = QK.sectionHead({ kicker: 'Power rankings · every sport', title: 'Who’s on top, and who’s climbing',
      sub: 'Our ratings, ranked: the No. 1 in every sport, how the top ten got there, and the best and worst players at every position. Pick a sport.' }) +
    '<div class="qkp-hm-strip">' + QKR.no1Strip(strip, { active: st.sport }) + '</div>' +
    '<div class="qkp-hm-bar"><div class="qk-chips scroll" id="qkp-hm-sp" role="group" aria-label="Sport">' + sports.map(function (s) { return '<button type="button" class="qk-chip" data-value="' + esc(s.sport) + '" aria-pressed="' + (s.sport === st.sport ? 'true' : 'false') + '">' + esc(s.label) + '</button>'; }).join('') + '</div>' +
      '<div id="qkp-hm-lg"></div></div>' +
    '<div class="qkp-hm-panel"><div class="qk-card qkp-hm-a"><div class="qk-card-body"><div class="qkp-hm-h" id="qkp-hm-ha"></div><div id="qkp-hm-bump"></div></div></div>' +
      '<div class="qk-card qkp-hm-b"><div class="qk-card-body"><div class="qkp-hm-h" id="qkp-hm-hb"></div><div id="qkp-hm-sp2"></div></div></div></div>';
  var stripEl = el.querySelector('.qkp-hm-strip');
  function pickSport(k, scroll) {
    st.sport = k; st.league = null;
    stripEl.querySelectorAll('.qkp-no1').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-sport') === k); });
    el.querySelectorAll('#qkp-hm-sp .qk-chip').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-value') === k ? 'true' : 'false'); });
    paint();
    if (scroll) { var pn = el.querySelector('.qkp-hm-bar'); if (pn && pn.scrollIntoView) pn.scrollIntoView({ behavior: QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth', block: 'start' }); }
  }
  stripEl.addEventListener('click', function (ev) { var b = ev.target.closest ? ev.target.closest('.qkp-no1') : null; if (b) pickSport(b.getAttribute('data-sport'), true); });
  QK.chips(el.querySelector('#qkp-hm-sp'), function (v) { if (v[0]) pickSport(v[0], false); });
  function paint() {
    var s = sp(), l = lg(), base = QK.sportUrl(s.sport);
    var where = s.label === l.label ? s.label : s.label + ' · ' + l.label;
    var lgEl = el.querySelector('#qkp-hm-lg');
    /* a scrolling row of chips: football has 18 leagues (a segmented control widened the page past the screen) */
    lgEl.innerHTML = s.leagues.length > 1 ? '<div class="qk-chips scroll" role="group" aria-label="League">' + s.leagues.map(function (x) { return '<button type="button" class="qk-chip" data-value="' + esc(x.league) + '" aria-pressed="' + (x.league === l.league ? 'true' : 'false') + '">' + esc(x.label) + '</button>'; }).join('') + '</div>' : '';
    if (s.leagues.length > 1) QK.chips(lgEl.querySelector('.qk-chips'), function (v) { if (v[0]) { st.league = v[0]; paint(); } });
    var ha = el.querySelector('#qkp-hm-ha'), hb = el.querySelector('#qkp-hm-hb'), bump = el.querySelector('#qkp-hm-bump'), spe = el.querySelector('#qkp-hm-sp2');
    var href = base + '#/power' + (s.leagues.length > 1 ? '?l=' + encodeURIComponent(l.league) : '');
    if (s.power_href) href = base + s.power_href.replace('{league}', encodeURIComponent(l.league));
    if (l.power_href) href = base + l.power_href;
    ha.innerHTML = '<div><div class="qk-sh-kicker">' + esc(where + ' · the climb') + '</div><h3>' + esc(l.kind === 'players' ? 'The top ' + (l.noun || 'players') : 'The top ' + (l.noun || 'teams')) + ', ' + esc(l.phase === 'offseason' ? 'as the season ended' : (BY[l.step] || 'week by week')) + '</h3></div><a class="qk-more" href="' + esc(href) + '">Full power rankings</a>';
    hb.innerHTML = '';
    bump.innerHTML = '<div class="qk-skel block" style="height:300px"></div>'; spe.innerHTML = '';
    var url = base + 'data/' + l.file, key = s.sport + ':' + l.league, tok = key + Math.random();
    el._qkpTok = tok;
    var got = cache[key] || (cache[key] = QK.fetchJSON(url));
    got.then(function (doc) {
      if (el._qkpTok !== tok || !el.isConnected) return;
      QKR.mountBump(bump, doc, { base: base, compact: true });
      var gs = ((doc.players || {}).groups || []);
      var pb = el.querySelector('.qkp-hm-b');
      pb.hidden = !gs.length;
      el.querySelector('.qkp-hm-panel').classList.toggle('one', !gs.length);
      if (gs.length) {
        var PH = (doc.players || {}).head || {};
        hb.innerHTML = '<div><div class="qk-sh-kicker">' + esc(where + ' · ' + (PH.home || 'by position')) + '</div><h3>' + esc(PH.title || 'Best and worst at every position') + '</h3></div><span class="qkp-hm-cap">Each dot a qualified ' + esc(((doc.players || {}).noun || 'player').replace(/s$/, '')) + ' · better →</span>';
        QKR.mountSpectrum(spe, gs, { base: base, max: o.maxGroups || 9 });
      }
    }, function () {
      if (el._qkpTok !== tok) return;
      delete cache[key];
      bump.innerHTML = '<p class="qk-sub">This sport’s power rankings did not load. <a href="' + esc(href) + '">Open them on its site</a>.</p>';
    });
  }
  paint();
};

root.QKR = QKR;
})(typeof window !== 'undefined' ? window : this);
