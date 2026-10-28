/* The Quant Rink — the season recap (#/?s=<S> for a finished season; round 9, 28 Oct 2026). The overview of a past
 * season reads as what happened, not as an empty current-season template:
 *   1. the champion and the Final, with our chance of the champion before the season and at days 60 and 120
 *      (calibration.json season_sim.runs: the simulation run at those checkpoints with ratings fitted before them);
 *   2. the final bracket with the series scores (playoffs.js RK.bracket), then our pre-series call on every series:
 *      the walk-forward forecast of game 1 (schedule.json model.p_home, made before the series) carried through a
 *      best-of-seven with home ice in games 1, 2, 5 and 7; the road chance is the game-1 chance less twice the season's
 *      home edge in our own forecasts (the mean home chance of the regular season less 50%);
 *   3. the final standings by conference with seeds and clinch marks;
 *   4. the award winners (awards.json winners) beside the top of the usual criteria (awards.json boards);
 *   5. the season's leaders (history.json season_leaders);
 *   6. how our game forecasts did over the regular season (schedule.json: the favourite's record).
 * Reads <S>/season.json, <S>/schedule.json, <S>/awards.json, history.json and calibration.json. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const AWARD_WHAT = { hart: 'Most valuable player', vezina: 'Best goaltender', norris: 'Best defenceman', calder: 'Best rookie', ross: 'Most points', richard: 'Most goals', selke: 'Best defensive forward' };

/* P(the home-ice side wins a best-of-seven): home games 1, 2, 5, 7 at pH, road games 3, 4, 6 at pR. */
function seriesP(pH, pR) {
  const HOME = [1, 1, 0, 0, 1, 0, 1];
  let st = { '0-0': 1 }, win = 0;
  for (let g = 0; g < 7; g++) {
    const nx = {};
    Object.keys(st).forEach(k => {
      const ab = k.split('-').map(Number), p = HOME[g] ? pH : pR, pr = st[k];
      const a = [ab[0] + 1, ab[1]], b = [ab[0], ab[1] + 1];
      if (a[0] === 4) win += pr * p; else nx[a.join('-')] = (nx[a.join('-')] || 0) + pr * p;
      if (b[1] < 4) nx[b.join('-')] = (nx[b.join('-')] || 0) + pr * (1 - p);
    });
    st = nx;
  }
  return win;
}
/* Our pre-series call for every series in a bracket: { key: { fav, p, hit, home } } from the schedule's game-1 forecasts. */
function seriesCalls(b, games) {
  const by = {};
  (games || []).forEach(g => { if (g && g.game_id) by[String(g.game_id)] = g; });
  const reg = (games || []).filter(g => g && String(g.type || '') !== 'PO' && !RK.isPlayoffGame(g) && g.model && isNum(g.model.p_home));
  const edge = reg.length > 100 ? reg.reduce((s, g) => s + g.model.p_home, 0) / reg.length - 0.5 : 0.03;
  const out = [];
  [1, 2, 3, 4].forEach(r => ((b && b.rounds[r]) || []).filter(Boolean).forEach(x => {
    const g1 = by[String((x.games || [])[0])];
    if (!g1 || !g1.model || !isNum(g1.model.p_home) || !x.a.team) return;
    const H = RK.canonTeam(g1.home), A = RK.canonTeam(g1.away);
    const pH = g1.model.p_home, pR = Math.max(0.02, Math.min(0.98, pH - 2 * edge));
    const pSer = seriesP(pH, pR);
    const fav = pSer >= 0.5 ? H : A, p = Math.max(pSer, 1 - pSer);
    const win = x.winner || (x.a.wins >= 4 ? x.a.team : x.b.wins >= 4 ? x.b.team : null);
    out.push({ round: r, s: x, home: H, away: A, fav: fav, p: p, pHome: pSer, winner: win, hit: win ? win === fav : null });
  }));
  return { list: out, edge: edge };
}
RK.seriesCalls = seriesCalls;
RK.seriesP = seriesP;

function render(el, S) {
  const L = RK.seasonLabel(S);
  el.innerHTML = '<section class="ql-intro rk-recap-intro" aria-label="Season recap"><div class="ql-intro-l"><div class="qk-greet-date">NHL · ' + esc(L) + ' · Season recap</div><h1 id="rc-title">The ' + esc(L) + ' season</h1><p id="rc-lede">How it finished, and how our numbers called it.</p></div>' +
    '<nav class="ql-links" aria-label="This season"><a href="' + esc(RK.standingsHref(S)) + '"><b>Standings</b><span>The final table</span></a><a href="' + esc(RK.standingsHref(S)) + '?tab=bracket"><b>Bracket</b><span>Every series</span></a><a href="#/scout?s=' + S + '"><b>Scouting Room</b><span>Every player that season</span></a></nav></section>' +
    '<div id="rc-champ">' + QK.skeleton('card', 1) + '</div><div id="rc-bracket"></div><div id="rc-calls"></div><div id="rc-table"></div><div id="rc-awards"></div><div id="rc-leaders"></div><div id="rc-games"></div>' +
    '<p class="qk-sub rk-ov-doing"><a class="qk-link" href="#/">Back to this season →</a> ' + esc(RK.seasonLabel(RK.currentSeason())) + ' as it stands.</p>';
  return Promise.all([RK.loadYear('season.json', S), RK.loadYear('schedule.json', S), RK.loadYear('awards.json', S), RK.load('history.json'), RK.load('calibration.json')]).then(res => {
    if (!U.alive(el)) return;
    const d = RK.ok(res[0]) ? res[0] : null, sch = RK.ok(res[1]) ? (res[1].games || []) : [], aw = RK.ok(res[2]) ? res[2] : null, hist = RK.ok(res[3]) ? res[3] : {}, cal = RK.ok(res[4]) ? res[4] : {};
    if (!d) { el.querySelector('#rc-champ').innerHTML = QK.empty('Not built yet', 'The ' + L + ' season file is not available.'); return; }
    const rows = RK.seasonRows(d);
    const sn = (d.bracket || {}).seeds_now || null;
    const confs = ['Eastern', 'Western'].filter(c => rows.some(r => r.conference === c));
    confs.forEach(c => RK.seedConf(rows, c, sn));
    const b = RK.bracket ? RK.bracket.of(d) : null;
    const hc = (hist.champions || []).filter(x => Number(x.season) === Number(S))[0] || {};
    const champ = (b && b.champion) || (hc.champion_abbr ? RK.canonTeam(hc.champion_abbr) : null);
    const fin = b && (b.rounds[4] || []).filter(Boolean)[0];
    const runner = fin && champ ? (fin.a.team === champ ? fin.b.team : fin.a.team) : (hc.finalist_abbr ? RK.canonTeam(hc.finalist_abbr) : null);
    const finSc = fin ? Math.max(fin.a.wins || 0, fin.b.wins || 0) + '–' + Math.min(fin.a.wins || 0, fin.b.wins || 0) : '';
    const pres = rows.slice().sort(RK.standingsCmp)[0];
    const runs = ((cal.season_sim || {}).runs || []).filter(x => Number(x.season) === Number(S) && isNum(x.p_champion)).sort((x, y) => x.day - y.day);
    const calls = b ? seriesCalls(b, sch) : { list: [] };
    const done = calls.list.filter(c => c.hit !== null), hits = done.filter(c => c.hit).length;
    const cr = champ ? rows.filter(r => r.team === champ)[0] : null;
    /* 1. the champion */
    if (champ) {
      el.querySelector('#rc-title').textContent = RK.teamShort(champ) + ' won the Cup.';
      el.querySelector('#rc-lede').textContent = RK.teamName(champ) + (runner ? ' beat the ' + RK.teamName(runner) + (finSc ? ' ' + finSc : '') + ' in the Final' : ' won the Stanley Cup') + '. ' +
        (runs.length ? 'Before the season we gave them ' + U.pct(runs[0].p_champion) + ' to lift it.' : '') + (done.length ? ' We favoured the winner in ' + hits + ' of ' + done.length + ' series.' : '');
      const tiles = [{ label: 'Stanley Cup', value: RK.teamAbbr(champ), signal: true, href: RK.teamHref(champ, S), sub: RK.teamName(champ) + (runner ? ' beat ' + RK.teamShort(runner) + (finSc ? ' ' + finSc : '') : '') },
        cr ? { label: 'Their regular season', value: cr.pts + ' pts', sub: RK.record(cr.w, cr.l, cr.otl) + (cr.seed ? ' · seeded ' + cr.seed : '') + (isNum(cr.rating) ? ' · our rating ' + U.signed(cr.rating, 2) : '') } : null,
        pres ? { label: 'Best record', value: RK.teamAbbr(pres.team) + ' ' + pres.pts, href: RK.teamHref(pres.team, S), sub: RK.teamName(pres.team) + ': the Presidents’ Trophy' + (pres.team === champ ? ', and the Cup' : '') } : null,
        runs.length ? { label: 'Our pre-season chance', value: U.pct(runs[0].p_champion), tip: 'Our season simulation run on opening day with ratings fitted before it, and again at days 60 and 120', sub: 'for ' + RK.teamShort(champ) + runs.slice(1).map(x => '; day ' + x.day + ': ' + U.pct(x.p_champion)).join('') } : null,
        done.length ? { label: 'Our series calls', value: hits + ' of ' + done.length, sub: 'series won by our pre-series favourite' } : null].filter(Boolean);
      el.querySelector('#rc-champ').innerHTML = '<section class="qk-section" style="margin-top:var(--sp-5)">' + QK.stats(tiles) + '</section>';
    } else el.querySelector('#rc-champ').innerHTML = QK.note('No champion on record for ' + L + '.');
    /* 2. the bracket and our calls */
    if (b && RK.bracket) {
      el.querySelector('#rc-bracket').innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'The playoffs', title: 'How the bracket played out', sub: 'Every series with its seeds and the result in games.' }) +
        '<div class="qk-card"><div class="qk-card-body rk-recap-br">' + RK.bracket.html(b) + '</div></div></section>';
    }
    if (calls.list.length) {
      const RT = (RK.bracket || {}).RT || {};
      const line = c => '<li class="' + (c.hit === true ? 'hit' : c.hit === false ? 'miss' : '') + '"><span class="rd">' + esc(RT[c.round] || '') + '</span>' +
        '<span class="m">' + U.teamEnt(c.s.a.team, { abbr: true, season: S }) + '<span class="qk-muted"> v </span>' + U.teamEnt(c.s.b.team, { abbr: true, season: S }) + '</span>' +
        '<span class="f">We had <b>' + esc(RK.teamAbbr(c.fav)) + ' ' + U.pct(c.p, 0) + '</b></span><span class="r">' + (c.winner ? esc(RK.teamAbbr(c.winner)) + ' won ' + Math.max(c.s.a.wins || 0, c.s.b.wins || 0) + '–' + Math.min(c.s.a.wins || 0, c.s.b.wins || 0) : 'Not finished') + '</span>' +
        '<span class="v">' + (c.hit === true ? QK.tag('Called it', 'signal') : c.hit === false ? QK.tag('Upset') : '') + '</span>' +
        '<a class="qk-more" href="' + esc(RK.seriesHref ? RK.seriesHref(S, c.round, c.s.n) : RK.standingsHref(S) + '?tab=bracket') + '">Series</a></li>';
      const exp = done.reduce((s, c) => s + c.p, 0);
      el.querySelector('#rc-calls').innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Our calls', title: 'We said it. Here’s what happened.', sub: 'Our chance for each series before it started: the forecast for game 1, made before the puck dropped, carried through a best of seven with home ice (the road games ' + U.f(200 * calls.edge, 1) + ' points lower, the home-ice advantage in our own forecasts that season).' }) +
        (done.length ? QK.explain('<b>' + hits + ' of ' + done.length + ' favourites went through.</b> Our chances added up to ' + U.f(exp, 1) + ' expected: ' + (Math.abs(hits - exp) < 1.5 ? 'right where the numbers said.' : hits > exp ? 'favourites did a little better than we expected.' : 'more upsets than we expected. Playoff series are close to coin flips: a 60% favourite still goes out 4 times in 10.')) : '') +
        '<div class="qk-card"><div class="qk-card-body flush"><ul class="rk-list rk-calls">' + calls.list.map(line).join('') + '</ul></div></div></section>';
    }
    /* 3. the final standings */
    if (rows.length) {
      el.querySelector('#rc-table').innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Final standings', title: 'Where everyone finished', sub: 'Playoff seeds (A1 = first in the Atlantic, WC = wild card) and clinch marks: x playoff spot, y division, z conference, p Presidents’ Trophy, e eliminated.', actions: '<a class="qk-more" href="' + esc(RK.standingsHref(S)) + '">Full standings</a>' }) +
        '<div class="qk-grid">' + confs.map(c => '<div class="qk-span-6">' + U.card2(c + ' Conference', 'by points', '<div id="rc-st-' + c.charAt(0) + '"></div>', { flush: true }) + '</div>').join('') + '</div></section>';
      confs.forEach(c => {
        const list = rows.filter(r => r.conference === c).slice().sort(RK.standingsCmp);
        QK.leaderboard(el.querySelector('#rc-st-' + c.charAt(0)), { dense: true, rank: true, rowHref: r => RK.teamHref(r.team, S), columns: [
          { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team, S), sub: 'cl' },
          { key: 'seed', label: 'Seed', sort: false, fmt: v => (v ? '<b>' + esc(v) + '</b>' : '<span class="qk-muted">—</span>') },
          { key: 'rec', label: 'W-L-OTL', sort: false }, { key: 'pts', label: 'Pts', num: true, fmt: v => '<b>' + v + '</b>' },
          { key: 'xgf_pct', label: 'xGF%', num: true, fmt: v => U.pct(v, 1), tip: 'Share of 5-on-5 expected goals' },
          { key: 'rating', label: 'Rating', num: true, fmt: v => U.signed(v, 2), tip: 'Our team rating at the end of the season: goals a game better than an average club' }],
          rows: list.map(r => Object.assign({}, r, { name: RK.teamShort(r.team), rec: RK.record(r.w, r.l, r.otl), cl: r.clinch ? 'clinched: ' + ({ x: 'playoff spot', y: 'division', z: 'conference', p: 'Presidents’ Trophy', e: 'eliminated' }[String(r.clinch).toLowerCase()] || r.clinch) : '' })) });
      });
    }
    /* 4. awards */
    const W = (aw && aw.winners) || {};
    const AW = ((aw && aw.awards) || []).filter(a => (W[a.key] || []).length);
    if (AW.length) {
      const bc = (aw.board_cols || ['id', 'name', 'team', 'value']);
      const board = k => ((aw.boards || {})[k] || []).map(x => { const o = {}; bc.forEach((c, i) => { o[c] = x[i]; }); return o; });
      el.querySelector('#rc-awards').innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Awards', title: 'Who took the trophies', sub: 'The winners, beside the player who led the award’s usual criteria in our numbers.' }) +
        '<div class="rk-aw-grid">' + AW.map(a => {
          const w = W[a.key][0], top = board(a.key)[0];
          const same = top && w && QK.surname(String(top.name || '')) === QK.surname(String(w.name || ''));
          const t = w.team ? RK.canonTeam(w.team) : null;
          return '<article class="qk-card rk-aw" style="--tc:' + esc(t ? U.tcol(t) : 'var(--signal)') + '"><div class="qk-card-body"><div class="qk-kicker">' + esc(a.name) + '</div>' +
            '<div class="rk-aw-w">' + (t ? QK.teamMark(U.team(t), 'sm') : '') + '<b class="' + QK.longName(w.name || '', 16).trim() + '">' + esc(w.name || '') + '</b></div>' +
            '<div class="rk-aw-s">' + esc(AWARD_WHAT[a.key] || a.desc || '') + (isNum(w.value) ? ' · ' + esc(w.value) : '') + '</div>' +
            (top ? '<div class="rk-aw-o">' + (same ? QK.tag('Top of our board too', 'signal') : 'Top of our board: <b>' + esc(top.name || '') + '</b>' + (isNum(top.value) ? ' (' + esc(Number.isInteger(top.value) ? top.value : U.f(top.value, 2)) + ')' : '')) + '</div>' : '') +
            '</div></article>';
        }).join('') + '</div></section>';
    }
    /* 5. leaders */
    const SL = (hist.season_leaders || {})[String(S)] || null;
    if (SL) {
      const order = ['p', 'g', 'gar', 'ixg', 'xgf_pct', 'gsax', 'sv_pct'];
      const F = { xgf_pct: v => U.pct(v, 1), sv_pct: v => RK.fmtVal(v, '3'), gsax: v => U.signed(v, 1), gar: v => U.f(v, 1), ixg: v => U.f(v, 1) };
      const items = order.filter(k => SL[k]).map(k => { const x = SL[k]; return { sport: 'hockey', kicker: 'NHL · ' + RK.teamAbbr(x.team), title: x.label, name: x.name, value: (F[k] || (v => String(v)))(x.value), href: RK.playerHref(x.id), expl: '' }; }).slice(0, 5);
      el.querySelector('#rc-leaders').innerHTML = items.length ? QK.band(QK.sectionHead({ kicker: 'Season leaders', title: 'The ' + L + ' leaders', sub: 'The top name on each board, at the end of the regular season.', actions: '<a class="qk-more" href="#/scout?view=leaders&s=' + S + '">Every leader</a>' }) + QK.hotRow(items)) : '';
    }
    /* 6. our game forecasts that season */
    const fs = sch.filter(g => RK.isFinal(g) && g.model && isNum(g.model.p_home) && isNum(g.hs) && isNum(g.as) && g.hs !== g.as);
    if (fs.length > 50) {
      const reg = fs.filter(g => !RK.isPlayoffGame(g)), po = fs.filter(g => RK.isPlayoffGame(g));
      const rec = list => { let w = 0, e = 0; list.forEach(g => { const ph = g.model.p_home, fav = ph >= 0.5 ? 'h' : 'a'; e += Math.max(ph, 1 - ph); if ((fav === 'h') === (g.hs > g.as)) w++; }); return { n: list.length, w: w, e: e }; };
      const R = rec(reg), P = rec(po);
      el.querySelector('#rc-games').innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Game by game', title: 'How our game forecasts did', sub: 'Every game with our forecast made before it (walk-forward: ratings fitted on earlier games only). A favourite is the side we gave over 50%.' }) +
        QK.stats([{ label: 'Regular season', value: U.pct(R.w / R.n, 1), signal: true, sub: 'favourites won ' + QK.fmt.num(R.w) + ' of ' + QK.fmt.num(R.n) + ' games; we expected ' + U.pct(R.e / R.n, 1) },
          P.n ? { label: 'Playoffs', value: U.pct(P.w / P.n, 1), sub: 'favourites won ' + P.w + ' of ' + P.n + ' games; we expected ' + U.pct(P.e / P.n, 1) } : null,
        ].filter(Boolean)) + QK.explain('<b>Is that good?</b> Hockey favourites win about 55 to 60% of the time, and when the favourites win about as often as our chances said, the numbers mean what they say. The best call on a night still misses about 4 times in 10.') +
        '<p class="qk-sub" style="margin-top:12px"><a class="qk-link" href="#/model?tab=calibration">How we’re doing over every season →</a></p></section>';
    }
    RK.setMeta('Season recap');
  });
}

RK.recap = { render: render };
})(window.RK);
