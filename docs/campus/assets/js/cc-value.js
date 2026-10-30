/* The Quant Campus — Value & Moves (#/<L>/value?tab=value|position|transfers) and Fantasy (#/<L>/fantasy).
 * Value: the leaderboard in the level's currency (football: EPA above replacement; basketball: value above
 * replacement), filters by position and team. By position: the best ten at each position with the reason.
 * Transfers: inferred moves (the same ESPN athlete on a new team), the biggest, and net value by team. Labelled as
 * inferred, not the official transfer portal.
 * Fantasy: projections for the coming period in each scoring format, tiers, start/sit and sleepers, and the
 * walk-forward backtest against a naive baseline.
 * Reads <L>/<S>/value.json, <L>/<S>/moves.json, <L>/<S>/fantasy.json. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

CC.route('value', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  /* round 9: "By position" is the landing view (value compares best within a position); the full table is the
     Scouting Room board */
  var list = [['position', 'By position'], ['value', 'Value'], ['transfers', 'Transfers']];
  var tab = U.tab(p, ['value', 'position', 'transfers'], 'position');
  el.innerHTML = U.head('Value & Moves', 'What every player is worth on the field in our value model, the best at each position, and the transfers we can see in the box scores.', U.kicker(L, S)) + U.tabs(L, 'value', list, S, tab) +
    QK.note(CC.hk(L) ? '<b>Goals above replacement (GAR)</b> is what a player adds over a replacement-level player at the same position: goals created, a damped share of plus-minus, penalties and faceoffs; goalies, goals saved above average. Transfers are inferred from College Hockey News player ids, not the official portal.' + CC.hkCredit(true)
      : '<b>Value above replacement</b> is what a player adds over a replacement-level player at the same position: ' + (CC.fb(L) ? 'expected points on the player’s plays' : 'a box-score rating scaled so a team’s players add up to its margin') + '. Transfers here are inferred from box scores and rosters, not the official portal.') + '<div id="vb">' + QK.skeleton('lines', 8) + '</div>';
  var body = QK.$('#vb', el);
  return Promise.all([CC.load(CC.path(L, S, tab === 'transfers' ? 'moves.json' : 'value.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var d = a[0];
    if (!CC.ok(d)) { body.innerHTML = U.missing(tab === 'transfers' ? 'Transfers' : 'Player value', d); return; }
    if (tab === 'transfers') { transfers(body, L, S, d); return; }
    var cur = d.currency || {};
    var sub = (d.basis === 'last_season' ? QK.tag('Last season’s values: ' + CC.seasonLabel(L, S - 1) + ', players on this season’s rosters', 'signal') + ' ' : '') + '<b>' + esc(cur.label || 'Value') + '</b>' + (cur.desc ? ': ' + esc(cur.desc) : '') + '.';
    var rows = d.leaders || [];
    if (!rows.length) { body.innerHTML = '<p class="cc-note">' + sub + '</p>' + QK.empty('No value numbers yet', 'They appear once games have been played this season. Try last season with the season picker.'); return; }
    if (tab === 'value') {
      var pos = {}; rows.forEach(function (r) { if (r.pos) pos[r.pos] = (pos[r.pos] || 0) + 1; });
      var chips = '<div class="qk-chips scroll cc-filters" id="v-pos" role="group" aria-label="Position">' + ['all'].concat(Object.keys(pos).sort(function (x, y) { return pos[y] - pos[x]; })).map(function (k, i) {
        return '<button type="button" class="qk-chip" style="--ca:var(--signal)" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(k === 'all' ? 'All' : CC.hk(L) ? (CC.HKV.posPl[k] || k) : k) + '</button>'; }).join('') + '</div>';
      var r0 = rows[0], pg0 = rows.filter(function (r) { return isNum(r.value_pg); }).slice().sort(function (x, y) { return y.value_pg - x.value_pg; })[0];
      var tl = [];
      if (r0) tl.push({ label: 'Most valuable', value: QK.surname(r0.name || '') + ' ' + CC.f(r0.value, fb ? 1 : 1), signal: true, href: CC.playerHref(L, r0.id, S), sub: (r0.pos || '') + ' · ' + CC.tname(L, r0.team), tip: 'Our value model: ' + (cur.label || 'value') });
      if (pg0) tl.push({ label: 'Most valuable a game', value: QK.surname(pg0.name || '') + ' ' + CC.f(pg0.value_pg, 2), href: CC.playerHref(L, pg0.id, S), sub: (pg0.pos || '') + ' · ' + CC.tname(L, pg0.team) });
      tl.push({ label: 'Players ranked', value: QK.fmt.num(rows.length), sub: d.basis === 'last_season' ? 'on this season’s rosters, valued on last season' : 'qualified players this season' });
      body.innerHTML = U.stats(tl) + '<p class="cc-note">' + sub + '</p>' + chips + U.card('The top 20', 'Our value ' + (CC.isCur(L, S) ? 'this season' : 'in ' + esc(CC.seasonLabel(L, S))) + ', in team colours; tap a bar for the player.', U.chart('v-top', 600, 'Top 20 players by value')) +
        QK.explain('Every player’s value, with percentiles against the same position and every other metric beside it, is on the <a class="qk-link" id="v-board" href="' + esc(CC.scoutHref(L, S, 'cols=Value')) + '">Scouting Room board</a>; the best at each position is the <a class="qk-link" href="' + esc(CC.href(L, 'value', null, S)) + '">By position</a> view.', { title: 'The whole table.' });
      var curPos = 'all';
      var paint = function () {
        var rs = rows.filter(function (r) { return curPos === 'all' || r.pos === curPos; });
        var top = rs.slice(0, 20);
        QKC.bar('#v-top', { cats: top.map(function (r) { return (r.name || '').replace(/^(\S)\S*\s/, '$1. ') + ' · ' + CC.tabbr(L, r.team); }), series: [{ name: cur.label || 'Value', data: top.map(function (r) { return r.value; }) }], horizontal: true, labels: true, fmt: function (v) { return CC.f(v, 1); },
          colors: top.map(function (r) { return CC.tcol(L, r.team); }), hrefs: top.map(function (r) { return CC.playerHref(L, r.id, S); }), labelWidth: 150, valName: cur.label || 'Value', catName: 'Player' });
      };
      QK.chips(QK.$('#v-pos', body), function (v) { curPos = v[0] || 'all'; paint(); });
      paint();
      return;
    }
    var bp = d.by_position || {};
    var order = fb ? ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'EDGE', 'LB', 'DB', 'CB', 'S', 'K', 'P'] : CC.hk(L) ? ['F', 'D', 'G'] : ['G', 'F', 'C'];
    var ks = Object.keys(bp).sort(function (x, y) { var a1 = order.indexOf(x), b1 = order.indexOf(y); return (a1 < 0 ? 99 : a1) - (b1 < 0 ? 99 : b1); });
    var bestAt = ks.filter(function (k) { return (bp[k] || []).length; }).map(function (k) { return { k: k, r: bp[k][0] }; });
    body.innerHTML = '<p class="cc-note">' + sub + '</p>' + (bestAt.length ? U.card('The best at each position', 'The most valuable player at each position' + (CC.isCur(L, S) ? ' this season' : '') + '; value compares best within a position, so read each bar against its own position’s list below.', U.chart('v-pos', Math.max(240, bestAt.length * 34 + 50), 'The most valuable player at each position')) : '') +
      '<div class="cc-auto wide">' + ks.map(function (k) {
      return U.card(CC.hk(L) ? (CC.HKV.posPl[k] || k) : k, 'Top ' + bp[k].length, '<ol class="cc-rank">' + bp[k].map(function (r) {
        return '<li><span class="n"></span>' + U.playerEnt(L, r.id, r.name, r.team, CC.tabbr(L, r.team), S) + '<b class="v">' + CC.f(r.value, fb || CC.hk(L) ? 1 : 2) + '</b><div class="why">' + esc(r.why || '') + '</div></li>'; }).join('') + '</ol>');
    }).join('') + '</div>';
    if (bestAt.length) QKC.bar('#v-pos', { cats: bestAt.map(function (b) { return b.k + ' · ' + QK.surname(b.r.name || ''); }), horizontal: true, labels: true, fmt: function (v) { return CC.f(v, 1); },
      series: [{ name: cur.label || 'Value', data: bestAt.map(function (b) { return b.r.value; }) }], colors: bestAt.map(function (b) { return CC.tcol(L, b.r.team); }), hrefs: bestAt.map(function (b) { return CC.playerHref(L, b.r.id, S); }), labelWidth: 130, valName: cur.label || 'Value', catName: 'Position' });
  });
});

/* Transfers (round 9): the headline numbers, what the grades mean, net value by team as a chart, the best moves, then
   every team's moves in and out as a collapsible row (built when opened), and every move folded at the foot. */
var GRADE_TXT = [['A', 'top 20%'], ['B', '60th to 80th percentile'], ['C', '40th to 60th'], ['D', '20th to 40th'], ['F', 'bottom 20%']];
function transfers(node, L, S, d) {
  var mv = d.moves || [], fb = CC.fb(L);
  var bt = d.by_team || {};
  var teams = Object.keys(bt).filter(function (t) { return isNum(bt[t].net_value); }).sort(function (x, y) { return bt[y].net_value - bt[x].net_value; });
  var top = teams.slice(0, 10).concat(teams.slice(-10).filter(function (t) { return teams.indexOf(t) >= 10; }));
  var byId = {}; mv.forEach(function (m) { byId[String(m.player)] = m; });
  var best = (d.best || []).length ? d.best : mv.filter(function (m) { return isNum(m.value_after); }).slice().sort(function (x, y) { return y.value_after - x.value_after; }).slice(0, 20);
  var html = U.stats([teams[0] ? { label: 'Biggest net gain', value: CC.tabbr(L, teams[0]) + ' ' + CC.signed(bt[teams[0]].net_value, 1), signal: true, href: CC.teamHref(L, teams[0], S), sub: CC.tname(L, teams[0]) + ' · value in minus value out' } : null,
    best[0] ? { label: 'Most valuable arrival', value: QK.surname(best[0].name || '') + ' ' + CC.f(best[0].value_after, 1), href: CC.playerHref(L, best[0].player, S), sub: (best[0].pos || '') + ' · ' + CC.tshort(L, best[0].from) + ' to ' + CC.tshort(L, best[0].to) } : null,
    { label: 'Moves found', value: QK.fmt.num(mv.length), sub: 'the same athlete on a new team' }, { label: 'Teams involved', value: QK.fmt.num(Object.keys(bt).length) }]);
  html += QK.explain('<b>What the grades mean.</b> A move’s grade is how good the player was <i>before</i> it: last season’s value at the old team as a percentile among every player, ' +
    GRADE_TXT.map(function (g) { return U.grade(g[0]) + ' ' + g[1]; }).join(', ') + '. “Value after” is this season so far at the new team. ' + QK.tag('Inferred from box scores, not the official transfer portal') + ' ' + esc(d.note || ''));
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Net value by team', 'Value of players in minus value of players out: the ten biggest gains and the ten biggest losses.', top.length ? U.chart('mv-net', Math.max(300, top.length * 22 + 40), 'Net transfer value by team') : QK.empty('No moves', '')) + '</div><div class="qk-span-6">' +
    U.card('The best moves so far', 'The most valuable players on their new team this season.', best.length ? U.table(['Player', 'Pos', 'From', 'To', { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, 'Grade'], best.slice(0, 12).map(rowOf), { sticky: false }) : QK.empty('No moves yet', '')) + '</div></div>';
  html += U.section('By team', 'Every team’s arrivals and departures, the biggest net gains first. Open a team to see the players.', '<div class="cc-mvt">' + teams.map(function (t, i) {
    var x = bt[t], n1 = (x['in'] || []).length, n0 = (x.out || []).length;
    return '<details class="cc-mvt-t" data-t="' + esc(t) + '"' + (i >= 20 ? ' hidden' : '') + '><summary>' + U.teamEnt(L, t, { season: S }) + '<span class="cc-mvt-n">' + n1 + ' in · ' + n0 + ' out</span><b class="num ' + CC.cls(x.net_value) + '">' + CC.signed(x.net_value, 1) + '</b></summary><div class="cc-mvt-b"></div></details>';
  }).join('') + '</div>' + (teams.length > 20 ? '<button type="button" class="qk-btn sm" id="mv-more" style="margin-top:10px">Show all ' + teams.length + ' teams</button>' : ''), '', 'Moves');
  html += '<details class="cc-data"><summary>Every move (' + QK.fmt.num(mv.length) + ')</summary><div id="mv-all"></div></details>';
  node.innerHTML = html;
  function rowOf(m) {
    return { cells: [{ html: '<a href="' + esc(CC.playerHref(L, m.player, S)) + '">' + esc(m.name || CC.pname(L, m.player)) + '</a>', v: m.name }, esc(m.pos || '—'), { html: U.teamEnt(L, m.from, { abbr: true }), v: CC.tname(L, m.from) }, { html: U.teamEnt(L, m.to, { season: S, abbr: true }), v: CC.tname(L, m.to) },
      { v: m.value_before, html: CC.f(m.value_before, 1) }, { v: isNum(m.value_after) ? m.value_after : null, html: CC.f(m.value_after, 1) }, { html: U.grade(m.grade), v: m.grade || 'Z' }], _href: CC.playerHref(L, m.player, S) };
  }
  QK.$$('.cc-mvt-t', node).forEach(function (det) {
    det.addEventListener('toggle', function () {
      var bx = det.querySelector('.cc-mvt-b');
      if (!det.open || bx.innerHTML) return;
      var x = bt[det.getAttribute('data-t')] || {};
      var list = function (ids, dir) { var rs = (ids || []).map(function (id) { return byId[String(id)]; }).filter(Boolean); return rs.length ? U.table(['Player', 'Pos', dir === 'in' ? 'From' : 'From', 'To', { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, 'Grade'], rs.map(rowOf), { sticky: false }) : '<p class="cc-note">None found.</p>'; };
      bx.innerHTML = '<div class="qk-grid cc-grid"><div class="qk-span-6"><div class="cc-mini-h">In</div>' + list(x['in'], 'in') + '</div><div class="qk-span-6"><div class="cc-mini-h">Out</div>' + list(x.out, 'out') + '</div></div>';
      U.wire(bx);
    });
  });
  var more = QK.$('#mv-more', node);
  if (more) more.addEventListener('click', function () { QK.$$('.cc-mvt-t[hidden]', node).forEach(function (x) { x.hidden = false; }); more.remove(); });
  var allD = QK.$('#mv-all', node).parentNode;
  allD.addEventListener('toggle', function () { var h = QK.$('#mv-all', node); if (!allD.open || h.innerHTML) return; h.innerHTML = mv.length ? U.table(['Player', 'Pos', 'From', 'To', { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, 'Grade'], mv.map(rowOf), { maxHeight: 640 }) : ''; U.wire(h); });
  U.wire(node);
  if (top.length) QKC.bar('#mv-net', { cats: top.map(function (t) { return CC.tshort(L, t); }), series: [{ name: 'Net value', data: top.map(function (t) { return bt[t].net_value; }) }], horizontal: true, diverging: true, labels: true, fmt: function (v) { return CC.signed(v, 1); }, hrefs: top.map(function (t) { return CC.teamHref(L, t, S); }), labelWidth: 100, valName: 'Net value (points)', catName: 'Team' });
}

/* ── fantasy ─────────────────────────────────────────────────────────── */
CC.route('fantasy', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  el.innerHTML = U.head('Fantasy', '', U.kicker(L, S)) + QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'fantasy.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var d = a[0];
    if (!CC.ok(d)) { el.innerHTML = U.head('Fantasy', '', U.kicker(L, S)) + U.missing('Fantasy projections', d); return; }
    var fmts = Object.keys(d.rankings || {});
    var FN = { ppr: 'PPR', half: 'Half PPR', standard: 'Standard', points: 'Points league', '9cat': '9-category', nine_cat: '9-category', std: 'Standard' };
    var proj = d.projections || [];
    var bt = d.backtest || {};
    var html = U.head('Fantasy', 'Projections for ' + esc(d.period || 'the coming period') + ' from usage, efficiency and the opponent. Our own scoring; no official fantasy-game data or ownership (their terms do not allow reuse).', U.kicker(L, S));
    var top0 = (proj || []).slice().sort(function (x, y) { return (y.proj || 0) - (x.proj || 0); })[0];
    html += U.stats([top0 ? { label: 'Top projection', value: QK.surname(top0.name || '') + ' ' + CC.f(top0.proj, 1), signal: true, href: CC.playerHref(L, top0.id, S), sub: (top0.pos || '') + ' · ' + CC.tname(L, top0.team) + (isNum(top0.proj_lo) ? ' · ' + CC.f(top0.proj_lo, 1) + '–' + CC.f(top0.proj_hi, 1) : '') } : null,
      isNum(bt.mae) ? { label: 'Projection error', value: CC.f(bt.mae, 2), unit: 'pts', sub: 'mean absolute; a naive projection ' + CC.f(bt.mae_naive, 2), tip: 'Walk-forward backtest against the actual fantasy points' } : null,
      isNum(bt.rank_corr) ? { label: 'Rank correlation', value: CC.f(bt.rank_corr, 2), sub: 'naive ' + CC.f(bt.rank_corr_naive, 2) } : null, isNum(bt.n) ? { label: 'Games tested', value: QK.fmt.num(bt.n) } : null]);
    if (!proj.length) { el.innerHTML = html + (CC.isCur(L, S) ? QK.empty('No projections yet', 'They appear before the first games of the period.') : QK.empty('No projections for this season', 'Weekly projections are kept for the current season; the backtest above covers the past seasons.')); return; }
    var poss = {}; proj.forEach(function (r) { if (r.pos) poss[r.pos] = 1; });
    html += '<div class="cc-toolbar">' + (fmts.length ? '<div class="qk-seg" id="ff-fmt" role="group" aria-label="Scoring format">' + fmts.map(function (f, i) { return '<button type="button" data-value="' + esc(f) + '" aria-pressed="' + (i === 0) + '">' + esc(FN[f] || f) + '</button>'; }).join('') + '</div>' : '') +
      '<div class="qk-chips scroll" id="ff-pos" role="group" aria-label="Position">' + ['all'].concat(Object.keys(poss)).map(function (k, i) { return '<button type="button" class="qk-chip" style="--ca:var(--signal)" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(k === 'all' ? 'All' : k) + '</button>'; }).join('') + '</div></div>';
    html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + U.card('Top 25: floor to ceiling', 'Our projected points (dot) with the likely range, 10th to 90th percentile (bar).', U.chart('ff-rng', 640, 'Projected fantasy points with range, top 25')) + '</div><div class="qk-span-7" id="ff-tbl"></div></div>';
    var pById = {}; proj.forEach(function (r) { pById[r.id] = r; });
    function mini(title, sub, list) { list = (list || []).map(function (r) { return Object.assign({}, pById[r.id] || {}, r); }); return list && list.length ? U.card(title, sub, '<ul class="cc-list">' + list.slice(0, 10).map(function (r) { return '<li>' + U.playerEnt(L, r.id, r.name, r.team, (r.pos || '') + (r.opp ? ' v ' + CC.tabbr(L, r.opp) : ''), S) + '<span class="v">' + CC.f(r.proj, 1) + '</span></li>'; }).join('') + '</ul>') : ''; }
    var m1 = mini('Start or sit', 'Closest calls among likely starters.', d.start_sit), m2 = mini('Sleepers', 'Projected well above their usual usage.', d.sleepers);
    if (m1 || m2) html += '<div class="qk-grid cc-grid">' + (m1 ? '<div class="qk-span-6">' + m1 + '</div>' : '') + (m2 ? '<div class="qk-span-6">' + m2 + '</div>' : '') + '</div>';
    el.innerHTML = html;
    var st = { fmt: fmts[0] || null, pos: 'all' };
    function paint() {
      var byId = {}; proj.forEach(function (r) { byId[r.id] = r; });
      var base = st.fmt && (d.rankings[st.fmt] || []).length ? d.rankings[st.fmt].map(function (r) { return Object.assign({}, byId[r.id] || {}, r); }) : proj;
      var rs = base.filter(function (r) { return st.pos === 'all' || r.pos === st.pos; });
      QK.$('#ff-tbl', el).innerHTML = U.card((st.fmt ? (FN[st.fmt] || st.fmt) + ' rankings' : 'Projections'), rs.length + ' players · tiers group players a manager can treat as interchangeable.', U.table(['Player', 'Team', 'Pos', 'Opp', { label: 'Proj', align: 'right' }, { label: 'Range', align: 'right' }, { label: 'Tier', align: 'right' }], rs.map(function (r) {
        return { cells: [{ html: '<a href="' + esc(CC.playerHref(L, r.id, S)) + '">' + esc(r.name || CC.pname(L, r.id)) + '</a>', v: r.name }, { html: U.teamEnt(L, r.team, { season: S, abbr: true }), v: CC.tname(L, r.team) }, esc(r.pos || '—'), r.opp ? { html: U.teamEnt(L, r.opp, { abbr: true }), v: CC.tname(L, r.opp) } : '—',
          { v: r.proj, html: '<b>' + CC.f(r.proj, 1) + '</b>' }, { v: r.proj_hi, html: CC.f(r.proj_lo, 1) + '–' + CC.f(r.proj_hi, 1) }, isNum(r.tier) ? r.tier : '—'], _href: CC.playerHref(L, r.id, S) };
      }), { maxHeight: 640 }));
      U.wire(QK.$('#ff-tbl', el));
      var top = rs.slice(0, 25);
      QKC.range('#ff-rng', { rows: top.map(function (r) { return { label: (r.name || '').replace(/^(\S)\S*\s/, '$1. ') + ' ' + (r.pos || ''), lo: r.proj_lo, hi: r.proj_hi, mid: r.proj, href: CC.playerHref(L, r.id, S) }; }), loName: 'Floor', hiName: 'Ceiling', midName: 'Projection', valName: 'Fantasy points', fmt: function (v) { return CC.f(v, 1); } });
    }
    if (fmts.length) QK.seg(QK.$('#ff-fmt', el), function (v) { st.fmt = v; paint(); });
    QK.chips(QK.$('#ff-pos', el), function (v) { st.pos = v[0] || 'all'; paint(); });
    paint();
    U.wire(el);
  });
});

})(window.CC);
