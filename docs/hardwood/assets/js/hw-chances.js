/* The Quant Hardwood — Standings ▸ Chances (#/<L>/standings?tab=chances; ?tab=odds still works), round 9 (28 Oct 2026).
 * One tab for the season simulation, rebuilt on the house order (the number, the chart, the table, the explain strip). It
 * replaces "Chances & ratings" (the legacy season.js view: seed distribution, win totals, rating paths, ratings,
 * schedule difficulty, leaders) and takes the playoff bars and the race chart off the Table:
 *   1. headline numbers: the title favourite, the most projected wins, the closest playoff call, the toughest run-in;
 *   2. title race (QK.chances, ours only) beside the conference titles;
 *   3. who makes the playoffs, per conference: a top-six seed or through the play-in (stacked bars);
 *   4. where each team finishes: the seed distribution heat map (per conference, or the league);
 *   5. win totals: every team's projected wins with the 90% range (QKC.range), and one team's whole distribution;
 *   6. how the race is shaping up (QKL.race, the race log), then the full table of chances and the explain strip.
 * Round 9, Phase 4: 7. the remaining strength of schedule (season.json schedule_difficulty: the average net rating of
 * the opponents played and still to play), 8. the NBA draft lottery board (sim.teams p_lottery_pick: each lottery
 * team's chance of every pick 1-14, from the simulated seasons and the lottery odds), as the Rink has the NHL's.
 * Rating paths live on Teams ▸ Through the season, schedule strength on the strength-of-schedule card (Phase 4) and the
 * player leaders in the Scouting Room. A finished season says so and points to the recap and the bracket.
 * Data: <L>/<S>/season.json (sim.teams: exp_w, w_p05, w_p95, seed_dist, win_dist, p_top6, p_playoffs, p_playin, p_conf,
 * p_title, magic, clinched) and <L>/race_log.json through QKL. Older-browser rule: no optional chaining, no nullish
 * coalescing. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const r3 = v => (isNum(v) ? Math.round(v * 1000) / 1000 : 0);

function chancesTab(node, L, S) {
  return HW.load(HW.path('season.json', L, S)).then(season => {
    if (!U.alive(node)) return;
    if (!U.ok(season)) { node.innerHTML = U.empty('Not built yet', 'The season payload for ' + HW.seasonLabel(L, S) + ' is not available.'); return; }
    const sim = HW.simTeams(season), st = season.standings || {}, fmt = season.format || {};
    const open = Object.keys(sim).some(t => isNum(sim[t].w_p05) && sim[t].w_p95 > sim[t].w_p05);
    const anyTitle = Object.keys(sim).some(t => isNum(sim[t].p_title) && sim[t].p_title > 0 && sim[t].p_title < 1);
    if (!open && !anyTitle) {
      node.innerHTML = QK.explain('The ' + esc(HW.seasonLabel(L, S)) + ' season is over, so its chances are settled. The <a class="qk-link" href="' + esc(HW.href(L, '', S)) + '">season recap</a> has the champion, the bracket and our calls against what happened; the <a class="qk-link" href="' + esc(HW.href(L, 'standings', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=bracket') + '">Bracket</a> has every series.', { title: 'Chances end with the season.' });
      return;
    }
    const confs = Object.keys(st).filter(c => (st[c] || []).length).sort();
    const ids = Object.keys(sim);
    const n = Number((season.sim || {}).n_sims || 20000);
    const leagueWide = fmt.seeding === 'league';
    const byTitle = ids.filter(t => isNum(sim[t].p_title)).sort((a, b) => sim[b].p_title - sim[a].p_title);
    const byW = ids.filter(t => isNum(sim[t].exp_w)).sort((a, b) => sim[b].exp_w - sim[a].exp_w);
    const coin = ids.filter(t => isNum(sim[t].p_playoffs)).sort((a, b) => Math.abs(sim[a].p_playoffs - 0.5) - Math.abs(sim[b].p_playoffs - 0.5))[0];
    const sd = season.schedule_difficulty || {};
    const tough = ids.filter(t => sd[t] && isNum(sd[t].remaining) && (sd[t].n_remaining || 0) > 5).sort((a, b) => sd[b].remaining - sd[a].remaining)[0];
    const kp = [];
    if (byTitle[0]) kp.push({ label: 'Title favourite', value: HW.teamShort(L, byTitle[0]) + ' ' + U.pct(sim[byTitle[0]].p_title), signal: true, href: HW.teamHref(L, byTitle[0], S), sub: 'wins it in ' + Math.max(1, Math.round(sim[byTitle[0]].p_title * 100)) + ' of 100 simulated seasons' });
    if (byW[0]) kp.push({ label: 'Most projected wins', value: HW.teamAbbr(L, byW[0]) + ' ' + U.f(sim[byW[0]].exp_w, 1), sub: '90% range ' + U.f(sim[byW[0]].w_p05, 0) + '–' + U.f(sim[byW[0]].w_p95, 0) + ' wins' });
    if (coin && open) kp.push({ label: 'Closest playoff call', value: HW.teamAbbr(L, coin) + ' ' + U.pct(sim[coin].p_playoffs), sub: 'the team nearest a coin flip for a playoff place' });
    if (tough) kp.push({ label: 'Toughest run-in', value: HW.teamAbbr(L, tough) + ' ' + U.signed(sd[tough].remaining, 1), sub: 'average opponent net rating, ' + sd[tough].n_remaining + ' games left' });
    const lo = HW.leagueOpts ? HW.leagueOpts(season, L, S) : null;
    let h = '<div class="hw-kpis">' + QK.stats(kp) + '</div>';
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who lifts the trophy?', sub: 'Our chance of winning the title from ' + n.toLocaleString('en-GB') + ' simulated seasons, and of winning each conference.' }) + '<div class="qk-grid">' +
      U.card2('Title chances', 'Every team with a chance, in team colours', '<div id="ch-title"></div>', { cls: 'qk-span-' + (leagueWide ? 12 : 6) }) +
      (leagueWide ? '' : U.card2('Conference titles', 'Our chance of reaching the Finals', '<div class="qk-seg" id="ch-cf-seg" role="group" aria-label="Conference" style="margin-bottom:10px">' + confs.map((c, i) => '<button type="button" data-value="' + esc(c) + '" aria-pressed="' + (i === 0) + '">' + esc(c) + '</button>').join('') + '</div><div id="ch-conf"></div>', { cls: 'qk-span-6' })) + '</div></section>';
    if (open) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Playoff picture', title: 'Who makes the playoffs', sub: fmt.playin ? 'Our chance of a top-six seed (straight through), and of getting in through the play-in (seeds 7 to 10).' : 'Our chance of a playoff place.' }) +
        '<div class="qk-grid">' + (leagueWide ? [['__all', 'League']] : confs.map(c => [c, c])).map((c, i, a) => U.card2(c[1], '', U.chart('ch-po-' + i, 22 * (c[0] === '__all' ? ids.length : (st[c[0]] || []).length) + 80, c[1] + ' playoff chances'), { cls: a.length > 1 ? 'qk-span-6' : 'qk-span-12' })).join('') + '</div></section>';
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Where they finish', title: 'Every seed, every team', sub: 'The share of simulated seasons each team finishes in each seed. A team spread across many seeds is still to be decided; one bright cell is nearly settled.',
        actions: leagueWide ? '' : '<div class="qk-seg" id="ch-sd-seg" role="group" aria-label="Conference">' + confs.map((c, i) => '<button type="button" data-value="' + esc(c) + '" aria-pressed="' + (i === 0) + '">' + esc(c) + '</button>').join('') + '</div>' }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="ch-seed" class="qk-chart" style="--h:' + (24 * (leagueWide ? ids.length : Math.max.apply(null, confs.map(c => (st[c] || []).length))) + 90) + 'px" role="img" aria-label="Seed distribution"></div></div></div></section>';
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Win totals', title: 'How many wins', sub: 'The average of our simulated seasons (dot) and the range nine in ten land in (bar). Pick a team for its whole spread.' }) +
        '<div class="qk-grid">' + U.card2('Projected wins', 'Every team, 90% range', U.chart('ch-wins', Math.max(340, 22 * byW.length + 70), 'Projected wins with a 90% range'), { cls: 'qk-span-7' }) +
        U.card2('One team’s spread', '<select class="qk-select" id="ch-wt-team" aria-label="Team">' + byW.map(t => '<option value="' + esc(t) + '">' + esc(HW.teamName(L, t)) + '</option>').join('') + '</select>', U.chart('ch-wd', 320, 'Final win total distribution'), { cls: 'qk-span-5' }) + '</div></section>';
    }
    /* 7. remaining schedule strength */
    const sdT = ids.filter(t => sd[t] && isNum(sd[t].remaining) && (sd[t].n_remaining || 0) > 0).sort((a, b) => sd[b].remaining - sd[a].remaining);
    if (open && sdT.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Strength of schedule', title: 'Who has the hard run-in', sub: 'The average net rating of the opponents each team still has to play (our ratings, points per 100 possessions; above zero is tougher than an average schedule), beside the schedule it has already played.' }) +
      '<div class="qk-card"><div class="qk-card-body"><div id="ch-sos" class="qk-chart" style="--h:' + (22 * sdT.length + 90) + 'px" role="img" aria-label="Strength of schedule, played and remaining"></div></div></div></section>';
    /* 8. the draft lottery (NBA) */
    const lot = L === 'nba' ? ids.filter(t => (sim[t].p_lottery_pick || []).reduce((a, b) => a + b, 0) > 0.05).sort((a, b) => ((sim[b].p_lottery_pick || [])[0] || 0) - ((sim[a].p_lottery_pick || [])[0] || 0) || (sim[a].exp_w || 0) - (sim[b].exp_w || 0)) : [];
    if (open && lot.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Draft lottery', title: 'Who gets the first pick', sub: 'Each lottery team’s chance of every pick from 1 to 14: the simulated seasons decide who misses the playoffs and in what order, then the lottery odds (14% for each of the three worst records) draw the top four.' }) +
      '<div class="qk-grid"><div class="qk-span-5">' + U.card2('The first pick', 'Our chance of the number one pick', '<div id="ch-lot1"></div>', {}) + '</div>' +
      '<div class="qk-span-7">' + U.card2('Every pick, every team', 'Share of simulated seasons landing each pick (%)', '<div id="ch-lot" class="qk-chart" style="--h:' + (22 * Math.min(lot.length, 18) + 90) + 'px" role="img" aria-label="Lottery pick distribution"></div>', {}) + '</div></div></section>';
    if (lo) h += '<div id="ch-race"></div>';
    h += '<section class="qk-section">' + U.card2('Every chance, in one table', 'Projected wins (hover for the 90% range), then our chance of each outcome; sort any column.', '<div id="ch-table"></div>', { flush: true }) + '</section>';
    h += QK.explain('<b>Playoffs 60%</b> means the team made the playoffs in about 6 of every 10 simulated seasons, so 4 in 10 it did not. Each simulated season plays every remaining game with our game model (ratings, home court, rest and travel), then the play-in and the playoffs. The chances move every day as results come in. <a class="qk-link" href="' + esc(HW.href(L, 'model') + '?tab=methodology') + '">How it works →</a>', { title: 'What’s that number?' });
    node.innerHTML = h;

    /* 2. title race */
    const rows = list => list.map(t => ({ label: HW.teamShort(L, t), p: sim[t].p_title, href: HW.teamHref(L, t, S), mark: U.team(L, t), color: HW.teamColourRaw(L, t) }));
    document.getElementById('ch-title').innerHTML = QK.chances(rows(byTitle.filter(t => sim[t].p_title > 0)), { limit: 12, key: false });
    const confEl = document.getElementById('ch-conf');
    if (confEl) {
      const drawConf = c => { confEl.innerHTML = QK.chances(ids.filter(t => sim[t].conference === c && isNum(sim[t].p_conf) && sim[t].p_conf > 0).sort((a, b) => sim[b].p_conf - sim[a].p_conf).map(t => ({ label: HW.teamShort(L, t), p: sim[t].p_conf, href: HW.teamHref(L, t, S), mark: U.team(L, t), color: HW.teamColourRaw(L, t) })), { limit: 8, key: false }); };
      drawConf(confs[0]);
      QK.seg(document.getElementById('ch-cf-seg'), drawConf);
    }
    if (open) {
      /* 3. playoff bars */
      (leagueWide ? ['__all'] : confs).forEach((c, i) => {
        const tids = (c === '__all' ? ids : (st[c] || []).map(r => String(r.team))).filter(t => sim[t]).sort((a, b) => (sim[b].p_playoffs || 0) - (sim[a].p_playoffs || 0));
        const series = fmt.playin
          ? [{ name: 'Top-six seed', data: tids.map(t => r3(sim[t].p_top6)) }, { name: 'Via the play-in', data: tids.map(t => r3(Math.max(0, (sim[t].p_playoffs || 0) - (sim[t].p_top6 || 0)))) }]
          : [{ name: 'Playoffs', data: tids.map(t => r3(sim[t].p_playoffs)) }];
        QKC.bar('#ch-po-' + i, { cats: tids.map(t => HW.teamAbbr(L, t)), series: series, horizontal: true, stack: true, legend: series.length > 1, fmt: v => U.pct(v), max: 1, hrefs: tids.map(t => HW.teamHref(L, t, S)), labelWidth: 46, valName: 'Our playoff chance', catName: 'Team' });
      });
      /* 4. seed distribution */
      const drawSeeds = c => {
        const tids = (c === '__all' ? ids : (st[c] || []).map(r => String(r.team))).filter(t => sim[t] && (sim[t].seed_dist || []).length).sort((a, b) => (sim[b].exp_w || 0) - (sim[a].exp_w || 0));
        const ns = Math.max.apply(null, tids.map(t => sim[t].seed_dist.length).concat([1]));
        const data = [];
        tids.forEach((t, yi) => sim[t].seed_dist.forEach((p, xi) => { data.push([xi, yi, Math.round(p * 1000) / 10]); }));
        QKC.heatmap('#ch-seed', { x: Array.from({ length: ns }, (_, i) => String(i + 1)), y: tids.map(t => HW.teamAbbr(L, t)), data: data, min: 0, max: Math.max(50, Math.max.apply(null, data.map(d => d[2]))), labelMin: 5, fmt: v => Math.round(v) + '%', xName: 'Final seed', yName: 'Team' });
      };
      drawSeeds(leagueWide ? '__all' : confs[0]);
      const ss = document.getElementById('ch-sd-seg');
      if (ss) QK.seg(ss, drawSeeds);
      /* 5. win totals */
      QKC.range('#ch-wins', { rows: byW.filter(t => isNum(sim[t].w_p05) && isNum(sim[t].w_p95)).map(t => ({ label: HW.teamName(L, t), lo: sim[t].w_p05, hi: sim[t].w_p95, mid: sim[t].exp_w, href: HW.teamHref(L, t, S), color: HW.teamColourRaw(L, t),
        sub: isNum(sim[t].p_playoffs) ? U.pct(sim[t].p_playoffs) + ' to make the playoffs' : '' })), fmt: v => U.f(v, 0), loName: '5th', hiName: '95th percentile', midName: 'Projected wins', valName: 'Wins at season end', labelWidth: 150, label: 'Projected wins with a 90% range' });
      const drawWd = t => {
        const wd = sim[t].win_dist || [];
        const k0 = wd.findIndex(p => p > 0.0005), k1 = wd.length - 1 - wd.slice().reverse().findIndex(p => p > 0.0005);
        const ks = []; for (let k = Math.max(0, k0); k <= Math.max(k0, k1); k++) ks.push(k);
        QKC.bar('#ch-wd', { cats: ks.map(String), series: [{ name: 'Share of simulations', data: ks.map(k => Math.round(wd[k] * 1000) / 10), color: U.tcol(L, t) }], fmt: v => U.f(v, 1) + '%', valName: 'Share of simulated seasons (%)', catName: 'Final wins' });
      };
      if (byW[0]) { drawWd(byW[0]); document.getElementById('ch-wt-team').addEventListener('change', e => drawWd(e.target.value)); }
    }
    if (document.getElementById('ch-sos')) {
      QKC.bar('#ch-sos', { cats: sdT.map(t => HW.teamAbbr(L, t)), series: [{ name: 'Still to play', data: sdT.map(t => Math.round(sd[t].remaining * 100) / 100), color: 'model' }, { name: 'Played', data: sdT.map(t => isNum(sd[t].played) ? Math.round(sd[t].played * 100) / 100 : null), color: QK.cssVar('--c-other') }],
        horizontal: true, legend: true, fmt: v => U.signed(v, 2), labelWidth: 46, valName: 'Average opponent net rating (points per 100)', catName: 'Team', hrefs: sdT.map(t => HW.teamHref(L, t, S)) });
    }
    if (document.getElementById('ch-lot')) {
      const l18 = lot.slice(0, 18);
      document.getElementById('ch-lot1').innerHTML = QK.chances(lot.filter(t => (sim[t].p_lottery_pick || [])[0] > 0).slice(0, 10).map(t => ({ label: HW.teamShort(L, t), p: sim[t].p_lottery_pick[0], href: HW.teamHref(L, t, S), mark: U.team(L, t), color: HW.teamColourRaw(L, t) })), { key: false, limit: 10 });
      const data = [];
      l18.forEach((t, yi) => (sim[t].p_lottery_pick || []).forEach((p, xi) => { data.push([xi, yi, Math.round(p * 1000) / 10]); }));
      QKC.heatmap('#ch-lot', { x: Array.from({ length: 14 }, (_, i) => String(i + 1)), y: l18.map(t => HW.teamAbbr(L, t)), data: data, min: 0, max: Math.max(15, Math.max.apply(null, data.map(d => d[2]))), labelMin: 4, fmt: v => Math.round(v) + '%', xName: 'Pick', yName: 'Team' });
    }
    if (lo && window.QKL) QKL.race(document.getElementById('ch-race'), lo);
    /* 6. the table */
    const all = [];
    confs.forEach(c => (st[c] || []).forEach(r => all.push(Object.assign({ conf: c }, r))));
    const tr = all.filter(r => sim[String(r.team)]).map(r => { const s = sim[String(r.team)]; return { team: String(r.team), nm: HW.teamShort(L, r.team), conf: r.conf, rec: HW.record(r.w, r.l), exp: s.exp_w, lo: s.w_p05, hi: s.w_p95, top6: s.p_top6, pp: s.p_playoffs, pin: s.p_playin, pc: s.p_conf, pt: s.p_title }; })
      .sort((a, b) => (b.pt || 0) - (a.pt || 0) || (b.exp || 0) - (a.exp || 0));
    const cols = [{ key: 'nm', label: 'Team', type: 'entity', mark: r => U.team(L, r.team), href: r => HW.teamHref(L, r.team, S) }, { key: 'rec', label: 'W-L', num: true, sort: false },
      { key: 'exp', label: 'Proj W', num: true, fmt: (v, r) => (isNum(v) ? '<span data-tip="' + esc(U.f(r.lo, 0) + '–' + U.f(r.hi, 0) + ' (90% range)') + '">' + U.f(v, 1) + '</span>' : '—'), tip: 'Projected wins with the 90% range' }];
    if (fmt.playin) cols.push({ key: 'top6', label: 'Top 6', num: true, fmt: v => U.pct(v), tip: 'Our chance of a top-six seed (no play-in)' });
    cols.push({ key: 'pp', label: 'Playoffs', type: 'bar', max: 1, fmt: v => U.pct(v), tip: 'Our chance of reaching the playoffs proper' });
    if (fmt.playin) cols.push({ key: 'pin', label: 'Play-in', num: true, fmt: v => U.pct(v), tip: 'Our chance of finishing in the play-in places' });
    if (!leagueWide) cols.push({ key: 'pc', label: 'Conf', num: true, fmt: v => U.pct(v), tip: 'Our chance of winning the conference' });
    cols.push({ key: 'pt', label: 'Title', num: true, fmt: v => '<b>' + U.pct(v) + '</b>' });
    QK.leaderboard(document.getElementById('ch-table'), { columns: cols, rows: tr, dense: true, rank: true, rowHref: r => HW.teamHref(L, r.team, S) });
    HW.setMeta(n.toLocaleString('en-GB') + ' simulations of the rest of the season');
  });
}

HW.chances = { tab: chancesTab };
})(window.HW);
