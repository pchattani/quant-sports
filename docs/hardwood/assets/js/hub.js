/* The Quant Hardwood — the hub (#/ and #/<L>).
 *
 *   band: the league and season, its phase, a countdown to the next tip-off (or the
 *         number of games live), KPI tiles (title favourite, best team, MVP favourite);
 *   games: live and today's games with model against market (moneyline, spread, total)
 *          and live win probability, else the next games, then recent results;
 *   key upcoming games (by how much each result moves playoff or title odds);
 *   title odds against the market, power ratings, the award race, a standings snapshot,
 *   explore links and the sister sites.
 *
 * Works in the preseason (projected wins instead of records) and in the playoffs (series
 * tags, title odds). Reads index.json, <L>/<S>/season.json, markets.json, awards.json. */
(function (HW) {
'use strict';

const esc = HW.esc;

function tile(v, label) { return '<div class="hb-tile"><span class="hb-v">' + v + '</span><span class="hb-l">' + esc(label) + '</span></div>'; }

function phaseText(ph) {
  return { preseason: 'Preseason', regular: 'Regular season', playin: 'Play-in tournament', playoffs: 'Playoffs', offseason: 'Offseason' }[ph] || (ph ? HW.titleCase(ph) : '');
}

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
      return HW.isNum(n.if_win[k]) && HW.isNum(n.if_loss[k]) ? Math.abs(n.if_win[k] - n.if_loss[k]) : 0;
    };
    const lev = swing(nx) + swing(other);
    seen[nx.game] = 1;
    const card = (cards || []).find(c => String(c.id) === String(nx.game));
    out.push({ id: nx.game, lev: lev, date: nx.date, home: nx.home ? tid : nx.opp, away: nx.home ? nx.opp : tid,
      p_home: nx.home ? nx.p_win : (HW.isNum(nx.p_win) ? 1 - nx.p_win : null), card: card,
      key: keyOf(nx.if_win, ['playoffs', 'postseason', 'title']) });
  });
  return out.filter(x => x.lev > 0.005).sort((a, b) => b.lev - a.lev);
}

function powerRows(L, season) {
  const pw = (season && season.power) || [];
  let list = pw.map(r => ({ tid: String(r[0]), net: r[1], chg: r[2] }));
  if (!list.length && season && season.ratings) {
    list = Object.keys(season.ratings).map(t => ({ tid: t, net: season.ratings[t].net, chg: null })).sort((a, b) => b.net - a.net);
  }
  if (!list.length) return HW.muted('Ratings arrive with the first games.');
  const max = Math.max.apply(null, list.map(r => Math.abs(r.net || 0))) || 1;
  return list.slice(0, 10).map((r, i) => {
    const w = Math.abs(r.net || 0) / max * 50;
    const col = HW.teamColour(L, r.tid);
    const fill = (r.net || 0) >= 0 ? 'left:50%;width:' + w.toFixed(1) + '%' : 'left:' + (50 - w).toFixed(1) + '%;width:' + w.toFixed(1) + '%';
    const chg = HW.isNum(r.chg) && r.chg !== 0 ? '<span class="' + (r.chg > 0 ? 'pos-up' : 'pos-down') + '">' + (r.chg > 0 ? '▲' : '▼') + Math.abs(r.chg) + '</span>' : '';
    return '<div class="pw-row"><span class="pw-rank">' + (i + 1) + '</span><span class="pw-name">' + HW.teamLink(L, r.tid, { short: true }) + '</span>' +
      '<span class="pw-track"><span class="pw-mid"></span><span class="pw-fill" style="' + fill + ';background:' + esc(col) + '"></span></span>' +
      '<span class="pw-v">' + HW.signed(r.net, 1) + '</span><span class="pw-chg" title="Rank change over 7 days">' + chg + '</span></div>';
  }).join('') + '<a class="more-link" href="' + HW.seasonHref(L) + '">All teams, rating paths and schedule difficulty →</a>';
}

function standingsSnapshot(L, season, sim, preseason) {
  const st = (season && season.standings) || {};
  const confs = Object.keys(st);
  if (!confs.length) return HW.muted('Standings arrive with the season.');
  const html = confs.map(conf => {
    let rows = (st[conf] || []).slice();
    if (preseason) rows.sort((a, b) => ((sim[b.team] || {}).exp_w || 0) - ((sim[a.team] || {}).exp_w || 0));
    rows = rows.slice(0, confs.length > 1 ? 8 : 10);
    return '<div><div class="day-head">' + esc(conf) + '</div>' + HW.tableHTML(
      [{ label: '#', align: 'right' }, { label: 'Team' }, { label: preseason ? 'Proj W' : 'W-L', align: 'right' }, { label: 'Playoffs', align: 'right' }],
      rows.map((r, i) => {
        const s = sim[r.team] || {};
        return [{ v: i + 1, html: '<span class="seed-n">' + (preseason ? i + 1 : (r.seed || i + 1)) + '</span>' },
          { v: HW.teamName(L, r.team), html: HW.teamLink(L, r.team, { short: true }) },
          preseason ? { v: s.exp_w, html: HW.num(s.exp_w, 1) } : { v: r.pct, html: HW.record(r.w, r.l) },
          { v: s.p_playoffs, html: HW.isNum(s.p_playoffs) ? HW.pct(s.p_playoffs, 0) : '—' }];
      }), { compact: true }) + '</div>';
  }).join('');
  return '<div class="mini-st">' + html + '</div><a class="more-link" href="' + HW.seasonHref(L) + '">Full standings with seed odds and magic numbers →</a>';
}

function awardRace(el, L, awards) {
  const keys = ['mvp', 'roy', 'dpoy', 'sixth', 'mip', 'clutch'];
  const names = { mvp: 'MVP', roy: 'Rookie', dpoy: 'Defensive', sixth: 'Sixth player', mip: 'Most improved', clutch: 'Clutch' };
  const have = keys.filter(k => awards && awards[k] && awards[k].model && Object.keys(awards[k].model).length);
  if (!have.length) { el.innerHTML = HW.muted('The award models start once enough games are played.'); return; }
  let active = have[0];
  const draw = () => {
    const a = awards[active];
    const mk = HW.titleProbs(a.market);
    const items = Object.keys(a.model).map(pid => ({ label: HW.playerShort(L, pid), p: a.model[pid], market: HW.isNum(mk[pid]) ? mk[pid] : null,
      colour: HW.teamColour(L, (HW.NAMES[L].players[pid] || {}).team) })).sort((x, y) => y.p - x.p).slice(0, 6);
    HW.charts.probBars(el.querySelector('.aw-chart'), items, { height: 230, top: 6 });
  };
  el.innerHTML = '<div class="toggle-row">' + HW.toggles(have.map(k => ({ key: k, label: names[k] })), active, 'data-aw') + '</div><div class="aw-chart"></div>' +
    '<a class="more-link" href="' + HW.href(L, 'awards') + '">All award races with the reasoning →</a>';
  HW.wireToggles(el, 'data-aw', k => { active = k; draw(); });
  draw();
}

function explore(L) {
  const links = [
    ['season/' + HW.state.season, 'Season', 'Standings, seed odds, rating paths'],
    ['games', 'Games', 'Every game by date'],
    ['playoffs', 'Playoffs', 'Bracket and series odds'],
    ['markets', 'Markets', 'Model against the market'],
    ['players', 'Players', 'Impact, shooting, percentiles'],
    ['teams', 'Teams', 'Ratings, lineups, shot profiles'],
    ['leaders', 'Leaders', 'Per game and per 100'],
    ['lab', 'Lab', 'Scatter any two metrics'],
    ['calibration', 'Calibration', 'How good is the model?']
  ];
  return '<div class="hub-links pad">' + links.map(l => '<a href="' + (l[0].indexOf('season/') === 0 ? '#/' + L + '/' + l[0] : HW.href(L, l[0])) + '"><b>' + esc(l[1]) + '</b><span>' + esc(l[2]) + '</span></a>').join('') +
    '<a href="#/methodology"><b>Methodology</b><span>How the models work</span></a>' +
    '<a href="' + HW.FOOTBALL_URL + '"><b>⚽ The Quant Footballer</b><span>The sister site for football</span></a>' +
    '<a href="' + HW.PADDOCK_URL + '"><b>🏁 The Quant Paddock</b><span>The sister site for Formula 1</span></a>' +
    '<a href="' + HW.ACE_URL + '"><b>🎾 The Quant Ace</b><span>The sister site for ATP and WTA tennis</span></a>' +
    '<a href="' + HW.BULLPEN_URL + '"><b>⚾ The Quant Bullpen</b><span>The sister site for MLB</span></a>' +
    '<a href="' + HW.GRIDIRON_URL + '"><b>🏈 The Quant Gridiron</b><span>The sister site for the NFL</span></a>' +
    '<a href="' + HW.RINK_URL + '"><b>🏒 The Quant Rink</b><span>The sister site for the NHL</span></a></div>';
}

function render(el, params) {
  const L = params.league, S = params.season;
  const info = HW.leagueInfo(L);
  const isCurrent = S === HW.currentSeason(L);
  const ph = isCurrent ? (info.phase || null) : 'offseason';
  el.innerHTML = '<div class="hw-band" id="hub-band"></div>' +
    '<div class="hub-cols"><div id="hub-left"></div><div id="hub-right"></div></div>' +
    HW.card('Explore', 'the ' + HW.leagueName(L) + ' pages and the sister sites', explore(L));
  return HW.loadAll([HW.path('season.json', L, S), HW.lpath('markets.json', L), HW.path('awards.json', L, S), HW.path('players.json', L, S)]).then(arr => {
    if (!el.isConnected) return;
    const season = HW.ok(arr[0]) ? arr[0] : null, markets = HW.ok(arr[1]) ? arr[1] : null, awards = HW.ok(arr[2]) ? arr[2] : null;
    const sim = HW.simTeams(season);
    const preseason = ph === 'preseason' || (season && Object.keys(season.standings || {}).every(c => (season.standings[c] || []).every(r => !r.w && !r.l)));
    const today = isCurrent ? (info.today || []) : [], next = isCurrent ? (info.next_games || []) : [], last = isCurrent ? (info.last_games || []) : [];
    const upcoming = today.concat(next).filter(g => HW.gameState(g) === 'pre').sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const liveN = today.filter(g => HW.gameState(g) === 'in').length;
    const champ = (info.champions || []).find(c => Number(c[0]) === Number(S));

    // ── band
    let left = '<div class="card"><div class="pad"><div class="hb-kicker">' + esc(HW.leagueName(L)) + ' · ' + esc(phaseText(ph) || 'Season') + '</div>' +
      '<div class="hb-league">' + esc(info.name || HW.leagueName(L)) + ' <span class="hb-season">' + esc(HW.seasonLabel(L, S)) + '</span></div>';
    if (!isCurrent && champ) left += '<div class="hb-sub">Champion: ' + (HW.NAMES[L].teams[String(champ[1])] ? HW.teamLink(L, champ[1]) : esc(champ[1])) + '</div>';
    else if (preseason) left += '<div class="hb-sub">Projections from the preseason ratings; records start on opening night.</div>';
    else if (ph === 'playoffs') left += '<div class="hb-sub">Series odds and title chances update after every game. <a href="' + HW.href(L, 'playoffs') + '">The bracket →</a></div>';
    left += '<div class="cd-row"><div class="cd-box" id="hub-cd"></div></div></div></div>';
    const tTeams = Object.keys(sim).filter(t => HW.isNum(sim[t].p_title)).sort((a, b) => sim[b].p_title - sim[a].p_title);
    const fav = tTeams[0];
    const pw = (season && season.power) || [];
    const mvp = awards && awards.mvp && awards.mvp.model ? Object.keys(awards.mvp.model).sort((a, b) => awards.mvp.model[b] - awards.mvp.model[a])[0] : null;
    let right = '<div class="card"><div class="card-header">At a glance</div><div class="pad"><div class="hub-mini-tiles">' +
      tile(fav ? esc(HW.teamAbbr(L, fav)) + ' ' + HW.pct(sim[fav].p_title, 0) : '—', 'Title favourite') +
      tile(pw[0] ? esc(HW.teamAbbr(L, pw[0][0])) + ' ' + HW.signed(pw[0][1], 1) : '—', 'Best net rating') +
      tile(mvp ? esc(HW.playerShort(L, mvp)) : '—', 'MVP favourite') + '</div>' +
      '<div class="lw-sub" style="margin-top:10px">' + (today.length ? today.length + ' game' + (today.length > 1 ? 's' : '') + ' today' + (liveN ? ' · <span class="cd-live">' + liveN + ' live</span>' : '') : 'No games today') +
      (season && season.updated_at ? ' · model updated ' + esc(HW.fmtStamp(season.updated_at)) : '') + '</div></div></div>';
    document.getElementById('hub-band').innerHTML = left + right;
    const firstPre = upcoming[0];
    const tick = () => {
      const cd = document.getElementById('hub-cd');
      if (!cd) return;
      if (liveN) { cd.innerHTML = '<div class="cd-label">Now</div><div class="cd-value cd-live"><span class="live-dot"></span> ' + liveN + ' live</div><div class="cd-when">Scores and win probability below.</div>'; return; }
      if (firstPre && HW.countdown(firstPre.date)) {
        cd.innerHTML = '<div class="cd-label">Next tip-off · ' + esc(HW.teamAbbr(L, firstPre.away)) + ' @ ' + esc(HW.teamAbbr(L, firstPre.home)) + '</div><div class="cd-value">' + esc(HW.countdown(firstPre.date)) + '</div>' +
          '<div class="cd-when">' + esc(HW.fmtDate(firstPre.date, { time: true })) + ' (your time)</div>';
        return;
      }
      cd.innerHTML = '<div class="cd-label">' + esc(HW.seasonLabel(L, S)) + '</div><div class="cd-value" style="font-size:1.2rem">' + (ph === 'offseason' || !isCurrent ? 'Season complete' : 'No games scheduled soon') + '</div><div class="cd-when">' +
        (ph === 'offseason' ? 'The schedule returns with the next season.' : 'Check the games page for the calendar.') + '</div>';
    };
    tick();
    HW.interval(tick, 1000);

    // ── left: games and key games
    const lg = document.getElementById('hub-left');
    let games = '';
    const shown = {};
    const block = (title, list, opts) => {
      const l = list.filter(g => !shown[g.id]);
      if (!l.length) return '';
      l.forEach(g => { shown[g.id] = 1; });
      return '<div class="day-head">' + esc(title) + '</div><div class="gc-grid">' + l.map(g => HW.gameCard(g, Object.assign({ league: L }, opts || {}))).join('') + '</div>';
    };
    const live = today.filter(g => HW.gameState(g) === 'in');
    games += block('Live', live);
    games += block('Today', today);
    if (!today.length) games += block('Next up', next.slice(0, 8), { date: true });
    games += block('Recent results', last.slice().sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 6), { date: true });
    lg.innerHTML = HW.card(today.length ? 'Tonight' : 'Games', 'model against the market · fair win % beside each team',
      (games || HW.muted(isCurrent ? 'No games in the next few days.' : 'Browse the ' + esc(HW.seasonLabel(L, S)) + ' games by date.')) +
      '<a class="more-link" href="' + HW.href(L, 'games') + '">All games by date →</a>') +
      '<div id="hub-key"></div>';
    const lev = leverage(sim, today.concat(next));
    if (lev.length) {
      const rows = lev.slice(0, 6).map(x => [
        { v: x.date, html: esc(HW.fmtDate(x.card ? x.card.date : x.date, { year: false })) },
        { v: HW.teamName(L, x.away), html: HW.teamLink(L, x.away, { abbr: true }) + ' @ ' + HW.teamLink(L, x.home, { abbr: true }) },
        { v: x.p_home, html: HW.isNum(x.p_home) ? esc(HW.teamAbbr(L, x.home)) + ' ' + HW.pct(x.p_home, 0) : '—', align: 'right' },
        { v: x.lev, html: '<span class="lev">' + HW.num(x.lev * 100, 1) + ' pp</span>', align: 'right', title: 'Combined swing in ' + String(x.key || '').replace(/_/g, ' ') + ' odds between a win and a loss' },
        { html: HW.gameLink(L, x.id, '→') }
      ]);
      document.getElementById('hub-key').innerHTML = HW.card('Key upcoming games', 'ranked by how much the result moves both teams’ ' + (ph === 'playoffs' ? 'title' : 'playoff') + ' odds',
        HW.tableHTML([{ label: 'Date' }, { label: 'Game' }, { label: 'Model', align: 'right' }, { label: 'Leverage', align: 'right' }, { label: '', sortable: false }], rows, { compact: true }));
    }

    // ── right: title odds, power, awards, standings
    const rg = document.getElementById('hub-right');
    rg.innerHTML = HW.card('Title odds', 'model bars · market ticks', '<div id="hub-title"></div><a class="more-link" href="' + HW.href(L, 'markets') + '">Every market against the model →</a>') +
      HW.card('Power ratings', 'net points per 100 possessions, adjusted for opponents', powerRows(L, season)) +
      HW.card('Award race', 'model probability · market ticks', '<div id="hub-aw"></div>') +
      HW.card(preseason ? 'Projected standings' : 'Standings', preseason ? 'by projected wins' : 'with playoff odds', standingsSnapshot(L, season, sim, preseason));
    const mkt = HW.titleProbs(markets && markets.futures && markets.futures.champion);
    const items = tTeams.slice(0, 10).map(t => ({ label: HW.teamAbbr(L, t), p: sim[t].p_title, market: HW.isNum(mkt[t]) ? mkt[t] : null, colour: HW.teamColour(L, t) }));
    if (items.length) HW.charts.probBars('hub-title', items, { top: 10 });
    else document.getElementById('hub-title').innerHTML = !season ? HW.notBuilt('The season model', arr[0]) : HW.muted('No title odds for this season.');
    awardRace(document.getElementById('hub-aw'), L, awards);
    HW.sortable(el);
    HW.setMeta(season && season.sim && season.sim.n_sims ? HW.num(season.sim.n_sims, 0) + ' season simulations' : '');
  });
}

HW.route('hub', render);
})(window.HW);
