/* The Quant Scrum — Rankings: our rebuild of the World Rugby rankings (the table, the week's movement, the history,
 * "what each result would do" for the next tests, the exchanges just played, and how close the rebuild is to the
 * published table) and our own ratings (attack and defence, movement, history). Reads <S>/rankings.json and
 * <S>/ratings.json (oddsmarkets/rugby/pages.py). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;

function mv(n) {
  if (!isNum(n) || n === 0) return '<span class="qk-muted">–</span>';
  return '<span class="' + (n > 0 ? 'pos' : 'neg') + '">' + (n > 0 ? '▲' : '▼') + Math.abs(n) + '</span>';
}

function histChart(el, S, hist, ids, yName) {
  if (!el || !window.QKC) return;
  var months = {};
  ids.forEach(function (id) { (hist[id] || []).forEach(function (h) { months[h[0]] = 1; }); });
  var x = Object.keys(months).sort();
  if (x.length < 3) return;
  var cols = SC.lineColours(S, ids);
  QKC.line(el, { x: x.map(function (m) { return m + '-15'; }), xType: 'time', series: ids.map(function (id, i) {
    var map = {}, last = null;
    (hist[id] || []).forEach(function (h) { map[h[0]] = h[1]; });
    return { name: SC.tabbr(S, id), color: cols[i], data: x.map(function (m) { if (isNum(map[m])) last = map[m]; return last; }) };
  }), yName: yName, xName: 'Month', endLabels: true, step: 'end', yFmt: function (v) { return fmt.num(v, 0); } });
}

function whatIf(S, w) {
  var hn = SC.tname(S, w.home), an = SC.tname(S, w.away);
  var bands = w.bands.map(function (b) {
    var lab = b.result.replace('A ', hn + ' ').replace('B ', an + ' ');
    return '<tr><td>' + esc(lab) + '</td><td class="num ' + SC.cls(b.a) + '">' + SC.signed(b.a, 2) + '</td><td class="num">' + SC.f(b.a_after, 2) + '</td><td class="num ' + SC.cls(b.b) + '">' + SC.signed(b.b, 2) + '</td><td class="num">' + SC.f(b.b_after, 2) + '</td></tr>';
  }).join('');
  var p = w.p || [];
  return '<article class="qk-card sc-wi"><div class="qk-card-head"><div><h3 class="qk-card-title">' + esc(hn + ' v ' + an) + '</h3><div class="qk-card-sub">' + esc(SC.date(w.date) + ' · ' + SC.compName(w.comp)) +
    (isNum(p[0]) ? ' · our chances ' + esc(SC.tabbr(S, w.home) + ' ' + SC.pct(p[0]) + ', ' + SC.tabbr(S, w.away) + ' ' + SC.pct(p[2])) : '') + '</div></div><a class="qk-more" href="' + esc(SC.matchHref(S, w.id)) + '">Match</a></div>' +
    '<div class="qk-card-body flush"><div class="qk-table-wrap"><table class="qk-table dense sc-witab"><thead><tr><th>Result</th><th>' + esc(SC.tabbr(S, w.home)) + '</th><th>After</th><th>' + esc(SC.tabbr(S, w.away)) + '</th><th>After</th></tr></thead><tbody>' + bands + '</tbody></table></div>' +
    '<p class="sc-note sc-pad">Now ' + esc(SC.tabbr(S, w.home)) + ' ' + SC.f(w.pts[0], 2) + ', ' + esc(SC.tabbr(S, w.away)) + ' ' + SC.f(w.pts[1], 2) + '.</p></div></article>';
}

function checkNote(c) {
  if (!c || !c.sep2026) return '';
  var a = c.sep2026, b = c.dec2025 || {};
  return QK.explain('<b>How close is our rebuild?</b> Rebuilt from 1995 with no published input at all, our table on ' + SC.date(a.date) + ' sits ' + SC.f(a.mae, 2) + ' points from the published one on average (' +
    a.n + ' of the top ' + a.of + ' sides; ' + SC.f(a.mae_top10, 2) + ' for the top ten), with ' + a.same_rank + ' in exactly the right place and ' + a.within_one + ' within one (rank correlation ' + SC.f(a.spearman, 3) + '). ' +
    (b.n ? 'Against the published order on ' + SC.date(b.date) + ', ' + b.same_rank + ' of ' + b.n + ' were placed exactly and ' + b.within_one + ' within one. ' : '') +
    'Most of the gap is tests our source does not carry. The live table therefore starts from the published points of 28 September 2026 and adds every result since with the same formula.');
}

SC.route('rankings', function (page, P) {
  var S = P.S, tab = U.tab(P, ['wr', 'ours'], S === 'men' ? 'wr' : 'ours');
  page.innerHTML = U.head('Rankings', tab === 'wr' ? 'World Rugby’s points-exchange rankings, rebuilt by us from results with the published formula.' : 'Our rating: points better than an average test side on a neutral ground, from every result, with home advantage, travel and rest taken out.', SC.SNAME[S]) +
    U.tabs((S === 'men' ? [{ key: 'wr', label: 'World Rugby (our rebuild)', href: SC.href(S, 'rankings') }] : []).concat([{ key: 'ours', label: 'Our ratings', href: SC.href(S, 'rankings', null, 'tab=ours') }]), tab) +
    '<div id="rk-body">' + QK.skeleton('lines', 8) + '</div>';
  var body = QK.$('#rk-body', page);
  if (tab === 'ours') {
    return SC.load(S + '/ratings.json').then(function (d) {
      if (!U.alive(body)) return;
      if (!SC.ok(d)) { body.innerHTML = U.missing('Our ratings', d); return; }
      var rows = (d.teams || []).filter(function (t) { return isNum(t.rank); });
      var rest = (d.teams || []).filter(function (t) { return !isNum(t.rank); });
      var cols = [{ label: '#' }, { label: 'Team', align: 'left', sticky: true }, { label: 'Rtg' }, { label: 'Attack' }, { label: 'Defence' }, { label: '30 days' }, { label: '12 months' },
        { label: 'Last 5', align: 'left' }, { label: 'Won-drawn-lost, 12 months' }, { label: 'World Rugby rank' }, { label: 'Tests' }];
      var html = '<div class="qk-g75"><div>' + U.card('Every side, by our rating', 'Sides with five or more tests, one in the last four years, and a tie to the main pool (a tier-one or tier-two side, or three tests against one in four years). Attack is points scored above an average side, defence points kept out; they add up to the rating. The World Rugby rank is our rebuild of the official table, a different system.',
        U.table(cols, rows.map(function (t, i) {
          return [{ v: t.rank, html: String(t.rank) }, { v: SC.tname(S, t.id), html: U.teamEnt(S, t.id) + SC.followStar(S, t.id) }, { v: t.rating, html: '<b class="sc-ours">' + SC.signed(t.rating, 1) + '</b>' },
            { v: t.att, html: SC.signed(t.att, 1) }, { v: t.dfn, html: SC.signed(t.dfn, 1) }, { v: t.d30 || 0, html: '<span class="' + SC.cls(t.d30) + '">' + (isNum(t.d30) ? SC.signed(t.d30, 1) : '—') + '</span>' },
            { v: t.d365 || 0, html: '<span class="' + SC.cls(t.d365) + '">' + (isNum(t.d365) ? SC.signed(t.d365, 1) : '—') + '</span>' }, { v: t.form, html: U.form(t.form) },
            { v: (t.rec12 || [0])[0], html: (t.rec12 || []).join('–') }, { v: t.wr_rank || 999, html: t.wr_rank ? String(t.wr_rank) + ' <span class="qk-muted">(' + SC.f(t.wr, 2) + ')</span>' : '—' }, { v: t.n, html: String(t.n) }];
        }), { cls: 'sc-table', maxHeight: 900 }), { flush: true }) + '</div><div>' +
        U.card('The top eight, month by month', 'Our rating at the end of each month.', U.chart('rk-hist', 360, 'Rating history')) +
        U.card('Ours against World Rugby’s', 'Each side’s rating (across) against its World Rugby points (up, our rebuild). Sides off the diagonal trend are where the two systems disagree.', U.chart('rk-vs', 340, 'Our rating against World Rugby points')) + '</div></div>' +
        (rest.length ? U.card('Provisional: not ranked', 'These ' + rest.length + ' sides have fewer than five tests rated, or fewer than three tests against tier-one or tier-two opposition in four years. A rating is only pinned down against the sides a team actually plays, so theirs are rough and carry no rank; the World Rugby rank (our rebuild) is the better guide for them.', U.table([{ label: 'Team', align: 'left' }, { label: 'Rtg (provisional)' }, { label: 'World Rugby rank' }, { label: 'Last 5', align: 'left' }, { label: 'Tests' }],
          rest.map(function (t) { return [{ v: SC.tname(S, t.id), html: U.teamEnt(S, t.id) + SC.followStar(S, t.id) }, { v: t.rating, html: '<span class="qk-muted">' + SC.signed(t.rating, 1) + '</span>' }, { v: t.wr_rank || 999, html: t.wr_rank ? String(t.wr_rank) : '—' }, { v: t.form, html: U.form(t.form) }, { v: t.n, html: String(t.n) }]; }), { cls: 'sc-table', maxHeight: 420 }), { flush: true }) : '') +
        QK.explain('<b>Why two rankings?</b> World Rugby’s exchange moves a fixed amount per result and ignores the score beyond 15 points, so it is slow and blunt by design. Ours uses the full margin, the venue, travel and rest, and it is what our chances come from. Home advantage in our model is about ' + SC.f(d.home_adv, 1) + ' points.');
      body.innerHTML = html;
      U.wire(body);
      var hist = {};
      rows.slice(0, 8).forEach(function (t) { hist[t.id] = t.hist || []; });
      histChart(QK.$('#rk-hist', body), S, hist, rows.slice(0, 8).map(function (t) { return t.id; }), 'Our rating (points)');
      var pts = rows.filter(function (t) { return isNum(t.wr) && isNum(t.rating); }).slice(0, 30);
      if (window.QKC && pts.length > 4) QKC.scatter(QK.$('#rk-vs', body), { points: pts.map(function (t) { var tm = SC.team(S, t.id) || {}; return { x: t.rating, y: t.wr, name: tm.name, label: tm.abbr, color: tm.colour, href: SC.teamHref(S, t.id) }; }),
        xName: 'Our rating (points)', yName: 'World Rugby points (our rebuild)', labelTop: 30 });
    });
  }
  return SC.load(S + '/rankings.json').then(function (d) {
    if (!U.alive(body)) return;
    if (!SC.ok(d)) { body.innerHTML = U.missing('The rankings', d); return; }
    var rows = d.table || [];
    var cols = [{ label: '#' }, { label: 'Move' }, { label: 'Team', align: 'left', sticky: true }, { label: 'Points' }, { label: 'Week' }, { label: 'Tests' }, { label: 'Last test' }];
    var html = '<div class="qk-g75"><div>' + U.card('The table: World Rugby’s system, our rebuild', (d.source === 'anchored' ? 'From the published points of 28 September 2026, plus every result since (' + (d.moves || []).length + ' in the last weeks shown below).' : 'Rebuilt from results.') +
      ' This is not our rating: ours, a different system with its own order, is on the Our ratings tab.',
      U.table(cols, rows.slice(0, 60).map(function (r) {
        return [{ v: r.rank, html: String(r.rank) }, { v: (r.prev_rank || r.rank) - r.rank, html: mv((r.prev_rank || r.rank) - r.rank) }, { v: SC.tname(S, r.id), html: U.teamEnt(S, r.id) + SC.followStar(S, r.id) },
          { v: r.pts, html: '<b>' + SC.f(r.pts, 2) + '</b>' }, { v: r.pts - r.prev, html: '<span class="' + SC.cls(r.pts - r.prev) + '">' + (Math.abs(r.pts - r.prev) >= 0.005 ? SC.signed(r.pts - r.prev, 2) : '–') + '</span>' },
          { v: r.played, html: String(r.played || '') }, { v: r.last || '', html: esc(r.last ? SC.date(r.last) : '') }];
      }), { cls: 'sc-table', maxHeight: 900 }), { flush: true }) + '</div><div>' +
      U.card('The top ten since 2004', 'Points at the end of each month: our rebuild from results before 28 September 2026, the published anchor after.', U.chart('rk-hist', 380, 'Ranking points history')) +
      ((d.moves || []).length ? U.card('The latest exchanges', 'What each result moved: the home side’s gain (the away side lost the same).', '<ul class="sc-list">' + d.moves.slice(0, 12).map(function (m) {
        return '<li><span class="s">' + esc(SC.date(m.date)) + '</span>' + U.teamEnt(S, m.home, { abbr: true }) + '<span class="s">v</span>' + U.teamEnt(S, m.away, { abbr: true }) + '<span class="v ' + SC.cls(m.x) + '">' + SC.signed(m.x, 2) + '</span></li>';
      }).join('') + '</ul>') : '') + '</div></div>';
    html += checkNote(d.check);
    if ((d.what_if || []).length) {
      html += U.sec('What each result would do', 'The next tests, five ways', 'The points each side gains or loses for each kind of result, from today’s points and the published formula' +
        (d.rule && d.rule.home_bonus_ends ? ' (no home allowance since ' + SC.date(d.rule.home_bonus_ends) + ')' : '') + '. A win by more than 15 is worth half as much again; World Cup matches count double.',
        '<div class="sc-wis">' + d.what_if.map(function (w) { return whatIf(S, w); }).join('') + '</div>');
    }
    body.innerHTML = html;
    U.wire(body);
    histChart(QK.$('#rk-hist', body), S, d.history || {}, rows.slice(0, 10).map(function (r) { return r.id; }).filter(function (id) { return (d.history || {})[id]; }), 'World Rugby points');
  });
});
})();
