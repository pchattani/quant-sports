/* The Quant Bullpen — Overview (#/ and #/<L>), the kit v4 "Broadcast" landing page (docs/rink/assets/js/rk-overview.js
 * is the reference).
 *
 *   1. the intro band: what the site covers and how to use it, with three quick links (Games, Standings or the
 *      bracket, Players);
 *   2. "This week in MLB" (the current MLB season): the stage (the week of the regular season, or the postseason
 *      round and the series still alive), then the top lines from index.json "digest" (scripts/build_bullpen.py with
 *      oddsmarkets/common/digest.py): the biggest postseason or World Series chance mover, the upset of the week,
 *      the team of the week and the other games that matter;
 *   3. the game that matters most, by significance (digest.featured: oddsmarkets/common/featured.py), as the
 *      diagonal split hero labelled "Live now", "Tonight" (only when it truly is tonight in the reader's time),
 *      "Today", "Tomorrow" or the weekday; with nothing big on, the World Series race instead;
 *   4. "N games. Our calls." (our chance, the market small and grey beside it); the black power list (Who's hot);
 *      round 6, the fan modules: "Breakout watch" (the biggest jumps in Bullpen WAR from last season), "Best player
 *      nobody talks about" (a spotlight with percentiles and his WAR by season), "Who's for real?" beside the
 *      biggest climb and fall from last season; "What's that number?"; "Who wins the World Series?" with the
 *      bracket; the strength map; the standings; the leader boards; a small link to "How we're doing" (the Model
 *      page holds our record and calibration now).
 *
 * Reads index.json (cards, postseason, leaders, teams, digest; levels.aaa for Triple-A), <L>/<S>/season.json
 * (standings, ratings, simulation); lazily, the top hitters' and pitchers' player files and last season's
 * season.json for the fan modules. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const U = BP.ui;

const PHASE = { preseason: 'Preseason', regular: 'Regular season', postseason: 'Postseason', offseason: 'Off-season', complete: 'Season complete' };
/* World Series chances: ours only (the postseason paths, else index teams); no market on the overview. */
function titleRows(idx, post) {
  const pt = (post && post.teams) || {};
  const it = idx.teams || {};
  const ids = Object.keys(Object.keys(pt).length ? pt : it);
  return ids.map(t => {
    const p = isNum((pt[t] || {}).p_ws) ? pt[t].p_ws : (it[t] || {}).p_ws;
    return { t: t, p: p };
  }).filter(r => isNum(r.p) && r.p > 0.0005).sort((a, b) => b.p - a.p);
}
/* Who's hot: one card per leaderboard, the leader with the next best behind. */
const HOT = [['h_war', 'Best hitter', 'Bullpen WAR', 'Wins above a replacement player: batting, running, fielding and position.', v => BP.num(v, 1), 'hitter'],
  ['h_hr', 'Most home runs', 'home runs', 'The season total so far.', v => String(v), 'hitter'],
  ['h_xwoba_plus', 'Best contact', 'xwOBA+', 'Our expected wOBA from how hard and at what angle the ball was hit: .320 is about average.', v => BP.fmtAvg(v), 'hitter'],
  ['p_war', 'Best pitcher', 'Bullpen WAR', 'Wins above a replacement-level arm, from the runs allowed.', v => BP.num(v, 1), 'pitcher'],
  ['p_stuff_plus', 'Nastiest stuff', 'Stuff+', 'The physics of the pitches alone: 100 is league average, 110 is excellent.', v => String(Math.round(v)), 'pitcher']];
function hotItems(lead, L) {
  return HOT.filter(x => (lead[x[0]] || []).length).map(x => {
    const r = lead[x[0]][0], r2 = lead[x[0]][1];
    const tm = (BP.player(r[0]) || {}).team;
    return { sport: 'baseball', kicker: BP.levelName(L) + (tm ? ' · ' + BP.teamAbbr(tm) : ''), title: x[1], name: BP.playerName(r[0]), value: x[4](r[1]), unit: x[2], next: r2 ? { name: BP.playerName(r2[0]), value: x[4](r2[1]) } : null, expl: x[3],
      href: BP.playerHref(r[0], { level: L, role: x[5] }) };
  });
}

BP.ui.hotItems = hotItems;   // leaders.js draws the same power list

/* ── the landing top (the same shape on every sport overview) ──────────────────────────────────────────────── */
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
/* "Live now" | "Tonight" | "Today" | "Tomorrow" | the weekday | the date, in the reader's own time (QK.now()). */
function whenLabel(g) {
  if (!g) return '';
  if (g.status === 'live') return 'Live now';
  if (g.status === 'final') return 'Final';
  const d = new Date(g.start), now = new Date(QK.now());
  if (isNaN(d)) return '';
  if (g.status === 'pre' && d.getTime() <= now.getTime() && !QK.awaiting(g)) return 'Under way';
  const d0 = x => { const y = new Date(x.getTime()); y.setHours(0, 0, 0, 0); return y.getTime(); };
  const n = Math.round((d0(d) - d0(now)) / 864e5);
  if (n === 0) return d.getHours() >= 17 ? 'Tonight' : 'Today';
  if (n === 1) return 'Tomorrow';
  if (n > 1 && n < 7) return d.toLocaleDateString('en-GB', { weekday: 'long' });
  return QK.fmt.date(g.start);
}
function intro(o) {
  return '<section class="ql-intro" aria-label="About this site"><div class="ql-intro-l"><div class="qk-greet-date">' + esc(o.tag) + '</div>' +
    '<h1>' + esc(o.title) + '</h1><p>' + esc(o.lede) + '</p></div>' +
    '<nav class="ql-links" aria-label="Start here">' + o.links.map(l => '<a href="' + esc(l.href) + '"><b>' + esc(l.label) + '</b><span>' + esc(l.sub) + '</span></a>').join('') + '</nav></section>';
}
/* a date-only payload day ("2026-09-27") in en-GB without a time-zone shift */
const day = d => QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d);
const ptsOf = d => (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts';
const the = t => 'the ' + BP.teamShort(t);
const The = t => 'The ' + BP.teamShort(t);
/* "the Mariners lead 3–2" for a postseason series {teams, wins} */
function seriesState(s) {
  if (!s || !s.teams || !s.wins || s.wins.length !== 2) return '';
  const w = s.wins, t = s.teams;
  if (w[0] === w[1]) return 'level at ' + w[0] + '–' + w[1];
  const i = w[0] > w[1] ? 0 : 1;
  return the(t[i]) + ' lead ' + w[i] + '–' + w[1 - i];
}
function seriesFor(c, post) {
  const pair = [String(c.home), String(c.away)].sort().join('|');
  return ((post && post.series) || []).filter(s => (s.teams || []).map(String).sort().join('|') === pair)[0] || null;
}
/* Why the featured game: the shared rule's reasons (the series words replace "a semi-final"), then our numbers. */
function reasonsWhy(r, c, idx, post) {
  const pt = (post && post.teams) || {}, it = idx.teams || {};
  const ws = t => (isNum((pt[t] || {}).p_ws) ? pt[t].p_ws : (it[t] || {}).p_ws);
  const pp = t => (it[t] || {}).p_postseason;
  const ser = c.series ? seriesFor(c, post) : null;
  const lead = (r || []).filter(x => x && !(c.series && /^a (final|semi-final|quarter-final|play-off)$/.test(x))).join(' and ');
  const head = c.series ? BP.seriesText(c.series) + (ser && seriesState(ser) ? ', ' + seriesState(ser) : '') : '';
  const A = BP.teamAbbr(c.away), H = BP.teamAbbr(c.home);
  const nums = isNum(ws(c.away)) && isNum(ws(c.home)) && (ws(c.away) > 0.005 || ws(c.home) > 0.005) ? 'to win the World Series ' + A + ' ' + U.pct(ws(c.away)) + ', ' + H + ' ' + U.pct(ws(c.home))
    : isNum(pp(c.away)) && isNum(pp(c.home)) ? 'our postseason chances ' + A + ' ' + U.pct(pp(c.away)) + ', ' + H + ' ' + U.pct(pp(c.home)) : '';
  const parts = [head, lead ? lead.charAt(0).toUpperCase() + lead.slice(1) : ''].filter(Boolean).join('. ');
  return parts ? parts + (nums ? ': ' + nums : '') + '.' : (nums ? nums.charAt(0).toUpperCase() + nums.slice(1) + '.' : '');
}
/* The game that matters most, on the shared significance rule (featured.py rank_featured: the tier, the stage and
 * the series, the stakes in our simulations, the start time and hour, live-ness; closeness only a small bonus),
 * from index.json digest.featured: the first of "today" still upcoming or live at the reader's clock, else "week".
 * An older payload without it gets the old pick (live first, then the closest calls). */
function pickFeatured(idx, cards, post) {
  const by = {}, now = QK.now();
  cards.forEach(c => { by[c.gpk] = c; });
  /* a card still "pre" up to 4 h after its start is almost surely under way (statuses lag the hourly build): it stays the
     lead; past that it is waiting for its result (QK.awaiting) and is never featured */
  const ok = (c, hrs) => {
    if (!c || BP.isFinal(c) || (BP.notNeeded && BP.notNeeded(c)) || QK.awaiting(BP.kitGame(c, 'mlb'))) return false;
    const h = (Date.parse(c.start || c.date) - now) / 36e5;
    return BP.isLive(c) ? h > -10 : h > -4 && h < hrs;
  };
  const F = (idx.digest || {}).featured;
  if (F && (F.today || F.week)) {
    const T = (F.today || []).filter(f => ok(by[f.id], 24));
    const f = T[0] || (F.week && ok(by[F.week.id], 24 * 7) ? F.week : null);
    if (!f) return { c: null, rest: [] };
    return { c: by[f.id], why: reasonsWhy(f.why, by[f.id], idx, post), week: !T.length, rest: T.slice(1).map(x => by[x.id]) };
  }
  const sc = cards.filter(c => ok(c, 48)).map(c => [QK.watchScore(BP.kitGame(c, 'mlb')), c]).filter(x => x[0] > -1e8).sort((a, b) => b[0] - a[0]);
  return sc.length ? { c: sc[0][1], why: reasonsWhy([], sc[0][1], idx, post), rest: sc.slice(1).map(x => x[1]) } : null;
}
/* On pace for history (round 9, Phase 4): data/mlb/<S>/chases.json (analytics/records.py): each stat's season leader
   against the single-season record and the top 15 since 1901; the four closest to the record, as story cards with the
   pace bar. In season "on pace for" (162 games at the same rate); once the regular season is over, "how close they came". */
function chaseFill(host, L, S) {
  if (!host) return;
  BP.loadYear('chases.json', L, S).then(c => {
    if (!host.isConnected || !BP.ok(c) || !c.stats) return;
    const items = Object.keys(c.stats).map(k => { const x = c.stats[k], ld = (x.leaders || [])[0]; return ld ? { k: k, x: x, ld: ld, r: ld.pace / x.record[2] } : null; })
      .filter(Boolean).sort((a, b) => (a.ld.rank || 99) - (b.ld.rank || 99) || b.r - a.r).slice(0, 4);
    if (!items.length) return;
    const fin = !!c.final;
    host.innerHTML = QK.sectionHead({ kicker: fin ? 'Record watch' : 'On pace for history', title: fin ? 'How close they came' : 'Chasing the record books',
      sub: (fin ? 'The season’s leaders against the single-season records since 1901 (American and National League).' : 'The season’s leaders at their pace over 162 games, against the single-season records since 1901.') + ' Records from the Lahman Baseball Database.' }) +
      QK.storyCards(items.map(it => {
        const ld = it.ld, rec = it.x.record, nm = BP.playerName(ld.pid) || ld.name;
        const where = ld.rank ? (fin ? 'The ' + ordinal(ld.rank) + '-best total since 1901. ' : 'That pace would be the ' + ordinal(ld.rank) + '-best since 1901. ') : (fin ? 'Short of the top 15 since 1901 (' + it.x.list_min + '). ' : 'Off the top-15 pace (' + it.x.list_min + '). ');
        return { kicker: it.x.label, name: nm, sub: BP.teamAbbr(ld.team), value: fin ? ld.value : Math.round(ld.pace), unit: fin ? it.x.label.toLowerCase() : 'on pace', colour: U.raw(ld.team),
          href: BP.playerHref(ld.pid, { level: L, role: it.x.kind === 'pitcher' ? 'pitcher' : 'hitter' }),
          pace: { now: ld.value, pace: ld.pace, target: rec[2], max: Math.max(rec[2], ld.pace) * 1.05, label: 'Record ' + rec[2] + ' · ' + rec[0] + ', ' + rec[1], fmt: v => String(Math.round(v)) },
          text: where + (ld.behind > 0 ? Math.round(ld.behind) + ' short of ' + rec[0] + '’s ' + rec[2] + '.' : 'A new record.') };
      }), { cols: 4 });
  });
}
/* Hot and cold (round 9, Phase 4): data/<L>/<S>/form.json (analytics/form.py): each player's last 100 plate appearances
   (xwOBA+) or last 500 pitches (Pitching+) against their own season; the two ends of each list with the run as a spark. */
function formFill(host, L, S) {
  if (!host) return;
  BP.loadYear('form.json', L, S).then(f => {
    if (!host.isConnected || !BP.ok(f)) return;
    const H = f.hitters || {}, P = f.pitchers || {};
    if (!(H.hot || []).length && !(P.hot || []).length) return;
    const lb = (id, rows, pit) => {
      const node = host.querySelector('#' + id);
      if (!node || !rows.length) return;
      QK.leaderboard(node, { dense: true, columns: [{ key: 'name', label: pit ? 'Pitcher' : 'Hitter', type: 'entity', sub: 'sub', mark: r => U.team(r.team, L, S), href: r => BP.playerHref(r.pid, { level: L, role: pit ? 'pitcher' : 'hitter' }) },
        { key: 'spark', label: 'Recent run', type: 'spark' },
        { key: 'recent', label: pit ? 'Last 500 pitches' : 'Last 100 PA', num: true, fmt: v => (pit ? String(Math.round(v)) : BP.fmtAvg(v)) },
        { key: 'delta', label: 'v season', num: true, fmt: v => '<span class="' + (v > 0 ? 'edge-pos' : 'edge-neg') + '">' + (pit ? U.signed(v, 0) : (v >= 0 ? '+' : '−') + BP.fmtAvg(Math.abs(v)).replace(/^0/, '')) + '</span>' }],
      rows: rows.slice(0, 5).map(r => Object.assign({}, r, { sub: (r.pos || '') + ' · ' + BP.teamAbbr(r.team) + ' · season ' + (pit ? Math.round(r.season) : BP.fmtAvg(r.season)) })) });
    };
    host.innerHTML = QK.sectionHead({ kicker: 'Hot and cold', title: 'Who’s on a run, and who’s in a slump', sub: 'Each player against their own season: hitters on what their contact deserved over the last 100 plate appearances (xwOBA+), pitchers on Pitching+ over the last 500 pitches' + (f.asof ? ', to ' + BP.fmtDate(f.asof, { year: false }) : '') + '.' }) +
      '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Hot bats', 'xwOBA+, last 100 PA', '<div id="fm-hh"></div>', { flush: true }) + '</div><div class="qk-span-6">' + U.card2('Hot arms', 'Pitching+, last 500 pitches', '<div id="fm-ph"></div>', { flush: true }) + '</div>' +
      '<div class="qk-span-6">' + U.card2('Cold bats', 'the biggest drops from the season', '<div id="fm-hc"></div>', { flush: true }) + '</div><div class="qk-span-6">' + U.card2('Cold arms', 'the biggest drops from the season', '<div id="fm-pc"></div>', { flush: true }) + '</div></div>';
    lb('fm-hh', H.hot || [], false); lb('fm-ph', P.hot || [], true); lb('fm-hc', H.cold || [], false); lb('fm-pc', P.cold || [], true);
  });
}
/* Triple-A's lead (round 9): the finals (season.json postseason as played: the IL and PCL championship series and the
   national championship game) and the call-ups and top prospects (prospects.json: callups, ranked, mlb_eq). */
function aaaFill(el, post, L, S) {
  const fin = el.querySelector('#ov-aaa-fin'), up = el.querySelector('#ov-aaa-up');
  if (fin && post && (post.series || []).length) {
    const list = post.series || [];
    const ch = list.find(x => x.round === 'CH');
    const champ = post.champion;
    const line = x => { const w = x.winner, i = x.teams.indexOf(w), o = x.teams[1 - i]; return w ? { w: w, o: o, sc: x.wins[i] + '–' + x.wins[1 - i] } : null; };
    const g = ch && (ch.games || [])[0];
    const card = (x, big) => {
      const r = line(x);
      if (!r) return '';
      const last = x.games && x.games.length ? x.games[x.games.length - 1] : null;
      return '<div class="ov-fin' + (big ? ' big' : '') + '"><span class="qk-kicker">' + esc(x.round_name || '') + '</span>' +
        '<span class="ov-fin-w">' + U.teamEnt(r.w, L, S) + '</span><span class="ov-fin-sc num">' + esc(x.best_of > 1 ? r.sc : (isNum((x.score || [])[0]) ? x.score.join('–') : 'Won')) + '</span>' +
        '<span class="ov-fin-o">' + (x.best_of > 1 ? 'Series win' : 'One game') + ' over the ' + esc(BP.teamShort(r.o)) + (last ? ' · <a href="' + BP.gameHref(last, L, S) + '">' + (x.best_of > 1 ? 'Last game' : 'The game') + ' →</a>' : '') + '</span></div>';
    };
    fin.innerHTML = QK.sectionHead({ kicker: 'How it finished', title: champ ? 'The ' + BP.teamShort(champ) + ' are Triple-A champions' : 'The finals', sub: 'The International League and Pacific Coast League finals, then one game for the national title.', actions: g ? '<a class="qk-more" href="' + BP.gameHref(g, L, S) + '">The championship game</a>' : '' }) +
      '<div class="ov-fins">' + (ch ? card(ch, true) : '') + list.filter(x => x.round !== 'CH').map(x => card(x)).join('') + '</div>';
  }
  if (!up) return;
  BP.loadYear('prospects.json', L, S).then(d => {
    if (!up.isConnected || !BP.ok(d)) return;
    const P = d.players || {};
    const ups = (d.callups || Object.keys(P).filter(pid => (P[pid].mlb_this_season || 0) > 0 && isNum(P[pid].age) && P[pid].age < 25).sort((a, b) => P[b].mlb_this_season - P[a].mlb_this_season)).slice(0, 8);
    const hit = ((d.ranked || {}).hitters || []).slice(0, 5), pit = ((d.ranked || {}).pitchers || []).slice(0, 5);
    const ent = (pid, sub) => { const x = P[pid] || {}; return '<li>' + BP.playerLink(pid, { level: 'aaa', season: S, name: x.name, role: x.kind === 'pitcher' ? 'pitcher' : 'hitter' }) + '<span class="sb">' + esc(sub) + '</span></li>'; };
    const org = x => (x.parent ? BP.teamAbbr(x.parent) + ' · ' : '');
    let h = '';
    if (ups.length) h += QK.sectionHead({ kicker: 'Called up', title: 'Who made the jump', sub: 'Triple-A players who made their major-league debut this season, the most big-league time first.', actions: '<a class="qk-more" href="#/prospects">Every prospect</a>' }) +
      QK.storyCards(ups.map(pid => { const x = P[pid]; const pit = x.kind === 'pitcher'; return { kicker: (x.parent ? BP.teamShort(x.parent) : 'MLB') + ' · ' + (x.pos || (pit ? 'P' : '')), name: x.name, sub: 'age ' + Math.floor(x.age || 0),
        value: x.mlb_this_season, unit: pit ? 'MLB batters faced' : 'MLB plate appearances', href: BP.playerHref(pid, { level: 'mlb', role: pit ? 'pitcher' : 'hitter' }),
        text: pit ? 'Triple-A: ' + (isNum((x.aaa || {}).k_pct) ? U.pct(x.aaa.k_pct) + ' strikeouts, ' : '') + (isNum((x.aaa || {}).ra9) ? BP.num(x.aaa.ra9, 2) + ' runs a nine' : '') : 'Triple-A: ' + (isNum((x.aaa || {}).woba) ? 'wOBA ' + BP.fmtAvg(x.aaa.woba) : '') + (isNum((x.aaa || {}).hr) ? ', ' + x.aaa.hr + ' home runs' : '') }; }));
    if (hit.length || pit.length) h += '<div style="margin-top:var(--sp-5)">' + QK.sectionHead({ kicker: 'Top prospects', title: 'Ready for the majors?', sub: 'The best Triple-A lines translated to the major leagues: hitters by their MLB-equivalent wOBA, pitchers by strikeouts minus walks; 100 PA or batters faced or more.', tag: 'h3' }) +
      '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Hitters', 'MLB-equivalent wOBA', '<ol class="bp-list bp-lead ov-pros">' + hit.map(pid => ent(pid, org(P[pid]) + 'wOBA ' + BP.fmtAvg((P[pid].mlb_eq || {}).woba))).join('') + '</ol>') + '</div>' +
      '<div class="qk-span-6">' + U.card2('Pitchers', 'MLB-equivalent strikeouts minus walks', '<ol class="bp-list bp-lead ov-pros">' + pit.map(pid => ent(pid, org(P[pid]) + 'K−BB ' + U.pct((P[pid].mlb_eq || {}).k_bb_pct))).join('') + '</ol>') + '</div></div></div>';
    up.innerHTML = h;
  });
}
/* The recap of a finished season (round 9): the champion as the spotlight (our calls for them, the World Series), our
   favourite and how it went, and the award winners against our pre-vote calls (data/mlb/award_history.json). */
function recapFill(host, post, season, L, S, o) {
  if (!host) return;
  o = o || {};
  const TB = o.title && o.title.champion === post.champion ? o.title : null;   // digest.stage.title (this season): the games
  const champ = post.champion;
  const calls = (season && season.calls) || {};
  const pre = (calls.preplayoff || {}).p_ws || {}, first = (calls.first || {}).p_ws || {};
  const ranked = Object.keys(pre).sort((a, b) => pre[b] - pre[a]);
  const list = BP.charts.seriesList(post);
  const ws = list.find(x => x.rk === 'WS');
  const runner = ws ? ws.teams.find(t => t !== champ) : null;
  const wsW = ws ? (ws.teams[0] === champ ? ws.wins : [ws.wins[1], ws.wins[0]]) : null;
  const pt = (post.teams || {})[champ] || {};
  /* the champion's postseason record, every series */
  const rec = list.reduce((a, x) => { const i = x.teams.indexOf(champ); if (i < 0 || !x.wins) return a; return [a[0] + x.wins[i], a[1] + x.wins[1 - i]]; }, [0, 0]);
  let h = '';
  if (champ) {
    const t = U.team(champ, L, S);
    const fav = ranked[0];
    const hero = games => QK.champHero({ kicker: S + ' World Series champions', name: BP.teamName(champ), sub: [BP.teamInfo(champ).division, isNum(pt.seed) ? 'seed ' + pt.seed : '', (BP.RECORDS || {})[champ] ? (BP.RECORDS || {})[champ] + ' in the regular season' : ''].filter(Boolean).join(' · '),
      team: { name: t.name, abbr: t.abbr, colour: t.colour }, href: BP.teamHref(champ, L, S),
      headline: wsW ? 'Beat the ' + BP.teamName(runner) + ' ' + wsW[0] + '–' + wsW[1] + ' in the World Series' + (TB && TB.decided ? ', ' + day(TB.decided) : '') + '.' : '',
      games: games,
      stats: [isNum(pre[champ]) ? { label: 'Our chance before October', value: U.pct(pre[champ]), sub: ordinal(ranked.indexOf(champ) + 1) + ' of ' + ranked.length + ' clubs' } : null,
        isNum(first[champ]) ? { label: 'Our chance after week one', value: U.pct(first[champ]) } : null,
        { label: 'Postseason record', value: rec[0] + '–' + rec[1], sub: list.filter(x => BP.charts.winnerOf(x) === champ).length + ' series won' }].filter(Boolean),
      text: isNum(pre[champ]) ? 'We gave them ' + U.pct(pre[champ]) + ' on the eve of the postseason, ' + ordinal(ranked.indexOf(champ) + 1) + ' of the ' + ranked.length + ' clubs' +
        (fav && fav !== champ ? '; our favourite, the ' + BP.teamShort(fav) + ' at ' + U.pct(pre[fav]) + ', ' + (reachText(post, fav) || 'fell short') + '.' : ': our favourite, and they won it.') : '',
      links: [{ href: BP.ghref('postseason', S), text: 'The bracket' }, { href: BP.teamHref(champ, L, S), text: 'Team page' }, { href: '#/history', text: 'Every champion' }] });
    /* the World Series games, the champion's runs first: digest.stage.title (this season), else the schedule */
    const chips = gs => gs.map((g, i) => ({ label: 'G' + (i + 1), score: g.score[0] + '–' + g.score[1], won: g.score[0] > g.score[1], sub: (g.home ? 'home' : 'away') + (g.date ? ' · ' + day(g.date).replace(/^\w+ /, '') : ''), href: BP.gameHref(g.gpk, L, S) }));
    h += '<div id="ov-champ">' + hero(TB ? chips(TB.games || []) : []) + '</div>';
    if (!TB && ws && (ws.games || []).length) {
      BP.loadYear('schedule.json', L, S).then(sc => {
        const box = host.querySelector('#ov-champ');
        const by = {};
        ((sc && sc.games) || []).forEach(g => { if (g && g.gpk) by[String(g.gpk)] = g; });
        const gs = ws.games.map(id => by[String(id)]).filter(g => g && BP.isFinal(g) && isNum(g.hs)).map(g => { const home = String(g.home) === champ; return { gpk: g.gpk, date: String(g.date || '').slice(0, 10), home: home, score: home ? [g.hs, g.as] : [g.as, g.hs] }; });
        if (box && gs.length) box.innerHTML = hero(chips(gs));
      });
    }
  }
  /* how the title was won: our World Series chance for the champion (and the runner-up) day by day through October,
     from the race log; then our calls against what happened and the bracket as played (the Bracket page's pieces) */
  h += '<div id="ov-recap-won"></div>';
  if (ranked.length || list.length) {
    h += '<div style="margin-top:var(--sp-5)">' + QK.sectionHead({ kicker: 'The postseason', title: 'Our calls against what happened', tag: 'h3', sub: 'The World Series chance we gave each club on the eve of the postseason, beside how far it went, and the bracket as it was played.',
      actions: '<a class="qk-more" href="' + BP.ghref('postseason', S) + '">Every series</a>' }) +
      '<div class="qk-grid">' + (ranked.length ? '<div class="qk-span-12">' + U.card2('Our calls', 'Our World Series chance on ' + day((calls.preplayoff || {}).asof) + ', the champion in volt', '<div id="ov-recap-calls" class="qk-chart" style="--h:' + Math.max(300, 30 * ranked.length + 60) + 'px" role="img" aria-label="Our pre-postseason World Series chances against how far each club went"></div>') + '</div>' : '') +
      '<div class="qk-span-12">' + U.card2('The bracket', 'Seeds and every series score', '<div id="ov-recap-bk"></div>') + '</div></div></div>';
  }
  h += '<div id="ov-recap-aw"></div>';
  host.innerHTML = h;
  if (ranked.length && BP.recap && host.querySelector('#ov-recap-calls')) BP.recap.callsChart('#ov-recap-calls', post, calls);
  if (BP.charts.mlbBracket && host.querySelector('#ov-recap-bk')) BP.charts.mlbBracket(host.querySelector('#ov-recap-bk'), post, { level: L });
  if (champ) wonFill(host.querySelector('#ov-recap-won'), champ, runner, calls, L, S, pre[champ]);
  BP.load('mlb/award_history.json').then(ah => {
    const box = host.querySelector('#ov-recap-aw');
    const recs = ah && ah.ok !== false ? (ah.seasons || {})[String(S)] : null;
    if (!box || !recs) return;
    const keys = Object.keys(ah.labels || {}).filter(k => recs[k]);
    /* the votes come in November: until then the cards show our calls, never a blank winner */
    const voted = keys.some(k => (recs[k].winner || {}).name);
    box.innerHTML = '<div style="margin-top:var(--sp-5)">' + QK.sectionHead({ kicker: 'The awards', title: voted ? 'Who won, and what we said' : 'The award races: our calls', tag: 'h3',
      sub: voted ? 'The winners against our pre-vote calls, made from the full regular season with a model fitted only on earlier seasons.' : 'The winners are announced in November. Our calls from the full regular season, with a model fitted only on earlier seasons.',
      actions: '<a class="qk-more" href="#/awards?s=' + S + '">Every race</a>' }) +
      '<div class="ov-aw">' + keys.map(k => {
        const r = recs[k], w = r.winner || {}, pk = r.pick || {};
        if (!voted) return '<div class="ov-aw-c"><div class="qk-kicker">' + esc(ah.labels[k]) + '</div><div class="ov-aw-n">' + (pk.pid ? BP.playerLink(pk.pid, { level: L, season: S, name: pk.name }) : esc(pk.name || '—')) + '</div>' +
          '<div class="ov-aw-v num">' + (isNum(pk.p) ? U.pct(pk.p) : '—') + '</div><div class="ov-aw-s">Our pick, before the vote</div></div>';
        const hit = w.rank === 1;
        return '<div class="ov-aw-c' + (hit ? ' hit' : '') + '"><div class="qk-kicker">' + esc(ah.labels[k]) + '</div><div class="ov-aw-n">' + (w.pid ? BP.playerLink(w.pid, { level: L, season: S, name: w.name }) : esc(w.name || '—')) + '</div>' +
          '<div class="ov-aw-v num">' + (isNum(w.p) ? U.pct(w.p) : '—') + '</div><div class="ov-aw-s">' + (hit ? 'Our top pick' : 'Our pick: ' + esc(pk.name || '—') + (isNum(pk.p) ? ' (' + U.pct(pk.p) + ')' : '') + (w.rank ? '; the winner was our ' + ordinal(w.rank) : '')) + '</div></div>';
      }).join('') + '</div></div>';
  });
}
/* "How the title was won" (round 11): the champion's and the runner-up's World Series chance by day from the eve of the
   postseason to the last out (data/mlb/race_log.json); nothing when the log does not cover the season. */
function wonFill(host, champ, runner, calls, L, S, p0) {
  if (!host) return;
  BP.loadLevel('race_log.json', L).then(lg => {
    const p = ((lg || {})[String(S)] || {}).p_ws || {};
    const eve = (calls.preplayoff || {}).asof;
    const days = Object.keys(p).sort().filter(d => !eve || d >= eve);
    if (!host.isConnected || days.length < 3 || !days.some(d => isNum(p[d][champ]))) return;
    const pts = t => days.map(d => (isNum(p[d][t]) ? Math.round(1000 * p[d][t]) / 10 : null));
    const c0 = pts(champ), lo = Math.min.apply(null, c0.filter(isNum));
    host.innerHTML = '<div style="margin-top:var(--sp-5)">' + QK.sectionHead({ kicker: 'How the title was won', title: 'From ' + U.pct(isNum(p0) ? p0 : lo / 100) + ' to champions', tag: 'h3',
      sub: 'Our World Series chance for the ' + BP.teamShort(champ) + (runner ? ' and the ' + BP.teamShort(runner) : '') + ', day by day from the eve of the postseason to the last out.' }) +
      U.card2('Our World Series chance through October', 'in team colours; each point is the chance we showed that day', '<div id="ov-won" class="qk-chart" style="--h:300px" role="img" aria-label="Our World Series chance for the champion through the postseason"></div>') + '</div>';
    QKC.line('#ov-won', { x: days.map(d => day(d).replace(/^\w+ /, '')), xName: 'Day', yName: 'World Series chance (%)', yMin: 0, yMax: 100, yFmt: v => Math.round(v) + '%', endLabels: true,
      label: 'World Series chance by day', series: [{ name: BP.teamShort(champ), label: BP.teamAbbr(champ), color: QK.color.ensure(U.raw(champ) || '#7d93ff', '#14171d', 3), data: c0, width: 3 }]
        .concat(runner ? [{ name: BP.teamShort(runner), label: BP.teamAbbr(runner), color: QK.color.ensure(U.raw(runner) || '#9aa3b2', '#14171d', 3), data: pts(runner), dash: true }] : []) });
  });
}
function reachText(post, t) {
  const r = ((post.teams || {})[t] || {}).reached;
  return r === 'WS' ? 'lost the World Series' : r === 'CS' ? 'lost the LCS' : r === 'DS' ? 'went out in the Division Series' : r === 'WC' ? 'went out in the Wild Card round' : '';
}
function ordinal(n) { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
/* Under the hero: why we picked it (round 6: the "How sure are we?" line lives on the Model page now). */
function heroNote(g, why) {
  return why ? '<b>Why this game?</b> ' + esc(why) : false;
}
/* "This week in MLB": the stage line. */
function stageLine(st, phase) {
  if (!st) return PHASE[phase] ? PHASE[phase] + '.' : '';
  if (/pre/.test(phase)) return 'Spring training. Opening Day is ' + day(st.first) + '.';
  if (/off|complete/.test(phase)) return st.champion ? The(st.champion) + ' won the World Series. Our numbers pick up again in spring.' : 'The off-season. Our numbers pick up again in spring.';
  if (/post/.test(phase)) {
    if (st.champion) return The(st.champion) + ' won the World Series.';
    const al = (st.alive || []);
    if (!al.length) return 'The postseason.';
    const name = al[0].name || BP.roundLabel(al[0].round);
    const ser = al.map(s => BP.teamShort(s.teams[0]) + ' v ' + BP.teamShort(s.teams[1]) + ', ' + seriesState(s)).join('; ');
    return 'The postseason: the ' + name + (al.length > 1 ? 's' : '') + ' (best of ' + (al[0].best_of || 7) + '). ' + ser + '.' + (al[0].round !== 'WS' ? ' The World Series is next.' : '');
  }
  return 'Regular season, week ' + st.week + ' of ' + st.weeks + ': ' + QK.fmt.num(st.played) + ' of ' + QK.fmt.num(st.total) + ' games played. It runs to ' + day(st.last) + ', then twelve clubs play for the World Series.';
}
function weekTiles(dig, feat, titles, L, S, played) {
  const T = [];
  const mv = dig.movers;
  if (played && played.champion) {
    /* round 11: a decided World Series leads the week: the champion, never a favourite at 100% */
    const ch = played.champion, ws = BP.charts.seriesList(played).filter(x => x.rk === 'WS')[0];
    const ro = ws ? ws.teams.filter(t => t !== ch)[0] : null, w = ws ? (ws.teams[0] === ch ? ws.wins : [ws.wins[1], ws.wins[0]]) : null;
    T.push({ label: 'World Series champions', value: BP.teamAbbr(ch), href: BP.teamHref(ch, L, S), signal: true,
      sub: The(ch) + (ro && w ? ' beat ' + the(ro) + ' ' + w[0] + '–' + w[1] + ' in the World Series.' : ' won the World Series.') });
  } else if (mv && (mv.up.length || mv.down.length)) {
    const up = mv.up[0], dn = mv.down[0], lead = up || dn, what = mv.metric === 'p_ws' ? 'World Series' : 'postseason';
    T.push({ label: 'Biggest mover', value: BP.teamAbbr(lead.key) + ' ' + ptsOf(lead.d), href: BP.teamHref(lead.key, L, S), signal: true,
      sub: The(lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + U.pct(lead.p) + ' in our ' + what + ' chance since ' + day(mv.since) + '.' + (up && dn ? ' Biggest fall: ' + BP.teamAbbr(dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  } else if (titles.length) {
    const f = titles[0];
    T.push({ label: 'World Series favourite', value: BP.teamAbbr(f.t) + ' ' + U.pct(f.p), href: BP.teamHref(f.t, L, S), signal: true,
      sub: (f.p < 0.2 ? 'Nobody is better than 1 in 5. ' : '') + The(f.t) + ' lead our board, from 20,000 simulated brackets.' });
  }
  const u = dig.upset;
  if (u) {
    const score = u.side === 'home' ? u.hs + '–' + u.as : u.as + '–' + u.hs;
    T.push({ label: 'Upset of the week', value: BP.teamAbbr(u.winner) + ' ' + U.pct(u.p), href: BP.gameHref(u.id, L),
      sub: The(u.winner) + ' beat ' + the(u.loser) + ' ' + score + ' on ' + QK.fmt.date(u.start) + '. We gave them ' + U.pct(u.p) + ' before first pitch.' });
  }
  const h = dig.hot;
  if (h) T.push({ label: 'Team of the week', value: BP.teamAbbr(h.key) + ' ' + h.w + '–' + h.l, href: BP.teamHref(h.key, L, S),
    sub: The(h.key) + ': ' + h.w + ' win' + (h.w === 1 ? '' : 's') + ' in ' + h.gp + ' games, ' + (h.margin >= 0 ? '+' : '−') + Math.abs(h.margin) + ' run difference.' });
  const rest = ((feat && feat.rest) || []).filter(Boolean).slice(0, 2);
  if (rest.length) T.push({ label: 'Also worth a look', value: rest.map(c => BP.teamAbbr(c.away) + '–' + BP.teamAbbr(c.home)).join(' · '), href: BP.href('games', L, S), text: rest.length > 1,
    sub: rest.map(c => { const w = whenLabel(BP.kitGame(c, L)); return w + (BP.isLive(c) ? '' : ' ' + QK.fmt.time(c.start)) + ': ' + (c.series ? BP.seriesText(c.series, true) + ', ' : '') + 'the ' + BP.teamShort(c.away) + ' at the ' + BP.teamShort(c.home); }).join('. ') + '.' });
  return T;
}

function render(el, params) {
  const L = params.level, S = params.season;
  const idx = BP.index() || {};
  const isCurrent = S === BP.currentSeason(L);
  const lv = BP.levelInfo(L);
  const src = L === 'mlb' ? idx : lv;
  const phase = isCurrent ? String(lv.phase || idx.phase || '') : 'complete';
  el.innerHTML = QK.skeleton('card', 3);
  return BP.loadAll([BP.ypath('season.json', L, S), 'index.json']).then(arr => {
    if (!U.alive(el)) return;
    const season = BP.ok(arr[0]) ? arr[0] : null;
    let post = isCurrent ? (L === 'mlb' ? idx.postseason : lv.postseason) || null : null;
    const sp = season && season.postseason && typeof season.postseason === 'object' && season.postseason.series ? season.postseason : null;
    if (sp) post = Object.assign({}, sp, post || {}, { teams: sp.teams || (post && post.teams), seeds: sp.seeds || (post && post.seeds), series: (post && post.series) || sp.series });
    const rows = BP.standingsRows ? BP.standingsRows(season || {}) : {};
    BP.setRecords(U.records(season || {}));
    /* Triple-A has no simulation: its rows carry 1 / 0 for the clubs that played in September, never a chance column */
    const hasSim = BP.levelInfo(L).sim !== false && (Object.keys(rows).some(t => rows[t].sim && isNum(rows[t].sim.p_postseason)) || Object.keys(rows).some(t => isNum(rows[t].p_postseason)));
    /* round 11: a decided World Series (this season's too) opens like a finished season: the champion, the recap; never
       a title race at 100% */
    const played = sp ? BP.charts.asPlayed(sp) : null;
    const champ = L === 'mlb' && played && played.actual ? played.champion : null;
    const decided = isCurrent && !!champ;
    const titles = L === 'mlb' && !decided ? titleRows(idx, post) : [];
    const inPost = !decided && phase === 'postseason' && post && post.series && post.series.length;
    const round = inPost && post.round ? BP.roundLabel(post.round) : '';
    const kicker = [BP.levelLong(L), S, PHASE[phase] || BP.titleCase(phase), round].filter(Boolean).join(' · ');
    const title = L === 'aaa' ? 'Triple-A, by the numbers.' : isCurrent ? 'Every MLB game, by the numbers.' : 'The ' + S + ' season, by the numbers.';
    const sub = !isCurrent ? 'The final standings, how good every club really was, who was lucky, and the players behind it.'
      : L === 'aaa' ? 'Statcast for the International and Pacific Coast Leagues, with major-league translations for every prospect.'
        : 'Our win chance for every game from a plate-appearance simulation with the lineups and starters, postseason chances from 20,000 simulated brackets, Statcast percentiles and the players behind it all.';

    // scoreboard lists
    const seen = {};
    const pick = list => list.filter(c => c && U.fresh(c) && !seen[c.gpk] && (seen[c.gpk] = 1));
    const order = { live: 0, pre: 1, final: 2 };
    const st = c => (BP.isLive(c) ? 'live' : BP.isFinal(c) ? 'final' : 'pre');
    const today = isCurrent ? pick((src.today || []).slice()).sort((a, b) => order[st(a)] - order[st(b)] || String(a.start).localeCompare(String(b.start))) : [];
    const next = isCurrent ? pick((src.upcoming || []).slice().sort((a, b) => String(a.start || a.date).localeCompare(String(b.start || b.date)))) : [];
    const results = isCurrent ? pick((src.recent || []).slice().sort((a, b) => String(b.start || b.date).localeCompare(String(a.start || a.date)))) : [];
    const hasGames = today.length + next.length + results.length > 0;
    const first = today.length ? 'today' : next.length ? 'next' : 'results';

    const when = 'today';
    const landing = isCurrent && L === 'mlb';
    const dig = landing ? (idx.digest || {}) : {};
    const feat = landing ? pickFeatured(idx, today.concat(next), post) : null;
    let h = '';
    if (landing) {
      h += intro({ tag: kicker, title: 'Every MLB game, team and player, by the numbers.',
        lede: decided ? 'The ' + S + ' season is over: the ' + BP.teamName(champ) + ' won the World Series. How they won it, our calls against what happened, the award races and the players behind it, in plain English.'
          : inPost ? 'Our chance for every postseason game, who wins the World Series from 20,000 simulated brackets, and the Statcast numbers behind the players, in plain English.'
          : 'Our chance for every game from a plate-appearance simulation with the lineups and starters, the race for October from 20,000 simulated seasons, and Statcast percentiles for every player, in plain English.',
        links: [{ label: 'Games', sub: 'Every game, our chance', href: BP.href('games', L, S) },
          decided ? { label: 'Bracket', sub: 'Every series as played', href: BP.ghref('postseason') }
            : inPost ? { label: 'Bracket', sub: 'Every series and path', href: BP.ghref('postseason') } : { label: 'Standings', sub: 'The race for October', href: BP.href('standings', L, S) },
          { label: 'Scouting Room', sub: 'Every player, every metric', href: BP.href('scout', L, S) }] });
      h += '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in MLB', title: '<span id="ov-wk">The week so far</span>', html: true, sub: esc(stageLine(dig.stage, phase)) }) +
        '<div id="ov-week"></div><div id="ov-feat" class="ql-feat"></div></section>';
    } else if (isCurrent && today.length + next.length > 0) {
      h += intro({ tag: kicker, title: 'Triple-A, by the numbers.', lede: sub,
        links: [{ label: 'Games', sub: 'Every game, our chance', href: BP.href('games', L, S) }, { label: 'Standings', sub: 'The table', href: BP.href('standings', L, S) }, { label: 'Prospects', sub: 'Major-league translations', href: BP.href('prospects', L, S) }] });
    } else {
      h += QK.sectionHead({ kicker: kicker, title: title, sub: sub, size: 'lg', tag: 'h1',
        actions: '<a class="qk-btn primary" href="' + BP.href('games', L, S) + '">' + (isCurrent ? 'All games' : 'Every game') + '</a><a class="qk-btn ghost" href="' + BP.href('standings', L, S) + '">Standings</a>' });
    }

    /* round 9: a finished MLB season opens with its recap (the champion, our calls against what happened, the awards);
       round 11: so does this season once its World Series is decided, straight after the intro */
    const recapOn = L === 'mlb' && !!played && !!played.actual && (!isCurrent || decided);
    if (recapOn) {
      const rc = '<section class="qk-section" id="ov-recap"></section>';
      h = decided && h.indexOf('<section class="qk-section ql-week">') > 0 ? h.replace('<section class="qk-section ql-week">', rc + '<section class="qk-section ql-week">') : h + rc;
    }
    /* round 9: Triple-A leads with its own story: how the season finished (the league finals and the national
       championship), the players it sent up, and the best prospects by our major-league translation */
    if (L === 'aaa') h += '<section class="qk-section" id="ov-aaa-fin"></section><section class="qk-section" id="ov-aaa-up"></section>';
    if (hasGames) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch', title: '<span id="ov-gh">Today</span>', html: true, sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.',
      actions: U.seg('ov-when', 'Games', [['today', 'Today'], ['next', 'Next'], ['results', 'Results']], first) }) + '<div class="qk-watch" id="ov-games"></div></section>';
    const hot = hotItems(src.leaders || {}, L);
    /* Who's hot: the black power list, the top name on five boards */
    if (hot.length) h += QK.band(QK.sectionHead({ kicker: isCurrent && !decided ? 'Who’s hot' : 'The season’s best', title: isCurrent && !decided ? 'The leaders, board by board' : 'Who led the way', sub: 'The top name on five boards, the next best behind, and a line on what the number means.',
      actions: '<a class="qk-more" href="' + BP.href('scout', L, S) + '?view=leaders">Every position’s leaders</a>' }) + QK.hotRow(hot));
    /* round 6: the fan modules (MLB, this season): breakout watch, then the spotlight; Who's for real? (win % against
       run differential) beside the biggest climb and fall from last season. Filled lazily by fanModules. */
    if (landing) h += '<section class="qk-section" id="ov-chase"></section><section class="qk-section" id="ov-form"></section><section class="qk-section" id="ov-break"></section><section class="qk-section" id="ov-spot"></section>';
    const realHTML = '<div class="bp-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Clubs top-left are winning more than their runs suggest; bottom-right, the reverse. Luck in close games, or something real?' }) +
      '<div class="qk-card"><div class="qk-card-body"><div id="ov-real" class="qk-chart" role="img" aria-label="Win percentage against run differential a game"></div><p class="qk-caption" id="ov-real-cap"></p></div></div></div>';
    h += landing ? '<section class="qk-section qk-g75">' + realHTML + '<div id="ov-climb"></div></section>' : '<section class="qk-section">' + realHTML + '</section>';
    if (isCurrent) h += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against the same position or role (shortstops, starters, relievers): 90th means better than 90 in 100.',
      '<b>Bullpen WAR</b> is ours: wins a player adds over a replacement-level one, from batting, running, fielding and pitching. 2 is a solid regular, 5 or more is All-Star level.'] }) + '</section>';

    // season simulation
    if (titles.length || inPost) {
      h += '<section class="qk-section" id="ov-title">' + QK.sectionHead({ kicker: 'Title race', title: 'Who wins the World Series?', html: true, sub: '<span id="ov-ws-lede">Our chances from simulating every remaining game and the bracket, each series played out in the model.</span>',
        actions: '<a class="qk-more" href="' + BP.ghref('postseason') + '">Every series and path</a>' }) +
        '<div class="qk-grid">' + (titles.length ? '<div class="qk-span-' + (inPost ? 5 : 12) + '">' + U.card2('World Series chances', 'Our chance from 20,000 simulated brackets, in team colours', '<div id="ov-ws"></div>', { foot: '<span>Clubs still alive</span>' + U.more(BP.ghref('postseason'), 'Every series and path') }) + '</div>' : '') +
        (inPost ? '<div class="qk-span-' + (titles.length ? 7 : 12) + '">' + U.card2('The bracket', 'Series wins and our chance to win each series', '<div id="ov-bk"></div>', { foot: '<span>' + (post.sims ? BP.int(post.sims) + ' simulated brackets' : '') + '</span>' + U.more(BP.ghref('postseason'), 'Postseason') }) + '</div>' : '') + '</div></section>';
    }

    // team strength (round 9): the offence-v-run-prevention map is the Teams page's style map; here a teaser with the
    // clubs that stand out on each side
    const haveRatings = Object.keys(rows).some(t => rows[t].rating && isNum(rows[t].rating.net));
    if (haveRatings) {
      const rr = Object.keys(rows).map(t => rows[t]).filter(r => r.rating && isNum(r.rating.off) && isNum(r.rating.net));
      const prev = r => (isNum(r.rating.def) ? r.rating.def : 0) + (isNum(r.rating.pitch) ? r.rating.pitch : 0);
      const top = (f, n) => rr.slice().sort((a, b) => f(b) - f(a)).slice(0, n);
      const both = top(r => Math.min(r.rating.off, prev(r)), 1)[0], bats = top(r => r.rating.off, 1)[0], arms = top(r => prev(r), 1)[0];
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Team strength', title: 'Bats or arms?', sub: 'Where each club’s strength comes from, in runs a game above an average club, from our team ratings.',
        actions: '<a class="qk-more" href="' + BP.href('teams', L, S) + '?map=0">The style map</a>' }) +
        QK.stats([bats ? { label: 'Best offence', value: BP.teamAbbr(bats.tid) + ' ' + U.signed(bats.rating.off, 2), sub: 'runs a game above average, batting and running', href: BP.teamHref(bats.tid, L, S) } : null,
          arms ? { label: 'Best run prevention', value: BP.teamAbbr(arms.tid) + ' ' + U.signed(prev(arms), 2), sub: 'runs a game saved, pitching and fielding', href: BP.teamHref(arms.tid, L, S) } : null,
          both ? { label: 'Best on both', value: BP.teamAbbr(both.tid), signal: true, sub: 'offence ' + U.signed(both.rating.off, 2) + ', run prevention ' + U.signed(prev(both), 2), href: BP.teamHref(both.tid, L, S) } : null].filter(Boolean)) + '</section>';
    }

    // standings
    const leagues = [];
    Object.keys(rows).forEach(t => { const lg = rows[t].league; if (lg && leagues.indexOf(lg) < 0) leagues.push(lg); });
    leagues.sort();
    if (leagues.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Standings', title: 'The table', sub: 'Wins and losses, run differential' + (hasSim ? ', and our chance of a postseason place from the season simulation.' : '.'),
      actions: leagues.length > 1 ? U.seg('ov-lg', 'League', leagues.map(x => [x, x]), leagues[0]) : '' }) +
      U.card2(isCurrent && (inPost || decided) ? 'Final regular season' : 'Standings', '', '<div id="ov-st"></div>', { flush: true, foot: '<span>' + esc(BP.levelName(L) + ' ' + S) + '</span>' + U.more(BP.href('standings', L, S), 'Full standings') }) + '</section>';

    // round 9: one leaders module (Who's hot, above); the boards for every position are the Scouting Room's Leaders
    /* our record and calibration live on the Model page ("How we're doing"): one small link here */
    if (L === 'mlb') h += '<p class="qk-sub bp-ov-doing">Every forecast is checked against the result: <a class="qk-link" href="#/calibration">How we’re doing →</a></p>';

    el.innerHTML = h;
    if (recapOn) recapFill(el.querySelector('#ov-recap'), played, season, L, S, { title: decided ? (dig.stage || {}).title : null });
    if (landing) { formFill(el.querySelector('#ov-form'), L, S); chaseFill(el.querySelector('#ov-chase'), L, S); }
    if (L === 'aaa') aaaFill(el, sp, L, S);

    // this week: the top lines, then the game that matters most (or the World Series race when nothing big is on)
    if (landing) {
      const T = weekTiles(dig, feat, titles, L, S, decided ? played : null);
      el.querySelector('#ov-week').innerHTML = T.length ? QK.stats(T) : '';
      if (T.length >= 3) el.querySelector('#ov-wk').textContent = 'The week in ' + WORDS[T.length].toLowerCase() + ' lines';
      const fe = el.querySelector('#ov-feat');
      if (feat && feat.c) {
        const g = Object.assign(BP.kitGame(feat.c, L), { league: 'MLB' }), lab = whenLabel(g);
        const occ = feat.c.series ? BP.seriesText(feat.c.series, true) : (feat.week && !/^(Today|Tonight|Live now|Under way)$/.test(lab) ? 'The big one this week' : 'The one to watch');
        fe.innerHTML = QK.featureCard(g, { scribble: lab + ' · ' + occ, nick: t => t.short || t.name, note: heroNote(g, feat.why) });
      } else if (titles.length) {  /* nothing big on: one line to the title race below (round 9: the race is shown once) */
        fe.innerHTML = '<p class="qk-sub bp-ov-quiet">' + (feat ? 'Nothing big on today.' : 'No games in the next few days.') + ' The race for the World Series follows below, and every chance is on <a class="qk-link" href="' + BP.href('chances', L, S) + '">Chances</a>.</p>';
      }
    }

    // draw: games
    if (hasGames) {
      const draw = w => {
        const list = w === 'next' ? next : w === 'results' ? results : today;
        const n = Math.min(9, list.length);
        const W = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
        el.querySelector('#ov-gh').textContent = w === 'next' ? 'Next up. Our calls.' : w === 'results' ? 'Latest results' : (n ? (W[n] || n) + ' game' + (n === 1 ? '' : 's') + '. Our calls.' : 'Today');
        el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(c => BP.gameCard(c, { level: L, date: w !== 'today', why: true })).join('') : QK.empty('No games', w === 'today' ? 'No games today: see the next ones.' : 'Nothing to show yet.');
      };
      draw(first);
      QK.seg(el.querySelector('#ov-when'), draw);
    }
    // World Series chances: ours only (the market is on game pages and the Model page)
    /* the title race in team colours, ours only (the market is on game pages and the Model page) */
    if (titles.length && el.querySelector('#ov-ws')) {
      const wsRows = titles.map(r => ({ label: BP.teamShort(r.t), p: r.p, href: BP.teamHref(r.t, L, S), mark: U.team(r.t, L, S), color: U.raw(r.t) }));
      el.querySelector('#ov-ws').innerHTML = QK.chances(wsRows, { limit: 10, key: false });
      const w0 = wsRows[0], lede = el.querySelector('#ov-ws-lede');
      if (w0 && lede) lede.textContent = (w0.p < 0.2 ? 'Nobody’s better than 1 in 5. The ' + w0.label + ' lead our board at ' + U.pct(w0.p) + '.'
        : 'The ' + w0.label + ' lead at ' + U.pct(w0.p) + (w0.p >= 0.5 ? ': they win it in about ' + Math.round(w0.p * 10) + ' of 10 simulated brackets.' : '.')) + ' Every remaining game and series simulated 20,000 times.';
    }
    if (landing) fanModules(el, idx, L, S, rows);
    /* Who's for real?: games won against run differential a game (QKC.quadrant), the corners named */
    if (el.querySelector('#ov-real')) {
      const rr = Object.keys(rows).map(t => rows[t]).filter(r => isNum(r.w) && isNum(r.l) && r.w + r.l > 0 && isNum(r.rd));
      const pts = rr.map(r => ({ x: r.rd / (r.w + r.l), y: r.w / (r.w + r.l) * 100, name: BP.teamName(r.tid), sub: r.w + '–' + r.l + ' · run differential ' + U.signed(r.rd, 0), label: BP.teamAbbr(r.tid), color: U.raw(r.tid), href: BP.teamHref(r.tid, L, S) }));
      if (pts.length >= 6) {
        const gps = rr.map(r => r.w + r.l), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
        QKC.quadrant('#ov-real', { points: pts, xName: 'Run differential a game (runs)', yName: 'Games won (%)', refX: 0, refY: 50, xFmt: v => U.signed(v, 1), yFmt: v => Math.round(v) + '%', label: BP.levelName(L) + ' clubs: run differential against games won' });
        el.querySelector('#ov-real-cap').textContent = BP.levelName(L) + ' ' + S + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. Run differential is runs scored minus runs allowed, per game. Dashed lines: an even differential and a .500 record. Tap a club for its page.';
      } else el.querySelector('#ov-real').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');
    }
    if (inPost && BP.charts && BP.charts.mlbBracket && el.querySelector('#ov-bk')) BP.charts.mlbBracket(el.querySelector('#ov-bk'), post, { level: L, narrow: true });
    // standings by league
    if (leagues.length) {
      const drawLg = lg => {
        const rs = Object.keys(rows).map(t => rows[t]).filter(r => r.league === lg).sort((a, b) => (b.pct || 0) - (a.pct || 0) || (b.w || 0) - (a.w || 0));
        const lead0 = {};
        rs.forEach(r => { const d = r.division || ''; if (!lead0[d]) lead0[d] = r; });
        const cols = [
          { key: 'name', label: 'Club', type: 'entity', sub: 'div', mark: r => U.team(r.tid, L, S), href: r => BP.teamHref(r.tid, L, S) },
          { key: 'w', label: 'W', num: true }, { key: 'l', label: 'L', num: true },
          { key: 'pct', label: 'Pct', num: true, fmt: v => BP.fmtAvg(v) },
          { key: 'gb', label: 'GB', num: true, fmt: v => { const x = Number(v); return isNum(v) && isFinite(x) && x > 0 ? (x % 1 ? x.toFixed(1) : String(x)) : '—'; } },
          { key: 'rd', label: 'RD', num: true, fmt: v => (isNum(v) ? U.signed(v, 0) : '—') }
        ];
        if (!isCurrent && rs.some(r => isNum(r.seed))) cols.splice(1, 0, { key: 'seed', label: 'Seed', num: true, fmt: (v, r) => (isNum(v) ? String(v) + (r.clinched ? ' <span class="clinch" title="' + esc({ z: 'Division and a bye', y: 'Division', w: 'Wild card' }[r.clinched] || 'Clinched') + '">' + esc(r.clinched) + '</span>' : '') : '—'), tip: 'Postseason seed; z: division and a bye, y: division, w: wild card' });
        if (hasSim) cols.push({ key: 'pp', label: 'Postseason', type: 'bar', max: 1, fmt: v => (isNum(v) ? (v >= 0.9995 ? 'In' : v <= 0.0005 ? 'Out' : U.pct(v)) : '—'), tip: 'Our chance of a postseason place from the season simulation' });
        QK.leaderboard(el.querySelector('#ov-st'), { dense: true, rank: true, rowHref: r => BP.teamHref(r.tid, L, S), columns: cols,
          rows: rs.map(r => Object.assign({}, r, { name: BP.teamShort(r.tid), div: String(r.division || '').replace(/^(AL|NL)\s/, ''), gb: isNum(r.gb) ? r.gb : (lead0[r.division || ''] ? ((lead0[r.division || ''].w - r.w) + (r.l - lead0[r.division || ''].l)) / 2 : null),
            pp: r.sim && isNum(r.sim.p_postseason) ? r.sim.p_postseason : (isNum(r.p_postseason) ? r.p_postseason : null) })) });
      };
      drawLg(leagues[0]);
      if (leagues.length > 1) QK.seg(el.querySelector('#ov-lg'), drawLg);
    }
    if (today.some(BP.isLive)) BP.liveRefresh([BP.ypath('season.json', L, S)], 60000);
    BP.setMeta(decided ? 'The ' + S + ' season is over' : post && post.sims ? BP.int(post.sims) + ' bracket simulations' : '');
  });
}

/* ── fan modules (round 6): breakout watch, the best player nobody talks about, the biggest climbs ──────────── */
/* Read lazily after the page draws: the player files of the top eight hitters and pitchers by Bullpen WAR (about
 * 30 KB each) and last season's season.json (15 KB). Nothing here is about how our forecasts score. */
const WAR_TRACK = 9;   /* a breakout card's WAR track runs 0 to 9 (an MVP-level season) */
const SPOT_KEYS = ['xwoba_plus', 'barrel_pct', 'chase_pct', 'oaa', 'sprint_speed', 'bat_speed', 'hard_pct', 'woba'];
const SPOT_LABEL = { xwoba_plus: 'xwOBA+ (our expected wOBA)', barrel_pct: 'Barrel rate', chase_pct: 'Chase rate', oaa: 'Outs above average', sprint_speed: 'Sprint speed', bat_speed: 'Bat speed', hard_pct: 'Hard-hit rate', woba: 'wOBA' };
function spotVal(k, v) {
  if (!isNum(v)) return '';
  if (/_pct$/.test(k)) return (100 * v).toFixed(1) + '%';
  if (k === 'woba' || k === 'xwoba_plus') return BP.fmtAvg(v);
  if (k === 'sprint_speed') return BP.num(v, 1) + ' ft/s';
  if (k === 'bat_speed') return BP.num(v, 1) + ' mph';
  if (k === 'oaa') return U.signed(v, 0);
  return BP.num(v, 1);
}
function mlbSeasons(p, kind, S) { return ((p && p.seasons) || []).filter(s => s.level === 'mlb' && s.kind === kind && isNum(s.war) && s.season <= S); }
function curBlock(p, kind, S) { const c = (p && p.current) || {}; return c.season === S && c.level === 'mlb' ? (c[kind === 'hitter' ? 'hitting' : 'pitching'] || null) : null; }
/* this season's WAR against last season's, when last season was a real one (200+ PA or 150+ batters faced) */
function breakoutOf(p, kind, S) {
  const ss = mlbSeasons(p, kind, S), cur = ss.filter(s => s.season === S)[0];
  const prev = ss.filter(s => s.season === S - 1 && (kind === 'hitter' ? (s.pa || 0) >= 200 : (s.bf || 0) >= 150))[0];
  if (!cur || !prev) return null;
  const by = {};
  ss.forEach(s => { by[s.season] = s.war; });
  const yrs = Object.keys(by).map(Number).sort((a, b) => a - b);
  return { p: p, kind: kind, cur: cur, prev: prev, gain: cur.war - prev.war, line: yrs.map(y => by[y]), yrs: yrs };
}
const JUMP = ['Biggest jump', 'Second biggest', 'Third biggest'];
/* pitchers' percentiles are within the role (pct_role): say which */
const roleOf = blk => (blk.pct_role ? (blk.role === 'RP' ? ' of relievers' : ' of starters') : '');
function breakoutCard(b, L, S, i) {
  const blk = curBlock(b.p, b.kind, S) || {}, pc = blk.pct_role || blk.pct || {};
  const tm = blk.team || b.cur.team, pos = blk.pos || b.cur.pos || (b.kind === 'pitcher' ? 'P' : '');
  const deep = b.kind === 'hitter' ? (isNum(pc.woba) && pc.woba >= 80 ? 'a wOBA in the ' + QK.ordinal(Math.round(pc.woba)) + ' percentile of his position' : '')
    : (isNum(pc.stuff_plus) && pc.stuff_plus >= 80 ? 'Stuff+ in the ' + QK.ordinal(Math.round(pc.stuff_plus)) + ' percentile' + roleOf(blk) : (isNum(pc.ra9) && pc.ra9 >= 80 ? 'runs allowed in the ' + QK.ordinal(Math.round(pc.ra9)) + ' percentile' + roleOf(blk) : ''));
  const work = b.kind === 'hitter' ? BP.int(b.cur.pa) + ' plate appearances' : 'about ' + Math.round(b.cur.ip) + ' innings';
  return { kicker: JUMP[i] || 'Breakout watch', sport: 'baseball', name: b.p.name, sub: [BP.teamAbbr(tm), pos, isNum(blk.age) ? 'age ' + Math.floor(blk.age) : ''].filter(Boolean).join(' · '),
    value: U.signed(b.gain, 1), unit: 'WAR on ' + (S - 1), colour: U.raw(tm), mark: U.team(tm, L, S),
    from: { label: String(S - 1), value: BP.num(b.prev.war, 1), pos: Math.max(0, b.prev.war) / WAR_TRACK * 100 }, to: { label: String(S), value: BP.num(b.cur.war, 1), pos: Math.max(0, b.cur.war) / WAR_TRACK * 100 },
    spark: b.line.length > 2 ? b.line : null, sparkLabel: b.line.length > 2 ? 'Bullpen WAR, ' + b.yrs[0] + '–' + b.yrs[b.yrs.length - 1] : '',
    text: 'From ' + BP.num(b.prev.war, 1) + ' Bullpen WAR in ' + (S - 1) + ' to ' + BP.num(b.cur.war, 1) + ' in ' + S + ', over ' + work + (deep ? ', with ' + deep : '') + '.',
    href: progHref(BP.playerHref(b.p.id, { level: L, role: b.kind })), link: { text: 'Progression' } };
}
const progHref = h => h + (h.indexOf('?') >= 0 ? '&' : '?') + 'view=progression';   /* the player's Progression tab (round 6) */
function spotlightOf(p, rank, L, S) {
  const blk = curBlock(p, 'hitter', S) || {}, pc = blk.pct_role || blk.pct || {}, v = blk.values || {};
  const keys = SPOT_KEYS.filter(k => isNum(pc[k])).slice(0, 4);
  const cur = mlbSeasons(p, 'hitter', S).filter(s => s.season === S)[0] || {};
  const line = mlbSeasons(p, 'hitter', S);
  const tm = blk.team || cur.team;
  return QK.spotlight({ kicker: 'Best player nobody talks about', name: p.name, sub: [BP.teamName(tm), blk.pos || cur.pos, isNum(blk.age) ? 'age ' + Math.floor(blk.age) : ''].filter(Boolean).join(' · '),
    team: U.team(tm, L, S), href: BP.playerHref(p.id, { level: L, role: 'hitter' }),
    headline: BP.num(cur.war, 1) + ' Bullpen WAR, ' + QK.ordinal(rank) + ' among MLB hitters, and not in the home-run top ten.',
    stats: keys.map(k => ({ label: U.label('hitter', k, SPOT_LABEL[k] || k), value: spotVal(k, v[k]), pctl: pc[k] })),
    spark: line.length > 1 ? { values: line.map(s => s.war), labels: [String(line[0].season), String(line[line.length - 1].season)], label: 'Bullpen WAR by season' } : null,
    text: 'Percentiles against his position. Bullpen WAR is our own: batting, running and fielding in wins above a replacement-level player.',
    links: [{ href: BP.playerHref(p.id, { level: L, role: 'hitter' }), text: 'Player page' }, { href: progHref(BP.playerHref(p.id, { level: L, role: 'hitter' })), text: 'Progression' }, { href: BP.ghref('compare'), text: 'Compare' }] });
}
/* last season's record against this one: the biggest climb and the biggest fall */
function climbs(rows, prevRows, L, S) {
  const out = [];
  Object.keys(rows).forEach(t => {
    const a = rows[t], b = prevRows[t];
    if (!a || !b || !isNum(a.w) || !isNum(a.l) || !isNum(b.w) || !isNum(b.l) || a.w + a.l < 20 || b.w + b.l < 100) return;
    out.push({ t: t, a: a, b: b, d: a.w / (a.w + a.l) - b.w / (b.w + b.l) });
  });
  out.sort((x, y) => y.d - x.d);
  const full = x => x.a.w + x.a.l >= 160;
  const card = (x, k) => {
    const pa = x.a.w / (x.a.w + x.a.l), pb = x.b.w / (x.b.w + x.b.l), pos = p => Math.max(0, Math.min(100, (p - 0.3) / 0.4 * 100));
    const dw = full(x) ? x.a.w - x.b.w : null;
    return { kicker: k, sport: 'baseball', name: BP.teamName(x.t), sub: BP.teamAbbr(x.t) + ' · ' + (x.a.division || x.a.league || ''), mark: U.team(x.t, L, S), colour: U.raw(x.t),
      value: dw !== null ? U.signed(dw, 0) : U.signed(100 * (pa - pb), 0), unit: dw !== null ? 'wins on ' + (S - 1) : 'points of win %',
      from: { label: (S - 1) + ' ' + x.b.w + '–' + x.b.l, value: BP.fmtAvg(pb), pos: pos(pb) }, to: { label: S + ' ' + x.a.w + '–' + x.a.l, value: BP.fmtAvg(pa), pos: pos(pa) },
      text: The(x.t) + ' went ' + x.b.w + '–' + x.b.l + ' in ' + (S - 1) + ' and ' + x.a.w + '–' + x.a.l + ' in ' + S + (isNum(x.a.rd) ? ', with a run differential of ' + U.signed(x.a.rd, 0) : '') + '.',
      href: BP.teamHref(x.t, L, S) };
  };
  return out.length >= 2 ? [card(out[0], 'Biggest climb'), card(out[out.length - 1], 'Biggest fall')] : [];
}
function fanModules(el, idx, L, S, rows) {
  const lead = idx.leaders || {};
  const ids = k => (lead[k] || []).slice(0, 8).map(r => String(r[0]));
  const hit = ids('h_war'), pit = ids('p_war'), hr = (lead.h_hr || []).map(r => String(r[0]));
  const files = hit.concat(pit).map(id => BP.load('players/' + id + '.json'));
  Promise.all(files.concat([BP.load(BP.ypath('season.json', L, S - 1))])).then(res => {
    if (!U.alive(el)) return;
    const prevSeason = res.pop();
    const ps = res.slice(0, hit.length), qs = res.slice(hit.length);
    const br = ps.map(p => breakoutOf(p, 'hitter', S)).concat(qs.map(p => breakoutOf(p, 'pitcher', S))).filter(b => b && b.gain >= 1.5).sort((a, b) => b.gain - a.gain).slice(0, 3);
    const bh = el.querySelector('#ov-break');
    if (bh && br.length) {
      bh.innerHTML = QK.sectionHead({ kicker: 'Breakout watch', title: 'Who took the leap', sub: 'The biggest jumps in Bullpen WAR from last season, among the top eight hitters and pitchers this season. Last season had to be a real one: 200 plate appearances or 150 batters faced.',
        actions: '<a class="qk-more" href="' + BP.href('scout', L, S) + '?view=leaders">Every position’s leaders</a>' }) + QK.storyCards(br.map((b, i) => breakoutCard(b, L, S, i)));
    }
    /* the best player nobody talks about: the highest-WAR hitter outside the top three and off the home-run board */
    const sp = el.querySelector('#ov-spot');
    let pick = null;
    hit.forEach((id, i) => { if (!pick && i >= 3 && hr.indexOf(id) < 0 && ps[i] && curBlock(ps[i], 'hitter', S)) pick = { p: ps[i], rank: i + 1 }; });
    if (sp && pick) sp.innerHTML = QK.spotlight ? spotlightOf(pick.p, pick.rank, L, S) : '';
    const cl = el.querySelector('#ov-climb');
    const prevRows = prevSeason && BP.standingsRows ? BP.standingsRows(prevSeason) : {};
    const cards = climbs(rows, prevRows, L, S);
    if (cl && cards.length) cl.innerHTML = QK.sectionHead({ kicker: 'Biggest surprise', title: 'Up and down', sub: 'This season’s record against last season’s, every club.' }) + QK.storyCards(cards, { cols: 1 });
  });
}

BP.route('hub', render);
})(window.BP);
