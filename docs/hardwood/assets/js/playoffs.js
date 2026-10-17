/* The Quant Hardwood — playoffs (#/<L>/playoffs).
 *
 *   bracket: per round, the most likely matchups (projected) or the actual series once set, each with
 *            the chance the matchup happens and the home-court team's series win probability; series
 *            scores from the game cards when the playoffs are live;
 *   p_reach: each team's chance of reaching every round and winning the title;
 *   champion banner for finished seasons.
 *
 * Reads <L>/<S>/season.json (sim, bracket, standings) and index.json game cards. */
(function (HW) {
'use strict';

const esc = HW.esc;
const ROUND_LABEL = { r1: 'First round', semis: 'Conference semis', conf_finals: 'Conference finals', finals: 'Finals', playin: 'Play-in', qf: 'Quarter-finals', sf: 'Semi-finals' };

function roundLabel(L, r, n, i) {
  if (L === 'wnba' && r === 'semis') return 'Semi-finals';
  if (ROUND_LABEL[r]) return ROUND_LABEL[r];
  return i === n - 1 ? 'Finals' : 'Round ' + (i + 1);
}

/* Greedy: the most likely matchups with no team repeated, `count` of them. */
function likely(matchups, count) {
  const used = {}, out = [];
  (matchups || []).slice().sort((a, b) => (b.p || 0) - (a.p || 0)).forEach(m => {
    if (out.length >= count) return;
    const a = String(m.home_court), b = String(m.other);
    if (used[a] || used[b]) return;
    used[a] = used[b] = 1;
    out.push(m);
  });
  return out;
}

/* Series state from game cards: {key "a|b": {wins: {tid: n}, summary}}. */
function seriesFromCards(cards) {
  const out = {};
  (cards || []).forEach(g => {
    if (!g || !g.series) return;
    const k = [String(g.home), String(g.away)].sort().join('|');
    const o = out[k] || (out[k] = { wins: {}, summary: null });
    if (g.series.summary) o.summary = g.series.summary;
    if (g.series.wins && typeof g.series.wins === 'object') Object.assign(o.wins, g.series.wins);
  });
  return out;
}

function seedOf(season) {
  const out = {};
  const st = (season && season.standings) || {};
  Object.keys(st).forEach(c => (st[c] || []).forEach((r, i) => { out[String(r.team)] = r.seed || i + 1; }));
  return out;
}

function seriesBox(L, m, seeds, live) {
  const a = String(m.home_court), b = String(m.other);
  const pa = HW.isNum(m.p_home_court_wins) ? m.p_home_court_wins : null;
  const set = (m.p || 0) >= 0.999;
  const st = live[[a, b].sort().join('|')];
  const wa = st && HW.isNum(st.wins[a]) ? st.wins[a] : null, wb = st && HW.isNum(st.wins[b]) ? st.wins[b] : null;
  const decided = pa !== null && (pa >= 0.9999 || pa <= 0.0001);
  const row = (t, p, w, out) => '<div class="br-team' + (out ? ' out' : '') + '">' + HW.teamBar(L, t) +
    '<span><span class="br-seed">' + (seeds[t] || '') + '</span>' + HW.teamLink(L, t, { short: true, bar: false }) + '</span>' +
    '<span class="br-v">' + (w !== null ? w : (p !== null ? HW.pct(p, 0) : '')) + '</span></div>';
  return '<div class="br-series' + (decided ? ' done' : '') + '">' +
    row(a, pa, wa, decided && pa <= 0.0001) + row(b, pa === null ? null : 1 - pa, wb, decided && pa >= 0.9999) +
    '<div class="br-note">' + (set ? (st && st.summary ? esc(st.summary) : 'Series set') + (pa !== null && !decided ? ' · ' + esc(HW.teamAbbr(L, pa >= 0.5 ? a : b)) + ' ' + HW.pct(Math.max(pa, 1 - pa), 0) + ' to win' : '')
      : 'Matchup in ' + HW.pct(m.p, 0) + ' of simulations') + '</div></div>';
}

function render(el, params) {
  const L = params.league, S = params.season;
  const info = HW.leagueInfo(L);
  const isCurrent = S === HW.currentSeason(L);
  el.innerHTML = HW.pageHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S) + ' playoffs', 'Bracket, series odds and each team’s path',
    '<a href="' + HW.seasonHref(L, S) + '">Season</a><a href="' + HW.href(L, 'markets', S) + '">Markets</a>') + '<div id="po-body"><div class="muted">Loading…</div></div>';
  return HW.loadAll([HW.path('season.json', L, S), HW.lpath('history.json', L)]).then(arr => {
    if (!el.isConnected) return;
    const season = arr[0], hist = HW.ok(arr[1]) ? arr[1] : null;
    const body = document.getElementById('po-body');
    let html = '';
    const hrow = hist && (hist.seasons || []).find(x => Number(x.season) === Number(S));
    const champ = hrow ? hrow.champion : ((info.champions || []).find(c => Number(c[0]) === Number(S)) || [])[1];
    if (champ && (!isCurrent || info.phase === 'offseason')) {
      html += '<div class="champ-banner"><div><div class="cb-k">Champion</div><div class="cb-v">' + (HW.NAMES[L].teams[String(champ)] ? HW.teamLink(L, champ) : esc(champ)) + '</div></div>' +
        (hrow && hrow.runner_up ? '<div><div class="cb-k">Runner-up</div><div>' + (HW.NAMES[L].teams[String(hrow.runner_up)] ? HW.teamLink(L, hrow.runner_up) : esc(hrow.runner_up)) + '</div></div>' : '') +
        (hrow && hrow.finals_mvp ? '<div><div class="cb-k">Finals MVP</div><div>' + (HW.NAMES[L].players[String(hrow.finals_mvp)] ? HW.playerLink(L, hrow.finals_mvp) : esc(hrow.finals_mvp)) + '</div></div>' : '') + '</div>';
    }
    if (!HW.ok(season)) { body.innerHTML = html + HW.card('Playoffs', '', HW.notBuilt('The season model', season)); return; }
    const sim = HW.simTeams(season);
    const br = season.bracket || {};
    const rounds = br.rounds || [];
    const seeds = seedOf(season);
    const cards = isCurrent ? (info.last_games || []).concat(info.today || [], info.next_games || []) : [];
    const live = seriesFromCards(cards);
    if (rounds.length && br.matchups) {
      const n = rounds.length;
      const groups = Object.keys(br.groups || {});
      const slots = br.slots || [];
      const posOf = t => {
        const gi = Math.max(0, groups.findIndex(g => (br.groups[g] || []).map(String).indexOf(String(t)) >= 0));
        const si = slots.indexOf(seeds[String(t)]);
        return gi * 100 + (si < 0 ? 50 : si);
      };
      const slotKey = m => Math.min(posOf(m.home_court), posOf(m.other));
      const cols = rounds.map((r, i) => {
        const count = Math.pow(2, n - 1 - i);
        const ms = likely(br.matchups[r] || [], count).sort((x, y) => slotKey(x) - slotKey(y));
        return '<div class="br-round"><div class="br-title">' + esc(roundLabel(L, r, n, i)) + (br.series && br.series[i] ? ' · best of ' + br.series[i] : '') + '</div>' +
          (ms.length ? ms.map(m => seriesBox(L, m, seeds, live)).join('') : '<div class="muted-inline" style="font-size:0.78rem">To be decided</div>') + '</div>';
      });
      const champs = Object.keys(sim).filter(t => (sim[t].p_title || 0) > 0).sort((a, b) => sim[b].p_title - sim[a].p_title).slice(0, 4);
      cols.push('<div class="br-round"><div class="br-title">Champion</div>' + champs.map(t => '<div class="br-series"><div class="br-team">' + HW.teamBar(L, t) + '<span>' + HW.teamLink(L, t, { short: true, bar: false }) + '</span><span class="br-v">' + HW.pct(sim[t].p_title, 0) + '</span></div></div>').join('') + '</div>');
      html += HW.card('Bracket', 'the most likely matchups until the series are set; percentages are series win chances',
        '<div class="bracket-wrap"><div class="bracket">' + cols.join('') + '</div></div>' +
        '<div class="section-note">Before a series is set, each box shows the most likely pairing for that slot and how often it came up in the simulations. ' +
        (br.groups && Object.keys(br.groups).length > 1 ? 'Seeding is by conference.' : 'Seeding is league-wide.') + '</div>');
    } else {
      html += HW.card('Bracket', '', HW.muted('The bracket appears once the playoff format and seeds can be simulated.'));
    }
    // p_reach table
    const ids = Object.keys(sim).filter(t => sim[t].p_reach && Object.keys(sim[t].p_reach).length);
    if (ids.length) {
      const rk = rounds.length ? rounds : Object.keys(sim[ids[0]].p_reach);
      ids.sort((a, b) => (sim[b].p_title || 0) - (sim[a].p_title || 0) || (sim[b].p_playoffs || 0) - (sim[a].p_playoffs || 0));
      const shown = ids.filter(t => (sim[t].p_playoffs || 0) > 0.0005 || (sim[t].p_playin || 0) > 0.0005);
      const cols = [{ label: 'Playoffs', title: 'Reach the playoffs proper' }].concat(rk.slice(1).map((r, i) => ({ label: 'Reach ' + roundLabel(L, r, rk.length, i + 1).replace('Conference ', 'conf. ') }))).concat([{ label: 'Title' }]);
      html += HW.card('Path to the title', 'probability of reaching each round', HW.charts.heatTable({
        cols: cols, scale: 'seq', max: 1, corner: 'Team',
        rows: shown.map(t => ({ label: HW.teamLink(L, t), values: [sim[t].p_playoffs].concat(rk.slice(1).map(r => sim[t].p_reach[r])).concat([sim[t].p_title]) })),
        fmt: v => (v >= 0.995 ? '✓' : v < 0.005 ? (v > 0 ? '<1' : '–') : Math.round(v * 100) + '')
      }) + '<div class="section-note">Percent. ✓ = reached (or certain).</div>');
    }
    // Series in progress / recent playoff games
    const po = cards.filter(g => g.stype === 'post' || g.series);
    if (po.length) {
      html += HW.card('Playoff games', 'latest and upcoming', '<div class="gc-grid">' + po.slice().sort((a, b) => String(a.date).localeCompare(String(b.date))).map(g => HW.gameCard(g, { league: L, date: true })).join('') + '</div>');
    }
    body.innerHTML = html;
    HW.setMeta(season.sim && season.sim.n_sims ? HW.num(season.sim.n_sims, 0) + ' simulations' : '');
  });
}

HW.route('playoffs', render);
})(window.HW);
