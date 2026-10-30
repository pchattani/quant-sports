/* The Quant Hardwood — the past-season recap (round 9, 28 Oct 2026). A finished season reads as a recap, never as an
 * empty current-season template:
 *   - the champion, with the Finals result and the Finals MVP (history.json);
 *   - the final bracket with every series score (hw-bracket.js, season.json postseason);
 *   - final standings with seeds and the flags (z top seed, x playoffs, p play-in, e out; HW.recap.flags);
 *   - the award winners against our chance at the season's end (awards.json winner and model);
 *   - our calls against what happened: the chance our season simulation gave the eventual champion before the season
 *     and at each checkpoint of the walk-forward test (calibration.json season_sim_runs: no look-ahead, each run sees only
 *     the games played by then).
 *   HW.recap.flags(season) -> { tid: 'z' | 'x' | 'p' | 'e' }
 *   HW.recap.fill(host, L, S, season, awards, hist) (renders, async)
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const CP = { 0: 'Before the season', 0.25: 'A quarter in', 0.5: 'Halfway', 0.75: 'Three quarters in', 1: 'Before the playoffs' };
const FLAG_TIP = { z: 'Top seed in the conference', x: 'Made the playoffs', p: 'Lost in the play-in', e: 'Missed the postseason' };

function flags(season) {
  const out = {};
  const ps = (season && season.postseason && season.postseason.series) || [];
  if (!ps.length) return out;
  const po = {}, pin = {};
  ps.forEach(s => (s.teams || []).forEach(t => { if (s.stype === 'post') po[String(t)] = 1; else pin[String(t)] = 1; }));
  const st = (season && season.standings) || {};
  Object.keys(st).forEach(c => (st[c] || []).forEach((r, i) => {
    const t = String(r.team), seed = isNum(r.seed) ? r.seed : i + 1;
    out[t] = po[t] ? (seed === 1 ? 'z' : 'x') : pin[t] ? 'p' : 'e';
  }));
  return out;
}
function flagHTML(f) { return f ? '<span class="qk-badge' + (f === 'z' || f === 'x' ? ' accent' : '') + '" data-tip="' + esc(FLAG_TIP[f]) + '">' + f + '</span>' : ''; }

function fill(host, L, S, season, awards, hist) {
  if (!host) return Promise.resolve();
  const R = HW.bracket ? HW.bracket.rounds(season, L) : null;
  const hrow = hist ? (hist.seasons || []).find(x => Number(x.season) === Number(S)) : null;
  const champ = (R && R.champion) || (hrow && hrow.champion ? String(hrow.champion) : null);
  if (!champ) { host.innerHTML = ''; return Promise.resolve(); }
  const fin = R && R.final;
  const ru = (R && R.runnerUp) || (hrow && hrow.runner_up ? String(hrow.runner_up) : null);
  const w = fin ? fin.wins || {} : {};
  const score = fin && ru ? (w[champ] || 0) + '-' + (w[ru] || 0) : '';
  const fmvp = hrow && hrow.finals_mvp ? (HW.NAMES[L].players[String(hrow.finals_mvp)] ? HW.playerName(L, hrow.finals_mvp) : String(hrow.finals_mvp)) : '';
  /* round 11: the kit's champion hero (QK.champHero): the Finals result, each game as a chip, the Finals MVP */
  const LGN = L === 'wnba' ? 'WNBA' : 'NBA';
  const games = ((fin && fin.games) || []).filter(g => isNum(g.hs) && isNum(g.as)).map((g, i) => {
    const home = String(g.home) === champ, a = home ? g.hs : g.as, b = home ? g.as : g.hs;
    return { label: 'G' + (i + 1), score: a + '–' + b, won: a > b, sub: (home ? 'home' : 'away') + (g.date ? ' · ' + HW.fmtDate(g.date, { year: false }) : ''), href: g.id ? HW.gameHref(L, g.id, S) : null };
  });
  const t = U.team(L, champ) || {};
  let h = '<section class="qk-section">' + QK.sectionHead({ kicker: 'How it finished', title: 'The ' + HW.teamShort(L, champ) + ' win it all', sub: HW.leagueName(L) + ' ' + HW.seasonLabel(L, S) + ': the champion, every series, the awards and how our numbers called it.' }) +
    QK.champHero({ kicker: HW.seasonLabel(L, S) + ' ' + LGN + ' champions', name: HW.teamName(L, champ), href: HW.teamHref(L, champ, S), team: { abbr: HW.teamAbbr(L, champ), colour: HW.teamColourRaw(L, champ) || t.colour },
      headline: ru ? 'Beat the ' + HW.teamName(L, ru) + (score ? ' ' + score.replace('-', '–') : '') + ' in the ' + LGN + ' Finals.' : '', games: games,
      stats: fmvp ? [{ label: 'Finals MVP', value: fmvp, text: true }] : [] });
  if (R && R.rounds.length) h += '<div class="qk-card" style="margin-top:var(--sp-4)"><div class="qk-card-head"><div><div class="qk-card-title">The bracket</div><div class="qk-card-sub">Every series and its score; tap one for its games</div></div></div><div class="qk-card-body">' + HW.bracket.html(L, S, season, { playin: false, compact: true }) + '</div></div>';
  h += '<div class="qk-grid hw-sec"><div class="qk-span-6" id="rc-calls"></div><div class="qk-span-6" id="rc-awards"></div></div></section>';
  host.innerHTML = h;
  /* awards: the winner against our chance at the season's end */
  const aw = document.getElementById('rc-awards');
  const keys = awards ? (Array.isArray(awards.keys) ? awards.keys : Object.keys(awards.labels || {})).filter(k => awards[k] && awards[k].winner && (awards[k].winner.ids || []).length) : [];
  if (aw && keys.length) {
    const lab = awards.labels && !Array.isArray(awards.labels) ? awards.labels : {};
    const NAME = { mvp: 'MVP', roy: 'Rookie of the Year', dpoy: 'Defensive Player', sixth: 'Sixth Man', mip: 'Most Improved', clutch: 'Clutch Player' };
    const rows = keys.map(k => {
      const a = awards[k], m = a.model || {}, wid = String(a.winner.ids[0]), wn = (a.winner.names || [])[0] || HW.playerName(L, wid);
      const fav = Object.keys(m).sort((x, y) => m[y] - m[x])[0];
      return { k: k, award: NAME[k] || lab[k] || k.toUpperCase(), win: wn, wid: wid, p: isNum(m[wid]) ? m[wid] : null, fav: fav, hit: fav === wid };
    });
    const hits = rows.filter(r => r.hit).length;
    aw.innerHTML = U.card2('The awards, and our pick', 'Our favourite at the end of the regular season against the winner: ' + hits + ' of ' + rows.length + ' right',
      '<ul class="hw-list">' + rows.map(r => '<li><span class="hw-rc-aw">' + esc(r.award) + '</span>' + U.playerEnt(L, r.wid, r.win, null, null, S) +
        '<span class="v">' + (r.hit ? QK.tag('Our pick', 'signal') + ' ' + (isNum(r.p) ? U.pct(r.p) : '') : (r.fav ? '<span class="hw-quiet">ours: ' + esc(HW.playerName(L, r.fav)) + '; the winner at ' + (isNum(r.p) ? U.pct(r.p) : 'under 1%') + '</span>' : '')) + '</span></li>').join('') + '</ul>', { flush: true });
  } else if (aw) aw.remove();
  /* our calls: the champion's chance at each checkpoint of the walk-forward season test */
  return HW.load(L + '/calibration.json').then(cj => {
    const box = document.getElementById('rc-calls');
    if (!box) return;
    const runs = (U.ok(cj) ? cj.season_sim_runs || [] : []).filter(x => Number(x.season) === Number(S) && isNum(x.p_champion)).sort((a, b) => a.checkpoint - b.checkpoint);
    if (!runs.length) { box.innerHTML = U.card2('Our call', '', QK.empty('Not in the test', 'Our walk-forward season test does not cover ' + HW.seasonLabel(L, S) + '.')); return; }
    const nT = Object.keys((season && season.teams) || {}).length || 30;
    box.innerHTML = U.card2('Our calls against what happened', 'The chance our season simulation gave the ' + esc(HW.teamShort(L, champ)) + ' to win the title, using only the games played by then (an average team’s share is ' + U.pct(1 / nT) + ')',
      U.chart('rc-calls-c', 240, 'Our title chance for the champion through the season') +
      QK.note('Before the season we gave the ' + esc(HW.teamShort(L, champ)) + ' <b>' + U.pct(runs[0].p_champion) + '</b>' + (runs.length > 1 ? '; by ' + esc(CP[runs[runs.length - 1].checkpoint] || 'the last check').toLowerCase() + ', <b>' + U.pct(runs[runs.length - 1].p_champion) + '</b>' : '') + '. ' +
        (runs[0].p_champion >= 2 / nT ? 'A contender in our numbers from the start.' : 'Not one of our early favourites: a title from there is what a ' + U.pct(runs[0].p_champion) + ' chance looks like when it comes off.')));
    QKC.bar('#rc-calls-c', { cats: runs.map(x => CP[x.checkpoint] || Math.round(x.checkpoint * 100) + '% in'), series: [{ name: 'Our title chance', data: runs.map(x => Math.round(x.p_champion * 1000) / 10), color: 'model' }], labels: true, fmt: v => v + '%', valName: 'Our title chance (%)', catName: 'When' });
  });
}

HW.recap = { flags: flags, flagHTML: flagHTML, fill: fill };
})(window.HW);
