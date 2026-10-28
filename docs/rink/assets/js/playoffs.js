/* The Quant Rink — the playoffs (#/playoffs, #/playoffs/<S>).
 *
 * The bracket: West on the left, East on the right, the Stanley Cup Final in the middle; each series
 * with its seeds, the series score and our probability of each side winning it (the market's where
 * known). Before the playoffs the bracket is the projection "if the season ended today" from the
 * wild-card standings. Then every team's odds by round (make the playoffs, win a round, the conference,
 * the Cup) against the Cup market, and the seed distribution.
 *
 * Reads data/<S>/season.json: bracket {rounds: [{round, series: [SERIES]}], champion} | [SERIES]; SERIES
 * {round, conference, top|high|home: {team, seed, wins}, bottom|low|away: {...}, p_top (our probability the
 * top side wins the series), market_top, winner, games: [game_id]}; odds {team: {p_playoffs, p_r2, p_r3
 * (reach the conference final), p_final|p_conf, p_cup}}. Also data/<S>/markets.json (futures.cup) for the
 * market column. RK.seasonRows and RK.seedConf come from standings.js. */
(function (RK) {
'use strict';

const esc = RK.esc;
const isNum = RK.isNum;

function sideOf(s, keys) { for (let i = 0; i < keys.length; i++) { const v = s[keys[i]]; if (v) return typeof v === 'object' ? v : { team: v }; } return null; }
/* SEEDS: team -> seed ('C1', 'WC2') for the season on screen, from season.json bracket.seeds_now (set by bracketOf). */
let SEEDS = {};
const seedRank = sd => { const m = /^([A-Z]+)(\d)$/.exec(String(sd || '')); return m ? (m[1] === 'WC' ? 10 : 0) + Number(m[2]) : 50; };
function normSeries(s0, rnd) {
  const s = s0 || {};
  let a = sideOf(s, ['top', 'high', 'home', 'team_a', 'a']) || {}, b = sideOf(s, ['bottom', 'low', 'away', 'team_b', 'b']) || {};
  /* the build's shape for a real series: {round, series, teams: [a, b], wins: {abbr: n}, games, winner}; the higher
     seed goes on top, a side missing from wins has won none (a sweep) */
  if (Array.isArray(s.teams) && s.teams.length === 2 && !a.team) {
    const w = s.wins || {}, t = s.teams.map(RK.canonTeam);
    const side = x => ({ team: x, seed: SEEDS[x] || null, wins: isNum(w[x]) ? Number(w[x]) : 0 });
    const flip = seedRank(SEEDS[t[1]]) < seedRank(SEEDS[t[0]]);
    a = side(flip ? t[1] : t[0]); b = side(flip ? t[0] : t[1]);
  }
  const pTop = isNum(s.p_top) ? Number(s.p_top) : (isNum(s.p_a) ? Number(s.p_a) : (isNum(a.p) ? Number(a.p) : (isNum(b.p) ? 1 - Number(b.p) : null)));
  return { round: isNum(s.round) ? Number(s.round) : rnd, conf: RK.confName(s.conference || s.conf || (a.team ? RK.teamConf(a.team) : '')),
    a: { team: a.team ? RK.canonTeam(a.team) : null, seed: a.seed || null, wins: isNum(a.wins) ? Number(a.wins) : null },
    b: { team: b.team ? RK.canonTeam(b.team) : null, seed: b.seed || null, wins: isNum(b.wins) ? Number(b.wins) : null },
    p: pTop, market: isNum(s.market_top) ? Number(s.market_top) : null, winner: s.winner ? RK.canonTeam(s.winner) : null, games: s.games || [], label: s.label || '', n: isNum(s.series) ? Number(s.series) : 0 };
}
/* The bracket from the payload: {rounds: {1: [SERIES], ...}, champion, projected: false} or null. */
function bracketOf(d) {
  const b = d && d.bracket;
  if (!b) return null;
  SEEDS = {};
  const sn = b.seeds_now || {}, DV = {};
  (((d.standings || {}).rows) || []).forEach(r => { if (r && r.team && r.division) DV[RK.canonTeam(r.team)] = r.division; });
  Object.keys(sn).forEach(c => {
    const x = sn[c] || {}, lead = (x.leaders || []).map(RK.canonTeam), wc = (x.wild_card || []).map(RK.canonTeam);
    const divs = {};
    lead.forEach(t => { const dv = DV[t] || RK.teamDiv(t) || '?'; divs[dv] = (divs[dv] || 0) + 1; SEEDS[t] = dv.charAt(0) + divs[dv]; });
    wc.forEach((t, i) => { SEEDS[t] = 'WC' + (i + 1); });
  });
  const out = { rounds: {}, champion: b.champion ? RK.canonTeam(b.champion) : null, projected: !!b.projected };
  if (Array.isArray(b)) b.forEach(s => { const x = normSeries(s, 1); (out.rounds[x.round] = out.rounds[x.round] || []).push(x); });
  else if (Array.isArray(b.rounds)) b.rounds.forEach((r, i) => (r.series || r.matchups || []).forEach(s => { const x = normSeries(s, isNum(r.round) ? Number(r.round) : i + 1); (out.rounds[x.round] = out.rounds[x.round] || []).push(x); }));
  else if (Array.isArray(b.series)) b.series.forEach(s => { const x = normSeries(s, 1); (out.rounds[x.round] = out.rounds[x.round] || []).push(x); });
  else if (b.series && typeof b.series === 'object') Object.keys(b.series).forEach(k => (b.series[k] || []).forEach(s => { const r = { r1: 1, r2: 2, conf_final: 3, final: 4 }[k] || parseInt(k, 10) || 1; const x = normSeries(s, r); (out.rounds[x.round] = out.rounds[x.round] || []).push(x); }));
  Object.keys(out.rounds).forEach(r => { out.rounds[r].sort((x, y) => (x.n || 0) - (y.n || 0)); });
  return Object.keys(out.rounds).length ? out : null;
}
/* "If the season ended today": the first round from the wild-card standings, later rounds to be decided. */
function projected(rows, odds, sn) {
  const out = { rounds: { 1: [], 2: [], 3: [], 4: [] }, champion: null, projected: true };
  ['Western', 'Eastern'].forEach(conf => {
    if (!rows.some(r => r.conference === conf)) return;
    const p = RK.seedConf(rows, conf, sn);
    if (p.divs.length < 2 || p.wc.length < 2) return;
    const d1 = p.divs[0].rows[0], d2 = p.divs[1].rows[0];
    const best = RK.standingsCmp(d1, d2) <= 0 ? 0 : 1;
    const pr = (a, b) => {
      const pa = (odds[a.team] || {}).p_r2, pb = (odds[b.team] || {}).p_r2;
      return { round: 1, conf: conf, a: { team: a.team, seed: a.seed, wins: null }, b: { team: b.team, seed: b.seed, wins: null },
        p: isNum(pa) && isNum(pb) && pa + pb > 0 ? pa / (pa + pb) : null, market: null, winner: null, games: [] };
    };
    p.divs.forEach((dv, i) => {
      const r = dv.rows;
      if (r.length < 3) return;
      out.rounds[1].push(pr(r[0], i === best ? p.wc[1] : p.wc[0]));
      out.rounds[1].push(pr(r[1], r[2]));
    });
    out.rounds[2].push(null, null);
    out.rounds[3].push(null);
  });
  out.rounds[4].push(null);
  return out;
}
function teamLine(x, won, lost, p, pLabel) {
  if (!x || !x.team) return '<div class="nb-team tbd"><span class="nb-seed"></span><span class="nb-name">TBD</span><span class="nb-s"></span><span class="nb-p"></span></div>';
  return '<div class="nb-team' + (won ? ' won' : '') + (lost ? ' lost' : '') + '"><span class="nb-seed">' + esc(x.seed || '') + '</span>' +
    '<span class="nb-name">' + RK.teamLink(x.team, { abbr: true }) + '<span class="nb-full">' + esc(RK.teamShort(x.team)) + '</span></span>' +
    '<span class="nb-s">' + (isNum(x.wins) ? x.wins : '') + '</span><span class="nb-p">' + (isNum(p) ? RK.pct(p, 0) + (pLabel ? '<small>' + esc(pLabel) + '</small>' : '') : '') + '</span></div>';
}
function seriesBox(s, title) {
  if (!s) return '<div class="nb-game proj"><div class="nb-head">' + esc(title || '') + '</div>' + teamLine(null) + teamLine(null) + '</div>';
  const done = !!s.winner || (isNum(s.a.wins) && s.a.wins >= 4) || (isNum(s.b.wins) && s.b.wins >= 4);
  const win = s.winner || (isNum(s.a.wins) && s.a.wins >= 4 ? s.a.team : (isNum(s.b.wins) && s.b.wins >= 4 ? s.b.team : null));
  const started = (s.a.wins || 0) + (s.b.wins || 0) > 0;
  const status = done ? esc(RK.teamAbbr(win)) + ' wins ' + Math.max(s.a.wins || 0, s.b.wins || 0) + '–' + Math.min(s.a.wins || 0, s.b.wins || 0)
    : started ? (s.a.wins === s.b.wins ? 'Tied ' + s.a.wins + '–' + s.b.wins : esc(RK.teamAbbr(s.a.wins > s.b.wins ? s.a.team : s.b.team)) + ' leads ' + Math.max(s.a.wins, s.b.wins) + '–' + Math.min(s.a.wins, s.b.wins)) : '';
  const pa = done ? null : s.p, pb = done || !isNum(s.p) ? null : 1 - s.p;
  const last = (s.games || []).length ? s.games[s.games.length - 1] : null;
  const inner = '<div class="nb-head">' + esc(title || '') + '<span>' + status + '' + '</span></div>' +
    teamLine(s.a, win && win === s.a.team, win && win !== s.a.team, pa, '') + teamLine(s.b, win && win === s.b.team, win && win !== s.b.team, pb, '');
  return last ? '<div class="nb-game' + (done ? ' done' : '') + '" title="Latest game: ' + esc(last) + '">' + inner + '<a class="nb-last" href="' + RK.gameHref(last) + '">latest game →</a></div>'
    : '<div class="nb-game' + (done ? ' done' : '') + (s.a.team ? '' : ' proj') + '">' + inner + '</div>';
}
const RT = { 1: 'First round', 2: 'Second round', 3: 'Conference final', 4: 'Stanley Cup Final' };
function bracketHTML(b) {
  const conf = (r, c) => (b.rounds[r] || []).filter(s => s && s.conf === c);
  const pad = (list, n) => { const out = list.slice(0, n); while (out.length < n) out.push(null); return out; };
  // later rounds not yet set are padded with empty boxes
  const W = r => pad(conf(r, 'Western'), [0, 4, 2, 1][r]), E = r => pad(conf(r, 'Eastern'), [0, 4, 2, 1][r]);
  const fin = (b.rounds[4] || []).filter(Boolean)[0] || null;
  const col = (list, r, cls) => '<div class="nb-round ' + (cls || '') + '"><div class="nb-title">' + esc(RT[r]) + '</div><div class="nb-col">' + list.map(s => seriesBox(s, '')).join('') + '</div></div>';
  const grid = '<div class="nb-wrap"><div class="nb-grid">' + col(W(1), 1) + col(W(2), 2) + col(W(3), 3) +
    '<div class="nb-round nb-sb"><div class="nb-title">' + esc(RT[4]) + '</div><div class="nb-col">' + seriesBox(fin, '') +
    (b.champion ? '<div class="nb-champ">🏆 ' + RK.teamLink(b.champion) + '</div>' : '') + '</div></div>' +
    col(E(3), 3) + col(E(2), 2) + col(E(1), 1) + '</div></div>';
  const list = '<div class="nb-rounds">' + [1, 2, 3, 4].map(r => {
    const ss = (b.rounds[r] || []).filter(Boolean);
    if (!ss.length) return '';
    return '<div class="box-head">' + esc(RT[r]) + '</div><div class="nb-list">' + ss.map(s => seriesBox(s, r < 4 ? s.conf : '')).join('') + '</div>';
  }).join('') + (b.champion ? '<div class="nb-champ pad">🏆 ' + RK.teamLink(b.champion) + '</div>' : '') + '</div>';
  return '<div class="nb-wide">' + grid + '</div><div class="nb-narrow">' + list + '</div>';
}
/* season.json bracket.sim.matchups {r1: [{home_ice, other, p (how often this series happens), p_home_ice_wins}]}: the likeliest series. */
function likelyBlock(d) {
  const m = d && d.bracket && d.bracket.sim && d.bracket.sim.matchups;
  if (!m) return '';
  const RN = { r1: 'First round', r2: 'Second round', conf_final: 'Conference final', final: 'Stanley Cup Final' };
  const keys = Object.keys(m).filter(k => (m[k] || []).length);
  if (!keys.length) return '';
  return RK.card('Likeliest series', 'how often each matchup came up in the simulation, and the home-ice team\'s chance to win it', '<div class="grid-2 pad-grid">' + keys.map(k => '<div><div class="box-head">' + esc(RN[k] || RK.titleCase(k)) + '</div>' +
    RK.tableHTML([{ label: 'Series' }, { label: 'Happens', align: 'right' }, { label: 'Home ice wins', align: 'right' }], m[k].slice(0, 8).map(x => [
      { html: RK.teamLink(x.home_ice, { abbr: true }) + ' v ' + RK.teamLink(x.other, { abbr: true }), v: x.home_ice }, { html: RK.pct(x.p, 1), v: x.p }, { html: RK.pct(x.p_home_ice_wins, 0), v: x.p_home_ice_wins }]), { compact: true }) + '</div>').join('') + '</div>');
}
function oddsTable(rows, cupMkt, S) {
  const list = rows.filter(r => isNum(r.p_playoffs) || isNum(r.p_cup)).sort((a, b) => (b.p_cup || 0) - (a.p_cup || 0) || (b.p_playoffs || 0) - (a.p_playoffs || 0));
  if (!list.length) return RK.muted('No playoff simulation in this build.');
  const col = (r, k) => { const v = r[k]; return { html: isNum(v) ? (v >= 0.9995 ? '<span class="odds-done">✓</span>' : RK.pct(v, v < 0.1 ? 1 : 0)) : '—', v: v }; };
  const cols = [{ label: 'Team' }, { label: 'Seed', title: 'Today\'s seed in the wild-card standings' }, { label: 'Playoffs' }, { label: 'Round 2', align: 'right', title: 'Win the first round' },
    { label: 'Conf. final', align: 'right' }, { label: 'Final', align: 'right', title: 'Win the conference' }, { label: 'Cup', align: 'right' }]
;
  return RK.tableHTML(cols, list.map(r => {
    return { _href: RK.teamHref(r.team, S), cells: [{ html: RK.teamLink(r.team, { short: true, season: S }), v: r.team }, { html: r.seed ? esc(r.seed) : '<span class="muted-inline" title="Outside a playoff spot today">—</span>', v: r.seed || 'zz' },
      { html: RK.probCell(r.p_playoffs, RK.teamColour(r.team)), v: r.p_playoffs }, col(r, 'p_r2'), col(r, 'p_r3'), col(Object.assign({}, r, { p_final: isNum(r.p_final) ? r.p_final : r.p_conf }), 'p_final'), col(r, 'p_cup')]
 };
  }), { compact: true, cls: 'std-table' });
}

/* A finished (or running) postseason without a simulation: how far each club went, from the real series. */
function reachTable(b, S) {
  const T = {};
  [1, 2, 3, 4].forEach(r => (b.rounds[r] || []).filter(Boolean).forEach(x => [x.a, x.b].forEach((side, i) => {
    if (!side.team) return;
    const o = T[side.team] || (T[side.team] = { team: side.team, seed: side.seed, round: 0, w: 0, l: 0, out: null });
    const other = i ? x.a : x.b;
    o.round = Math.max(o.round, r); o.w += side.wins || 0; o.l += other.wins || 0;
    const win = x.winner || (side.wins >= 4 ? side.team : other.wins >= 4 ? other.team : null);
    if (win && win !== side.team) o.out = { r: r, by: other.team, sc: (other.wins || 0) + '–' + (side.wins || 0) };
  })));
  const list = Object.keys(T).map(k => T[k]).sort((x, y) => (y.round - x.round) || ((x.out ? 1 : 0) - (y.out ? 1 : 0)) || (y.w - y.l) - (x.w - x.l));
  if (!list.length) return '';
  return RK.tableHTML([{ label: 'Club' }, { label: 'Seed' }, { label: 'Went as far as' }, { label: 'Games won–lost', align: 'right' }, { label: 'Knocked out by' }],
    list.map(o => ({ _href: RK.teamHref(o.team, S), cells: [{ html: RK.teamLink(o.team, { short: true, season: S }), v: o.team }, { v: o.seed || '' },
      { html: o.out ? esc(RT[o.round]) : (b.champion === o.team ? '<b>Won the Stanley Cup</b>' : esc(RT[o.round]) + ' (still playing)'), v: o.round + (o.out ? 0 : 0.5) },
      { html: o.w + '–' + o.l, v: o.w - o.l }, { html: o.out ? RK.teamLink(o.out.by, { abbr: true, season: S }) + ' ' + esc(o.out.sc) : '—', v: o.out ? o.out.by : '' }] })), { compact: true, cls: 'std-table' });
}

RK.route('playoffs', function (el, params) {
  const S = params.season;
  const cur = S === RK.currentSeason();
  return Promise.all([RK.loadYear('season.json', S), Promise.resolve(null)]).then(res => {
    if (!el.isConnected) return;
    const d = res[0], mk = res[1];
    const nav = (S > RK.FIRST_SEASON ? '<a href="' + RK.playoffsHref(S - 10001) + '">← ' + esc(RK.seasonLabel(S - 10001)) + '</a>' : '') +
      (S < RK.currentSeason() ? '<a href="' + RK.playoffsHref(S + 10001) + '">' + esc(RK.seasonLabel(S + 10001)) + ' →</a>' : '') + '<a href="' + RK.standingsHref(S) + '">Standings</a>';
    if (!RK.ok(d)) { el.innerHTML = RK.pageHead(RK.seasonLabel(S) + ' playoffs', '', nav) + RK.notBuilt('The ' + RK.seasonLabel(S) + ' playoff picture', d); return; }
    const rows = RK.seasonRows ? RK.seasonRows(d) : [];
    const sn = d.bracket && d.bracket.seeds_now ? d.bracket.seeds_now : null;
    ['Western', 'Eastern'].forEach(c => { if (RK.seedConf && rows.some(r => r.conference === c)) RK.seedConf(rows, c, sn); });
    const odds = {};
    rows.forEach(r => { odds[r.team] = r; });
    let b = bracketOf(d);
    const isProj = !b || b.projected;
    if (!b && rows.length && RK.seedConf) b = projected(rows, odds, sn);
    const cupF = mk && RK.ok(mk) && mk.futures ? (mk.futures.cup || mk.futures.stanley_cup) : null;
    let cupMkt = {};
    if (Array.isArray(cupF)) cupF.forEach(x => { if (x && x.team && isNum(x.market)) cupMkt[RK.canonTeam(x.team)] = Number(x.market); });
    else if (cupF) cupMkt = cupF.market && (cupF.market.probs || cupF.market.prices || cupF.market.mid) ? RK.titleProbs(cupF.market) : (cupF.market || {});
    const champ = b && b.champion ? b.champion : null;
    el.innerHTML = RK.pageHead(RK.seasonLabel(S) + ' Stanley Cup playoffs', champ ? 'Champion: ' + RK.teamLink(champ) : (isProj ? 'Projected bracket: if the season ended today' : 'best of seven · the higher seed has home ice'), nav) +
      RK.card('Bracket', isProj ? 'the first round from today\'s wild-card standings · percentages: our chance to win the series' : 'series score and our chance to win the series',
        b ? bracketHTML(b) : RK.muted('No bracket for this season yet.')) +
      (isProj ? likelyBlock(d) : '') +
      (!isProj && !rows.some(r => isNum(r.p_playoffs) || isNum(r.p_cup)) ? RK.card('How far each club went', 'the sixteen clubs, by the round they reached · series results', reachTable(b, S))
        : RK.card('Chances by round', 'our chances from the season simulation', oddsTable(rows, cupMkt, S))) +
      '<div class="chart-note">In each conference the division winner with more points plays the second wild card; the other plays the first. Series chances come from our game model with home ice. For information only.</div>';
    RK.sortable(el);
  });
});

/* shared with the season recap (rk-recap.js) and the series pages */
RK.bracket = { of: bracketOf, html: bracketHTML, reach: reachTable, RT: RT };

})(window.RK);
