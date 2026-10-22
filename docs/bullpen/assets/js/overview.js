/* The Quant Bullpen — Overview (#/ and #/<L>): the season at a glance, charts first.
 *
 *   hero: the level, season and phase, with four headline numbers (title favourite, games today and live,
 *         the biggest model-v-market gap, the model's record against the closing line);
 *   games: live, today, next and recent as the kit's game cards (model, market, edge);
 *   charts: who wins it all (model v market), the postseason bracket, the team strength map (offence
 *           against run prevention), luck (wins against the Pythagorean record), the biggest model-v-market
 *           gaps, and the leaders as bar charts;
 *   standings snapshot: the six divisions with their playoff odds.
 *
 * Reads index.json (cards, postseason, leaders, teams; levels.aaa for Triple-A), <L>/<S>/season.json
 * (standings, ratings, postseason paths), mlb/<S>/markets.json (futures), mlb/calibration.json (backtest).
 * Charts are the kit's (QKC on ECharts); every chart sits beside a list or table with the same numbers. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;

const LEADERS = {
  h_war: ['Bullpen WAR', 'Hitters', '1'], h_xwoba_plus: ['xwOBA+', 'Hitters', 'avg'], h_woba: ['wOBA', 'Hitters', 'avg'], h_hr: ['Home runs', 'Hitters', 'int'],
  h_dv: ['Decision value', 'Hitters', '1'], h_bat_speed_adj: ['Bat speed', 'Hitters', '1'], h_barrel_pct: ['Barrel rate', 'Hitters', 'pct'], h_sprint_speed: ['Sprint speed', 'Hitters', '1'],
  p_war: ['Bullpen WAR', 'Pitchers', '1'], p_stuff_plus: ['Stuff+', 'Pitchers', 'int'], p_pitching_plus: ['Pitching+', 'Pitchers', 'int'], p_k_pct: ['Strikeout rate', 'Pitchers', 'pct'],
  p_ra9: ['RA9', 'Pitchers', '2'], p_fb_velo: ['Fastball velocity', 'Pitchers', '1'], p_csw_pct: ['CSW rate', 'Pitchers', 'pct'], p_tunnel_index: ['Tunnel index', 'Pitchers', 'int']
};
const LOWER = { p_ra9: true };
const PHASE = { preseason: 'Preseason', regular: 'Regular season', postseason: 'Postseason', offseason: 'Off-season', complete: 'Season complete' };

function kpi(label, value, sub, tip) {
  return '<div class="qk-kpi"><div class="qk-kpi-label">' + (tip ? '<span data-tip="' + esc(tip) + '">' + esc(label) + '</span>' : esc(label)) + '</div>' +
    '<div class="qk-kpi-value is-text">' + value + '</div>' + (sub ? '<div class="qk-kpi-sub"><span class="qk-truncate">' + sub + '</span></div>' : '') + '</div>';
}
function chartCard(id, title, sub, h, span, foot) {
  return '<section class="qk-card qk-span-' + span + '"><div class="qk-card-head"><div><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div></div><div class="qk-card-body"><div id="' + id + '" style="--h:' + h + 'px"></div></div>' +
    (foot ? '<div class="qk-card-foot">' + foot + '</div>' : '') + '</section>';
}
function more(href, label) { return '<a href="' + href + '">' + esc(label) + ' →</a>'; }

/* Futures: model against market for the champion (mlb/<S>/markets.json "champion"; model from the postseason paths or index teams). */
function titleRows(idx, post, mk) {
  const pt = (post && post.teams) || {};
  const it = idx.teams || {};
  const mkt = mk && mk.champion && mk.champion.market ? BP.titleProbs(mk.champion.market) : {};
  const ids = Object.keys(Object.keys(pt).length ? pt : it);
  return ids.map(t => {
    const p = isNum((pt[t] || {}).p_ws) ? pt[t].p_ws : (it[t] || {}).p_ws;
    return { t: t, p: p, m: isNum(mkt[t]) ? mkt[t] : null };
  }).filter(r => isNum(r.p) && (r.p > 0.0005 || (isNum(r.m) && r.m > 0.005))).sort((a, b) => b.p - a.p).slice(0, 12);
}

/* The biggest model-v-market gaps: open games, live series, futures. */
function gapRows(cards, post, mk, L) {
  const out = [], seen = {};
  cards.forEach(c => {
    if (!c || seen[c.gpk] || BP.isFinal(c)) return;
    seen[c.gpk] = 1;
    const m = c.model || {}, k = c.market || {};
    if (!isNum(m.p_home) || !isNum(k.p_home)) return;
    const homeUp = m.p_home >= k.p_home;
    const side = homeUp ? c.home : c.away;
    out.push({ label: BP.teamShort(side) + ' to win · ' + BP.teamAbbr(c.away) + ' @ ' + BP.teamAbbr(c.home), sub: BP.fmtDate(c.date, { year: false }) + (c.series ? ' · ' + BP.seriesText(c.series, true) : ''),
      a: homeUp ? m.p_home : 1 - m.p_home, b: homeUp ? k.p_home : 1 - k.p_home, href: BP.gameHref(c.gpk, L) });
  });
  ((post && post.series) || []).forEach(s => {
    if (!s.p || !s.market || s.done) return;
    [0, 1].forEach(i => {
      if (!isNum(s.p[i]) || !isNum(s.market[i]) || s.p[i] < s.market[i]) return;
      out.push({ label: BP.teamShort(s.teams[i]) + ' to win the ' + BP.roundLabel(s.round, true), sub: 'Series · ' + (s.wins ? s.wins[0] + '-' + s.wins[1] : ''), a: s.p[i], b: s.market[i], href: BP.ghref('postseason') });
    });
  });
  if (mk && mk.champion && mk.champion.market) {
    const mkt = BP.titleProbs(mk.champion.market), pt = (post && post.teams) || {};
    Object.keys(mkt).forEach(t => { const p = (pt[t] || {}).p_ws; if (isNum(p) && isNum(mkt[t]) && (p > 0.01 || mkt[t] > 0.01)) out.push({ label: BP.teamShort(t) + ' to win the World Series', sub: 'Futures', a: p, b: mkt[t], href: '#/markets' }); });
  }
  out.forEach(r => { r.gap = r.a - r.b; });
  return out.sort((x, y) => Math.abs(y.gap) - Math.abs(x.gap)).slice(0, 8);
}

function divisionSnapshot(rows, L, S, hasSim) {
  const byDiv = {};
  Object.keys(rows).forEach(t => { const r = rows[t]; if (!r.division) return; (byDiv[r.division] = byDiv[r.division] || []).push(r); });
  const divs = BP.DIVISIONS.filter(d => byDiv[d]).concat(Object.keys(byDiv).filter(d => BP.DIVISIONS.indexOf(d) < 0).sort());
  if (!divs.length) return '';
  return '<div class="ov-divs">' + divs.map(d => {
    const list = byDiv[d].slice().sort((a, b) => (b.pct || 0) - (a.pct || 0) || (b.w || 0) - (a.w || 0));
    const lead = list[0];
    return '<div class="ov-div"><div class="ov-div-head">' + esc(d) + '</div>' + list.map(r => {
      const gb = ((lead.w - r.w) + (r.l - lead.l)) / 2;
      const p = r.sim && isNum(r.sim.p_postseason) ? r.sim.p_postseason : null;
      return '<a class="ov-div-row" href="' + BP.teamHref(r.tid, L, S) + '">' + BP.teamMark(r.tid, 'sm') + '<span class="nm">' + esc(BP.teamShort(r.tid)) + '</span>' +
        '<span class="num">' + esc((r.w || 0) + '-' + (r.l || 0)) + '</span><span class="num muted">' + (gb > 0 ? (gb % 1 ? gb.toFixed(1) : gb) : '—') + '</span>' +
        '<span class="num ' + (r.rd > 0 ? 'edge-pos' : r.rd < 0 ? 'edge-neg' : '') + '">' + (isNum(r.rd) ? BP.signed(r.rd, 0) : '') + '</span>' +
        (hasSim ? '<span class="num">' + (p === null ? '—' : p >= 0.9995 ? '✓' : p <= 0.0005 ? '<span class="muted">0</span>' : BP.pct(p, 0)) + '</span>' : '') + '</a>';
    }).join('') + '</div>';
  }).join('') + '</div><div class="ov-div-key">W-L · games behind · run differential' + (hasSim ? ' · postseason odds from the season simulation (✓ clinched)' : '') + '</div>';
}

function render(el, params) {
  const L = params.level, S = params.season;
  const idx = BP.index() || {};
  const isCurrent = S === BP.currentSeason(L);
  const lv = BP.levelInfo(L);
  const src = L === 'mlb' ? idx : lv;
  const phase = isCurrent ? String(lv.phase || idx.phase || '') : 'complete';
  el.innerHTML = '<div class="ov">' + QK.skeleton('card', 3) + '</div>';
  return BP.loadAll([BP.ypath('season.json', L, S), L === 'mlb' && isCurrent ? BP.ypath('markets.json', L, S) : 'index.json', L === 'mlb' ? BP.lpath('calibration.json', L) : 'index.json']).then(arr => {
    if (!el.isConnected) return;
    const season = BP.ok(arr[0]) ? arr[0] : null;
    const mk = L === 'mlb' && isCurrent && BP.ok(arr[1]) ? arr[1] : null;
    const cal = L === 'mlb' && BP.ok(arr[2]) ? arr[2] : null;
    let post = isCurrent ? (L === 'mlb' ? idx.postseason : lv.postseason) || null : null;
    const sp = season && season.postseason && typeof season.postseason === 'object' && season.postseason.series ? season.postseason : null;
    if (sp) post = Object.assign({}, sp, post || {}, { teams: sp.teams || (post && post.teams), seeds: sp.seeds || (post && post.seeds), series: (post && post.series) || sp.series });
    const rows = BP.standingsRows ? BP.standingsRows(season || {}) : {};
    const hasSim = Object.keys(rows).some(t => rows[t].sim && isNum(rows[t].sim.p_postseason));
    const live = isCurrent ? (src.today || []).filter(BP.isLive) : [];
    const today = isCurrent ? (src.today || []).filter(c => !BP.isLive(c)) : [];
    const upcoming = isCurrent ? (src.upcoming || []) : [], recent = isCurrent ? (src.recent || []) : [];
    const allCards = [].concat(src.today || [], upcoming, recent);
    const titles = L === 'mlb' ? titleRows(idx, post, mk) : [];
    const gaps = L === 'mlb' && isCurrent ? gapRows(allCards, post, mk, L) : [];
    const fav = titles[0] || null;
    const inPost = phase === 'postseason' && post && post.series && post.series.length;

    // ── hero
    const round = inPost && post.round ? BP.roundLabel(post.round) : '';
    const kicker = [BP.levelLong(L), PHASE[phase] || BP.titleCase(phase), round].filter(Boolean).join(' · ');
    let lede;
    if (!isCurrent) lede = 'The ' + S + ' season in numbers: the final standings, how good every club really was, and who was lucky.';
    else if (inPost && L === 'mlb') lede = 'The postseason is on. Every game is priced by our plate-appearance simulation with the probable starters, and every series by simulating the bracket, against Kalshi, Polymarket and DraftKings.';
    else if (L === 'aaa') lede = 'Triple-A Statcast for the International and Pacific Coast Leagues, with major-league translations for every prospect.';
    else lede = 'Every game priced by a plate-appearance simulation against the market, with live win probability while games are on.';
    const nToday = (src.today || []).length;
    const k1 = L === 'mlb' && fav ? kpi('Title favourite', BP.teamMark(fav.t, 'sm') + ' ' + esc(BP.teamShort(fav.t)), 'Model ' + BP.pct(fav.p, 0) + (isNum(fav.m) ? ' · market ' + BP.pct(fav.m, 0) : ''), 'World Series probability from simulating the rest of the season and the bracket')
      : kpi('Clubs', esc(String(Object.keys(rows).length || lv.teams || '—')), BP.levelName(L) + ' ' + S);
    const k2 = isCurrent ? kpi(live.length ? 'Live now' : 'Games today', '<span class="num">' + (live.length || nToday) + '</span>', live.length ? '<span class="qk-badge live">Live</span> ' + nToday + ' today' : (upcoming.length ? upcoming.length + ' more in the next days' : 'no games scheduled'))
      : kpi('Games played', '<span class="num">' + BP.int((lv.final || lv.games || 0)) + '</span>', 'regular season and postseason');
    const g0 = gaps[0];
    const k3 = g0 ? kpi('Biggest gap', '<span class="num ' + (g0.gap > 0 ? 'edge-pos' : 'edge-neg') + '">' + BP.signed(g0.gap * 100, 0) + ' pts</span>', esc(g0.label), 'Model probability minus the de-vigged market, in percentage points')
      : kpi('Top hitter', (src.leaders && src.leaders.h_war && src.leaders.h_war[0]) ? BP.playerLink(src.leaders.h_war[0][0], { level: L }) : '—', (src.leaders && src.leaders.h_war && src.leaders.h_war[0]) ? BP.num(src.leaders.h_war[0][1], 1) + ' Bullpen WAR' : '');
    const pooled = cal && cal.games && cal.games.pooled ? cal.games.pooled : null;
    const vm = pooled && pooled.vs_market ? pooled.vs_market : null;
    const k4 = pooled && pooled.model ? kpi('Model backtest', '<span class="num">' + BP.int(pooled.n_games) + '</span> games', 'log loss ' + BP.num(pooled.model.logloss, 3) + (vm && vm.market ? ' · closing line ' + BP.num(vm.market.logloss, 3) : '') + ' · <a href="#/calibration">calibration</a>', 'Every game since 2015 priced walk-forward, from information before first pitch')
      : kpi('Top pitcher', (src.leaders && src.leaders.p_war && src.leaders.p_war[0]) ? BP.playerLink(src.leaders.p_war[0][0], { level: L }) : '—', (src.leaders && src.leaders.p_war && src.leaders.p_war[0]) ? BP.num(src.leaders.p_war[0][1], 1) + ' Bullpen WAR' : '');

    let html = '<section class="ov-hero"><div class="ov-hero-main"><div class="qk-kicker">' + esc(kicker) + '</div><h1 class="ov-title">' + esc(BP.levelName(L)) + ' <span>' + S + '</span></h1>' +
      '<p class="ov-lede">' + esc(lede) + '</p><div class="ov-hero-links">' +
      '<a class="qk-btn primary" href="' + BP.href('games', L, S) + '">' + (isCurrent ? 'Today’s games' : 'Every game') + '</a>' +
      '<a class="qk-btn" href="' + BP.href('standings', L, S) + '">Standings</a>' + (L === 'mlb' && isCurrent ? '<a class="qk-btn" href="#/markets">Odds board</a>' : '<a class="qk-btn" href="#/prospects">Prospects</a>') + '</div></div>' +
      '<div class="ov-kpis">' + k1 + k2 + k3 + k4 + '</div></section>';

    // ── games
    const shown = {};
    const pickCards = list => list.filter(c => c && !shown[c.gpk] && (shown[c.gpk] = 1));
    const order = pickCards(live).concat(pickCards(today.filter(c => !BP.isFinal(c)).sort((a, b) => String(a.start).localeCompare(String(b.start)))),
      pickCards(upcoming.slice().sort((a, b) => String(a.start || a.date).localeCompare(String(b.start || b.date)))),
      pickCards(today.filter(BP.isFinal)), pickCards(recent.slice().sort((a, b) => String(b.start || b.date).localeCompare(String(a.start || a.date)))));
    if (order.length) {
      html += '<section class="qk-section ov-games"><div class="qk-section-head"><div><h2>' + (live.length ? 'Live and next' : 'Games') + '</h2><div class="qk-sub">Model win probability on every card; the strip compares the model (blue) with the de-vigged market (orange) before first pitch.</div></div>' +
        '<a class="qk-btn" href="' + BP.href('games', L, S) + '">All games</a></div><div class="qk-auto ov-gamegrid" style="--min:270px">' +
        order.slice(0, 8).map(c => BP.gameCard(c, { level: L, date: true })).join('') + '</div></section>';
    }

    // ── charts
    html += '<section class="qk-section"><div class="qk-section-head"><div><h2>The season in charts</h2><div class="qk-sub">Tap a bar or a point to open the team or game.</div></div></div><div class="qk-grid ov-charts">';
    if (titles.length) html += chartCard('ov-title', 'Who wins the World Series', titles.some(r => isNum(r.m)) ? 'Model (blue) against the de-vigged market (orange)' : 'Model probability from simulating the season and the bracket', Math.max(200, titles.length * 34 + 40), 7, more(BP.ghref('postseason'), 'Path odds and series'));
    if (inPost) html += '<section class="qk-card qk-span-' + (titles.length ? 5 : 12) + ' ov-bracket"><div class="qk-card-head"><div><div class="qk-card-title">The bracket</div><div class="qk-card-sub">Series wins and the model’s chance to win each series</div></div></div><div class="qk-card-body"><div id="ov-bk"></div></div><div class="qk-card-foot">' + more(BP.ghref('postseason'), 'Postseason') + '</div></section>';
    const haveRatings = Object.keys(rows).some(t => rows[t].rating && isNum(rows[t].rating.off));
    if (haveRatings) html += chartCard('ov-map', 'Team strength map', 'Offence against run prevention, in runs per game above average (our ratings). Up and right is better.', 400, 7, more(BP.href('teams', L, S), 'Every team'));
    const haveLuck = Object.keys(rows).some(t => isNum(rows[t].pythag_w));
    if (haveLuck) html += chartCard('ov-luck', 'Who has been lucky', 'Wins above (or below) the Pythagorean record from runs scored and allowed', 400, 5, more(BP.href('standings', L, S), 'Standings'));
    if (gaps.length) html += chartCard('ov-gaps', 'Model v market', 'The biggest disagreements right now: games, series and futures', Math.max(220, gaps.length * 40 + 40), 7, more('#/markets', 'Odds board'));
    const lead = src.leaders || {};
    const lkeys = Object.keys(lead).filter(k => (lead[k] || []).length);
    if (lkeys.length) html += '<section class="qk-card qk-span-' + (gaps.length ? 5 : 12) + '"><div class="qk-card-head"><div><div class="qk-card-title">Leaders</div><div class="qk-card-sub">' + esc(BP.levelName(L) + ' ' + S) + '</div></div></div>' +
      '<div class="qk-card-body"><div class="qk-chips scroll ov-lchips" id="ov-lchips">' + lkeys.map((k, i) => '<button type="button" class="qk-chip" aria-pressed="' + (i === 0) + '" data-value="' + esc(k) + '">' + esc((LEADERS[k] || [BP.titleCase(k)])[0] + (LEADERS[k] ? ' · ' + LEADERS[k][1].toLowerCase() : '')) + '</button>').join('') + '</div>' +
      '<div id="ov-lead" style="--h:330px;margin-top:10px"></div></div><div class="qk-card-foot">' + more(BP.href('leaders', L, S), 'Every leaderboard') + '</div></section>';
    html += '</div></section>';

    // ── standings snapshot
    const snap = divisionSnapshot(rows, L, S, hasSim);
    if (snap) html += '<section class="qk-section"><div class="qk-section-head"><div><h2>Standings</h2><div class="qk-sub">' + esc(BP.levelName(L) + ' ' + S) + (inPost ? ' · final regular season' : '') + '</div></div><a class="qk-btn" href="' + BP.href('standings', L, S) + '">Full standings</a></div>' + snap + '</section>';

    // ── explore
    html += '<section class="qk-section"><div class="qk-section-head"><div><h2>Explore</h2></div></div><div class="ov-explore">' + [
      [BP.href('hitters', L, S), 'Players', 'Savant-style percentiles, expected stats and arsenals'],
      [BP.href('value', L, S), 'Value & Moves', 'What every player is worth; trades rated and simulated'],
      ['#/mlb/fantasy', 'Fantasy', 'Roto and points rankings, dynasty, closers, streamers'],
      [BP.href('lab', L, S), 'Lab', 'Scatter any two metrics; compare players'],
      ['#/umpires', 'Umpires', 'Accuracy, run impact and ABS challenges'],
      ['#/methodology', 'Model', 'How it works and how well it has done']
    ].map(x => '<a class="qk-card is-link ov-x" href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div></section>';

    el.innerHTML = '<div class="ov">' + html + '</div>';

    // ── draw the charts
    if (titles.length) {
      const hasM = titles.some(r => isNum(r.m));
      if (hasM) QKC.dumbbell('#ov-title', { rows: titles.map(r => ({ label: BP.teamShort(r.t), a: r.p, b: isNum(r.m) ? r.m : r.p, href: BP.teamHref(r.t, L, S) })), aName: 'Model', bName: 'Market', valName: 'World Series probability', labelWidth: 110, max: Math.min(1, Math.ceil(Math.max.apply(null, titles.map(r => Math.max(r.p, r.m || 0))) * 10 + 0.5) / 10) });
      else QKC.bar('#ov-title', { cats: titles.map(r => BP.teamShort(r.t)), series: [{ name: 'World Series', data: titles.map(r => r.p) }], horizontal: true, labels: true, fmt: v => BP.pct(v, 0), colors: titles.map(r => BP.teamInfo(r.t).colour), hrefs: titles.map(r => BP.teamHref(r.t, L, S)), labelWidth: 110, valName: 'World Series probability' });
    }
    if (inPost && BP.charts && BP.charts.mlbBracket) BP.charts.mlbBracket(document.getElementById('ov-bk'), post, { level: L, narrow: true });
    if (haveRatings) {
      const pts = Object.keys(rows).filter(t => rows[t].rating && isNum(rows[t].rating.off)).map(t => {
        const r = rows[t].rating;
        const prev = (isNum(r.def) ? r.def : 0) + (isNum(r.pitch) ? r.pitch : 0);
        return { x: r.off, y: prev, name: BP.teamName(t), label: BP.teamAbbr(t), color: BP.teamInfo(t).colour, href: BP.teamHref(t, L, S), size: 13 };
      });
      QKC.scatter('#ov-map', { points: pts, xName: 'Offence (runs/game)', yName: 'Run prevention (runs/game)', xFmt: v => BP.signed(v, 1), yFmt: v => BP.signed(v, 1), refX: 0, refY: 0, labelAll: true,
        quadrants: ['Pitching and defence', 'Complete teams', 'Rebuilding', 'Bats carry them'], label: 'Team strength map' });
    }
    if (haveLuck) {
      const lk = Object.keys(rows).filter(t => isNum(rows[t].pythag_w) && isNum(rows[t].w)).map(t => ({ t: t, v: rows[t].w - rows[t].pythag_w })).sort((a, b) => b.v - a.v);
      const pick = lk.length > 16 ? lk.slice(0, 8).concat(lk.slice(-8)) : lk;
      QKC.bar('#ov-luck', { cats: pick.map(r => BP.teamAbbr(r.t)), series: [{ name: 'Wins above Pythagorean', data: pick.map(r => Math.round(r.v * 10) / 10) }], horizontal: true, diverging: true, labels: true,
        fmt: v => BP.signed(v, 1), hrefs: pick.map(r => BP.teamHref(r.t, L, S)), labelWidth: 46, label: 'Wins above the Pythagorean record', valName: 'Wins above Pythagorean' });
    }
    if (gaps.length) QKC.dumbbell('#ov-gaps', { rows: gaps.map(g => ({ label: g.label, a: g.a, b: g.b, sub: g.sub, href: g.href })), aName: 'Model', bName: 'Market', valName: 'Win probability', labelWidth: 210 });
    if (lkeys.length) {
      const draw = k => {
        const rowsL = (lead[k] || []).slice(0, 10);
        const meta = LEADERS[k] || [BP.titleCase(k), '', '2'];
        const fmt = v => BP.fmtVal(v, meta[2]);
        QKC.bar('#ov-lead', { cats: rowsL.map(r => BP.playerName(r[0]) + (BP.player(r[0]).team ? ' · ' + BP.teamAbbr(BP.player(r[0]).team) : '')), series: [{ name: meta[0], data: rowsL.map(r => Number(r[1])) }],
          horizontal: true, labels: true, fmt: fmt, hrefs: rowsL.map(r => BP.playerHref(r[0], { level: L })), labelWidth: 150, min: LOWER[k] ? undefined : undefined,
          colors: rowsL.map(r => BP.teamInfo(BP.player(r[0]).team).colour), label: meta[0] + ' leaders', valName: meta[0] + ({ h_bat_speed_adj: ' (mph)', h_sprint_speed: ' (ft/s)', p_fb_velo: ' (mph)' }[k] || '') });
      };
      draw(lkeys[0]);
      QK.chips(document.getElementById('ov-lchips'), v => { if (v && v[0]) draw(v[0]); });
    }
    if (live.length) BP.liveRefresh([BP.ypath('markets.json', L, S)], 60000);
    BP.setMeta(post && post.sims ? BP.int(post.sims) + ' bracket simulations' : '');
  });
}

BP.route('hub', render);
})(window.BP);
