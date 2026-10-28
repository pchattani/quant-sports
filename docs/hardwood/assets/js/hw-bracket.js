/* The Quant Hardwood — the real playoff bracket (round 9, 28 Oct 2026).
 *
 * season.json `postseason.series` (oddsmarkets/basketball/analytics/season.py postseason): every play-in and playoff
 * series played so far, each playoff series with `rnum` (its round, 1-based, from the bracket's depth), `round` (the
 * normalised name: First round ... NBA Finals / WNBA Finals), `conf`, `winner`, `best_of` and its games. A payload
 * built before the normalisation (no `rnum`) gets the same depth rule here, so every past season draws.
 *
 *   HW.bracket.rounds(season, L) -> { rounds: [{ k, name, series: [S] }], playin: [S], champion, runnerUp, final, n }
 *       S = { teams: [a, b], wins: { tid: n }, winner, games: [...], round, conf, rnum, best_of, summary, href }
 *   HW.bracket.html(L, S, season, o) -> the bracket as HTML (o: { compact, seeds: { tid: seed }, calls: { tid: p } })
 *   HW.bracket.seriesHref(L, S, a, b) -> '#/<L>/series/<a>-<b>?s=S' (the series page, hw-series.js)
 *   HW.bracket.find(season, a, b) -> the series of the two teams (playoffs first, then the play-in)
 *
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const esc = HW.esc, isNum = HW.isNum;

function key(t) { return (t || []).map(String).sort().join('|'); }
function firstDate(s) { return ((s.games || []).map(g => String(g.date || '')).sort()[0]) || ''; }
function nameOf(L, k, n) {
  const from = n - k;
  if (from <= 0) return (L === 'wnba' ? 'WNBA' : 'NBA') + ' Finals';
  const names = L === 'nba' ? ['Conference finals', 'Conference semi-finals', 'First round'] : (n >= 4 ? ['Semi-finals', 'Second round', 'First round'] : ['Semi-finals', 'First round']);
  return names[from - 1] || 'Round ' + k;
}

function rounds(season, L) {
  const ps = (season && season.postseason && season.postseason.series) || [];
  const fmt = (season && season.format) || {};
  const post = ps.filter(s => s.stype === 'post').map(s => Object.assign({}, s, { teams: (s.teams || []).map(String) }));
  const playin = ps.filter(s => s.stype === 'playin').map(s => Object.assign({}, s, { teams: (s.teams || []).map(String) }));
  if (!post.length && !playin.length) return null;
  post.sort((a, b) => firstDate(a).localeCompare(firstDate(b)));
  if (post.some(s => !isNum(s.rnum))) {
    const played = {};
    post.forEach(s => { s.rnum = 1 + Math.max.apply(null, s.teams.map(t => played[t] || 0).concat([0])); s.teams.forEach(t => { played[t] = (played[t] || 0) + 1; }); });
  }
  const n = Math.max.apply(null, [(fmt.rounds || []).length || 1].concat(post.map(s => s.rnum)));
  post.forEach(s => {
    if (!s.round || /playoff series/i.test(String(s.round)) || !isNum(s.rnum)) s.round = nameOf(L, s.rnum, n);
    if (!s.winner) {
      const later = s.teams.filter(t => post.some(o => o.rnum > s.rnum && o.teams.indexOf(t) >= 0));
      if (later.length === 1) s.winner = later[0];
      else if (/wins/i.test(String(s.summary || ''))) s.winner = s.teams.slice().sort((a, b) => ((s.wins || {})[b] || 0) - ((s.wins || {})[a] || 0))[0];
    }
  });
  playin.forEach(s => {
    const g = (s.games || [])[0] || {};
    if (!s.winner && g.status === 'post' && isNum(g.hs) && isNum(g.as)) s.winner = String(g.hs > g.as ? g.home : g.away);
  });
  const by = {};
  post.forEach(s => { (by[s.rnum] || (by[s.rnum] = [])).push(s); });
  const ks = Object.keys(by).map(Number).sort((a, b) => a - b);
  /* order each round along the bracket: from the latest round back, each series' feeders under it (top team first) */
  const last = ks[ks.length - 1];
  const order = {};
  if (last) {
    order[last] = by[last].slice().sort((a, b) => String(a.conf || '').localeCompare(String(b.conf || '')));
    for (let k = last - 1; k >= 1; k--) {
      const out = [];
      (order[k + 1] || []).forEach(p => p.teams.forEach(t => { const c = (by[k] || []).find(s => s.teams.indexOf(t) >= 0 && out.indexOf(s) < 0); if (c) out.push(c); }));
      (by[k] || []).slice().sort((a, b) => String(a.conf || '').localeCompare(String(b.conf || ''))).forEach(s => { if (out.indexOf(s) < 0) out.push(s); });
      order[k] = out;
    }
  }
  const finalS = last === n ? (by[last] || [])[0] : null;
  const champion = finalS && finalS.winner ? finalS.winner : null;
  return {
    n: n, playin: playin, final: finalS, champion: champion,
    runnerUp: champion ? finalS.teams.filter(t => t !== champion)[0] : null,
    rounds: ks.map(k => ({ k: k, name: (order[k][0] || {}).round || nameOf(L, k, n), series: order[k] }))
  };
}

function seriesHref(L, S, a, b) { return '#/' + L + '/series/' + [a, b].map(String).sort().join('-') + (S && Number(S) !== HW.currentSeason(L) ? '?s=' + S : ''); }

function find(season, a, b) {
  const R = rounds(season, (season && season.league) || HW.state.league);
  if (!R) return null;
  const k = key([a, b]);
  for (let i = 0; i < R.rounds.length; i++) { const s = R.rounds[i].series.find(x => key(x.teams) === k); if (s) return s; }
  return R.playin.find(x => key(x.teams) === k) || null;
}

/* the summary line of a series: "BOS win 4-2", "Tied 2-2", "NYK lead 3-1" */
function line(L, s) {
  const w = s.wins || {}, t = s.teams;
  const a = w[t[0]] || 0, b = w[t[1]] || 0;
  if (s.winner) { const lo = s.teams.filter(x => x !== s.winner)[0]; return HW.teamAbbr(L, s.winner) + ' win ' + (w[s.winner] || 0) + '-' + (w[lo] || 0); }
  if (a === b) return a ? 'Tied ' + a + '-' + b : 'Not started';
  const lead = a > b ? t[0] : t[1];
  return HW.teamAbbr(L, lead) + ' lead ' + Math.max(a, b) + '-' + Math.min(a, b);
}

function box(L, S, s, o) {
  const seeds = o.seeds || {}, w = s.wins || {};
  const ordered = s.teams.slice().sort((a, b) => (isNum(seeds[a]) ? seeds[a] : 99) - (isNum(seeds[b]) ? seeds[b] : 99));
  const row = t => {
    const lost = s.winner && s.winner !== t;
    const won = s.winner === t;
    const col = HW.teamColourRaw(L, t) || QK.cssVar('--slate');
    return '<div class="hw-brs-t' + (lost ? ' out' : '') + (won ? ' won' : '') + '"><i style="background:' + esc(col) + '" aria-hidden="true"></i>' +
      '<span class="sd">' + (isNum(seeds[t]) ? seeds[t] : '') + '</span>' +
      '<span class="nm">' + esc(o.compact ? HW.teamAbbr(L, t) : HW.teamShort(L, t)) + '</span>' +
      '<b class="w">' + (s.stype === 'playin' ? (((s.games || [])[0] || {})[String(((s.games || [])[0] || {}).home) === t ? 'hs' : 'as'] || '') : (w[t] || 0)) + '</b></div>';
  };
  const call = o.calls && s.stype !== 'playin' ? o.calls[key(s.teams)] : null;
  return '<a class="hw-brs' + (s.winner ? ' done' : '') + '" href="' + esc(seriesHref(L, S, s.teams[0], s.teams[1])) + '" aria-label="' + esc(HW.teamName(L, s.teams[0]) + ' v ' + HW.teamName(L, s.teams[1]) + ': ' + line(L, s)) + '">' +
    ordered.map(row).join('') + '<span class="hw-brs-n">' + esc(s.stype === 'playin' ? 'Play-in' : line(L, s)) + (call ? ' · ' + esc(call) : '') + '</span></a>';
}

function html(L, S, season, o) {
  o = o || {};
  const R = rounds(season, L);
  if (!R) return '';
  if (!o.seeds) {
    const st = (season && season.standings) || {}, seeds = {};
    Object.keys(st).forEach(c => (st[c] || []).forEach((r, i) => { seeds[String(r.team)] = isNum(r.seed) ? r.seed : i + 1; }));
    o.seeds = seeds;
  }
  const cols = [];
  if (R.playin.length && o.playin !== false) cols.push('<div class="hw-brr hw-brr-pi"><div class="hw-brr-h">Play-in</div><div class="hw-brr-b">' + R.playin.map(s => box(L, S, s, Object.assign({}, o, { compact: true }))).join('') + '</div></div>');
  R.rounds.forEach(r => cols.push('<div class="hw-brr"><div class="hw-brr-h">' + esc(r.name) + (r.series[0] && r.series[0].best_of ? ' <small>best of ' + r.series[0].best_of + '</small>' : '') + '</div><div class="hw-brr-b">' + r.series.map(s => box(L, S, s, o)).join('') + '</div></div>'));
  for (let k = (R.rounds.length ? R.rounds[R.rounds.length - 1].k : 0) + 1; k <= R.n; k++) cols.push('<div class="hw-brr"><div class="hw-brr-h">' + esc(nameOf(L, k, R.n)) + '</div><div class="hw-brr-b"><div class="hw-brs tbd"><span class="hw-brs-n">To be decided</span></div></div></div>');
  if (R.champion) {
    const bl = QK.color.block(HW.teamColourRaw(L, R.champion));
    cols.push('<div class="hw-brr hw-brr-ch"><div class="hw-brr-h">Champion</div><div class="hw-brr-b"><a class="hw-brch" href="' + esc(HW.teamHref(L, R.champion, S)) + '" style="--tc:' + esc(bl.bg) + ';--te:' + esc(bl.edge || bl.bg) + '">' +
      '<span class="k">' + esc(HW.seasonLabel(L, S)) + '</span><b>' + esc(HW.teamName(L, R.champion)) + '</b></a></div></div>');
  }
  return '<div class="hw-br-wrap"><div class="hw-br' + (o.compact ? ' compact' : '') + '" style="--cols:' + cols.length + '">' + cols.join('') + '</div></div>';
}

HW.bracket = { rounds: rounds, html: html, seriesHref: seriesHref, find: find, line: line, key: key };
})(window.HW);
