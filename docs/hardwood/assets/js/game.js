/* The Quant Hardwood — the game centre (#/<L>/game/<gid>) and the games list (#/<L>/games[/<date>]).
 *
 * Game centre, from <L>/<S>/games/<gid>.json:
 *   head: teams, score, status, line score, series, venue;
 *   pregame: model line against the market (win %, spread, total), Elo, the margin broken into
 *            its parts (ratings, home court, rest, travel, injuries) and the injury report;
 *   awards; box score with advanced columns; Four Factors; margin flow; win probability (model and
 *   ESPN, top plays marked); shot charts per team (make/miss, xPTS, hex against the league, zones)
 *   with the shot-quality split; lineups; rotation chart; key plays with WPA.
 *   Box-only seasons (no play-by-play) and upcoming games show what exists.
 *
 * Games list: the season's games by local date with a date picker, built from index.json
 * (today / next / last), an optional <L>/<S>/schedule.json ([GAME_CARD] or {games:[...]}) and the
 * team game logs in teams.json (results of every played game). */
(function (HW) {
'use strict';

const esc = HW.esc;

// ── helpers ────────────────────────────────────────────────────────────────

/* Minutes from a box value: seconds when large (store format), else minutes. */
function minutesOf(v) { return HW.isNum(v) ? (Number(v) > 70 ? Number(v) / 60 : Number(v)) : null; }
function scoreText(s) {
  if (Array.isArray(s)) return s[0] + '-' + s[1];
  return s === null || s === undefined ? '' : String(s);
}
function teamsOf(g) { return [String(g.away), String(g.home)]; }
function otherTeam(g, t) { return String(t) === String(g.home) ? String(g.away) : String(g.home); }

/* Load the game, trying the season in the URL first, then the other seasons of the league. */
function loadGame(L, S, gid) {
  const tried = [S];
  const tryOne = s => HW.load(L + '/' + s + '/games/' + gid + '.json').then(d => (d ? { d: d, s: s } : null));
  return tryOne(S).then(r => {
    if (r) return r;
    const rest = HW.seasons(L).filter(s => tried.indexOf(s) < 0).slice(0, 3);
    let p = Promise.resolve(null);
    rest.forEach(s => { p = p.then(x => x || tryOne(s)); });
    return p;
  });
}

// ── head ───────────────────────────────────────────────────────────────────

function headHTML(L, g, S) {
  const st = HW.gameState(g);
  const done = st === 'post';
  const hs = g.hs, as = g.as;
  const side = (tid, pts, home) => {
    const win = done && HW.isNum(hs) && HW.isNum(as) && (home ? hs > as : as > hs);
    const nm = '<div><div class="gm-tname">' + HW.teamLink(L, tid, { bar: false }) + '</div><div class="gm-trec">' + (home ? 'Home' : 'Away') + '</div></div>';
    const bar = HW.teamBar(L, tid);
    const score = st === 'pre' || !HW.isNum(pts) ? '' : '<div class="gm-pts' + (win ? ' win' : '') + '">' + pts + '</div>';
    return '<div class="gm-team' + (home ? ' home' : '') + '">' + (home ? score + nm + bar : bar + nm + score) + '</div>';
  };
  const kick = [HW.stypeLabel(g.stype), g.series && (g.series.summary || g.series.round) ? esc(g.series.summary || g.series.round) : '',
    esc(HW.fmtDate(g.date, { time: true })), g.venue ? esc(typeof g.venue === 'object' ? [g.venue.name, g.venue.city].filter(Boolean).join(', ') : g.venue) : '',
    HW.isNum(g.attendance) && g.attendance > 0 ? 'Attendance ' + Number(g.attendance).toLocaleString('en-GB') : ''].filter(Boolean);
  let html = '<div class="gm-head"><div class="gm-kicker">' + kick.join(' · ') + '</div>' +
    '<div class="gm-score">' + side(g.away, as, false) + '<div class="gm-mid">' + HW.statusChip(g, L) + (st === 'pre' ? '<div class="gm-sub">' + esc(HW.countdown(g.date) || '') + '</div>' : '') + '</div>' + side(g.home, hs, true) + '</div>';
  const ln = g.line || {};
  const la = ln.away || ln[g.away] || [], lh = ln.home || ln[g.home] || [];
  if (la.length || lh.length) {
    const n = Math.max(la.length, lh.length);
    const cols = [{ label: '', sortable: false }].concat(Array.from({ length: n }, (_, i) => ({ label: HW.periodLabel(L, i + 1), sortable: false, align: 'center' }))).concat([{ label: 'T', sortable: false, align: 'center' }]);
    const row = (tid, arr, tot) => [{ html: HW.teamBar(L, tid) + esc(HW.teamAbbr(L, tid)) }].concat(Array.from({ length: n }, (_, i) => ({ v: arr[i], html: HW.isNum(arr[i]) ? String(arr[i]) : '' }))).concat([{ html: '<b>' + (HW.isNum(tot) ? tot : '') + '</b>' }]);
    html += '<div class="linescore">' + HW.tableHTML(cols, [row(g.away, la, as), row(g.home, lh, hs)], { compact: true }) + '</div>';
  }
  return html + '</div>';
}

// ── pregame ────────────────────────────────────────────────────────────────

function pregameHTML(L, g) {
  const pre = g.pregame || {};
  const m = pre.model || {}, mk = pre.market || null;
  if (!HW.isNum(m.p_home) && !mk) return '';
  const H = HW.teamAbbr(L, g.home), A = HW.teamAbbr(L, g.away);
  const box = (k, v, s) => '<div class="pre-box"><div class="pre-k">' + esc(k) + '</div><div class="pre-v">' + v + '</div><div class="pre-s">' + s + '</div></div>';
  const fav = HW.isNum(m.p_home) ? (m.p_home >= 0.5 ? g.home : g.away) : null;
  const pf = fav ? (fav === g.home ? m.p_home : 1 - m.p_home) : null;
  let html = '<div class="pre-grid">' +
    box('Win probability', fav ? esc(HW.teamAbbr(L, fav)) + ' ' + HW.pct(pf, 0) : '—',
      'fair ' + esc(H) + ' ' + HW.american(m.p_home) + ' · ' + esc(A) + ' ' + HW.american(HW.isNum(m.p_home) ? 1 - m.p_home : null) +
      (mk && HW.isNum(mk.p_home) ? '<br>market ' + esc(H) + ' ' + HW.pct(mk.p_home, 0) + ' (' + HW.edgeHTML(m.p_home, mk.p_home) + ' pp)' : '')) +
    box('Spread', esc(H) + ' ' + HW.fmtSpread(HW.isNum(m.spread_fair) ? m.spread_fair : (HW.isNum(m.margin) ? -m.margin : null)),
      'model margin ' + HW.signed(m.margin, 1) + (HW.isNum(m.sd) ? ' ± ' + HW.num(m.sd, 1) : '') + (mk && HW.isNum(mk.spread_home) ? '<br>market ' + esc(H) + ' ' + HW.fmtSpread(mk.spread_home) : '')) +
    box('Total', HW.num(m.total, 1), (HW.isNum(m.pts_home) ? esc(H) + ' ' + HW.num(m.pts_home, 1) + ' · ' + esc(A) + ' ' + HW.num(m.pts_away, 1) : 'projected points') +
      (mk && HW.isNum(mk.total) ? '<br>market ' + HW.num(mk.total, 1) : '')) + '</div>';
  const det = m.detail || {};
  const parts = ['rating', 'hca', 'rest', 'b2b', 'travel', 'tz', 'altitude', 'injury']   // pace sets the total, not the margin.filter(k => HW.isNum(det[k]) && Math.abs(det[k]) > 0.005);
  const label = { rating: 'Team ratings', hca: 'Home court', rest: 'Rest', b2b: 'Back-to-back', travel: 'Travel', tz: 'Time zones', altitude: 'Altitude', injury: 'Injuries', pace: 'Pace' };
  if (parts.length) {
    html += '<div class="section-note">How the model builds the ' + esc(H) + ' margin (points): ' + parts.map(k => esc(label[k]) + ' <b>' + HW.signed(det[k], 1) + '</b>').join(' · ') +
      (HW.isNum(pre.elo_p_home) ? ' · Elo alone: ' + esc(H) + ' ' + HW.pct(pre.elo_p_home, 0) : '') + '</div>';
  } else if (HW.isNum(pre.elo_p_home)) {
    html += '<div class="section-note">Elo alone: ' + esc(H) + ' ' + HW.pct(pre.elo_p_home, 0) + '</div>';
  }
  if (mk && mk.sources && mk.sources.length) html += '<div class="section-note">Market: ' + mk.sources.map(s => '<span class="src-chip">' + esc(s) + '</span>').join('') + ', de-vigged.</div>';
  const inj = pre.injuries || {};
  const injT = teamsOf(g).filter(t => (inj[t] || []).length);
  if (injT.length) {
    html += '<div class="grid-2" style="gap:0">' + injT.map(t => '<div class="inj-list"><div class="day-head" style="padding:4px 0">' + HW.teamBar(L, t) + esc(HW.teamName(L, t)) + ' injuries</div>' +
      inj[t].map(x => '<div class="inj-row"><span>' + (x.player && HW.NAMES[L].players[String(x.player)] ? HW.playerLink(L, x.player) : esc(x.name || x.player)) + ' <span class="inj-st">' + esc(x.status || '') + '</span></span>' +
        '<span class="num" title="Effect on the team margin, points">' + (HW.isNum(x.impact) ? HW.signed(x.impact, 1) : '') + '</span></div>').join('') + '</div>').join('') + '</div>';
  }
  return HW.card(HW.gameState(g) === 'pre' ? 'Preview' : 'Pregame', 'model against the market', html);
}

// ── awards ─────────────────────────────────────────────────────────────────

function awardsHTML(L, g) {
  const a = g.awards || {};
  const defs = [['player_of_game', 'Player of the game'], ['biggest_swing', 'Biggest swing'], ['shot_maker', 'Shot maker'], ['unluckiest', 'Unluckiest shooter'], ['stopper', 'Stopper']];
  const cards = defs.filter(d => a[d[0]] && a[d[0]].player).map(d => {
    const x = a[d[0]];
    return '<div class="award" style="border-top-color:' + esc(HW.teamColour(L, x.team)) + '"><div class="aw-title">' + esc(d[1]) + '</div>' +
      '<div class="aw-who">' + HW.playerLink(L, x.player, { team: x.team }) + '</div><div class="aw-val">' + esc(x.label || (HW.isNum(x.value) ? HW.num(x.value, 2) : '')) + '</div>' +
      (x.why ? '<div class="aw-why">' + esc(x.why) + '</div>' : '') + '</div>';
  });
  const extra = [];
  if (HW.isNum(a.excitement)) extra.push('Excitement index <b>' + HW.num(a.excitement, 1) + '</b>');
  if (HW.isNum(a.comeback)) extra.push('Comeback: the winner was down to <b>' + HW.pct(a.comeback, 1) + '</b> win probability');
  if (!cards.length && !extra.length) return '';
  return HW.card('Game awards', '', (cards.length ? '<div class="awards pad">' + cards.join('') + '</div>' : '') + (extra.length ? '<div class="section-note">' + extra.join(' · ') + '</div>' : ''));
}

// ── box score ──────────────────────────────────────────────────────────────

function boxTable(L, g, tid) {
  const b = (g.box || {})[tid];
  if (!b || !(b.players || []).length) return HW.muted('No box score for this team.');
  const players = b.players.slice();
  const has = k => players.some(p => HW.isNum(p[k]));
  const adv = [['ts', 'TS%', 'pct', 'True shooting'], ['usg', 'USG%', 'pct', 'Usage rate'], ['game_score', 'GmSc', '1', 'Game score'],
    ['wpa', 'WPA', 'wpa', 'Win probability added (percentage points)'], ['pox', 'POX', 'pm', 'Points over expected on shots (made points minus xPTS)']].filter(a => has(a[0]));
  const cols = [{ label: 'Player' }, { label: 'MIN', align: 'right' }, { label: 'PTS', align: 'right' }, { label: 'REB', align: 'right', title: 'Rebounds (offensive-defensive)' },
    { label: 'AST', align: 'right' }, { label: 'STL', align: 'right' }, { label: 'BLK', align: 'right' }, { label: 'TOV', align: 'right' }, { label: 'PF', align: 'right', cls: 'hide-sm' },
    { label: 'FG', align: 'right' }, { label: '3P', align: 'right' }, { label: 'FT', align: 'right' }, { label: '+/-', align: 'right' }]
    .concat(adv.map(a => ({ label: a[1], align: 'right', title: a[3] })));
  players.sort((a, b2) => ((b2.starter ? 1 : 0) - (a.starter ? 1 : 0)) || ((minutesOf(b2.min) || 0) - (minutesOf(a.min) || 0)));
  let firstBench = true;
  const rows = players.map(p => {
    const mins = minutesOf(p.min);
    const sep = !p.starter && firstBench && players.some(x => x.starter);
    if (!p.starter) firstBench = false;
    const cell = (v, html) => ({ v: v, html: html === undefined ? (HW.isNum(v) ? String(v) : '—') : html, cls: sep ? 'starter-sep' : '' });
    return { cells: [
      cell(p.name, HW.playerLink(L, p.id, { name: p.name }) + (p.pos ? ' <span class="muted-inline" style="font-size:0.72rem">' + esc(p.pos) + '</span>' : '')),
      cell(mins, HW.isNum(mins) ? HW.fmtMin(mins) : '—'),
      cell(p.pts, '<b>' + (HW.isNum(p.pts) ? p.pts : '—') + '</b>'),
      cell(p.reb, (HW.isNum(p.reb) ? p.reb : '—') + (HW.isNum(p.oreb) ? ' <span class="muted-inline" style="font-size:0.72rem">' + p.oreb + '-' + p.dreb + '</span>' : '')),
      cell(p.ast), cell(p.stl), cell(p.blk), cell(p.tov), cell(p.pf),
      cell(p.fgm, HW.isNum(p.fga) ? p.fgm + '-' + p.fga : '—'), cell(p.tpm, HW.isNum(p.tpa) ? p.tpm + '-' + p.tpa : '—'), cell(p.ftm, HW.isNum(p.fta) ? p.ftm + '-' + p.fta : '—'),
      cell(p.pm, HW.isNum(p.pm) ? '<span class="' + (p.pm > 0 ? 'pos-up' : p.pm < 0 ? 'pos-down' : '') + '">' + HW.signed(p.pm, 0) + '</span>' : '—')
    ].concat(adv.map(a => cell(p[a[0]], a[2] === 'wpa' ? (HW.isNum(p.wpa) ? HW.signed(p.wpa * (Math.abs(p.wpa) <= 1 ? 100 : 1), 1) : '—') : HW.fmtVal(p[a[0]], a[2])))) };
  });
  const t = b.team || {};
  if (HW.isNum(t.fga) || HW.isNum(t.pts)) {
    const tpts = HW.isNum(t.pts) ? t.pts : (String(tid) === String(g.home) ? g.hs : g.as);
    const treb = HW.isNum(t.reb) ? t.reb : (HW.isNum(t.oreb) ? t.oreb + t.dreb : null);
    rows.push({ _class: 'box-total', cells: [{ v: 'zzz', html: 'Team' }, { html: '' }, { html: HW.isNum(tpts) ? String(tpts) : '' }, { html: HW.isNum(treb) ? String(treb) : '' },
      { html: HW.isNum(t.ast) ? String(t.ast) : '' }, { html: HW.isNum(t.stl) ? String(t.stl) : '' }, { html: HW.isNum(t.blk) ? String(t.blk) : '' }, { html: HW.isNum(t.tov) ? String(t.tov) : '' },
      { html: HW.isNum(t.pf) ? String(t.pf) : '' }, { html: HW.isNum(t.fga) ? t.fgm + '-' + t.fga : '' }, { html: HW.isNum(t.tpa) ? t.tpm + '-' + t.tpa : '' }, { html: HW.isNum(t.fta) ? t.ftm + '-' + t.fta : '' }, { html: '' }]
      .concat(adv.map(() => ({ html: '' }))) });
  }
  const extras = [];
  if (HW.isNum(t.ortg)) extras.push('Offensive rating ' + HW.num(t.ortg, 1));
  if (HW.isNum(t.pace)) extras.push('pace ' + HW.num(t.pace, 1));
  if (HW.isNum(t.pts_paint)) extras.push('paint points ' + t.pts_paint);
  if (HW.isNum(t.pts_fastbreak)) extras.push('fast-break ' + t.pts_fastbreak);
  if (HW.isNum(t.pts_off_tov)) extras.push('off turnovers ' + t.pts_off_tov);
  return HW.tableHTML(cols, rows, { compact: true, cls: 'box-table' }) + (extras.length ? '<div class="section-note">' + esc(extras.join(' · ')) + '</div>' : '');
}

function fourFactorsHTML(L, g) {
  const ff = g.four_factors || {};
  const a = ff[g.away], h = ff[g.home];
  if (!a || !h) return '';
  const defs = [['efg', 'Effective FG%', false], ['tov', 'Turnover rate', true], ['orb', 'Off. rebound rate', false], ['ftr', 'Free-throw rate', false]];
  const ac = HW.teamColour(L, g.away), hc = HW.teamColour(L, g.home);
  return '<div class="ff-bar" style="padding-top:10px"><span class="ff-v">' + HW.teamBar(L, g.away) + esc(HW.teamAbbr(L, g.away)) + '</span><span></span><span class="ff-v r">' + esc(HW.teamAbbr(L, g.home)) + HW.teamBar(L, g.home) + '</span></div>' +
    defs.map(d => {
      const av = a[d[0]], hv = h[d[0]];
      if (!HW.isNum(av) || !HW.isNum(hv)) return '';
      const better = d[2] ? (av < hv ? 'a' : 'h') : (av > hv ? 'a' : 'h');
      const tot = Math.abs(av) + Math.abs(hv) || 1;
      const aw = Math.abs(av) / tot * 100;
      return '<div class="ff-bar"><span class="ff-v' + (better === 'a' ? ' better' : '') + '">' + HW.fmtVal(av, 'pct') + '</span>' +
        '<div><div class="ff-mid">' + esc(d[1]) + (d[2] ? ' (lower is better)' : '') + '</div><div class="pw-track" style="display:flex;overflow:hidden">' +
        '<span style="width:' + aw.toFixed(1) + '%;background:' + esc(ac) + '"></span><span style="flex:1;background:' + esc(hc) + '"></span></div></div>' +
        '<span class="ff-v r' + (better === 'h' ? ' better' : '') + '">' + HW.fmtVal(hv, 'pct') + '</span></div>';
    }).join('') + '<div class="section-note">Dean Oliver’s four factors: shooting, ball security, offensive rebounding and getting to the line.</div>';
}

function shotQualityHTML(L, g) {
  const sq = g.shot_quality || {};
  const ids = teamsOf(g).filter(t => sq[t]);
  if (!ids.length) return '';
  return '<div class="sq-grid">' + ids.map(t => {
    const q = sq[t];
    const diff = HW.isNum(q.pts) && HW.isNum(q.xpts) ? q.pts - q.xpts : q.pox;
    return '<div class="sq-box"><h4>' + HW.teamBar(L, t) + esc(HW.teamName(L, t)) + '</h4>' +
      '<div class="sq-line"><span>Expected points from shot quality (xPTS)</span><b>' + HW.num(q.xpts, 1) + '</b></div>' +
      '<div class="sq-line"><span>Points scored on those shots</span><b>' + HW.num(q.pts, 0) + '</b></div>' +
      '<div class="sq-line"><span>Shot-making (points over expected)</span><b class="' + (diff > 0 ? 'edge-pos' : 'edge-neg') + '">' + HW.signed(diff, 1) + '</b></div>' +
      (HW.isNum(q.xefg) ? '<div class="sq-line"><span>Expected eFG%</span><b>' + HW.fmtVal(q.xefg, 'pct') + '</b></div>' : '') + '</div>';
  }).join('') + '</div><div class="section-note">Shot quality is what an average shooter would score from the same looks (location, shot type, assisted or not); shot-making is the rest.</div>';
}

function lineupsHTML(L, g, tid) {
  const lu = ((g.lineups || {})[tid] || []).slice().sort((a, b) => (b.sec || 0) - (a.sec || 0)).slice(0, 10);
  if (!lu.length) return HW.muted('No lineup data.');
  return HW.tableHTML([{ label: 'Lineup' }, { label: 'MIN', align: 'right' }, { label: 'Poss', align: 'right' }, { label: 'Pts +', align: 'right' }, { label: 'Pts −', align: 'right' }, { label: 'Net / 100', align: 'right' }],
    lu.map(x => [{ v: (x.players || []).join(','), html: '<span class="lu-players">' + (x.players || []).map(p => HW.playerLink(L, p, { short: true })).join(', ') + '</span>' },
      { v: x.sec, html: HW.fmtSec(x.sec) }, { v: x.poss, html: HW.num(x.poss, 0) }, { v: x.pts_for, html: String(x.pts_for) }, { v: x.pts_against, html: String(x.pts_against) },
      { v: x.net, html: HW.isNum(x.net) ? '<span class="' + (x.net > 0 ? 'pos-up' : x.net < 0 ? 'pos-down' : '') + '">' + HW.signed(x.net, 1) + '</span>' : '—' }]), { compact: true });
}

function playsHTML(L, g) {
  const plays = (g.plays || []).slice();
  if (!plays.length) return '';
  const top = plays.filter(p => HW.isNum(p.wpa)).slice().sort((a, b) => Math.abs(b.wpa) - Math.abs(a.wpa)).slice(0, 6);
  const topIdx = top.map(p => plays.indexOf(p));
  plays.sort((a, b) => (a.t || 0) - (b.t || 0));
  return '<div class="play-list">' + plays.map(p => {
    const rank = topIdx.indexOf((g.plays || []).indexOf(p));
    const w = HW.isNum(p.wpa) ? p.wpa * (Math.abs(p.wpa) <= 1 ? 100 : 1) : null;
    const signedW = w;
    return '<div class="play-row' + (rank >= 0 ? ' top' : '') + '"><span class="play-clock">' + esc(HW.periodLabel(L, p.period) + ' ' + (p.clock || '')) + '</span>' +
      (p.team ? HW.teamBar(L, p.team) : '<span></span>') + '<span class="play-text">' + (rank >= 0 ? '<b>#' + (rank + 1) + '</b> ' : '') + esc(p.text || '') + '</span>' +
      '<span class="play-score">' + esc(scoreText(p.score)) + '</span>' +
      '<span class="play-wpa" title="Change in the home team’s win probability">' + (signedW === null ? '' : '<span class="' + (signedW > 0 ? 'edge-pos' : signedW < 0 ? 'edge-neg' : '') + '">' + HW.signed(signedW, 1) + '</span>') + '</span></div>';
  }).join('') + '</div><div class="section-note">WPA: change in ' + esc(HW.teamAbbr(L, g.home)) + ' win probability, percentage points. The ' + Math.min(6, top.length) + ' biggest swings are numbered and marked on the win-probability chart.</div>';
}

// ── game centre ────────────────────────────────────────────────────────────

function renderGame(el, params) {
  const L = params.league, gid = params.id;
  el.innerHTML = '<div class="muted">Loading the game…</div>';
  return Promise.all([loadGame(L, params.season, gid), HW.load(HW.path('players.json', L, params.season))]).then(all => {
    const res = all[0];
    if (!el.isConnected) return;
    if (!res || !HW.ok(res.d)) {
      el.innerHTML = HW.card('Game', '', HW.notBuilt('This game', res && res.d) + '<a class="more-link" href="' + HW.href(L, 'games') + '">All games →</a>');
      return;
    }
    const g = res.d, S = res.s;
    if (S !== HW.state.season) HW.state.season = S;
    const st = HW.gameState(g);
    const H = String(g.home), A = String(g.away);
    document.title = HW.teamAbbr(L, A) + ' @ ' + HW.teamAbbr(L, H) + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
    const hasBox = Object.keys(g.box || {}).some(t => ((g.box[t] || {}).players || []).length);
    const pbp = !!(g.flow && g.flow.length);
    let html = headHTML(L, g, S) + pregameHTML(L, g) + awardsHTML(L, g);
    if (hasBox) {
      html += HW.card('Box score', 'advanced columns where play-by-play exists', '<div class="toggle-row" id="gm-box-tabs">' + HW.toggles([{ key: A, label: HW.teamName(L, A) }, { key: H, label: HW.teamName(L, H) }], A, 'data-bx') + '</div><div id="gm-box"></div>');
    }
    const ff = fourFactorsHTML(L, g);
    if (pbp || ff) {
      html += '<div class="grid-2">' + (pbp ? HW.card('Game flow', 'margin from ' + esc(HW.teamAbbr(L, H)) + '’s side, by game time', '<div id="gm-flow"></div>') : '') +
        (ff ? HW.card('Four factors', '', ff) : '') + '</div>';
    }
    if (g.wp) html += HW.card('Win probability', 'our live model against ESPN’s; numbered points are the biggest swings', '<div id="gm-wp"></div>');
    const shots = g.shots ? HW.charts.shotRows(g.shots) : [];
    if (shots.length) {
      html += HW.card('Shot charts', 'every field-goal attempt; xPTS = expected points from shot quality',
        '<div class="toggle-row" id="gm-shot-mode">' + HW.toggles([{ key: 'dots', label: 'Make / miss' }, { key: 'xpts', label: 'xPTS' }, { key: 'hex', label: 'Hex v league' }, { key: 'zone', label: 'Zones' }], 'dots', 'data-sm') + '</div>' +
        '<div class="grid-2" style="gap:0"><div><div class="day-head">' + HW.teamBar(L, A) + esc(HW.teamName(L, A)) + '</div><div id="gm-shot-a"></div></div>' +
        '<div><div class="day-head">' + HW.teamBar(L, H) + esc(HW.teamName(L, H)) + '</div><div id="gm-shot-h"></div></div></div>' +
        '<div class="toggle-row" id="gm-zone-tabs">' + HW.toggles([{ key: A, label: HW.teamAbbr(L, A) + ' zones' }, { key: H, label: HW.teamAbbr(L, H) + ' zones' }], A, 'data-zt') + '</div><div id="gm-zones"></div>' +
        shotQualityHTML(L, g));
    } else if (g.shot_quality) {
      html += HW.card('Shot quality', '', shotQualityHTML(L, g));
    }
    if (g.lineups) html += HW.card('Lineups', 'five-player units by minutes; net points per 100 possessions', '<div class="toggle-row" id="gm-lu-tabs">' + HW.toggles([{ key: A, label: HW.teamName(L, A) }, { key: H, label: HW.teamName(L, H) }], A, 'data-lu') + '</div><div id="gm-lu"></div>');
    if (g.rotation) html += HW.card('Rotations', 'who was on the floor when', '<div class="grid-2" style="gap:0"><div><div class="day-head">' + HW.teamBar(L, A) + esc(HW.teamName(L, A)) + '</div><div id="gm-rot-a"></div></div><div><div class="day-head">' + HW.teamBar(L, H) + esc(HW.teamName(L, H)) + '</div><div id="gm-rot-h"></div></div></div>');
    const pl = playsHTML(L, g);
    if (pl) html += HW.card('Key plays', 'the highest-leverage moments and every late score', pl);
    if (st !== 'pre' && !pbp && hasBox) html += '<div class="section-note">No play-by-play for this game: the flow, win probability, shots, lineups and rotations need it (most seasons before about 2017 are box-score only).</div>';
    if (st === 'pre' && !g.pregame) html += HW.card('Preview', '', HW.muted('The model line appears once the game is within the build window.'));
    html += '<div class="ph-nav" style="margin-top:10px"><a href="' + HW.href(L, 'games/' + HW.localDay(g.date), S) + '">Games that day</a>' +
      '<a href="' + HW.teamHref(L, A, S) + '">' + esc(HW.teamName(L, A)) + '</a><a href="' + HW.teamHref(L, H, S) + '">' + esc(HW.teamName(L, H)) + '</a></div>';
    el.innerHTML = html;

    if (hasBox) {
      const drawBox = t => { const n = document.getElementById('gm-box'); n.innerHTML = boxTable(L, g, t); HW.sortable(n); };
      drawBox(A);
      HW.wireToggles(document.getElementById('gm-box-tabs'), 'data-bx', drawBox);
    }
    if (pbp) HW.charts.flowChart('gm-flow', g.flow, { league: L, home: H, away: A });
    if (g.wp) HW.charts.wpChart('gm-wp', g.wp, { league: L, home: H, away: A, plays: g.plays || [] });
    if (shots.length) {
      HW.load(HW.path('shots_league.json', L, S)).then(grid => {
        if (!el.isConnected) return;
        const gridOk = HW.ok(grid) ? grid : null;
        const draw = mode => {
          ['a', 'h'].forEach(k => {
            const t = k === 'a' ? A : H;
            HW.charts.shotChart('gm-shot-' + k, shots, { league: L, team: t, mode: mode === 'xpts' ? 'dots' : mode, colour: mode === 'xpts' ? 'xpts' : 'made', grid: gridOk, height: 400, noScale: k === 'a' });
          });
        };
        draw('dots');
        HW.wireToggles(document.getElementById('gm-shot-mode'), 'data-sm', draw);
        const lz = HW.charts.leagueZones(gridOk);
        const drawZ = t => { document.getElementById('gm-zones').innerHTML = HW.charts.zoneTable(HW.charts.zoneStats(shots.filter(s => String(s.team) === String(t))), { league: lz }); };
        drawZ(A);
        HW.wireToggles(document.getElementById('gm-zone-tabs'), 'data-zt', drawZ);
      });
    }
    if (g.lineups) {
      const drawLu = t => { const n = document.getElementById('gm-lu'); n.innerHTML = lineupsHTML(L, g, t); HW.sortable(n); };
      drawLu(A);
      HW.wireToggles(document.getElementById('gm-lu-tabs'), 'data-lu', drawLu);
    }
    if (g.rotation) {
      const tMax = (g.flow && g.flow.length ? g.flow[g.flow.length - 1][0] : null);
      const nameOf = id => {
        let nm = null;
        Object.keys(g.box || {}).forEach(t => ((g.box[t] || {}).players || []).forEach(p => { if (String(p.id) === String(id)) nm = p.name; }));
        if (!nm) return HW.playerShort(L, id);
        const parts = nm.split(' ');
        return parts.length > 1 ? parts[0].charAt(0) + '. ' + parts.slice(1).join(' ') : nm;
      };
      const order = t => (((g.box || {})[t] || {}).players || []).slice().sort((a, b) => ((b.starter ? 1 : 0) - (a.starter ? 1 : 0)) || ((minutesOf(b.min) || 0) - (minutesOf(a.min) || 0))).map(p => String(p.id));
      HW.charts.rotationChart('gm-rot-a', g.rotation[A], { league: L, team: A, names: nameOf, order: order(A), tMax: tMax });
      HW.charts.rotationChart('gm-rot-h', g.rotation[H], { league: L, team: H, names: nameOf, order: order(H), tMax: tMax });
    }
    HW.setMeta(g.updated_at ? 'Game built ' + esc(HW.fmtStamp(g.updated_at)) : '');
  });
}

// ── games list ─────────────────────────────────────────────────────────────

/* Every game of the season we can find, as GAME_CARD-like objects keyed by id. */
function seasonGames(L, S) {
  const isCur = S === HW.currentSeason(L);
  return HW.loadAll([HW.path('schedule.json', L, S), HW.path('teams.json', L, S), HW.lpath('markets.json', L)]).then(arr => {
    const out = {};
    const put = g => { if (g && g.id) out[String(g.id)] = Object.assign({}, out[String(g.id)] || {}, g); };
    const sch = arr[0];
    if (HW.ok(sch)) (Array.isArray(sch) ? sch : (sch.games || [])).forEach(put);
    const tm = HW.ok(arr[1]) ? arr[1].teams || {} : {};
    Object.keys(tm).forEach(t => (tm[t].log || []).forEach(r => {
      if (!r.game || out[String(r.game)] && out[String(r.game)].status) return;
      const home = r.home ? t : String(r.opp), away = r.home ? String(r.opp) : t;
      put({ id: String(r.game), date: r.date, status: HW.isNum(r.pts) ? 'post' : 'pre', home: home, away: away,
        hs: r.home ? r.pts : r.opp_pts, as: r.home ? r.opp_pts : r.pts });
    }));
    if (isCur) {
      const info = HW.leagueInfo(L);
      (info.last_games || []).concat(info.today || [], info.next_games || []).forEach(put);
    }
    const mk = HW.ok(arr[2]) ? (arr[2].games || {}) : {};
    Object.keys(mk).forEach(id => { if (out[id] && !out[id].model && mk[id].model) out[id].model = mk[id].model; if (out[id] && !out[id].market && mk[id].market) out[id].market = mk[id].market; });
    return Object.keys(out).map(k => out[k]).filter(g => g.date);
  });
}

function renderGames(el, params) {
  const L = params.league, S = params.season;
  el.innerHTML = HW.pageHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S) + ' games', 'Scores, model lines and links to every game centre') + '<div id="gl-body"><div class="muted">Loading games…</div></div>';
  return seasonGames(L, S).then(list => {
    if (!el.isConnected) return;
    const body = document.getElementById('gl-body');
    if (!list.length) { body.innerHTML = HW.card('Games', '', HW.muted('No games found for this season yet.')); return; }
    const byDay = {};
    list.forEach(g => { const d = HW.localDay(g.date); (byDay[d] || (byDay[d] = [])).push(g); });
    const days = Object.keys(byDay).sort();
    const todayStr = HW.localDay(new Date().toISOString());
    let day = params.date && byDay[params.date] ? params.date : null;
    if (!day) day = days.find(d => d >= todayStr) || days[days.length - 1];
    if (params.date && !byDay[params.date]) day = days.find(d => d >= params.date) || days[days.length - 1];
    const draw = d => {
      const i = days.indexOf(d);
      const prev = days[i - 1], next = days[i + 1];
      const games = byDay[d].slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
      body.innerHTML = HW.card(HW.fmtDate(d), games.length + ' game' + (games.length === 1 ? '' : 's'),
        '<div class="ctl-row">' + (prev ? '<a class="tbtn" href="' + HW.href(L, 'games/' + prev, S) + '">← ' + esc(HW.fmtDate(prev, { year: false })) + '</a>' : '') +
        '<input type="date" id="gl-date" value="' + esc(d) + '" min="' + esc(days[0]) + '" max="' + esc(days[days.length - 1]) + '">' +
        (next ? '<a class="tbtn" href="' + HW.href(L, 'games/' + next, S) + '">' + esc(HW.fmtDate(next, { year: false })) + ' →</a>' : '') +
        '<select id="gl-month"></select></div>' +
        '<div class="gc-grid">' + games.map(g => HW.gameCard(g, { league: L, season: S })).join('') + '</div>');
      const months = {};
      days.forEach(x => { const m = x.slice(0, 7); if (!months[m]) months[m] = x; });
      const sel = document.getElementById('gl-month');
      sel.innerHTML = '<option value="">Jump to month…</option>' + Object.keys(months).map(m => '<option value="' + months[m] + '">' + esc(HW.fmtDate(m + '-15', { weekday: false }).replace(/^\d+ /, '')) + '</option>').join('');
      sel.addEventListener('change', () => { if (sel.value) HW.go(HW.href(L, 'games/' + sel.value, S)); });
      document.getElementById('gl-date').addEventListener('change', ev => { const v = ev.target.value; if (v) HW.go(HW.href(L, 'games/' + v, S)); });
    };
    draw(day);
  });
}

HW.route('game', renderGame);
HW.route('games', renderGames);
HW.gameCentre = { loadGame: loadGame, seasonGames: seasonGames, boxTable: boxTable, minutesOf: minutesOf };
})(window.HW);
