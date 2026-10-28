/* The Quant Footballer — football charts on the kit (QKC, ECharts 5.5): pitches, shot maps, formations, radar,
 * rating colours, and a few series helpers. Everything takes its colours from the tokens at paint time, so the
 * theme toggle repaints it. Exposed as FB.charts.
 *
 *   FB.charts.shotMap(el, shots, opts)     shots [{x, y (Sofascore: distance from the goal line, across, 0-100),
 *                                          side: 'home'|'away', outcome: goal|save|post|block|miss, xg, name, href}]
 *                                          opts {surface: 'full'|'half', label, homeName, awayName}
 *   FB.charts.formation(el, spec)          spec {surface: 'half'|'full', points: [{x, y, label, sub, color, ring, href, tip}]}
 *                                          x, y in 0-100 of the surface (half: x across, y up from the own goal line 0-50)
 *   FB.charts.xiPoints(xi, formation)      a team's XI on the upright half pitch: [{p, x, y}]
 *   FB.charts.lineupPoints(list, formation, side)   starters on the full horizontal pitch (home left): [{e, x, y}] | null
 *   FB.charts.radar(el, spec)              spec {axes: [{name, max}], series: [{name, values, color}], label}
 *   FB.charts.ratingColor(r)               Sofascore-style rating colour from the status tokens
 *   FB.charts.outcomeOf(shot)              goal|save|post|block|miss from a shot row (match or season shot lists) */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum;

/* A match rating (1-10) on the kit's percentile scale (cold to hot, STYLE_GUIDE 3): 5.8 or less at the cold end, 7.0
   (about a typical starter) grey in the middle, 8.2 or more at the hot end. ratingPct for the scale position,
   ratingInk for the number on it (black or white, whichever reads). */
function ratingPct(r) { return Math.max(0, Math.min(100, (Number(r) - 5.8) / 2.4 * 100)); }
function ratingColor(r) {
  if (!isNum(r)) return QK.cssVar('--ink-4') || '#6e7681';
  return QK.pctHex(ratingPct(r));
}
function ratingInk(r) { return isNum(r) ? QK.pctInk(ratingPct(r)) : 'var(--ink-1)'; }

function outcomeOf(s) {
  var t = String(s.shot_type || s.type || s.outcome || '').toLowerCase();
  if (t === 'goal') return 'goal';
  if (t === 'save') return 'save';
  if (t === 'post') return 'post';
  if (t.indexOf('block') >= 0) return 'block';
  return 'miss';
}
var OUTCOMES = [['goal', 'Goal'], ['save', 'Saved'], ['post', 'Woodwork'], ['block', 'Blocked'], ['miss', 'Off target']];
/* One colour per shot outcome, shared by the shot map and the goal mouth, set on the series too so the legend keys
   match the dots: a goal in volt (what happened), a save cyan, the woodwork red-orange, blocked and off target grey.
   Never cobalt: blue is reserved for ours. */
function outcomeColours(T) { return { goal: T.volt, save: T.cat[2], post: T.cat[1], block: T.ink3, miss: T.ink4 }; }

/* ── surfaces (SVG, chart coordinates with y up, drawn as the container's background) */
function strokeOf(T) { return T.dark ? 'rgba(255,255,255,0.22)' : 'rgba(13,17,23,0.28)'; }
function halfPitchSVG(T) {
  /* upright attacking half: 68 m across, 52.5 m from the goal line (top) to halfway (bottom) */
  var st = strokeOf(T), fill = T.dark ? 'rgba(255,255,255,0.025)' : 'rgba(13,17,23,0.025)';
  var g = '<rect x="0" y="0" width="68" height="52.5" fill="' + fill + '" stroke="none"/>' +
    '<path d="M0 0H68V52.5H0Z"/><path d="M13.84 0V16.5H54.16V0"/><path d="M24.84 0V5.5H43.16V0"/>' +
    '<path d="M30.34 0V-1.2H37.66V0" stroke-width="2"/><circle cx="34" cy="11" r="0.45" fill="' + st + '"/>' +
    '<path d="M26.69 16.5A9.15 9.15 0 0 0 41.31 16.5"/><path d="M24.85 52.5A9.15 9.15 0 0 1 43.15 52.5"/>';
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-0.5 -1.5 69 54.5" preserveAspectRatio="none"><style>path,circle,rect{vector-effect:non-scaling-stroke}</style>' +
    '<g fill="none" stroke="' + st + '" stroke-width="1.25">' + g + '</g></svg>';
}
function surfaceBg(kind, T) {
  return 'url("data:image/svg+xml,' + encodeURIComponent(kind === 'half' ? halfPitchSVG(T) : QKC.surfaceSVG('pitch', T)) + '")';
}

/* ── shot map */
function shotXY(s, surface) {
  var x = Number(s.x), y = Number(s.y);
  if (surface === 'half') return [y * 0.68, 52.5 - x * 1.05];
  return s.side === 'away' ? [x * 1.05, (100 - y) * 0.68] : [(100 - x) * 1.05, y * 0.68];
}
function shotMap(el, shots, o) {
  o = o || {};
  el = typeof el === 'string' ? document.getElementById(el) : el;
  if (!el) return null;
  var surface = o.surface === 'half' ? 'half' : 'full';
  var list = (shots || []).filter(function (s) { return isNum(s.x) && isNum(s.y); });
  if (!list.length) { el.innerHTML = '<p class="fb-muted">No shot locations.</p>'; el.style.removeProperty('--h'); return null; }
  el.classList.add('qk-chart', 'sq', 'qk-surface', 'fb-pitch-chart');
  el.style.setProperty('--ar', surface === 'half' ? '68 / 54.5' : '105 / 68');
  return QKC.mount(el, function (T) {
    el.style.backgroundImage = surfaceBg(surface, T);
    var colour = outcomeColours(T);
    var series = OUTCOMES.map(function (k) {
      var pts = list.filter(function (s) { return outcomeOf(s) === k[0]; });
      return {
        type: 'scatter', name: k[1], z: k[0] === 'goal' ? 4 : 2, itemStyle: { color: colour[k[0]] },
        symbolSize: function (v) { return Math.max(6, Math.sqrt(isNum(v[2]) ? v[2] : 0.05) * (o.sizeScale || 34)); },
        data: pts.map(function (s) {
          var p = shotXY(s, surface);
          var c = colour[k[0]];
          return { value: [p[0], p[1], s.xg], name: s.name || '', href: s.href, s: s,
            itemStyle: { color: k[0] === 'miss' || k[0] === 'block' ? QKC.hexA(c, 0.45) : c, borderColor: k[0] === 'goal' ? T.s1 : c, borderWidth: k[0] === 'goal' ? 1.5 : 1 } };
        })
      };
    }).filter(function (x) { return x.data.length; });
    var ax = surface === 'half' ? [[-0.5, 68.5], [-1.5, 53]] : [[0, 105], [0, 68]];
    var graphic = [];
    if (surface === 'full' && (o.homeName || o.awayName)) {
      graphic.push({ type: 'text', right: 8, bottom: 6, style: { text: (o.homeName || 'Home') + ' attacking →', fill: T.ink3, font: '600 11px ' + T.fontUI }, silent: true });
      graphic.push({ type: 'text', left: 8, bottom: 6, style: { text: '← ' + (o.awayName || 'Away') + ' attacking', fill: T.ink3, font: '600 11px ' + T.fontUI }, silent: true });
    }
    return {
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'value', min: ax[0][0], max: ax[0][1], show: false },
      yAxis: { type: 'value', min: ax[1][0], max: ax[1][1], show: false },
      legend: surface === 'half' ? { bottom: 4, left: 'center', icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 11 } } : { top: 6, left: 8, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 11 } },
      graphic: graphic,
      tooltip: QKC.tooltip(T, { formatter: function (p) {
        var s = (p.data || {}).s || {};
        var bits = [];
        if (isNum(s.time)) bits.push(s.time + (s.added_time ? '+' + s.added_time : '') + '\'');
        if (s.body_part || s.body) bits.push(String(s.body_part || s.body).replace(/-/g, ' '));
        if (s.situation) bits.push(String(s.situation).replace(/-/g, ' '));
        return '<div style="font-weight:600">' + esc(p.data.name || p.seriesName) + '</div>' + (s.match ? '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(s.match) + '</div>' : '') +
          (bits.length ? '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(bits.join(' · ')) + '</div>' : '') +
          QKC.tipRow(p.color, p.seriesName, isNum(s.xg) ? 'xG ' + Number(s.xg).toFixed(2) : '');
      } }),
      series: series
    };
  }, { label: o.label || 'Shot map' });
}

/* ── formations (HTML over an SVG pitch; no chart library needed) */
function xiPoints(xi, formation) {
  var list = (xi || []).filter(Boolean);
  if (!list.length) return [];
  var gkIdx = -1;
  list.forEach(function (p, i) { if (gkIdx < 0 && p.pos === 'G') gkIdx = i; });
  var gk = gkIdx >= 0 ? list[gkIdx] : null;
  var out = list.filter(function (p, i) { return i !== gkIdx; });
  var lines = String(formation || '').split('-').map(function (n) { return parseInt(n, 10); }).filter(function (n) { return n > 0; });
  var ordered = out;
  if (!lines.length || lines.reduce(function (a, b) { return a + b; }, 0) !== out.length) {
    var byPos = { D: [], M: [], F: [] };
    out.forEach(function (p) { (byPos[p.pos] || byPos.M).push(p); });
    lines = ['D', 'M', 'F'].map(function (k) { return byPos[k].length; }).filter(function (n) { return n > 0; });
    ordered = byPos.D.concat(byPos.M, byPos.F);
  }
  var pts = [];
  if (gk) pts.push({ p: gk, x: 50, y: 6 });
  var k = 0;
  lines.forEach(function (n, li) {
    var depth = 6 + (li + 1) * (40 / (lines.length + 0.4));
    var span = Math.min(80, 24 * (n - 1));
    for (var j = 0; j < n; j++, k++) {
      var across = n === 1 ? 50 : 50 - span / 2 + j * (span / (n - 1));
      if (ordered[k]) pts.push({ p: ordered[k], x: 100 - across, y: depth });
    }
  });
  return pts;
}
/* Starters on the horizontal full pitch, home attacking right. null when the line-up and formation do not add up. */
function lineupPoints(list, formation, side) {
  var starters = (list || []).filter(function (e) { return e.start; });
  var lines = String(formation || '').split('-').map(function (n) { return parseInt(n, 10); }).filter(function (n) { return n > 0; });
  var gk = starters.filter(function (e) { return e.pos === 'G'; });
  var out = starters.filter(function (e) { return e.pos !== 'G'; });
  if (starters.length !== 11 || gk.length !== 1 || lines.reduce(function (a, b) { return a + b; }, 0) !== 10) return null;
  var home = side === 'home';
  var pts = [{ e: gk[0], x: home ? 4 : 96, y: 50 }];
  var k = 0;
  lines.forEach(function (n, li) {
    var depth = 5 + (li + 1) * (42 / (lines.length + 0.5));
    var span = Math.min(76, 24 * (n - 1));
    for (var j = 0; j < n; j++, k++) {
      var across = n === 1 ? 50 : 50 - span / 2 + j * (span / (n - 1));
      pts.push({ e: out[k], x: home ? depth : 100 - depth, y: home ? across : 100 - across });
    }
  });
  return pts;
}
function formation(el, spec) {
  el = typeof el === 'string' ? document.getElementById(el) : el;
  if (!el) return;
  var s = spec || {};
  var half = s.surface !== 'full';
  var T = QKC.tokens();
  function paint() {
    var T2 = QKC.tokens();
    el.style.setProperty('--pitch', surfaceBg(half ? 'half' : 'full', T2));
    Array.prototype.forEach.call(el.querySelectorAll('.fb-xi-dot'), function (d) {
      var r = d.getAttribute('data-rt');
      if (r !== null && r !== '') d.style.background = ratingColor(Number(r));
      /* the number on the dot in black or white, whichever reads on its fill (AA on the pale rating colours) */
      var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(getComputedStyle(d).backgroundColor || '');
      if (m && QK.color) d.style.color = QK.color.ink(QK.color.hex([Number(m[1]), Number(m[2]), Number(m[3])]));
    });
  }
  el.className = 'fb-xi' + (half ? ' half' : ' full');
  el.innerHTML = (s.points || []).map(function (p) {
    /* half: x across (0-100, left to right), y up from the own goal (0-50) -> top% from the halfway line */
    var left = half ? p.x : p.x, top = half ? 100 - (p.y / 52.5) * 100 : 100 - p.y;
    var tag = p.href ? 'a' : 'span';
    return '<' + tag + ' class="fb-xi-p"' + (p.href ? ' href="' + esc(p.href) + '"' : '') + ' style="left:' + left.toFixed(1) + '%;top:' + top.toFixed(1) + '%"' + (p.tip ? ' data-tip="' + esc(p.tip) + '"' : '') + '>' +
      '<span class="fb-xi-dot"' + (isNum(p.rt) ? ' data-rt="' + p.rt + '"' : '') + ' style="' + (p.color ? 'background:' + esc(p.color) + ';' : '') + (p.ring ? 'box-shadow:0 0 0 2px ' + esc(p.ring) + ';' : '') + '">' + esc(p.mark || '') + '</span>' +
      '<span class="fb-xi-l">' + esc(p.label || '') + '</span>' + (p.sub ? '<span class="fb-xi-s">' + esc(p.sub) + '</span>' : '') + '</' + tag + '>';
  }).join('');
  el.setAttribute('role', 'img');
  if (s.label) el.setAttribute('aria-label', s.label);
  paint();
  QK.theme.onChange(function () { if (el.isConnected) setTimeout(paint, 40); });
  return T;
}

/* ── radar */
function radar(el, s) {
  return QKC.mount(el, function (T) {
    return {
      legend: s.series.length > 1 ? { bottom: 0, icon: 'rect', itemWidth: 12, itemHeight: 4, textStyle: { color: T.ink2 } } : undefined,
      tooltip: QKC.tooltip(T, { trigger: 'item' }),
      radar: {
        indicator: s.axes.map(function (a) { return { name: a.name, max: a.max || 100, min: a.min || 0 }; }),
        radius: s.series.length > 1 ? '56%' : '60%', center: ['50%', s.series.length > 1 ? '46%' : '50%'], splitNumber: 4,
        axisName: { color: T.ink2, fontSize: 10.5, fontFamily: T.fontUI },
        splitLine: { lineStyle: { color: T.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: T.grid } }
      },
      series: [{
        type: 'radar', symbol: 'circle', symbolSize: 4,
        data: s.series.map(function (x, i) {
          var c = x.color ? QK.color.ensure(x.color, T.s1, 3) : T.cat[i % 8];
          return { name: x.name, value: x.values.map(function (v) { return isNum(v) ? v : 0; }), lineStyle: { color: c, width: 2 }, itemStyle: { color: c }, areaStyle: { color: QKC.hexA(c, 0.16) } };
        })
      }]
    };
  }, { label: s.label || 'Percentile profile' });
}

FB.charts = {
  shotMap: shotMap, formation: formation, xiPoints: xiPoints, lineupPoints: lineupPoints, radar: radar,
  ratingColor: ratingColor, ratingInk: ratingInk, outcomeOf: outcomeOf, OUTCOMES: OUTCOMES, outcomeColours: outcomeColours, halfPitchSVG: halfPitchSVG, surfaceBg: surfaceBg
};
})(window.FB);
