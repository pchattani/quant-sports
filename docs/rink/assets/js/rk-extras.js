/* The Quant Rink — round 9 additions (28 Oct 2026), from data the site already has (no new fetches):
 *   RK.goalieStrip(host, games)    Games: tonight's starting goalies, confirmed or projected (the schedule's goalies, ESPN's
 *                                  probable starters), each with this season's goals saved above expected (goalies.json).
 *   RK.scheduleStrength(host, S)   Standings › Chances: who has the easier road, from the schedule's remaining games, the
 *                                  opponents' ratings (season.json) and our chance in each (schedule.json model.p_home).
 *   RK.recordsInReach(host, S)     Standings › Races: the leaders' full-season pace against the NHL single-season records.
 *   RK.injuryBoard(host, S)        Teams: who is missing and what it costs, in wins above replacement this season, from the
 *                                  ESPN injury status and return date in valuation.json and each player's value rate.
 *   #/series/<S>/<round>/<n>       a playoff series page: the result, our pre-series call, every game with its score and our
 *                                  pre-game chance, and our series chance game by game.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);
const surname = n => RK.surnameOf(n || '');

/* ── tonight's starting goalies ─────────────────────────────────────────── */
RK.goalieStrip = function (host, games) {
  if (!host) return;
  const list = (games || []).filter(g => g && g.goalies && (g.goalies.home || g.goalies.away) && U.status(g) !== 'final');
  if (!list.length) { host.innerHTML = ''; return; }
  RK.loadYear('goalies.json', RK.currentSeason()).then(gk => {
    if (!U.alive(host)) return;
    const P = (RK.ok(gk) && gk.players) || {};
    const line = (q, team) => {
      if (!q) return '<div class="rk-gs-g none"><span class="nm">Not listed yet</span><span class="st">' + esc(RK.teamAbbr(team)) + '</span></div>';
      const pid = String(q.pid || q.id || ''), p = P[pid] || {}, v = p.values || {};
      const conf = /^(confirmed|starter|start|ok)$/i.test(q.status || '');
      return '<div class="rk-gs-g">' + QK.teamMark(U.team(team), 'sm') + '<span class="nm">' + (pid ? '<a href="' + esc(RK.playerHref(pid)) + '">' + esc(q.name || RK.playerName(pid)) + '</a>' : esc(q.name || '')) + '</span>' +
        '<span class="st ' + (conf ? 'on' : '') + '" title="' + esc((conf ? 'Confirmed' : 'Projected') + (q.at ? ' · listed ' + RK.fmtStamp(q.at) : '') + (q.src ? ' · ' + q.src : '')) + '">' + (conf ? 'Confirmed' : 'Projected') + '</span>' +
        '<span class="v num" data-tip="Goals saved above expected this season">' + (isNum(v.gsax) ? U.signed(v.gsax, 1) + ' GSAx' : '—') + '</span><span class="s num">' + (isNum(v.sv_pct) ? RK.fmtVal(v.sv_pct, 'svpct') + ' · ' + (v.gp || 0) + ' GP' : '') + '</span></div>';
    };
    host.innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'In the crease', title: list.every(g => RK.localDay(g.start || g.date) === RK.todayISO()) ? 'Tonight’s starting goalies' : 'The starting goalies', sub: 'Confirmed or projected starters (ESPN’s probable starters, read every 15 minutes near game time), with each goalie’s goals saved above expected this season. Our game chances use the listed starter.' }) +
      '<div class="rk-gs">' + list.map(g => '<div class="rk-gs-c"><div class="rk-gs-h"><a href="' + esc(RK.gameHref(g.game_id)) + '" aria-label="' + esc(RK.teamName(g.away) + ' at ' + RK.teamName(g.home) + ': the game centre') + '"><b>' + esc(RK.teamAbbr(g.away)) + ' @ ' + esc(RK.teamAbbr(g.home)) + '</b></a><span>' + esc(QK.fmt.time(g.start) || '') + '</span></div>' +
        line(g.goalies.away, g.away) + line(g.goalies.home, g.home) + '</div>').join('') + '</div></section>';
    if (QK.tooltips) QK.tooltips();
  });
};

/* ── remaining schedule strength ────────────────────────────────────────── */
RK.scheduleStrength = function (host, S) {
  if (!host) return;
  host.innerHTML = QK.skeleton('lines', 4);
  Promise.all([RK.loadYear('schedule.json', S), RK.loadYear('season.json', S)]).then(res => {
    if (!U.alive(host)) return;
    const games = RK.ok(res[0]) ? (res[0].games || []) : [], R = RK.ok(res[1]) ? (res[1].ratings || {}) : {};
    const rating = t => { const u = (R[t] || {}).units || {}; return isNum(u.rating) ? u.rating : null; };
    const left = games.filter(g => g && !RK.isPlayoffGame(g) && RK.gameState(g) !== 'final' && g.home && g.away);
    if (!left.length) { host.innerHTML = ''; return; }
    const T = {};
    left.forEach(g => {
      [['home', 'away'], ['away', 'home']].forEach(x => {
        const t = RK.canonTeam(g[x[0]]), o = RK.canonTeam(g[x[1]]);
        const r = T[t] || (T[t] = { team: t, n: 0, home: 0, opp: [], p: [], days: [] });
        r.n++; if (x[0] === 'home') r.home++;
        if (isNum(rating(o))) r.opp.push(rating(o));
        const ph = g.model && isNum(g.model.p_home) ? g.model.p_home : null;
        if (isNum(ph)) r.p.push(x[0] === 'home' ? ph : 1 - ph);
        r.days.push(String(g.date || '').slice(0, 10));
      });
    });
    const mean = a => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null);
    const rows = Object.keys(T).map(t => { const r = T[t]; const ds = r.days.filter(Boolean).sort(); let b2b = 0; for (let i = 1; i < ds.length; i++) if (RK.addDays(ds[i - 1], 1) === ds[i]) b2b++;
      return { team: t, n: r.n, home: r.home, opp: mean(r.opp), p: mean(r.p), b2b: b2b }; }).filter(r => isNum(r.opp)).sort((a, b) => b.opp - a.opp);
    host.innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'The road ahead', title: 'Who has the harder schedule left?', sub: 'The average rating of each club’s remaining opponents (goals a game against an average club), with home games, back-to-backs and our average chance in those games. Hardest at the top.' }) +
      '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Strength of the remaining schedule', 'Average opponent rating, goals a game', U.chart('ch-sos', Math.max(420, 22 * rows.length + 60), 'Remaining schedule strength')) + '</div>' +
      '<div class="qk-span-6">' + U.card2('Every club', rows[0] ? rows[0].n + ' to ' + rows[rows.length - 1].n + ' games left' : '', '<div id="ch-sos-t"></div>', { flush: true }) + '</div></div>' +
      QK.explain('<b>What’s that number?</b> +0.10 means the opponents left are, on average, a tenth of a goal a game better than an average club. Our chance already includes it: a hard road shows up as a lower average chance. Back-to-backs count the second night of two in a row.', { html: true }) + '</section>';
    QKC.bar('#ch-sos', { cats: rows.map(r => RK.teamName(r.team)), series: [{ name: 'Opponent rating', data: rows.map(r => r.opp) }], horizontal: true, diverging: true, labels: true, fmt: x => U.signed(x, 2), hrefs: rows.map(r => RK.teamHref(r.team, S)), labelWidth: 150, valName: 'Average opponent rating (goals a game)' });
    QK.leaderboard(host.querySelector('#ch-sos-t'), { dense: true, rank: true, maxHeight: Math.max(420, 22 * rows.length + 60), sort: { key: 'opp', dir: 'desc' }, rowHref: r => RK.teamHref(r.team, S), columns: [
      { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team, S) }, { key: 'n', label: 'Left', num: true }, { key: 'home', label: 'Home', num: true },
      { key: 'b2b', label: 'Back-to-backs', num: true }, { key: 'opp', label: 'Opponents', num: true, fmt: x => U.signed(x, 2), tip: 'Average rating of the opponents left' },
      { key: 'p', label: 'Our avg chance', num: true, fmt: x => U.pct(x, 0), tip: 'Our average win chance in the games left' }], rows: rows.map(r => Object.assign({ name: RK.teamShort(r.team) }, r)) });
  });
};

/* ── season records in reach ────────────────────────────────────────────── */
/* The NHL single-season records (the league's record book), by what they measure. */
const RECORDS = [
  ['p', 'Points', 215, 'Wayne Gretzky, 1985–86', 'S'], ['g', 'Goals', 92, 'Wayne Gretzky, 1981–82', 'S'], ['a', 'Assists', 163, 'Wayne Gretzky, 1985–86', 'S'],
  ['p', 'Points by a defenceman', 139, 'Bobby Orr, 1970–71', 'D'], ['g', 'Goals by a defenceman', 48, 'Paul Coffey, 1985–86', 'D'],
  ['w', 'Wins by a goalie', 48, 'Martin Brodeur (2006–07) and Braden Holtby (2015–16)', 'G'],
  ['pts', 'Points by a club', 135, 'Boston Bruins, 2022–23', 'T'], ['tw', 'Wins by a club', 65, 'Boston Bruins, 2022–23', 'T']];
RK.recordsInReach = function (host, S) {
  if (!host) return;
  if (Number(S) !== Number(RK.currentSeason())) { host.innerHTML = ''; return; }
  Promise.all([RK.loadYear('lab.json', S), RK.loadYear('season.json', S)]).then(res => {
    if (!U.alive(host)) return;
    const lab = RK.ok(res[0]) ? res[0] : {}, sj = RK.ok(res[1]) ? res[1] : {};
    const rows = RK.seasonRows(sj), by = {}; rows.forEach(r => { by[r.team] = r; });
    const full = RK.regGames(S);
    const col = (X, i, k) => (X && X.data && X.data[k] ? X.data[k][i] : null);
    const lead = (X, key, test) => {
      if (!X || !Array.isArray(X.ids)) return null;
      let best = null;
      X.ids.forEach((id, i) => { const v = col(X, i, key), pos = (X.pos || [])[i]; if (!isNum(v) || (test && !test(pos))) return; if (!best || v > best.v) best = { id: String(id), name: (X.name || [])[i], team: (X.team || [])[i], v: v }; });
      return best;
    };
    const cards = RECORDS.map(rc => {
      let who, v, gp, name, team, href;
      if (rc[4] === 'T') {
        const r = rows.slice().sort((a, b) => (rc[0] === 'pts' ? (b.pts || 0) - (a.pts || 0) : (b.w || 0) - (a.w || 0)))[0];
        if (!r) return null;
        v = rc[0] === 'pts' ? r.pts : r.w; gp = r.gp; name = RK.teamName(r.team); team = r.team; href = RK.teamHref(r.team, S);
      } else {
        who = rc[4] === 'G' ? lead(lab.goalies, 'w') : lead(lab.skaters, rc[0], rc[4] === 'D' ? (pos => String(pos).toUpperCase() === 'D') : null);
        if (!who) return null;
        v = who.v; team = who.team; gp = (by[RK.canonTeam(team)] || {}).gp; name = who.name; href = RK.playerHref(who.id);
      }
      if (!isNum(v) || !isNum(gp) || gp < 1) return null;
      const pace = v / gp * full, rec = rc[2];
      return { kicker: rc[1], name: name, sub: RK.teamAbbr(team) + ' · ' + v + ' through ' + gp + ' club game' + (gp === 1 ? '' : 's'), colour: RK.teamColourRaw(team), mark: U.team(team), href: href,
        value: Math.round(pace), unit: 'over ' + full + ' games, on this pace', pace: { now: v, pace: pace, target: rec, label: 'Record' },
        text: 'The record is ' + rec + ', ' + rc[3] + '. ' + (gp < 20 ? gp + ' games in, a pace this hot usually cools: ' + (pace >= rec ? 'on pace to break it for now.' : 'short of it even at this pace.') : pace >= rec ? 'On pace to break it.' : 'Would need ' + Math.max(0, Math.ceil(rec - v)) + ' more in ' + (full - gp) + ' games: ' + U.f((rec - v) / Math.max(1, full - gp), 2) + ' a game.') };
    }).filter(Boolean);
    host.innerHTML = cards.length ? '<section class="qk-section">' + QK.sectionHead({ kicker: 'Records in reach', title: 'On pace for history?', sub: 'This season’s leaders at their club’s games played, paced over a full ' + full + '-game season, against the NHL single-season records. Early in a season every pace is hot.' }) + QK.storyCards(cards) + '</section>' : '';
  });
};

/* ── the injury board ───────────────────────────────────────────────────── */
RK.injuryBoard = function (host, S) {
  if (!host) return;
  if (Number(S) !== Number(RK.currentSeason())) { host.innerHTML = ''; return; }
  RK.loadYear('valuation.json', S).then(v => {
    if (!U.alive(host)) return;
    if (!RK.ok(v)) { host.innerHTML = ''; return; }
    const gpw = (v.currency || {}).goals_per_win || 6;
    const rows = U.rowsOf(v).filter(r => Array.isArray(r.inj) && r.inj[0]).map(r => {
      const gm = isNum(r.inj[2]) ? r.inj[2] : 0, rate = isNum(r.rate) ? Math.max(0, r.rate) : 0;
      return Object.assign({}, r, { status: r.inj[0], ret: r.inj[1] || '', gm: gm, lost: rate * (r.mpg || 0) / 60 * gm / gpw });
    });
    if (!rows.length) { host.innerHTML = ''; return; }
    const T = {};
    rows.forEach(r => { const t = RK.canonTeam(r.team); const o = T[t] || (T[t] = { team: t, lost: 0, n: 0, top: null }); o.lost += r.lost; o.n++; if (!o.top || r.lost > o.top.lost) o.top = r; });
    const tl = Object.keys(T).map(t => T[t]).sort((a, b) => b.lost - a.lost);
    const big = rows.slice().sort((a, b) => b.lost - a.lost).slice(0, 25);
    const fetched = ((v.injuries || {}).fetched_at) || '';
    host.innerHTML = QK.sectionHead({ kicker: 'Who’s missing', title: 'What the injuries cost', sub: 'Each club’s players on the injury report, valued: the wins above replacement they are expected to miss this season (their value rate × ice time × the games they miss, from the ESPN status and return date). A replacement fills in, so this is what the club loses on the ice.' }) +
      '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Wins lost to injury, by club', 'This season, expected', U.chart('tm-inj-c', Math.max(360, 22 * tl.length + 60), 'Wins lost to injury by club')) + '</div>' +
      '<div class="qk-span-6">' + U.card2('The biggest absences', 'Players out, by the value they take with them', '<div id="tm-inj-t"></div>', { flush: true }) + '</div></div>' +
      QK.explain('<b>How sure are we?</b> A return date is ESPN’s estimate and often moves. Long-term injured reserve counts the whole season left. ' + (fetched ? 'Injury report as of ' + esc(RK.fmtStamp(fetched)) + '.' : ''), { html: true });
    QKC.bar('#tm-inj-c', { cats: tl.map(x => RK.teamName(x.team)), series: [{ name: 'Wins lost', data: tl.map(x => x.lost) }], horizontal: true, labels: true, fmt: x => U.f(x, 2), colors: tl.map(x => RK.teamColourRaw(x.team)), hrefs: tl.map(x => RK.teamHref(x.team, S)), labelWidth: 150, valName: 'Wins above replacement lost this season' });
    QK.leaderboard(host.querySelector('#tm-inj-t'), { dense: true, rank: true, maxHeight: Math.max(360, 22 * tl.length + 60), sort: { key: 'lost', dir: 'desc' }, rowHref: r => RK.playerHref(r.id), columns: [
      { key: 'name', label: 'Player', type: 'entity', mark: r => U.team(r.team), href: r => RK.playerHref(r.id), sub: 'sub' },
      { key: 'status', label: 'Status', sort: false, fmt: x => '<span class="rk-inj">' + esc(x) + '</span>' },
      { key: 'gm', label: 'Games out', num: true }, { key: 'lost', label: 'Wins lost', num: true, fmt: x => '<b>' + U.f(x, 2) + '</b>' }],
      rows: big.map(r => Object.assign({}, r, { sub: [r.pos, r.ret ? 'back ' + RK.fmtDate(r.ret, { weekday: false }) : ''].filter(Boolean).join(' · ') })) });
  });
};

/* ── playoff series pages ───────────────────────────────────────────────── */
RK.seriesHref = (S, r, n) => '#/series/' + S + '/' + r + '/' + n;
function seriesPage(el, params) {
  const S = RK.toSeason(params.S) || RK.currentSeason(), rd = Number(params.round), sn = Number(params.num);
  const tabs = [['table', 'Table'], ['chances', 'Chances'], ['bracket', 'Bracket'], ['history', 'History'], ['races', 'Races']].map((t, i) => ({ key: t[0], label: t[1], href: RK.standingsHref(S) + (i ? '?tab=' + t[0] : '') }));
  const body = U.section(el, { section: 'standings', title: 'Standings', sub: 'A playoff series, game by game.', tabs: tabs, active: 'bracket' });
  body.innerHTML = QK.skeleton('lines', 6);
  return Promise.all([RK.loadYear('season.json', S), RK.loadYear('schedule.json', S)]).then(res => {
    if (!U.alive(body)) return;
    const d = RK.ok(res[0]) ? res[0] : null, games = RK.ok(res[1]) ? (res[1].games || []) : [];
    const b = d && RK.bracket ? RK.bracket.of(d) : null;
    const x = b ? (b.rounds[rd] || []).filter(s => s && s.n === sn)[0] : null;
    if (!x || !x.a.team) { body.innerHTML = QK.empty('No such series', 'This series is not in the ' + RK.seasonLabel(S) + ' bracket.') + '<p class="qk-sub"><a class="qk-link" href="' + esc(RK.standingsHref(S)) + '?tab=bracket">The bracket →</a></p>'; return; }
    const RT = RK.bracket.RT;
    const call = (RK.seriesCalls ? RK.seriesCalls(b, games).list : []).filter(c => c.s === x)[0] || null;
    const by = {}; games.forEach(g => { if (g && g.game_id) by[String(g.game_id)] = g; });
    const gs = (x.games || []).map(id => by[String(id)]).filter(Boolean);
    const win = x.winner || (x.a.wins >= 4 ? x.a.team : x.b.wins >= 4 ? x.b.team : null);
    const A = x.a, B = x.b, hi = Math.max(A.wins || 0, B.wins || 0), lo = Math.min(A.wins || 0, B.wins || 0);
    const title = win ? RK.teamShort(win) + ' won ' + hi + '–' + lo : (A.wins === B.wins ? 'Level at ' + (A.wins || 0) + '–' + (B.wins || 0) : RK.teamShort((A.wins || 0) > (B.wins || 0) ? A.team : B.team) + ' lead ' + hi + '–' + lo);
    /* our series chance through the series: before game 1, then after each game, from the pre-series game chances */
    let path = [];
    if (call) {
      const H = call.home, pH = (by[String((x.games || [])[0])] || {}).model ? by[String(x.games[0])].model.p_home : null;
      if (isNum(pH)) {
        const pR = Math.max(0.02, Math.min(0.98, pH - 2 * (RK.seriesCalls(b, games).edge || 0.03)));
        const HOME = [1, 1, 0, 0, 1, 0, 1];
        const pFrom = (w, l, g) => { if (w >= 4) return 1; if (l >= 4) return 0; const p = HOME[g] ? pH : pR; return p * pFrom(w + 1, l, g + 1) + (1 - p) * pFrom(w, l + 1, g + 1); };
        let w = 0, l = 0;
        path.push({ label: 'Before game 1', p: pFrom(0, 0, 0) });
        gs.forEach((g, i) => { if (!RK.isFinal(g) || !isNum(g.hs) || !isNum(g.as)) return; const hw = RK.canonTeam(g.home) === H ? g.hs > g.as : g.as > g.hs; if (hw) w++; else l++; path.push({ label: 'After game ' + (i + 1), p: pFrom(w, l, i + 1) }); });
        path = path.map(o => Object.assign(o, { team: H }));
      }
    }
    const fav = call ? call.fav : null;
    body.innerHTML = QK.sectionHead({ kicker: RK.seasonLabel(S) + ' playoffs · ' + (RT[rd] || 'Round ' + rd) + (rd < 4 && x.conf ? ' · ' + x.conf : ''), title: title, size: 'lg', sub: RK.teamName(A.team) + (A.seed ? ' (' + A.seed + ')' : '') + ' against ' + RK.teamName(B.team) + (B.seed ? ' (' + B.seed + ')' : '') + '. Best of seven; the higher seed has home ice in games 1, 2, 5 and 7.' }) +
      QK.tape({ left: { name: RK.teamName(A.team), short: RK.teamAbbr(A.team), sub: (A.seed || '') + ' · ' + (A.wins || 0) + ' wins', colour: RK.teamColourRaw(A.team), alt: RK.teamAlt(A.team), href: RK.teamHref(A.team, S) },
        right: { name: RK.teamName(B.team), short: RK.teamAbbr(B.team), sub: (B.seed || '') + ' · ' + (B.wins || 0) + ' wins', colour: RK.teamColourRaw(B.team), alt: RK.teamAlt(B.team), href: RK.teamHref(B.team, S) },
        groups: [{ label: 'The series', rows: [{ label: 'Games won', a: A.wins || 0, b: B.wins || 0, ta: String(A.wins || 0), tb: String(B.wins || 0) },
          { label: 'Goals', a: gs.reduce((s, g) => s + ((RK.canonTeam(g.home) === A.team ? g.hs : g.as) || 0), 0), b: gs.reduce((s, g) => s + ((RK.canonTeam(g.home) === B.team ? g.hs : g.as) || 0), 0) },
          { label: 'Expected goals', a: gs.reduce((s, g) => s + ((g.xg || {})[RK.canonTeam(g.home) === A.team ? 'home' : 'away'] || 0), 0), b: gs.reduce((s, g) => s + ((g.xg || {})[RK.canonTeam(g.home) === B.team ? 'home' : 'away'] || 0), 0), fmt: v => U.f(v, 1) }] }], wins: false }) +
      QK.stats([call ? { label: 'Our pre-series call', value: RK.teamAbbr(fav) + ' ' + U.pct(call.p, 0), signal: true, sub: 'from our game-1 forecast, home ice included' + (call.hit === true ? ' · called it' : call.hit === false ? ' · an upset' : '') } : null,
        { label: 'Games', value: String(gs.length), sub: gs.filter(g => g.ot || g.so || (isNum(g.period) && g.period > 3)).length + ' to overtime' },
        win ? { label: 'Winner', value: RK.teamAbbr(win), href: RK.teamHref(win, S), sub: rd < 4 ? 'through to the ' + (RT[rd + 1] || 'next round').toLowerCase() : 'Stanley Cup champions' } : null].filter(Boolean)) +
      '<div class="qk-grid" style="margin-top:var(--sp-5)"><div class="qk-span-7">' + U.card2('Game by game', 'The score, the expected goals and our pre-game chance', '<div id="sr-t"></div>', { flush: true }) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Our series chance as it went', path.length ? 'For ' + RK.teamName(path[0].team) + ', from the pre-series game chances' : '', path.length > 1 ? U.chart('sr-c', 300, 'Our series chance after each game') : QK.empty('Not enough to chart')) + '</div></div>' +
      QK.explain('<b>How sure are we?</b> Playoff series are close: a 60% favourite still goes out 4 times in 10. The series chance after each game keeps the pre-series game chances and updates only the score, so it shows what each win was worth.', { html: true }) +
      '<p class="qk-sub" style="margin-top:12px"><a class="qk-link" href="' + esc(RK.standingsHref(S)) + '?tab=bracket">The whole bracket →</a></p>';
    QK.table(body.querySelector('#sr-t'), { dense: true, rowHref: r => RK.gameHref(r.id), columns: [
      { key: 'n', label: 'Game', num: true }, { key: 'date', label: 'Date', fmt: v => esc(RK.fmtDate(v, { year: false })) },
      { key: 'where', label: 'Home', sort: false, fmt: (v, r) => U.teamEnt(r.home, { abbr: true, season: S }) },
      { key: 'score', label: 'Result', sort: false, fmt: (v, r) => '<a class="qk-link" href="' + esc(RK.gameHref(r.id)) + '">' + esc(v) + '</a>' },
      { key: 'xg', label: 'xG', sort: false }, { key: 'p', label: 'Our chance', sort: false, tip: 'Our pre-game chance for the side we favoured' }],
      rows: gs.map((g, i) => { const fin = RK.isFinal(g), w = fin ? (g.hs > g.as ? g.home : g.away) : null, ph = g.model && isNum(g.model.p_home) ? g.model.p_home : null;
        return { id: g.game_id, n: i + 1, date: g.date, home: g.home, score: fin ? RK.teamAbbr(w) + ' ' + Math.max(g.hs, g.as) + '–' + Math.min(g.hs, g.as) + (g.so ? ' (SO)' : (g.ot || (isNum(g.period) && g.period > 3)) ? ' (OT)' : '') : RK.fmtDate(g.start || g.date, { year: false, weekday: true }),
          xg: g.xg && isNum(g.xg.home) ? RK.teamAbbr(g.away) + ' ' + U.f(g.xg.away, 1) + ' · ' + RK.teamAbbr(g.home) + ' ' + U.f(g.xg.home, 1) : '—', p: isNum(ph) ? RK.teamAbbr(ph >= 0.5 ? g.home : g.away) + ' ' + U.pct(Math.max(ph, 1 - ph), 0) : '—' }; }) });
    if (path.length > 1) QKC.line('#sr-c', { x: path.map(o => o.label.replace('After game ', 'G').replace('Before game 1', 'Start')), series: [{ name: RK.teamAbbr(path[0].team), data: path.map(o => Math.round(o.p * 1000) / 10), color: RK.teamColourRaw(path[0].team) }],
      yMin: 0, yMax: 100, yFmt: v => v + '%', yName: 'Series chance (%)', xName: 'Game', ref: { y: 50, label: 'Even' }, endLabels: false, label: 'Our series chance after each game' });
    RK.setMeta(RK.seasonLabel(S) + ' · ' + (RT[rd] || ''));
  });
}
RK.page('series', seriesPage);
})(window.RK);
