/* The Quant Gridiron — Chances (#/playoffs[/<S>]) and the Bracket (#/bracket[/<S>]), in the Standings section (round 9:
 * the old playoff picture split in two, with Season forecasts, the win totals and the draft order folded into Chances).
 * The bracket (projected from today's seeds before the playoffs; 14 teams from 2020), each game with our win chance;
 * Super Bowl chances (ours only: kit v3 keeps the market to game detail and the Model page); the likeliest Super Bowl
 * matchups; each conference's seed distribution; our round-by-round chances. Reads <S>/season.json. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
const ROUND_NAME = { WC: 'Wild Card', DIV: 'Divisional', CON: 'Conference', SB: 'Super Bowl' };

function roundKey(r) {
  const s = String(r || '').toUpperCase();
  if (/^WC|WILD/.test(s)) return 'WC';
  if (/^DIV/.test(s)) return 'DIV';
  if (/^CON|^CONF|CHAMP/.test(s)) return 'CON';
  if (/^SB|SUPER/.test(s)) return 'SB';
  return s;
}
function confOf(g) { return g.conf || g.conference || GI.teamInfo(g.home).conference || GI.teamInfo(g.away).conference || ''; }
function winnerOf(g) {
  if (!g) return null;
  if (g.winner) return GI.canonTeam(g.winner);
  if (GI.isFinal(g) && isNum(g.hs) && isNum(g.as) && g.hs !== g.as) return g.hs > g.as ? g.home : g.away;
  return null;
}
function bracketModel(d, rows) {
  const br = d.bracket || d.playoffs || {};
  const seeds = {};
  const brGames = (br.games || []).concat([].concat.apply([], (br.rounds || []).map(r => (r.games || []).map(g => Object.assign({ round: r.key }, g)))));
  const seedSrc = br.seeds || br.seeds_today || d.seeds_today || {};
  const projected = !brGames.some(g => !g.projected && (g.game_id || GI.isFinal(g) || GI.isLive(g)));
  GI.CONFERENCES.forEach(conf => {
    let s = seedSrc[conf];
    if (s && !Array.isArray(s)) s = s.seeds || [];
    if (!s || !s.length) s = rows.filter(r => r.conference === conf && (isNum(r.seed) || isNum(r.p_playoffs))).sort((a, b) => (isNum(a.seed) && isNum(b.seed) ? a.seed - b.seed : (b.p_playoffs || 0) - (a.p_playoffs || 0))).slice(0, 7).map(r => r.team);
    seeds[conf] = s.map(GI.canonTeam);
  });
  const games = brGames.map(g => Object.assign({}, g, { round: roundKey(g.round || g.gtype), home: GI.canonTeam(g.home), away: GI.canonTeam(g.away) }));
  const seedOf = (conf, t) => { const i = seeds[conf].indexOf(t); return i >= 0 ? i + 1 : null; };
  const find = (round, conf, a, b) => games.find(g => g.round === round && (!conf || confOf(g) === conf) && ((a && (g.home === a || g.away === a)) || (b && (g.home === b || g.away === b)))) || null;
  const out = { seeds: seeds, projected: projected, SB: null, p: br.p || {} };
  GI.CONFERENCES.forEach(conf => {
    const S = seeds[conf];
    const wc = [[2, 7], [3, 6], [4, 5]].map(pr => find('WC', conf, S[pr[0] - 1], S[pr[1] - 1]) || { round: 'WC', conf: conf, home: S[pr[0] - 1] || null, away: S[pr[1] - 1] || null, projected: true });
    const alive = [S[0]].concat(wc.map(winnerOf));
    const known = alive.every(Boolean);
    let div = games.filter(g => g.round === 'DIV' && confOf(g) === conf);
    if (div.length < 2) {
      const left = known ? alive.slice().sort((x, y) => seedOf(conf, x) - seedOf(conf, y)) : null;
      const gA = div.find(g => g.home === S[0] || g.away === S[0]) || { round: 'DIV', conf: conf, home: S[0] || null, away: left ? left[3] : null, projected: true };
      const gB = div.find(g => g !== gA) || { round: 'DIV', conf: conf, home: left ? left[1] : null, away: left ? left[2] : null, projected: true };
      div = [gA, gB];
    }
    const con = games.find(g => g.round === 'CON' && confOf(g) === conf) || { round: 'CON', conf: conf, home: null, away: null, projected: true };
    out[conf] = { seeds: S, WC: wc, DIV: div, CON: con };
  });
  out.SB = games.find(g => g.round === 'SB') || { round: 'SB', home: winnerOf(out.AFC.CON), away: winnerOf(out.NFC.CON), projected: true };
  return out;
}
function gameBox(g, m, cls) {
  if (!g) return '';
  const fin = GI.isFinal(g), live = GI.isLive(g), w = winnerOf(g);
  const seedOf = t => { for (let k = 0; k < GI.CONFERENCES.length; k++) { const i = (m.seeds[GI.CONFERENCES[k]] || []).indexOf(t); if (i >= 0) return i + 1; } return ''; };
  const pH = live && isNum(g.wp_home) ? g.wp_home : (isNum(g.p_home) ? Number(g.p_home) : (g.model && isNum(g.model.p_home) ? g.model.p_home : null));
  const row = (t, side) => {
    if (!t) return '<div class="gi-br-t lost"><span class="s"></span><span class="n">TBD</span><span class="p"></span></div>';
    const p = pH === null ? null : (side === 'home' ? pH : 1 - pH);
    const sc = side === 'home' ? g.hs : g.as;
    return '<div class="gi-br-t' + (w && w !== t ? ' lost' : '') + '"><span class="s">' + esc(seedOf(t)) + '</span>' + GI.mark(t, 'sm') + '<span class="n">' + esc(GI.teamAbbr(t)) + '</span><span class="p">' + (fin || live ? esc(isNum(sc) ? sc : '') : (p !== null ? GI.pct(p, 0) : '')) + '</span></div>';
  };
  const tag = g.game_id ? 'a href="' + GI.gameHref(g.game_id) + '"' : 'div';
  /* a played game: our pre-game call for the winner under the score (blue when we had the winner favoured) */
  const pc = fin && w && pH !== null ? (w === g.home ? pH : 1 - pH) : null;
  const call = isNum(pc) ? '<span class="gi-br-call' + (pc >= 0.5 ? ' hit' : '') + '" title="Our pre-game chance for the winner">Our call: ' + esc(GI.teamAbbr(w)) + ' ' + GI.pct(pc, 0) + '</span>' : '';
  return '<' + tag + ' class="gi-br-g' + (cls ? ' ' + cls : '') + '">' + row(g.away, 'away') + row(g.home, 'home') + call + '</' + (g.game_id ? 'a' : 'div') + '>';
}
function bracketHTML(m) {
  if (!m.AFC.seeds.length && !m.NFC.seeds.length) return GI.muted('The bracket is not set yet.');
  const bye = conf => m[conf].seeds[0] ? '<div class="gi-br-g"><div class="gi-br-t"><span class="s">1</span>' + GI.mark(m[conf].seeds[0], 'sm') + '<span class="n">' + esc(GI.teamAbbr(m[conf].seeds[0])) + '</span><span class="p">bye</span></div></div>' : '';
  const col = (conf, k) => '<div class="gi-br-col"><h4>' + conf + ' ' + ROUND_NAME[k] + '</h4>' + (k === 'WC' ? bye(conf) + m[conf].WC.map(g => gameBox(g, m)).join('') : k === 'DIV' ? m[conf].DIV.map(g => gameBox(g, m)).join('') : gameBox(m[conf].CON, m)) + '</div>';
  return '<div class="gi-br-wrap"><div class="gi-bracket">' + ['WC', 'DIV', 'CON'].map(k => col('AFC', k)).join('') + '<div class="gi-br-col"><h4>Super Bowl</h4>' + gameBox(m.SB, m, 'gi-br-sb') + '</div>' + ['CON', 'DIV', 'WC'].map(k => col('NFC', k)).join('') + '</div></div>';
}
function seedDist(rows, S) {
  return GI.grid(GI.CONFERENCES.map(conf => {
    const list = rows.filter(r => r.conference === conf && r.seed_dist);
    if (!list.length) return '';
    const val = (sd, k) => (Array.isArray(sd) ? sd[k - 1] : sd[String(k)]);
    const exp = r => { let e = 0, t = 0; for (let k = 1; k <= 7; k++) { const v = Number(val(r.seed_dist, k)) || 0; e += k * v; t += v; } return t ? e / t + (1 - t) * 8 : 8; };
    list.sort((a, b) => exp(a) - exp(b));
    return GI.card(conf + ' seeds', '% of simulations · seeds 1–4 are division winners', GI.heatTable({ corner: 'Seed', center: 0, max: 0.5, cols: ['1', '2', '3', '4', '5', '6', '7', 'Out'], fmt: v => (v >= 0.005 ? String(Math.round(v * 100)) : '·'),
      rows: list.map(r => { const v = [1, 2, 3, 4, 5, 6, 7].map(k => val(r.seed_dist, k)); const inP = v.reduce((s, x) => s + (Number(x) || 0), 0);
        return { label: GI.teamLink(r.team, { abbr: true, season: S }), values: v.concat([Math.max(0, 1 - inP)]), titles: v.map((x, i) => GI.teamAbbr(r.team) + ' as the ' + GI.ordinal(i + 1) + ' seed: ' + GI.pct(x, 1)).concat([GI.teamAbbr(r.team) + ' misses: ' + GI.pct(1 - inP, 1)]) }; }) }), { span: 6 });
  }).join(''));
}

/* Chances (#/playoffs[/<S>]?view=sb|conf|div|playoffs|seed1|wins|draft): the season simulation's boards in one place
 * (round 9: the Season forecasts page folded in; the win totals and the draft order moved here from Standings), then the
 * round-by-round table and how the race has moved (QKL.race: our chances over time and the week's movers). */
const VIEWS = [['sb', 'Super Bowl'], ['conf', 'Conference'], ['div', 'Division'], ['playoffs', 'Playoffs'], ['seed1', 'No. 1 seed'], ['wins', 'Win totals'], ['draft', 'No. 1 pick']];
let CV = 'sb';
const markOf = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
function chanceList(list, key, S, o) {
  o = o || {};
  const L = list.filter(r => isNum(r[key])).sort((a, b) => b[key] - a[key]);
  if (!L.length) return GI.muted('The season simulation has not run yet.');
  return QK.chances(L.map(r => ({ label: GI.teamShort(r.team), p: r[key], href: GI.teamHref(r.team, S), color: GI.teamInfo(r.team).colour, mark: markOf(r.team) })), { limit: o.limit || 16, key: false });
}
function chancesBody(host, d, rows, S) {
  const v = CV;
  const sbm = (((d.bracket || {}).sim || {}).sb_matchups || []).slice(0, 10);
  let h = '';
  if (v === 'sb') h = GI.grid(GI.card('Who lifts the Lombardi Trophy?', 'Our chance from 20,000 simulated seasons', chanceList(rows, 'p_sb', S, { limit: 14 }) + QK.note('Even the favourite misses most seasons: a 20% chance means four seasons in five end without the trophy.'), { span: 7 }) +
    GI.card('Likeliest Super Bowls', 'Share of our simulated seasons', sbm.length ? GI.chartBox('po-sbm', 440, 'Likeliest Super Bowl matchups') : GI.muted('Matchups arrive with the season simulation.'), { span: 5 }));
  else if (v === 'conf') h = GI.grid(GI.CONFERENCES.map(c => GI.card(c + ' champion', 'Our chance of reaching the Super Bowl', chanceList(rows.filter(r => r.conference === c), 'p_conf', S), { span: 6 })).join(''));
  else if (v === 'div') h = GI.grid(GI.DIVISIONS.map(dv => GI.card(dv, 'Our chance of winning the division', chanceList(rows.filter(r => r.division === dv), 'p_div', S), { span: 6 })).join(''));
  else if (v === 'playoffs') h = GI.grid(GI.CONFERENCES.map(c => GI.card(c + ': make the playoffs', 'Seven of sixteen get in', chanceList(rows.filter(r => r.conference === c), 'p_playoffs', S), { span: 6 })).join('')) + seedDist(rows, S);
  else if (v === 'seed1') h = GI.grid(GI.CONFERENCES.map(c => GI.card(c + ' No. 1 seed', 'The bye and home field to the conference final', chanceList(rows.filter(r => r.conference === c), 'p_bye', S, { limit: 8 }), { span: 6 })).join(''));
  else if (v === 'wins') h = GI.STD.winsView(rows, S);
  else if (v === 'draft') h = GI.STD.draftView(d, rows, S);
  host.innerHTML = h;
  GI.sortable(host);
  if (v === 'sb' && sbm.length) GI.ch.bar('po-sbm', { cats: sbm.map(x => GI.teamAbbr(x.afc) + ' v ' + GI.teamAbbr(x.nfc)), series: [{ name: 'Chance', color: 'model', data: sbm.map(x => x.p) }], horizontal: true, labels: true, fmt: x => GI.pct(x, 1), labelWidth: 80, valName: 'Share of simulated seasons', catName: 'AFC v NFC' });
  if (v === 'wins') GI.STD.drawWins(rows);
  if (v === 'draft') {
    const list = (Array.isArray(d.draft) ? d.draft : []).filter(x => isNum(x.p_first_pick) && x.p_first_pick > 0.001).sort((a, b) => b.p_first_pick - a.p_first_pick).slice(0, 10);
    GI.ch.probBars('dr-first', list.map(x => ({ label: GI.teamName(x.team), p: x.p_first_pick, colour: GI.teamColour(x.team), href: GI.teamHref(x.team) })), { keepHeight: true, labelWidth: 140, valName: 'First-pick probability', emptyText: 'No team has a real chance at the first pick yet.' });
  }
}
function roundByRound(rows, S) {
  const list = rows.filter(r => isNum(r.p_sb)).sort((a, b) => (b.p_sb || 0) - (a.p_sb || 0));
  if (!list.length) return '';
  return GI.card('Round by round', 'Our chance of reaching each stage, from the season simulation', GI.tableHTML([{ label: 'Team' }, { label: 'Conf' }, { label: 'Playoffs', align: 'right' }, { label: 'Division', align: 'right' }, { label: 'Bye', align: 'right' },
    { label: 'Reach SB', align: 'right', title: 'Win the conference' }, { label: 'Win SB', align: 'right' }, { label: 'Projected wins', align: 'right' }],
    list.map(r => ({ _href: GI.teamHref(r.team, S), cells: [{ html: GI.teamLink(r.team, { short: true, season: S }), v: r.team }, r.conference,
      { html: GI.probBar(r.p_playoffs, GI.tc(r.team)), v: r.p_playoffs }, { html: GI.pct(r.p_div, 0), v: r.p_div }, { html: GI.pct(r.p_bye, 0), v: r.p_bye }, { html: GI.pct(r.p_conf, 1), v: r.p_conf }, { html: '<b class="gi-ours">' + GI.pct(r.p_sb, 1) + '</b>', v: r.p_sb }, { html: GI.num(r.proj_w, 1), v: r.proj_w }] })), { sticky: true }), { flush: true });
}
function pager(S, href) { return (S > GI.FIRST_SEASON ? '<a class="qk-btn" href="' + href(S - 1) + '">← ' + (S - 1) + '</a>' : '') + (S < GI.currentSeason() ? '<a class="qk-btn" href="' + href(S + 1) + '">' + (S + 1) + ' →</a>' : ''); }

GI.route('playoffs', function (el, params) {
  const S = Number(params.season);
  const q = params.query || {};
  CV = VIEWS.some(x => x[0] === q.view) ? q.view : 'sb';
  return GI.loadAll([GI.ypath('season.json', S)]).then(res => {
    if (!el.isConnected) return;
    const d = res[0];
    const nav = GI.sectionNav('standings', 'playoffs');
    const head = GI.pageHead('Standings · ' + S, S + ' chances', 'Every season question from 20,000 simulated seasons: the Super Bowl, the conferences, the divisions, the playoffs, the No. 1 seeds, win totals and the No. 1 pick.', pager(S, GI.playoffsHref)) + nav;
    if (!GI.ok(d)) { el.innerHTML = head + GI.notBuilt('The ' + S + ' chances', d); return; }
    const rows = GI.seasonRows(d);
    if (!rows.some(r => isNum(r.p_playoffs) || isNum(r.p_sb))) {
      el.innerHTML = head + QK.empty(S < GI.currentSeason() ? 'The ' + S + ' season is over' : 'The simulation has not run yet', S < GI.currentSeason() ? 'Chances are kept for the season in play. How it finished is on the Table and the Bracket.' : 'Chances appear once the season simulation has run.') +
        '<p style="text-align:center"><a class="qk-btn" href="' + GI.standingsHref(S) + '">Table</a> <a class="qk-btn primary" href="' + GI.bracketHref(S) + '">Bracket</a></p>';
      return;
    }
    el.innerHTML = head + '<div class="qk-chips scroll" id="po-chips" role="group" aria-label="Question" style="margin-bottom:var(--sp-4)">' + VIEWS.map(x => '<button type="button" class="qk-chip" data-value="' + x[0] + '" aria-pressed="' + (x[0] === CV) + '">' + esc(x[1]) + '</button>').join('') + '</div>' +
      '<div id="po-body"></div>' + roundByRound(rows, S) + (d.league && window.QKL ? '<div id="po-race"></div>' : '');
    GI.sortable(el);
    const body = el.querySelector('#po-body');
    QK.chips(el.querySelector('#po-chips'), x => { CV = x[0]; GI.setHashQuiet(GI.ghref('playoffs', S, { view: CV === 'sb' ? undefined : CV })); chancesBody(body, d, rows, S); });
    chancesBody(body, d, rows, S);
    /* how the race has moved: our chances over time and the week's movers (QKL.race); the games that matter sit on the Table */
    const lo = GI.leagueOpts ? GI.leagueOpts(d, S, GI.CONFERENCES[0]) : null;
    if (lo && el.querySelector('#po-race')) {
      QKL.race(el.querySelector('#po-race'), lo);
      QK.$$('#po-race .qk-card', el).forEach(c => { const t = c.querySelector('.qk-card-title'); if (t && /games that matter/i.test(t.textContent)) { const p = c.parentNode; if (p && p.classList.contains('qk-span-12')) p.remove(); else c.remove(); } });
    }
  });
});

/* Bracket (#/bracket[/<S>]): the bracket (projected from today's seeds during the season; a finished season shows every
 * result with our pre-game call) and each conference's seed distribution. */
GI.route('bracket', function (el, params) {
  const S = Number(params.season);
  return GI.loadAll([GI.ypath('season.json', S)]).then(res => {
    if (!el.isConnected) return;
    const d = res[0];
    const nav = GI.sectionNav('standings', 'bracket');
    const fmt = S >= 2020 ? '14 teams: seven per conference; only the No. 1 seed has a bye' : '12 teams: six per conference; the top two seeds have byes';
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead('Standings', S + ' bracket', '', pager(S, GI.bracketHref)) + nav + GI.notBuilt('The ' + S + ' bracket', d); return; }
    const rows = GI.seasonRows(d);
    const m = bracketModel(d, rows);
    const champ = m.SB && winnerOf(m.SB);
    el.innerHTML = GI.pageHead('Standings · ' + S, S + ' bracket', esc(fmt) + (m.projected ? ' · <b>projected</b> from today\'s seeds' : ''), pager(S, GI.bracketHref)) + nav +
      (champ ? '<div class="gi-br-champ" style="--tc:' + esc(GI.tc(champ)) + '">' + GI.mark(champ, 'lg') + '<div><span class="qk-kicker">Super Bowl champions</span><b>' + esc(GI.teamName(champ)) + '</b><span>' + esc(GI.teamAbbr(m.SB.away)) + ' ' + m.SB.as + ', ' + esc(GI.teamAbbr(m.SB.home)) + ' ' + m.SB.hs + '</span></div></div>' : '') +
      GI.card(m.projected ? 'Projected bracket' : 'Bracket', m.projected ? 'If the season ended today: today’s seeds. Each team’s chance of reaching each round is on Chances; a game’s win chance appears once the matchup is set' : 'Every result, with our pre-game call for the winner in small type (blue: we had the winner favoured)', S < 2020 ? GI.muted('The bracket view follows the 14-team format (2020 on). The seeds below still apply.') : bracketHTML(m)) +
      (m.projected ? seedDist(rows, S) : '');
    GI.sortable(el);
  });
});


/* A finished season's recap (round 9, phase 3), at the top of its Standings › Table: the champion and the Super Bowl
 * with our pre-game call, our record on the playoff games, the bracket with every score, the award winners against our
 * own ranking, and what we called before the season where we kept it (the race log starts with 2026). Reads the season
 * file the page has, history.json (award winners) and <S>/awards.json (our ranking for a past season). */
const AW = [['mvp', 'MVP'], ['opoy', 'Offensive Player of the Year'], ['dpoy', 'Defensive Player of the Year'], ['oroy', 'Offensive Rookie of the Year'], ['droy', 'Defensive Rookie of the Year'], ['cpoy', 'Comeback Player of the Year'], ['coty', 'Coach of the Year']];
GI.recap = function (host, d, S, rows) {
  if (!host) return;
  const m = bracketModel(d, rows);
  const games = [m.AFC, m.NFC].reduce((a, c) => a.concat(c.WC, c.DIV, [c.CON]), []).concat([m.SB]).filter(g => g && GI.isFinal(g) && winnerOf(g));
  const call = g => { const p = isNum(g.p_home) ? Number(g.p_home) : (g.model && isNum(g.model.p_home) ? g.model.p_home : null); if (p === null) return null; const w = winnerOf(g); return w === g.home ? p : 1 - p; };
  const called = games.map(call).filter(isNum), hits = called.filter(p => p > 0.5).length;
  const champ = m.SB && winnerOf(m.SB);
  const sbCall = m.SB ? call(m.SB) : null;
  const top = rows.filter(r => isNum(r.rating)).sort((a, b) => b.rating - a.rating)[0];
  const best = rows.slice().sort((a, b) => GI.STD.pctW(b) - GI.STD.pctW(a) || (b.diff || 0) - (a.diff || 0))[0];
  const far = t => { if (t === champ) return 'won the Super Bowl'; const lost = games.filter(g => g.home === t || g.away === t).map(g => g.round); if (!lost.length) return 'missed the playoffs'; const r = lost[lost.length - 1]; return { WC: 'lost in the Wild Card round', DIV: 'lost in the Divisional round', CON: 'lost the conference final', SB: 'lost the Super Bowl' }[r] || 'reached the playoffs'; };
  host.innerHTML = '<section class="qk-section gi-recap">' +
    (champ ? '<div class="gi-br-champ" style="--tc:' + esc(GI.tc(champ)) + '">' + GI.mark(champ, 'lg') + '<div><span class="qk-kicker">' + S + ' champions</span><b>' + esc(GI.teamName(champ)) + '</b><span>Super Bowl: ' + esc(GI.teamAbbr(m.SB.away)) + ' ' + m.SB.as + ', ' + esc(GI.teamAbbr(m.SB.home)) + ' ' + m.SB.hs +
      (isNum(sbCall) ? ' · our pre-game call: ' + esc(GI.teamAbbr(champ)) + ' ' + GI.pct(sbCall, 0) : '') + '</span></div></div>' : '') +
    GI.kpis([called.length ? GI.kpi('Our playoff calls', hits + ' of ' + called.length, 'games where we favoured the winner before kick-off', { signal: true }) : '',
      best ? GI.kpi('Best record', esc(GI.teamAbbr(best.team)) + ' ' + GI.record(best.w, best.l, best.t), esc(far(best.team)), { href: GI.teamHref(best.team, S) }) : '',
      top ? GI.kpi('Our top-rated team', esc(GI.teamAbbr(top.team)) + ' ' + GI.signed(top.rating, 1), 'at the end of the regular season; ' + esc(far(top.team)), { href: GI.teamHref(top.team, S) }) : '']) +
    GI.card('How the playoffs went', 'Every score, with our pre-game call for the winner (blue: we had the winner favoured) · <a href="' + GI.bracketHref(S) + '">the full bracket</a>', S >= 2020 ? bracketHTML(m) : GI.muted('The bracket view follows the 14-team format (2020 on).')) +
    '<div id="rc-aw"></div>' +
    '<p class="gi-cap">Before the season: we kept no daily simulation for ' + S + ' (the race log starts with 2026), so there is no pre-season call to set against how it finished. The final standings with the seeds are below.</p></section>';
  Promise.all([GI.load('history.json'), GI.loadYear('awards.json', S)]).then(res => {
    const h = res[0], a = res[1];
    const row = ((h && h.champions && h.champions.seasons) || []).filter(x => x.season === S)[0];
    const W = (row && row.awards) || {}, A = (GI.ok(a) && a.awards) || {};
    const list = AW.filter(k => W[k[0]]);
    if (!list.length || !host.isConnected) return;
    const fold = x => GI.fold(String(x || '').replace(/[.']/g, '').replace(/\s+(jr|sr|ii|iii|iv)$/i, ''));
    GI.set('rc-aw', GI.card('The awards', 'The winners, and where each sat on our own list (our value metrics ranked the candidates; a past season has no award probabilities)', GI.tableHTML([{ label: 'Award' }, { label: 'Winner' }, { label: 'Top of our list' }, { label: 'Winner on our list', align: 'right' }],
      list.map(k => {
        const w = W[k[0]], c = ((A[k[0]] || {}).candidates || []), i = c.findIndex(x => fold(x.name) === fold(w[0]));
        return [esc(k[1]), { html: '<b>' + esc(w[0]) + '</b> <span class="gi-tag">' + esc(GI.teamAbbr(w[1])) + '</span>', v: w[0] }, { html: c[0] ? (c[0].pid ? GI.playerLink(c[0].pid, c[0].name) : esc(c[0].name)) : '—', v: c[0] ? c[0].name : '' },
          { html: i >= 0 ? (i === 0 ? '<b class="gi-ours">1st</b>' : GI.ordinal(i + 1)) : (c.length ? 'not in our top ' + c.length : '—'), v: i >= 0 ? i : 99 }];
      })), { flush: true }));
  });
};

})(window.GI);
