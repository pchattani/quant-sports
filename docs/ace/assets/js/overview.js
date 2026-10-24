/* The Quant Ace — Overview (#/ and #/<T>), on kit v4 "Broadcast" (the Rink overview, rk-overview.js, is the reference).
 *
 *   ticker: live, today's and the next matches with our chance before the first ball, then the latest results;
 *   the intro band (what the site covers, three quick links: the draws in play, Rankings, Players);
 *   "This week in <tour> tennis": the stage line (the tournaments in play, the next big one, the Finals), then the
 *   top lines from the tour's index.json digest (scripts/build_ace.py, analytics/site.py digest): the biggest mover in
 *   the race to the Finals or the year-end No. 1 (the year-end favourite until the chance log is a day old), the upset
 *   of the week, the player of the week, our record this week, the other matches that matter; then the match that
 *   matters most on the shared significance rule (digest.featured), labelled "Live now", "Tonight", "Today",
 *   "Tomorrow" or the weekday in the reader's time, never "Our pick"; with nothing big on, the race instead;
 *   tournaments in play; "N matches. Our calls." (QK.gameCard with a one-line reason each, Today / Next / Results);
 *   the black power list (QK.band + QK.hotRow: the race leader, the most titles, the Elo No. 1, the best on clay and
 *   grass); "We say it. Then we check it." (QK.howSure from <T>/calibration.json) beside "Who's for real?"
 *   (QKC.quadrant: share of games won, the process, against share of matches won, the results, from value.json's
 *   luck rows; tennis has no xG, and games won is the steadier number that match wins drift back to); "What's that
 *   number?"; the title race in our chance only (the tournament in play, the year-end No. 1), the race to the Finals
 *   and the Elo top 10; past years: the champions. No market anywhere on the page.
 *
 * Reads index.json (tours[T]), <T>/race.json, <T>/calibration.json, <T>/value.json (current year) and the in-play
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
  let sure = '';
  const p1 = (c.model || {}).p1;
  if (g.status !== 'live' && isNum(p1)) {
    const fav = p1 >= 0.5 ? c.p1 : c.p2, other = p1 >= 0.5 ? c.p2 : c.p1, pf = Math.max(p1, 1 - p1), miss = Math.max(1, Math.round(10 * (1 - pf)));
    sure = ' <b>How sure are we?</b> ' + TA.pct(pf, 0) + ' for ' + esc(TA.playerSurname(T, fav)) + ' means ' + esc(TA.playerSurname(T, other)) + ' wins a match like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.';
  }
  return '<b>Why this match?</b> ' + esc(lead) + sure;
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
  const r = dig.record;
  if (r) {
    const diff = r.won - r.expected;
    out.push({ label: 'Our record this week', value: r.won + ' of ' + r.n, href: TA.href(T, 'calibration'),
      sub: 'Our favourites won ' + r.won + ' of ' + r.n + ' matches; we expected ' + QK.fmt.num(r.expected, 0) + '. ' + (Math.abs(diff) < 2 ? 'Right on our numbers.' : diff > 0 ? 'A good week for the favourites.' : 'A week of upsets: a 60% call still misses 4 times in 10.') });
  }
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
    let html = (tick.length ? '<div class="qk-ticker ta-ticker" aria-label="Scoreboard">' + QK.ticker(tick, { group: 'league', pill: false }) + '</div>' : '') +
      intro({ tag: kicker,
        title: isCurrent ? 'Every ' + tourW + ' match, player and tournament, by the numbers.' : 'The ' + TA.tourName(T) + ' in ' + Y + ', as it finished.',
        lede: isCurrent ? 'Our chance for every match, title chances from simulating every draw, who’s for real, and the race to the Finals, in plain English.'
          : 'The ' + Y + ' season: the champions, the rankings and the ratings as they finished.',
        links: [{ label: evNow.length ? 'Draws' : 'Tournaments', sub: evNow.length ? ev0Name : 'The calendar and every draw', href: evNow.length ? TA.eventHref(T, evNow[0].event) : TA.href(T, 'calendar', Y) },
          { label: 'Rankings', sub: 'And the race to the Finals', href: TA.href(T, 'rankings', Y) }, { label: 'Players', sub: 'Ratings and percentiles', href: TA.href(T, 'players', Y) }] });
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
        if (fq.length >= 3) html += '<div class="ql-race">' + QK.sectionHead({ kicker: sm, title: 'So here’s the race to the Finals', sub: 'Our chance of qualifying for the ' + tourW + ' Finals, for the players still in the hunt, from simulating the rest of the season.', tag: 'h3' }) +
          QK.chances(fq.slice(0, 8).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid) })), { max: 1, key: false, oursName: 'Our chance of qualifying' }) + '</div>';
        else if (no1.length >= 2) html += '<div class="ql-race">' + QK.sectionHead({ kicker: sm, title: 'So here’s the race for No. 1', sub: 'Our chance of finishing the year ranked No. 1, from simulating the rest of the season.', tag: 'h3' }) +
          QK.chances(no1.slice(0, 6).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid) })), { max: 1, key: false, oursName: 'Our chance' }) + '</div>';
        else if (titleRows.length) html += '<div class="ql-race">' + QK.sectionHead({ kicker: sm, title: 'Who wins ' + ev0Name + '?', sub: 'Our title chances from simulating the rest of the draw.', tag: 'h3' }) +
          QK.chances(titleRows.slice(0, 6).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid) })), { key: false, oursName: 'Our title chance' }) + '</div>';
      }
      html += '</div></section>';
    }

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
    if (hot.length >= 3) html += QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: isCurrent ? 'The form players' : 'The year’s leaders', sub: 'The leaders in the race, the trophy count and our ratings, with the next best for scale.' }) + QK.hotRow(hot.slice(0, 5)));

    // ── We say it. Then we check it. (fills when <T>/calibration.json is there) beside Who's for real? (current year)
    html += '<section class="qk-section qk-g75"><div><div id="ov-sure-h"></div><div id="ov-sure"></div></div>' +
      (isCurrent ? '<div class="ta-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Winning games is the steady part of a record; turning them into match wins takes tiebreaks and deciding sets, which come and go. Top-left: winning more matches than the games suggest. Bottom-right: the reverse.' }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Share of matches won against share of games won">' + QK.skeleton('chart', 1) + '</div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div>' : '<div></div>') + '</section>';
    html += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against the rest of the tour: 90th means better than 90 in 100 qualified players.',
      'Every forecast is checked against what happened. <a class="qk-link" href="' + TA.href(T, 'calibration') + '">The record is on the calibration page.</a>'] }) + '</section>';

    // ── charts
    const raceRows = isCurrent && race ? Object.keys(race.finals_qual || {}).map(pid => ({ pid: pid, p: race.finals_qual[pid] })).filter(r => isNum(r.p)).sort((a, b) => b.p - a.p).slice(0, 12) : [];
    const eloKeys = ['all', 'hard', 'clay', 'grass'].filter(k => ((info.elo_top || {})[k] || []).length);
    const hasNo1 = isCurrent && race && race.year_end_no1 && Object.keys(race.year_end_no1).length;
    if (titleRows.length || hasNo1) {
      const t0 = titleRows[0];
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: titleRows.length ? 'Who lifts the trophy?' : 'Who finishes No. 1?',
        sub: (t0 ? (t0.p < 0.2 ? 'Nobody’s better than 1 in 5 in ' + ev0Name + '. ' : TA.playerShort(T, t0.pid) + ' leads our board in ' + ev0Name + ' at ' + TA.pct(t0.p, 0) + '. ') : '') + 'Our chances from simulating the rest of the draw and the season, match by match.',
        actions: titleRows.length ? '<a class="qk-more" href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path</a>' : '' }) + '<div class="qk-grid">';
      if (titleRows.length) html += '<div class="qk-span-6">' + V().card('Who wins ' + ev0Name, 'Our title chance from simulating the rest of the draw', '<div id="ov-title"></div>', { foot: '<span>Top ten</span><a href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path →</a>' }) + '</div>';
      if (hasNo1) html += '<div class="qk-span-6">' + V().card('Year-end No. 1', 'Our chance of finishing the year ranked No. 1', '<div id="ov-no1"></div>', { foot: '<span>From ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons</span><a href="' + TA.href(T, 'rankings') + '">Rankings →</a>' }) + '</div>';
      html += '</div></section>';
    }
    if (raceRows.length || eloKeys.length) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Race and ratings', title: 'Who makes the ' + (T === 'wta' ? 'WTA' : 'ATP') + ' Finals?', sub: 'Our chance of qualifying from simulating the rest of the season, beside our strength ratings. Tap a row to open the player.' }) + '<div class="qk-grid">';
      if (raceRows.length) html += '<div class="qk-span-6">' + V().card('Race to the Finals', 'Our chance of qualifying, from ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons', '<div id="ov-race"></div>', { foot: '<span>Race points when the season was last simulated' + (race.as_of ? ' (' + esc(TA.fmtDate(race.as_of, { year: false, weekday: false })) + ')' : '') + '</span><a href="' + TA.href(T, 'race') + '">The race →</a>' }) + '</div>';
      if (eloKeys.length) html += '<div class="qk-span-6">' + V().card('Elo top 10', 'Our strength ratings from every tour-level result', V().seg('ov-sf', eloKeys.map(k => [k, k === 'all' ? 'Overall' : TA.surfaceLabel(k)]), eloKeys[0], 'Surface') + V().chart('ov-elo', 360, 'Elo top 10'), { foot: '<span>A 100-point gap makes the higher-rated player about a 64% favourite</span><a href="' + TA.href(T, 'elo') + '">Elo tables →</a>' }) + '</div>';
      html += '</div></section>';
    }
    if (!isCurrent) {
      const ch = champions(T, Y);
      if (ch) html += '<section class="qk-section">' + QK.sectionHead({ kicker: Y, title: 'Champions', sub: 'The Slams, the Finals and the 1000s in ' + Y + '.', actions: '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every tournament</a>' }) + '<div class="qk-card">' + ch + '</div></section>';
    }
    html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Explore', title: 'More on the ' + TA.tourName(T) }) + '<div class="ov-explore">' + [
      [TA.href(T, 'players', Y), 'Players', 'Ranked against their tour on the metrics that predict'],
      [TA.href(T, 'h2h'), 'Head to head', 'Any two players, any surface'],
      [TA.href(T, 'value'), 'Value', 'Breakouts, luck, over- and undervalued players'],
      [TA.href(T, 'compare'), 'Compare', 'Two or three players side by side'],
      [TA.href(T, 'calibration'), 'Calibration', 'How often our chances came true'],
      ['#/methodology', 'Model', 'How the ratings and simulations work']
    ].map(x => '<a class="qk-card is-link ov-x" href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div></section>';

    el.innerHTML = html;

    /* We say it. Then we check it.: the match model's record from <T>/calibration.json (QK.howSure: the big numbers
       over the we-said / it-happened bars); nothing when the file is absent. The full record is on the calibration page. */
    TA.load(TA.tpath('calibration.json', T)).then(cj => {
      const box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
      const cb = box && TA.ok(cj) ? QK.calib.find(cj) : null;
      if (!box) return;
      if (!cb || !cb.bins.length) { box.innerHTML = ''; hd.innerHTML = ''; return; }
      const ys = (cj.years || []).slice().sort();
      hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every ' + TA.tourName(T) + ' match we have forecast' + (ys.length ? ' since ' + ys[0] : '') + ', grouped by the chance we gave a player. When the two lines match, our numbers mean what they say.',
        actions: '<a class="qk-more" href="' + TA.href(T, 'calibration') + '">The full record</a>' });
      QK.howSure(box, { calibration: cj, league: TA.tourName(T), span: ys.length ? ys[0] + '–' + ys[ys.length - 1] : '', subject: 'that player', unit: 'matches' });
    });

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
    if (titleRows.length) el.querySelector('#ov-title').innerHTML = QK.chances(titleRows.slice(0, 10).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(TA.playerRank(T, r.pid)) ? 'No. ' + TA.playerRank(T, r.pid) : '' })), { oursName: 'Our title chance', key: false });
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
