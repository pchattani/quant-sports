/* The Quant Footballer — Fantasy (#/fantasy): our own FPL-style points, projections, picks and a suggested squad.
 *
 *   #/fantasy?l=<league>&v=<rank|gw|fdr|picks|squad|method>&p=<G|D|M|F>&max=<cost>&q=<text>&fd=<att|def>
 *
 * Reads data/fantasy/meta.json (scoring, the walk-forward backtest, the leagues) and data/fantasy/<league>.json
 * (players with projections per gameweek, the fixture-difficulty table, the picks and the optimised squad).
 * Method: docs/MODELS.md 11d; payloads: UNIFIED_PAYLOADS.md 12.4. Costs are our own proxy from the value model (the
 * payload's `price` field); official FPL costs and ownership are not used (the Premier League's terms forbid reuse). */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, signed = FB.signed;

var POS = ['G', 'D', 'M', 'F'];
var POS_LABEL = { G: 'Goalkeeper', D: 'Defender', M: 'Midfielder', F: 'Forward' };
var POS_SHORT = { G: 'GK', D: 'DEF', M: 'MID', F: 'FWD' };
var POS_SLOT = { G: 4, D: 1, M: 3, F: 8 };
var VIEWS = [['rank', 'Rankings'], ['gw', 'Next gameweek'], ['fdr', 'Fixtures'], ['picks', 'Picks'], ['squad', 'Suggested squad'], ['method', 'Method and backtest']];
var PART_LABEL = { app: 'Minutes', goals: 'Goals', assists: 'Assists', cs: 'Clean sheet', gc: 'Conceded', saves: 'Saves', cards: 'Cards', og_pm: 'OG / pen. miss', dc: 'Def. contribution', bonus: 'Bonus' };

function n1(v) { return isNum(v) ? Number(v).toFixed(1) : '—'; }
function pc(v) { return isNum(v) ? Math.round(v * 100) + '%' : '—'; }
function cost(v) { return isNum(v) ? '£' + Number(v).toFixed(1) + 'm' : '—'; }
function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function posColor(p) { return 'var(--c-' + (POS_SLOT[p] || 8) + ')'; }
function posHex(p) { return QK.cssVar('--c-' + (POS_SLOT[p] || 8)); }
function posTag(p) { return '<span class="fb-fa-pos" style="--k:' + posColor(p) + '" title="' + esc(POS_LABEL[p] || p) + '">' + esc(POS_SHORT[p] || p) + '</span>'; }
function plink(r) { return FB.playerLink(r.id, r.name || ('#' + r.id)); }
/* Crest files exist only where the league's teams.json names one: link without a crest otherwise. */
var CRESTS = {};
function clink(r) { return r.tid ? FB.clubLink(r.tid, r.club, { nocrest: !CRESTS[String(r.tid)] }) : esc(r.club || '—'); }
function href(q) { return '#/fantasy' + FB.qs(q); }
/* A v2 leaderboard (kit QK.leaderboard: bar cells) with FB.table's options. */
function board(id, cols, list, o) {
  var node = document.getElementById(id);
  o = o || {};
  return node ? QK.leaderboard(node, { columns: cols, rows: list, sort: o.sort || null, rank: !!o.rank, dense: true, maxHeight: o.maxHeight, caption: o.caption }) : null;
}

FB.route('fantasy', function (el, p) {
  var q = FB.merge(p.query || {}, {});
  el.innerHTML = FB.pageHead('Fantasy', 'Fantasy football projections', 'FPL-style points computed by us from Sofascore\'s match data and projected from our match model\'s expected goals, for every followed league. Costs are our own proxy from the player value model; FPL\'s official costs and ownership are not used (the Premier League\'s terms forbid reusing its data). For fun and research, not advice.') +
    '<div id="fa-top">' + FB.loading('lines', 3) + '</div><div id="fa-body" class="fb-mt"></div>';
  return FB.load('fantasy/meta.json').then(function (meta) {
    if (!FB.alive(el)) return;
    if (!meta || !(meta.leagues || []).length) { FB.set('fa-top', FB.empty('Not built yet', 'The fantasy payloads (data/fantasy/) arrive with the next hourly build.')); return; }
    var leagues = meta.leagues;
    if (!q.l || !leagues.some(function (x) { return x.slug === q.l; })) q.l = leagues[0].slug;
    return Promise.all([FB.load('fantasy/' + q.l + '.json'), FB.compFile(q.l, 'teams')]).then(function (d) {
      if (!FB.alive(el)) return;
      var doc = d[0], tm = (d[1] || {}).teams || {};
      Object.keys(tm).forEach(function (n) { if (tm[n].team_id && tm[n].crest) CRESTS[String(tm[n].team_id)] = 1; });
      if (!doc) { FB.set('fa-top', FB.empty('No fantasy file for this league')); return; }
      draw(el, meta, doc, q);
    });
  });
});

function draw(el, meta, doc, q) {
  var rows = FB.rows(doc);
  var byId = {};
  rows.forEach(function (r) { byId[r.id] = r; });
  var v = q.v || 'rank';
  if (VIEWS.every(function (x) { return x[0] !== v; })) v = 'rank';
  var bt = meta.backtest || {}, m = (bt.methods || {}).model || {}, l5 = (bt.methods || {}).last5 || {};
  var gw = (doc.gameweeks || [])[0];
  el.querySelector('#fa-top').innerHTML =
    FB.toolbar([FB.field('League', FB.select('fa-league', meta.leagues.map(function (x) { return [x.slug, x.name]; }), q.l, 'League'))]) +
    '<div class="fb-mt">' + FB.subnav(VIEWS.map(function (x) { return [href({ l: q.l, v: x[0] === 'rank' ? null : x[0] }), x[1], x[0]]; }), v, 'Fantasy views') + '</div>' +
    '<div class="fb-mt">' + FB.kpis([
      FB.kpi('Next gameweek', gw ? esc(gw.label) : '—', { text: true, sub: gw ? gw.n + ' fixtures' : 'no fixtures with a model line' }),
      FB.kpi('Players projected', String(rows.length), { sub: 'current squads of ' + esc(doc.name || '') }),
      FB.kpi('Backtest rank corr.', isNum(m.spearman_round_mean) ? num(m.spearman_round_mean, 2) : '—', { sub: 'per round · last-5 form ' + (isNum(l5.spearman_round_mean) ? num(l5.spearman_round_mean, 2) : '—'), tip: 'Spearman correlation of projected and actual points among a round\'s players, averaged over rounds, walk-forward.' }),
      FB.kpi('Top-20 picks scored', isNum(m.top20_actual_mean) ? n1(m.top20_actual_mean) : '—', { sub: 'points a round · form picks ' + (isNum(l5.top20_actual_mean) ? n1(l5.top20_actual_mean) : '—') })
    ]) + '</div>' +
    '<div class="fb-mt">' + FB.note('<b>Rank correlation</b> runs from 0 (no better than guessing) to 1 (every player in the right order). A single gameweek is mostly luck, so even a good projection misses often. Costs are our own proxy, not FPL\'s.') + '</div>';
  var sel = el.querySelector('#fa-league');
  if (sel) sel.addEventListener('change', function () { FB.go(href({ l: sel.value, v: q.v })); });
  var body = el.querySelector('#fa-body');
  if (v === 'gw') drawGW(el, body, doc, rows, byId);
  else if (v === 'fdr') drawFDR(el, body, doc, q);
  else if (v === 'picks') drawPicks(body, doc, byId);
  else if (v === 'squad') drawSquad(el, body, doc, byId);
  else if (v === 'method') drawMethod(el, body, meta);
  else drawRank(el, body, doc, rows, q);
}

// ── rankings ────────────────────────────────────────────────────────────────

function formCell(r) {
  if (!r.form_apps) return '<span class="qk-muted">—</span>';
  var d = (r.form_pts || 0) - (r.form_xpts || 0);
  return '<span data-tip="Last five club league matches: ' + n1(r.form_pts) + ' points, ' + n1(r.form_xpts) + ' from the underlying numbers">' + Math.round(r.form_pts || 0) + ' <span class="' + (d >= 0 ? 'fb-up' : 'fb-down') + '">(' + signed(d, 1) + ')</span></span>';
}

function drawRank(el, body, doc, rows, q) {
  var gws = doc.gameweeks || [];
  body.innerHTML = FB.card('', '', FB.toolbar([
    FB.field('Position', '<div class="qk-chips" id="fa-pos" role="group" aria-label="Position">' + [['', 'All']].concat(POS.map(function (p) { return [p, POS_LABEL[p] + 's']; })).map(function (x) {
      return '<button class="qk-chip" type="button" data-value="' + x[0] + '" aria-pressed="' + ((q.p || '') === x[0]) + '"' + (x[0] ? ' style="--ca:' + posColor(x[0]) + '"' : '') + '>' + esc(x[1]) + '</button>';
    }).join('') + '</div>'),
    FB.field('Max cost (£m)', '<input class="qk-input fb-fa-num" type="number" id="fa-max" min="4" max="15" step="0.5" value="' + esc(q.max || '') + '">'),
    FB.field('Player', '<input class="qk-input" type="search" id="fa-q" placeholder="Find a player" value="' + esc(q.q || '') + '">')
  ]) + '<p class="fb-cap" id="fa-note"></p>') +
    '<div class="fb-mt">' + FB.card('Cost against projection', 'Next-5-gameweek projection by cost for the players shown (top 150); the further above the crowd, the more points for the money. Colour is the position.', FB.chartBox('fa-sc', 360, 'Projection by cost') + '<div class="qk-legend fb-mt">' + POS.map(function (p) { return '<span><i class="dot" style="--k:' + posColor(p) + '"></i>' + POS_LABEL[p] + 's</span>'; }).join('') + '</div>') + '</div>' +
    '<div class="fb-mt">' + FB.card('Rankings', 'Sorted by the next five gameweeks.', '<div id="fa-table"></div>', { flush: true }) + '</div>';
  var redraw = function () {
    var qn = q.q ? norm(q.q) : '';
    var maxP = isNum(q.max) && q.max !== '' ? Number(q.max) : null;
    var list = rows.filter(function (r) { return (!q.p || r.pos === q.p) && (maxP === null || (r.price || 0) <= maxP) && (!qn || norm(r.name).indexOf(qn) >= 0); })
      .sort(function (a, b) { return (b.h5 || 0) - (a.h5 || 0); });
    var shown = list.slice(0, 150);
    FB.set('fa-note', list.length + ' players' + (list.length > shown.length ? ' (top ' + shown.length + ' shown)' : '') + ' · Next 5 = projected points over the next ' + Math.min(5, gws.length) + ' gameweeks; ROS = every remaining gameweek with a model line (' + doc.n_gameweeks + '). Tiers break where the next-5 projection drops sharply within a position. Form: points in the last five league matches and, in brackets, points above what the underlying numbers were worth — a big positive number is luck likely to fade.');
    board('fa-table', [
      { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return plink(r); } },
      { key: 'pos', label: 'Pos', fmt: function (v) { return posTag(v); } },
      { key: 'club', label: 'Club', fmt: function (v, r) { return clink(r); } },
      { key: 'price', label: 'Cost', num: true, tip: 'Our cost proxy (from the value model), £m', fmt: function (v) { return cost(v); } },
      { key: 'next', label: 'Next GW', num: true, fmt: function (v) { return n1(v); } },
      { key: 'h5', label: 'Next 5', type: 'bar', fmt: function (v) { return '<b>' + n1(v) + '</b>'; }, tip: 'Our projected points over the next five gameweeks' },
      { key: 'ros', label: 'ROS', num: true, tip: 'Rest of season', fmt: function (v) { return n1(v); } },
      { key: 'tier', label: 'Tier', num: true, fmt: function (v) { return v ? '<span class="fb-fa-tier t' + Math.min(v, 6) + '">' + v + '</span>' : '—'; } },
      { key: 'e_min', label: 'xMin', num: true, tip: 'Expected minutes a match', fmt: function (v) { return isNum(v) ? Math.round(v) + '\'' : '—'; } },
      { key: 'p_goal', label: 'P(goal)', num: true, tip: 'Chance of scoring in the next gameweek', fmt: function (v) { return pc(v); } },
      { key: 'cs', label: 'CS', num: true, tip: 'Chance of a clean sheet (60+ minutes) next gameweek', fmt: function (v) { return pc(v); } },
      { key: 'season_pts', label: 'Season', num: true, tip: 'Points this season in the league' },
      { key: 'formd', label: 'Form (v underlying)', num: true, fmt: function (v, r) { return formCell(r); } }
    ], shown.map(function (r) { return FB.merge(r, { formd: (r.form_pts || 0) - (r.form_xpts || 0) }); }), { rank: true, maxHeight: 640, caption: 'Fantasy rankings' });
    if (!shown.length) FB.set('fa-table', FB.empty('No player clears the filters'));
    var box = el.querySelector('#fa-sc');
    var pts = shown.filter(function (r) { return isNum(r.price) && isNum(r.h5); });
    if (pts.length < 3) { box.style.height = 'auto'; box.innerHTML = FB.muted('Too few players for a chart.'); return; }
    box.style.height = '';
    QKC.scatter(box, {
      points: pts.map(function (r) { return { x: r.price, y: r.h5, name: r.name + ' · ' + (r.club || '') + ' · ' + POS_SHORT[r.pos], color: posHex(r.pos), size: 10, href: FB.href.player(r.id), label: FB.surname(r.name) }; }),
      xName: 'Cost (£m, our proxy)', yName: 'Next 5 GW points', xFmt: function (v) { return '£' + num(v, 1); }, yFmt: function (v) { return num(v, 0); }, labelTop: 10, label: 'Projection by cost'
    });
  };
  QK.chips(el.querySelector('#fa-pos'), function (vals) { q.p = vals[0] || ''; FB.setQuery({ p: q.p || null }); redraw(); });
  var t = null;
  [['fa-max', 'max'], ['fa-q', 'q']].forEach(function (x) {
    var inp = el.querySelector('#' + x[0]);
    if (inp) inp.addEventListener('input', function () { clearTimeout(t); t = setTimeout(function () { q[x[1]] = inp.value || ''; var pt = {}; pt[x[1]] = inp.value || null; FB.setQuery(pt); redraw(); }, 300); });
  });
  redraw();
}

// ── next gameweek ───────────────────────────────────────────────────────────

function drawGW(el, body, doc, rows, byId) {
  var gw = (doc.gameweeks || [])[0];
  var parts = doc.parts || [];
  var top = rows.slice().sort(function (a, b) { return (b.next || 0) - (a.next || 0); }).slice(0, 30);
  var cap = ((doc.picks || {}).captain || []).map(function (id) { return byId[id]; }).filter(Boolean);
  body.innerHTML = FB.card('Captain picks', (gw ? esc(gw.label) + ' · ' : '') + 'the highest projections for the gameweek (a double gameweek adds both fixtures).',
    '<div class="fb-fa-caps">' + cap.map(function (r, i) {
      return '<div class="fb-fa-cap" style="--k:' + posColor(r.pos) + '"><span class="fb-fa-cap-r">' + (i + 1) + '</span><div class="fb-fa-cap-n">' + plink(r) + ' ' + posTag(r.pos) +
        '<div class="fb-fa-sub">' + esc(r.club || '') + ' · ' + cost(r.price) + '</div></div><div class="fb-fa-cap-p"><b class="fb-num">' + n1(r.next) + '</b><span>pts</span><div class="fb-fa-sub">goal ' + pc(r.p_goal) + ' · G/A ' + pc(r.p_ga) + '</div></div></div>';
    }).join('') + '</div>') +
    '<div class="fb-mt">' + FB.card('Where the points come from', 'The top 15 for the gameweek, expected points by scoring component.', FB.chartBox('fa-gw-chart', 460, 'Expected points by component')) + '</div>' +
    '<div class="fb-mt">' + FB.card('Top 30 for the gameweek', 'Expected points by scoring component.', '<div id="fa-gw"></div>', { flush: true }) + '</div>';
  var t15 = top.slice(0, 15);
  var shownParts = parts.map(function (p, i) { return [p, i]; }).filter(function (x) { return t15.some(function (r) { return Math.abs(((r.next_parts || [])[x[1]]) || 0) >= 0.05; }); });
  if (t15.length && shownParts.length) QKC.bar(el.querySelector('#fa-gw-chart'), {
    horizontal: true, stack: true, legend: true, labelWidth: 130, fmt: function (v) { return num(v, 2); }, valName: 'Expected points', catName: 'Player',
    cats: t15.map(function (r) { return r.name; }),
    series: shownParts.map(function (x) { return { name: PART_LABEL[x[0]] || x[0], data: t15.map(function (r) { return Math.round((((r.next_parts || [])[x[1]]) || 0) * 100) / 100; }) }; }),
    hrefs: t15.map(function (r) { return FB.href.player(r.id); }), label: 'Expected points by component'
  });
  var cols = [
    { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return plink(r); } },
    { key: 'pos', label: 'Pos', fmt: function (v) { return posTag(v); } },
    { key: 'club', label: 'Club', fmt: function (v, r) { return clink(r); } },
    { key: 'price', label: 'Cost', num: true, fmt: function (v) { return cost(v); } },
    { key: 'next', label: 'Total', num: true, fmt: function (v) { return '<b>' + n1(v) + '</b>'; } }
  ].concat(parts.map(function (p, i) { return { key: 'part' + i, label: PART_LABEL[p] || p, num: true, fmt: function (v) { return isNum(v) ? num(v, 2) : '—'; } }; }));
  FB.table('fa-gw', cols, top.map(function (r) { var o = FB.merge(r, {}); parts.forEach(function (p, i) { o['part' + i] = (r.next_parts || [])[i]; }); return o; }), { rank: true });
}

// ── fixture difficulty ──────────────────────────────────────────────────────

function drawFDR(el, body, doc, q) {
  var mode = q.fd === 'def' ? 'def' : 'att';
  var gws = (doc.gameweeks || []).slice(0, 6);
  var fdr = (doc.fdr || []).slice().sort(function (a, b) { return mode === 'att' ? (b.xg_for || 0) - (a.xg_for || 0) : (b.cs_sum || 0) - (a.cs_sum || 0); });
  var cell = function (fx) {
    if (!fx || !fx.length) return '<span class="fb-fa-fdr r0">—</span>';
    return fx.map(function (x) {
      var rating = mode === 'att' ? x[4] : x[5];
      return '<span class="fb-fa-fdr r' + rating + '" data-tip="' + esc(x[0]) + (x[1] ? ' (home)' : ' (away)') + ': expected goals for ' + num(x[2], 2) + ', against ' + num(x[3], 2) + '">' +
        esc(String(x[0] || '').slice(0, 3).toUpperCase()) + (x[1] ? '' : '<i>a</i>') + '<b>' + num(mode === 'att' ? x[2] : x[3], 1) + '</b></span>';
    }).join('');
  };
  body.innerHTML = FB.card('Fixture difficulty', 'The next six gameweeks from the match model\'s expected goals. 1 (green) is the easiest fifth of the league\'s fixtures, 5 (red) the hardest; <i>a</i> is away.',
    FB.toolbar([FB.seg('fa-fd', [['att', 'Attackers (goals for)'], ['def', 'Defenders (goals against)']], mode, 'Difficulty for')]) +
    '<div class="fb-fa-legend">' + [1, 2, 3, 4, 5].map(function (r) { return '<span class="fb-fa-fdr r' + r + '">' + r + '</span>'; }).join('') + '<span class="qk-muted">easiest → hardest · sorted by ' + (mode === 'att' ? 'expected goals for' : 'expected clean sheets') + ' over six gameweeks</span></div>' +
    '<div class="qk-table-wrap fb-fa-fdrwrap"><table class="qk-table dense"><thead><tr><th class="sticky-col">Club</th><th class="num">' + (mode === 'att' ? 'xG for' : 'xCS') + '</th>' +
    gws.map(function (g) { return '<th title="' + esc(g.label) + '">GW' + g.gw + '</th>'; }).join('') + '</tr></thead><tbody>' +
    fdr.map(function (c) {
      return '<tr><td class="sticky-col">' + clink(c) + '</td><td class="num">' + num(mode === 'att' ? c.xg_for : c.cs_sum, 1) + '</td>' +
        gws.map(function (g, i) { return '<td class="fb-fa-fdrc">' + cell((c.gws || [])[i]) + '</td>'; }).join('') + '</tr>';
    }).join('') + '</tbody></table></div>') +
    '<div class="fb-mt">' + FB.card(mode === 'att' ? 'Expected goals over six gameweeks' : 'Expected clean sheets over six gameweeks', 'Every club, from the same projections.', FB.chartBox('fa-fdr-chart', Math.max(320, fdr.length * 20), 'Six-gameweek totals by club')) + '</div>';
  FB.wireSeg(el, 'fa-fd', function (v) { FB.setQuery({ v: 'fdr', fd: v === 'def' ? 'def' : null }, true); });
  if (fdr.length) QKC.bar(el.querySelector('#fa-fdr-chart'), {
    horizontal: true, labels: true, labelWidth: 130, fmt: function (v) { return num(v, 1); }, valName: mode === 'att' ? 'Expected goals for' : 'Expected clean sheets', catName: 'Club',
    cats: fdr.map(function (c) { return c.club; }), series: [{ name: mode === 'att' ? 'xG for' : 'Expected clean sheets', data: fdr.map(function (c) { return Math.round((mode === 'att' ? c.xg_for : c.cs_sum) * 10) / 10; }) }],
    hrefs: fdr.map(function (c) { return c.tid ? FB.href.club(c.tid) : null; }), label: 'Six-gameweek totals'
  });
}

// ── picks ───────────────────────────────────────────────────────────────────

function pickCard(title, sub, ids, byId, extra) {
  var rs = (ids || []).map(function (id) { return byId[id]; }).filter(Boolean);
  return '<section class="qk-card fb-fa-pick"><div class="qk-card-head"><div class="fb-card-titles"><h3 class="qk-card-title">' + esc(title) + '</h3><div class="qk-card-sub">' + esc(sub) + '</div></div></div><div class="qk-card-body">' +
    (rs.length ? '<ol class="fb-fa-list">' + rs.map(function (r) {
      return '<li><div class="fb-fa-li-top"><span class="fb-fa-li-n">' + plink(r) + ' ' + posTag(r.pos) + '</span><b class="fb-num">' + n1(r.h5) + '</b></div>' +
        '<div class="fb-fa-sub">' + esc(r.club || '') + ' · ' + cost(r.price) + (extra ? ' · ' + extra(r) : '') + '</div></li>';
    }).join('') + '</ol>' : FB.muted('Nobody fits.')) + '</div></section>';
}
function drawPicks(body, doc, byId) {
  var p = doc.picks || {};
  var luck = function (r) { return 'last 5: ' + Math.round(r.form_pts || 0) + ' pts v ' + n1(r.form_xpts) + ' underlying'; };
  var xmin = function (r) { return 'xMin ' + Math.round(r.e_min || 0); };
  body.innerHTML = '<p class="fb-cap">Our suggested picks from the projections; the right-hand number is the next five gameweeks. Model suggestions, not advice.</p><div class="fb-fa-picks">' +
    POS.map(function (k) { return pickCard('Best buys: ' + POS_LABEL[k] + 's', 'projected well above what players at their cost usually score', (p.buys || {})[k], byId, xmin); }).join('') +
    pickCard('Bargains (£6.5m or less)', 'most projected points per £m above the floor', p.value, byId, xmin) +
    pickCard('Differentials', 'top-tier projection, outside the top 15 at their position by points so far (no ownership data: FPL\'s is not used)', p.differentials, byId, function (r) { return (r.season_pts || 0) + ' pts so far'; }) +
    pickCard('Transfer out', 'scored well so far, projected well below that over the next five', p.sell, byId, function (r) { return (r.season_pts || 0) + ' pts in ' + (r.season_apps || 0) + ' apps'; }) +
    pickCard('Buy low', 'underlying numbers better than the points of the last five (unlucky)', p.buy_low, byId, luck) +
    pickCard('Sell high', 'points well above the underlying numbers of the last five (lucky)', p.sell_high, byId, luck) + '</div>';
}

// ── the squad ───────────────────────────────────────────────────────────────

function drawSquad(el, body, doc, byId) {
  var s = doc.squad || {};
  if (!s.xi) { body.innerHTML = FB.empty('No optimised squad this build', s.solver ? String(s.solver) : ''); return; }
  var xi = s.xi.map(function (id) { return byId[id]; }).filter(Boolean);
  var bench = (s.bench || []).map(function (id) { return byId[id]; }).filter(Boolean);
  var formation = (function () { var d = xi.filter(function (r) { return r.pos === 'D'; }).length, m = xi.filter(function (r) { return r.pos === 'M'; }).length, f = xi.filter(function (r) { return r.pos === 'F'; }).length; return d + '-' + m + '-' + f; })();
  body.innerHTML = FB.kpis([
    FB.kpi('Formation', esc(s.formation || formation), { text: true, sub: esc(s.solver || '') }),
    FB.kpi('Cost', cost(s.cost), { sub: 'of ' + cost(s.budget) }),
    FB.kpi('XI, next ' + (s.horizon || 5), n1(s.xi_h5), { signal: true, sub: 'our projected points' }),
    FB.kpi('XI, next gameweek', n1(s.xi_next), { sub: 'captain doubled' })
  ]) + '<div class="fb-mt">' + FB.grid(
    FB.card('Suggested starting XI', 'Each player: cost · projected points over the next ' + (s.horizon || 5) + ' gameweeks. C captain, V vice.', '<div id="fa-pitch"></div>', { span: 7 }) +
    FB.card('The fifteen', 'Bench below the line.', '<div id="fa-squad-tbl"></div>', { span: 5, flush: true })
  ) + '</div><p class="fb-cap">Fifteen players (2 goalkeepers, 5 defenders, 5 midfielders, 3 forwards), at most three from a club, within the budget, chosen to maximise the starting XI\'s projected points over the next ' + (s.horizon || 5) + ' gameweeks (plus a tenth of the bench\'s) and the captain\'s next-gameweek points, as an integer programme.</p>';
  var pts = FB.charts.xiPoints(xi.map(function (r) { return FB.merge(r, { pos: r.pos }); }), s.formation || formation);
  FB.charts.formation(el.querySelector('#fa-pitch'), {
    surface: 'half', label: 'Suggested starting XI',
    points: pts.map(function (x) {
      var r = x.p;
      var tag = r.id === s.captain ? 'C' : r.id === s.vice ? 'V' : POS_SHORT[r.pos];
      return { x: x.x, y: x.y, label: FB.surname(r.name), sub: cost(r.price) + ' · ' + n1(r.h5), mark: tag, color: posHex(r.pos), ring: r.id === s.captain ? QK.cssVar('--signal') : null, href: FB.href.player(r.id) };
    })
  });
  var list = xi.slice().sort(function (a, b) { return POS.indexOf(a.pos) - POS.indexOf(b.pos) || (b.h5 || 0) - (a.h5 || 0); }).concat(bench.map(function (r) { return FB.merge(r, { _bench: true }); }));
  FB.table('fa-squad-tbl', [
    { key: 'name', label: 'Player', sort: false, fmt: function (v, r) { return (r._bench ? '<span class="qk-muted">Bench · </span>' : '') + plink(r) + (r.id === s.captain ? ' ' + FB.badge('C', 'accent') : r.id === s.vice ? ' ' + FB.badge('V') : ''); } },
    { key: 'pos', label: 'Pos', sort: false, fmt: function (v) { return posTag(v); } },
    { key: 'price', label: 'Cost', num: true, sort: false, fmt: function (v) { return cost(v); } },
    { key: 'next', label: 'Next', num: true, sort: false, fmt: function (v) { return n1(v); } },
    { key: 'h5', label: 'Next 5', num: true, sort: false, fmt: function (v) { return '<b>' + n1(v) + '</b>'; } }
  ], list, {});
  var tb = el.querySelector('#fa-squad-tbl tbody');
  if (tb && bench.length) { var trs = tb.querySelectorAll('tr'); var first = trs[xi.length]; if (first) first.classList.add('fb-fa-benchrow'); }
}

// ── method ──────────────────────────────────────────────────────────────────

function drawMethod(el, body, meta) {
  var bt = meta.backtest || {}, ms = bt.methods || {}, sc = meta.scoring || {};
  var keys = ['model', 'last5', 'std', 'y365'].filter(function (k) { return ms[k]; });
  body.innerHTML = FB.kpis([
    FB.kpi('Rounds backtested', FB.int(bt.rounds), { sub: FB.int(bt.player_rounds) + ' player-rounds' }),
    FB.kpi('Mean actual points', n1(bt.mean_actual), { sub: 'a player a round' }),
    FB.kpi('Calibration', isNum(bt.calibration) ? '×' + num(bt.calibration, 3) : '—', { sub: 'actual / projected', tip: bt.calibration_note || 'Live projections are multiplied by this ratio of actual to projected points.' }),
    FB.kpi('Our MAE', isNum((ms.model || {}).mae) ? num(ms.model.mae, 2) : '—', { signal: true, sub: 'points a player a round' })
  ]) + '<div class="fb-mt">' + FB.grid(
    FB.card('Top-20 picks, actual points', 'Actual points a round of the 20 highest-projected players, by projection.', FB.chartBox('fa-m-top', 260, 'Top-20 actual points by method'), { span: 6 }) +
    FB.card('Error by position', 'Mean absolute error of our projection, points a round.', FB.chartBox('fa-m-pos', 260, 'Error by position'), { span: 6 })
  ) + '</div><div class="fb-mt">' + FB.card('Walk-forward backtest', (bt.rounds || 0) + ' league rounds, every followed league.', bt.ok ? '<div id="fa-m-tbl"></div>' : FB.muted('No backtest this build: ' + esc(bt.reason || '')), { flush: true }) + '</div>' +
    '<p class="fb-cap">Each round is projected from earlier matches only, and the fixture\'s expected goals come from a walk-forward team-strength stand-in (past fixtures keep no model line), so the live projections, which use the match model, should do at least this well. Actual points use the same scoring from the line-ups (0 for a player who did not play). Most players score 1-3 points most weeks, which is why the absolute errors are close; the ranking and the top picks are where a projection earns its keep. ' + esc(bt.calibration_note ? 'Calibration: ' + bt.calibration_note + '.' : '') + '</p>' +
    '<div class="fb-mt">' + FB.card('Scoring', 'FPL\'s 2025/26 rules applied by us to Sofascore\'s match data.', '<div class="fb-prose"><ul>' +
      '<li>Minutes: ' + esc(sc.minutes || '') + '. Goals: goalkeeper 10, defender 6, midfielder 5, forward 4. Assists 3.</li>' +
      '<li>Clean sheet (60+ minutes, nothing conceded while on the pitch): goalkeeper and defender 4, midfielder 1. ' + esc(sc.goals_conceded || '') + '. ' + esc(sc.saves || '') + '.</li>' +
      '<li>Yellow −1, red −3 (a second yellow counts as the red only), own goal −2, penalty missed −2.</li>' +
      '<li>Defensive contribution: ' + esc(sc.defensive_contribution || '') + '.</li><li>Bonus: ' + esc(sc.bonus || '') + '.</li><li>Not scored: ' + esc(sc.not_scored || '') + '.</li></ul>' +
      '<p>Projection per player and fixture: expected minutes and the chances of playing and of 60+ minutes from the player\'s recent share of the club\'s league minutes (60-day half-weight); per-90 rates (180-day weighting, shrunk to the position) of goals and assists (70% expected, 30% actual), saves, cards, bonus and defensive-contribution hits; scaled by the fixture: attacking rates by the team\'s expected goals in the fixture against its average over its remaining fixtures, the clean sheet as exp(−expected goals against), goals conceded and saves from Poisson expectations.</p>' +
      '<p>Costs: our own proxy, each player\'s expected points above replacement next season from the value model, ranked within the league and position and mapped onto FPL-like ranges (goalkeepers £4.0-6.0m, defenders £4.0-7.5m, midfielders £4.5-13.0m, forwards £4.5-14.5m). FPL\'s own data is not used: the Premier League\'s terms of use forbid reproducing or re-using its material, so its costs and ownership are left out.</p></div>') + '</div>';
  if (keys.length) QKC.bar(el.querySelector('#fa-m-top'), { horizontal: true, labels: true, labelWidth: 150, fmt: function (v) { return num(v, 2); }, valName: 'Actual points per round', catName: 'Projection',
    cats: keys.map(function (k) { return ms[k].label; }), series: [{ name: 'Top-20 actual points', data: keys.map(function (k) { return ms[k].top20_actual_mean; }) }],
    colors: keys.map(function (k) { return k === 'model' ? QK.cssVar('--signal') : QK.cssVar('--ink-4'); }) });
  var bp = (ms.model || {}).by_position || {};
  var ps = POS.filter(function (p) { return bp[p]; });
  if (ps.length) QKC.bar(el.querySelector('#fa-m-pos'), { labels: true, fmt: function (v) { return num(v, 2); }, cats: ps.map(function (p) { return POS_LABEL[p] + 's'; }),
    valName: 'MAE (points per round)', catName: 'Position', series: [{ name: 'MAE', data: ps.map(function (p) { return bp[p].mae; }) }], colors: ps.map(posHex) });
  else FB.set('fa-m-pos', FB.muted('No breakdown this build.'));
  if (bt.ok) FB.table('fa-m-tbl', [
    { key: 'label', label: 'Projection', sticky: true, fmt: function (v, r) { return r.k === 'model' ? '<b>' + esc(v) + '</b>' : esc(v); } },
    { key: 'mae', label: 'MAE', num: true, tip: 'Mean absolute error of a player\'s points in a round', fmt: function (v) { return num(v, 3); } },
    { key: 'rmse', label: 'RMSE', num: true, fmt: function (v) { return num(v, 3); } },
    { key: 'bias', label: 'Bias', num: true, fmt: function (v) { return signed(v, 3); } },
    { key: 'spearman_round_mean', label: 'Rank corr.', num: true, tip: 'Spearman correlation of projected and actual points among the round\'s players, averaged over rounds', fmt: function (v) { return num(v, 3); } },
    { key: 'top20_actual_mean', label: 'Top-20 pts', num: true, fmt: function (v) { return num(v, 2); } },
    { key: 'big5_mae', label: 'Big-five MAE', num: true, fmt: function (v) { return num(v, 3); } }
  ], keys.map(function (k) { return FB.merge(ms[k], { k: k }); }), {});
}

})(window.FB);
