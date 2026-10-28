/* The Quant Ace — Overview (#/ and #/<T>), on kit v4 "Broadcast" (the Rink overview, rk-overview.js, is the reference).
 *
 *   ticker: live, today's and the next matches with our chance before the first ball, then the latest results;
 *   the intro band (what the site covers, three quick links: the draws in play, Rankings, Players);
 *   "This week in <tour> tennis": the stage line (the tournaments in play, the next big one, the Finals), then the
 *   top lines from the tour's index.json digest (scripts/build_ace.py, analytics/site.py digest): the biggest mover in
 *   the race to the Finals or the year-end No. 1 (the year-end favourite until the chance log is a day old), the upset
 *   of the week, the player of the week, the other matches that matter; then the match that
 *   matters most on the shared significance rule (digest.featured), labelled "Live now", "Tonight", "Today",
 *   "Tomorrow" or the weekday in the reader's time, never "Our pick"; with nothing big on, the race instead;
 *   tournaments in play; "N matches. Our calls." (QK.gameCard with a one-line reason each, Today / Next / Results);
 *   the black power list (QK.band + QK.hotRow: the race leader, the most titles, the Elo No. 1, the best on clay and
 *   grass); round 6, the fan stories from value.json (current year): "Breakout watch" (our breakout model's likeliest
 *   climbers, the ranking now against our forecast rank in a year), "Best player nobody talks about" (QK.spotlight: the
 *   ranking furthest behind our rating) and "Clutch or lucky?" (tiebreaks and deciding sets won over expected, the
 *   surface specialist); "Who's for real?" (QKC.quadrant: share of games won, the process, against share of matches
 *   won, the results, from value.json's luck rows); "What's that number?"; the title race in our chance only (the
 *   tournament in play, the year-end No. 1), the race to the Finals and the Elo top 10; past years: the champions.
 *   The market sits only beside our chance on match cards and the ticker, small and grey (market: 'quiet'). Our record
 *   and the calibration chart are on the Model section's "How we're doing" tab (#/<T>/calibration).
 *
 * Reads index.json (tours[T]), <T>/race.json, <T>/value.json (current year) and the in-play
 * events' <T>/events/<id>.json.
 * Cards still live or upcoming 12 hours after their start are dropped (TA.fresh): a stale snapshot never shows as
 * today. */
(function (TA) {
'use strict';

const esc = TA.esc;
const isNum = TA.isNum;
const V = () => TA.v2;
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];

/* ── the landing top (the same shape on every sport overview; the Rink's rk-overview.js is the reference) ── */

/* "Live now" | "Tonight" | "Today" | "Tomorrow" | the weekday | the date, in the reader's own time (QK.now()). */
function whenLabel(g) {
  if (!g) return '';
  if (g.status === 'live') return 'Live now';
  if (g.status === 'final') return 'Final';
  const d = new Date(g.start), now = new Date(QK.now());
  if (isNaN(d)) return '';
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
/* a date-only payload day ("2026-10-18") in en-GB without a time-zone shift */
const day = d => QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d);
const ptsOf = d => (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts';
const cap = x => { x = String(x || ''); return x.charAt(0).toUpperCase() + x.slice(1); };

/* The match that matters most, on the shared significance rule (oddsmarkets/common/featured.py rank_featured: the
 * tournament's level, the round, the start time and hour, live-ness; closeness only a small bonus), from the tour's
 * digest.featured. The builder asks tennis for more than the Home page does (a Slam, Finals or 1000 match, a 500 from
 * the quarters or a 250 final), so a 50/50 match at a minor event at 03:00 never leads. The first of "today" still
 * upcoming or live at the reader's clock, else "week"; with nothing big on, the page leads with the race instead. */
function pickFeatured(dig, cards) {
  const by = {}, now = QK.now();
  cards.forEach(c => { if (c && c.id) by[c.id] = c; });
  const ok = (c, hrs) => {
    if (!c || TA.isFinished(c)) return false;
    const d = TA.parseDate(c.date);
    if (!d || String(c.date).length <= 10) return false;
    const h = (d.getTime() - now) / 36e5;
    return TA.matchState(c) === 'live' ? h > -8 : h > -1 && h < hrs;
  };
  const F = (dig || {}).featured || {};
  const T = (F.today || []).filter(f => ok(by[f.id], 24));
  const f = T[0] || (F.week && ok(by[F.week.id], 24 * 7) ? F.week : null);
  if (!f) return null;
  return { c: by[f.id], why: f.why || [], week: !T.length, rest: T.slice(1).map(x => by[x.id]) };
}
function heroNote(T, g, c, why, info) {
  const ev = TA.eventInfo(T, c.event) || {};
  const lv = ev.level || ((info.events_now || []).filter(e => e.event === c.event)[0] || {}).level;
  const rl = TA.roundLabel(c.round), big = /^(final|semi|quarter)/i.test(rl);
  const lead = (big ? 'The ' + rl.toLowerCase() + ' of the ' : rl + ' at the ') + TA.eventName(T, c.event) + (lv ? ', ' + (lv === 'slam' ? 'a Grand Slam' : (/^[AEIOU]/.test(TA.levelLabel(lv, T)) ? 'an ' : 'a ') + TA.levelLabel(lv, T)) : '') + '.' +
    (why.filter(w => !/final|semi|quarter|knockout|play-off/.test(w)).length ? ' ' + cap(why.filter(w => !/final|semi|quarter|knockout|play-off/.test(w)).join(' and ')) + '.' : '');
  return '<b>Why this match?</b> ' + esc(lead);
}
/* the stage of the season: the tournaments in play, what is next, the Finals */
function stageLine(T, st) {
  if (!st) return '';
  const nm = e => e.name || TA.eventName(T, e.id);
  const lv = e => TA.levelLabel(e.level, T);
  const parts = [];
  const now = st.now || [];
  if (now.length) {
    const more = now.length - 1, ws = ['', 'one', 'two', 'three'];
    parts.push('In play: ' + nm(now[0]) + ' (' + lv(now[0]) + ', ' + TA.surfaceLabel(now[0].surface).toLowerCase() + ', to ' + day(now[0].end) + ')' + (more ? ', and ' + (ws[more] || more) + ' more' : '') + '.');
  }
  else parts.push('Between tournaments.');
  const nb = st.next_big, nx = st.next;
  if (nb) parts.push('Next big one: ' + nm(nb) + ' (' + lv(nb) + ') from ' + day(nb.start) + '.');
  else if (nx) parts.push('Next: ' + nm(nx) + ' (' + lv(nx) + ') from ' + day(nx.start) + '.');
  if (st.finals) parts.push('The season ends at the ' + nm(st.finals) + ', from ' + day(st.finals.start) + '.');
  else if (isNum(st.done) && isNum(st.total)) parts.push(st.done + ' of ' + st.total + ' tournaments on our calendar are done.');
  return parts.join(' ');
}
function weekTiles(T, dig, race, feat, yeFav) {
  const out = [];
  const mv = dig.movers;
  if (mv && (mv.up.length || mv.down.length)) {
    const up = mv.up[0], dn = mv.down[0], lead = up || dn, fin = mv.metric !== 'year_end_no1';
    out.push({ label: 'Biggest mover', value: TA.playerSurname(T, lead.key) + ' ' + ptsOf(lead.d), href: TA.href(T, 'race'), signal: true,
      sub: TA.playerShort(T, lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + TA.pct(lead.p, 0) + ' in our chance of ' + (fin ? 'making the Finals' : 'finishing No. 1') + ' since ' + day(mv.since) + '.' + (up && dn ? ' Biggest fall: ' + TA.playerSurname(T, dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  } else if (yeFav) {
    out.push({ label: 'Year-end No. 1', value: TA.playerSurname(T, yeFav[0]) + ' ' + TA.pct(yeFav[1], 0), href: TA.href(T, 'race'), signal: true,
      sub: TA.playerShort(T, yeFav[0]) + ' leads our race to finish the year No. 1' + (race && race.n_sims ? ', from ' + Number(race.n_sims).toLocaleString('en-GB') + ' simulated seasons' : '') + '.' });
  }
  const u = dig.upset;
  if (u) {
    const sc = u.side === 'home' ? u.hs + '–' + u.as : u.as + '–' + u.hs;
    out.push({ label: 'Upset of the week', value: TA.playerSurname(T, u.winner) + ' ' + TA.pct(u.p, 0), href: TA.matchHref(T, u.id),
      sub: TA.playerShort(T, u.winner) + ' beat ' + TA.playerShort(T, u.loser) + ' ' + sc + ' in sets on ' + QK.fmt.date(u.start) + '. We gave them ' + TA.pct(u.p, 0) + ' before the first ball.' });
  }
  const h = dig.hot;
  if (h) out.push({ label: 'Player of the week', value: TA.playerSurname(T, h.key) + ' ' + h.w + '–' + h.l, href: TA.playerHref(T, h.key),
    sub: TA.playerShort(T, h.key) + ': ' + h.w + ' win' + (h.w === 1 ? '' : 's') + ' from ' + h.gp + ' matches this week, ' + (h.margin >= 0 ? '+' : '−') + Math.abs(h.margin) + ' in sets.' });
  const rest = (feat && feat.rest || []).filter(Boolean).slice(0, 2);
  if (rest.length) out.push({ label: 'Also worth a look', value: rest.map(c => TA.playerSurname(T, c.p1) + '–' + TA.playerSurname(T, c.p2)).join(' · '), href: TA.href(T, 'calendar'), text: true,
    sub: rest.map(c => { const g = TA.kitGame(c, T), w = whenLabel(g); return w + (g.status === 'live' ? '' : ' ' + QK.fmt.time(g.start)) + ': ' + TA.roundLabel(c.round) + ', ' + TA.eventName(T, c.event); }).join('. ') + '.' });
  return out;
}

function champions(T, Y) {
  const ev = TA.EVENTS[T][String(Y)] || {};
  const ids = Object.keys(ev).filter(id => ['slam', 'finals', 'm1000'].indexOf(ev[id].level) >= 0 && ev[id].champion)
    .sort((a, b) => String(ev[a].start).localeCompare(String(ev[b].start)));
  if (!ids.length) return '';
  return TA.tableHTML([{ label: 'Tournament' }, { label: 'Level', cls: 'hide-sm' }, { label: 'Champion' }, { label: 'Runner-up', cls: 'hide-sm' }],
    ids.map(id => [{ v: ev[id].start, html: TA.eventLink(T, id, { surface: true }) }, { v: TA.levelRank(ev[id].level), html: esc(TA.levelLabel(ev[id].level, T)), cls: 'hide-sm' },
      { v: TA.playerName(T, ev[id].champion), html: TA.playerLink(T, ev[id].champion) }, { v: TA.playerName(T, ev[id].runner_up), html: ev[id].runner_up ? TA.playerLink(T, ev[id].runner_up) : '—', cls: 'hide-sm' }]), { compact: true });
}

/* ── round 6: the fan stories, from value.json (one file, already loaded for "Who's for real?") ──
 * Breakout watch: our breakout model's likeliest climbers in the next 12 months (breakout.rows p_rise12m; 15+ matches in
 * the last year, ranked inside the top 250), the ranking now against our forecast rank in a year (r12m) on a log track.
 * Best player nobody talks about: the ranking furthest behind our rating (value.rows: rank against the rank our rating
 * implies, inside the top 120), not one of the breakout cards. Clutch or lucky?: tiebreaks and deciding sets won over
 * what the player's own serve and return made likely (luck.rows season; 12+ tiebreaks, 8+ deciders), and the surface
 * specialist (a surface Elo rank far better than the overall one, 15+ matches on it). */
function rankPos(r) { return isNum(r) && r > 0 ? Math.max(0, Math.min(100, 100 * (1 - Math.log(r) / Math.log(400)))) : 0; }
function fanStories(el, T, vj) {
  const nm = pid => { const s = TA.playerShort(T, pid); return /^Player /.test(TA.playerName(T, pid)) && vj.names && vj.names[pid] ? vj.names[pid] : s; };
  const full = pid => { const s = TA.playerName(T, pid); return /^Player /.test(s) && vj.names && vj.names[pid] ? vj.names[pid] : s; };
  /* the value file's own ranking (its as_of day) on its cards, so the card and the story agree */
  const sub = (pid, age, rk) => [isNum(rk) ? 'No. ' + rk : (isNum(TA.playerRank(T, pid)) ? 'No. ' + TA.playerRank(T, pid) : ''), TA.playerCountry ? TA.playerCountry(T, pid) : '', isNum(age) ? 'age ' + Math.floor(age) : ''].filter(Boolean).join(' · ');
  const ours = QK.ours ? QK.ours({ short: true, model: 'Breakout model' }) : '';
  // breakout watch
  const B = ((vj.breakout || {}).rows || []).filter(r => isNum(r.p_rise12m) && isNum(r.rank) && r.rank <= 250 && (r.n12 || 0) >= 15 && isNum(r.r12m)).sort((a, b) => b.p_rise12m - a.p_rise12m).slice(0, 3);
  const def = (vj.breakout || {}).rise_def || {};
  const used = {};
  const bx = el.querySelector('#ov-break');
  if (bx && B.length) {
    bx.innerHTML = QK.sectionHead({ kicker: 'Breakout watch', title: 'Next year’s climbers', html: true, sub: 'The players our breakout model' + ours + ' likes most to climb the rankings in the next twelve months: where they are now, and where it sees them in a year.',
      actions: '<a class="qk-more" href="' + TA.href(T, 'value') + '">Every breakout pick</a>' }) +
      QK.storyCards(B.map(r => {
        used[r.pid] = 1;
        const goal = Math.max(1, Math.min(Math.round(r.rank * Math.exp(isNum(def.log) ? def.log : -0.405)), r.rank - (def.places || 5)));
        const trend = isNum(r.d_elo) && Math.abs(r.d_elo) >= 25 ? ' Elo ' + (r.d_elo > 0 ? 'up ' : 'down ') + Math.abs(Math.round(r.d_elo)) + ' in six months.' : '';
        const back = isNum(r.idle) && r.idle >= 60 ? ' Back from ' + Math.round(r.idle / 7) + ' weeks out, so the ranking trails the level.' : '';
        return { kicker: 'Breakout watch', name: full(r.pid), sub: sub(r.pid, r.age, r.rank), href: TA.playerHref(T, r.pid) + '?view=progression', sport: 'tennis',
          value: TA.pct(r.p_rise12m, 0), unit: 'chance of a big climb',
          from: { label: 'Ranked now', value: 'No. ' + r.rank, pos: rankPos(r.rank) }, to: { label: 'Our forecast, a year on', value: 'No. ' + Math.round(r.r12m), pos: rankPos(r.r12m) },
          text: 'A big climb means No. ' + goal + ' or better within a year.' + trend + back, link: { text: 'Progression' } };
      }), { cols: 3 }) +
      '<p class="qk-caption">' + (vj.as_of ? 'Rankings as of ' + QK.fmt.date(vj.as_of + 'T12:00:00') + ', when the model last ran. ' : '') + 'Forecasts, not promises: across 2018–2025 about ' + TA.pct(((((vj.breakout || {}).test || {})['12m'] || {}).risers || {}).hit || 0.44, 0) + ' of the model’s top picks made the climb, against ' + TA.pct(((vj.breakout || {}).base_rise || {})['12m'] || 0.19, 0) + ' of all players.</p>';
  }
  // best player nobody talks about
  const V = ((vj.value || {}).rows || []).filter(r => isNum(r.rank) && r.rank <= 120 && isNum(r.imp) && isNum(r.gap) && r.gap > 0 && !used[r.pid]).sort((a, b) => b.gap - a.gap);
  const v0 = V[0], sx = el.querySelector('#ov-spot');
  if (sx && v0) {
    used[v0.pid] = 1;
    const sf = v0.surf || {};
    const stats = [{ label: 'Elo · No. ' + v0.elo_rank + ' on tour', value: TA.num(v0.elo, 0) }].concat(['hard', 'clay', 'grass'].filter(k => sf[k] && isNum(sf[k][0])).map(k => ({ label: TA.surfaceLabel(k) + ' Elo · No. ' + sf[k][1], value: TA.num(sf[k][0], 0) })));
    sx.innerHTML = QK.spotlight({ kicker: 'Best player nobody talks about', name: full(v0.pid), sub: sub(v0.pid, v0.age, v0.rank), href: TA.playerHref(T, v0.pid),
      headline: 'Ranked No. ' + v0.rank + (vj.as_of ? ' on ' + QK.fmt.date(vj.as_of + 'T12:00:00') : '') + ', but our rating plays like the No. ' + Math.round(v0.imp) + ' player on tour.',
      text: 'Rankings add up a year of points, so time out, a light schedule or a slow start leave them behind the level. Our Elo ratings read every result, weighted by the opponent.',
      stats: stats, links: [{ href: TA.playerHref(T, v0.pid), text: 'Player page' }, { href: TA.playerHref(T, v0.pid) + '?view=progression', text: 'Progression' }, { href: TA.compareHref(T, v0.pid), text: 'Compare' }] });
  }
  // clutch or lucky?
  const L = ((vj.luck || {}).rows || []).filter(r => r && r.season);
  const tbN = r => ((r.season.tb || {}).w || 0) + ((r.season.tb || {}).l || 0), dcN = r => ((r.season.dec || {}).w || 0) + ((r.season.dec || {}).l || 0);
  const tb = L.filter(r => tbN(r) >= 12 && isNum((r.season.tb || {}).over)).sort((a, b) => b.season.tb.over - a.season.tb.over)[0];
  const dc = L.filter(r => dcN(r) >= 8 && isNum((r.season.dec || {}).over) && (!tb || r.pid !== tb.pid)).sort((a, b) => b.season.dec.over - a.season.dec.over)[0];
  let spec = null;
  ((vj.value || {}).rows || []).forEach(r => {
    if (!isNum(r.elo_rank) || !r.surf || used[r.pid]) return;
    Object.keys(r.surf).forEach(k => { const x = r.surf[k]; if (x && isNum(x[1]) && x[1] <= 30 && (x[2] || 0) >= 15) { const d = r.elo_rank - x[1]; if (d >= 15 && (!spec || d > spec.d)) spec = { r: r, k: k, x: x, d: d }; } });
  });
  const cards = [];
  if (tb) { const t = tb.season.tb; cards.push({ kicker: 'Tiebreak king', name: full(tb.pid), sub: sub(tb.pid), href: TA.playerHref(T, tb.pid), sport: 'tennis', value: '+' + TA.num(t.over, 1), unit: 'tiebreaks over expected',
    text: 'Won ' + t.w + ' of ' + (t.w + t.l) + ' tiebreaks this year; from the points they win on serve and return we would expect about ' + Math.round(t.exp) + '. Tiebreaks sit close to coin flips, so a run like this tends to cool.' }); }
  if (dc) { const t = dc.season.dec; cards.push({ kicker: 'Deciding-set specialist', name: full(dc.pid), sub: sub(dc.pid), href: TA.playerHref(T, dc.pid), sport: 'tennis', value: t.w + '–' + t.l, unit: 'in deciding sets',
    text: 'About ' + Math.round(t.exp) + ' deciding-set wins was the likely haul from their serve and return; they have ' + t.w + '. Nerve, fitness or fortune: deciders swing back more often than not.' }); }
  if (spec) cards.push({ kicker: TA.surfaceLabel(spec.k) + ' specialist', name: full(spec.r.pid), sub: sub(spec.r.pid, spec.r.age, spec.r.rank), href: TA.playerHref(T, spec.r.pid), sport: 'tennis', value: 'No. ' + spec.x[1], unit: 'on ' + TA.surfaceLabel(spec.k).toLowerCase(),
    from: { label: 'Overall Elo', value: 'No. ' + spec.r.elo_rank, pos: rankPos(spec.r.elo_rank) }, to: { label: TA.surfaceLabel(spec.k) + ' Elo', value: 'No. ' + spec.x[1], pos: rankPos(spec.x[1]) },
    text: 'No. ' + spec.r.elo_rank + ' in our overall rating, No. ' + spec.x[1] + ' on ' + TA.surfaceLabel(spec.k).toLowerCase() + ' from ' + spec.x[2] + ' matches on it. Watch the draw when the tour gets there.' });
  const cx = el.querySelector('#ov-clutch');
  if (cx && cards.length) cx.innerHTML = QK.sectionHead({ kicker: 'Clutch or lucky?', title: 'The stories behind the scores', sub: 'This year’s tiebreaks and deciding sets against what each player’s own serve and return made likely, and a player whose surface rating runs far ahead of the overall one.',
    actions: '<a class="qk-more" href="' + TA.href(T, 'value') + '?v=luck">Luck, player by player</a>' }) + QK.storyCards(cards, { cols: 3 });
}

/* Round 9 (Phase 4): records in reach, from history.json (every tour-level champion since 2000 for the ATP, 2007 for the
   WTA). For the active players (ranked inside the top 100) the closest chases on the Grand Slam and the title lists: the
   next mark above them and who holds it. The lists cover our files only, so the cards say "since <year>". Weeks at No. 1
   need the weekly rankings, which the files do not keep, so there is no card for them. */
function recordsInReach(host, T, hist, rk) {
  if (!host) return;
  /* active = in this week's official ranking (rankings.json), not a retired player's last rank on file */
  const now = {};
  (((rk && rk.ok !== false) ? rk.official : null) || []).forEach(r => { now[String(r[1])] = r[0]; });
  const ev = (hist || {}).events || {}, slam = {}, ttl = {};
  Object.keys(ev).forEach(tid => {
    const e = ev[tid] || {};
    if (e.level === 'q' || e.level === 'ch') return;
    (e.champions || []).forEach(c => { const pid = String(c[1]); ttl[pid] = (ttl[pid] || 0) + 1; if (e.level === 'slam') slam[pid] = (slam[pid] || 0) + 1; });
  });
  const since = ((TA.fk || {}).FIRST_YEAR || {})[T] || (T === 'wta' ? 2007 : 2000);
  const rank = pid => now[String(pid)];
  const active = pid => isNum(rank(pid)) && rank(pid) <= 100;
  const chases = (cnt, what) => {
    const all = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]);
    return all.filter(p => active(p) && cnt[p] >= 1).map(p => {
      const above = all.filter(q => cnt[q] > cnt[p]);
      if (!above.length) return { p: p, n: cnt[p], top: true, what: what };
      const mark = Math.min.apply(null, above.map(q => cnt[q]));
      const holders = above.filter(q => cnt[q] === mark);
      return { p: p, n: cnt[p], mark: mark, gap: mark - cnt[p], holders: holders, what: what, rec: all[0], recN: cnt[all[0]] };
    });
  };
  const sl = chases(slam, 'slam'), tl = chases(ttl, 'title');
  const pick = list => list.filter(x => !x.top).sort((a, b) => a.gap - b.gap || b.n - a.n);
  const cards = [];
  const recCard = (cnt, label) => { const all = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]); if (!all.length) return null;
    const p = all[0]; return { kicker: 'The record since ' + since, name: TA.playerName(T, p), sub: (active(p) ? 'Active · No. ' + rank(p) : 'Retired or outside the top 100') + ' · ' + TA.tourName(T), href: TA.playerHref(T, p), sport: 'tennis',
      value: String(cnt[p]), unit: label, text: (all[1] ? 'Next on the list: ' + TA.playerName(T, all[1]) + ' with ' + cnt[all[1]] + '.' : '') }; };
  const chaseCard = x => ({ kicker: x.what === 'slam' ? 'Grand Slams in reach' : 'Titles in reach', name: TA.playerName(T, x.p), sub: 'No. ' + rank(x.p) + ' · ' + TA.tourName(T), href: TA.playerHref(T, x.p), sport: 'tennis',
    value: String(x.n), unit: x.what === 'slam' ? 'Grand Slam titles since ' + since : 'tour-level titles since ' + since,
    pace: { now: x.n, target: x.mark, max: x.mark, label: 'Level with ' + TA.playerSurname(T, x.holders[0]) },
    text: x.gap + ' more to draw level with ' + x.holders.map(q => TA.playerName(T, q)).join(' and ') + ' on ' + x.mark + ', ' + (x.gap + 1) + ' to pass.' });
  const r1 = recCard(slam, 'Grand Slam titles');
  if (r1) cards.push(r1);
  pick(sl).slice(0, 2).forEach(x => cards.push(chaseCard(x)));
  pick(tl).filter(x => cards.every(c => c.name !== TA.playerName(T, x.p))).slice(0, 3 - Math.min(2, cards.length - 1)).forEach(x => cards.push(chaseCard(x)));
  if (cards.length < 2) { host.innerHTML = ''; return; }
  host.innerHTML = QK.sectionHead({ kicker: 'Records in reach', title: 'Chasing the lists', sub: 'Grand Slam and tour-level titles on our files, every champion since ' + since + ': the record, and the active players closest to the next mark above them.' }) +
    QK.storyCards(cards.slice(0, 4), { cols: Math.min(4, cards.length) }) +
    '<p class="qk-caption">Counts start in ' + since + ', the first ' + TA.tourName(T) + ' season on our files, so earlier titles are not in them. Weeks at No. 1 are not counted: our files keep the latest ranking, not every week’s.</p>';
}

function render(el, params) {
  const T = params.tour, Y = params.year;
  const info = TA.tourInfo(T);
  const isCurrent = Y === TA.currentYear(T);
  const evNow = isCurrent ? (info.events_now || []) : [];
  el.innerHTML = QK.skeleton('card', 3);
  return TA.loadAll([TA.tpath('race.json', T)].concat(evNow.map(e => TA.eventPath(T, e.event)))).then(arr => {
    if (!el.isConnected) return;
    const race = isCurrent && TA.ok(arr[0]) ? arr[0] : null;
    const evs = {};
    evNow.forEach((e, i) => { if (TA.ok(arr[1 + i])) evs[e.event] = arr[1 + i]; });
    const live = isCurrent ? TA.fresh(info.live) : [], today = isCurrent ? TA.fresh(info.today) : [];
    const upcoming = isCurrent ? TA.fresh(info.upcoming) : [], recent = isCurrent ? (info.recent || []) : [];
    const elo1 = ((info.elo_top || {}).all || [])[0];
    let no1 = null;
    Object.keys(TA.NAMES[T]).forEach(pid => { if (TA.NAMES[T][pid].rank === 1) no1 = pid; });
    let yeFav = null;
    if (race && race.year_end_no1) Object.keys(race.year_end_no1).forEach(pid => { const p = race.year_end_no1[pid]; if (isNum(p) && (!yeFav || p > yeFav[1])) yeFav = [pid, p]; });
    const ev0 = evNow.length ? evs[evNow[0].event] : null;
    const sim0 = ev0 && ev0.sim && ev0.sim.players ? ev0.sim.players : null;
    const titleRows = sim0 ? Object.keys(sim0).map(pid => ({ pid: pid, p: sim0[pid].p_title })).filter(r => isNum(r.p) && r.p > 0.002).sort((a, b) => b.p - a.p) : [];
    const ev0Name = evNow.length ? (evNow[0].name || TA.eventName(T, evNow[0].event)) : '';

    // ── head, ticker and stat tiles
    const kicker = [TA.tourName(T), Y, isCurrent ? (evNow.length ? evNow.map(e => e.name || TA.eventName(T, e.event)).join(' · ') + ' in play' : 'between tournaments') : 'season review'].join(' · ');
    const shown = {};
    const pick = list => list.filter(c => c && !shown[c.id] && (shown[c.id] = 1));
    const byDate = (a, b) => String(a.date).localeCompare(String(b.date));
    const nowList = pick(live).concat(pick(today.filter(c => !TA.isFinished(c)).sort(byDate)));
    const nextList = pick(upcoming.slice().sort(byDate));
    const doneList = pick(today.filter(TA.isFinished).sort((a, b) => String(b.date).localeCompare(String(a.date)))).concat(pick(recent.slice().sort((a, b) => String(b.date).localeCompare(String(a.date)))));
    const tick = nowList.concat(nextList).slice(0, 14).concat(doneList.slice(0, 8)).map(c => TA.kitGame(c, T));
    /* the landing top: the intro band, "This week in <tour> tennis" (the stage line and the top lines from the tour's
       index.json digest), then the match that matters most, or the race when nothing big is on */
    const tourW = T === 'wta' ? 'WTA' : 'ATP';
    const dig = isCurrent ? (info.digest || {}) : {};
    const feat = isCurrent ? pickFeatured(dig, nowList.concat(nextList)) : null;
    /* round 9: one of each module. The lead's fallback race (nothing big on) is not repeated further down, and the Elo
       leaders live in the power list only (the Elo view has the tables) */
    const used = {};
    let html = (tick.length ? '<div class="qk-ticker ta-ticker" aria-label="Scoreboard">' + QK.ticker(tick, { group: 'league', pill: false, market: 'quiet' }) + '</div>' : '') +
      intro({ tag: kicker,
        title: isCurrent ? 'Every ' + tourW + ' match, player and tournament, by the numbers.' : 'The ' + TA.tourName(T) + ' in ' + Y + ', as it finished.',
        lede: isCurrent ? 'Our chance for every match, title chances from simulating every draw, who’s for real, and the race to the Finals, in plain English.'
          : 'The ' + Y + ' season: the champions, the rankings and the ratings as they finished.',
        links: [{ label: evNow.length ? 'Draws' : 'Tournaments', sub: evNow.length ? ev0Name : 'The calendar and every draw', href: evNow.length ? TA.eventHref(T, evNow[0].event) : TA.href(T, 'calendar', Y) },
          { label: 'Rankings', sub: 'And the race to the Finals', href: TA.href(T, 'rankings', Y) }, { label: 'Scouting Room', sub: 'Every player, every metric', href: TA.href(T, 'scout', Y) }] });
    if (isCurrent) {
      const wt = weekTiles(T, dig, race, feat, yeFav);
      html += '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in ' + tourW + ' tennis', title: wt.length >= 3 ? 'The week in ' + WORDS[wt.length].toLowerCase() + ' lines' : 'The week so far', sub: stageLine(T, dig.stage) }) +
        (wt.length ? QK.stats(wt) : '') + '<div class="ql-feat">';
      if (feat) {
        const g = TA.kitGame(feat.c, T, { initials: true }), lab = whenLabel(g);
        html += QK.featureCard(g, { scribble: lab + (feat.week ? ' · The big one this week' : ' · The one to watch'), kicker: g.league + ' · ' + g.note, note: heroNote(T, g, feat.c, feat.why, info) });
      } else {
        /* nothing big on: the race leads (the race to the Finals, then the year-end No. 1), else the biggest
           tournament's title chances */
        const no1 = race && race.year_end_no1 ? Object.keys(race.year_end_no1).map(pid => ({ pid: pid, p: race.year_end_no1[pid] })).filter(r => isNum(r.p) && r.p > 0.002).sort((a, b) => b.p - a.p) : [];
        const fq = race && race.finals_qual ? Object.keys(race.finals_qual).map(pid => ({ pid: pid, p: race.finals_qual[pid] })).filter(r => isNum(r.p) && r.p > 0.01 && r.p < 0.995).sort((a, b) => b.p - a.p) : [];
        const sm = evNow.length ? 'Nothing big on right now' : 'Between tournaments';
        if (fq.length >= 3) used.fq = 1;
        else if (no1.length >= 2) used.no1 = 1;
        else if (titleRows.length) used.title = 1;
        if (fq.length >= 3) html += '<div class="ql-race">' + QK.sectionHead({ kicker: sm, title: 'So here’s the race to the Finals', sub: 'Our chance of qualifying for the ' + tourW + ' Finals, for the players still in the hunt, from simulating the rest of the season.', tag: 'h3' }) +
          QK.chances(fq.slice(0, 8).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid) })), { max: 1, key: false, oursName: 'Our chance of qualifying' }) + '</div>';
        else if (no1.length >= 2) html += '<div class="ql-race">' + QK.sectionHead({ kicker: sm, title: 'So here’s the race for No. 1', sub: 'Our chance of finishing the year ranked No. 1, from simulating the rest of the season.', tag: 'h3' }) +
          QK.chances(no1.slice(0, 6).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid) })), { max: 1, key: false, oursName: 'Our chance' }) + '</div>';
        else if (titleRows.length) html += '<div class="ql-race">' + QK.sectionHead({ kicker: sm, title: 'Who wins ' + ev0Name + '?', sub: 'Our title chances from simulating the rest of the draw.', tag: 'h3' }) +
          QK.chances(titleRows.slice(0, 6).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid) })), { key: false, oursName: 'Our title chance' }) + '</div>';
      }
      html += '</div></section>';
    }

    /* round 9: a finished season opens on its recap (ta-past.js: the champions, the Finals' last four as played with our
       calls, our call going into every big event against who won, the season-end top ten, the best by our numbers) */
    if (!isCurrent) html += '<div id="ov-recap"></div>';
    if (evNow.length) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'In play', title: 'Tournaments this week', sub: 'Open one for the draw, every path through it and our title chances from simulating the rest of it.' }) + '<div class="ta-evcards">' +
        evNow.map(e => {
          const inf = TA.eventInfo(T, e.event);
          const col = TA.surfaceColour(e.surface || inf.surface, inf.indoor);
          return '<a class="ta-evcard" href="' + TA.eventHref(T, e.event) + '" style="--sf:' + col + '"><span class="k">' + esc(TA.levelLabel(e.level || inf.level, T)) + ' · ' + esc(TA.surfaceLabel(e.surface || inf.surface, inf.indoor)) + '</span>' +
            '<b>' + esc(e.name || TA.eventName(T, e.event)) + '</b><span class="m">' + esc(TA.fmtRange(e.start, e.end)) + (e.round_now ? ' · ' + esc(TA.roundLabel(e.round_now)) : '') + '</span>' +
            (e.favourite && e.favourite[0] ? '<span class="f">Our favourite ' + esc(TA.playerShort(T, e.favourite[0])) + ' <b>' + TA.pct(e.favourite[1], 0) + '</b></span>' : '') + '</a>';
        }).join('') + '</div></section>';
    }

    if (isCurrent) {
      const first = nowList.length ? 'now' : nextList.length ? 'next' : 'results';
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch', title: '<span id="ov-gh"></span>', html: true, sub: 'Our chance for each player before the first ball, the favourite in blue, and a line on why it’s worth your time. Once it starts: the score set by set.',
        actions: V().seg('ov-when', [['now', 'Today'], ['next', 'Next'], ['results', 'Results']], first, 'Matches') + '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every draw</a>' }) +
        '<div class="qk-watch" id="ov-games"></div></section>';
    }

    // ── who's hot: from index.json and this year's champions (no extra payload)
    const hot = [];
    const rt = (info.race_top || []).filter(r => Array.isArray(r) && isNum(r[3])).sort((a, b) => b[3] - a[3]);
    if (isCurrent && rt.length) hot.push({ sport: 'tennis', title: 'Race leader', name: TA.playerShort(T, rt[0][0]), value: Math.round(rt[0][3]), unit: 'race points', next: rt[1] ? { name: TA.playerShort(T, rt[1][0]), value: Math.round(rt[1][3]) } : null, expl: 'Ranking points won this year: the race to the ' + (T === 'wta' ? 'WTA' : 'ATP') + ' Finals.', href: TA.href(T, 'race') });
    const ttl = {}, evY = TA.EVENTS[T][String(Y)] || {};
    Object.keys(evY).forEach(id => { const ch = evY[id] && evY[id].champion; if (ch && evY[id].level !== 'q') ttl[ch] = (ttl[ch] || 0) + 1; });
    const tl = Object.keys(ttl).sort((a, b) => ttl[b] - ttl[a]);
    if (tl.length) hot.push({ sport: 'tennis', title: 'Most titles in ' + Y, name: TA.playerShort(T, tl[0]), value: ttl[tl[0]], unit: ttl[tl[0]] === 1 ? 'title' : 'titles', next: tl[1] ? { name: TA.playerShort(T, tl[1]), value: ttl[tl[1]] } : null, expl: 'Tour-level titles this year, at every level.', href: TA.playerHref(T, tl[0]) });
    [['all', 'Elo No. 1', 'Our strength rating from every tour-level result; above 2,000 is rare air.'], ['clay', 'Best on clay', 'Clay Elo: the rating from clay matches only.'], ['grass', 'Best on grass', 'Grass Elo: a short season, so it moves slowly.']].forEach(x => {
      const r = (info.elo_top || {})[x[0]] || [];
      if (!r.length) return;
      hot.push({ sport: 'tennis', title: x[1], name: TA.playerShort(T, r[0][0]), value: Math.round(r[0][1]), unit: x[0] === 'all' ? 'Elo' : TA.surfaceLabel(x[0]) + ' Elo', next: r[1] ? { name: TA.playerShort(T, r[1][0]), value: Math.round(r[1][1]) } : null, expl: x[2], href: TA.playerHref(T, r[0][0]) });
    });
    if (isCurrent && hot.length >= 3) html += QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: isCurrent ? 'The form players' : 'The year’s leaders', sub: 'The leaders in the race, the trophy count and our ratings, with the next best for scale.' }) + QK.hotRow(hot.slice(0, 5)));

    // ── round 6: the fan stories (value.json, current year), then Who's for real?
    if (isCurrent) {
      html += '<section class="qk-section" id="ov-break"></section>' +
        '<section class="qk-section" id="ov-spot"></section>' +
        '<section class="qk-section" id="ov-clutch"></section>' +
        '<section class="qk-section" id="ov-records"></section>';
      html += '<section class="qk-section ta-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Winning games is the steady part of a record; turning them into match wins takes tiebreaks and deciding sets, which come and go. Top-left: winning more matches than the games suggest. Bottom-right: the reverse.' }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" style="--h:440px" role="img" aria-label="Share of matches won against share of games won">' + QK.skeleton('chart', 1) + '</div><p class="qk-caption" id="ov-luck-cap"></p></div></div></section>';
    }
    html += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against the rest of the tour: 90th means better than 90 in 100 qualified players.',
      'An <b>Elo rating</b> moves with every result: beat a stronger player, gain more. A 100-point gap makes the higher-rated player about a 64% favourite.'] }) + '</section>';

    // ── charts
    const raceRows = isCurrent && race && !used.fq ? Object.keys(race.finals_qual || {}).map(pid => ({ pid: pid, p: race.finals_qual[pid] })).filter(r => isNum(r.p)).sort((a, b) => b.p - a.p).slice(0, 12) : [];
    const eloKeys = [];
    const hasNo1 = isCurrent && race && race.year_end_no1 && Object.keys(race.year_end_no1).length && !used.no1;
    const showTitle = titleRows.length && !used.title;
    if (showTitle || hasNo1) {
      const t0 = titleRows[0];
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: showTitle ? 'Who lifts the trophy?' : 'Who finishes No. 1?',
        sub: (t0 ? (t0.p < 0.2 ? 'Nobody’s better than 1 in 5 in ' + ev0Name + '. ' : TA.playerShort(T, t0.pid) + ' leads our board in ' + ev0Name + ' at ' + TA.pct(t0.p, 0) + '. ') : '') + 'Our chances from simulating the rest of the draw and the season, match by match.',
        actions: showTitle ? '<a class="qk-more" href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path</a>' : '' }) + '<div class="qk-grid">';
      if (showTitle) html += '<div class="qk-span-6">' + V().card('Who wins ' + ev0Name, 'Our title chance from simulating the rest of the draw', '<div id="ov-title"></div>', { foot: '<span>Top ten</span><a href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path →</a>' }) + '</div>';
      if (hasNo1) html += '<div class="qk-span-6">' + V().card('Year-end No. 1', 'Our chance of finishing the year ranked No. 1', '<div id="ov-no1"></div>', { foot: '<span>From ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons</span><a href="' + TA.href(T, 'rankings') + '">Rankings →</a>' }) + '</div>';
      html += '</div></section>';
    }
    if (raceRows.length) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Race to the Finals', title: 'Who makes the ' + (T === 'wta' ? 'WTA' : 'ATP') + ' Finals?', sub: 'Our chance of qualifying from simulating the rest of the season. Tap a row to open the player.' }) + '<div class="qk-grid">';
      if (raceRows.length) html += '<div class="qk-span-8">' + V().card('Race to the Finals', 'Our chance of qualifying, from ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons', '<div id="ov-race"></div>', { foot: '<span>Race points when the season was last simulated' + (race.as_of ? ' (' + esc(TA.fmtDate(race.as_of, { year: false, weekday: false })) + ')' : '') + '</span><a href="' + TA.href(T, 'race') + '">The race →</a>' }) + '</div>';
      if (eloKeys.length) html += '<div class="qk-span-6">' + V().card('Elo top 10', 'Our strength ratings from every tour-level result', V().seg('ov-sf', eloKeys.map(k => [k, k === 'all' ? 'Overall' : TA.surfaceLabel(k)]), eloKeys[0], 'Surface') + V().chart('ov-elo', 360, 'Elo top 10'), { foot: '<span>A 100-point gap makes the higher-rated player about a 64% favourite</span><a href="' + TA.href(T, 'elo') + '">Elo tables →</a>' }) + '</div>';
      html += '</div></section>';
    }
    if (!isCurrent) {
      const ch = champions(T, Y);
      if (ch) html += '<section class="qk-section">' + QK.sectionHead({ kicker: Y, title: 'Champions', sub: 'The Slams, the Finals and the 1000s in ' + Y + '.', actions: '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every tournament</a>' }) + '<div class="qk-card">' + ch + '</div></section>';
    }
    html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Explore', title: 'More on the ' + TA.tourName(T) }) + '<div class="ov-explore">' + [
      [TA.href(T, 'scout', Y), 'Scouting Room', 'Every player ranked against the tour or one surface, on every metric'],
      [TA.href(T, 'h2h'), 'Head to head', 'Any two players, any surface'],
      [TA.href(T, 'value'), 'Value', 'Breakouts, luck, over- and undervalued players'],
      [TA.href(T, 'compare'), 'Compare', 'Two or three players side by side'],
      [TA.href(T, 'calibration'), 'How we’re doing', 'Our recent record and how often our chances came true'],
      ['#/methodology', 'Model', 'How the ratings and simulations work']
    ].map(x => '<a class="qk-card is-link ov-x" href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div></section>';

    el.innerHTML = html;
    if (!isCurrent && TA.past && TA.past.recap) TA.past.recap(el.querySelector('#ov-recap'), T, Y);

    if (isCurrent) TA.load(TA.tpath('value.json', T)).then(vj => { if (el.isConnected && TA.ok(vj)) fanStories(el, T, vj); });
    if (isCurrent) TA.loadAll([TA.tpath('history.json', T), TA.tpath('rankings.json', T)]).then(r2 => { if (el.isConnected && TA.ok(r2[0])) recordsInReach(el.querySelector('#ov-records'), T, r2[0], r2[1]); });

    /* Who's for real?: share of matches won (results) against share of games won (the process) this season, from
       value.json's luck rows (the season block), the top 40 by ranking with 15 or more tour-level matches */
    if (isCurrent && el.querySelector('#ov-luck')) {
      TA.load(TA.tpath('value.json', T)).then(vj => {
        const host = el.querySelector('#ov-luck');
        if (!host) return;
        const rows = (((TA.ok(vj) && vj.luck) || {}).rows || []).map(r => ({ pid: String(r.pid), s: r.season || {} }))
          .filter(r => isNum(r.s.games_share) && isNum(r.s.win_pct) && (r.s.n || 0) >= 15);
        const rk = r => (isNum(TA.playerRank(T, r.pid)) ? TA.playerRank(T, r.pid) : 9999);
        const top = rows.sort((a, b) => rk(a) - rk(b)).slice(0, 40);
        if (top.length < 8) { host.innerHTML = QK.empty('Not yet', 'The chart fills in once enough players have 15 matches this season.'); return; }
        const pts = top.map(r => ({ x: r.s.games_share * 100, y: r.s.win_pct * 100, label: TA.playerSurname(T, r.pid), name: TA.playerName(T, r.pid) + (isNum(TA.playerRank(T, r.pid)) ? ' · No. ' + TA.playerRank(T, r.pid) : ''),
          sub: r.s.w + '–' + (r.s.n - r.s.w) + ' this season' + (isNum(r.s.adj_win_pct) ? '; on the games won, about ' + TA.pct(r.s.adj_win_pct, 0) + ' of matches' : ''), href: TA.playerHref(T, r.pid) }));
        const avgY = pts.reduce((a, p) => a + p.y, 0) / pts.length;
        QKC.quadrant('#ov-luck', { points: pts, xName: 'Share of games won (%)', yName: 'Share of matches won (%)', refX: 50, refY: avgY,
          xFmt: v => Math.round(v) + '%', yFmt: v => Math.round(v) + '%', label: TA.tourName(T) + ' players: share of games won against share of matches won' });
        el.querySelector('#ov-luck-cap').textContent = TA.tourName(T) + ' ' + Y + ', the top ' + pts.length + ' by ranking with 15 or more tour-level matches. Dashed lines: half the games, and the group’s average match record. Tap a player for the page.';
      });
    }

    if (isCurrent) {
      const draw = w => {
        const list = w === 'next' ? nextList : w === 'results' ? doneList : nowList;
        const gh = el.querySelector('#ov-gh');
        const n = Math.min(9, list.length);
        if (gh) gh.textContent = w === 'next' ? 'Next up. Our calls.' : w === 'results' ? 'Latest results' : (n ? (WORDS[n] || n) + ' match' + (n === 1 ? '' : 'es') + '. Our calls.' : 'Today');
        el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(c => TA.matchCard(c, { tour: T, why: true })).join('')
          : QK.empty('No matches', w === 'now' ? 'Nothing on today’s schedule: see the next matches.' : w === 'next' ? 'No matches scheduled yet.' : 'No results yet.');
      };
      draw(nowList.length ? 'now' : nextList.length ? 'next' : 'results');
      QK.seg(el.querySelector('#ov-when'), draw);
    }
    if (showTitle) el.querySelector('#ov-title').innerHTML = QK.chances(titleRows.slice(0, 10).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(TA.playerRank(T, r.pid)) ? 'No. ' + TA.playerRank(T, r.pid) : '' })), { oursName: 'Our title chance', key: false });
    if (eloKeys.length) {
      const drawElo = k => {
        const rows = (info.elo_top || {})[k] || [];
        const lo = Math.min.apply(null, rows.map(r => r[1]));
        QKC.bar('#ov-elo', { cats: rows.map(r => TA.playerShort(T, r[0]) + (isNum(TA.playerRank(T, r[0])) ? ' · No. ' + TA.playerRank(T, r[0]) : '')), series: [{ name: (k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + ' Elo', data: rows.map(r => Math.round(r[1])), color: k === 'all' ? 'model' : undefined }],
          horizontal: true, labels: true, fmt: v => TA.num(v, 0), min: Math.floor((lo - 120) / 50) * 50, colors: rows.map(() => (k === 'all' ? null : TA.surfaceColour(k))).map(c => c || undefined),
          hrefs: rows.map(r => TA.playerHref(T, r[0])), labelWidth: 150, label: 'Elo top 10', valName: (k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + ' Elo', catName: 'Player' });
      };
      drawElo(eloKeys[0]);
      QK.seg(el.querySelector('#ov-sf'), drawElo);
    }
    if (raceRows.length) el.querySelector('#ov-race').innerHTML = QK.chances(raceRows.map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(((race.race || {})[r.pid] || {}).now) ? TA.num(race.race[r.pid].now, 0) + ' pts' : '' })), { max: 1, oursName: 'Our chance of qualifying', key: false });
    const n1 = el.querySelector('#ov-no1');
    if (n1) n1.innerHTML = QK.chances(Object.keys(race.year_end_no1).map(pid => ({ label: TA.playerShort(T, pid), p: race.year_end_no1[pid], href: TA.playerHref(T, pid) })), { max: 1, oursName: 'Our chance', key: false });
    if (live.length) TA.interval(() => { if (document.visibilityState === 'visible') TA.go(location.hash || '#/' + T); }, 90000);
    TA.setMeta(race && race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' season simulations' : '');
  });
}

TA.route('hub', render);
})(window.TA);
