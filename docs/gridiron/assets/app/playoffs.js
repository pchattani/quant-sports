/* The Quant Gridiron — the playoff picture (#/playoffs[/<S>]), in the Standings section.
 * The bracket (projected from today's seeds before the playoffs; 14 teams from 2020), each game priced
 * by the model; the likeliest Super Bowl matchups; each conference's seed distribution; round-by-round
 * odds against the Super Bowl market. Reads <S>/season.json and <S>/markets.json. */
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
  return '<' + tag + ' class="gi-br-g' + (cls ? ' ' + cls : '') + '">' + row(g.away, 'away') + row(g.home, 'home') + '</' + (g.game_id ? 'a' : 'div') + '>';
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

GI.route('playoffs', function (el, params) {
  const S = Number(params.season);
  return GI.loadAll([GI.ypath('season.json', S)].concat(S === GI.currentSeason() ? [GI.ypath('markets.json', S)] : [])).then(res => {
    if (!el.isConnected) return;
    const d = res[0], mk = GI.ok(res[1]) ? res[1] : null;
    const pager = (S > GI.FIRST_SEASON ? '<a class="qk-btn" href="' + GI.playoffsHref(S - 1) + '">← ' + (S - 1) + '</a>' : '') + (S < GI.currentSeason() ? '<a class="qk-btn" href="' + GI.playoffsHref(S + 1) + '">' + (S + 1) + ' →</a>' : '');
    const nav = GI.sectionNav('standings', 'playoffs');
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead('Standings', S + ' playoff picture', '', pager) + nav + GI.notBuilt('The ' + S + ' playoff picture', d); return; }
    const rows = GI.seasonRows(d);
    const m = bracketModel(d, rows);
    const fmt = S >= 2020 ? '14 teams: seven per conference; only the No. 1 seed has a bye' : '12 teams: six per conference; the top two seeds have byes';
    const sbm = (((d.bracket || {}).sim || {}).sb_matchups || []).slice(0, 10);
    const sbMk = {};
    (((mk || {}).futures || {}).sb || []).forEach(r => { if (r && r.team) sbMk[r.team] = r.market; });
    const list = rows.filter(r => isNum(r.p_sb)).sort((a, b) => (b.p_sb || 0) - (a.p_sb || 0));
    el.innerHTML = GI.pageHead('Standings', S + ' playoff picture', esc(fmt) + (m.projected ? ' · <b>projected</b> from today\'s seeds' : ''), pager) + nav +
      GI.card(m.projected ? 'Projected bracket' : 'Bracket', m.projected ? 'if the season ended today · each matchup priced by the model' : 'model win probability per game, score once played', S < 2020 ? GI.muted('The bracket view follows the 14-team format (2020 on). The seeds and odds below still apply.') : bracketHTML(m)) +
      GI.grid(GI.card('Super Bowl: model v market', 'blue model, orange market', GI.chartBox('po-sb', 440, 'Super Bowl odds, model against market'), { span: 7 }) +
        GI.card('Likeliest Super Bowls', '% of simulations', sbm.length ? GI.chartBox('po-sbm', 440, 'Likeliest Super Bowl matchups') : GI.muted('Matchups arrive with the season simulation.'), { span: 5 })) +
      seedDist(rows, S) +
      GI.card('Round-by-round odds', 'model · Super Bowl market from <a href="#/futures">Futures</a>', GI.tableHTML([{ label: 'Team' }, { label: 'Conf' }, { label: 'Playoffs', align: 'right' }, { label: 'Bye', align: 'right' },
        { label: 'Reach SB', align: 'right', title: 'Win the conference' }, { label: 'Win SB', align: 'right' }, { label: 'Market', align: 'right', title: 'De-vigged Super Bowl winner market' }, { label: 'Gap', align: 'right', title: 'Model minus market, points: a disagreement, not a recommendation' }],
        list.map(r => { const q = isNum(sbMk[r.team]) ? sbMk[r.team] : null; return { _href: GI.teamHref(r.team, S), cells: [{ html: GI.teamLink(r.team, { short: true, season: S }), v: r.team }, r.conference,
          { html: GI.probBar(r.p_playoffs, GI.tc(r.team)), v: r.p_playoffs }, { html: GI.pct(r.p_bye, 0), v: r.p_bye }, { html: GI.pct(r.p_conf, 1), v: r.p_conf }, { html: '<b>' + GI.pct(r.p_sb, 1) + '</b>', v: r.p_sb },
          { html: q === null ? '—' : GI.pct(q, 1), v: q }, { html: GI.gapHTML(r.p_sb, q), v: q === null ? null : r.p_sb - q }] }; }), { sticky: true }), { flush: true });
    GI.sortable(el);
    const dm = list.filter(r => isNum(sbMk[r.team])).slice(0, 14);
    if (dm.length) GI.ch.dumbbell('po-sb', { rows: dm.map(r => ({ label: GI.teamName(r.team), a: r.p_sb, b: sbMk[r.team], href: GI.teamHref(r.team) })), max: Math.min(1, Math.max.apply(null, dm.map(r => Math.max(r.p_sb, sbMk[r.team]))) * 1.15), labelWidth: 150, valName: 'Super Bowl probability' });
    else GI.ch.probBars('po-sb', list.slice(0, 14).map(r => ({ label: GI.teamName(r.team), p: r.p_sb, colour: GI.teamColour(r.team), href: GI.teamHref(r.team) })), { keepHeight: true, valName: 'Super Bowl probability' });
    if (sbm.length) GI.ch.bar('po-sbm', { cats: sbm.map(x => GI.teamAbbr(x.afc) + ' v ' + GI.teamAbbr(x.nfc)), series: [{ name: 'Chance', data: sbm.map(x => x.p) }], horizontal: true, labels: true, fmt: v => GI.pct(v, 1), labelWidth: 80 });
  });
});

})(window.GI);
