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

function vrowCells(L, S, r, fb) {
  return [{ html: '<a href="' + esc(CC.playerHref(L, r.id, S)) + '">' + esc(r.name || CC.pname(L, r.id)) + '</a>', v: r.name }, { html: U.teamEnt(L, r.team, { season: S, abbr: true }), v: CC.tname(L, r.team) }, esc(r.pos || '—'), esc(r['class'] || '—'),
    isNum(r.gp) ? r.gp : '—', { v: r.value, html: '<b>' + CC.f(r.value, fb ? 1 : 2) + '</b>' }, { v: r.value_pg, html: CC.f(r.value_pg, 2) }, { v: r.pctl, html: isNum(r.pctl) ? QK.pctlChip(r.pctl) : '—' }, { html: '<span class="qk-muted">' + esc(r.why || '') + '</span>', v: r.why || '' }];
}
var VCOLS = ['Player', 'Team', 'Pos', 'Class', { label: 'GP', align: 'right' }, { label: 'Value', align: 'right' }, { label: 'Per game', align: 'right' }, { label: 'Pctl', align: 'right' }, 'Why'];

CC.route('value', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  var list = [['value', 'Value'], ['position', 'By position'], ['transfers', 'Transfers']];
  var tab = U.tab(p, ['value', 'position', 'transfers'], 'value');
  el.innerHTML = U.head('Value & Moves', '', U.kicker(L, S)) + U.tabs(L, 'value', list, S, tab) + '<div id="vb">' + QK.skeleton('lines', 8) + '</div>';
  var body = QK.$('#vb', el);
  return Promise.all([CC.load(CC.path(L, S, tab === 'transfers' ? 'moves.json' : 'value.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var d = a[0];
    if (!CC.ok(d)) { body.innerHTML = U.missing(tab === 'transfers' ? 'Transfers' : 'Player value', d); return; }
    if (tab === 'transfers') { transfers(body, L, S, d); U.wire(body); return; }
    var cur = d.currency || {};
    var sub = '<b>' + esc(cur.label || 'Value') + '</b>' + (cur.desc ? ': ' + esc(cur.desc) : '') + '.';
    var rows = d.leaders || [];
    if (!rows.length) { body.innerHTML = '<p class="cc-note">' + sub + '</p>' + QK.empty('No value numbers yet', 'They appear once games have been played this season. Try last season with the season picker.'); return; }
    if (tab === 'value') {
      var pos = {}; rows.forEach(function (r) { if (r.pos) pos[r.pos] = (pos[r.pos] || 0) + 1; });
      var chips = '<div class="qk-chips scroll cc-filters" id="v-pos" role="group" aria-label="Position">' + ['all'].concat(Object.keys(pos).sort(function (x, y) { return pos[y] - pos[x]; })).map(function (k, i) {
        return '<button type="button" class="qk-chip" style="--ca:var(--accent)" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(k === 'all' ? 'All' : k) + '</button>'; }).join('') + '</div>';
      body.innerHTML = '<p class="cc-note">' + sub + '</p>' + chips + '<div class="qk-grid cc-grid"><div class="qk-span-5">' + U.card('Top 20', '', U.chart('v-top', 560, 'Top 20 players by value')) + '</div><div class="qk-span-7" id="v-tbl"></div></div>';
      var curPos = 'all';
      var paint = function () {
        var rs = rows.filter(function (r) { return curPos === 'all' || r.pos === curPos; });
        QK.$('#v-tbl', body).innerHTML = U.card('Leaderboard', rs.length + ' players', U.table(VCOLS, rs.map(function (r) { return { cells: vrowCells(L, S, r, fb), _href: CC.playerHref(L, r.id, S) }; }), { maxHeight: 620 }));
        U.wire(QK.$('#v-tbl', body));
        var top = rs.slice(0, 20);
        QKC.bar('#v-top', { cats: top.map(function (r) { return (r.name || '').replace(/^(\S)\S*\s/, '$1. ') + ' · ' + CC.tabbr(L, r.team); }), series: [{ name: cur.label || 'Value', data: top.map(function (r) { return r.value; }) }], horizontal: true, labels: true, fmt: function (v) { return CC.f(v, 1); },
          colors: top.map(function (r) { return CC.tcol(L, r.team); }), hrefs: top.map(function (r) { return CC.playerHref(L, r.id, S); }), labelWidth: 150 });
      };
      QK.chips(QK.$('#v-pos', body), function (v) { curPos = v[0] || 'all'; paint(); });
      paint();
      return;
    }
    var bp = d.by_position || {};
    var order = fb ? ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'EDGE', 'LB', 'DB', 'CB', 'S', 'K', 'P'] : ['G', 'F', 'C'];
    var ks = Object.keys(bp).sort(function (x, y) { var a1 = order.indexOf(x), b1 = order.indexOf(y); return (a1 < 0 ? 99 : a1) - (b1 < 0 ? 99 : b1); });
    body.innerHTML = '<p class="cc-note">' + sub + '</p><div class="cc-auto wide">' + ks.map(function (k) {
      return U.card(k, 'Top ' + bp[k].length, '<ol class="cc-rank">' + bp[k].map(function (r) {
        return '<li><span class="n"></span>' + U.playerEnt(L, r.id, r.name, r.team, CC.tabbr(L, r.team), S) + '<b class="v">' + CC.f(r.value, fb ? 1 : 2) + '</b><div class="why">' + esc(r.why || '') + '</div></li>'; }).join('') + '</ol>');
    }).join('') + '</div>';
  });
});

function transfers(node, L, S, d) {
  var mv = d.moves || [], fb = CC.fb(L);
  var bt = d.by_team || {};
  var teams = Object.keys(bt).filter(function (t) { return isNum(bt[t].net_value); }).sort(function (x, y) { return bt[y].net_value - bt[x].net_value; });
  var top = teams.slice(0, 10).concat(teams.slice(-10).filter(function (t) { return teams.indexOf(t) >= 10; }));
  var html = '<p class="cc-note"><b>' + esc(d.note || 'Inferred from box scores and rosters; not the official transfer portal.') + '</b></p>';
  html += '<div class="qk-kpis cc-kpis">' + QK.kpi({ label: 'Moves found', value: String(mv.length) }) + QK.kpi({ label: 'Teams involved', value: String(Object.keys(bt).length) }) +
    (teams[0] ? QK.kpi({ label: 'Biggest net gain', html: true, value: esc(CC.tabbr(L, teams[0])) + ' ' + CC.signed(bt[teams[0]].net_value, 1), sub: esc(CC.tname(L, teams[0])) }) : '') + '</div>';
  html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + U.card('Net value by team', 'Value of players in minus value of players out (most and least).', top.length ? U.chart('mv-net', Math.max(300, top.length * 22 + 30), 'Net transfer value by team') : QK.empty('No moves', '')) + '</div><div class="qk-span-7">' +
    U.card('All moves', 'Value before (last season, old team) and after (this season, new team).', mv.length ? U.table(['Player', 'Pos', 'From', 'To', { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, 'Grade'], mv.map(function (m) {
      return { cells: [{ html: '<a href="' + esc(CC.playerHref(L, m.player, S)) + '">' + esc(m.name || CC.pname(L, m.player)) + '</a>', v: m.name }, esc(m.pos || '—'), { html: U.teamEnt(L, m.from, { abbr: true }), v: CC.tname(L, m.from) }, { html: U.teamEnt(L, m.to, { season: S, abbr: true }), v: CC.tname(L, m.to) },
        { v: m.value_before, html: CC.f(m.value_before, 1) }, { v: isNum(m.value_after) ? m.value_after : null, html: CC.f(m.value_after, 1) }, { html: U.grade(m.grade), v: m.grade || 'Z' }], _href: CC.playerHref(L, m.player, S) };
    }), { maxHeight: 640 }) : QK.empty('No moves found', 'Moves are inferred once the new season’s box scores and rosters are in.')) + '</div></div>';
  node.innerHTML = html;
  if (top.length) QKC.bar('#mv-net', { cats: top.map(function (t) { return CC.tshort(L, t); }), series: [{ name: 'Net value', data: top.map(function (t) { return bt[t].net_value; }) }], horizontal: true, diverging: true, labels: true, fmt: function (v) { return CC.signed(v, 1); }, hrefs: top.map(function (t) { return CC.teamHref(L, t, S); }), labelWidth: 100 });
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
    var html = U.head('Fantasy', 'Projections for ' + esc(d.period || 'the coming period') + ' from usage, efficiency and the opponent. Our own scoring; no official fantasy-game prices or ownership (their terms do not allow reuse).', U.kicker(L, S));
    html += '<div class="qk-kpis cc-kpis">' + QK.kpi({ label: 'Projection error', value: CC.f(bt.mae, 2), sub: 'mean absolute, points; naive ' + CC.f(bt.mae_naive, 2), tip: 'Walk-forward backtest against the actual fantasy points' }) +
      QK.kpi({ label: 'Rank correlation', value: CC.f(bt.rank_corr, 2), sub: 'naive ' + CC.f(bt.rank_corr_naive, 2) }) + QK.kpi({ label: 'Games tested', value: isNum(bt.n) ? QK.fmt.num(bt.n) : '—' }) + '</div>';
    if (!proj.length) { el.innerHTML = html + (CC.isCur(L, S) ? QK.empty('No projections yet', 'They appear before the first games of the period.') : QK.empty('No projections for this season', 'Weekly projections are kept for the current season; the backtest above covers the past seasons.')); return; }
    var poss = {}; proj.forEach(function (r) { if (r.pos) poss[r.pos] = 1; });
    html += '<div class="cc-toolbar">' + (fmts.length ? '<div class="qk-seg" id="ff-fmt" role="group" aria-label="Scoring format">' + fmts.map(function (f, i) { return '<button type="button" data-value="' + esc(f) + '" aria-pressed="' + (i === 0) + '">' + esc(FN[f] || f) + '</button>'; }).join('') + '</div>' : '') +
      '<div class="qk-chips scroll" id="ff-pos" role="group" aria-label="Position">' + ['all'].concat(Object.keys(poss)).map(function (k, i) { return '<button type="button" class="qk-chip" style="--ca:var(--accent)" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(k === 'all' ? 'All' : k) + '</button>'; }).join('') + '</div></div>';
    html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + U.card('Top 25: floor to ceiling', 'Projected points with the 10th to 90th percentile range.', U.chart('ff-rng', 640, 'Projected fantasy points with range, top 25')) + '</div><div class="qk-span-7" id="ff-tbl"></div></div>';
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
