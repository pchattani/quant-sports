/* The Quant Gridiron — the playoff picture (#/playoffs, #/playoffs/<S>).
 *
 * The bracket (14 teams: per conference the No. 1 seed's bye, Wild Card 2v7, 3v6, 4v5, then the
 * Divisional round with the 1 seed hosting the lowest seed left, the conference championships and
 * the Super Bowl) with each game's model probability and the market where there is one; projected
 * from the current seeds before the playoffs. Then each conference's seed distribution and the
 * round-by-round odds against the Super Bowl market.
 *
 * Reads data/<S>/season.json (bracket {seeds {AFC, NFC}, games [{round WC|DIV|CON|SB, conf, home,
 * away, seeds, p_home, market, game_id, hs, as, status, projected}], p {team: {p_div_round,
 * p_conf_game, p_sb_app, p_sb}}}; standings rows with p_playoffs, p_bye, p_conf, p_sb, seed_dist)
 * and data/<S>/markets.json (futures.sb). GI.charts.nflBracket(el, model, opts) is exported. */
(function (GI) {
'use strict';

const esc = GI.esc;
const isNum = GI.isNum;
const ROUNDS = ['WC', 'DIV', 'CON', 'SB'];
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
/* {AFC: {seeds: [t1..t7], WC: [g27, g36, g45], DIV: [gA, gB], CON: g}, NFC: ..., SB: g, projected}. */
function bracketModel(d, rows) {
  const br = d.bracket || d.playoffs || {};
  const seeds = {};
  const brGames = (br.games || []).concat([].concat.apply([], (br.rounds || []).map(r => (r.games || []).map(g => Object.assign({ round: r.key }, g)))));
  const seedSrc = br.seeds || br.seeds_today || d.seeds_today || {};
  const projected = !brGames.some(g => !g.projected && (g.game_id || GI.isFinal(g) || GI.isLive(g)));
  GI.CONFERENCES.forEach(conf => {
    let s = seedSrc[conf];
    if (s && !Array.isArray(s)) s = s.seeds || [];
    if (!s || !s.length) s = rows.filter(r => r.conference === conf && (isNum(r.seed) || isNum(r.p_playoffs)))
      .sort((a, b) => (isNum(a.seed) && isNum(b.seed) ? a.seed - b.seed : (b.p_playoffs || 0) - (a.p_playoffs || 0))).slice(0, 7).map(r => r.team);
    seeds[conf] = s.map(GI.canonTeam);
  });
  const games = brGames.map(g => Object.assign({}, g, { round: roundKey(g.round || g.gtype), home: GI.canonTeam(g.home), away: GI.canonTeam(g.away) }));
  const seedOf = (conf, t) => { const i = seeds[conf].indexOf(t); return i >= 0 ? i + 1 : null; };
  const find = (round, conf, a, b) => games.find(g => g.round === round && (!conf || confOf(g) === conf) && ((a && (g.home === a || g.away === a)) || (b && (g.home === b || g.away === b)))) || null;
  const out = { seeds: seeds, projected: projected, SB: null, p: br.p || {} };
  GI.CONFERENCES.forEach(conf => {
    const S = seeds[conf];
    const wc = [[2, 7], [3, 6], [4, 5]].map(pr => {
      const h = S[pr[0] - 1], a = S[pr[1] - 1];
      return find('WC', conf, h, a) || { round: 'WC', conf: conf, home: h || null, away: a || null, projected: true };
    });
    const alive = [S[0]].concat(wc.map(g => winnerOf(g)));
    const known = alive.every(Boolean);
    let div = games.filter(g => g.round === 'DIV' && confOf(g) === conf);
    if (div.length < 2) {
      const left = known ? alive.slice().sort((x, y) => seedOf(conf, x) - seedOf(conf, y)) : null;
      const gA = div.find(g => g.home === S[0] || g.away === S[0]) || { round: 'DIV', conf: conf, home: S[0] || null, away: left ? left[3] : null, projected: true, tbd: !left };
      const gB = div.find(g => g !== gA) || { round: 'DIV', conf: conf, home: left ? left[1] : null, away: left ? left[2] : null, projected: true, tbd: !left };
      div = [gA, gB];
    }
    const con = games.find(g => g.round === 'CON' && confOf(g) === conf) || { round: 'CON', conf: conf, home: null, away: null, projected: true, tbd: true };
    out[conf] = { seeds: S, WC: wc, DIV: div, CON: con };
  });
  out.SB = games.find(g => g.round === 'SB') || { round: 'SB', home: winnerOf(out.AFC.CON), away: winnerOf(out.NFC.CON), projected: true, tbd: true };
  return out;
}
function gameBox(g, title, m) {
  if (!g) return '';
  const st = GI.gameState(g);
  const fin = st === 'final', live = GI.isLive(g);
  const w = winnerOf(g);
  const seedOf = t => { for (let k = 0; k < GI.CONFERENCES.length; k++) { const i = (m.seeds[GI.CONFERENCES[k]] || []).indexOf(t); if (i >= 0) return i + 1; } return ''; };
  const pH = live && isNum(g.wp_home) ? g.wp_home : (isNum(g.p_home) ? Number(g.p_home) : (g.model && isNum(g.model.p_home) ? g.model.p_home : null));
  const mk = isNum(g.market) ? Number(g.market) : (g.market && isNum(g.market.p_home) ? g.market.p_home : null);
  const row = (t, side) => {
    if (!t) return '<div class="nb-team tbd"><span class="nb-seed"></span><span class="nb-name">TBD</span><span class="nb-s"></span><span class="nb-p"></span></div>';
    const p = pH === null ? null : (side === 'home' ? pH : 1 - pH);
    const q = mk === null ? null : (side === 'home' ? mk : 1 - mk);
    const sc = side === 'home' ? g.hs : g.as;
    return '<div class="nb-team' + (w && w === t ? ' won' : '') + (w && w !== t ? ' lost' : '') + '"><span class="nb-seed">' + esc(seedOf(t)) + '</span>' +
      '<span class="nb-name">' + GI.teamBar(t) + esc(GI.teamAbbr(t)) + '<span class="nb-full">' + esc(GI.teamShort(t)) + '</span></span>' +
      '<span class="nb-s">' + (isNum(sc) && st !== 'pre' ? esc(sc) : '') + '</span>' +
      '<span class="nb-p" title="' + (q !== null ? 'Model ' + GI.pct(p, 1) + ' · market ' + GI.pct(q, 1) : 'Model probability of winning this game') + '">' + (fin ? '' : (p !== null ? GI.pct(p, 0) : '')) + (q !== null && !fin ? '<small>mkt ' + GI.pct(q, 0) + '</small>' : '') + '</span></div>';
  };
  const tag = g.game_id ? 'a href="' + GI.gameHref(g.game_id) + '"' : 'div';
  return '<' + tag + ' class="nb-game' + (fin ? ' done' : '') + (live ? ' live' : '') + (g.projected ? ' proj' : '') + '"><div class="nb-head">' + esc(title) +
    (live ? '<span><span class="live-dot"></span> ' + esc(GI.clockText(g.qtr, g.clock)) + '</span>' : g.kickoff && !fin ? '<span>' + esc(GI.fmtDate(g.kickoff, { year: false })) + '</span>' : g.projected ? '<span>projected</span>' : '') + '</div>' +
    row(g.away, 'away') + row(g.home, 'home') + '</' + (g.game_id ? 'a' : 'div') + '>';
}
let ROUND_SEL = null;
function nflBracket(el, m) {
  const root = typeof el === 'string' ? document.getElementById(el) : el;
  if (!root) return;
  if (!m.AFC.seeds.length && !m.NFC.seeds.length) { root.innerHTML = GI.muted('The bracket is not set yet.'); return; }
  const byeBox = conf => '<div class="nb-game proj"><div class="nb-head">' + esc(conf) + ' No. 1 seed<span>bye</span></div>' +
    (m[conf].seeds[0] ? '<div class="nb-team"><span class="nb-seed">1</span><span class="nb-name">' + GI.teamBar(m[conf].seeds[0]) + esc(GI.teamAbbr(m[conf].seeds[0])) + '<span class="nb-full">' + esc(GI.teamShort(m[conf].seeds[0])) + '</span></span><span class="nb-s"></span><span class="nb-p"></span></div>' : '') + '</div>';
  const col = (conf, k) => {
    const x = m[conf];
    if (k === 'WC') return byeBox(conf) + x.WC.map((g, i) => gameBox(g, conf + ' WC · ' + ['2 v 7', '3 v 6', '4 v 5'][i], m)).join('');
    if (k === 'DIV') return x.DIV.map((g, i) => gameBox(g, conf + ' Divisional' + (i === 0 ? ' · 1 seed' : ''), m)).join('');
    return gameBox(x.CON, conf + ' Championship', m);
  };
  const draw = () => {
    const narrow = (root.clientWidth || 1000) < 900;
    if (!narrow) {
      root.innerHTML = '<div class="nb-wrap"><div class="nb-grid">' +
        ['WC', 'DIV', 'CON'].map(k => '<div class="nb-round"><div class="nb-title">AFC ' + ROUND_NAME[k] + '</div><div class="nb-col">' + col('AFC', k) + '</div></div>').join('') +
        '<div class="nb-round nb-sb"><div class="nb-title">Super Bowl</div><div class="nb-col">' + gameBox(m.SB, 'Super Bowl', m) + '</div></div>' +
        ['CON', 'DIV', 'WC'].map(k => '<div class="nb-round"><div class="nb-title">NFC ' + ROUND_NAME[k] + '</div><div class="nb-col">' + col('NFC', k) + '</div></div>').join('') +
        '</div></div>';
    } else {
      if (ROUND_SEL === null) {
        ROUND_SEL = 'WC';
        ROUNDS.forEach(rk => {
          const gs = rk === 'SB' ? [m.SB] : rk === 'CON' ? [m.AFC.CON, m.NFC.CON] : rk === 'DIV' ? m.AFC.DIV.concat(m.NFC.DIV) : [];
          if (gs.some(g => g && (GI.isFinal(g) || GI.isLive(g)))) ROUND_SEL = rk;
        });
      }
      const body = ROUND_SEL === 'SB' ? gameBox(m.SB, 'Super Bowl', m) : GI.CONFERENCES.map(c => col(c, ROUND_SEL)).join('');
      root.innerHTML = '<div class="toggle-row nb-rounds">' + GI.toggles(ROUNDS.map(r => ({ key: r, label: ROUND_NAME[r] })), ROUND_SEL, 'data-rd') + '</div><div class="nb-list">' + body + '</div>';
      GI.wireToggles(root.querySelector('.nb-rounds'), 'data-rd', k => { ROUND_SEL = k; draw(); });
    }
  };
  draw();
  let lastW = root.clientWidth;
  const onResize = () => { if (!root.isConnected) return; const w = root.clientWidth; if ((w < 900) !== (lastW < 900)) draw(); lastW = w; };
  window.addEventListener('resize', onResize);
  GI.onLeave(() => window.removeEventListener('resize', onResize));
}
GI.charts.nflBracket = nflBracket;
GI.charts.nflBracketModel = bracketModel;

function seedDistBlock(rows, S) {
  const html = GI.CONFERENCES.map(conf => {
    const list = rows.filter(r => r.conference === conf && r.seed_dist);
    if (!list.length) return '';
    const val = (sd, k) => (Array.isArray(sd) ? sd[k - 1] : (sd[String(k)] !== undefined ? sd[String(k)] : sd[k]));
    const exp = r => { let e = 0, t = 0; for (let k = 1; k <= 7; k++) { const v = Number(val(r.seed_dist, k)) || 0; e += k * v; t += v; } return t ? e / t + (1 - t) * 8 : 8; };
    list.sort((a, b) => exp(a) - exp(b));
    const spec = { corner: 'Seed', scale: 'seq', max: 0.6, cols: ['1', '2', '3', '4', '5', '6', '7', 'Out'],
      fmt: v => (v >= 0.005 ? Math.round(v * 100) + '' : '·'),
      rows: list.map(r => {
        const v = [1, 2, 3, 4, 5, 6, 7].map(k => val(r.seed_dist, k));
        const inP = v.reduce((s, x) => s + (Number(x) || 0), 0);
        const out = Array.isArray(r.seed_dist) && r.seed_dist.length > 7 ? r.seed_dist[7] : (r.seed_dist.out !== undefined ? r.seed_dist.out : Math.max(0, 1 - inP));
        return { label: GI.teamLink(r.team, { abbr: true, season: S }), values: v.concat([out]), titles: v.map((x, i) => GI.teamAbbr(r.team) + ' as the ' + GI.ordinal(i + 1) + ' seed: ' + GI.pct(x, 1)).concat([GI.teamAbbr(r.team) + ' misses: ' + GI.pct(out, 1)]) };
      }) };
    return '<div>' + GI.card(conf + ' seeds', '% of simulations · seeds 1–4 are division winners', GI.charts.heatTable(spec)) + '</div>';
  }).join('');
  return html ? '<div class="grid-2">' + html + '</div>' : '';
}
function oddsBlock(rows, m, mk, S) {
  const sbF = ((mk && mk.futures) || {}).sb || {};
  const sbM = sbF.market && typeof sbF.market === 'object' ? sbF.market : {};
  const sbMk = sbM.probs || sbM.prices || sbM.mid || sbM.available === false ? GI.titleProbs(sbM) : sbM;
  const list = rows.filter(r => isNum(r.p_playoffs) || isNum(r.p_sb)).sort((a, b) => (b.p_sb || 0) - (a.p_sb || 0) || (b.p_playoffs || 0) - (a.p_playoffs || 0));
  if (!list.length) return '';
  const P = m.p || {};
  const cols = [{ label: 'Team' }, { label: 'Conf' }, { label: 'Playoffs' }, { label: 'Bye', align: 'right' }, { label: 'Div. round', align: 'right', title: 'Reach the Divisional round' },
    { label: 'Conf. game', align: 'right', title: 'Reach the conference championship' }, { label: 'Super Bowl', align: 'right', title: 'Reach the Super Bowl' },
    { label: 'Win SB', align: 'right' }, { label: 'Market', align: 'right', title: 'De-vigged Super Bowl winner market' }, { label: 'Model − market', align: 'right', title: 'Percentage points: a disagreement, not a recommendation' }];
  const has = k => list.some(r => isNum((P[r.team] || {})[k]) || isNum(r[k]));
  const drop = [];
  if (!has('p_div_round')) drop.push(4);
  if (!has('p_conf_game')) drop.push(5);
  const keep = (x, i) => drop.indexOf(i) < 0;
  return GI.card('Round-by-round odds', 'model · Super Bowl market from <a href="#/markets">Markets</a>', GI.tableHTML(cols.filter(keep), list.map(r => {
    const p = P[r.team] || {};
    const q = isNum(sbMk[r.team]) ? Number(sbMk[r.team]) : null;
    return { _href: GI.teamHref(r.team, S), cells: [{ html: GI.teamLink(r.team, { short: true, season: S }), v: r.team }, r.conference || '—',
      { html: GI.probCell(r.p_playoffs, GI.teamColour(r.team)), v: r.p_playoffs }, { html: GI.pct(r.p_bye, 0), v: r.p_bye },
      { html: GI.pct(isNum(p.p_div_round) ? p.p_div_round : r.p_div_round, 0), v: isNum(p.p_div_round) ? p.p_div_round : r.p_div_round },
      { html: GI.pct(isNum(p.p_conf_game) ? p.p_conf_game : r.p_conf_game, 0), v: isNum(p.p_conf_game) ? p.p_conf_game : r.p_conf_game },
      { html: GI.pct(isNum(p.p_sb_app) ? p.p_sb_app : r.p_conf, 1), v: isNum(p.p_sb_app) ? p.p_sb_app : r.p_conf },
      { html: '<b>' + GI.pct(isNum(p.p_sb) ? p.p_sb : r.p_sb, 1) + '</b>', v: isNum(p.p_sb) ? p.p_sb : r.p_sb },
      { html: q === null ? '—' : GI.pct(q, 1), v: q }, { html: GI.edgeHTML(isNum(p.p_sb) ? p.p_sb : r.p_sb, q), v: q === null ? null : (r.p_sb || 0) - q }].filter(keep) };
  }), { compact: true, cls: 'std-table' }));
}

GI.route('playoffs', function (el, params) {
  const S = Number(params.season);
  return Promise.all([GI.loadYear('season.json', S), GI.loadYear('markets.json', S)]).then(res => {
    if (!el.isConnected) return;
    const d = res[0], mk = GI.ok(res[1]) ? res[1] : null;
    const nav = '<a href="' + GI.standingsHref(S) + '">Standings →</a>' + (S > GI.FIRST_SEASON ? '<a href="' + GI.playoffsHref(S - 1) + '">← ' + (S - 1) + '</a>' : '') + (S < GI.currentSeason() ? '<a href="' + GI.playoffsHref(S + 1) + '">' + (S + 1) + ' →</a>' : '');
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead(S + ' playoffs', '', nav) + GI.notBuilt('The ' + S + ' playoff picture', d); return; }
    const rows = GI.seasonRows ? GI.seasonRows(d) : [];
    const m = bracketModel(d, rows);
    const fmt = S >= 2020 ? '14 teams: seven per conference, the No. 1 seed has the only bye' : '12 teams: six per conference, the top two seeds have byes';
    el.innerHTML = GI.pageHead(S + ' playoffs', esc(fmt) + (m.projected ? ' · <b>projected</b> from the current seeds' : ''), nav) +
      GI.card(m.projected ? 'Projected bracket' : 'Bracket', m.projected ? 'if the season ended today · each game priced by the model (market below where listed)' : 'model probability per game; market below where listed', '<div id="po-br"></div>') +
      seedDistBlock(rows, S) + oddsBlock(rows, m, mk, S);
    if (S < 2020) {
      el.querySelector('#po-br').innerHTML = GI.muted('The bracket view follows the 14-team format (2020 on). The seeds and odds below still apply.');
    } else nflBracket(el.querySelector('#po-br'), m);
    GI.sortable(el);
  });
});

})(window.GI);
