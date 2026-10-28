/* The Quant Gridiron — Overview (#/), the kit v4 "Broadcast" landing page (docs/rink/assets/js/rk-overview.js is the
 * reference).
 *   the ticker; the intro band (what the site covers, how to use it, three quick links: Games, Playoff race,
 *   Players); "This week in the NFL": the stage (the week of the season, or the playoff round), then the top lines
 *   from index.json "digest" (scripts/build_gridiron.py with oddsmarkets/common/digest.py): the biggest playoff or
 *   Super Bowl chance mover, the upset of the week, the team of the week and the other games that matter; the game that matters most by significance (digest.featured: oddsmarkets/common/featured.py) as the
 *   diagonal split hero, labelled "Live now", "Tonight" (only when it truly is tonight in the reader's time), "Today",
 *   "Tomorrow" or the weekday, else the Super Bowl race; "N games. Our calls." (the games that matter first); the
 *   black power list; round 6, the fan modules: "Records in reach" (each leader's 17-game pace against the
 *   single-season record), "Breakout watch" (the biggest jumps in our value-a-game percentile from last season), "Best
 *   player nobody talks about" (a spotlight), "Who's for real?" beside the biggest turnaround and fall from last
 *   season; "What's that number?"; "Who lifts the Lombardi Trophy?" beside projected wins; offence v defence; the
 *   playoff race division by division; leaders; a small link to "How we're doing" (our record and calibration live on
 *   the Model page). Game cards and the ticker carry the market small and grey beside our chance.
 * Reads index.json, <S>/season.json, glossary.json (leader labels); lazily, <S>/leaders.json, the value leaders'
 * player files and last season's season.json for the fan modules. */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;

const LEADER_FALLBACK = { composite: ['QB composite', '1'], epa_db: ['EPA per dropback', 'epa'], cpoe: ['CPOE', 'signed1'], rush_epa: ['Rush EPA per carry', 'epa'],
  ryoe: ['Rush yards over expected per carry', 'signed'], rec_epa: ['Receiving EPA', '1'], sacks: ['Sacks', '1'], fg_oe: ['FG points over expected', 'signed1'] };
function glossIndex(g) {
  const out = {};
  ((g && g.groups) || []).forEach(gr => (gr.entries || []).forEach(e => { if (e && e.key && !out[e.key]) out[e.key] = e; }));
  return out;
}
function leaderMeta(key, G) {
  const m = /^(qb|rb|wr|te|k|p|def)_(.+)$/.exec(key);
  const k = m ? m[2] : key, pre = m ? m[1].toUpperCase() : '';
  const e = G[key] || G[k];
  if (e) return { label: e.label, fmt: e.fmt, lower: e.lower, pre: pre, desc: e.desc };
  const f = LEADER_FALLBACK[k];
  return { label: f ? f[0] : GI.titleCase(k), fmt: f ? f[1] : null, pre: pre };
}

/* The old pick, kept for the order of the other games: live first, then the closest calls with the most at stake. */
function watchVal(g, po) {
  if (GI.isLive(g)) return 100;
  if (!GI.isPre(g)) return -1;
  const p = isNum((g.model || {}).p_home) ? g.model.p_home : 0.5;
  const stake = ((po[g.home] || {}).p_playoffs || 0.5) + ((po[g.away] || {}).p_playoffs || 0.5);
  return stake * (1 - Math.abs(p - 0.5) * 1.6);
}

/* ── the landing top (the same shape on every sport overview) ──────────────────────────────────────────────── */
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
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
/* a date-only payload day ("2027-01-10") in en-GB without a time-zone shift */
const day = d => QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d);
const ptsOf = d => (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts';
const the = t => 'the ' + GI.teamShort(t);
const The = t => 'The ' + GI.teamShort(t);
/* Why the featured game: the shared rule's reasons, then our playoff and Super Bowl numbers. */
function reasonsWhy(r, c, po) {
  const a = po[c.away] || {}, h = po[c.home] || {}, A = GI.teamAbbr(c.away), H = GI.teamAbbr(c.home);
  const lead = (r || []).filter(Boolean).join(' and ');
  const nums = [isNum(a.p_playoffs) && isNum(h.p_playoffs) ? 'our playoff chances ' + A + ' ' + GI.pct(a.p_playoffs, 0) + ', ' + H + ' ' + GI.pct(h.p_playoffs, 0) : '',
    isNum(a.p_sb) && isNum(h.p_sb) && (a.p_sb >= 0.02 || h.p_sb >= 0.02) ? 'to win the Super Bowl ' + A + ' ' + GI.pct(a.p_sb, 0) + ', ' + H + ' ' + GI.pct(h.p_sb, 0) : ''].filter(Boolean).join('; ');
  if (!lead) return nums ? nums.charAt(0).toUpperCase() + nums.slice(1) + '.' : '';
  return lead.charAt(0).toUpperCase() + lead.slice(1) + (nums ? ': ' + nums : '') + '.';
}
/* The game that matters most, on the shared significance rule (featured.py rank_featured: the NFL tier, the playoff
 * round, the playoff and Super Bowl stakes in our simulations, rivalries, the kick-off time and hour, live-ness;
 * closeness only a small bonus), from index.json digest.featured: the first of "today" still upcoming or live at
 * the reader's clock, else "week". An older payload without it gets the old pick. */
function pickFeatured(idx, games, po) {
  const by = {}, now = QK.now();
  games.forEach(g => { by[g.game_id] = g; });
  const ok = (g, hrs) => { if (!g || GI.isFinal(g)) return false; const h = (Date.parse(g.kickoff) - now) / 36e5; return GI.isLive(g) ? h > -8 : GI.isPre(g) && h > -1 && h < hrs; };
  const F = (idx.digest || {}).featured;
  if (F && (F.today || F.week)) {
    const T = (F.today || []).filter(f => ok(by[f.id], 24));
    const f = T[0] || (F.week && ok(by[F.week.id], 24 * 7) ? F.week : null);
    if (!f) return { c: null, rest: [], order: [] };
    return { c: by[f.id], why: reasonsWhy(f.why, by[f.id], po), week: !T.length, rest: T.slice(1).map(x => by[x.id]), order: (F.today || []).map(x => x.id) };
  }
  const list = games.filter(g => ok(g, 24 * 7)).sort((a, b) => watchVal(b, po) - watchVal(a, po));
  return list.length ? { c: list[0], why: reasonsWhy([], list[0], po), rest: list.slice(1, 3), order: [] } : null;
}
/* Under the hero: why we picked it (round 6: the "How sure are we?" line lives on the Model page now). */
function heroNote(g, why) {
  return why ? '<b>Why this game?</b> ' + esc(why) : false;
}
/* "This week in the NFL": the stage line. */
function stageLine(st, ph) {
  if (!st) return '';
  if (st.round) return 'The playoffs: the ' + st.round_name + (st.round === 'SB' ? '.' : '. Lose and the season is over.');
  if (/pre/.test(ph)) return 'Preseason. The regular season kicks off ' + day(st.first) + '.';
  if (/off/.test(ph)) return 'The off-season. Our numbers pick up again in September.';
  return 'Week ' + st.week + ' of ' + st.weeks + ': ' + QK.fmt.num(st.played) + ' of ' + QK.fmt.num(st.total) + ' regular-season games played. The regular season runs to ' + day(st.last) + ', then fourteen teams play for the Super Bowl.';
}
function weekTiles(dig, feat, po) {
  const T = [];
  const mv = dig.movers;
  if (mv && (mv.up.length || mv.down.length)) {
    const up = mv.up[0], dn = mv.down[0], lead = up || dn, what = mv.metric === 'p_sb' ? 'Super Bowl' : 'playoff';
    T.push({ label: 'Biggest mover', value: GI.teamAbbr(lead.key) + ' ' + ptsOf(lead.d), href: GI.teamHref(lead.key), signal: true,
      sub: The(lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + GI.pct(lead.p, 0) + ' in our ' + what + ' chance since ' + day(mv.since) + '.' + (up && dn ? ' Biggest fall: ' + GI.teamAbbr(dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  } else {
    const fav = Object.keys(po).filter(t => isNum(po[t].p_sb)).sort((a, b) => po[b].p_sb - po[a].p_sb)[0];
    if (fav) T.push({ label: 'Super Bowl favourite', value: GI.teamAbbr(fav) + ' ' + GI.pct(po[fav].p_sb, 0), href: GI.teamHref(fav), signal: true,
      sub: (po[fav].p_sb < 0.25 ? 'Nobody is better than 1 in 4. ' : '') + The(fav) + ' lead our board, from 20,000 simulated seasons.' });
  }
  const u = dig.upset;
  if (u) {
    const score = u.side === 'home' ? u.hs + '–' + u.as : u.as + '–' + u.hs;
    T.push({ label: 'Upset of the week', value: GI.teamAbbr(u.winner) + ' ' + GI.pct(u.p, 0), href: GI.gameHref(u.id),
      sub: The(u.winner) + ' beat ' + the(u.loser) + ' ' + score + ' on ' + QK.fmt.date(u.start) + '. We gave them ' + GI.pct(u.p, 0) + ' before kick-off.' });
  }
  const h = dig.hot;
  if (h) T.push({ label: 'Team of the week', value: GI.teamAbbr(h.key) + ' ' + h.w + '–' + h.l, href: GI.teamHref(h.key),
    sub: The(h.key) + ': ' + (h.gp === 1 ? 'the biggest win of the week, ' : h.w + ' wins in ' + h.gp + ' games, ') + (h.margin >= 0 ? '+' : '−') + Math.abs(h.margin) + ' points.' });
  const rest = ((feat && feat.rest) || []).filter(Boolean).slice(0, 2);
  if (rest.length) T.push({ label: 'Also worth a look', value: rest.map(g => GI.teamAbbr(g.away) + '–' + GI.teamAbbr(g.home)).join(' · '), href: '#/games', text: rest.length > 1,
    sub: rest.map(g => { const w = whenLabel(GI.qkGame(g)); return w + (GI.isLive(g) ? '' : ' ' + QK.fmt.time(g.kickoff)) + ': the ' + GI.teamShort(g.away) + ' at the ' + GI.teamShort(g.home); }).join('. ') + '.' });
  return T;
}

/* "Who's hot": the top of five of the builder's leaderboards, each with what the number means. */
const HOT = [
  ['qb_epa_db', 'Best passer', 'EPA per dropback', 'Expected points added each time the quarterback drops back, sacks and scrambles included. Zero is an average play.'],
  ['rb_ryoe', 'Best runner', 'rush yards over expected a carry', 'Yards beyond what our model expects from the blocking, the box and the down and distance.'],
  ['wr_rec_epa', 'Best receiver', 'receiving EPA', 'Expected points the offence gained on the throws to this receiver, this season.'],
  ['def_sacks', 'Most sacks', 'sacks', 'Sacks this season. Pressure without the sack does not show in public data.'],
  ['k_fg_oe', 'Best kicker', 'field-goal points over expected', 'Points from field goals beyond what our model expects from the distances tried. Kicking is close to noise.']
];
function hotItems(L, G) {
  return HOT.map(h => {
    const list = L[h[0]] || [];
    const r0 = list[0], r1 = list[1];
    if (!r0) return null;
    const m = leaderMeta(h[0], G);
    const f = v => GI.fmtVal(v, m.fmt);
    return { sport: 'nfl', kicker: h[1] + ' · ' + GI.teamAbbr(GI.player(r0[0]).team), title: h[2].charAt(0).toUpperCase() + h[2].slice(1), name: GI.playerName(r0[0]), value: f(r0[1]), href: GI.playerHref(r0[0]),
      next: r1 ? { name: GI.playerName(r1[0]), value: f(r1[1]) } : null, expl: h[3] };
  }).filter(Boolean);
}

function divisionsGrid(rows) {
  if (!rows.length) return GI.muted('Standings arrive with the first build.');
  return '<div class="gi-divs">' + GI.DIVISIONS.map(dv => {
    const list = rows.filter(r => r.division === dv).sort((a, b) => (b.pct - a.pct) || ((b.p_div || 0) - (a.p_div || 0)));
    if (!list.length) return '';
    return '<div class="gi-div"><div class="gi-div-h"><span>' + esc(dv) + '</span><span>W-L</span><span>Playoffs</span></div>' + list.map((r, i) =>
      '<div class="gi-div-r' + (i === 0 ? ' lead' : '') + '">' + GI.teamLink(r.team, { short: true }) + '<span class="n">' + esc(GI.record(r.w, r.l, r.t)) + '</span>' +
      '<span>' + GI.probBar(r.p_playoffs, GI.tc(r.team)) + '</span></div>').join('') + '</div>';
  }).join('') + '</div>';
}

function seasonRows(season) {
  const out = [];
  ((season && season.standings) || []).forEach(d => (d.teams || []).forEach(t => out.push(Object.assign({ division: d.division, conference: d.conference }, t))));
  return out;
}


/* ── fan modules (round 6): records in reach, breakout watch, the best player nobody talks about, the turnarounds ── */
/* Read lazily after the page draws: <S>/leaders.json (75 KB), the player files of the leaders on the value boards (about
 * 7 KB each, thirty at most) and last season's season.json (40 KB). Nothing here is about how our forecasts score. */
const GROUP_PL = { qb: 'quarterbacks', rb: 'running backs', wr: 'receivers', te: 'tight ends', edge: 'pass rushers', idl: 'interior linemen', lb: 'linebackers', cb: 'cornerbacks', s: 'safeties' };
/* the leader boards a record chase reads: [leaders.json group, key, the words]; the record itself is the best season in
   our play-by-play before this one (history.json season_records, 1999 on), never a hard-coded figure */
const RECORDS = [['QB', 'pass_yds', 'passing yards'], ['QB', 'pass_td', 'passing touchdowns'], ['RB', 'rush_yds', 'rushing yards'], ['RB', 'rush_td', 'rushing touchdowns'],
  ['WR', 'rec_yds', 'receiving yards'], ['WR', 'rec_td', 'receiving touchdowns'], ['DEF', 'sacks', 'sacks']];
/* the record before season S: the best row of history.json season_records[key] from an earlier season (ties: every holder) */
function recordBefore(hist, key, S) {
  const b = ((hist && hist.season_records) || {})[key];
  const rows = ((b && b.rows) || []).filter(r => isNum(r[2]) && r[2] < S && isNum(r[4]));
  if (!rows.length) return null;
  const top = rows[0][4], who = rows.filter(r => r[4] === top);
  return { value: top, who: who.map(r => r[1] + ', ' + r[2]).join(', and ') };
}
const VALUE_BOARDS = [['QB', 'composite'], ['RB', 'value'], ['WR', 'value'], ['TE', 'value'], ['DEF', 'def_value']];
const SPOT_KEYS = { rb: ['ryoe', 'rush_epa', 'explosive', 'rush_success'], wr: ['rec_epa_tgt', 'target_share', 'croe', 'yacoe'], te: ['rec_epa_tgt', 'target_share', 'croe', 'yacoe'],
  edge: ['pressures_pg', 'sacks_pg', 'tfl_pg', 'splash_pg'], idl: ['pressures_pg', 'sacks_pg', 'tfl_pg', 'splash_pg'], lb: ['tackles_pg', 'tfl_pg', 'pressures_pg', 'splash_pg'] };
const SPOT_LABEL = { ryoe: 'Rush yards over expected', rush_epa: 'Rush EPA per carry', explosive: 'Explosive-run rate', rush_success: 'Rush success rate', rec_epa_tgt: 'Receiving EPA per target',
  target_share: 'Target share', croe: 'Catch rate over expected', yacoe: 'Yards after catch over expected', pressures_pg: 'Pressures a game', sacks_pg: 'Sacks a game', tfl_pg: 'Tackles for loss a game',
  splash_pg: 'Splash plays a game', tackles_pg: 'Tackles a game', pd_pg: 'Passes defended a game', ff_pg: 'Forced fumbles a game', yac_rec: 'Yards after catch per catch', catch_rate: 'Catch rate', adot: 'Average depth of target' };
const JUMP = ['Biggest jump', 'Second biggest', 'Third biggest'];
function seasonOf(p, S) { return ((p && p.seasons) || []).filter(s => s.season === S)[0] || null; }
/* a season's value and percentile for one metric: s.pct (the older player file) or the compact dv / dp arrays in the
   order of p.prog.keys[group] (the progression-era player file) */
function metricOf(p, s, k) {
  if (!s) return { v: null, pct: null };
  if (s.pct && isNum(s.pct[k])) return { v: isNum(s[k]) ? s[k] : null, pct: s.pct[k] };
  const keys = p && p.prog && p.prog.keys ? p.prog.keys[s.group] : null, i = keys ? keys.indexOf(k) : -1;
  if (i >= 0 && Array.isArray(s.dp)) return { v: Array.isArray(s.dv) && isNum(s.dv[i]) ? s.dv[i] : (isNum(s[k]) ? s[k] : null), pct: isNum(s.dp[i]) ? s.dp[i] : null };
  return { v: isNum(s[k]) ? s[k] : null, pct: null };
}
function qualPct(p, s) { return s && s.qualified ? metricOf(p, s, 'gvar_pg').pct : null; }
function gvar(p, s) { return metricOf(p, s, 'gvar_pg').v; }
function spotVal(k, v) { if (!isNum(v)) return ''; if (/share|rate|success|explosive/.test(k) && Math.abs(v) <= 1) return (100 * v).toFixed(1) + '%'; return GI.num(v, Math.abs(v) >= 10 ? 1 : 2); }
function paceCards(lead, files, S, hist) {
  const out = [];
  RECORDS.forEach(r0 => {
    const rec = recordBefore(hist, r0[1], S);
    if (!rec) return;
    const r = [r0[0], r0[1], rec.value, rec.who, r0[2]];
    const top = (((lead.players || {})[r[0]] || {})[r[1]] || [])[0];
    const p = top ? files[top[0]] : null, s = p ? seasonOf(p, S) : null;
    if (!s || !isNum(s[r[1]]) || !isNum(s.games) || s.games < 3) return;
    const pace = s[r[1]] / s.games * 17;
    out.push({ r: r, p: p, s: s, v: s[r[1]], pace: pace, ratio: pace / r[2] });
  });
  out.sort((a, b) => b.ratio - a.ratio);
  return out.slice(0, 3).map(x => {
    const half = x.r[1] === 'sacks', f = v => (half ? GI.num(v, 1) : QK.fmt.num(Math.round(v)));
    const on = x.ratio >= 1;
    return { kicker: on ? 'On record pace' : 'Records in reach', sport: 'nfl', name: x.p.name, sub: [GI.teamAbbr(x.s.team), x.p.pos, x.s.games + ' games'].join(' · '),
      value: f(x.pace), unit: x.r[4] + ' pace', colour: GI.teamInfo(x.s.team).colour, mark: { name: GI.teamName(x.s.team), abbr: GI.teamAbbr(x.s.team), colour: GI.teamInfo(x.s.team).colour },
      pace: { now: x.v, pace: x.pace, target: x.r[2], label: 'Record', fmt: f },
      text: f(x.v) + ' ' + x.r[4] + ' in ' + x.s.games + ' games. At that rate, ' + f(x.pace) + ' over 17 games; the most in a season since 1999 in our play-by-play is ' + f(x.r[2]) + ' (' + x.r[3] + '). ' + (x.s.games <= 8 ? x.s.games + ' games is a small sample: early paces usually cool.' : ''),
      href: GI.playerHref(x.p.id) };
  });
}
function breakoutCards(files, S) {
  const out = [];
  Object.keys(files).forEach(id => {
    const p = files[id], c = seasonOf(p, S), b = seasonOf(p, S - 1), pc = qualPct(p, c), pb = qualPct(p, b);
    if (!isNum(pc) || !isNum(pb) || pc < 75 || pc - pb < 25) return;
    out.push({ p: p, c: c, b: b, pc: pc, pb: pb, d: pc - pb });
  });
  out.sort((a, b) => b.d - a.d);
  return out.slice(0, 3).map((x, i) => {
    const grp = GROUP_PL[x.c.pg] || 'players at the position';
    const line = (x.p.seasons || []).filter(s => s.qualified && isNum(gvar(x.p, s)) && s.season <= S);
    return { kicker: JUMP[i], sport: 'nfl', name: x.p.name, sub: [GI.teamAbbr(x.c.team), x.p.pos, isNum(x.c.age) ? 'age ' + Math.floor(x.c.age) : ''].filter(Boolean).join(' · '),
      value: '+' + Math.round(x.d), unit: 'percentile points', colour: GI.teamInfo(x.c.team).colour, mark: { name: GI.teamName(x.c.team), abbr: GI.teamAbbr(x.c.team), colour: GI.teamInfo(x.c.team).colour },
      from: { label: String(S - 1), value: QK.ordinal(Math.round(x.pb)), pos: x.pb }, to: { label: S + ' so far', value: QK.ordinal(Math.round(x.pc)), pos: x.pc },
      spark: line.length > 2 ? line.map(s => gvar(x.p, s)) : null, sparkLabel: line.length > 2 ? 'Value a game (ours), ' + line[0].season + '–' + line[line.length - 1].season : '',
      text: 'From the ' + QK.ordinal(Math.round(x.pb)) + ' to the ' + QK.ordinal(Math.round(x.pc)) + ' percentile of ' + grp + ' in value a game, our player value model. ' + x.c.games + ' games in: a small sample, so watch whether it holds.',
      href: GI.playerHref(x.p.id) + '?view=progression', link: { text: 'Progression' } };
  });
}
function spotlightHTML(files, lead, S) {
  const counted = {}, topOfBoard = {};
  RECORDS.forEach(r => (((lead.players || {})[r[0]] || {})[r[1]] || []).slice(0, 10).forEach(x => { counted[x[0]] = 1; }));
  VALUE_BOARDS.forEach(v => { const t = (((lead.players || {})[v[0]] || {})[v[1]] || [])[0]; if (t) topOfBoard[t[0]] = 1; });
  let best = null;
  Object.keys(files).forEach(id => {
    const p = files[id], c = seasonOf(p, S), pc = qualPct(p, c), gv = gvar(p, c);
    if (!c || c.pg === 'qb' || !isNum(pc) || pc < 90 || counted[id] || topOfBoard[id] || !isNum(gv)) return;
    if (!best || gv > best.gv) best = { p: p, c: c, pc: pc, gv: gv };
  });
  if (!best) return '';
  const c = best.c, P = best.p, keys = (SPOT_KEYS[c.pg] || Object.keys(c.pct || {}).filter(k => k !== 'gvar_pg')).filter(k => isNum(metricOf(P, c, k).pct)).slice(0, 4);
  const line = (P.seasons || []).filter(s => s.qualified && isNum(gvar(P, s)) && s.season <= S);
  const grp = GROUP_PL[c.pg] || 'players at the position';
  return QK.spotlight({ kicker: 'Best player nobody talks about', name: best.p.name, sub: [GI.teamName(c.team), best.p.pos, isNum(c.age) ? 'age ' + Math.floor(c.age) : ''].filter(Boolean).join(' · '),
    number: best.p.number, team: { name: GI.teamName(c.team), abbr: GI.teamAbbr(c.team), colour: GI.teamInfo(c.team).colour }, href: GI.playerHref(best.p.id),
    headline: QK.ordinal(Math.round(best.pc)) + ' percentile of ' + grp + ' in value a game, and on none of the yardage, touchdown or sack top tens.',
    stats: [{ label: 'Value a game (ours)', value: GI.num(best.gv, 2), pctl: best.pc }].concat(keys.slice(0, 3).map(k => ({ label: SPOT_LABEL[k] || GI.titleCase(k), value: spotVal(k, metricOf(P, c, k).v), pctl: metricOf(P, c, k).pct }))),
    spark: line.length > 1 ? { values: line.map(s => gvar(P, s)), labels: [String(line[0].season), String(line[line.length - 1].season)], label: 'Value a game by season' } : null,
    text: 'Percentiles against qualified ' + grp + ' this season, ' + c.games + ' games in. Value a game is our player value model: what he adds over a replacement-level player, per game.',
    links: [{ href: GI.playerHref(best.p.id), text: 'Player page' }, { href: GI.playerHref(best.p.id) + '?view=progression', text: 'Progression' }, { href: '#/compare', text: 'Compare' }] });
}
function turnCards(rows, prevRows, po, S) {
  const prev = {};
  prevRows.forEach(r => { prev[GI.canonTeam(r.team)] = r; });
  const pctOf = r => (r.w + 0.5 * (r.t || 0)) / Math.max(1, r.w + r.l + (r.t || 0));
  const out = rows.filter(r => prev[GI.canonTeam(r.team)] && r.w + r.l + (r.t || 0) >= 3).map(r => { const b = prev[GI.canonTeam(r.team)]; return { r: r, b: b, d: pctOf(r) - pctOf(b) }; }).sort((x, y) => y.d - x.d);
  if (out.length < 2) return [];
  const card = (x, k) => ({ kicker: k, sport: 'nfl', name: GI.teamName(x.r.team), sub: GI.teamAbbr(x.r.team) + ' · ' + (x.r.division || ''), colour: GI.teamInfo(x.r.team).colour,
    mark: { name: GI.teamName(x.r.team), abbr: GI.teamAbbr(x.r.team), colour: GI.teamInfo(x.r.team).colour }, value: (x.d > 0 ? '+' : '−') + Math.abs(Math.round(100 * x.d)), unit: 'points of win %',
    from: { label: (S - 1) + ' ' + GI.record(x.b.w, x.b.l, x.b.t), value: Math.round(100 * pctOf(x.b)) + '%', pos: 100 * pctOf(x.b) }, to: { label: S + ' ' + GI.record(x.r.w, x.r.l, x.r.t), value: Math.round(100 * pctOf(x.r)) + '%', pos: 100 * pctOf(x.r) },
    text: The(x.r.team) + ' went ' + GI.record(x.b.w, x.b.l, x.b.t) + ' last season and are ' + GI.record(x.r.w, x.r.l, x.r.t) + ' now' + (isNum((po[x.r.team] || {}).p_playoffs) ? '; our playoff chance is ' + GI.pct(po[x.r.team].p_playoffs, 0) + '.' : '.'),
    href: GI.teamHref(x.r.team) });
  return [card(out[0], 'Biggest turnaround'), card(out[out.length - 1], 'Biggest fall')];
}
function fanModules(el, S, rows, po) {
  GI.loadAll([GI.ypath('leaders.json', S), GI.ypath('season.json', S - 1), 'history.json']).then(res => {
    if (!el.isConnected) return;
    const lead = GI.ok(res[0]) ? res[0] : {}, prevRows = GI.ok(res[1]) ? seasonRows(res[1]) : [], hist = GI.ok(res[2]) ? res[2] : null;
    const turn = turnCards(rows, prevRows, po, S);
    if (turn.length) GI.set('ov-turn', QK.sectionHead({ kicker: 'Biggest surprise', title: 'Up and down', sub: 'This season’s record so far against last season’s, every team.' }) + QK.storyCards(turn, { cols: 1 }));
    const ids = {};
    VALUE_BOARDS.forEach(v => ((((lead.players || {})[v[0]] || {})[v[1]]) || []).slice(0, 6).forEach(x => { ids[x[0]] = 1; }));
    RECORDS.forEach(r => { const t = ((((lead.players || {})[r[0]] || {})[r[1]]) || [])[0]; if (t) ids[t[0]] = 1; });
    const list = Object.keys(ids);
    return Promise.all(list.map(id => GI.loadPlayer(id))).then(ps => {
      if (!el.isConnected) return;
      const files = {};
      ps.forEach((p, i) => { if (p && GI.ok(p)) files[list[i]] = p; });
      const pc = paceCards(lead, files, S, hist);
      if (pc.length) GI.set('ov-pace', QK.sectionHead({ kicker: 'Records in reach', title: 'On pace for history?', sub: 'Each leader’s rate so far over a 17-game season, against the most in a season in our play-by-play (1999 on, regular season). Early in a season every pace looks huge; the bars show how far there is to go.', actions: '<a class="qk-more" href="#/scout?view=leaders">Every leaderboard</a>' }) + QK.storyCards(pc));
      const bc = breakoutCards(files, S);
      if (bc.length) GI.set('ov-break', QK.sectionHead({ kicker: 'Breakout watch', title: 'Who took the leap', sub: 'The biggest jumps in our value-a-game percentile from last season, among the leaders on the value boards. Both seasons qualified.' }) + QK.storyCards(bc));
      const sp = spotlightHTML(files, lead, S);
      if (sp) GI.set('ov-spot', sp);
    });
  });
}

GI.route('overview', function (el) {
  const idx = GI.index() || {};
  if (!GI.ok(idx)) { el.innerHTML = GI.pageHead('NFL', 'The Quant Gridiron', '') + GI.notBuilt('The overview', idx); return; }
  const S = GI.currentSeason(), W = GI.currentWeek();
  return GI.loadAll([GI.ypath('season.json', S), 'glossary.json']).then(res => {
    if (!el.isConnected) return;
    const season = GI.ok(res[0]) ? res[0] : null, G = glossIndex(res[1]);
    const all = (idx.games || []).slice().sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
    const games = all.filter(g => !GI.isStale(g));
    const stale = all.length - games.length;
    const liveIds = {};
    games.filter(GI.isLive).forEach(g => { liveIds[g.game_id] = 1; });
    (idx.live || []).forEach(g => { if (g && GI.isLive(g) && !GI.isStale(g)) liveIds[g.game_id] = 1; });
    const live = games.filter(g => liveIds[g.game_id]);
    const po = idx.playoff_odds || {};
    const rows = seasonRows(season);
    const byTeam = GI.rowsByTeam(rows);
    const ph = GI.phase();
    const phaseText = ph === 'playoffs' ? 'Playoffs' : ph === 'offseason' ? 'Offseason' : ph === 'preseason' ? 'Preseason' : 'Regular season';
    const ratings = (season && season.ratings) || {};
    const L = idx.leaders || {};
    const dig = idx.digest || {};
    const feat = pickFeatured(idx, games.concat((idx.live || []).filter(g => g && !liveIds[g.game_id] && GI.isLive(g))), po);
    const tick = games.length ? '<div class="qk-ticker gi-ticker" aria-label="This week\'s games">' + QK.ticker(games.map(g => GI.qkGame(g, byTeam)), { group: 'league', pill: false, market: 'quiet' }) + '</div>' : '';
    const wk = GI.weekLabel(W, S);

    el.innerHTML = tick +
      intro({ tag: 'NFL · ' + S + ' · ' + phaseText + ' · ' + wk, title: 'Every NFL game, team and player, by the numbers.',
        lede: 'Our chance for every game this week, the playoff race from 20,000 simulated seasons, every fourth down graded, and the players behind it all, in plain English.',
        links: [{ label: 'Games', sub: 'All ' + wk + ', our chance', href: GI.weekHref(S, W) }, { label: 'Playoff race', sub: 'Standings and seeds', href: '#/standings' }, { label: 'Scouting Room', sub: 'Every player, every metric', href: '#/scout' }] }) +
      '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in the NFL', title: '<span id="ov-wk">The week so far</span>', html: true, sub: esc(stageLine(dig.stage, ph)) }) +
        '<div id="ov-week"></div><div id="ov-feat" class="ql-feat"></div></section>' +

      '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch', title: '<span id="ov-gh">Games we’d pick</span>', html: true,
        sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.',
        actions: GI.seg('ov-when', [['picks', 'Our picks'], ['all', 'All ' + all.length], ['results', 'Last week', !(idx.recent || []).length]], 'picks', 'Games') }) +
        '<div id="ov-games"></div>' +
        (stale ? '<p class="qk-caption">' + stale + ' game' + (stale === 1 ? '' : 's') + ' from ' + esc(wk) + ' ' + (stale === 1 ? 'is' : 'are') + ' waiting for ' + (stale === 1 ? 'its result' : 'their results') + ' in the next update; the <a href="' + GI.weekHref(S, W) + '">week page</a> keeps our pre-game forecast for each.</p>' : '') + '</section>' +

      '<div id="ov-hot"></div>' +

      '<section class="qk-section" id="ov-pace"></section><section class="qk-section" id="ov-break"></section><section class="qk-section" id="ov-spot"></section>' +
      '<section class="qk-section qk-g75">' +
        '<div class="gi-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Teams top-left are winning more than their play suggests; bottom-right, the reverse. A hot start, or something real?' }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Win percentage against EPA per play margin, every team"></div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div><div id="ov-turn"></div></section>' +

      '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0], 'A <b>rating</b> is points a game better than an average team on a neutral field: +7 is a touchdown better.', '<b>EPA</b> (expected points added) scores every play by how much it moved the expected score: a first down on third and long is worth more than a short gain on first down.'] }) + '</section>' +

      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who lifts the Lombardi Trophy?', sub: '<span id="ov-sb-lede">Our chances from 20,000 simulated seasons.</span>', html: true, actions: '<a class="qk-more" href="#/playoffs">Every chance</a>' }) +
        GI.grid(GI.card('Super Bowl chances', 'Our chance from 20,000 simulated seasons, in team colours', '<div id="ov-sb"></div>', { span: 6, foot: '<span>Top ten of 32</span><a href="#/playoffs">Bracket →</a>' }) +
          GI.card('Projected wins', 'Mean of the simulated seasons (dot) and its 90% range (bar)', GI.chartBox('ov-range', 520, 'Projected wins with a 90% range'), { span: 6, foot: '<span>Range: 5th to 95th percentile of 20,000 seasons</span><a href="' + GI.ghref('playoffs', S, { view: 'wins' }) + '">Win totals →</a>' })) +
        QK.explain('<b>What’s that number?</b> Even the favourite misses most seasons. A 20% Super Bowl chance means four seasons in five end without the trophy.') + '</section>' +

      '<p class="gi-cap gi-ov-teaser">Offence against defence, every team on our ratings: the <a href="' + GI.ghref('teams', S, { sec: 'map' }) + '">style map on Teams →</a></p>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Playoff race', title: 'Division by division', sub: 'Record and our playoff chance from 20,000 simulated seasons; tap a team for its page.', actions: '<a class="qk-more" href="#/playoffs">Seeds and bracket</a>' }) +
        GI.card('', '', divisionsGrid(rows)) + '</section>' +


      /* our record and calibration live on the Model page ("How we're doing"): one small link here */
      '<p class="qk-sub gi-ov-doing">Every forecast is checked against the result: <a class="qk-link" href="#/calibration">How we’re doing →</a></p>';

    /* What to watch: our six picks (live first, then the closest calls with the most at stake), every game this week,
       or last week's results with our pre-game call; each card with its one-line reason, no market */
    const rank = {};
    ((feat && feat.order) || []).forEach((id, i) => { rank[id] = i + 1; });
    const picks = games.filter(g => GI.isLive(g) || GI.isPre(g)).sort((a, b) => ((rank[a.game_id] || 99) - (rank[b.game_id] || 99)) || (watchVal(b, po) - watchVal(a, po))).slice(0, 6);

    // this week: the top lines, then the game that matters most (or the Super Bowl race when nothing big is on)
    const T = weekTiles(dig, feat, po);
    GI.set('ov-week', T.length ? QK.stats(T) : '');
    if (T.length >= 3) GI.set('ov-wk', 'The week in ' + WORDS[T.length].toLowerCase() + ' lines');
    if (feat && feat.c) {
      const fq = GI.qkGame(feat.c, byTeam), lab = whenLabel(fq);
      fq.league = (feat.c.week ? GI.weekLabel(feat.c.week, GI.gameSeason(feat.c.game_id)) : wk) + (feat.c.div_game ? ' · Division game' : '');
      GI.set('ov-feat', QK.featureCard(fq, { scribble: lab + (feat.week && !/^(Today|Tonight|Live now)$/.test(lab) ? ' · The big one this week' : ' · The one to watch'), nick: t => t.name, note: heroNote(fq, feat.why) }));
    }
    const NUM = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'];
    const drawGames = w => {
      const list = w === 'all' || !picks.length && w === 'picks' ? all : w === 'results' ? (idx.recent || []) : picks;
      const n = list.length;
      GI.set('ov-gh', w === 'all' || !picks.length && w === 'picks' ? 'Every game in ' + esc(wk) : w === 'results' ? 'How last week went' : NUM[n] + ' game' + (n === 1 ? '' : 's') + '. Our calls.');
      GI.set('ov-games', n ? '<div class="qk-watch">' + list.map(g => GI.gameCard(g, { rows: byTeam, why: true, date: w === 'results', compact: w === 'results' })).join('') + '</div>' : QK.empty('No games this week', 'The schedule is being set.'));
    };
    drawGames('picks');
    GI.wireSeg(el, 'ov-when', drawGames);

    // who's hot: the black power list, the top name on five boards
    const hot = hotItems(L, G);
    GI.set('ov-hot', hot.length ? QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, board by board', sub: 'The top name on five of our leaderboards, qualified players only, and a line on what each number means.', actions: '<a class="qk-more" href="#/scout?view=leaders">Every leaderboard</a>' }) + QK.hotRow(hot)) : '');

    /* round 6: the fan modules, lazily (records in reach, breakout watch, the spotlight, the turnarounds) */
    fanModules(el, S, rows, po);

    /* Who's for real?: win % against the EPA-per-play margin (offence EPA a play less the EPA a play allowed) */
    const luck = rows.filter(r => r.w + r.l + (r.t || 0) > 0 && ratings[r.team] && isNum((ratings[r.team].values || {}).off_epa) && isNum((ratings[r.team].values || {}).def_epa));
    if (luck.length >= 8) {
      const pts = luck.map(r => { const v = ratings[r.team].values; return { x: v.off_epa - v.def_epa, y: 100 * (r.w + 0.5 * (r.t || 0)) / (r.w + r.l + (r.t || 0)), label: GI.teamAbbr(r.team), name: GI.teamName(r.team), sub: GI.record(r.w, r.l, r.t) + ' · EPA a play ' + GI.signed(v.off_epa, 3) + ' for, ' + GI.signed(v.def_epa, 3) + ' allowed', color: GI.teamInfo(r.team).colour || GI.teamColour(r.team), href: GI.teamHref(r.team) }; });
      const gps = luck.map(r => r.w + r.l + (r.t || 0)), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
      QKC.quadrant('#ov-luck', { points: pts, xName: 'EPA per play margin (offence less defence)', yName: 'Win %', refX: 0, refY: 50, yMin: 0, yMax: 100,
        xFmt: v => GI.signed(v, 2), yFmt: v => Math.round(v) + '%', label: 'NFL teams: EPA per play margin against win percentage' });
      GI.set('ov-luck-cap', 'NFL ' + S + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. EPA per play margin: expected points added a play on offence, less what the defence allows. Dashed lines: an even margin and a .500 record. Tap a team for its page.');
    } else el.querySelector('#ov-luck').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');

    // Super Bowl: our chance only (no market on the overview), each bar in the team's colours
    const chRow = (t, p) => ({ label: GI.teamShort(t), p: p, href: GI.teamHref(t), color: GI.teamInfo(t).colour, mark: { name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour } });
    const sbRows = Object.keys(po).filter(t => isNum(po[t].p_sb)).map(t => chRow(t, po[t].p_sb));
    GI.set('ov-sb', sbRows.length ? QK.chances(sbRows, { limit: 10, key: false }) : GI.muted('The season simulation has not run yet.'));
    const sb0 = sbRows.slice().sort((a, b) => b.p - a.p)[0];
    if (sb0) GI.set('ov-sb-lede', esc((sb0.p < 0.25 ? 'Nobody’s better than 1 in 4. The ' + sb0.label + ' lead our board at ' + GI.pct(sb0.p, 0) + '.' : 'The ' + sb0.label + ' lead at ' + GI.pct(sb0.p, 0) + '.') + ' From 20,000 simulated seasons.'));

    // projected wins: mean and the 90% range
    const rr = rows.filter(r => isNum(r.mean_wins) && isNum(r.w_p05) && isNum(r.w_p95)).sort((a, b) => b.mean_wins - a.mean_wins);
    if (rr.length) {
      const show = rr.slice(0, 16);
      const n = el.querySelector('#ov-range');
      if (n) {
        const c = QKC.range(n, { rows: show.map(r => ({ label: GI.teamName(r.team), lo: r.w_p05, hi: r.w_p95, mid: r.mean_wins, href: GI.teamHref(r.team), color: GI.teamColour(r.team), sub: GI.record(r.w, r.l, r.t) + ' now · ' + GI.pct(r.p_playoffs, 0) + ' to make the playoffs' })),
          fmt: v => GI.num(v, 1), loName: '5th', hiName: '95th percentile', midName: 'Projected wins', valName: 'Wins at season end', labelWidth: 150 });
        if (c) GI.onLeave(() => { try { c.dispose(); } catch (e) { /* gone */ } });
        n.insertAdjacentHTML('afterend', '<p class="qk-caption">The top sixteen by projected wins. Each bar spans the 5th to 95th percentile of the team’s wins across the simulated seasons.</p>');
      }
    } else GI.ch.none('ov-range', 'The projection appears once the season simulation has run.');

    if (live.length) GI.liveRefresh([], 60000);
  });
});


})(window.GI);
