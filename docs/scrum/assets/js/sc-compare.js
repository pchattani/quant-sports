/* The Quant Scrum — Compare and Progression (10 Nov 2026).
 *
 *   #/<S>/compare?t=<a>,<b>                 team v team: the tale of the tape on our ratings, form and the two-year
 *                                           profile (opponent-adjusted, percentiles among test sides), the head-to-head
 *                                           record and the meetings, the two ratings over time
 *   #/<S>/compare?p=<a>,<b>[,<c>]           player v player (the Scouting Room's Compare tab; ?view=players or
 *   #/<S>/compare/players                   #/<S>/compare/players open its defaults, ?grp=<group> a group's top two):
 *                                           position chips (each loads the group's top two by Scrum value), the
 *                                           group's key metrics from the spec first, then the rest by family
 *                                           (percentiles within each player's position group), "instead" links when
 *                                           the positions differ, what each does best, careers, where they sit
 *   #/<S>/progression?t=<a>,<b>..&m=&r=     two to four sides over time: our rating or World Rugby points month by
 *                                           month, and form year by year (win share, margin over our forecast, points)
 *   #/<S>/progression?p=<a>,<b>..           two to four careers year by year (kit QK.compareProgression) against each
 *                                           year's qualified players of the position (progression_ref.json)
 *
 * Reads <S>/teams.json, <S>/teams/<id>.json, <S>/players.json, <S>/players/<id>.json and <S>/progression_ref.json
 * (oddsmarkets/rugby/pages.py). Kit: QK.compareView / QK.tape, QK.verdicts, QKC.line, QKC.distribution,
 * QK.compareProgression (assets/qk/progression.js). Older-browser rule: no optional chaining, no nullish coalescing. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;
var MAXT = 4;

function ids(q, k) {
  var out = [];
  String((q || {})[k] || '').split(',').forEach(function (x) { x = x.trim(); if (x && out.indexOf(x) < 0) out.push(x); });
  return out;
}
function kindOf(q) { return (q || {}).p !== undefined && (q || {}).t === undefined ? 'p' : ((q || {}).view === 'players' ? 'p' : 't'); }
function cmpHref(S, kind, list, extra) { return SC.href(S, 'compare', null, (kind === 'p' ? 'p=' : 't=') + list.map(encodeURIComponent).join(',') + (extra ? '&' + extra : '')); }
function progHref(S, kind, list, extra) { return SC.href(S, 'progression', null, (kind === 'p' ? 'p=' : 't=') + list.map(encodeURIComponent).join(',') + (extra ? '&' + extra : '')); }
SC.cmpHref = cmpHref; SC.progHref = progHref;

function tabs(S, sec, kind) {
  var k = sec + kind;
  return U.tabs([{ key: 'comparet', label: 'Teams side by side', href: SC.href(S, 'compare', null, 'view=teams') },
    { key: 'comparep', label: 'Players side by side', href: SC.href(S, 'compare', null, 'view=players') },
    { key: 'progressiont', label: 'Team progression', href: SC.href(S, 'progression', null, 'view=teams') },
    { key: 'progressionp', label: 'Player progression', href: SC.href(S, 'progression', null, 'view=players') }], k);
}
function question(names) { return names.length > 1 ? names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?' : (names[0] || ''); }
function teamOpts(S, rows, sel) {
  return rows.map(function (r) { return '<option value="' + esc(r.id) + '"' + (String(r.id) === String(sel) ? ' selected' : '') + '>' + esc(SC.tname(S, r.id)) + (r.rank ? ' (' + r.rank + ')' : '') + '</option>'; }).join('');
}
/* every side with a team page: the ranked ones by rank, then the rest by name */
function teamRows(S, all) {
  var ranked = ((SC.ok(all) && all.teams) || []).slice().sort(function (a, b) { return (a.rank || 999) - (b.rank || 999); });
  var seen = {}; ranked.forEach(function (r) { seen[r.id] = 1; });
  var ts = SC.info(S).teams || {}, rest = [];
  Object.keys(ts).forEach(function (id) { if (!seen[id] && ts[id].active) rest.push({ id: id, rank: null }); });
  rest.sort(function (a, b) { return SC.tname(S, a.id).localeCompare(SC.tname(S, b.id)); });
  return ranked.concat(rest);
}
function mfmtT(m, v) {
  if (!isNum(v)) return '—';
  if (m && m.unit === '%') return Math.round(v * 100) + '%';
  return Math.abs(v) >= 100 ? fmt.num(v, 0) : fmt.num(v, 1);
}

/* ── team v team ──────────────────────────────────────────────────────── */
function compareTeams(page, P) {
  var S = P.S, q = P.query || {};
  page.innerHTML = U.head('Compare', 'Two sides side by side: our ratings, form, how each plays (per test over two years, opponent-adjusted, percentiles among test sides), the head-to-head record and the ratings over time.', SC.SNAME[S]) +
    tabs(S, 'compare', 't') + '<div id="cm-body">' + QK.skeleton('card', 2) + '</div>';
  var body = QK.$('#cm-body', page);
  return SC.load(S + '/teams.json').then(function (all) {
    if (!U.alive(body)) return;
    var rows = teamRows(S, all);
    if (rows.length < 2) { body.innerHTML = U.missing('The team catalogue', all); return; }
    var list = ids(q, 't').filter(function (id) { return SC.team(S, id); }).slice(0, 2);
    if (list.length < 2) {
      /* one side: its next opponent, else the side rated nearest; none: the top two */
      var fill = rows.filter(function (r) { return list.indexOf(String(r.id)) < 0; });
      if (!list.length) list = [String(rows[0].id), String(rows[1].id)];
      else list.push(String(fill[0].id));
    }
    return Promise.all([SC.load(S + '/teams/' + list[0] + '.json'), SC.load(S + '/teams/' + list[1] + '.json')]).then(function (res) {
      if (!U.alive(body)) return;
      var A = res[0], B = res[1];
      if (list.length === 2 && !ids(q, 't')[1] && SC.ok(A)) {
        var nx = (A.next || [])[0];
        var opp = nx ? (String(nx.home) === String(list[0]) ? nx.away : nx.home) : null;
        if (opp && String(opp) !== String(list[1]) && SC.team(S, opp) && SC.team(S, opp).active && ids(q, 't').length === 1) { SC.go(cmpHref(S, 't', [list[0], String(opp)])); return; }
      }
      if (!SC.ok(A) || !SC.ok(B)) { body.innerHTML = U.missing('A team page', SC.ok(A) ? B : A); return; }
      drawTeams(body, S, all, rows, list, A, B);
    });
  });
}

function drawTeams(body, S, all, rows, list, A, B) {
  var ta = A.team || SC.team(S, list[0]) || {}, tb = B.team || SC.team(S, list[1]) || {};
  var M = {}, groups = {}, gorder = [];
  ((SC.ok(all) && all.metrics) || []).forEach(function (m) { M[m.id] = m; if (!groups[m.group]) { groups[m.group] = []; gorder.push(m.group); } groups[m.group].push(m.id); });
  var pm = function (T) { return (T.profile && T.profile.m) || {}; };
  var formW = function (f) { return String(f || '').split('').filter(function (c) { return c === 'W'; }).length + 0.5 * String(f || '').split('').filter(function (c) { return c === 'D'; }).length; };
  var y12 = function (T, tid) {
    var since = new Date(QK.now() - 365 * 864e5).toISOString().slice(0, 10), r = [0, 0, 0];
    (T.results || []).forEach(function (c) { if (String(c.date).slice(0, 10) >= since) { var x = SC.result(S, c, tid); r[x === 'W' ? 0 : x === 'D' ? 1 : 2]++; } });
    return r;
  };
  var ya = y12(A, list[0]), yb = y12(B, list[1]);
  var wdl = function (f) { f = String(f || ''); if (!f) return '—'; var c = function (x) { return f.split('').filter(function (y) { return y === x; }).length; }; return c('W') + '–' + c('D') + '–' + c('L'); };
  var share = function (r) { var n = r[0] + r[1] + r[2]; return n ? (r[0] + 0.5 * r[1]) / n : null; };
  var tgroups = [{ label: 'Ratings', rows: [
    { label: 'Our rating', tip: 'Points better than an average test side on a neutral ground.', a: A.rating, b: B.rating, ta: SC.signed(A.rating, 1), tb: SC.signed(B.rating, 1) },
    { label: 'Attack', tip: 'Points scored against an average side, above the average.', a: A.att, b: B.att, ta: SC.signed(A.att, 1), tb: SC.signed(B.att, 1) },
    { label: 'Defence', tip: 'Points kept out against an average side, above the average.', a: A.dfn, b: B.dfn, ta: SC.signed(A.dfn, 1), tb: SC.signed(B.dfn, 1) },
    { label: 'World Rugby points', tip: 'Our rebuild of the official rankings from results with the published formula.', a: A.wr, b: B.wr, ta: SC.f(A.wr, 2), tb: SC.f(B.wr, 2) },
    { label: 'Rank in our ratings', better: 'low', a: A.rank, b: B.rank, ta: A.rank ? QK.ordinal(A.rank) : 'unranked', tb: B.rank ? QK.ordinal(B.rank) : 'unranked' }] },
    { label: 'Form', rows: [
      { label: 'Last ten tests', tip: 'Wins in the last ten (a draw is half).', a: formW(A.form), b: formW(B.form), ta: wdl(A.form), tb: wdl(B.form) },
      { label: 'Won, last 12 months', tip: 'Share of tests won in the last year (a draw is half).', a: share(ya), b: share(yb), ta: ya.join('–'), tb: yb.join('–') }] }];
  var pa = pm(A), pb = pm(B);
  gorder.forEach(function (g) {
    var rs = groups[g].filter(function (k) { return pa[k] && pb[k]; }).map(function (k) {
      var m = M[k];
      return { label: m.label, tip: m.style ? 'Style: neither end is better.' : (m.unit === '%' ? '' : 'Per test, opponent-adjusted.'), better: m.dir === 'lower' ? 'low' : 'high', a: pa[k].adj, b: pb[k].adj, ta: mfmtT(m, pa[k].v), tb: mfmtT(m, pb[k].v),
        pa: m.style ? null : pa[k].pct, pb: m.style ? null : pb[k].pct };
    }).filter(function (r) { return isNum(r.a) && isNum(r.b); });
    if (rs.length) tgroups.push({ label: g, rows: rs });
  });
  var noProf = !Object.keys(pa).length || !Object.keys(pb).length;
  /* the head to head */
  var h = (A.h2h || []).filter(function (r) { return String(r.opp) === String(list[1]); })[0];
  var meets = (A.results || []).filter(function (c) { return String(c.home) === String(list[1]) || String(c.away) === String(list[1]); });
  var gap = isNum(A.rating) && isNum(B.rating) ? A.rating - B.rating : null;
  var fav = isNum(gap) ? (gap >= 0 ? ta : tb) : null;
  var opts = teamOpts(S, rows, list[0]), opts2 = teamOpts(S, rows, list[1]);
  var pick = '<div class="sc-cmp-pick">' + QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="cm-a" aria-label="First side">' + opts + '</select>' },
    { label: 'v', html: '<select class="qk-select" id="cm-b" aria-label="Second side">' + opts2 + '</select>' }]) +
    '<div class="qk-chips"><a class="qk-chip" href="' + esc(cmpHref(S, 't', [list[1], list[0]])) + '">⇄ Swap</a><a class="qk-chip" href="' + esc(progHref(S, 't', list)) + '">Both over time →</a></div></div>';
  var html = U.card('Pick two sides', 'Ranked sides first, by our rank; then every side with a test in the last ten years', pick);
  html += '<section class="qk-section sc-sec">' + QK.sectionHead({ kicker: 'Side by side', title: question([ta.name, tb.name]),
    sub: 'Bar length = percentile among test sides (100 = best) where there is one, else each side’s share of the pair. The better number in each row is solid.' }) +
    U.card('', '', QK.tape({ left: { name: ta.name, short: ta.abbr, sub: SC.signed(A.rating, 1) + ' rating', colour: ta.colour, alt: ta.alt, href: SC.teamHref(S, list[0]) },
      right: { name: tb.name, short: tb.abbr, sub: SC.signed(B.rating, 1) + ' rating', colour: tb.colour, alt: tb.alt, href: SC.teamHref(S, list[1]) }, gap: true, groups: tgroups }) +
      (isNum(gap) ? U.note('<b>On a neutral ground</b> our ratings make ' + esc(fav.name) + ' ' + (Math.abs(gap) < 0.5 ? 'level with the other side' : 'about ' + Math.max(1, Math.round(Math.abs(gap))) + (Math.round(Math.abs(gap)) <= 1 ? ' point' : ' points') + ' better') + ' (the rating gap; home advantage, travel and rest move it on the day).') : '') +
      (noProf ? U.note('One of these sides has fewer than six tests with team statistics in two years, so the profile rows are missing; the ratings and form still compare.') : '')) + '</section>';
  /* head to head */
  var h2hHtml;
  if (h) {
    var nn = h.p, wa = h.w, wb = h.l;
    h2hHtml = QK.stats([{ label: 'Tests', value: String(nn), sub: 'since ' + SC.year(h.first) }, { label: ta.name + ' won', value: String(wa), sub: SC.pct(nn ? wa / nn : null, 0) },
      { label: 'Drawn', value: String(h.d), sub: '' }, { label: tb.name + ' won', value: String(wb), sub: SC.pct(nn ? wb / nn : null, 0) },
      { label: 'Points', value: (h.pf || 0) + '–' + (h.pa || 0), sub: ta.abbr + ' first' + (h.ro ? ', ' + h.ro + ' result-only' : '') }]);
    if (meets.length) {
      h2hHtml += U.table([{ label: 'Date', align: 'left' }, { label: 'Competition', align: 'left' }, { label: 'Venue', align: 'left' }, { label: 'Score' }, { label: 'Winner', align: 'left' }, { label: 'Our chance (' + esc(ta.abbr) + ')' }],
        meets.slice(0, 12).map(function (c) {
          var home = String(c.home) === String(list[0]), us = home ? c.hs : c.as, th = home ? c.as : c.hs, p = c.p ? (home ? c.p[0] : c.p[2]) : null;
          var win = us > th ? ta.name : us < th ? tb.name : 'Draw';
          return [{ v: c.date, html: '<a href="' + esc(SC.matchHref(S, c.id)) + '">' + esc(SC.date(c.date)) + '</a>' }, { v: c.comp, html: esc(SC.compName(c.comp)) },
            { v: home ? 0 : 1, html: esc(home ? ta.name + ' home' : c.neutral ? 'Neutral' : tb.name + ' home') }, { v: us - th, html: SC.scoreText(us, th, c.ro) }, { v: win, html: esc(win) }, { v: p || 0, html: isNum(p) ? SC.pct(p) : '—' }];
        }), { cls: 'sc-tbl' });
    }
  } else h2hHtml = QK.empty('These sides have not met in our data', 'Tests from 1871; the record fills in once they meet.');
  html += U.sec('Head to head', 'Every meeting in our data', (h && h.last ? 'Last met ' + esc(SC.date(h.last.date)) + ': ' + esc(ta.abbr) + ' ' + SC.scoreText(h.last.us, h.last.them, h.last.ro) + ' ' + esc(tb.abbr) + '. ' : '') + 'The most recent meetings with our pre-match chance for ' + esc(ta.name) + '.', U.card('', '', h2hHtml));
  html += U.sec('Over time', 'The two ratings, month by month', 'Our rating (points better than an average side) since 2000; the full history and form year by year are on the progression page.',
    U.card('', '', U.chart('cm-rating', 320, 'Our rating over time for both sides') + '<div class="qk-chips" style="margin-top:12px"><a class="qk-chip" href="' + esc(progHref(S, 't', list)) + '">Ratings and form over time →</a></div>'));
  body.innerHTML = html;
  var sa = QK.$('#cm-a', body), sb = QK.$('#cm-b', body);
  var go = function () { if (sa.value && sb.value && sa.value !== sb.value) SC.go(cmpHref(S, 't', [sa.value, sb.value])); };
  sa.addEventListener('change', go); sb.addEventListener('change', go);
  ratingLines(QK.$('#cm-rating', body), S, [{ id: list[0], T: A }, { id: list[1], T: B }], 'rating', '2000');
}

/* line colours for several sides: the team colours when every pair is clearly apart (RGB distance), else the kit's
   categorical palette, so two blues (France, New Zealand lifted off black) never share a chart */
function lineCols(S, list) {
  var c = SC.lineColours(S, list);
  var rgb = function (x) { var el = document.createElement('i'); el.style.color = x; document.body.appendChild(el); var v = getComputedStyle(el).color; el.parentNode.removeChild(el); var m = /(\d+)\D+(\d+)\D+(\d+)/.exec(v); return m ? [+m[1], +m[2], +m[3]] : null; };
  var v = c.map(rgb), ok = v.every(Boolean);
  for (var i = 0; ok && i < v.length; i++) for (var j = i + 1; j < v.length; j++) {
    var d = Math.sqrt(Math.pow(v[i][0] - v[j][0], 2) + Math.pow(v[i][1] - v[j][1], 2) + Math.pow(v[i][2] - v[j][2], 2));
    if (d < 110) ok = false;
  }
  if (ok) return c;
  var cat = (window.QKC && QKC.tokens ? QKC.tokens().cat : null) || ['#7d93ff', '#ff6a4d', '#38d2e6', '#d4ff3a'];
  return list.map(function (_, k) { return cat[k % cat.length]; });
}

/* rating (or World Rugby points) month by month for several sides on one time axis */
function ratingLines(el, S, items, key, from) {
  if (!el || !window.QKC) return;
  var cols = lineCols(S, items.map(function (x) { return x.id; }));
  var months = {};
  var hist = items.map(function (x) {
    var hh = (key === 'wr' ? x.T.wr_hist : x.T.rating_hist) || [];
    var o = {}; hh.forEach(function (h) { if (!from || h[0] >= from) { o[h[0]] = h[1]; months[h[0]] = 1; } });
    return o;
  });
  var xs = Object.keys(months).sort();
  if (xs.length < 3) { el.innerHTML = QK.empty('Not enough history to draw', ''); return; }
  /* each side's value carried forward to every month (a rating holds between tests) */
  var series = items.map(function (x, i) {
    var last = null, started = false;
    return { name: SC.tname(S, x.id), color: cols[i], step: key === 'wr' ? 'end' : undefined, data: xs.map(function (m) {
      if (hist[i][m] !== undefined) { last = hist[i][m]; started = true; }
      return started ? last : null;
    }) };
  });
  QKC.line(el, { x: xs.map(function (m) { return m + '-15'; }), xType: 'time', series: series, legend: true, endLabels: true,
    ref: key === 'wr' ? undefined : { y: 0, label: 'Average test side' }, step: key === 'wr' ? 'end' : undefined,
    yName: key === 'wr' ? 'World Rugby points (our rebuild)' : 'Our rating (points v an average side)', xName: 'Month', yFmt: key === 'wr' ? function (v) { return fmt.num(v, 0); } : function (v) { return SC.signed(v, 0); } });
}

/* ── player v player ──────────────────────────────────────────────────── */
var FAMILY = [['value', 'Value'], ['scoring', 'Scoring'], ['creating', 'Creating'], ['carrying', 'Carrying'], ['defence', 'Defence'], ['set piece', 'Set piece'], ['breakdown', 'Breakdown and work'], ['discipline', 'Discipline and handling'], ['kicking', 'Kicking']];
function boardIndex(bd) {
  var cols = bd.cols || [], ix = {};
  cols.forEach(function (c, i) { ix[c] = i; });
  var by = {};
  (bd.rows || []).forEach(function (r) { by[String(r[ix.id])] = r; });
  return { ix: ix, by: by };
}
/* the six position groups of the spec (docs/_design/metrics/rugby.json `groups`), their key metrics when the spec
   catalogue does not load (the same headline sets), and the Scouting Room's sub-navigation for the player pages */
var GROUPS = ['front_row', 'lock', 'back_row', 'halves', 'centres', 'back_three'];
var HEAD = { front_row: ['val80', 'tk', 'tkpct', 'car', 'lopct', 'rk', 'inv', 'pc'], lock: ['val80', 'tk', 'tkpct', 'car', 'm', 'rk', 'ml', 'pc'],
  back_row: ['val80', 'tk', 'car', 'm', 'db', 'tkpct', 'inv', 'pc'], halves: ['val80', 'pts', 'pas', 'kfh', 'kpct', 'gkp', 'ta', 'tk'],
  centres: ['val80', 'm', 'cb', 'db', 'car', 'off', 'ta', 'tk'], back_three: ['val80', 'm', 'cb', 'db', 'tries', 'mpc', 'kfh', 'tk'] };
var THIN = 10;
function scoutTabs(S, active) {
  return U.tabs([{ key: 'board', label: 'Board', href: SC.href(S, 'scout') }, { key: 'chart', label: 'Chart', href: SC.href(S, 'scout', null, 'view=chart') },
    { key: 'leaders', label: 'Leaders', href: SC.href(S, 'scout', null, 'view=leaders') }, { key: 'compare', label: 'Compare', href: SC.href(S, 'compare', null, 'view=players') },
    { key: 'progression', label: 'Progression', href: SC.href(S, 'progression', null, 'view=players') }], active);
}
function headOf(cat, g) { var h = cat && cat.headline ? cat.headline(g) : []; return h.length ? h : (HEAD[g] || HEAD.back_three); }
/* a group's players, best first: the qualified by Scrum value, then (only when the group is short) the rest by minutes */
function groupRows(bd, B, g) {
  var ix = B.ix, rows = (bd.rows || []).filter(function (r) { return r[ix.grp] === g; });
  var q = rows.filter(function (r) { return r[ix.q]; }).sort(function (a, b) { return (isNum(b[ix.val80]) ? b[ix.val80] : -99) - (isNum(a[ix.val80]) ? a[ix.val80] : -99); });
  var rest = rows.filter(function (r) { return !r[ix.q]; }).sort(function (a, b) { return (b[ix.min] || 0) - (a[ix.min] || 0); });
  return q.concat(rest);
}
function topOf(bd, B, g, n, not) {
  not = not || [];
  return groupRows(bd, B, g).map(function (r) { return String(r[B.ix.id]); }).filter(function (id) { return not.indexOf(id) < 0; }).slice(0, n);
}
function nQual(bd, B, g) { var ix = B.ix; return (bd.rows || []).filter(function (r) { return r[ix.grp] === g && r[ix.q]; }).length; }
/* the main group: the one with the most qualified players */
function mainGroup(bd, B) {
  var best = GROUPS[0], bn = -1;
  GROUPS.forEach(function (g) { var n = nQual(bd, B, g); if (n > bn) { bn = n; best = g; } });
  return best;
}
/* his partner in his own group: the most similar player of the group, else the group's best */
function partnerOf(bd, B, id, pf) {
  var ix = B.ix, r = B.by[String(id)];
  if (!r) return null;
  var g = r[ix.grp];
  var sim = ((pf && pf.similar) || []).filter(function (x) { var o = B.by[String(x.id)]; return o && o[ix.grp] === g && String(x.id) !== String(id); })[0];
  return sim ? String(sim.id) : (topOf(bd, B, g, 1, [String(id)])[0] || null);
}
function lc1(s) { s = String(s || ''); return /^Scrum /.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1); }

function comparePlayers(page, P) {
  var S = P.S, q = P.query || {};
  page.innerHTML = U.head('Compare players', 'Two or three players side by side, position first: each group’s key metrics lead, rates per 80 minutes over the last two years, shrunk toward the position, with each player’s percentile within his position group.', 'Scouting Room · ' + SC.SNAME[S]) +
    scoutTabs(S, 'compare') + '<div id="cm-body">' + QK.skeleton('card', 2) + '</div>';
  var body = QK.$('#cm-body', page);
  return Promise.all([SC.load(S + '/players.json'), QK.spec && QK.spec.load ? QK.spec.load('rugby') : Promise.resolve(null)]).then(function (res0) {
    if (!U.alive(body)) return;
    var bd = res0[0], cat = res0[1];
    if (!SC.ok(bd) || !(bd.rows || []).length) { body.innerHTML = U.missing('The player board', bd); return; }
    var B = boardIndex(bd);
    var list = ids(q, 'p').filter(function (id) { return B.by[id]; }).slice(0, 3);
    var fill = Promise.resolve(list);
    if (!list.length) {
      /* nobody picked: the top two of the asked group, else of the main group (the most qualified players) */
      var g0 = GROUPS.indexOf(q.grp) >= 0 ? q.grp : mainGroup(bd, B);
      fill = Promise.resolve(topOf(bd, B, g0, 2));
    } else if (list.length === 1) {
      /* one picked: the player most like him in his own group */
      fill = SC.load(S + '/players/' + list[0] + '.json').then(function (pf) {
        var p2 = partnerOf(bd, B, list[0], SC.ok(pf) ? pf : null);
        return p2 ? list.concat([p2]) : list;
      });
    }
    return fill.then(function (l2) {
      return Promise.all(l2.map(function (id) { return SC.load(S + '/players/' + id + '.json'); })).then(function (pfs) {
        if (!U.alive(body)) return;
        drawPlayers(body, S, bd, B, l2, pfs, cat);
      });
    });
  });
}

function drawPlayers(body, S, bd, B, list, pfs, cat) {
  var ix = B.ix;
  var E = list.map(function (id, i) { return { id: id, r: B.by[id], pf: SC.ok(pfs[i]) ? pfs[i] : null }; }).filter(function (e) { return e.r; });
  var grpA = E.length ? E[0].r[ix.grp] : mainGroup(bd, B);
  var same = E.every(function (e) { return e.r[ix.grp] === grpA; });
  var active = same ? grpA : null;
  /* the name boxes: the active group first (best first), then everyone else by name; team and position on each */
  var lbl = function (r) { return r[ix.n] + ' (' + SC.tabbr(S, r[ix.team]) + ', ' + SC.posName(r[ix.pos]) + ')'; };
  var first = groupRows(bd, B, active || grpA);
  var seen = {}; first.forEach(function (r) { seen[String(r[ix.id])] = 1; });
  var others = (bd.rows || []).filter(function (r) { return !seen[String(r[ix.id])]; }).sort(function (a, b) { return String(a[ix.n]).localeCompare(String(b[ix.n])); });
  var opts = first.concat(others).map(function (r) { return [String(r[ix.id]), lbl(r)]; });
  var lab = function (id) { var o = opts.filter(function (x) { return x[0] === id; })[0]; return o ? o[1] : ''; };
  var ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];
  var pick = '<div class="sc-cmp-slots">' + [0, 1, 2].map(function (i) {
    return '<label class="sc-cmp-slot" style="--ec:' + ECOL[i] + '"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span>' +
      '<input class="qk-input" list="cm-names" data-i="' + i + '" value="' + esc(E[i] ? lab(E[i].id) : '') + '" placeholder="Type a name" autocomplete="off"></label>';
  }).join('') + '<datalist id="cm-names">' + opts.map(function (o) { return '<option value="' + esc(o[1]) + '"></option>'; }).join('') + '</datalist></div>';
  /* position first: one chip per group (its top two by Scrum value), then what the group is judged on */
  var chips = '<div class="qk-chips sc-cmp-grps" role="group" aria-label="Position group">' + GROUPS.map(function (g) {
    var pair = topOf(bd, B, g, 2);
    if (pair.length < 2) return '';
    return '<a class="qk-chip" href="' + esc(cmpHref(S, 'p', pair)) + '"' + (g === active ? ' aria-current="true" aria-pressed="true"' : '') + '>' + esc(SC.GROUP[g]) + '</a>';
  }).join('') + '</div>';
  var keyLine = function (g) {
    var hs = headOf(cat, g).map(function (id) { var m = cat && cat.metric ? cat.metric(id, 'player') : null; return lc1(m ? m.label : (SC.scout && SC.scout.mmeta ? SC.scout.mmeta(id).label : id)); });
    return '<p class="sc-cmp-key"><b>' + esc(SC.GROUP[g] || g) + ':</b> ' + esc(hs.join(', ')) + ' — the metrics that best describe and predict a ' + esc(SC.GROUP1[g] || 'player') + '.</p>';
  };
  var lines = '';
  if (same) lines += keyLine(grpA);
  else {
    /* different positions: say so, and offer each a partner from his own group */
    var gs = []; E.forEach(function (e) { if (gs.indexOf(e.r[ix.grp]) < 0) gs.push(e.r[ix.grp]); });
    lines += '<p class="sc-cmp-key"><b>Different positions</b> (' + esc(gs.map(function (g) { return SC.GROUP[g]; }).join(', ')) + '): the key metrics of each lead, and each percentile is against the player’s own group.</p>' +
      '<div class="qk-chips sc-cmp-inst">' + E.map(function (e) {
        var p2 = partnerOf(bd, B, e.id, e.pf);
        return p2 ? '<a class="qk-chip" href="' + esc(cmpHref(S, 'p', [e.id, p2])) + '">Compare ' + esc(e.r[ix.n]) + ' with a ' + esc(SC.GROUP1[e.r[ix.grp]] || 'player') + ' instead →</a>' : '';
      }).join('') + '</div>';
  }
  /* thin groups: say so in one line */
  var thin = (same ? [grpA] : E.map(function (e) { return e.r[ix.grp]; })).filter(function (g, i, a) { return a.indexOf(g) === i && nQual(bd, B, g) < THIN; });
  thin.forEach(function (g) {
    lines += U.note('Early days for this group: only ' + nQual(bd, B, g) + ' qualified ' + esc(String(SC.GROUP[g] || g).toLowerCase()) + ' (' + Math.round(bd.min_q || 160) + '+ minutes in the last two years) so far; percentiles settle as more tests are played.');
  });
  var top = U.card('Pick a position, then the players', 'Each chip loads the two best qualified players of the group by Scrum value; or type any names (the group on screen is suggested first)', chips + lines + pick +
    (E.length >= 2 ? '<div class="qk-chips" style="margin-top:10px">' + (E.length === 2 ? '<a class="qk-chip" href="' + esc(cmpHref(S, 'p', [E[1].id, E[0].id])) + '">⇄ Swap</a>' : '') +
      '<a class="qk-chip" href="' + esc(progHref(S, 'p', E.map(function (e) { return e.id; }))) + '">Careers year by year →</a></div>' : ''));
  if (E.length < 2) {
    body.innerHTML = top + QK.empty('Pick at least two players', 'Type a name in each box, or pick a position above.');
    wirePick(body, S, opts); return;
  }
  var metrics = (bd.metrics || []);
  var MM = {}; metrics.forEach(function (m) { MM[m.id] = m; });
  var label = function (m) { return cat && cat.label ? cat.label(m.id, 'player', m.label) : m.label; };
  var tip = function (m) { return cat && cat.tip ? cat.tip(m.id, 'player', '') : ''; };
  var rowOf = function (m) {
    return { key: m.id, label: label(m), tip: tip(m), better: m.dir === 'lower' ? 'low' : 'high', values: E.map(function (e) { return e.r[ix[m.id]]; }),
      pctls: E.map(function (e) { var k = ix['p_' + m.id]; return k !== undefined ? e.r[k] : null; }), fmt: function (v) { return SC.vfmt(m.id, v); } };
  };
  /* the key metrics lead: the group's headline set (both groups' when they differ), then everything else by family */
  var keyIds = [];
  (same ? [grpA] : E.map(function (e) { return e.r[ix.grp]; })).forEach(function (g) { headOf(cat, g).forEach(function (id) { if (keyIds.indexOf(id) < 0 && MM[id] && ix[id] !== undefined) keyIds.push(id); }); });
  var groups = [{ label: same ? 'Key metrics · ' + (SC.GROUP[grpA] || '') : 'Key metrics of both positions', rows: keyIds.map(function (id) { return rowOf(MM[id]); }).filter(function (r) { return r.values.some(isNum); }) }];
  FAMILY.forEach(function (f) {
    var rs = metrics.filter(function (m) { return m.family === f[0] && ix[m.id] !== undefined && keyIds.indexOf(m.id) < 0; }).map(rowOf).filter(function (r) { return r.values.some(isNum); });
    if (rs.length) groups.push({ label: 'More · ' + f[1], rows: rs });
  });
  groups = groups.filter(function (g) { return g.rows.length; });
  var ents = E.map(function (e) {
    var tid = e.r[ix.team], t = SC.team(S, tid) || {};
    return { name: e.r[ix.n], short: QK.surname(e.r[ix.n]), abbr: QK.surname(e.r[ix.n]), href: SC.playerHref(S, e.id), colour: t.colour, alt: t.alt,
      sub: [t.abbr || '', SC.posName(e.r[ix.pos]), e.r[ix.gp] + ' tests', fmt.num(e.r[ix.min]) + ' min'].filter(Boolean).join(' · ') };
  });
  var short = ents.map(function (e) { return e.short; });
  var verd = E.map(function (e, i) {
    var best = null, bd2 = 0;
    groups.forEach(function (g) { g.rows.forEach(function (r) {
      var mine = r.pctls[i]; if (!isNum(mine)) return;
      var oth = r.pctls.filter(function (_, j) { return j !== i; }).map(function (v) { return isNum(v) ? v : 0; });
      var d = mine - Math.max.apply(null, oth);
      if (d > bd2) { bd2 = d; best = r; }
    }); });
    return best ? { title: 'Best on ' + best.label.toLowerCase(), who: short[i], text: 'best of the ' + E.length + ' (' + best.fmt(best.values[i]) + ', ' + QK.ordinal(Math.round(best.pctls[i])) + ' percentile).' } : null;
  });
  var quals = E.filter(function (e) { return !e.r[ix.q]; }).map(function (e) { return e.r[ix.n]; });
  var peer = same ? (SC.GROUP[grpA] || 'the position').toLowerCase() : 'each player’s own position group';
  var html = top;
  html += '<section class="qk-section sc-sec">' + QK.sectionHead({ kicker: 'Side by side', title: question(short),
    sub: (E.length === 2 ? 'Bar length = percentile against ' + peer + ' (100 = best). The better number in each row is solid.' : 'Value and percentile against ' + peer + ' (100 = best). The best in each row is marked.') + ' Every player with minutes since ' + SC.date(bd.from) + '.' }) +
    U.card('', '', QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) +
      (quals.length ? U.note(esc(quals.join(', ')) + (quals.length > 1 ? ' are' : ' is') + ' short of the ' + Math.round(bd.min_q || 160) + '-minute floor: read the percentiles as early.') : '') +
      (!same ? U.note('Different positions: each percentile is against the player’s own position group, so the bars compare standing, not raw output.') : '')) + '</section>';
  /* careers */
  var crow = function (label2, fn) { return [{ v: label2, html: esc(label2) }].concat(E.map(function (e) { var v = e.pf ? fn(e.pf) : null; return { v: v === null ? '' : v, html: v === null || v === undefined ? '—' : esc(String(v)) }; })); };
  var age = function (pf) { return isNum(pf.age) ? SC.f(pf.age, 1) : null; };
  html += U.sec('Careers', 'Their tests side by side', 'Tests in our data (from 1996 for line-ups), with the career caps from Wikipedia where we have them.',
    U.card('', '', U.table([{ label: '', align: 'left' }].concat(E.map(function (e) { return { label: e.r[ix.n] }; })), [
      crow('Age', age), crow('Tests in our data', function (pf) { return pf.caps; }), crow('Career caps (Wikipedia)', function (pf) { return pf.wcaps && pf.wcaps.caps ? pf.wcaps.caps : null; }),
      crow('Starts', function (pf) { return pf.starts; }), crow('Won–drawn–lost', function (pf) { return (pf.wdl || []).join('–'); }),
      crow('Points', function (pf) { return pf.pts; }), crow('Tries', function (pf) { return pf.tries; }),
      crow('First test', function (pf) { return pf.first ? SC.date(pf.first) : null; }), crow('Last test', function (pf) { return pf.last ? SC.date(pf.last) : null; })], { cls: 'sc-tbl' })));
  if (same) html += U.sec('Where they sit', 'Among the ' + esc(peer), 'Every qualified player of the position with each of these marked, on the group’s key metrics.', U.card('', '', '<div class="qk-seg" id="cm-dm" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('cm-dist', 260, 'Peer distribution with the players marked')));
  body.innerHTML = html;
  wirePick(body, S, opts);
  if (!same || !window.QKC) return;
  var grp = grpA;
  var keys = keyIds.slice(0, 6);
  var M = MM;
  var seg = QK.$('#cm-dm', body);
  seg.innerHTML = keys.map(function (k, i) { return '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + k + '">' + esc((cat && cat.short ? cat.short(k, 'player') : null) || (M[k] || {}).short || k) + '</button>'; }).join('');
  var PCT = { tkpct: 1, kpct: 1, lopct: 1 };
  var dd = function (k) {
    var m = M[k] || {};
    var vals = (bd.rows || []).filter(function (r) { return r[ix.grp] === grp && r[ix.q] && isNum(r[ix[k]]); }).map(function (r) { return PCT[k] ? r[ix[k]] * 100 : r[ix[k]]; });
    var el = QK.$('#cm-dist', body);
    if (vals.length < 8) { el.innerHTML = QK.empty('Too few qualified players of the position', 'The chart appears once eight or more have played enough minutes.'); return; }
    QKC.distribution(el, { values: vals, binCount: 20, lowerBetter: m.dir === 'lower', colorBy: 'flat', fmt: function (v) { return PCT[k] ? Math.round(v) + '%' : fmt.num(v, Math.abs(v) >= 20 ? 0 : 1); },
      xName: label(m.id ? m : { id: k, label: k }) + ' · ' + vals.length + ' qualified ' + peer, yName: 'Players', label: 'Distribution of ' + (m.label || k),
      marks: E.map(function (e, i) { var v = e.r[ix[k]]; return { x: isNum(v) ? (PCT[k] ? v * 100 : v) : null, label: short[i], color: ['wpA', 'wpB', 'c5'][i] }; }).filter(function (x) { return isNum(x.x); }) });
  };
  if (keys.length) { dd(keys[0]); QK.seg(seg, dd); }
}
function wirePick(body, S, opts) {
  QK.$$('.sc-cmp-slots input', body).forEach(function (inp) {
    inp.addEventListener('change', function () {
      var out = [0, 1, 2].map(function (i) {
        var v = String((QK.$('.sc-cmp-slots input[data-i="' + i + '"]', body) || {}).value || '').trim();
        if (!v) return null;
        var lv = v.toLowerCase();
        var hit = opts.filter(function (o) { return o[1] === v; })[0] || opts.filter(function (o) { return o[1].toLowerCase().indexOf(lv) === 0; })[0] || opts.filter(function (o) { return o[1].toLowerCase().indexOf(lv) >= 0; })[0];
        return hit ? hit[0] : null;
      }).filter(Boolean);
      if (out.length) SC.go(cmpHref(S, 'p', out));
    });
  });
}

/* ── team progression ─────────────────────────────────────────────────── */
var FORM = [['win', 'Win share'], ['perf', 'Margin over our forecast'], ['pf', 'Points for and against']];
function teamProgression(page, P) {
  var S = P.S, q = P.query || {};
  page.innerHTML = U.head('Progression', 'Up to four sides over time: our rating and World Rugby points month by month, and form year by year against what our model expected.', SC.SNAME[S]) +
    tabs(S, 'progression', 't') + '<div id="pg-body">' + QK.skeleton('chart', 2) + '</div>';
  var body = QK.$('#pg-body', page);
  return SC.load(S + '/teams.json').then(function (all) {
    if (!U.alive(body)) return;
    var rows = teamRows(S, all);
    var list = ids(q, 't').filter(function (id) { return SC.team(S, id) && SC.team(S, id).active; }).slice(0, MAXT);
    if (!list.length) list = rows.slice(0, 2).map(function (r) { return String(r.id); });
    return Promise.all(list.map(function (id) { return SC.load(S + '/teams/' + id + '.json'); })).then(function (res) {
      if (!U.alive(body)) return;
      var items = list.map(function (id, i) { return { id: id, T: res[i] }; }).filter(function (x) { return SC.ok(x.T); });
      drawTeamProg(body, S, rows, items, q);
    });
  });
}

function drawTeamProg(body, S, rows, items, q) {
  var list = items.map(function (x) { return x.id; });
  var st = { key: q.m === 'wr' ? 'wr' : 'rating', from: q.r === 'all' ? '' : (q.r === '1987' ? '1987' : '2000'), form: FORM.some(function (f) { return f[0] === q.f; }) ? q.f : 'win' };
  var names = items.map(function (x) { return (x.T.team || {}).name || SC.tname(S, x.id); });
  var hasWr = items.some(function (x) { return (x.T.wr_hist || []).length > 2; });
  var addOpts = rows.filter(function (r) { return list.indexOf(String(r.id)) < 0; });
  var pick = '<form class="sc-cmp-add" id="pg-add" autocomplete="off"><label>Add a side <select class="qk-select" id="pg-sel"><option value="">Pick…</option>' + teamOpts(S, addOpts, '') + '</select></label>' +
    items.map(function (x) { return '<a class="qk-chip" href="' + esc(progHref(S, 't', list.filter(function (y) { return y !== x.id; }).length ? list.filter(function (y) { return y !== x.id; }) : list)) + '" aria-label="Remove ' + esc(SC.tname(S, x.id)) + '">✕ ' + esc(SC.tabbr(S, x.id)) + '</a>'; }).join('') +
    (items.length === 2 ? '<a class="qk-chip" href="' + esc(cmpHref(S, 't', list)) + '">Side by side →</a>' : '') + '</form>';
  var seg = function (id, label, opts, cur) { return '<div class="qk-seg" role="group" id="' + id + '" aria-label="' + esc(label) + '">' + opts.map(function (o) { return '<button type="button" data-value="' + o[0] + '" aria-pressed="' + (o[0] === cur) + '">' + esc(o[1]) + '</button>'; }).join('') + '</div>'; };
  var html = U.card('Sides', 'Up to four; ranked sides first', pick);
  html += '<section class="qk-section sc-sec">' + QK.sectionHead({ kicker: 'Over time', title: question(names), sub: 'Month by month, each side’s value held between its tests.' }) +
    U.card('Rating', 'Our rating is points better than an average test side on a neutral ground; World Rugby points are our rebuild of the official table.',
      '<div class="sc-ctl">' + seg('pg-k', 'Measure', [['rating', 'Our rating']].concat(hasWr ? [['wr', 'World Rugby points']] : []), st.key) + seg('pg-r', 'Range', [['2000', 'Since 2000'], ['1987', 'Since 1987'], ['all', 'All']], st.from || 'all') + '</div>' +
      U.chart('pg-chart', 360, 'Ratings over time')) + '</section>';
  html += U.sec('Form', 'Year by year', 'Win share counts a draw as half. Margin over our forecast is the average points by which a side beat (or fell short of) our pre-match margin that year: above zero, better than the model expected. A year with one or two tests swings widely: the table below gives the counts.',
    U.card('', '', '<div class="sc-ctl">' + seg('pg-f', 'Form measure', FORM, st.form) + '</div>' + U.chart('pg-form', 320, 'Form year by year') + '<div id="pg-tbl" style="margin-top:14px"></div>'));
  body.innerHTML = html;
  var sel = QK.$('#pg-sel', body);
  sel.addEventListener('change', function () { if (!sel.value) return; var nx = list.slice(0, MAXT - 1).concat([sel.value]); SC.go(progHref(S, 't', nx, qs())); });
  function qs() { return 'm=' + st.key + '&r=' + (st.from || 'all') + '&f=' + st.form; }
  function rememb() { try { history.replaceState(null, '', progHref(S, 't', list, qs())); } catch (e) { /* file:// */ } }
  var drawR = function () { ratingLines(QK.$('#pg-chart', body), S, items, st.key, st.from); rememb(); };
  QK.seg(QK.$('#pg-k', body), function (v) { st.key = v; drawR(); });
  QK.seg(QK.$('#pg-r', body), function (v) { st.from = v === 'all' ? '' : v; drawR(); });
  QK.seg(QK.$('#pg-f', body), function (v) { st.form = v; drawF(); rememb(); });
  drawR();
  function drawF() { formChart(QK.$('#pg-form', body), QK.$('#pg-tbl', body), S, items, st.form); }
  drawF();
}

function formChart(el, tbl, S, items, kind) {
  if (!el) return;
  var cols = lineCols(S, items.map(function (x) { return x.id; }));
  var by = items.map(function (x) { var o = {}; (x.T.years || []).forEach(function (r) { o[r[0]] = r; }); return o; });
  var lo = 9999, hi = 0;
  by.forEach(function (o) { Object.keys(o).forEach(function (y) { y = +y; if (y < lo) lo = y; if (y > hi) hi = y; }); });
  if (!hi) { el.innerHTML = QK.empty('No tests in our data yet', ''); if (tbl) tbl.innerHTML = ''; return; }
  lo = Math.max(lo, kind === 'perf' ? hi - 25 : hi - 30);
  var xs = []; for (var y = lo; y <= hi; y++) xs.push(y);
  var val = function (r) {
    if (!r) return null;
    if (kind === 'win') return r[1] ? (r[2] + 0.5 * r[3]) / r[1] * 100 : null;
    if (kind === 'perf') return r[9];
    return r[1] ? (r[5] - r[6]) / r[1] : null;
  };
  var series = [];
  items.forEach(function (x, i) {
    series.push({ name: SC.tname(S, x.id), color: cols[i], symbols: true, data: xs.map(function (yy) { var v = val(by[i][yy]); return isNum(v) ? v : null; }) });
  });
  if (window.QKC) QKC.line(el, { x: xs.map(String), series: series, legend: true, endLabels: false,
    ref: kind === 'win' ? { y: 50, label: 'Half won' } : { y: 0, label: kind === 'perf' ? 'As forecast' : 'Level' },
    yName: kind === 'win' ? 'Tests won (%)' : kind === 'perf' ? 'Margin over our forecast (points per test)' : 'Points difference per test', xName: 'Year',
    yFmt: kind === 'win' ? function (v) { return Math.round(v) + '%'; } : function (v) { return SC.signed(v, 0); } });
  if (!tbl) return;
  var yrs = xs.slice(-12).reverse();
  var head = [{ label: 'Year', align: 'left' }].concat(items.map(function (x) { return { label: SC.tabbr(S, x.id) }; }));
  tbl.innerHTML = U.table(head, yrs.map(function (yy) {
    return [{ v: yy, html: String(yy) }].concat(items.map(function (x, i) {
      var r = by[i][yy];
      if (!r) return { v: '', html: '<span class="qk-muted">—</span>' };
      var t = r[2] + '–' + r[3] + '–' + r[4];
      var sub = kind === 'perf' ? (isNum(r[9]) ? SC.signed(r[9], 1) : '—') : kind === 'pf' ? (r[1] ? SC.signed((r[5] - r[6]) / r[1], 1) : '—') : (isNum(r[7]) && r[8] ? fmt.num(r[7], 1) + ' exp.' : '');
      return { v: val(r) || 0, html: '<span class="num">' + t + '</span>' + (sub ? ' <span class="qk-muted">' + esc(sub) + '</span>' : '') };
    }));
  }), { cls: 'sc-tbl' }) + U.note('Won–drawn–lost each year' + (kind === 'win' ? ', with the wins our pre-match chances expected (a draw is half).' : kind === 'perf' ? ', with the margin over our forecast per test.' : ', with the points difference per test.'));
  U.wire(tbl);
}

/* ── player progression ───────────────────────────────────────────────── */
var REF_P = {};
function refJson(S) { if (!REF_P[S]) REF_P[S] = SC.load(S + '/progression_ref.json'); return REF_P[S]; }
function ageAt(dob, y) {
  if (!dob) return null;
  var d = new Date(dob + 'T00:00:00Z'); if (isNaN(d)) return null;
  return (Date.UTC(y, 6, 1) - d.getTime()) / (365.25 * 864e5);
}
function toP(S, pf) {
  var cur = new Date(QK.now()).getUTCFullYear();
  var seasons = (pf.seasons || []).slice().sort(function (a, b) { return a.y - b.y; }).map(function (s, i) {
    var t = SC.team(S, s.team) || {};
    return { key: String(s.y), x: s.y, label: String(s.y), age: ageAt((pf.bio || {}).dob, s.y), cy: i + 1, team: s.team ? { abbr: t.abbr, name: t.name, colour: t.colour } : null,
      group: pf.grp, n: s.n, nUnit: 'tests', small: !s.q, partial: s.y === cur, values: s.v || {}, pct: s.q ? (s.pc || {}) : {} };
  });
  return { id: String(pf.id), name: pf.name, short: QK.surname(pf.name), href: SC.playerHref(S, pf.id), seasons: seasons };
}
function playerProgression(page, P) {
  var S = P.S, q = P.query || {};
  page.innerHTML = U.head('Progression', 'Up to four careers year by year on the Scouting Room’s numbers, each year against that year’s qualified players of the position: by year, by age or by career year.', SC.SNAME[S]) +
    scoutTabs(S, 'progression') + '<div id="pg-body">' + QK.skeleton('chart', 1) + '</div>';
  var body = QK.$('#pg-body', page);
  return Promise.all([SC.load(S + '/players.json'), refJson(S)]).then(function (res0) {
    if (!U.alive(body)) return;
    var bd = res0[0], ref = res0[1];
    if (!SC.ok(bd)) { body.innerHTML = U.missing('The player board', bd); return; }
    var B = boardIndex(bd), ix = B.ix;
    var list = ids(q, 'p').filter(function (x) { return /^[\w-]+$/.test(x); }).slice(0, MAXT);
    var fill = Promise.resolve(list);
    if (!list.length) {
      var top = (bd.rows || []).filter(function (r) { return r[ix.q]; }).sort(function (a, b) { return (b[ix.val80] || -99) - (a[ix.val80] || -99); });
      fill = Promise.resolve(top.slice(0, 2).map(function (r) { return String(r[ix.id]); }));
    } else if (list.length === 1) {
      fill = SC.load(S + '/players/' + list[0] + '.json').then(function (pf) { return list.concat(((SC.ok(pf) && pf.similar) || []).slice(0, 1).map(function (x) { return String(x.id); })); });
    }
    return fill.then(function (l2) {
      return Promise.all(l2.map(function (id) { return SC.load(S + '/players/' + id + '.json'); })).then(function (pfs) {
        if (!U.alive(body)) return;
        drawPlayerProg(body, S, bd, B, ref, pfs.filter(function (pf) { return SC.ok(pf) && pf.name; }), q);
      });
    });
  });
}

function drawPlayerProg(body, S, bd, B, ref, pfs, q) {
  var ix = B.ix;
  var Ps = pfs.map(function (pf) { return toP(S, pf); });
  var R = QK.prog.ref(SC.ok(ref) ? ref : {});
  var PCT = { tkpct: 1, kpct: 1, lopct: 1 };
  var ms = (bd.metrics || []).map(function (m) { return { id: m.id, label: m.label, unit: PCT[m.id] ? 'share' : (m.id === 'val80' ? 'points per 80' : 'per 80'), dir: m.dir, ours: m.id === 'val80' ? { name: 'Scrum value' } : null,
    tip: '', head: ['val80', 'pts', 'm', 'tk', 'car'].indexOf(m.id) >= 0, fmt: function (v) { return SC.vfmt(m.id, v); } }; });
  var names = Ps.map(function (p) { return p.short; });
  var grps = {}; Ps.forEach(function (p) { if (p.seasons.length) grps[p.seasons[0].group] = 1; });
  var peerOf = function (Pp) { var g = Pp.seasons.length ? Pp.seasons[0].group : null; return g ? (SC.GROUP[g] || 'peers').toLowerCase() : 'peers'; };
  var sugg = [];
  pfs.forEach(function (pf) { (pf.similar || []).forEach(function (x) { var id = String(x.id); if (Ps.length < MAXT && !Ps.some(function (p) { return p.id === id; }) && !sugg.some(function (s) { return s.id === id; })) sugg.push({ id: id, name: x.n, sub: 'Plays most like ' + pf.name, href: progHref(S, 'p', Ps.map(function (p) { return p.id; }).concat([id])) }); }); });
  var opts = (bd.rows || []).map(function (r) { return [String(r[ix.id]), r[ix.n] + ' (' + SC.tabbr(S, r[ix.team]) + ', ' + SC.posName(r[ix.pos]) + ')']; }).sort(function (a, b) { return a[1].localeCompare(b[1]); });
  var st = { metric: q.m || 'val80', x: q.x === 'age' || q.x === 'year' ? q.x : 'season', y: q.y === 'pct' ? 'pct' : 'value' };
  body.innerHTML = QK.sectionHead({ kicker: 'Careers', title: question(names) || 'Pick players',
    sub: (Object.keys(grps).length > 1 ? 'Different positions: the peer band is left out and percentiles are each against the player’s own group. ' : '') + 'A year here is a calendar year of tests. Hover a year for the team, the age and the tests; hollow points are years under the minutes floor; ' + new Date(QK.now()).getUTCFullYear() + ' is still in progress.' }) +
    U.card('', '', '<div id="pg-w"></div><form class="sc-cmp-add" id="pg-add" autocomplete="off"><label for="pg-in">Add or swap a player <input class="qk-input" id="pg-in" list="pg-dl" placeholder="Type a name"></label><datalist id="pg-dl">' +
      opts.map(function (o) { return '<option value="' + esc(o[1]) + '"></option>'; }).join('') + '</datalist><button class="qk-btn" type="submit">Add</button>' +
      Ps.map(function (Pp) { var rest = Ps.filter(function (x) { return x !== Pp; }).map(function (x) { return x.id; }); return rest.length ? '<a class="qk-chip" href="' + esc(progHref(S, 'p', rest)) + '" aria-label="Remove ' + esc(Pp.name) + '">✕ ' + esc(Pp.short) + '</a>' : ''; }).join('') +
      (Ps.length >= 2 && Ps.length <= 3 ? '<a class="qk-chip" href="' + esc(cmpHref(S, 'p', Ps.map(function (x) { return x.id; }))) + '">Side by side →</a>' : '') + '</form>') +
    U.note('Rates per 80 minutes, shrunk toward the position like every rate on the site; statistics run from about 2006, so earlier tests count as appearances only. The shaded band is the middle half of that year’s qualified players of the position.');
  var w = QK.$('#pg-w', body);
  if (!Ps.length) w.innerHTML = QK.empty('Pick a player', 'Type a name below.');
  else QK.compareProgression(w, { players: Ps, metrics: ms, metric: st.metric, x: st.x, y: st.y, height: 380,
    ref: function (Pp, Sx, id) { return R(Sx.group, Sx.key, id); }, peerName: peerOf, suggest: sugg.slice(0, 5),
    cyNote: 'Career year counts years with a test in our data, which has line-ups from 1996.',
    onState: function (s) { st.metric = s.metric; st.x = s.x; st.y = s.y; try { history.replaceState(null, '', progHref(S, 'p', Ps.map(function (x) { return x.id; }), 'm=' + encodeURIComponent(s.metric) + '&x=' + s.x + '&y=' + s.y)); } catch (e) { /* file:// */ } } });
  var form = QK.$('#pg-add', body);
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var v = String(QK.$('#pg-in', body).value || '').trim().toLowerCase();
    if (!v) return;
    var hit = opts.filter(function (o) { return o[1].toLowerCase() === v; })[0] || opts.filter(function (o) { return o[1].toLowerCase().indexOf(v) === 0; })[0] || opts.filter(function (o) { return o[1].toLowerCase().indexOf(v) >= 0; })[0];
    if (!hit) return;
    var next = Ps.map(function (x) { return x.id; }).filter(function (id) { return id !== hit[0]; });
    if (next.length >= MAXT) next.pop();
    SC.go(progHref(S, 'p', next.concat([hit[0]])));
  });
}

SC.route('compare', function (page, P) { return kindOf(P.query) === 'p' || P.id === 'players' ? comparePlayers(page, P) : compareTeams(page, P); });
SC.route('progression', function (page, P) { return kindOf(P.query) === 'p' || P.id === 'players' ? playerProgression(page, P) : teamProgression(page, P); });
})();
