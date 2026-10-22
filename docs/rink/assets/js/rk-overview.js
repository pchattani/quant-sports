/* The Quant Rink — Overview (#/): the numbers and charts first.
 *
 *   KPI strip: games today (live), the Stanley Cup favourite, the top-rated club, the points leader, the
 *              biggest model–market gap;
 *   games: live and today's games (then the next and the latest results) as kit match cards, model v market;
 *   charts: Stanley Cup odds model v market (dumbbell), today's games model v market, power ratings,
 *           results v process (points % against 5v5 xGF%), playoff odds by conference;
 *   standings snapshot by conference and four leader boards (counting stats: no sample floor needed).
 *
 * Reads index.json, <S>/season.json, <S>/markets.json. Refreshes every minute while a game is live. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;

function kpis(idx, rows, cup) {
  const today = idx.today || [], live = (idx.live || []).length || today.filter(g => U.status(g) === 'live').length;
  const fav = cup.slice().sort((a, b) => (b.model || 0) - (a.model || 0))[0];
  const top = rows.slice().filter(r => isNum(r.rating)).sort((a, b) => b.rating - a.rating)[0];
  const ld = ((idx.leaders || {}).s_p || [])[0];
  const gap = (idx.gaps || [])[0];
  const gapTxt = gap ? (gap.kind === 'game' ? RK.teamAbbr(gap.away) + ' @ ' + RK.teamAbbr(gap.home) : RK.teamAbbr(gap.team) + ' ' + (gap.kind === 'cup' ? 'Cup' : gap.kind)) : '—';
  const out = [
    QK.kpi({ label: live ? 'Live now' : 'Games today', value: String(live || today.length), sub: live ? today.length + ' on the slate today' : (today.length ? 'first puck drop ' + QK.fmt.time((today[0] || {}).start) : 'no games today') }),
    QK.kpi({ label: 'Cup favourite', value: fav ? RK.teamAbbr(fav.team) + ' ' + U.pct(fav.model) : '—', sub: fav && isNum(fav.market) ? 'market ' + U.pct(fav.market) : 'model, 20,000 simulations', tip: 'Probability of winning the Stanley Cup in our season simulation' }),
    QK.kpi({ label: 'Top-rated club', value: top ? RK.teamAbbr(top.team) + ' ' + U.signed(top.rating, 2) : '—', sub: top ? 'goals a game better than average' : '', tip: 'Our team rating: expected goal difference per game against an average club' }),
    QK.kpi({ label: 'Points leader', value: ld ? RK.playerSurname(ld[0]) + ' ' + ld[1] : '—', sub: ld ? RK.teamAbbr(RK.player(ld[0]).team) : '', text: false }),
    QK.kpi({ label: 'Biggest gap v market', value: gap ? QK.fmt.pp(gap.edge) : '—', sub: gapTxt, tip: 'Model probability minus the market price, the largest disagreement right now' })
  ];
  return '<div class="qk-kpis rk-kpis">' + out.join('') + '</div>';
}

function gamesBlock(idx) {
  const today = (idx.today || []).slice(), live = idx.live || [];
  const seen = {};
  const list = [];
  live.concat(today).forEach(g => { if (!seen[g.game_id]) { seen[g.game_id] = 1; list.push(g); } });
  const order = { live: 0, pre: 1, final: 2 };
  list.sort((a, b) => order[U.status(a)] - order[U.status(b)] || String(a.start).localeCompare(String(b.start)));
  const up = (idx.upcoming || []).filter(g => !seen[g.game_id]).slice(0, 6);
  const rec = (idx.recent || []).filter(g => !seen[g.game_id]).slice().sort((a, b) => String(b.start).localeCompare(String(a.start))).slice(0, 6);
  return { today: list, upcoming: up, recent: rec };
}

function render(el, params) {
  const S = RK.currentSeason();
  const idx = RK.index() || {};
  el.innerHTML = '<header class="rk-head"><div><div class="qk-kicker">NHL · ' + esc(RK.seasonLabel(S)) + (RK.phaseLabel() ? ' · ' + esc(RK.phaseLabel()) : '') + '</div>' +
    '<h1>Every NHL game, priced.</h1><div class="qk-sub">Our win probability on every game against the market, playoff and Cup odds from 20,000 simulations of the season, and the numbers behind them.</div></div>' +
    '<div class="rk-flex"><a class="qk-btn" href="#/games">All games</a><a class="qk-btn" href="#/standings">Standings</a></div></header>' +
    '<div id="ov-kpis">' + QK.skeleton('lines', 2) + '</div>' +
    '<section class="qk-section" style="margin-top:var(--sp-6)"><div class="qk-section-head"><div><h2 id="ov-gh">Tonight</h2><div class="qk-sub">Model win probability on every card; the blue dot is our model, the orange the market.</div></div>' +
    '<div class="qk-seg" id="ov-when" role="group" aria-label="Games"><button type="button" aria-pressed="true" data-value="today">Today</button><button type="button" aria-pressed="false" data-value="next">Next</button><button type="button" aria-pressed="false" data-value="results">Results</button></div></div>' +
    '<div class="rk-games" id="ov-games">' + QK.skeleton('card', 3) + '</div></section>' +
    '<section class="qk-section"><div class="qk-grid">' +
    '<div class="qk-span-7">' + U.card2('Stanley Cup odds', 'Blue: our model · orange: the market (Kalshi and Polymarket, de-vigged)', U.chart('ov-cup', 430, 'Stanley Cup odds, model against market'), { id: 'ov-cup-card', foot: '<span>Gap = model minus market</span><a href="#/standings?tab=markets">Every futures market →</a>' }) + '</div>' +
    '<div class="qk-span-5">' + U.card2('Power ratings', 'Expected goal difference a game against an average club', U.chart('ov-power', 430, 'Team ratings'), { foot: '<span>All 32 clubs</span><a href="#/standings?tab=ratings">Ratings by component →</a>' }) + '</div>' +
    '</div></section>' +
    '<section class="qk-section"><div class="qk-grid">' +
    '<div class="qk-span-6">' + U.card2('Results v process', 'Points % against share of 5v5 expected goals: right of the line plays better than it looks, above it is winning more than its play', U.chart('ov-luck', 360, 'Points percentage against expected goals share'), { foot: '<span>Click a club for its page</span><a href="#/teams">All teams →</a>' }) + '</div>' +
    '<div class="qk-span-6">' + U.card2('Tonight: model v market', 'Home win probability, our model against the market', '<div id="ov-mvm"></div>', { foot: '<span>Pre-game prices only</span><a href="#/games">Games →</a>' }) + '</div>' +
    '</div></section>' +
    '<section class="qk-section"><div class="qk-section-head"><div><h2>Playoff race</h2><div class="qk-sub">Probability of making the playoffs, by conference, from the season simulation.</div></div>' +
    '<div class="qk-seg" id="ov-conf" role="group" aria-label="Conference"><button type="button" aria-pressed="true" data-value="Eastern">East</button><button type="button" aria-pressed="false" data-value="Western">West</button></div></div>' +
    '<div class="qk-grid"><div class="qk-span-7">' + U.card2('Playoff odds', 'Bars: P(playoffs); the line is the 50% mark', U.chart('ov-po', 440, 'Playoff odds')) + '</div>' +
    '<div class="qk-span-5">' + U.card2('Standings', 'Points, points % and the simulated playoff odds', '<div id="ov-st"></div>', { flush: true, foot: '<span>Wild-card format</span><a href="#/standings">Full standings →</a>' }) + '</div></div></section>' +
    '<section class="qk-section"><div class="qk-section-head"><div><h2>Leaders</h2><div class="qk-sub">Counting stats this season. Rates with sample floors are on the <a class="qk-link" href="#/players">Players</a> page.</div></div></div>' +
    '<div class="qk-grid" id="ov-leaders"></div></section>';

  return Promise.all([RK.load(S + '/season.json'), RK.load(S + '/markets.json')]).then(res => {
    if (!U.alive(el)) return;
    const season = RK.ok(res[0]) ? res[0] : {}, mk = RK.ok(res[1]) ? res[1] : {};
    const rows = ((season.standings || {}).rows || []).slice();
    const cup = (((mk.futures || {}).cup) || []).slice();
    const odds = idx.playoff_odds || {};
    if (!cup.length) Object.keys(odds).forEach(t => cup.push({ team: t, model: odds[t].p_cup, market: null }));
    el.querySelector('#ov-kpis').innerHTML = kpis(idx, rows, cup);

    // games
    const G = gamesBlock(idx);
    const draw = w => {
      const list = w === 'next' ? G.upcoming : w === 'results' ? G.recent : G.today;
      el.querySelector('#ov-gh').textContent = w === 'next' ? 'Next up' : w === 'results' ? 'Latest results' : (G.today.length ? 'Tonight' : 'Today');
      el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(g => U.card(g)).join('') : QK.empty('No games', w === 'today' ? 'No games today: see the next ones.' : 'Nothing to show yet.');
    };
    draw(G.today.length ? 'today' : 'next');
    if (!G.today.length) el.querySelectorAll('#ov-when button').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('data-value') === 'next' ? 'true' : 'false'));
    QK.seg(el.querySelector('#ov-when'), draw);

    // cup odds
    const cupRows = cup.filter(r => isNum(r.model)).sort((a, b) => b.model - a.model).slice(0, 12);
    const hasMk = cupRows.some(r => isNum(r.market));
    if (hasMk) {
      const dr = cupRows.map(r => ({ label: RK.teamName(r.team), a: r.model, b: isNum(r.market) ? r.market : r.model, href: RK.teamHref(r.team), sub: isNum(r.market) ? 'Gap ' + QK.fmt.pp(r.model - r.market) : 'no market price' }));
      const mx = Math.max.apply(null, dr.map(r => Math.max(r.a, r.b)));
      QKC.dumbbell('#ov-cup', { rows: dr, aName: 'Model', bName: 'Market', min: 0, max: Math.min(1, Math.ceil(mx * 20) / 20 + 0.02), labelWidth: 150, valName: 'Chance of winning the Cup' });
    } else {
      QKC.bar('#ov-cup', { cats: cupRows.map(r => RK.teamName(r.team)), series: [{ name: 'Model', data: cupRows.map(r => r.model) }], horizontal: true, labels: true, fmt: v => U.pct(v), colors: cupRows.map(r => RK.teamColourRaw(r.team)), hrefs: cupRows.map(r => RK.teamHref(r.team)), valName: 'Chance of winning the Cup' });
    }

    // power
    const pw = rows.filter(r => isNum(r.rating)).sort((a, b) => b.rating - a.rating);
    if (pw.length) {
      QKC.bar('#ov-power', { cats: pw.map(r => r.team), series: [{ name: 'Rating', data: pw.map(r => r.rating) }], horizontal: true, diverging: true, fmt: v => U.signed(v, 2), hrefs: pw.map(r => RK.teamHref(r.team)), labelWidth: 44, valName: 'Expected goal difference a game' });
    } else el.querySelector('#ov-power').innerHTML = QK.empty('No ratings yet', 'Ratings arrive with the first games.');

    // results v process
    const pts = rows.filter(r => isNum(r.xgf_pct) && isNum(r.p_pct) && r.gp > 0).map(r => ({ x: r.xgf_pct, y: r.p_pct, name: RK.teamName(r.team) + ' · ' + r.pts + ' pts in ' + r.gp, label: r.team, color: RK.teamColourRaw(r.team), href: RK.teamHref(r.team), size: 13 }));
    if (pts.length) QKC.scatter('#ov-luck', { points: pts, xName: '5v5 xGF%', yName: 'Points %', xFmt: v => Math.round(v * 100) + '%', yFmt: v => Math.round(v * 100) + '%', refX: 0.5, refY: 0.5, labelAll: true,
      quadrants: ['Lucky', 'Good and winning', 'Struggling', 'Unlucky'] });
    else el.querySelector('#ov-luck').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');

    // tonight model v market
    const pre = (idx.today || []).concat(idx.upcoming || []).filter(g => U.status(g) === 'pre' && g.model && isNum(g.model.p_home) && g.market && isNum(g.market.p_home)).slice(0, 10);
    if (pre.length) {
      el.querySelector('#ov-mvm').innerHTML = U.chart('ov-mvm-c', Math.max(220, 34 * pre.length + 50), 'Home win probability, model against market');
      QKC.dumbbell('#ov-mvm-c', { rows: pre.map(g => ({ label: RK.teamAbbr(g.away) + ' @ ' + RK.teamAbbr(g.home), a: g.model.p_home, b: g.market.p_home, href: RK.gameHref(g.game_id), sub: RK.fmtDate(g.start || g.date, { year: false, time: true }) + ' · ' + RK.srcLabel(g.market.sources) })), aName: 'Model', bName: 'Market', labelWidth: 90, valName: 'Home win probability' });
    } else el.querySelector('#ov-mvm').innerHTML = QK.empty('No pre-game prices', 'Model-v-market appears for games that have not started.');

    // playoff race + standings snapshot
    const conf = c => rows.filter(r => r.conference === c);
    const drawConf = c => {
      const rs = conf(c).filter(r => isNum(r.p_playoffs)).sort((a, b) => b.p_playoffs - a.p_playoffs);
      QKC.mount('#ov-po', T => ({
        grid: { left: 8, right: 46, top: 8, bottom: 30, containLabel: true },
        xAxis: QKC.axis(T, { min: 0, max: 1, fmt: v => Math.round(v * 100) + '%', name: 'Playoff probability', nameLocation: 'middle', nameGap: 26 }),
        yAxis: (function () { const a = QKC.axis(T, { type: 'category', data: rs.map(r => RK.teamName(r.team)), split: false, inverse: true }); a.axisLabel.color = T.ink2; a.axisLabel.width = 150; a.axisLabel.overflow = 'truncate'; return a; })(),
        tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => '<b>' + esc(ps[0].name) + '</b>' + QKC.tipRow(ps[0].color, 'Playoffs', U.pct(ps[0].value)) }),
        series: [{ type: 'bar', barMaxWidth: 14, data: rs.map(r => ({ value: r.p_playoffs, href: RK.teamHref(r.team), itemStyle: { color: QK.color.ensure(RK.teamColourRaw(r.team) || T.model, T.s1, 3), borderRadius: [0, 4, 4, 0] } })),
          label: { show: true, position: 'right', color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: p => U.pct(p.value) },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ xAxis: 0.5 }] } }]
      }), { label: 'Playoff odds, ' + c + ' Conference' });
      const st = conf(c).slice().sort((a, b) => (b.pts - a.pts) || (b.p_pct - a.p_pct));
      QK.table(el.querySelector('#ov-st'), {
        dense: true, rank: true, columns: [
          { key: 'team', label: 'Club', sticky: true, fmt: (v) => U.teamEnt(v, { abbr: true }) },
          { key: 'gp', label: 'GP', num: true }, { key: 'pts', label: 'Pts', num: true },
          { key: 'p_pct', label: 'Pts%', num: true, fmt: v => RK.fmtVal(v, '3') },
          { key: 'p_playoffs', label: 'Playoffs', num: true, fmt: v => U.pct(v) }
        ], rows: st
      });
    };
    drawConf('Eastern');
    QK.seg(el.querySelector('#ov-conf'), drawConf);

    // leaders (counting stats, everyone ranks)
    const L = idx.leaders || {};
    const boards = [['s_p', 'Points', v => String(v)], ['s_g', 'Goals', v => String(v)], ['s_gar', 'Rink value (GAR)', v => U.f(v, 1)], ['g_gsax', 'Goals saved above expected', v => U.signed(v, 1)]];
    el.querySelector('#ov-leaders').innerHTML = boards.map(b => {
      const r = (L[b[0]] || []).slice(0, 5);
      return '<div class="qk-span-3">' + U.card2(b[1], '', r.length ? '<ul class="rk-list">' + r.map((x, i) => '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(x[0], null, RK.player(x[0]).team) + '<span class="v">' + esc(b[2](x[1])) + '</span></li>').join('') + '</ul>' : QK.empty('No leaders yet'), { flush: true }) + '</div>';
    }).join('');

    RK.setMeta('');
    if ((idx.live || []).length || (idx.today || []).some(g => U.status(g) === 'live')) RK.liveRefresh([S + '/season.json'], 60000);
  });
}

RK.page('hub', render);
})(window.RK);
