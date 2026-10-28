/* The Quant Rink — Overview (#/), the kit v4 "Broadcast" landing page (the reference for every sport's overview).
 *
 *   1. the intro band: what the site covers and how to use it, with three quick links (Games, Playoff race, Players);
 *   2. "This week in the NHL": the stage of the season, then the top lines from index.json "digest" (built by
 *      scripts/build_rink.py with oddsmarkets/common/digest.py): the biggest playoff-chance movers, the upset of the
 *      week, the team of the week and the other games that matter;
 *   3. the game that matters most, by significance (digest.featured from the shared rule; a stand-in on stakes until
 *      the payload carries it), as the diagonal split hero, labelled "Live now", "Tonight" (only when it truly is
 *      tonight in the reader's time), "Today", "Tomorrow" or the weekday; with nothing big on, the Cup race instead;
 *   4. "N games. Our calls." (the market quiet under our chance); the black power list (Who's hot); Breakout watch;
 *      "Who's for real?" beside the records in reach and the biggest surprise; the best player nobody talks about;
 *      "What's that number?"; "Who lifts the Cup?" with projected points; the playoff race and standings (round 9:
 *      the leader boards, a repeat of Who's hot, left for the Scouting Room's Leaders); a small link to the Model page's "How we're doing" (round 6: our record and calibration live there).
 *
 * Reads index.json, <S>/season.json, <S>/markets.json (our Cup chances only); then, lazily, <S>/leaders.json, last
 * season's leaders.json, <S>/performers.json, race_log.json and a few player files (the fan modules). Refreshes
 * every minute while a game is live. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];

/* ── the landing top (the same shape on every sport overview) ──────────────────────────────────────────────── */

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
const nick = ab => (U.nick ? U.nick(ab) : RK.teamName(ab));
const teamFull = ab => { const t = (RK.index().teams || {})[ab] || {}; return { full: t.name || RK.teamName(ab), alt: t.alt || null }; };
function heroGame(c, rows) {
  const g = U.gameV2(c, null, rows);
  [['home', c.home], ['away', c.away]].forEach(x => { const f = teamFull(x[1]); g[x[0]].full = f.full; if (f.alt) g[x[0]].alt = f.alt; });
  return g;
}
function allCards(idx) {
  const seen = {}, out = [];
  (idx.live || []).concat(idx.today || [], idx.upcoming || []).forEach(c => { if (c && !seen[c.game_id]) { seen[c.game_id] = 1; out.push(c); } });
  return out;
}
const pctOf = p => U.pct(p);
/* a date-only payload day ("2027-04-10") in en-GB without a time-zone shift */
const day = d => QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d);
const ptsOf = d => (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts';

/* The game that matters most, on the shared significance rule (oddsmarkets/common/featured.py rank_featured: the
 * league tier, the stage, the stakes in our simulations, the start time and hour, live-ness; closeness only a small
 * bonus), from index.json digest.featured: the first of "today" still upcoming or live at the reader's clock, else
 * "next" (the big games later in the week), else "week" (the biggest game of the next seven days). An older payload without it gets a stand-in on the same lines
 * from the playoff and Cup chances. With nothing big, the page leads with the race instead. */
function stakesWhy(c, odds) {
  const a = odds[c.away] || {}, h = odds[c.home] || {};
  const pa = a.p_playoffs, ph = h.p_playoffs;
  if (isNum(pa) && isNum(ph) && pa > 0.25 && pa < 0.75 && ph > 0.25 && ph < 0.75) return 'Both clubs sit near the playoff line: our playoff chances ' + RK.teamAbbr(c.away) + ' ' + pctOf(pa) + ', ' + RK.teamAbbr(c.home) + ' ' + pctOf(ph) + '.';
  if ((a.p_cup || 0) >= 0.05 && (h.p_cup || 0) >= 0.05) return 'Two of our Cup contenders: ' + RK.teamAbbr(c.away) + ' ' + pctOf(a.p_cup) + ' and ' + RK.teamAbbr(c.home) + ' ' + pctOf(h.p_cup) + ' to lift it.';
  const top = (a.p_cup || 0) >= (h.p_cup || 0) ? [c.away, a, c.home, h] : [c.home, h, c.away, a];
  if ((top[1].p_cup || 0) >= 0.08) return RK.teamName(top[0]) + ', ' + pctOf(top[1].p_cup) + ' to lift the Cup in our simulations, against ' + RK.teamName(top[2]) + (isNum(top[3].p_playoffs) ? ' (' + pctOf(top[3].p_playoffs) + ' to make the playoffs)' : '') + '.';
  if (isNum(pa) && isNum(ph)) return 'The most at stake on the slate in our season simulations: playoff chances ' + RK.teamAbbr(c.away) + ' ' + pctOf(pa) + ', ' + RK.teamAbbr(c.home) + ' ' + pctOf(ph) + '.';
  return '';
}
function stakeScore(c, odds) {
  const a = odds[c.away] || {}, h = odds[c.home] || {};
  const u = p => (isNum(p) ? 4 * p * (1 - p) : 0.5);
  return 10 * (u(a.p_playoffs) + u(h.p_playoffs)) + 60 * ((a.p_cup || 0) + (h.p_cup || 0));
}
function reasonsWhy(r, c, odds) {
  const lead = (r || []).filter(Boolean).join(' and ');
  if (!lead) return stakesWhy(c, odds);
  const a = odds[c.away] || {}, h = odds[c.home] || {}, A = RK.teamAbbr(c.away), H = RK.teamAbbr(c.home);
  const nums = [isNum(a.p_playoffs) && isNum(h.p_playoffs) ? 'our playoff chances ' + A + ' ' + pctOf(a.p_playoffs) + ', ' + H + ' ' + pctOf(h.p_playoffs) : '',
    isNum(a.p_cup) && isNum(h.p_cup) ? 'to lift the Cup ' + A + ' ' + pctOf(a.p_cup) + ', ' + H + ' ' + pctOf(h.p_cup) : ''].filter(Boolean).join('; ');
  return lead.charAt(0).toUpperCase() + lead.slice(1) + (nums ? ': ' + nums : '') + '.';
}
function pickFeatured(idx) {
  const cards = allCards(idx), by = {}, now = QK.now(), odds = idx.playoff_odds || {};
  cards.forEach(c => { by[c.game_id] = c; });
  /* playable at the reader's clock: live (and started under 8 hours ago: an older "live" is a stale snapshot), or
     starting within `hrs` hours (an hour's grace after the start) */
  const ok = (c, hrs) => { if (!c) return false; const st = U.status(c); if (st === 'final') return false; const h = (Date.parse(c.start) - now) / 36e5; return st === 'live' ? h > -8 : h > -1 && h < hrs; };
  const F = (idx.digest || {}).featured;
  if (F && (F.today || F.week)) {
    const T = (F.today || []).filter(f => ok(by[f.id], 24)), N = (F.next || []).filter(f => ok(by[f.id], 24 * 7));
    const f = T[0] || N[0] || (F.week && ok(by[F.week.id], 24 * 7) ? F.week : null);
    if (!f) return { c: null, big: false, rest: [] };
    return { c: by[f.id], why: reasonsWhy(f.why, by[f.id], odds), big: true, week: !T.length, rest: T.concat(N).filter(x => x !== f).map(x => by[x.id]) };
  }
  const night = c => { const hr = new Date(c.start).getHours(); return hr >= 1 && hr < 8; };
  const sc = cards.filter(c => ok(c, 48)).map(c => {
    const g = U.game(c), live = g.status === 'live', h = Math.max(0, (Date.parse(c.start) - now) / 36e5);
    const p = isNum(g.p_home) ? g.p_home : 0.5;
    return [(live ? 30 : 0) + stakeScore(c, odds) + 3 * (1 - Math.abs(p - 0.5) * 2) - 0.35 * h - (night(c) && !live ? 15 : 0), c];
  }).sort((x, y) => y[0] - x[0]);
  if (!sc.length) return null;
  return { c: sc[0][1], why: stakesWhy(sc[0][1], odds), big: sc[0][0] >= 8, rest: sc.slice(1).map(x => x[1]) };
}

/* Under the hero: why we picked it (round 6: no "How sure are we?" teaser on the landing page). */
function heroNote(g, why) {
  return why ? '<b>Why this game?</b> ' + esc(why) : false;
}

/* "This week in the NHL": the stage line, then the top lines as black tiles. */
function stageLine(st, idx) {
  const ph = String(idx.phase || '');
  if (!st) return RK.phaseLabel() ? RK.phaseLabel() + ', NHL ' + RK.seasonLabel(RK.currentSeason()) + '.' : '';
  if (/pre/.test(ph)) return 'Preseason. The regular season starts ' + day(st.first) + '.';
  if (/play/.test(ph)) return 'The Stanley Cup playoffs: sixteen clubs, four rounds, best of seven.';
  if (/off/.test(ph)) return 'The off-season. Our numbers pick up again with the first games.';
  return 'Regular season, week ' + st.week + ' of ' + st.weeks + ': ' + QK.fmt.num(st.played) + ' of ' + QK.fmt.num(st.total) + ' games played. It runs to ' + day(st.last) + ', then sixteen clubs play for the Cup.';
}
function weekTiles(dig, idx, feat, cup) {
  const T = [];
  const mv = dig.movers;
  if (mv && (mv.up.length || mv.down.length)) {
    const up = mv.up[0], dn = mv.down[0], lead = up || dn, what = mv.metric === 'p_cup' ? 'Cup' : 'playoff';
    T.push({ label: 'Biggest mover', value: RK.teamAbbr(lead.key) + ' ' + ptsOf(lead.d), href: RK.teamHref(lead.key), signal: true,
      sub: RK.teamName(lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + pctOf(lead.p) + ' in our ' + what + ' chance since ' + day(mv.since) + '.' + (up && dn ? ' Biggest fall: ' + RK.teamAbbr(dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  } else if (cup) {
    T.push({ label: 'Cup favourite', value: RK.teamAbbr(cup.team) + ' ' + pctOf(cup.model), href: RK.teamHref(cup.team), signal: true,
      sub: (cup.model < 0.2 ? 'Nobody is better than 1 in 5. ' : '') + RK.teamName(cup.team) + ' lead our board, from 20,000 simulated seasons.' });
  }
  const u = dig.upset;
  if (u) {
    const score = u.side === 'home' ? u.hs + '–' + u.as : u.as + '–' + u.hs;
    T.push({ label: 'Upset of the week', value: RK.teamAbbr(u.winner) + ' ' + pctOf(u.p), href: RK.gameHref(u.id),
      sub: RK.teamName(u.winner) + ' beat ' + nick(u.loser) + ' ' + score + ' on ' + QK.fmt.date(u.start) + '. We gave them ' + pctOf(u.p) + ' before the start.' });
  }
  const h = dig.hot;
  if (h) T.push({ label: 'Team of the week', value: RK.teamAbbr(h.key) + ' ' + h.w + '–' + h.l, href: RK.teamHref(h.key),
    sub: RK.teamName(h.key) + ': ' + h.w + ' win' + (h.w === 1 ? '' : 's') + ' in ' + h.gp + ' games, ' + (h.margin >= 0 ? '+' : '−') + Math.abs(h.margin) + ' goal difference.' });
  const rest = (feat && feat.rest || []).slice(0, 2);
  if (rest.length) T.push({ label: 'Also worth a look', value: rest.map(c => RK.teamAbbr(c.away) + '–' + RK.teamAbbr(c.home)).join(' · '), href: '#/games', text: rest.length > 1,
    sub: rest.map(c => { const g = U.game(c), w = whenLabel(g); return w + (g.status === 'live' ? '' : ' ' + QK.fmt.time(c.start)) + ': ' + nick(c.away) + ' at ' + nick(c.home); }).join('. ') + '.' });
  return T;
}

function gamesBlock(idx) {
  const today = (idx.today || []).slice(), live = idx.live || [];
  const seen = {};
  const list = [];
  live.concat(today).forEach(g => { if (!seen[g.game_id]) { seen[g.game_id] = 1; list.push(g); } });
  const order = { live: 0, pre: 1, final: 2 };
  list.sort((a, b) => order[U.status(a)] - order[U.status(b)] || String(a.start).localeCompare(String(b.start)));
  const up = (idx.upcoming || []).filter(g => !seen[g.game_id]).slice(0, 8);
  const rec = (idx.recent || []).filter(g => !seen[g.game_id]).slice().sort((a, b) => String(b.start).localeCompare(String(a.start))).slice(0, 8);
  return { today: list, upcoming: up, recent: rec };
}

/* ── round 6: the fan modules (lazy, after the page is up; about 120 KB of small payloads and a few player files) ──
 *   Breakout watch       this season's points-per-60 board (leaders.json) against last season's: three skaters off last
 *                        season's top 25 with the biggest jump, last season's rate from the player file (20+ games)
 *   Records in reach     the points and goals leaders (index.json, the boards on the page) at their club's games
 *                        played, paced to 82, against the NHL records (Gretzky: 215 points in 1985-86, 92 goals in
 *                        1981-82)
 *   Biggest surprise     the largest move in our playoff chance since opening day (race_log.json; the early dates
 *                        are rebuilt from the results known on each date, never later ones)
 *   Nobody talks about   a skater on our deep boards (performers.json: isolated impact, xG share, Rink value per 60)
 *                        but not on the points board, with his percentiles (6+ games, so they exist) and a season line */
const RECORDS = { p: { v: 215, who: 'Wayne Gretzky', yr: '1985-86', noun: 'points' }, g: { v: 92, who: 'Wayne Gretzky', yr: '1981-82', noun: 'goals' } };
const f2 = v => (isNum(v) ? v.toFixed(2) : '—');
function seasonRow(pf, S) { return ((pf && pf.seasons) || []).filter(s => Number(s.season) === Number(S))[0] || null; }
function seasonLine(pf, key, S, n) {
  const ss = ((pf && pf.seasons) || []).filter(s => s.values && isNum(s.values[key]) && (s.qualified || Number(s.season) === Number(S)) && Number(s.season) <= Number(S));
  return ss.slice(-(n || 7));
}
function posName(p) { return p === 'D' ? 'D' : p === 'G' ? 'G' : p === 'C' ? 'C' : p === 'L' ? 'LW' : p === 'R' ? 'RW' : (p || ''); }
function fanModules(el, S, rows) {
  const prevS = Number(S) - 10001;
  const recOf = t => { const r = rows[t]; return r && isNum(r.w) ? r.w + '-' + r.l + '-' + (r.otl || 0) : ''; };
  return Promise.all([RK.load(S + '/leaders.json'), RK.load(prevS + '/leaders.json'), RK.load(S + '/performers.json'), RK.load('race_log.json')]).then(res => {
    if (!U.alive(el)) return;
    const L = RK.ok(res[0]) ? res[0] : null, LP = RK.ok(res[1]) ? res[1] : null, PF = RK.ok(res[2]) ? res[2] : null, RL = res[3] || {};
    const board = (d, k) => (((d || {}).skaters || {})[k] || {}).rows || [];
    const pts25 = {}; board(L, 'p').forEach(r => { pts25[r[0]] = 1; });
    const was25 = {}; board(LP, 'p60').concat(board(LP, 'p')).forEach(r => { was25[r[0]] = 1; });
    const brk = board(L, 'p60').filter(r => !was25[r[0]]).slice(0, 9);
    const IL = (RK.index() || {}).leaders || {};
    const ldr = { p: (IL.s_p || [])[0], g: (IL.s_g || [])[0] };
    /* nobody talks about: on two or more deep boards, never on the points board */
    const deep = {};
    ((PF && PF.views) || []).filter(v => v.key === 'forwards' || v.key === 'defence').forEach(v => (v.metrics || []).filter(m => ['rapm_net', 'adj_xgf_pct', 'gar_60', 'xgf60_rel', 'rapm_def'].indexOf(m.key) >= 0).forEach(m => (m.top || []).forEach(t => {
      if (pts25[t[0]]) return;
      const d = deep[t[0]] || (deep[t[0]] = { id: t[0], n: 0, best: 99, view: v.key });
      d.n++; d.best = Math.min(d.best, t[5] || 99);
    })));
    const quiets = Object.keys(deep).map(k => deep[k]).sort((a, b) => b.n - a.n || a.best - b.best).slice(0, 4);
    const ids = brk.map(r => r[0]).concat(quiets.map(q => q.id)).filter(Boolean);
    return Promise.all(ids.map(id => RK.loadPlayer(id))).then(pfs => {
      if (!U.alive(el)) return;
      const P = {}; ids.forEach((id, i) => { if (pfs[i]) P[id] = pfs[i]; });
      /* Breakout watch */
      const cards = [];
      brk.forEach(r => {
        const pf = P[r[0]], cur = seasonRow(pf, S), prv = seasonRow(pf, prevS);
        if (!cur || !prv || !isNum((prv.values || {}).p60) || !isNum((cur.values || {}).p60) || (prv.values.gp || 0) < 20 || (cur.values.gp || 0) < 6) return;
        const now = cur.values.p60, was = prv.values.p60, jump = now - was;
        if (jump < 0.6) return;
        cards.push({ r: r, pf: pf, cur: cur, prv: prv, now: now, was: was, jump: jump });
      });
      cards.sort((a, b) => b.jump - a.jump);
      const top = cards.slice(0, 3);
      const scale = Math.max(4, Math.max.apply(null, top.map(c => c.now).concat([0])) * 1.08);
      const team = id => (RK.player(id).team || '');
      const story = top.map(c => {
        const id = c.r[0], t = c.cur.team || team(id), gp = c.cur.values.gp, line = seasonLine(c.pf, 'p60', S);
        return { kicker: 'Breakout watch', name: c.pf.name || RK.playerName(id), sub: RK.teamAbbr(t) + ' · ' + posName(c.cur.pos || c.pf.pos) + (isNum(c.cur.age) ? ' · age ' + Math.floor(c.cur.age) : ''),
          value: '+' + c.jump.toFixed(2), unit: 'points per 60 on last season', colour: RK.teamColourRaw(t), mark: U.team(t), href: RK.playerHref(id) + '?view=progression',
          from: { label: 'Last season', value: f2(c.was), pos: 100 * c.was / scale }, to: { label: 'This season', value: f2(c.now), pos: 100 * c.now / scale },
          spark: line.length > 2 ? line.map(s => s.values.p60) : null, sparkLabel: line.length > 2 ? 'Points per 60, ' + RK.seasonLabel(line[0].season) + ' to now' : '',
          text: (c.cur.values.p || 0) + ' points in ' + gp + ' game' + (gp === 1 ? '' : 's') + ', after ' + f2(c.was) + ' per 60 over ' + c.prv.values.gp + ' games last season.' + (gp < 25 ? ' An early sample: per-60 rates take about 25 games to settle.' : ''),
          link: { text: 'Progression' } };
      });
      const bx = el.querySelector('#ov-break');
      if (bx) bx.innerHTML = story.length ? '<section class="qk-section">' + QK.sectionHead({ kicker: 'Breakout watch', title: 'Who has found another gear?', sub: 'Skaters on this season’s points-per-60 board who were nowhere near last season’s, ranked by the jump. Every number is points per 60 minutes, all situations.', actions: '<a class="qk-more" href="#/scout?view=leaders">Every leader</a>' }) + QK.storyCards(story) + '</section>' : '';

      /* Records in reach + Biggest surprise (beside Who's for real?) */
      const side = [];
      ['p', 'g'].forEach(k => {
        const r = ldr[k], R = RECORDS[k], t = r ? team(r[0]) : '', gp = t && rows[t] ? rows[t].gp : null;
        if (!r || !isNum(r[1]) || !isNum(gp) || gp < 1) return;
        const full = RK.regGames(S), pace = r[1] / gp * full;
        side.push({ kicker: k === 'p' ? 'Records in reach' : 'On pace for', name: RK.playerName(r[0]), sub: RK.teamAbbr(t) + ' · ' + r[1] + ' ' + R.noun + ' through ' + gp + ' club games', colour: RK.teamColourRaw(t), mark: U.team(t), href: RK.playerHref(r[0]),
          value: Math.round(pace), unit: R.noun + ' over ' + full + ' games, on this pace', pace: { now: r[1], pace: pace, target: R.v, label: 'Record' },
          text: 'The record is ' + R.v + ' ' + R.noun + ', ' + R.who + ' in ' + R.yr + '. ' + (gp < 20 ? gp + ' games in, a pace this hot usually cools.' : Math.round(pace) >= R.v ? 'On pace to break it.' : 'Short of it on this pace.') });
      });
      const rl = (RL[String(S)] || {}).p_playoffs || {};
      const days = Object.keys(rl).filter(d => /^\d{4}-/.test(d)).sort();
      if (days.length >= 2) {
        const a = rl[days[0]], b = rl[days[days.length - 1]];
        const mv = Object.keys(b).filter(t => isNum(a[t]) && isNum(b[t])).map(t => ({ t: t, d: b[t] - a[t], a: a[t], b: b[t] })).sort((x, y) => Math.abs(y.d) - Math.abs(x.d))[0];
        if (mv && Math.abs(mv.d) >= 0.1) side.push({ kicker: 'Biggest surprise', name: RK.teamName(mv.t), sub: recOf(mv.t) ? recOf(mv.t) + ' so far' : '', colour: RK.teamColourRaw(mv.t), mark: U.team(mv.t), href: RK.teamHref(mv.t),
          value: (mv.d > 0 ? '+' : '−') + Math.abs(Math.round(mv.d * 100)), unit: 'points of playoff chance',
          from: { label: 'Opening day', value: U.pct(mv.a), pos: mv.a * 100 }, to: { label: 'Now', value: U.pct(mv.b), pos: mv.b * 100 },
          text: 'No club’s playoff chance has moved more since opening day, in our season simulations: ' + (mv.d > 0 ? 'up' : 'down') + ' from ' + U.pct(mv.a) + ' to ' + U.pct(mv.b) + '.' });
      }
      const sx = el.querySelector('#ov-side');
      if (sx) sx.innerHTML = side.length ? QK.sectionHead({ kicker: 'Records and surprises', title: 'On pace for history?', sub: 'The leaders’ full-season pace against the records, and the club our numbers misjudged most.' }) + QK.storyCards(side, { cols: 1 }) : '';

      /* Best player nobody talks about */
      const quiet = quiets.filter(q => { const f = P[q.id], c = seasonRow(f, S); return f && c && f.current && f.current.pct && Object.keys(f.current.pct).length && ((c.values || {}).gp || 0) >= 6; })[0] || null;
      const qp = quiet && P[quiet.id], qc = seasonRow(qp, S);
      const spx = el.querySelector('#ov-spot');
      if (spx && qp && qc && qp.current && qp.current.pct) {
        const pc = qp.current.pct, v = qc.values || {}, D = (qc.pos || qp.pos) === 'D';
        const defs = [['rapm_net', 'Isolated impact (RAPM)', x => U.signed(x, 2), 'Our model: his impact on the goal share, isolated from team-mates and opponents.'],
          ['xgf_pct', 'On-ice xG share (5v5)', x => U.pct(x, 1), 'The share of expected goals his team gets with him on the ice at 5-on-5.'],
          ['rapm_def', 'Isolated defence (RAPM)', x => U.signed(x, 2), 'Our model: his defensive impact, isolated from team-mates and opponents.'],
          ['ixg60', 'Individual xG per 60 (5v5)', x => f2(x), 'Expected goals from his own shots per 60 minutes at 5-on-5.'],
          ['p60', 'Points per 60', x => f2(x), 'Points per 60 minutes, all situations.']];
        const stats = defs.filter(d => isNum(pc[d[0]]) && isNum(v[d[0]])).slice(0, 4).map(d => ({ label: d[1], value: d[2](v[d[0]]), pctl: pc[d[0]], tip: d[3] }));
        const line = seasonLine(qp, 'xgf_pct', S);
        const t = qc.team || team(quiet.id), top = stats.filter(s => s.pctl >= 90)[0] || stats[0];
        spx.innerHTML = stats.length ? '<section class="qk-section">' + QK.sectionHead({ kicker: 'Best player nobody talks about', title: 'Off the points board. All over ours.', sub: 'Not in the top 25 for points, but near the top of our deep boards: the play tilts his way. Percentiles against ' + (D ? 'defencemen' : 'forwards') + ' this season.' }) +
          QK.spotlight({ kicker: 'Spotlight · ' + (D ? 'defence' : 'forward'), name: qp.name, sub: RK.teamName(t) + ' · ' + posName(qc.pos || qp.pos) + (isNum(qc.age) ? ' · ' + Math.floor(qc.age) : ''), number: qp.number, team: { colour: RK.teamColourRaw(t) },
            headline: top ? QK.ordinal(Math.round(top.pctl)) + ' percentile in ' + top.label.replace(/ \(.*\)$/, '').toLowerCase() + ', with ' + (v.p || 0) + ' points in ' + (v.gp || 0) + ' games.' : '',
            stats: stats, spark: line.length > 2 ? { values: line.map(s => 100 * s.values.xgf_pct), labels: [RK.seasonLabel(line[0].season), 'now'], label: 'On-ice xG share by season' } : null,
            text: (v.gp || 0) < 25 ? 'An early-season sample: these rates settle after about 25 games.' : '', links: [{ href: RK.playerHref(quiet.id), text: 'Player page' }, { href: RK.playerHref(quiet.id) + '?view=progression', text: 'Progression' }, { href: '#/compare/progression/' + encodeURIComponent(quiet.id), text: 'Compare careers' }] }) + '</section>' : '';
      }
    });
  });
}

function render(el, params) {
  /* a past season (#/?s=<S>) reads as its recap (rk-recap.js), never as this season's page */
  const SP = params && params.season ? Number(params.season) : null;
  if (SP && SP !== Number(RK.currentSeason()) && RK.recap) return RK.recap.render(el, SP);
  const S = RK.currentSeason();
  const idx = RK.index() || {};
  const dig = idx.digest || {};
  const seg = '<div class="qk-seg" id="ov-when" role="group" aria-label="Games"><button type="button" aria-pressed="true" data-value="today">Today</button><button type="button" aria-pressed="false" data-value="next">Next</button><button type="button" aria-pressed="false" data-value="results">Results</button></div>';
  const feat = pickFeatured(idx);
  el.innerHTML = intro({ tag: 'NHL · ' + RK.seasonLabel(S) + (RK.phaseLabel() ? ' · ' + RK.phaseLabel() : ''),
    title: 'Every NHL game, player and team, by the numbers.',
    lede: 'Our chance for tonight’s games, who’s for real, and the race for the Cup, from 20,000 simulated seasons and expected goals, in plain English.',
    links: [{ label: 'Games', sub: 'Every game, our chance', href: '#/games' }, { label: 'Playoff race', sub: 'Standings and the Cup', href: '#/standings' }, { label: 'Scouting Room', sub: 'Every player, every metric', href: '#/scout' }] }) +
    '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in the NHL', title: '<span id="ov-wk">The week so far</span>', sub: '<span id="ov-stage">' + esc(stageLine(dig.stage, idx)) + '</span>', html: true }) +
    '<div id="ov-week"></div><div id="ov-feat" class="ql-feat"></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch', title: '<span id="ov-gh">Today</span>', html: true, sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.', actions: seg }) +
    '<div class="qk-watch" id="ov-games">' + QK.skeleton('card', 3) + '</div></section>' +
    '<div id="ov-hot"></div>' +
    '<div id="ov-break"></div>' +
    '<section class="qk-section qk-g75">' +
    '<div class="rk-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Clubs top-left are winning more than their chances suggest; bottom-right, the reverse. Early-season luck, or something real?' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Points percentage against share of 5-on-5 expected goals"></div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div><div id="ov-side"></div></section>' +
    '<div id="ov-spot"></div>' +
    '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0], QK.NEW_HERE[1], '<b>Expected goals</b> (xG) rate every shot by how often that kind of chance goes in: 0.3 xG goes in about 3 times in 10. A club that wins the xG battle usually wins the games, in time.'] }) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who lifts the Cup?', sub: '<span id="ov-cup-lede">Our chances from 20,000 simulated seasons.</span>', html: true, actions: '<a class="qk-more" href="#/standings?tab=markets">Every season forecast</a>' }) +
    '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Stanley Cup chances', 'Our chance from 20,000 simulated seasons, in team colours', '<div id="ov-cup"></div>', { foot: '<span>Top ten of 32</span><a href="#/standings?tab=ratings">Power ratings →</a>' }) + '</div>' +
    '<div class="qk-span-6">' + U.card2('Projected full-season points', 'Mean of the simulated seasons (dot) and its 90% range (bar)', U.chart('ov-range', 470, 'Projected points with a 90% range'), { foot: '<span>Range: 5th to 95th percentile of 20,000 seasons</span><a href="#/standings">Standings →</a>' }) + '</div></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Playoff race', title: 'Who makes the playoffs', sub: 'Our chance of a playoff spot by conference, beside the table as it stands.',
      actions: '<div class="qk-seg" id="ov-conf" role="group" aria-label="Conference"><button type="button" aria-pressed="true" data-value="Eastern">East</button><button type="button" aria-pressed="false" data-value="Western">West</button></div>' }) +
    '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Playoff chances', 'Our chance of making the playoffs', '<div id="ov-po"></div>') + '</div>' +
    '<div class="qk-span-6">' + U.card2('Standings', 'Points, points % and our playoff chance', '<div id="ov-st"></div>', { flush: true, foot: '<span>Wild-card format</span><a href="#/standings">Full standings →</a>' }) + '</div></div></section>' +
    '<p class="qk-sub rk-ov-doing"><a class="qk-link" href="#/model?tab=calibration">How we’re doing →</a> Our record and every forecast checked against the result, on the Model page.</p>';

  return Promise.all([RK.load(S + '/season.json'), RK.load(S + '/markets.json')]).then(res => {
    if (!U.alive(el)) return;
    const season = RK.ok(res[0]) ? res[0] : {}, mk = RK.ok(res[1]) ? res[1] : {};
    const rows = ((season.standings || {}).rows || []).slice();
    const byTeam = {}; rows.forEach(r => { byTeam[r.team] = r; });
    const cup = (((mk.futures || {}).cup) || []).slice();
    const odds = idx.playoff_odds || {};
    if (!cup.length) Object.keys(odds).forEach(t => cup.push({ team: t, model: odds[t].p_cup, market: null }));
    const cupFav = cup.filter(r => isNum(r.model)).sort((a, b) => b.model - a.model)[0];

    // this week: the top lines, then the game that matters most (or the race when nothing big is on)
    const T = weekTiles(dig, idx, feat, cupFav);
    el.querySelector('#ov-week').innerHTML = T.length ? QK.stats(T) : '';
    if (T.length >= 3) el.querySelector('#ov-wk').textContent = 'The week in ' + WORDS[T.length].toLowerCase() + ' lines';
    const fe = el.querySelector('#ov-feat');
    if (feat && feat.big) {
      const g = heroGame(feat.c, byTeam), lab = whenLabel(g);
      fe.innerHTML = QK.featureCard(g, { scribble: lab + (feat.week ? ' · The big one this week' : ' · The one to watch'), nick: t => nick(t.abbr), note: heroNote(g, feat.why) });
    } else if (cupFav) {  /* nothing big on: lead with the race */
      const top = cup.filter(r => isNum(r.model)).sort((a, b) => b.model - a.model).slice(0, 6);
      fe.innerHTML = '<div class="ql-race">' + QK.sectionHead({ kicker: feat && feat.c ? 'Nothing big on ' + whenLabel(U.game(feat.c)).toLowerCase() : 'No big game today', title: 'So here’s the race for the Cup', sub: 'Our chance of lifting the Stanley Cup, from 20,000 simulated seasons.', tag: 'h3' }) +
        QK.chances(top.map(r => ({ label: nick(r.team), p: r.model, href: RK.teamHref(r.team), mark: U.team(r.team), color: RK.teamColourRaw(r.team) })), { key: false }) + '</div>';
    }

    // scoreboard
    const G = gamesBlock(idx);
    const draw = w => {
      const list = w === 'next' ? G.upcoming : w === 'results' ? G.recent : G.today;
      const n = Math.min(9, list.length);
      el.querySelector('#ov-gh').textContent = w === 'next' ? 'Next up. Our calls.' : w === 'results' ? 'Latest results' : (n ? (WORDS[n] || n) + ' game' + (n === 1 ? '' : 's') + '. Our calls.' : 'Today');
      el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(g => U.gc(g, null, byTeam, true)).join('') : QK.empty('No games', w === 'today' ? 'No games today: see the next ones.' : 'Nothing to show yet.');
    };
    draw(G.today.length ? 'today' : 'next');
    if (!G.today.length) el.querySelectorAll('#ov-when button').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('data-value') === 'next' ? 'true' : 'false'));
    QK.seg(el.querySelector('#ov-when'), draw);

    // cup chances: ours only (the market is on game pages and the Model page)
    const cupRows = cup.filter(r => isNum(r.model)).map(r => ({ label: nick(r.team), p: r.model, href: RK.teamHref(r.team), mark: U.team(r.team), color: RK.teamColourRaw(r.team) }));
    el.querySelector('#ov-cup').innerHTML = QK.chances(cupRows, { limit: 10, key: false });
    const cup0 = cupRows.slice().sort((a, b) => b.p - a.p)[0];
    if (cup0) el.querySelector('#ov-cup-lede').textContent = (cup0.p < 0.2 ? 'Nobody’s better than 1 in 5. ' + cup0.label + ' lead our board at ' + U.pct(cup0.p) + '.' : cup0.label + ' lead at ' + U.pct(cup0.p) + '.') + ' From 20,000 simulated seasons.';

    // projected points: mean and the 90% range from the simulation
    const sim = (season.sim && season.sim.teams) || {};
    const rr = Object.keys(sim).filter(t => isNum(sim[t].mean_pts) && isNum(sim[t].pts_p05) && isNum(sim[t].pts_p95)).sort((a, b) => sim[b].mean_pts - sim[a].mean_pts);
    if (rr.length) {
      const show = rr.slice(0, 16);
      QKC.range('#ov-range', { rows: show.map(t => ({ label: RK.teamName(t), lo: sim[t].pts_p05, hi: sim[t].pts_p95, mid: sim[t].mean_pts, href: RK.teamHref(t), color: RK.teamColourRaw(t), sub: U.pct(sim[t].p_playoffs) + ' to make the playoffs' })),
        fmt: v => U.f(v, 0), loName: '5th', hiName: '95th percentile', midName: 'Projected full-season points', valName: 'Points at season end (full season)', labelWidth: 150 });
      el.querySelector('#ov-range').insertAdjacentHTML('afterend', '<p class="qk-caption">The top sixteen by projected points. Each bar spans the 5th to 95th percentile of the club’s points across the simulated seasons.</p>');
    } else el.querySelector('#ov-range').innerHTML = QK.empty('No simulation yet', 'The projection appears once the season simulation has run.');

    /* Who's for real?: points won against the 5-on-5 chance share (QKC.quadrant), the corners named */
    const luck = rows.filter(r => isNum(r.xgf_pct) && isNum(r.p_pct) && r.gp > 0);
    const pts = luck.map(r => ({ x: r.xgf_pct * 100, y: r.p_pct * 100, name: RK.teamName(r.team), sub: r.pts + ' points in ' + r.gp + ' games', label: r.team, color: RK.teamColourRaw(r.team), href: RK.teamHref(r.team) }));
    if (pts.length >= 6) {
      const avgY = pts.reduce((a, p) => a + p.y, 0) / pts.length, gps = luck.map(r => r.gp), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
      QKC.quadrant('#ov-luck', { points: pts, xName: 'Share of expected goals at 5-on-5 (%)', yName: 'Points won (% of possible)', refX: 50, refY: avgY,
        xFmt: v => Math.round(v) + '%', yFmt: v => Math.round(v) + '%', label: 'NHL clubs: share of expected goals against points won' });
      el.querySelector('#ov-luck-cap').textContent = 'NHL ' + RK.seasonLabel(S) + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. Dashed lines: a 50% chance share and the league’s average points. Tap a club for its page.';
    } else el.querySelector('#ov-luck').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');

    // playoff race + standings snapshot
    const conf = c => rows.filter(r => r.conference === c);
    const drawConf = c => {
      const rs = conf(c).filter(r => isNum(r.p_playoffs));
      el.querySelector('#ov-po').innerHTML = rs.length ? QK.chances(rs.map(r => ({ label: RK.teamName(r.team), p: r.p_playoffs, color: RK.teamColourRaw(r.team), href: RK.teamHref(r.team), mark: U.team(r.team) })), { max: 1, oursName: 'Our playoff chance' }) : QK.empty('No simulation yet');
      const st = conf(c).slice().sort((a, b) => (b.pts - a.pts) || (b.p_pct - a.p_pct));
      QK.leaderboard(el.querySelector('#ov-st'), {
        dense: true, rank: true, rowHref: r => RK.teamHref(r.team), columns: [
          { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team) },
          { key: 'gp', label: 'GP', num: true }, { key: 'pts', label: 'Pts', num: true },
          { key: 'p_pct', label: 'Pts%', num: true, fmt: v => RK.fmtVal(v, '3') },
          { key: 'p_playoffs', label: 'Playoffs', type: 'bar', max: 1, fmt: v => U.pct(v) }
        ], rows: st.map(r => Object.assign({ name: RK.teamShort(r.team) }, r))
      });
    };
    drawConf('Eastern');
    QK.seg(el.querySelector('#ov-conf'), drawConf);

    // leaders (counting stats, everyone ranks)
    const L = idx.leaders || {};
    /* Who's hot: the black power list, the top name on four boards */
    const HOT = [['s_p', 'Most points', v => String(v), 'Points = goals + assists, all situations.'], ['s_g', 'Most goals', v => String(v), 'Goals in all situations this season.'],
      ['s_gar', 'Rink value (GAR)', v => U.f(v, 1), 'Goals added over a replacement-level player, from our value model.'], ['g_gsax', 'Goals saved above expected', v => U.signed(v, 1), 'Shots faced against how often that kind of shot goes in. Above zero = better than an average goalie.']];
    const hot = HOT.map(b => { const r = (L[b[0]] || [])[0], r1 = (L[b[0]] || [])[1]; return r ? { sport: 'hockey', kicker: 'NHL · ' + RK.teamAbbr(RK.player(r[0]).team), title: b[1], name: RK.playerName(r[0]), value: b[2](r[1]), href: RK.playerHref(r[0]),
      next: r1 ? { name: RK.playerName(r1[0]), value: b[2](r1[1]) } : null, expl: b[3] } : null; }).filter(Boolean);
    if (hot.length) el.querySelector('#ov-hot').innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, board by board', sub: 'The top name on four boards, and a line on what the number means. Counting stats, so everyone ranks.', actions: '<a class="qk-more" href="#/scout?view=leaders">Every leader</a>' }) + QK.hotRow(hot));
    fanModules(el, S, byTeam);
    RK.setMeta('');
    if ((idx.live || []).length || (idx.today || []).some(g => U.status(g) === 'live')) RK.liveRefresh([S + '/season.json'], 60000);
  });
}

RK.overviewLanding = { whenLabel: whenLabel, pickFeatured: pickFeatured, weekTiles: weekTiles };
RK.page('hub', render);
})(window.RK);
