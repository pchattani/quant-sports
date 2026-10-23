/* The Quant Rink — Games (#/games[/<date>]) and the game centre (#/game/<id>), on the kit (Design System 2.0).
 *
 * Games: a strip of game days, the day's games as v2 game cards (our chance first, the market a quiet tick), our
 * chance for every home side, and how the model did once games are final.
 * Game centre (the v2 reference game page): scoreboard hero with our win-chance bar, stat tiles (our pre-game and
 * live chance, expected goals, the biggest swing), then Summary (win probability, expected-goals race, shot map,
 * linescore, three stars, tale of the tape, our pre-game forecast with the market as a reference, the exact-score
 * grid and the goals distribution, the box score) and Detail (the full pre-redesign game centre), ?view=detail.
 *
 * Reads <S>/schedule.json, index.json and <S>/games/<id>.json (PAYLOADS.md). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const dayOf = g => g.date || RK.localDay(g.start) || '';

function pickDay(days, S) {
  const today = RK.todayISO();
  if (S === RK.currentSeason()) {
    if (days.indexOf(today) >= 0) return today;
    const idx = RK.index() || {};
    const t0 = (idx.today || [])[0];
    if (t0 && days.indexOf(dayOf(t0)) >= 0) return dayOf(t0);
    const nxt = days.find(d => d >= today);
    if (nxt) return nxt;
  }
  return days[days.length - 1];
}

function strip(days, day, counts) {
  if (!days.length) return '';
  const i = Math.max(0, days.indexOf(day));
  const lo = Math.max(0, i - 7), hi = Math.min(days.length, lo + 15);
  const W = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  return '<nav class="rk-strip" aria-label="Game days">' + days.slice(lo, hi).map(d => {
    const dt = RK.parseDate(d);
    return '<a href="' + RK.gamesHref(d) + '"' + (d === day ? ' aria-current="page"' : '') + '><span>' + esc(dt ? W[dt.getUTCDay()] : '') + '</span><b>' + esc(String(dt ? dt.getUTCDate() : '')) + '</b>' +
      '<span>' + esc(RK.fmtDate(d, { year: false, weekday: false }).replace(/^\d+\s*/, '')) + ' · <span class="n">' + (counts[d] || 0) + '</span></span></a>';
  }).join('') + '</nav>';
}

function review(games) {
  const fin = games.filter(g => RK.isFinal(g) && isNum(g.hs) && isNum(g.as));
  if (!fin.length || !RK.lineNow || !RK.puckCover) return '';
  let su = 0, suN = 0, pl = 0, plN = 0, ou = 0, ouN = 0, brier = 0, bN = 0;
  fin.forEach(g => {
    const m = g.model || {};
    const ln = RK.lineNow(g) || {};
    const margin = Number(g.hs) - Number(g.as);
    if (isNum(m.p_home) && Math.abs(m.p_home - 0.5) > 1e-9 && margin !== 0) { suN++; if ((m.p_home > 0.5) === (margin > 0)) su++; brier += Math.pow(Number(m.p_home) - (margin > 0 ? 1 : 0), 2); bN++; }
    const pc = RK.puckCover(g, m, ln);
    if (pc && isNum(pc.p) && Math.abs(pc.p - 0.5) > 1e-9) { const fm = String(pc.team) === String(g.home) ? margin : -margin; plN++; if ((pc.p > 0.5) === (fm + pc.line > 0)) pl++; }
    if (isNum(m.total) && isNum(ln.total) && Math.abs(m.total - ln.total) > 0.05) { const goals = Number(g.hs) + Number(g.as); if (goals !== Number(ln.total)) { ouN++; if ((m.total > ln.total) === (goals > ln.total)) ou++; } }
  });
  const t = (k, n, label) => QK.kpi({ label: label, value: n ? k + '–' + (n - k) : '—', sub: n ? QK.fmt.pct(k / n) + ' right' : 'no games yet' });
  return '<section class="qk-section"><div class="qk-section-head"><div><h2>How the model did</h2><div class="qk-sub">' + fin.length + ' final' + (fin.length === 1 ? '' : 's') + '. One day says little: the long run is on the <a class="qk-link" href="#/model?tab=calibration">calibration</a> page.</div></div></div>' +
    '<div class="qk-kpis">' + t(su, suN, 'Our favourite won') + t(pl, plN, 'Two-goal margins called') + t(ou, ouN, 'Goal totals called') +
    QK.kpi({ label: 'Brier score', value: bN ? (brier / bN).toFixed(3) : '—', sub: '0.250 = a coin flip', tip: 'Mean squared error of the win probability; lower is better' }) + '</div></section>';
}

function gamesPage(el, params) {
  const S = params.date ? (RK.seasonOfDate(params.date) || params.season) : params.season;
  el.innerHTML = U.secHead('fixtures', 'Games', 'Every game with our win chance; tap a game for the game centre.') + QK.skeleton('card', 6);
  return RK.loadYear('schedule.json', S).then(sch => {
    if (!U.alive(el)) return;
    const idx = RK.index() || {};
    let games = RK.ok(sch) ? (sch.games || []).filter(Boolean) : [];
    const fresh = {};
    ['today', 'live', 'recent', 'upcoming'].forEach(k => (idx[k] || []).forEach(c => { if (c && c.game_id) fresh[c.game_id] = c; }));
    if (S === RK.currentSeason()) {
      games = games.map(g => fresh[g.game_id] || g);
      Object.keys(fresh).forEach(id => { if (!games.some(g => g.game_id === id)) games.push(fresh[id]); });
    }
    const counts = {};
    games.forEach(g => { const d = dayOf(g); if (d) counts[d] = (counts[d] || 0) + 1; });
    const days = Object.keys(counts).sort();
    const day = params.date || (days.length ? pickDay(days, S) : RK.todayISO());
    const list = games.filter(g => dayOf(g) === day).sort((a, b) => String(a.start).localeCompare(String(b.start)) || String(a.game_id).localeCompare(String(b.game_id)));
    const live = list.filter(g => U.status(g) === 'live');
    const di = days.indexOf(day);
    const prev = di > 0 ? days[di - 1] : days.filter(d => d < day).pop();
    const next = di >= 0 && di + 1 < days.length ? days[di + 1] : days.find(d => d > day);
    document.title = 'Games · ' + RK.fmtDate(day, { year: false }) + ' · ' + RK.SITE;
    const pre = list.filter(g => U.status(g) === 'pre' && g.model && isNum(g.model.p_home) && g.market && isNum(g.market.p_home));
    let h = U.secHead('fixtures', RK.fmtDate(day), [RK.seasonLabel(S), list.length + ' game' + (list.length === 1 ? '' : 's'), live.length ? live.length + ' live' : ''].filter(Boolean).join(' · '), null, null, 'NHL · Games') +
      '<div class="rk-flex" style="justify-content:space-between;margin-bottom:var(--sp-4)">' + strip(days, day, counts) +
      '<div class="rk-flex">' + (prev ? '<a class="qk-btn" href="' + RK.gamesHref(prev) + '" aria-label="Previous game day">←</a>' : '') + (next ? '<a class="qk-btn" href="' + RK.gamesHref(next) + '" aria-label="Next game day">→</a>' : '') +
      '<input class="qk-input" type="date" id="gd-jump" value="' + esc(day) + '" aria-label="Go to a date"></div></div>';
    if (!list.length) h += U.card2('No games', '', QK.empty('No games on ' + RK.fmtDate(day), next ? 'Next game day: ' + RK.fmtDate(next, { year: false }) : (RK.ok(sch) ? '' : 'The schedule is not built yet.')));
    else {
      h += '<div class="rk-games rk-gc">' + list.map(g => U.gc(g, { league: QK.fmt.time(g.start) || 'NHL' })).join('') + '</div>';
      if (pre.length) h += '<section class="qk-section">' + U.card2('Our chance for every home side', 'Teal: our win chance (overtime and shootout included). Grey ring: the market, for reference', U.chart('gd-mvm', Math.max(200, 34 * pre.length + 50), 'Our home win chance, with the market for reference')) + '</section>';
      h += review(list);
    }
    el.innerHTML = h;
    if (pre.length) QKC.dumbbell('#gd-mvm', { rows: pre.map(g => ({ label: RK.teamAbbr(g.away) + ' @ ' + RK.teamAbbr(g.home), a: g.model.p_home, b: g.market.p_home, href: RK.gameHref(g.game_id), sub: QK.fmt.time(g.start) })), labelWidth: 90, valName: 'Home win chance' });
    const jump = el.querySelector('#gd-jump');
    if (jump) jump.addEventListener('change', () => { if (/^\d{4}-\d\d-\d\d$/.test(jump.value)) RK.go(RK.gamesHref(jump.value)); });
    const cur = el.querySelector('.rk-strip [aria-current]');
    if (cur && cur.scrollIntoView) { try { cur.parentNode.scrollLeft = cur.offsetLeft - cur.parentNode.clientWidth / 2 + cur.clientWidth / 2; } catch (e) { /* old browsers */ } }
    RK.sortable(el);
    if (live.length) RK.liveRefresh([RK.ypath('schedule.json', S)], 60000);
  });
}

/* ── game centre ─────────────────────────────────────────────────────────── */
function cardOf(d, id) {
  const c = Object.assign({}, (d && d.card) || {});
  const idx = RK.index() || {};
  ['live', 'today', 'recent', 'upcoming'].forEach(k => (idx[k] || []).forEach(x => { if (x && String(x.game_id) === String(id)) Object.assign(c, x); }));
  return c;
}

/* v3 (Matchday) hero: QK.previewCard — away "at" home with records, the score bug when live, our chance for the
   favourite as a big teal number, a plain-English note (overtime and goals in all), the market as a quiet reference
   line before the game (game detail is one of the two places it may appear), and how the clubs match up so far. */
const TWO_WORD = /(Maple Leafs|Red Wings|Golden Knights|Blue Jackets)$/;
U.nick = abbr => { const n = RK.teamName(abbr) || abbr; const m = TWO_WORD.exec(n); return m ? m[1] : String(n).split(' ').slice(-1)[0]; };
function hero(c, d, g, season) {
  const st = g.status, pre = st === 'pre';
  const m = ((d && d.pregame) || {}).model || c.model || {};
  const mk = ((d && d.pregame) || {}).market || c.market || {};
  const [ca, ch] = U.pair(c.away, c.home);
  const rows = {}; (((season && season.standings) || {}).rows || []).forEach(r => { rows[r.team] = r; });
  const rec = t => { const r = rows[t]; return r && isNum(r.w) ? r.w + '–' + r.l + '–' + (r.otl || 0) + (isNum(r.pts) ? ' · ' + r.pts + ' pts' : '') : ''; };
  const G = Object.assign({}, g, { home: Object.assign({}, g.home, { colour: ch, record: rec(c.home) }), away: Object.assign({}, g.away, { colour: ca, record: rec(c.away) }) });
  /* the pre-game call stays the pre-game call once the game is over */
  if (st === 'final' && isNum(m.p_home)) G.p_home = Number(m.p_home);
  const R = (season && season.ratings) || {};
  const ua = (R[c.away] || {}).units || {}, uh = (R[c.home] || {}).units || {};
  const fx = [];
  const add = (label, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: label, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
  add('Goals for per game', ua.gf_g, uh.gf_g, v => U.f(v, 1));
  add('Goals against per game', ua.ga_g, uh.ga_g, v => U.f(v, 1), true);
  add('Chance share, 5-on-5', ua.xgf_pct5, uh.xgf_pct5, v => U.pct(v, 1));
  add('Expected goals for per game', ua.xgf_g, uh.xgf_g, v => U.f(v, 2));
  add('Team rating', (rows[c.away] || {}).rating, (rows[c.home] || {}).rating, v => U.signed(v, 2));
  const extra = [];
  if (pre && isNum(m.p_ot)) extra.push('About ' + (Math.round(1 / m.p_ot) > 1 ? '1 in ' + Math.round(1 / m.p_ot) : 'half') + ' (' + U.pct(m.p_ot) + ') go to overtime');
  if (pre && isNum(m.total)) extra.push('we expect about ' + Math.round(m.total) + ' goals in all');
  const kick = 'NHL' + (d && d.venue ? ' · ' + d.venue : '') + (RK.isPlayoffGame(c) && G.league !== 'NHL' ? ' · ' + G.league : '');
  const src = RK.srcLineOnly && RK.srcLineOnly(mk.sources) ? 'no-vig line' : (RK.srcLabel(mk.sources) || 'de-vigged');
  return '<div class="rk-preview">' + QK.previewCard(G, { kicker: kick, nick: t => U.nick(t.abbr), colors: [ca, ch], factors: fx,
    noteExtra: extra.length ? esc(extra.join(', and ') + '.') : '', market: pre && isNum(mk.p_home) ? { p: Number(mk.p_home), label: 'Market (' + src + ')' } : null }) + '</div>';
}

function kpiStrip(c, d, g) {
  const m = ((d && d.pregame) || {}).model || c.model || {};
  const out = [];
  const fav = isNum(m.p_home) ? (m.p_home >= 0.5 ? c.home : c.away) : null;
  if (fav) out.push({ label: g.status === 'pre' ? 'Our win chance' : 'Our pre-game call', value: RK.teamAbbr(fav) + ' ' + U.pct(Math.max(m.p_home, 1 - m.p_home)), signal: true, sub: isNum(m.p_ot) ? 'overtime ' + U.pct(m.p_ot) + ' · ' + U.f(m.total, 1) + ' goals expected' : '', tip: 'Our pre-game win chance, overtime and shootout included' });
  if (g.status === 'live' && isNum(c.wp_home)) { const f = c.wp_home >= 0.5 ? c.home : c.away; out.push({ label: 'Live win chance', value: RK.teamAbbr(f) + ' ' + U.pct(Math.max(c.wp_home, 1 - c.wp_home)), sub: 'our live model, every event', signal: true }); }
  const xg = c.xg || {};
  if (isNum(xg.home) && isNum(xg.away)) out.push({ label: 'Expected goals', value: U.f(xg.away, 1) + '–' + U.f(xg.home, 1), sub: RK.teamAbbr(c.away) + ' – ' + RK.teamAbbr(c.home) + ', empty net out', tip: 'The chance quality of every shot, added up' });
  if (isNum(m.home_goals) && isNum(m.away_goals) && g.status === 'pre') out.push({ label: 'Projected score', value: U.f(m.away_goals, 1) + '–' + U.f(m.home_goals, 1), sub: RK.teamAbbr(c.away) + ' – ' + RK.teamAbbr(c.home) + ', average of our simulations' });
  if (d && d.wp && isNum(d.wp.now) && g.status === 'final') out.push({ label: 'Biggest swing', value: swing(d), text: true, sub: 'largest win-chance move in one event' });
  return out.length ? '<div class="rk-kpis">' + QK.stats(out) + '</div>' : '';
}
function swing(d) {
  const s = (d.wp && d.wp.series) || [];
  let best = 0, at = null;
  for (let i = 1; i < s.length; i++) { const v = Math.abs(s[i][1] - s[i - 1][1]); if (v > best) { best = v; at = s[i][0]; } }
  return at === null ? '—' : Math.round(best * 100) + ' pts at ' + RK.secText(at);
}

function shotsOf(d) {
  const sh = d && d.shots;
  if (!sh || !Array.isArray(sh.rows)) return [];
  const ci = {}; (sh.cols || []).forEach((c, i) => { ci[c] = i; });
  return sh.rows.map(r => ({ period: r[ci.period], sec: r[ci.sec], team: r[ci.team], player: r[ci.player], x: r[ci.x], y: r[ci.y], type: r[ci.type], shot_type: r[ci.shot_type], xg: r[ci.xg], goal: r[ci.goal], strength: r[ci.strength] }));
}

function shotMap(node, d, c) {
  const rows = shotsOf(d).filter(s => s.type !== 'block' && isNum(s.x) && isNum(s.y));
  if (!rows.length) { node.innerHTML = QK.empty('No shot locations', 'The shot map fills in once the game has play-by-play.'); return; }
  const names = (d.shots && d.shots.players) || {};
  node.classList.add('qk-surface', 'sq');
  node.style.setProperty('--ar', '200 / 85');
  const [ca, ch] = U.pair(c.away, c.home);
  QKC.mount(node, T => {
    node.style.backgroundImage = 'url("data:image/svg+xml,' + encodeURIComponent(QKC.surfaceSVG('rink', T)) + '")';
    const ser = [];
    [[c.away, ca, -1], [c.home, ch, 1]].forEach(t => {
      [0, 1].forEach(goal => {
        const pts = rows.filter(s => String(s.team) === String(t[0]) && !!s.goal === !!goal).map(s => {
          const flip = (s.x < 0) === (t[2] > 0);
          const x = flip ? -s.x : s.x, y = flip ? -s.y : s.y;
          return { value: [x, y, s.xg], name: (names[s.player] || RK.playerName(s.player)) + ' · ' + RK.secText(s.sec) + ' · ' + (s.goal ? 'GOAL' : RK.shotTypeLabel(s.type)) + (s.strength && s.strength !== '5v5' ? ' (' + s.strength + ')' : ''),
            href: s.player ? RK.playerHref(s.player) : undefined,
            itemStyle: goal ? { color: t[1], borderColor: T.ink1, borderWidth: 1.5 } : { color: QKC.hexA(t[1], 0.35), borderColor: t[1], borderWidth: 1 } };
        });
        ser.push({ type: 'scatter', name: RK.teamAbbr(t[0]) + (goal ? ' goals' : ' shots'), data: pts, z: goal ? 3 : 2,
          symbolSize: v => Math.max(goal ? 9 : 5, Math.sqrt(isNum(v[2]) ? v[2] : 0.05) * 30) });
      });
    });
    return {
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'value', min: -100, max: 100, show: false }, yAxis: { type: 'value', min: -42.5, max: 42.5, show: false },
      legend: { show: false },
      tooltip: QKC.tooltip(T, { formatter: p => '<b>' + esc(p.data.name) + '</b>' + (isNum(p.value[2]) ? QKC.tipRow(p.color, 'xG', U.f(p.value[2], 2)) : '') }),
      series: ser
    };
  }, { label: 'Shot map: ' + RK.teamName(c.away) + ' attack left, ' + RK.teamName(c.home) + ' attack right' });
  node.insertAdjacentHTML('beforebegin', '<div class="rk-legend"><span><i style="--k:' + ca + '"></i>' + esc(RK.teamAbbr(c.away)) + ' goal</span><span><i class="o" style="--k:' + ca + '"></i>' + esc(RK.teamAbbr(c.away)) + ' shot (attacking left)</span>' +
    '<span><i style="--k:' + ch + '"></i>' + esc(RK.teamAbbr(c.home)) + ' goal</span><span><i class="o" style="--k:' + ch + '"></i>' + esc(RK.teamAbbr(c.home)) + ' shot (attacking right)</span><span>Dot size: expected goals</span></div>');
}

function linescore(d, c) {
  const ls = (d && d.linescore) || [];
  if (!ls.length) return '';
  const pl = RK.isPlayoffGame(c);
  const th = ls.map(r => '<th class="num">' + esc(RK.periodLabel(r.period, { playoff: pl })) + '</th>').join('');
  const row = (abbr, side) => '<tr><td class="sticky-col">' + U.teamEnt(abbr, { abbr: true }) + '</td>' + ls.map(r => '<td class="num">' + (isNum(r['g_' + side]) ? r['g_' + side] : '–') +
    '<span class="qk-muted" style="font-size:.78em"> ' + (isNum(r['s_' + side]) ? r['s_' + side] + ' sog' : '') + '</span></td>').join('') +
    '<td class="num"><b>' + (side === 'home' ? c.hs : c.as) + '</b></td><td class="num">' + U.f(ls.reduce((s, r) => s + (isNum(r['xg_' + side]) ? r['xg_' + side] : 0), 0), 2) + '</td></tr>';
  return '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th class="sticky-col">Club</th>' + th + '<th class="num">T</th><th class="num">xG</th></tr></thead><tbody>' + row(c.away, 'away') + row(c.home, 'home') + '</tbody></table></div>';
}

function boxTables(node, d, c) {
  const b = d && d.box;
  if (!b || !b.skaters) { node.innerHTML = QK.empty('No box score yet'); return; }
  const sc = b.skater_cols || [], gc = b.goalie_cols || [];
  const obj = (cols, r) => { const o = {}; cols.forEach((k, i) => { o[k] = r[i]; }); return o; };
  const teams = [c.away, c.home];
  node.innerHTML = '<div class="qk-seg" id="gm-box-team" role="group" aria-label="Club">' + teams.map((t, i) => '<button type="button" aria-pressed="' + (i === 1) + '" data-value="' + esc(t) + '">' + esc(RK.teamName(t)) + '</button>').join('') + '</div>' +
    '<div id="gm-box-sk" style="margin-top:12px"></div><div id="gm-box-g" style="margin-top:12px"></div>';
  const draw = t => {
    const sk = ((b.skaters || {})[t] || []).map(r => obj(sc, r));
    QK.table(node.querySelector('#gm-box-sk'), { dense: true, sort: { key: 'gs', dir: 'desc' }, columns: [
      { key: 'name', label: 'Skater', sticky: true, fmt: (v, r) => U.playerEnt(r.id, v) },
      { key: 'pos', label: 'Pos', fmt: v => U.pos(v) }, { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true }, { key: 'p', label: 'P', num: true },
      { key: 'sog', label: 'SOG', num: true }, { key: 'ixg', label: 'ixG', num: true, fmt: v => U.f(v, 2), tip: 'Individual expected goals' },
      { key: 'hits', label: 'Hits', num: true }, { key: 'blocks', label: 'Blk', num: true }, { key: 'toi', label: 'TOI', num: true, fmt: v => RK.fmtTOI(v, { minutes: true }) },
      { key: 'xgf_pct', label: 'xGF%', num: true, fmt: v => U.pct(v), tip: 'Share of 5v5 expected goals with the player on the ice' },
      { key: 'gs', label: 'Game score', num: true, fmt: v => U.f(v, 2) }], rows: sk });
    const gl = ((b.goalies || {})[t] || []).map(r => obj(gc, r));
    QK.table(node.querySelector('#gm-box-g'), { dense: true, columns: [
      { key: 'name', label: 'Goalie', sticky: true, fmt: (v, r) => U.playerEnt(r.id, v) }, { key: 'sa', label: 'SA', num: true }, { key: 'ga', label: 'GA', num: true },
      { key: 'sv_pct', label: 'SV%', num: true, fmt: v => RK.fmtVal(v, '3') }, { key: 'xga', label: 'xGA', num: true, fmt: v => U.f(v, 2) },
      { key: 'gsax', label: 'GSAx', num: true, fmt: v => '<span class="' + U.cls(v) + '">' + U.signed(v, 2) + '</span>', tip: 'Goals saved above expected' }, { key: 'toi', label: 'TOI', num: true, fmt: v => U.f(v, 1) }], rows: gl });
  };
  draw(c.home);
  QK.seg(node.querySelector('#gm-box-team'), draw);
}

function pregameCard(d, c) {
  const pg = (d && d.pregame) || {};
  const m = pg.model || c.model || {};
  const mk = pg.market || c.market || {};
  const ln = pg.line || c.line || {};
  if (!isNum(m.p_home)) return '';
  const A = RK.teamAbbr(c.away), H = RK.teamAbbr(c.home);
  const tl = isNum(m.total_line) ? Number(m.total_line) : (isNum(ln.total) ? Number(ln.total) : null);
  const rows = [
    ['Win (overtime included)', H + ' ' + U.pct(m.p_home) + ' · ' + A + ' ' + U.pct(1 - m.p_home), isNum(mk.p_home) ? H + ' ' + U.pct(mk.p_home) : '—'],
    ['Decided in regulation', isNum(m.p_reg_home) ? H + ' ' + U.pct(m.p_reg_home) + ' · ' + A + ' ' + U.pct(m.p_reg_away) + ' · overtime ' + U.pct(m.p_ot) : '—', ''],
    ['Wins by two or more', isNum(m.puck_line_home) ? H + ' ' + U.pct(m.puck_line_home) : '—', ''],
    ['Total goals', isNum(m.total) ? U.f(m.total, 2) + ' expected' + (isNum(m.p_over) && isNum(tl) ? ' · ' + Math.ceil(tl) + ' or more: ' + U.pct(m.p_over) : '') : '—', ''],
    ['Projected score', isNum(m.home_goals) ? A + ' ' + U.f(m.away_goals, 1) + ' – ' + U.f(m.home_goals, 1) + ' ' + H : '—', '']
  ];
  return '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Question</th><th>Our forecast</th><th><span data-tip="The prediction-market or no-vig line probability, shown as a reference">Market</span></th></tr></thead><tbody>' +
    rows.map(r => '<tr><td>' + esc(r[0]) + '</td><td class="num" style="text-align:left;color:var(--ink-1);font-weight:600">' + esc(r[1]) + '</td><td class="num qk-muted" style="text-align:left">' + esc(r[2]) + '</td></tr>').join('') + '</tbody></table></div>';
}

/* Tale of the tape: the two clubs' season profile from the ratings (season.json ratings[team].units). */
function tape(season, c) {
  const R = (season && season.ratings) || {};
  const a = (R[c.away] || {}).units || {}, h = (R[c.home] || {}).units || {};
  const st = {}; (((season && season.standings) || {}).rows || []).forEach(r => { st[r.team] = r; });
  const rows = [
    { label: 'Team rating (goals a game)', a: (st[c.away] || {}).rating, b: (st[c.home] || {}).rating, fmt: v => U.signed(v, 2), tip: 'Our rating: expected goal difference a game against an average club' },
    { label: '5v5 share of expected goals', a: a.xgf_pct5, b: h.xgf_pct5, fmt: v => U.pct(v, 1) },
    { label: 'Expected goals for / game', a: a.xgf_g, b: h.xgf_g, fmt: v => U.f(v, 2) },
    { label: 'Expected goals against / game', a: a.xga_g, b: h.xga_g, fmt: v => U.f(v, 2), better: 'low' },
    { label: 'Goals for / game', a: a.gf_g, b: h.gf_g, fmt: v => U.f(v, 2) },
    { label: 'Goals against / game', a: a.ga_g, b: h.ga_g, fmt: v => U.f(v, 2), better: 'low' }
  ];
  if (!rows.some(r => isNum(r.a) && isNum(r.b))) return '';
  const [ca, ch] = U.pair(c.away, c.home);
  const A = U.team(c.away), H = U.team(c.home); A.colour = ca; H.colour = ch;
  return QK.matchupBar({ left: A, right: H, rows: rows, colors: [ca, ch] });
}

/* Starting goalies before the game: ESPN's probable starters (projected, then confirmed) with the time each was
   first seen, and what they do to the model against each team's usual starter (pregame.model.goalie_effect). */
function goaliesCard(d, c) {
  const gl = c.goalies || ((d && d.card) || {}).goalies || {};
  const obj = x => (x && typeof x === 'object' ? x : x ? { pid: String(x) } : null);
  const h = obj(gl.home), a = obj(gl.away);
  if (!h && !a) return '';
  const m = (((d && d.pregame) || {}).model) || c.model || {};
  const fx = m.goalie_effect || null;
  const usual = (fx && fx.usual) || {};
  const row = (side, x) => {
    const team = side === 'home' ? c.home : c.away;
    if (!x) return '<tr><td>' + U.teamEnt(team, { abbr: true }) + '</td><td colspan="2" class="rk-note">Not listed yet</td></tr>';
    const st = String(x.status || '').toLowerCase();
    const badge = st ? '<span class="qk-badge' + (st === 'confirmed' ? ' accent' : '') + '">' + esc(st) + '</span>' : '';
    const alt = fx && usual[side] && x.pid && String(usual[side]) !== String(x.pid) ? 'usual starter ' + RK.playerName(String(usual[side])) : '';
    return '<tr><td>' + U.teamEnt(team, { abbr: true }) + '</td><td>' + (x.pid ? U.playerEnt(x.pid, x.name, null) : esc(x.name || '—')) + ' ' + badge + (alt ? '<div class="rk-note">' + esc(alt) + '</div>' : '') + '</td>' +
      '<td class="num" style="text-align:left">' + (x.at ? (st === 'confirmed' ? 'confirmed ' : 'listed ') + esc(RK.fmtStamp(x.at)) : '—') + '</td></tr>';
  };
  let note = '';
  if (fx && isNum(fx.p_home_usual) && isNum(m.p_home)) {
    const H = RK.teamAbbr(c.home);
    note = 'With these starters the model gives ' + esc(H) + ' ' + U.pct(m.p_home) + '; with each team\'s usual starter ' + U.pct(fx.p_home_usual) +
      ' (' + U.signed(100 * (m.p_home - fx.p_home_usual), 1) + ' pts)' + (isNum(fx.total_usual) && isNum(m.total) ? '. Total ' + U.f(m.total, 2) + ' v ' + U.f(fx.total_usual, 2) + ' goals.' : '.');
  } else if (h && h.status || a && a.status) {
    note = 'The model uses the listed starters; a team with none listed is forecast with its usual starter.';
  }
  const tbl = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Team</th><th>Starter</th><th>Since</th></tr></thead><tbody>' +
    row('away', a) + row('home', h) + '</tbody></table></div>';
  return U.card2('Starting goalies', 'ESPN\'s probable starters, read every hour (every 15 minutes near game time)', tbl + (note ? '<div class="rk-note" style="padding:var(--sp-3) var(--sp-4)">' + note + '</div>' : ''), { flush: true });
}

function summary(node, d, c, g, season) {
  const fin = g.status === 'final', live = g.status === 'live', pre = g.status === 'pre';
  const pl = RK.isPlayoffGame(c);
  const [ca, ch] = U.pair(c.away, c.home);
  const wp = (d && d.wp && d.wp.series) || [];
  const race = d && d.xg_race && Array.isArray(d.xg_race.rows) ? d.xg_race.rows : [];
  const sd = (((d || {}).pregame || {}).model || {}).score_dist;
  const td = (((d || {}).pregame || {}).model || {}).total_dist;
  const aw = (d && d.awards) || {};
  let h = '';
  if (!pre && (wp.length > 1 || race.length > 1)) {
    h += '<div class="qk-grid">' +
      (wp.length > 1 ? '<div class="qk-span-6">' + U.card2('Win chance through the game', 'Our live model after every event; dots mark goals', U.chart('gm-wp', 300, 'Win chance through the game')) + '</div>' : '') +
      (race.length > 1 ? '<div class="qk-span-6">' + U.card2('Expected-goals race', 'Cumulative xG, all situations; dots mark goals', U.chart('gm-xg', 300, 'Expected goals race')) + '</div>' : '') + '</div>';
  }
  if (!pre) h += '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-8">' + U.card2('Shot map', 'Unblocked attempts; filled dots are goals', '<div id="gm-map" class="qk-chart"></div>') + '</div>' +
    '<div class="qk-span-4"><div class="rk-stack">' + (linescore(d, c) ? U.card2('By period', 'Goals, shots on goal and expected goals', linescore(d, c), { flush: true }) : '') +
    ((aw.stars || []).length ? U.card2('Three stars', 'By game score', '<ul class="rk-list">' + aw.stars.map((s, i) => '<li><span class="n">' + '★'.repeat(i + 1).slice(0, 3) + '</span>' + U.playerEnt(s.id, s.name, s.team, s.line) + '<span class="v">' + U.f(s.score, 2) + '</span></li>').join('') + '</ul>', { flush: true }) : '') +
    (aw.best_line ? U.card2('Best line', esc(RK.teamAbbr(aw.best_line.team)) + ' · ' + U.f(aw.best_line.toi, 1) + ' min together at 5v5', '<div class="qk-sub">' + esc((aw.best_line.names || []).join(' – ')) + '</div><div class="rk-note">xG difference ' + U.signed(aw.best_line.xg_diff, 2) + '</div>') : '') +
    '</div></div></div>';
  const tp = tape(season, c);
  /* v3: the forecast table sits beside the hero (gamePage); here, the tale of the tape and the score grid */
  h += '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-' + (sd && sd.p ? 7 : 12) + '"><div class="rk-stack">' +
    (tp ? U.card2('Tale of the tape', 'Season so far: the stronger side of each bar is solid', tp) : '') + '</div></div>' +
    (sd && sd.p ? '<div class="qk-span-5">' + U.card2('Every final score', 'Our chance of each score (rows ' + esc(RK.teamAbbr(c.home)) + ', columns ' + esc(RK.teamAbbr(c.away)) + ')', U.chart('gm-sd', 300, 'Chance of each final score')) + '</div>' : '') + '</div>';
  if (pre) { const gk = goaliesCard(d, c); if (gk) h += '<div style="margin-top:var(--sp-4)">' + gk + '</div>'; }
  if (pre && Array.isArray(td) && td.length) h += '<div style="margin-top:var(--sp-4)">' + U.card2('Total goals', 'Our chance of each total, both teams combined. Totals include the overtime or shootout winner, which is why odd totals come up more often than even ones.', U.chart('gm-td', 240, 'Total goals distribution')) + '</div>';
  if (!pre) h += '<div style="margin-top:var(--sp-4)">' + U.card2('Box score', 'Every skater and goalie; sort any column', '<div id="gm-box"></div>') + '</div>';
  node.innerHTML = h;

  const goals = shotsOf(d).filter(s => s.goal);
  if (wp.length > 1) {
    const t = wp.map(p => Math.round(p[0] / 6) / 10);
    QKC.winProb('#gm-wp', { t: t, p: wp.map(p => p[1]), home: { name: RK.teamName(c.home), abbr: RK.teamAbbr(c.home), colour: ch }, away: { name: RK.teamName(c.away), abbr: RK.teamAbbr(c.away), colour: ca },
      events: goals.map(s => ({ t: Math.round(s.sec / 6) / 10, label: RK.teamAbbr(s.team) })), periods: [20, 40, 60], tFmt: v => Math.round(v) + "'" });
  }
  if (race.length > 1) {
    const ci = {}; (d.xg_race.cols || []).forEach((k, i) => { ci[k] = i; });
    const x = race.map(r => Math.round(r[ci.sec] / 6) / 10);
    QKC.mount('#gm-xg', T => {
      const mk = (side, col) => ({
        type: 'line', name: RK.teamAbbr(side === 'home' ? c.home : c.away), step: 'end', showSymbol: false, data: race.map((r, i) => [x[i], r[ci[side]]]),
        lineStyle: { width: 2.2, color: col }, itemStyle: { color: col }, areaStyle: { color: QKC.hexA(col, 0.12) },
        markPoint: { symbol: 'circle', symbolSize: 9, itemStyle: { color: col, borderColor: T.s1, borderWidth: 2 }, label: { show: false },
          data: race.map((r, i) => (r[ci.goal] && String(r[ci.goal]) === String(side === 'home' ? c.home : c.away) ? { coord: [x[i], r[ci[side]]] } : null)).filter(Boolean) },
        endLabel: { show: true, formatter: p => RK.teamAbbr(side === 'home' ? c.home : c.away) + ' ' + U.f(p.value[1], 2), color: T.ink2, fontFamily: T.fontNum, fontSize: 11 }
      });
      const xa = QKC.axis(T, { type: 'value', min: 0, max: Math.max(60, Math.ceil(x[x.length - 1] / 5) * 5), interval: 20, fmt: v => v + "'", split: false, line: true });
      const ya = QKC.axis(T, { fmt: v => v.toFixed(1) });
      const gB = 8 + QKC.nameAxis(xa, 'Game time (minutes)', 'bottom'), gT = 14 + QKC.nameAxis(ya, 'Cumulative expected goals', 'side');
      return {
        grid: { left: 8, right: 70, top: gT, bottom: gB, containLabel: true },
        xAxis: xa,
        yAxis: ya,
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => '<div style="color:' + T.ink3 + '">' + esc(U.f(ps[0].value[0], 1)) + "'</div>" + ps.map(p => QKC.tipRow(p.color, p.seriesName, U.f(p.value[1], 2))).join('') }),
        series: [mk('away', ca), mk('home', ch)]
      };
    }, { label: 'Expected goals race' });
  }
  if (!pre) shotMap(node.querySelector('#gm-map'), d, c);
  if (sd && sd.p) {
    const data = [];
    sd.p.forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])));
    QKC.heatmap('#gm-sd', { x: sd.p[0].map((_, j) => String(j)), y: sd.p.map((_, i) => String(i)), data: data, fmt: v => (v * 100).toFixed(1) + '%', cellLabels: true,
      xName: RK.teamAbbr(c.away) + ' goals', yName: RK.teamAbbr(c.home) + ' goals' });
  }
  if (pre && Array.isArray(td) && td.length) {
    const n = Math.min(td.length, 13);
    QKC.bar('#gm-td', { cats: td.slice(0, n).map((_, i) => String(i)), series: [{ name: 'Chance', color: 'model', data: td.slice(0, n) }], fmt: v => (v * 100).toFixed(1) + '%', catName: 'Total goals', valName: 'Chance' });
  }
  if (!pre) boxTables(node.querySelector('#gm-box'), d, c);
  if (live) RK.liveRefresh([RK.gamePath(c.game_id)], 30000);
}

function gamePage(el, params, state) {
  const id = params.id;
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'summary';
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([RK.loadGame(id), RK.loadYear('season.json', RK.gameSeason ? RK.gameSeason(id) : undefined)]).then(res => {
    const d = res[0], season = RK.ok(res[1]) ? res[1] : null;
    if (!U.alive(el)) return;
    const c = cardOf(RK.ok(d) ? d : null, id);
    if (!c.home && !(RK.ok(d) && d.card)) {
      el.innerHTML = U.secHead('fixtures', 'Game ' + id, 'This game is not in the published data.', null, null, 'NHL · Game centre') + U.card2('Not found', '', QK.empty('No game ' + id, 'Pick a game from the games page.'));
      return;
    }
    if (!c.game_id) c.game_id = id;
    const g = U.game(c);
    document.title = RK.teamAbbr(c.away) + ' @ ' + RK.teamAbbr(c.home) + ' · ' + RK.fmtDate(c.date || c.start, { year: false }) + ' · ' + RK.SITE;
    const tabs = [{ key: 'summary', label: 'Summary', href: RK.gameHref(id) }, { key: 'detail', label: 'Detail: preview, game flow, lines, full box', href: RK.gameHref(id) + '?view=detail' }];
    el.innerHTML = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + RK.gamesHref(c.date) + '">← ' + esc(RK.fmtDate(c.date || c.start, { year: false })) + ' games</a></div>' +
      '<div class="rk-gtop">' + hero(c, RK.ok(d) ? d : null, g, season) + '<div class="rk-gside rk-stack">' + kpiStrip(c, RK.ok(d) ? d : null, g) +
      (RK.ok(d) ? U.card2(g.status === 'pre' ? 'Our forecast' : 'Our pre-game forecast', 'Chances from our game model; the market column is a reference, not our forecast', pregameCard(d, c) || QK.empty('No pre-game forecast'), { flush: true }) : '') + '</div></div>' +
      '<div style="margin-top:var(--sp-6)">' + U.tabsHTML(tabs, view) + '</div><div id="gm-body" style="margin-top:var(--sp-4)"></div>';
    const body = el.querySelector('#gm-body');
    if (view === 'detail') return U.legacy('game', body, params, state);
    if (!RK.ok(d)) { body.innerHTML = U.card2('Game centre', '', QK.empty('The game page is not built yet', RK.reason(d))); return; }
    summary(body, d, c, g, season);
  });
}

RK.page('games', gamesPage);
RK.page('game', gamePage);
})(window.RK);
