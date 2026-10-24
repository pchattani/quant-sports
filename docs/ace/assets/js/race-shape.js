/* The Quant Ace — how the race is shaping up, and player profiles (round 5, 24 Oct 2026).
 *
 * Shared by the race (#/<T>/race), the rankings (#/<T>/rankings) and the tournament pages (#/<T>/event/<id>). Reads
 * race.json's fields from oddsmarkets/tennis/analytics/race.py (definitions in season_sim.race_extras):
 *   history   one snapshot of the simulation's chances per date (the 538-style lines and the week's movers);
 *   bounds    {pid: [Race points certain now, the most still reachable]}; status {pid: "in" | "out"}, mathematically
 *             certain only ("clinched" / "out of reach"), never the simulation's share;
 *   stakes    a chance conditioned on a result at an event in progress or starting within ten days (same simulations);
 *   week      each contender's tour-level results in the seven days to the simulation date (the movers' reasons);
 *   profiles  the season catalogue's values and percentiles (peers: the season's qualified tour players, the
 *             METRICS_SPEC tennis group), positional on profiles.keys.
 * Every builder returns an HTML string unless it says otherwise; charts mount after the HTML is in the page. */
(function (TA) {
'use strict';

const esc = TA.esc, isNum = TA.isNum;
const S = TA.shape = {};
const SURF = ['hard', 'clay', 'grass'];
const SURF_NAME = { hard: 'Hard court', clay: 'Clay', grass: 'Grass' };

/* race.json profiles -> pid -> { p: {key: pct}, v: {key: value}, qualified } | null */
S.profiles = race => {
  const pr = (race && race.profiles) || {}, keys = pr.keys || [], rows = pr.rows || {};
  const cache = {};
  return pid => {
    const r = rows[String(pid)];
    if (!r) return null;
    if (cache[pid]) return cache[pid];
    const o = { p: {}, v: {}, qualified: false };
    keys.forEach((k, i) => {
      if (k === 'qualified') { o.qualified = r[i] === 1; return; }
      const c = k.indexOf(':');
      o[k.slice(0, c)][k.slice(c + 1)] = r[i];
    });
    cache[pid] = o;
    return o;
  };
};

const ord = n => QK.ordinal(Math.round(n));
const pctTxt = p => TA.pct(p, p > 0.995 || p < 0.01 ? 1 : 0);

/* The surfaces in order of the player's percentile: [{ s, p, v }], best first. */
function surfaces(pr) {
  return SURF.map(s => ({ s: s, p: pr.p['elo_' + s], v: pr.v['elo_' + s] })).filter(x => isNum(x.p)).sort((a, b) => b.p - a.p);
}

/* Plain-English chips from a profile: [{ t, tone: 'good' | 'bad' | 'luck' | 'note', tip }], at most `max`. The cut-offs
 * are percentiles among the season's qualified players (top tenth = a strength, bottom fifth = a weak spot). */
S.chips = (pr, max) => {
  if (!pr) return [];
  const p = pr.p, v = pr.v, out = [];
  const add = (t, tone, tip) => out.push({ t: t, tone: tone, tip: tip });
  if (isNum(p.elo) && p.elo >= 95) add('Elite overall', 'good', 'Elo in the top 5% of the tour this season (' + ord(p.elo) + ' percentile).');
  if (isNum(p.hold) && p.hold >= 90) add('Big server', 'good', 'Holds serve more often than ' + Math.round(p.hold) + '% of the tour (' + TA.pct(v.hold, 0) + ' against an average returner).');
  if (isNum(p.brk) && p.brk >= 90) add('Elite returner', 'good', 'Breaks serve more often than ' + Math.round(p.brk) + '% of the tour (' + TA.pct(v.brk, 0) + ' against an average server).');
  const sf = surfaces(pr);
  if (sf.length === 3) {
    const best = sf[0], worst = sf[2];
    if (best.p >= 75 && best.p - sf[1].p >= 15) add({ hard: 'Hard-court specialist', clay: 'Clay specialist', grass: 'Grass-court threat' }[best.s], 'good',
      SURF_NAME[best.s] + ' Elo ' + TA.num(best.v, 0) + ', ' + ord(best.p) + ' percentile; the next best surface is ' + ord(sf[1].p) + '.');
    if (worst.p <= 35 && best.p - worst.p >= 30) add(SURF_NAME[worst.s] + ' is the weak spot', 'bad', SURF_NAME[worst.s] + ' Elo ' + TA.num(worst.v, 0) + ', ' + ord(worst.p) + ' percentile, against ' + ord(best.p) + ' on ' + SURF_NAME[best.s].toLowerCase() + '.');
  }
  if (isNum(p.win_v_top50) && p.win_v_top50 >= 90) add('Beats the best', 'good', 'Win % against the top 50 in the ' + ord(p.win_v_top50) + ' percentile.');
  if (isNum(p.hold) && p.hold <= 20) add('Serve is the weak spot', 'bad', 'Hold % in the ' + ord(p.hold) + ' percentile (' + TA.pct(v.hold, 0) + ').');
  if (isNum(p.brk) && p.brk <= 20) add('Return is the weak spot', 'bad', 'Break % in the ' + ord(p.brk) + ' percentile (' + TA.pct(v.brk, 0) + ').');
  if (isNum(p.win_v_top50) && p.win_v_top50 <= 15) add('Struggles v the top 50', 'bad', 'Win % against the top 50 in the ' + ord(p.win_v_top50) + ' percentile.');
  if (isNum(v.woe_pm) && v.woe_pm >= 0.05) add('Riding luck: results above rating', 'luck', TA.signed(v.wins_over_exp, 1) + ' wins over our pre-match chances in ' + v.matches + ' matches. Some of it can be real improvement the rating has not caught yet.');
  if (isNum(v.woe_pm) && v.woe_pm <= -0.05) add('Results below rating', 'luck', TA.signed(v.wins_over_exp, 1) + ' wins against our pre-match chances in ' + v.matches + ' matches: the rating says better is due.');
  if (isNum(v.tb_over) && Math.abs(v.tb_over) >= 2.5) add(v.tb_over > 0 ? 'Tiebreak luck' : 'Tiebreak bad luck', 'luck', TA.signed(v.tb_over, 1) + ' tiebreaks against what the serve and return numbers expect. Over one season this is mostly luck.');
  if (isNum(v.elo_d30) && v.elo_d30 >= 30) add('Rising: ' + TA.signed(v.elo_d30, 0) + ' Elo in 30 days', 'good', 'Overall Elo change over the last 30 days.');
  if (isNum(v.elo_d30) && v.elo_d30 <= -30) add('Cooling: ' + TA.signed(v.elo_d30, 0) + ' Elo in 30 days', 'bad', 'Overall Elo change over the last 30 days.');
  if (!pr.qualified) add('Small sample', 'note', 'Fewer tour-level matches this season than the floor for the percentiles: read them with care.');
  if (max && max <= 2) {
    /* a table cell: the top strength and the first weak spot or luck read, so the column is not all praise */
    const good = out.filter(c => c.tone === 'good'), other = out.filter(c => c.tone !== 'good');
    return good.slice(0, other.length ? max - 1 : max).concat(other.slice(0, max - Math.min(good.length, other.length ? max - 1 : max)));
  }
  return out.slice(0, max || 4);
};
S.chipHTML = list => (list || []).map(c => '<span class="rs-chip ' + c.tone + '" tabindex="0" data-tip="' + esc(c.tip) + '">' + esc(c.t) + '</span>').join('');

/* "Best at ... Weak spot ..." in one line, from the headline percentiles. */
const AREAS = [['hold', 'serve'], ['brk', 'return'], ['win_v_top50', 'results against the top 50'], ['elo_hard', 'hard courts'], ['elo_clay', 'clay'], ['elo_grass', 'grass']];
S.shortVersion = pr => {
  if (!pr) return '';
  const a = AREAS.filter(x => isNum(pr.p[x[0]])).map(x => ({ k: x[0], t: x[1], p: pr.p[x[0]] })).sort((x, y) => y.p - x.p);
  if (!a.length) return '';
  const best = a[0], worst = a[a.length - 1];
  if (worst.p >= 50) return 'Best at ' + best.t + ' (' + ord(best.p) + ' percentile); no weak spot in this set, the lowest is ' + worst.t + ' (' + ord(worst.p) + ').';
  return 'Best at ' + best.t + ' (' + ord(best.p) + ' percentile); the weak spot is ' + worst.t + ' (' + ord(worst.p) + ').';
};

/* A compact profile card: name, chips, the short version, LED meters for the headline set and a surface strip. */
S.card = (T, pid, pr, o) => {
  o = o || {};
  if (!pr) return '';
  const rows = [['elo', 'Elo', v => TA.num(v, 0)], ['hold', 'Hold', v => TA.pct(v, 0)], ['brk', 'Break', v => TA.pct(v, 0)],
    ['win_v_top50', 'Win % v top 50', null], ['games_won_pct', 'Games won', null]].map(m => ({ label: m[1], pctl: pr.p[m[0]], value: m[2] && isNum(pr.v[m[0]]) ? m[2](pr.v[m[0]]) : '' }));
  const sf = SURF.map(s => {
    const p = pr.p['elo_' + s], v = pr.v['elo_' + s];
    return '<div class="rs-sf" style="--sc:' + TA.surfaceColour(s) + '"><span class="l">' + esc(TA.surfaceLabel(s)) + '</span>' +
      (isNum(p) ? '<span class="pc" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '">' + Math.round(p) + '</span>' : '<span class="pc none">—</span>') +
      '<span class="v">' + (isNum(v) ? TA.num(v, 0) : '—') + '</span></div>';
  }).join('');
  return '<article class="rs-card">' +
    '<div class="rs-card-h"><div><a class="rs-name" href="' + TA.playerHref(T, pid) + '">' + esc(TA.playerName(T, pid)) + '</a>' +
      '<div class="rs-sub">' + esc([TA.playerCountry(T, pid), o.sub].filter(Boolean).join(' · ')) + '</div></div>' +
      (o.badge ? '<div class="rs-badge">' + o.badge + '</div>' : '') + '</div>' +
    '<div class="rs-chips">' + S.chipHTML(S.chips(pr, 4)) + '</div>' +
    '<p class="rs-short">' + esc(S.shortVersion(pr)) + '</p>' +
    QK.pctlBars(rows) +
    '<div class="rs-sfs" role="group" aria-label="Surface Elo, percentile and rating">' + sf + '</div></article>';
};
S.cardKey = () => QK.pctKey({ extra: 'percentiles among this season’s qualified tour players' });

/* ── the race ─────────────────────────────────────────────────────────────── */

/* Tiers from our chance and the certain lines: [{ key, title, sub, ids }]. */
S.tiers = (race, ids) => {
  const fq = race.finals_qual || {}, st = race.status || {};
  const T = [
    { key: 'in', title: 'Clinched', sub: 'Mathematically certain of a top-eight place', ids: [] },
    { key: 'lock', title: 'Finals locks', sub: 'In 99.5% or more of our simulations, not yet certain', ids: [] },
    { key: 'bubble', title: 'On the bubble', sub: 'Our chance between 5% and 99.5%', ids: [] },
    { key: 'long', title: 'Long shots', sub: 'Below 5%, still alive', ids: [] },
    { key: 'out', title: 'Out of reach', sub: 'Eight players are sure to finish ahead', ids: [] }];
  const at = k => T.filter(x => x.key === k)[0];
  ids.forEach(p => {
    const q = fq[p] || 0;
    if (st[p] === 'in') at('in').ids.push(p);
    else if (st[p] === 'out') at('out').ids.push(p);
    else if (q >= 0.995) at('lock').ids.push(p);
    else if (q >= 0.05) at('bubble').ids.push(p);
    else if (q >= 0.0005) at('long').ids.push(p);
  });
  return T.filter(x => x.ids.length);
};
S.tiersHTML = (T, race, ids, pts) => {
  const fq = race.finals_qual || {};
  const tiers = S.tiers(race, ids);
  if (!tiers.length) return '';
  return '<div class="rs-tiers">' + tiers.map(t => '<div class="rs-tier ' + t.key + '"><div class="rs-tier-h"><b>' + esc(t.title) + '</b><span>' + esc(t.sub) + '</span></div><ol>' +
    t.ids.slice(0, t.key === 'out' ? 6 : 10).map(p => '<li><a href="' + TA.playerHref(T, p) + '">' + esc(TA.playerShort(T, p)) + '</a><span class="n">' +
      (t.key === 'in' || t.key === 'out' ? (pts[p] ? TA.num(pts[p].pts, 0) + ' pts' : '') : pctTxt(fq[p] || 0)) + '</span></li>').join('') +
    (t.ids.length > (t.key === 'out' ? 6 : 10) ? '<li class="more">and ' + (t.ids.length - (t.key === 'out' ? 6 : 10)) + ' more</li>' : '') + '</ol></div>').join('') + '</div>';
};

/* The history as [{ as_of, finals_qual, year_end_no1 }], oldest first. */
S.history = race => ((race && race.history) || []).filter(h => h && h.as_of).sort((a, b) => String(a.as_of).localeCompare(String(b.as_of)));

/* The week's movers: the snapshot nearest seven days before the latest (at least a day older) against the latest.
 * { since, rows: [{ pid, now, was, d }] } (|d| >= 1 point), or null. */
S.movers = (race, key) => {
  const H = S.history(race);
  if (H.length < 2) return null;
  const last = H[H.length - 1], lastD = TA.parseDate(last.as_of);
  const older = H.slice(0, -1);
  const target = lastD ? lastD.getTime() - 7 * 864e5 : 0;
  const base = older.reduce((b, h) => { const t = TA.parseDate(h.as_of); return !b || Math.abs(t.getTime() - target) < Math.abs(TA.parseDate(b.as_of).getTime() - target) ? h : b; }, null);
  const a = base[key] || {}, b = last[key] || {};
  const keys = Object.keys(Object.assign({}, a, b));
  const rows = keys.map(p => ({ pid: p, now: isNum(b[p]) ? b[p] : 0, was: isNum(a[p]) ? a[p] : 0 })).map(r => Object.assign(r, { d: r.now - r.was }))
    .filter(r => Math.abs(r.d) >= 0.01).sort((x, y) => Math.abs(y.d) - Math.abs(x.d));
  return { since: base.as_of, to: last.as_of, rows: rows };
};

/* One line on a player's week: "Won Shanghai", "Lost in the semi-final at Basel", "Into the quarter-final at Paris". */
S.weekLine = (T, race, pid) => {
  const w = ((race && race.week) || {})[pid] || [];
  if (!w.length) return 'No tour-level match in the week: the line moved on other players’ results and the draws.';
  return w.map(e => {
    const ev = TA.eventLink(T, e[0]);
    if (e[2] === 'W') return 'Won ' + ev;
    if (e[2] === 'L') return 'Lost in the ' + esc(TA.roundLabel(e[1]).toLowerCase()) + ' at ' + ev;
    return 'Into the ' + esc(TA.roundLabel(e[1]).toLowerCase()) + ' at ' + ev;
  }).join('; ') + '.';
};
S.moversHTML = (T, race, key) => {
  const m = S.movers(race, key);
  const noun = key === 'year_end_no1' ? 'year-end No. 1' : 'Finals';
  if (!m) return '<p class="ta-cap" style="margin:0">Movers need two simulation dates; the first is on record, the second comes with the next build.</p>';
  if (!m.rows.length) return '<p class="ta-cap" style="margin:0">No chance of a ' + noun + ' place moved by a point or more since ' + esc(TA.fmtDate(m.since, { weekday: false, year: false })) + '.</p>';
  return '<div class="rs-movers">' + m.rows.slice(0, 6).map(r => '<div class="rs-mv ' + (r.d > 0 ? 'up' : 'down') + '">' +
    '<div class="rs-mv-h"><a href="' + TA.playerHref(T, r.pid) + '">' + esc(TA.playerShort(T, r.pid)) + '</a><b class="num" title="Percentage points">' + (r.d > 0 ? '▲ ' : '▼ ') + TA.num(Math.abs(r.d) * 100, 0) + ' pp</b></div>' +
    '<div class="rs-mv-p num">' + pctTxt(r.was) + ' → ' + pctTxt(r.now) + '</div>' +
    '<div class="rs-mv-why">' + S.weekLine(T, race, r.pid) + '</div></div>').join('') + '</div>' +
    '<p class="ta-cap">Our chance of ' + (key === 'year_end_no1' ? 'finishing the year No. 1' : 'qualifying') + ', ' + esc(TA.fmtDate(m.since, { weekday: false, year: false })) + ' to ' + esc(TA.fmtDate(m.to, { weekday: false, year: false })) +
    '; the change in percentage points (pp). The reason line lists the player’s own tour-level results in the seven days to the latest simulation.</p>';
};

/* What is at stake: the stakes rows for a metric (optionally one event), biggest swing first. */
S.stakeRows = (race, metric, eid) => ((race && race.stakes) || []).filter(r => r.metric === metric && (!eid || r.event === eid))
  .sort((a, b) => (b.if_win - b.if_lose) - (a.if_win - a.if_lose));
function swingBar(r) {
  const x = v => Math.max(0, Math.min(100, v * 100)).toFixed(1) + '%';
  return '<div class="rs-swing" role="img" aria-label="' + esc('Our chance now ' + pctTxt(r.p) + '; if the match is lost ' + pctTxt(r.if_lose) + '; if won ' + pctTxt(r.if_win)) + '">' +
    '<span class="track"></span><span class="span" style="left:' + x(Math.min(r.if_lose, r.if_win)) + ';width:' + Math.abs(r.if_win - r.if_lose) * 100 + '%"></span>' +
    '<span class="m lose" style="left:' + x(r.if_lose) + '"></span><span class="m now" style="left:' + x(r.p) + '"></span><span class="m win" style="left:' + x(r.if_win) + '"></span></div>';
}
S.stakesHTML = (T, race, metric, o) => {
  o = o || {};
  const all = S.stakeRows(race, metric, o.event), seen = {}, also = {};
  const rows = all.filter(r => {
    if (seen[r.pid]) { (also[r.pid] = also[r.pid] || []).push(r); return false; }
    seen[r.pid] = 1;
    return true;
  }).slice(0, o.limit || 8);
  const evName = id => TA.eventInfo(T, id).name || ((race.remaining_events || []).filter(x => x && x.id === id)[0] || {}).name || TA.eventName(T, id);
  if (!rows.length) return '';
  const noun = metric === 'year_end_no1' ? 'year-end No. 1' : 'qualifying';
  return '<div class="rs-stakes">' + rows.map(r => {
    const e = TA.eventInfo(T, r.event);
    const rem = ((race.remaining_events || []).filter(x => x && x.id === r.event)[0]) || {};
    const lvl = e.level || rem.level, start = e.start || rem.start;
    const nx = r.next;
    const first = r.in_progress ? 'next match' : 'first match';
    const when = r.in_progress ? (nx ? 'Next: ' + esc(TA.roundLabel(nx.round).toLowerCase()) + (nx.opp ? ' v ' + TA.playerLink(T, nx.opp, { short: true }) : '') : 'Under way') :
      'Starts ' + esc(TA.fmtDate(start, { weekday: false, year: false })) + ' · plays it in ' + TA.pct(r.p_enter, 0) + ' of our simulations';
    return '<div class="rs-stake"><div class="rs-stake-h"><a class="who" href="' + TA.playerHref(T, r.pid) + '">' + esc(TA.playerShort(T, r.pid)) + '</a>' +
      '<span class="at">at ' + TA.eventLink(T, r.event, { surface: true, name: e.name || rem.name }) + (lvl ? ' <span class="lvl">' + esc(TA.levelShort(lvl)) + '</span>' : '') + '</span>' +
      '<b class="sw num" title="Chance if the ' + first + ' is won minus chance if it is lost">' + TA.num((r.if_win - r.if_lose) * 100, 0) + ' pp swing</b></div>' +
      swingBar(r) +
      '<div class="rs-stake-n"><span class="lose">Loses the ' + first + ': <b>' + pctTxt(r.if_lose) + '</b></span><span class="now">Now: <b>' + pctTxt(r.p) + '</b></span>' +
      '<span class="win">Wins it: <b>' + pctTxt(r.if_win) + '</b></span>' + (isNum(r.if_title) ? '<span>Title: <b>' + pctTxt(r.if_title) + '</b></span>' : '') +
      (isNum(r.if_skip) && !r.in_progress ? '<span>Skips it: <b>' + pctTxt(r.if_skip) + '</b></span>' : '') + '</div>' +
      '<div class="rs-stake-w">' + when + '</div>' +
      ((also[r.pid] || []).length ? '<div class="rs-stake-w">Also: ' + also[r.pid].map(a => esc(evName(a.event)) + ' ' + TA.num((a.if_win - a.if_lose) * 100, 0) + ' pp').join(' · ') + '</div>' : '') + '</div>';
  }).join('') + '</div>' +
    '<p class="ta-cap">Our chance of ' + noun + ' in the simulations where the player loses the ' + (rows.some(r => r.in_progress) ? 'next' : 'first') + ' match there (red-orange), where the player wins it (blue), and now (volt tick). ' +
    'Same simulations, split by the result: nothing here is a separate model.</p>';
};

/* The certain lines in words: what is left on the calendar, who has clinched, who is out. */
S.clinchHTML = (T, race, ids) => {
  const left = race.left || {}, st = race.status || {};
  const inn = ids.filter(p => st[p] === 'in'), out = ids.filter(p => st[p] === 'out');
  const names = l => l.map(p => esc(TA.playerSurname(T, p))).join(', ');
  const parts = [];
  if (isNum(left.future_max)) parts.push('<b>' + TA.num((left.future_max || 0) + (left.in_progress_max ? 0 : 0), 0) + ' Race points</b> are still on offer to a player who wins one event a week on the calendar left' +
    (left.in_progress_max ? ', plus whatever the events under way still pay those in them' : '') + '.');
  parts.push(inn.length ? 'Clinched: ' + names(inn) + '.' : 'Nobody has clinched a place yet: enough players can still pass even the leader on points.');
  if (out.length) parts.push('Out of reach: ' + names(out.slice(0, 8)) + (out.length > 8 ? ' and ' + (out.length - 8) + ' more' : '') + '.');
  return QK.explain(parts.join(' ') + ' “Clinched” and “out of reach” are certain, whatever happens; “in every simulation” is our model’s 99.5% or more, which is not the same thing.', { title: 'Clinch lines.', html: true });
};

/* ── shape of the tour ────────────────────────────────────────────────────── */

/* Serve v return quadrant (charts mount after the HTML): returns { html, draw() }. */
S.quadrant = (T, race, ids, id) => {
  const prof = S.profiles(race);
  const pts = ids.map(p => ({ p: p, r: prof(p) })).filter(x => x.r && isNum(x.r.v.serve_rating) && isNum(x.r.v.return_rating)).slice(0, 24);
  if (pts.length < 5) return { html: '', draw: () => {} };
  return {
    html: TA.v2.chart(id, 420, 'Serve rating against return rating'),
    draw: () => QKC.quadrant('#' + id, {
      points: pts.map(x => ({ x: x.r.v.serve_rating, y: x.r.v.return_rating, name: TA.playerName(T, x.p), label: TA.playerSurname(T, x.p), href: TA.playerHref(T, x.p),
        sub: 'Hold ' + TA.pct(x.r.v.hold, 0) + ', break ' + TA.pct(x.r.v.brk, 0) })),
      xName: 'Serve rating (log-odds, 0 = tour average)', yName: 'Return rating (log-odds, 0 = tour average)', refX: 'mean', refY: 'mean',
      xFmt: v => TA.num(v, 2), yFmt: v => TA.num(v, 2),
      corners: { tl: 'Return first', tr: 'Complete game', bl: 'Below this group on both', br: 'Serve first' },
      label: 'Serve rating against return rating, this season' })
  };
};

/* Surface strengths: the contenders' hard, clay and grass Elo with their percentiles, strongest surface marked. */
S.surfaceHTML = (T, race, ids) => {
  const prof = S.profiles(race);
  const rows = ids.map(p => ({ p: p, r: prof(p) })).filter(x => x.r).slice(0, 16);
  if (!rows.length) return '';
  return TA.tableHTML([{ label: 'Player' }].concat(SURF.map(s => ({ label: TA.surfaceLabel(s), align: 'right', title: TA.surfaceLabel(s) + ' Elo with its percentile among the season’s qualified players' })), [{ label: 'Best surface', cls: 'hide-sm' }]),
    rows.map(x => {
      const sf = surfaces(x.r);
      return [{ v: TA.playerName(T, x.p), html: TA.playerLink(T, x.p, { short: true }) }].concat(SURF.map(s => {
        const p = x.r.p['elo_' + s], v = x.r.v['elo_' + s];
        return { v: p, html: '<span class="rs-cell">' + TA.pctPill(p) + '<span class="num">' + (isNum(v) ? TA.num(v, 0) : '—') + '</span></span>' };
      }), [{ v: sf.length ? sf[0].s : '', html: sf.length ? TA.surfaceChip(sf[0].s) : '—', cls: 'hide-sm' }]);
    }), { compact: true });
};

/* Ranking movers (official, since the previous ranking) and rating movers (Elo, last 30 days). */
S.moversRankHTML = (T, rk, race) => {
  const prof = S.profiles(race);
  const off = ((rk && rk.official) || []).filter(r => r[0] <= 100 && isNum(r[3]) && r[3] !== 0);
  const up = off.slice().sort((a, b) => b[3] - a[3] || a[0] - b[0]).slice(0, 5), dn = off.slice().sort((a, b) => a[3] - b[3] || a[0] - b[0]).slice(0, 5);
  const top = ((rk && rk.official) || []).filter(r => r[0] <= 50).map(r => ({ p: r[1], d: (prof(r[1]) || { v: {} }).v.elo_d30 })).filter(x => isNum(x.d));
  const eup = top.slice().sort((a, b) => b.d - a.d).slice(0, 5), edn = top.slice().sort((a, b) => a.d - b.d).slice(0, 5);
  const list = (rows, f) => '<ol class="rs-list">' + rows.map(f).join('') + '</ol>';
  const li = (p, txt, cls) => '<li><a href="' + TA.playerHref(T, p) + '">' + esc(TA.playerShort(T, p)) + '</a><span class="num ' + cls + '">' + txt + '</span></li>';
  const col = (h, body) => '<div class="rs-col"><div class="rs-col-h">' + esc(h) + '</div>' + body + '</div>';
  const prev = rk && rk.previous && rk.previous.date ? ' since ' + TA.fmtDate(rk.previous.date, { weekday: false, year: false }) : '';
  return '<div class="rs-cols">' +
    (up.length ? col('Ranking climbers' + prev, list(up, r => li(r[1], '▲' + r[3] + ' to No. ' + r[0], 'mv-up'))) : '') +
    (dn.length && dn[0][3] < 0 ? col('Ranking fallers' + prev, list(dn.filter(r => r[3] < 0), r => li(r[1], '▼' + Math.abs(r[3]) + ' to No. ' + r[0], 'mv-down'))) : '') +
    (eup.length ? col('Rating risers, 30 days (top 50)', list(eup.filter(x => x.d > 0), x => li(x.p, TA.signed(x.d, 0) + ' Elo', 'mv-up'))) : '') +
    (edn.length ? col('Rating fallers, 30 days (top 50)', list(edn.filter(x => x.d < 0), x => li(x.p, TA.signed(x.d, 0) + ' Elo', 'mv-down'))) : '') + '</div>';
};

/* The profile cards for a list of players, `n` shown, the rest behind a button. Wires itself on `root`. */
S.cardsHTML = (T, race, ids, o) => {
  o = o || {};
  const prof = S.profiles(race);
  const list = ids.filter(p => prof(p));
  if (!list.length) return '';
  const n = o.n || 8;
  return '<div class="rs-cards" data-n="' + n + '">' + list.map((p, i) => '<div class="rs-cw' + (i >= n ? ' rs-more' : '') + '">' + S.card(T, p, prof(p), { sub: o.sub ? o.sub(p) : '', badge: o.badge ? o.badge(p) : '' }) + '</div>').join('') + '</div>' +
    (list.length > n ? '<button type="button" class="qk-btn rs-show">Show all ' + list.length + '</button>' : '') + S.cardKey();
};
S.wire = root => {
  root.querySelectorAll('.rs-show').forEach(b => b.addEventListener('click', () => {
    const box = b.previousElementSibling;
    if (box) box.classList.add('open');
    b.remove();
  }));
  if (QK.tooltips) QK.tooltips(root);
};

})(window.TA);
