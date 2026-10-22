/* The Quant Hardwood — Overview (#/<L>): the league at a glance, charts first.
 *
 *   headline numbers (title favourite, best team, MVP favourite, next tip-off or live games, biggest model-v-market gap);
 *   live, today's and upcoming games as kit match cards (model v market), recent results;
 *   who wins it all (model v market), power ratings, projected wins against the market's win-total line,
 *   the award race, the playoff picture (series when the playoffs are on), most valuable players (projected WAR),
 *   key upcoming games by leverage, leaders (qualified players only).
 * A past season shows its champion, final standings and leaders.
 * Reads index.json, <L>/<S>/season.json, <L>/markets.json, <L>/<S>/awards.json, <L>/<S>/valuation.json, <L>/history.json. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const AWN = { mvp: 'MVP', roy: 'Rookie', dpoy: 'Defense', sixth: 'Sixth', mip: 'Most improved', clutch: 'Clutch' };

/* Upcoming games ranked by leverage: how far one result moves both teams' playoff (or title) odds. */
function leverage(sim, cards) {
  const seen = {}, out = [];
  const keyOf = (o, prefer) => { const ks = Object.keys(o || {}); for (let i = 0; i < prefer.length; i++) { const k = ks.find(x => x.indexOf(prefer[i]) >= 0); if (k) return k; } return ks[0]; };
  Object.keys(sim).forEach(tid => {
    const nx = sim[tid] && sim[tid].next;
    if (!nx || !nx.game || seen[nx.game]) return;
    const other = sim[nx.opp] && sim[nx.opp].next && sim[nx.opp].next.game === nx.game ? sim[nx.opp].next : null;
    const swing = n => {
      if (!n || !n.if_win || !n.if_loss) return 0;
      const k = keyOf(n.if_win, ['playoffs', 'postseason', 'title']);
      return isNum(n.if_win[k]) && isNum(n.if_loss[k]) ? Math.abs(n.if_win[k] - n.if_loss[k]) : 0;
    };
    seen[nx.game] = 1;
    const card = (cards || []).find(c => String(c.id) === String(nx.game));
    out.push({ id: nx.game, lev: swing(nx) + swing(other), date: card ? card.date : nx.date, home: nx.home ? tid : nx.opp, away: nx.home ? nx.opp : tid,
      p_home: nx.home ? nx.p_win : (isNum(nx.p_win) ? 1 - nx.p_win : null) });
  });
  return out.filter(x => x.lev > 0.005).sort((a, b) => b.lev - a.lev);
}

function kpis(L, S, d) {
  const out = [];
  const sim = d.sim, tT = Object.keys(sim).filter(t => isNum(sim[t].p_title)).sort((a, b) => sim[b].p_title - sim[a].p_title);
  if (d.isCur) {
    const fav = tT[0];
    const mk = fav && isNum(d.mkTitle[fav]) ? d.mkTitle[fav] : null;
    out.push(QK.kpi({ label: 'Title favourite', value: fav ? HW.teamAbbr(L, fav) + ' ' + U.pct(sim[fav].p_title) : '—', sub: fav ? HW.teamName(L, fav) + (mk !== null ? ' · market ' + U.pct(mk) : '') : 'no simulation yet', tip: 'Share of 20,000 simulated seasons the team wins the title' }));
  } else {
    const ch = d.champ;
    out.push(QK.kpi({ label: 'Champion', value: ch ? HW.teamName(L, ch) : '—', text: true, sub: d.histRow && d.histRow.runner_up ? 'beat ' + HW.teamName(L, d.histRow.runner_up) : HW.seasonLabel(L, S) }));
  }
  const pw = d.power[0];
  if (pw) out.push(QK.kpi({ label: 'Best team', value: HW.teamAbbr(L, pw.tid) + ' ' + U.signed(pw.net, 1), sub: 'net points per 100' + (isNum(pw.se) ? ' ± ' + U.f(pw.se, 1) : ''), tip: 'Opponent-adjusted net rating from the Kalman filter' }));
  if (d.mvp) out.push(QK.kpi({ label: d.isCur ? 'MVP favourite' : 'MVP', value: d.mvp.name, text: true, sub: d.isCur ? 'model ' + U.pct(d.mvp.p) + (isNum(d.mvp.mk) ? ' · market ' + U.pct(d.mvp.mk) : '') : HW.seasonLabel(L, S) }));
  if (d.isCur) {
    const live = d.today.filter(g => HW.gameState(g) === 'in');
    const next = d.upcoming[0];
    if (live.length) out.push(QK.kpi({ label: 'Live now', value: live.length + ' game' + (live.length > 1 ? 's' : ''), sub: live.map(g => HW.teamAbbr(L, g.away) + '–' + HW.teamAbbr(L, g.home)).join(' · ') }));
    else if (next) out.push('<div class="qk-kpi" id="ov-cd">' + cdHTML(L, next) + '</div>');
    else out.push(QK.kpi({ label: 'Next game', value: d.phase === 'offseason' ? 'Offseason' : 'None soon', text: true, sub: 'the schedule returns with the next season' }));
    if (d.edge) out.push(QK.kpi({ label: 'Biggest gap v market', value: QK.fmt.pp(d.edge.gap), sub: d.edge.label, tip: 'Model probability minus the de-vigged market price, percentage points' }));
  } else if (d.best) {
    out.push(QK.kpi({ label: 'Best record', value: HW.teamAbbr(L, d.best[0]) + ' ' + HW.record(d.best[1], d.best[2]), sub: HW.teamName(L, d.best[0]) }));
  }
  return '<div class="qk-kpis hw-kpis">' + out.join('') + '</div>';
}
function cdHTML(L, g) {
  const cd = HW.countdown(g.date);
  return '<div class="qk-kpi-label">Next tip-off</div><div class="qk-kpi-value">' + esc(cd ? cd.replace(/ \d+s$/, '') : HW.fmtTime(g.date)) + '</div>' +
    '<div class="qk-kpi-sub"><span class="qk-truncate">' + esc(HW.teamAbbr(L, g.away) + ' @ ' + HW.teamAbbr(L, g.home) + ' · ' + HW.fmtDate(g.date, { time: true, year: false })) + '</span></div>';
}

function gamesBlock(L, d) {
  const shown = {};
  const take = list => list.filter(g => !shown[g.id] && (shown[g.id] = 1));
  const live = take(d.today.filter(g => HW.gameState(g) === 'in'));
  const today = take(d.today);
  const next = take(d.next).slice(0, Math.max(0, 8 - live.length - today.length));
  const last = take(d.last.slice().sort((a, b) => String(b.date).localeCompare(String(a.date)))).slice(0, 6);
  const grid = (title, list, extra) => list.length ? '<div class="hw-day">' + title + (extra || '') + '</div><div class="hw-games">' + list.map(g => U.card(g, L)).join('') + '</div>' : '';
  const html = grid('<b>Live</b>', live) + grid('<b>Today</b>', today) + grid(today.length || live.length ? 'Coming up' : '<b>Next up</b>', next) + grid('Recent results', last);
  if (!html) return '';
  return '<section class="qk-section hw-sec0"><div class="qk-section-head"><div><h2>' + (live.length ? 'Live and today' : today.length ? 'Tonight' : 'Games') + '</h2>' +
    '<div class="qk-sub">Model win probability on every card; the blue and orange dots compare it with the market before tip-off.</div></div>' + U.link(HW.href(L, 'games'), 'All games') + '</div>' + html + '</section>';
}

/* Projected wins with the 90% range, and the market's win-total line where there is one. */
function winsChart(node, L, rows) {
  return QKC.mount(node, T => {
    const cats = rows.map(r => HW.teamAbbr(L, r.tid));
    const ya = QKC.axis(T, { type: 'category', data: cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.fontSize = 10.5;
    const hasLine = rows.some(r => isNum(r.line));
    return {
      grid: { left: 8, right: 18, top: 28, bottom: 26, containLabel: true },
      legend: { top: 0, left: 0, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2 }, data: ['Model (mean)'].concat(hasLine ? ['Market line'] : []) },
      xAxis: QKC.axis(T, { name: 'Wins', nameLocation: 'middle', nameGap: 24, scale: true }),
      yAxis: ya,
      tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: QKC.hexA(T.ink1, 0.04) } }, formatter: ps => {
        const r = rows[ps[0].dataIndex];
        return '<div style="font-weight:600;margin-bottom:4px">' + esc(HW.teamName(L, r.tid)) + '</div>' + QKC.tipRow(r.c, 'Model', U.f(r.exp, 1) + ' (' + U.f(r.lo, 0) + '–' + U.f(r.hi, 0) + ')') +
          (isNum(r.line) ? QKC.tipRow(T.market, 'Market line', U.f(r.line, 1)) + (isNum(r.pOver) ? QKC.tipRow(T.other, 'Over (model / market)', U.pct(r.pOver) + ' / ' + U.pct(r.pOverMk)) : '') : '');
      } }),
      series: [
        { type: 'custom', silent: true, z: 1, data: rows.map((r, i) => [r.lo, r.hi, i]), encode: { x: [0, 1], y: 2 },
          renderItem: (p, api) => { const a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]);
            return { type: 'rect', shape: { x: a[0], y: a[1] - 3, width: Math.max(2, b[0] - a[0]), height: 6, r: 3 }, style: { fill: QKC.hexA(rows[p.dataIndex].c, 0.35) } }; } },
        { type: 'scatter', name: 'Model (mean)', z: 3, symbolSize: 10, data: rows.map((r, i) => ({ value: [r.exp, i], href: HW.teamHref(L, r.tid), itemStyle: { color: r.c, borderColor: T.s1, borderWidth: 2 } })), itemStyle: { color: T.model } },
        { type: 'scatter', name: 'Market line', z: 4, symbol: 'diamond', symbolSize: 10, itemStyle: { color: T.market, borderColor: T.s1, borderWidth: 1.5 }, data: rows.filter(r => isNum(r.line)).map(r => [r.line, rows.indexOf(r)]) }
      ]
    };
  }, { label: 'Projected wins with the 90% range and the market win-total line' });
}

function render(el, params) {
  const L = U.L(params), S = U.S(params);
  const info = HW.leagueInfo(L);
  const isCur = U.isCur(L, S);
  el.innerHTML = U.secHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S), '', null, null, U.kicker(L, S)) + QK.skeleton('lines', 4);
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.lpath('markets.json', L)), HW.load(HW.path('awards.json', L, S)),
    isCur ? HW.load(HW.path('valuation.json', L, S)) : Promise.resolve(null), HW.load(HW.lpath('history.json', L)), HW.load(HW.path('value.json', L, S))]).then(arr => {
    if (!U.alive(el)) return;
    const season = U.ok(arr[0]) ? arr[0] : null, markets = U.ok(arr[1]) && String(arr[1].season) === String(S) ? arr[1] : null;
    const awards = U.ok(arr[2]) ? arr[2] : null, val = U.ok(arr[3]) ? arr[3] : null, hist = U.ok(arr[4]) ? arr[4] : null;
    const sim = HW.simTeams(season);
    const ph = isCur ? (info.phase || (season && season.phase)) : 'offseason';
    const today = isCur ? (info.today || []) : [], next = isCur ? (info.next_games || []) : [], last = isCur ? (info.last_games || []) : [];
    const upcoming = today.concat(next).filter(g => HW.gameState(g) === 'pre').sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const mkTitle = HW.titleProbs(markets && markets.futures && markets.futures.champion);
    const R = (season && season.ratings) || {};
    let power = ((season && season.power) || []).map(r => ({ tid: String(r[0]), net: r[1], chg: r[2], se: (R[String(r[0])] || {}).se_net }));
    if (!power.length) power = Object.keys(R).map(t => ({ tid: t, net: R[t].net, se: R[t].se_net })).filter(r => isNum(r.net)).sort((a, b) => b.net - a.net);
    const histRow = hist && (hist.seasons || []).find(x => Number(x.season) === Number(S));
    const champRow = (info.champions || []).find(c => Number(c[0]) === Number(S));
    // MVP favourite (model) or the season's MVP
    let mvp = null;
    if (isCur && awards && awards.mvp && awards.mvp.model) {
      const m = awards.mvp.model, mk = HW.titleProbs(awards.mvp.market);
      const top = Object.keys(m).sort((a, b) => (m[b] || 0) - (m[a] || 0))[0];
      if (top) mvp = { id: top, name: HW.playerShort(L, top), p: m[top], mk: mk[top] };
    } else if (histRow && histRow.mvp) mvp = { id: histRow.mvp, name: HW.NAMES[L].players[String(histRow.mvp)] ? HW.playerShort(L, histRow.mvp) : String(histRow.mvp) };
    // biggest model-v-market gap: upcoming games (home side) and the title market
    let edge = null;
    upcoming.forEach(g => {
      const m = (g.model || {}).p_home, k = (g.market || {}).p_home;
      if (isNum(m) && isNum(k) && (!edge || Math.abs(m - k) > Math.abs(edge.gap))) edge = { gap: m - k, label: HW.teamAbbr(L, g.home) + ' v ' + HW.teamAbbr(L, g.away) + ', home win' };
    });
    Object.keys(mkTitle).forEach(t => {
      const m = (sim[t] || {}).p_title, k = mkTitle[t];
      if (isNum(m) && isNum(k) && (!edge || Math.abs(m - k) > Math.abs(edge.gap))) edge = { gap: m - k, label: HW.teamName(L, t) + ' to win the title' };
    });
    const d = { isCur: isCur, sim: sim, mkTitle: mkTitle, power: power, mvp: mvp, today: today, next: next, last: last, upcoming: upcoming, phase: ph, edge: edge,
      champ: histRow ? histRow.champion : (champRow ? champRow[1] : null), histRow: histRow, best: histRow ? histRow.best_record : null };
    const P = { preseason: 'Projections from the preseason ratings until opening night; records start with the first game.', regular: 'Odds update after every game from 20,000 simulations of the rest of the season.',
      playin: 'Play-in week: odds update after every game.', playoffs: 'Series odds and title chances update after every game.', offseason: isCur ? 'The season is over; projections return with the next schedule.' : 'Final numbers for the season.' };
    const sub = P[ph] || '';
    const openSim = Object.keys(sim).some(t => isNum(sim[t].w_p05) && sim[t].w_p95 > sim[t].w_p05);
    const series = (season && season.postseason && season.postseason.series) || [];
    const liveSeries = isCur && ph === 'playoffs' ? series.filter(s => !/wins series/i.test(s.summary || '')) : [];
    const lev = isCur ? leverage(sim, today.concat(next)) : [];
    const ld = (season && season.leaders) || {};
    const ldKeys = ['pts', 'reb', 'ast', '3pm', 'stl', 'blk', 'ts', 'hpm'].filter(k => (ld[k] || []).length);

    let h = U.secHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S), esc(sub), null, null, U.kicker(L, S)) + kpis(L, S, d);
    if (isCur) h += gamesBlock(L, d);
    if (liveSeries.length) {
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Playoff series</h2><div class="qk-sub">Series in progress; the bracket has every round and each team’s chance of reaching it.</div></div>' + U.link(HW.href(L, 'standings') + '?tab=bracket', 'Bracket') + '</div>' +
        '<div class="hw-mini-grid">' + liveSeries.map(s => seriesTile(L, s, sim)).join('') + '</div></section>';
    }
    h += '<section class="qk-section"><div class="qk-section-head"><div><h2>' + (isCur ? 'The race' : 'The season') + '</h2><div class="qk-sub">' +
      (isCur ? 'Model probabilities from the season simulation against the de-vigged prediction-market price where one trades.' : 'Ratings and results for the season.') + '</div></div>' + U.link(HW.href(L, 'standings', S), 'Standings') + '</div><div class="qk-grid">';
    const tTeams = Object.keys(sim).filter(t => isNum(sim[t].p_title) && (sim[t].p_title > 0.001 || isNum(mkTitle[t]))).sort((a, b) => Math.max(sim[b].p_title, mkTitle[b] || 0) - Math.max(sim[a].p_title, mkTitle[a] || 0)).slice(0, 12);
    const awKeys = awards ? (awards.keys || Object.keys(AWN)).filter(k => awards[k] && awards[k].model && Object.keys(awards[k].model).length) : [];
    if (isCur && tTeams.length) h += U.card2('Who wins it all', Object.keys(mkTitle).length ? 'Title probability: <b style="color:var(--c-model)">model</b> v <b style="color:var(--c-market)">market</b>' : 'Title probability from the season simulation', U.chart('ov-title', Math.max(240, 28 * tTeams.length + 40), 'Title odds'), { cls: awKeys.length ? 'qk-span-7' : 'qk-span-12' });
    if (isCur && awKeys.length) {
      h += U.card2('Award race', 'Model probability and the market price', '<div class="qk-seg" id="ov-aw-seg" role="group" aria-label="Award">' + awKeys.map((k, i) => '<button type="button" data-value="' + k + '" aria-pressed="' + (i === 0) + '">' + esc(AWN[k] || k.toUpperCase()) + '</button>').join('') + '</div>' +
        U.chart('ov-aw', 300, 'Award race'), { cls: 'qk-span-5', foot: U.link(HW.href(L, 'players') + '?tab=awards', 'Every race with the reasoning') });
    }
    if (isCur && openSim) h += U.card2('Projected wins', 'Mean of the simulations with the 90% range' + (markets && markets.win_totals ? '; diamonds are the market’s win-total line' : ''), U.chart('ov-wins', Math.max(320, 20 * Object.keys(sim).length + 50), 'Projected wins'), { cls: 'qk-span-7' });
    if (power.length) h += U.card2('Power ratings', 'Net points per 100 possessions, opponent-adjusted', U.chart('ov-power', Math.max(260, 20 * power.length + 20), 'Power ratings'), { cls: isCur && openSim ? 'qk-span-5' : 'qk-span-12', foot: U.link(HW.href(L, 'teams', S), 'Every team') });
    h += '</div></section>';
    // playoff picture / standings
    const st = (season && season.standings) || {};
    const confs = Object.keys(st).filter(c => (st[c] || []).length);
    if (confs.length) {
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>' + (ph === 'preseason' ? 'Projected standings' : isCur ? 'Playoff picture' : 'Final standings') + '</h2><div class="qk-sub">' +
        (isCur ? 'Projected wins and the chance of a playoff place (play-in excluded) and of the title.' : 'Records and seeds.') + '</div></div>' + U.link(HW.href(L, 'standings', S), 'Full standings') + '</div><div class="qk-grid">' +
        confs.map((c, i) => U.card2(c, '', '<div id="ov-st-' + i + '"></div>', { cls: 'qk-span-6', flush: true })).join('') + '</div></section>';
    }
    // value and leverage
    const sv = U.ok(arr[5]) ? arr[5] : null;
    let vrows = U.rowsOf(val).filter(r => isNum(r.w0)).sort((a, b) => b.w0 - a.w0).slice(0, 12);
    const seasonWar = !vrows.length && sv;
    if (seasonWar) vrows = U.rowsOf(sv).filter(r => isNum(r.war) && r.q).sort((a, b) => b.war - a.war).slice(0, 12).map(r => Object.assign({}, r, { w0: r.war }));
    if (vrows.length || lev.length) {
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Who and what matters</h2><div class="qk-sub">' + (seasonWar ? 'Wins above replacement from HPM and minutes.' : 'Projected wins above replacement for the rest of the season, and the games that swing the most.') + '</div></div>' + U.link(HW.href(L, 'value'), 'Value & Moves') + '</div><div class="qk-grid">' +
        (vrows.length ? U.card2('Most valuable players', seasonWar ? 'Wins above replacement over the season (qualified players)' : 'Projected WAR, rest of season (current rosters)', U.chart('ov-war', 28 * vrows.length + 30, 'Most valuable players'), { cls: lev.length ? 'qk-span-7' : 'qk-span-12' }) : '') +
        (lev.length ? U.card2('Games that matter most', 'Combined swing in both teams’ ' + (ph === 'playoffs' ? 'title' : 'playoff') + ' odds between a win and a loss', '<ul class="hw-list">' + lev.slice(0, 8).map(x =>
          '<li><a href="' + esc(HW.gameHref(L, x.id)) + '" class="hw-ent"><span class="nm">' + esc(HW.teamAbbr(L, x.away) + ' @ ' + HW.teamAbbr(L, x.home)) + '</span><span class="sb">' + esc(HW.fmtDate(x.date, { year: false })) + '</span></a>' +
          '<span class="s">' + (isNum(x.p_home) ? esc(HW.teamAbbr(L, x.home)) + ' ' + U.pct(x.p_home) : '') + '</span><span class="v">' + U.f(x.lev * 100, 1) + ' pts</span></li>').join('') + '</ul>', { cls: vrows.length ? 'qk-span-5' : 'qk-span-12', flush: true }) : '') +
        '</div></section>';
    }
    if (ldKeys.length) {
      const LDL = { pts: 'Points', reb: 'Rebounds', ast: 'Assists', '3pm': 'Threes', stl: 'Steals', blk: 'Blocks', ts: 'True shooting', hpm: 'HPM' };
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Leaders</h2><div class="qk-sub">Per game; qualified players only (the league’s minimum games and minutes).</div></div>' + U.link(HW.href(L, 'players', S) + (S && !isCur ? '&' : '?') + 'tab=leaders', 'All leaderboards') + '</div>' +
        '<div class="hw-leaders">' + ldKeys.map(k => '<div class="qk-card"><div class="qk-card-head"><div class="qk-card-title">' + esc(LDL[k]) + '</div></div><ul class="hw-list">' +
          ld[k].slice(0, 5).map((r, i) => { const p = HW.NAMES[L].players[String(r[0])] || {};
            return '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(L, r[0], p.name, p.team, null, S) + '<span class="v">' + HW.fmtVal(r[1], k === 'ts' ? 'pct' : k === 'hpm' ? 'pm' : '1') + '</span></li>'; }).join('') + '</ul></div>').join('') + '</div></section>';
    }
    el.innerHTML = h;

    // ── charts
    if (document.getElementById('ov-title')) {
      if (Object.keys(mkTitle).length) {
        const mx = Math.max.apply(null, tTeams.map(t => Math.max(sim[t].p_title, mkTitle[t] || 0)));
        QKC.dumbbell('#ov-title', { rows: tTeams.map(t => ({ label: HW.teamName(L, t), a: sim[t].p_title, b: isNum(mkTitle[t]) ? mkTitle[t] : sim[t].p_title, href: HW.teamHref(L, t), sub: isNum(mkTitle[t]) ? '' : 'no market price' })),
          aName: 'Model', bName: 'Market', min: 0, max: Math.min(1, Math.ceil(mx * 20) / 20 + 0.05), labelWidth: 140, valName: 'Title probability' });
      } else {
        QKC.bar('#ov-title', { cats: tTeams.map(t => HW.teamName(L, t)), series: [{ name: 'Title', data: tTeams.map(t => sim[t].p_title) }], horizontal: true, labels: true, fmt: v => U.pct(v), colors: tTeams.map(t => U.tcol(L, t)), hrefs: tTeams.map(t => HW.teamHref(L, t)), labelWidth: 140, valName: 'Title probability' });
      }
    }
    if (document.getElementById('ov-power')) {
      QKC.bar('#ov-power', { cats: power.map(r => HW.teamAbbr(L, r.tid)), series: [{ name: 'Net rating', data: power.map(r => Math.round(r.net * 10) / 10) }], horizontal: true, labels: true, fmt: v => U.signed(v, 1),
        colors: power.map(r => U.tcol(L, r.tid)), hrefs: power.map(r => HW.teamHref(L, r.tid, S)), labelWidth: 46, valName: 'Net rating (pts per 100 possessions)' });
    }
    if (document.getElementById('ov-wins')) {
      const wt = (markets && markets.win_totals) || {};
      const rows = Object.keys(sim).filter(t => isNum(sim[t].exp_w)).map(t => ({ tid: t, exp: sim[t].exp_w, lo: sim[t].w_p05, hi: sim[t].w_p95, line: (wt[t] || {}).line, pOver: (wt[t] || {}).p_over_model, pOverMk: (wt[t] || {}).p_over_market, c: U.tcol(L, t) }))
        .sort((a, b) => b.exp - a.exp);
      winsChart(document.getElementById('ov-wins'), L, rows);
    }
    if (document.getElementById('ov-aw')) {
      const drawAw = k => {
        const a = awards[k], mk = HW.titleProbs(a.market);
        const ids = Object.keys(a.model).sort((x, y) => Math.max(a.model[y] || 0, mk[y] || 0) - Math.max(a.model[x] || 0, mk[x] || 0)).slice(0, 8);
        const hasMk = ids.some(id => isNum(mk[id]));
        if (hasMk) {
          const mx = Math.max.apply(null, ids.map(id => Math.max(a.model[id] || 0, mk[id] || 0)));
          QKC.dumbbell('#ov-aw', { rows: ids.map(id => ({ label: HW.playerName(L, id), a: a.model[id] || 0, b: isNum(mk[id]) ? mk[id] : (a.model[id] || 0), href: HW.playerHref(L, id), sub: isNum(mk[id]) ? '' : 'no market price' })), aName: 'Model', bName: 'Market', min: 0, max: Math.min(1, Math.ceil(mx * 20) / 20 + 0.05), labelWidth: 130, valName: 'Award probability' });
        } else {
          QKC.bar('#ov-aw', { cats: ids.map(id => HW.playerName(L, id)), series: [{ name: AWN[k] || k, data: ids.map(id => a.model[id] || 0) }], horizontal: true, labels: true, fmt: v => U.pct(v),
            colors: ids.map(id => U.tcol(L, (HW.NAMES[L].players[String(id)] || {}).team)), hrefs: ids.map(id => HW.playerHref(L, id)), labelWidth: 130, valName: 'Award probability' });
        }
      };
      drawAw(awKeys[0]);
      QK.seg(document.getElementById('ov-aw-seg'), drawAw);
    }
    confs.forEach((c, i) => {
      const node = document.getElementById('ov-st-' + i);
      const pre = ph === 'preseason';
      let rows = (st[c] || []).map(r => Object.assign({}, r, { s: sim[r.team] || {} }));
      if (pre) rows.sort((a, b) => (b.s.exp_w || 0) - (a.s.exp_w || 0));
      const cols = [{ key: 'seed', label: '#', num: true, fmt: (v, r) => String(pre ? rows.indexOf(r) + 1 : (r.seed || rows.indexOf(r) + 1)) },
        { key: 'team', label: 'Team', sticky: true, fmt: v => U.teamEnt(L, v, { short: true, season: S }) },
        pre ? { key: 'exp', label: 'Proj W', num: true, fmt: (v, r) => U.f(r.s.exp_w, 1) } : { key: 'w', label: 'W-L', num: true, fmt: (v, r) => HW.record(r.w, r.l) }];
      if (isCur && Object.keys(sim).length) {
        cols.push({ key: 'pp', label: 'Playoffs', num: true, fmt: (v, r) => probBar(r.s.p_playoffs, U.tcol(L, r.team)) });
        cols.push({ key: 'pt', label: 'Title', num: true, fmt: (v, r) => U.pct(r.s.p_title) });
      } else cols.push({ key: 'pd', label: 'Diff', num: true, fmt: v => U.sgnHTML(v, 0) });
      rows.forEach(r => { r.pp = r.s.p_playoffs; r.pt = r.s.p_title; r.exp = r.s.exp_w; });
      QK.table(node, { columns: cols, rows: rows.slice(0, 10), dense: true });
    });
    if (document.getElementById('ov-war')) {
      QKC.bar('#ov-war', { cats: vrows.map(r => r.name), series: [{ name: 'WAR', data: vrows.map(r => Math.round(r.w0 * 10) / 10) }], horizontal: true, labels: true, fmt: v => U.f(v, 1),
        colors: vrows.map(r => U.tcol(L, r.team)), hrefs: vrows.map(r => HW.playerHref(L, r.id)), labelWidth: 150, valName: seasonWar ? 'Wins above replacement' : 'Projected WAR, rest of season' });
    }
    const first = upcoming[0];
    if (first && !today.some(g => HW.gameState(g) === 'in')) HW.interval(() => { const n = document.getElementById('ov-cd'); if (n) n.innerHTML = cdHTML(L, first); }, 30000);
    HW.setMeta(season && season.sim && season.sim.n_sims ? HW.num(season.sim.n_sims, 0) + ' season simulations' + (season.updated_at ? ' · model ' + esc(HW.fmtStamp(season.updated_at)) : '') : '');
  });
}

function probBar(p, c) {
  if (!isNum(p)) return '—';
  return '<span class="hw-pbar"><span style="width:' + Math.max(1, p * 100).toFixed(1) + '%;background:' + esc(c) + '"></span></span><span class="hw-pv">' + U.pct(p) + '</span>';
}
HW.ui.probBar = probBar;

function seriesTile(L, s, sim) {
  const t = s.teams || [];
  const w = s.wins || {};
  const a = t[0], b = t[1];
  const pa = (sim[a] || {}).p_title, pb = (sim[b] || {}).p_title;
  return '<div class="hw-teamtile" style="--tc:' + esc(U.tcol(L, a)) + '"><div class="qk-kicker">' + esc(s.round || 'Series') + '</div>' +
    [a, b].map(x => '<div class="top">' + QK.teamMark(U.team(L, x), 'sm') + '<a class="nm" href="' + esc(HW.teamHref(L, x)) + '">' + esc(HW.teamName(L, x)) + '</a><span class="rec">' + (isNum(w[x]) ? w[x] : 0) + '</span></div>').join('') +
    '<div class="row"><span>' + esc(s.summary || '') + '</span><b>' + (isNum(pa) || isNum(pb) ? 'title ' + esc(HW.teamAbbr(L, a)) + ' ' + U.pct(pa) + ' · ' + esc(HW.teamAbbr(L, b)) + ' ' + U.pct(pb) : '') + '</b></div></div>';
}

HW.page('hub', render);
})(window.HW);
