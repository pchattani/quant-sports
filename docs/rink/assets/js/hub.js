/* The Quant Rink — the hub (#/).
 *
 *   band: today at a glance (games today and live now, the Stanley Cup favourite, the biggest
 *         model–market gap, the next puck drop) and the playoff-odds snapshot by conference;
 *   live games (refreshed every minute while any game is live);
 *   today's games as cards, then the model v market v line table with live win probability;
 *   the biggest model–market gaps (games and futures), last night's results, the next day's games,
 *   leaders, explore links.
 *
 * Reads index.json (today, live, recent, upcoming, playoff_odds, leaders, gaps, teams) and
 * glossary.json (leader labels). Shares RK.mvmTable (the model v market v line table) with games.js
 * and markets.js. */
(function (RK) {
'use strict';

const esc = RK.esc;
const isNum = RK.isNum;

/* Labels and formats for the leader keys the build is likely to write; glossary.json wins when it loads. */
const LEADER_META = {
  points: ['Points', 'int'], goals: ['Goals', 'int'], assists: ['Assists', 'int'], p: ['Points', 'int'], g: ['Goals', 'int'], a: ['Assists', 'int'],
  rapm_net: ['RAPM net (xG/60)', 'signed'], pp_points: ['Power-play points', 'int'],
  ixg: ['Individual xG', '2'], gax: ['Goals above expected', 'signed1'], gsax: ['Goals saved above expected', 'signed1'],
  sv_pct: ['Save %', 'svpct'], gaa: ['Goals-against average', '2'], xgf_pct: ['On-ice xGF%', 'pct'], cf_pct: ['On-ice CF%', 'pct'],
  rapm_off: ['RAPM offence', 'signed'], rapm_def: ['RAPM defence', 'signed'], value: ['Rink value', '1'], gar: ['Goals above replacement', '1'],
  war: ['Wins above replacement', '1'], toi: ['Time on ice per game', 'toi'], hits: ['Hits', 'int'], blocks: ['Blocked shots', 'int'],
  plus_minus: ['Plus-minus', 'pm'], shots: ['Shots on goal', 'int'], wins: ['Wins', 'int'], shutouts: ['Shutouts', 'int'],
  points_per_60: ['Points per 60', 'rate'], goals_per_60: ['Goals per 60', 'rate'], fo_pct: ['Face-off %', 'pct']
};
let GLOSS = null;
function indexGlossary(g) {
  const out = {};
  if (!g) return out;
  const visit = x => {
    if (Array.isArray(x)) { x.forEach(visit); return; }
    if (!x || typeof x !== 'object') return;
    if (x.key && x.label) { if (!out[x.key]) out[x.key] = x; if (x.kind) out[x.kind + ':' + x.key] = x; }
    ['groups', 'items', 'metrics', 'entries', 'terms'].forEach(k => { if (x[k]) visit(x[k]); });
    if (!x.key && !x.groups && !x.items && !x.metrics && !x.terms) Object.keys(x).forEach(k => { if (x[k] && typeof x[k] === 'object') visit(x[k]); });
  };
  visit(g);
  return out;
}
function glossMeta(key) {
  if (GLOSS && GLOSS[key]) return GLOSS[key];
  // index.json leaders are keyed s_<metric> (skaters) and g_<metric> (goalies)
  const km = /^(s|g|sk|skater|goalie)_(.+)$/.exec(String(key));
  const kind = km ? (/^(g|goalie)$/.test(km[1]) ? 'goalie' : 'skater') : '';
  const base = km ? km[2] : String(key);
  if (GLOSS && (GLOSS[kind + ':' + base] || GLOSS[base])) return GLOSS[kind + ':' + base] || GLOSS[base];
  const m = LEADER_META[key] || LEADER_META[base];
  return m ? { label: m[0], fmt: m[1], lower: key === 'gaa' } : { label: RK.titleCase(key), fmt: null };
}
function fmtLeader(key, v) {
  const m = glossMeta(key);
  if (m.fmt) return RK.fmtVal(v, m.fmt);
  if (!isNum(v)) return '—';
  return Number.isInteger(Number(v)) ? RK.int(v) : Math.abs(v) < 1 ? RK.signed(v, 3) : RK.num(v, 1);
}

function tile(v, label, sub) { return '<div class="hb-tile"><span class="hb-v">' + v + '</span><span class="hb-l">' + esc(label) + '</span>' + (sub ? '<span class="hb-s">' + sub + '</span>' : '') + '</div>'; }

// ── the model v market v line table (shared with games.js and markets.js) ──

/* The favourite's side of a puck line and the model's chance it covers: {team, line, p} (null without a line). */
function puckCover(g, model, line) {
  const l = RK.homeLine(line || {});
  if (!isNum(l)) return null;
  const pc = model && isNum(model.puck_line_home) && model.puck_line_home > 0 && model.puck_line_home < 1 ? Number(model.puck_line_home) : null;
  const homeFav = l < 0;
  return { team: homeFav ? g.home : g.away, line: -Math.abs(l), p: pc === null ? null : (homeFav ? pc : 1 - pc) };
}
/* The live or closing line object for a card: the close for a final game when there is one. */
function lineNow(g) {
  const ln = g.line || null;
  if (!ln) return {};
  return RK.isFinal(g) && ln.close && typeof ln.close === 'object' ? Object.assign({}, ln, ln.close) : ln;
}
function mvmTable(cards, opts) {
  const o = opts || {};
  const list = (cards || []).filter(Boolean);
  if (!list.length) return RK.muted('No games to price.');
  const cols = [
    { label: 'Game', sortable: false }, { label: 'Status', sortable: false },
    { label: 'Model', align: 'right', title: 'Our pre-game win probability (overtime and shootout included) for the side we favour; live: our live win probability' },
    { label: 'Market', align: 'right', title: 'De-vigged prediction-market probability for the same side' },
    { label: 'Edge', align: 'right', title: 'Model minus market, percentage points' },
    { label: 'OT', align: 'right', title: 'Our probability the game goes to overtime' },
    { label: 'Moneyline', align: 'right', title: 'The sportsbook moneyline (home first) and its no-vig probability for the model\'s side' },
    { label: 'Puck line', align: 'right', title: 'The favourite\'s puck line and our chance it covers' },
    { label: 'Model total', align: 'right', title: 'Our expected total goals' }, { label: 'O/U', align: 'right' },
    { label: 'Lean', align: 'right', title: 'Model total minus the line, in goals' }
  ];
  const rows = list.map(g => {
    const m = g.model || {}, mk = g.market || {}, ln = lineNow(g);
    const st = RK.gameState(g);
    const live = st === 'live' || st === 'int', fin = st === 'final';
    const pH = live && isNum(g.wp_home) ? Number(g.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
    const fav = pH === null ? (isNum(mk.p_home) && mk.p_home < 0.5 ? 'away' : 'home') : (pH >= 0.5 ? 'home' : 'away');
    const mp = pH === null ? null : (fav === 'home' ? pH : 1 - pH);
    const kp = isNum(mk.p_home) ? (fav === 'home' ? Number(mk.p_home) : 1 - Number(mk.p_home)) : null;
    const nv = isNum(ln.ml_home) && isNum(ln.ml_away) ? RK.devigAm([ln.ml_home, ln.ml_away]) : null;
    const pc = puckCover(g, m, ln);
    const opl = g.line && g.line.open ? RK.homeLine(g.line.open) : null;
    const status = fin ? '<b>' + esc(RK.teamAbbr(g.away)) + ' ' + esc(g.as) + ', ' + esc(RK.teamAbbr(g.home)) + ' ' + esc(g.hs) + '</b>' + (RK.endedIn(g) ? ' ' + esc(RK.endedIn(g)) : '')
      : live ? '<span class="edge-pos">' + (st === 'int' ? esc(RK.periodLabel(g.period, g) + ' int.') : esc(RK.clockText(g.period, g.clock, g) || 'Live')) + '</span>' + (isNum(g.as) && isNum(g.hs) ? ' · ' + esc(g.as) + '-' + esc(g.hs) : '')
        : esc(RK.fmtDate(g.start || g.date, { year: false })) + ' ' + esc(RK.fmtTime(g.start));
    const tot = isNum(m.total) && isNum(ln.total) ? Number(m.total) - Number(ln.total) : null;
    return { _href: RK.gameHref(g.game_id), _class: live ? 'row-live' : '', cells: [
      { html: RK.matchupLink(g.game_id, g.away, g.home) + (o.date ? '<span class="sub-line">' + esc(RK.fmtDate(g.date || g.start, { year: false })) + '</span>' : ''), v: g.game_id, cls: 'mvm-game' },
      { html: status, v: g.start || g.date || '' },
      { html: mp === null ? '—' : esc(RK.teamAbbr(g[fav])) + ' <b>' + RK.pct(mp, 1) + '</b>' + (live ? ' <span class="sub-line">live</span>' : ''), v: mp },
      { html: kp === null ? '—' : RK.pct(kp, 1) + (RK.srcLabel(mk.sources) ? '<span class="sub-line">' + esc(RK.srcLabel(mk.sources)) + '</span>' : ''), v: kp },
      { html: fin || live ? '<span class="muted-inline">—</span>' : RK.edgeHTML(mp, kp), v: mp !== null && kp !== null ? mp - kp : null },
      { html: RK.pct(m.p_ot, 0), v: m.p_ot },
      { html: isNum(ln.ml_home) ? RK.fmtOdds(ln.ml_home) + ' / ' + RK.fmtOdds(ln.ml_away) + (nv !== null ? '<span class="sub-line">no-vig ' + esc(RK.teamAbbr(g[fav])) + ' ' + RK.pct(fav === 'home' ? nv : 1 - nv, 0) + '</span>' : '') : '—', v: nv },
      { html: pc ? esc(RK.teamAbbr(pc.team)) + ' ' + RK.fmtLine(pc.line) + (pc.p !== null ? '<span class="sub-line">model ' + RK.pct(pc.p, 0) + '</span>' : '') +
        (isNum(opl) && opl !== RK.homeLine(ln) ? '<span class="sub-line">open ' + esc(RK.lineText(g.home, g.away, opl)) + '</span>' : '') : '—', v: pc ? pc.p : null },
      { html: RK.num(m.total, 2), v: m.total },
      { html: RK.num(ln.total, 1) + (g.line && g.line.open && isNum(g.line.open.total) && isNum(ln.total) && g.line.open.total !== ln.total ? '<span class="sub-line">open ' + RK.num(g.line.open.total, 1) + '</span>' : ''), v: ln.total },
      { html: tot === null ? '—' : (Math.abs(tot) < 0.05 ? '—' : (tot > 0 ? 'Over ' : 'Under ') + RK.num(Math.abs(tot), 2)), v: tot }
    ] };
  });
  return RK.tableHTML(cols, rows, { cls: 'mvm', compact: true });
}
RK.mvmTable = mvmTable;
RK.puckCover = puckCover;
RK.lineNow = lineNow;
RK.leaderMeta = glossMeta;

// ── blocks ─────────────────────────────────────────────────────────────────

/* A leader chip's label, told apart when a skater and a goalie board share one ('Rink value (GAR)' twice ->
 * the goalie's reads 'Goalie value (GAR)'; the skater's keeps the plain label). */
function leaderLabel(k, keys) {
  const lab = String(glossMeta(k).label || k);
  const dup = keys.some(j => j !== k && String(glossMeta(j).label || j) === lab);
  if (!dup) return lab;
  const goalie = /^(g|goalie)_/.test(k);
  if (goalie) return /^rink value/i.test(lab) ? lab.replace(/^rink value/i, 'Goalie value') : 'Goalie ' + (/^[A-Z][a-z]/.test(lab) ? lab.charAt(0).toLowerCase() + lab.slice(1) : lab);
  return lab;
}
function leadersBlock(el, leaders) {
  const keys = Object.keys(leaders || {}).filter(k => (leaders[k] || []).length);
  if (!keys.length) { el.innerHTML = RK.muted('Leaderboards arrive with the first build.'); return; }
  let active = keys[0];
  const draw = () => {
    const rows = leaders[active] || [];
    const vals = rows.map(r => Number(r[1])).filter(isNum);
    const max = Math.max.apply(null, vals), min = Math.min.apply(null, vals);
    const lower = !!(glossMeta(active) || {}).lower;
    el.querySelector('.ld-rows').innerHTML = rows.map((r, i) => {
      const t = max > min ? (lower ? (max - r[1]) / (max - min) : (r[1] - min) / (max - min)) : 1;
      const x = RK.player(r[0]);
      return '<div class="lb-row"><span class="lb-n">' + (i + 1) + '</span><span class="lb-name">' + RK.playerLink(r[0]) +
        (x.team ? '<span class="pl-team">' + esc(RK.teamAbbr(x.team)) + '</span>' : '') + (x.pos ? '<span class="pl-pos">' + esc(x.pos) + '</span>' : '') + '</span>' +
        '<span class="lb-bar"><span style="width:' + (30 + 70 * t).toFixed(0) + '%"></span></span><span class="lb-v">' + fmtLeader(active, r[1]) + '</span></div>';
    }).join('');
  };
  el.innerHTML = '<div class="toggle-row">' + RK.toggles(keys.map(k => ({ key: k, label: leaderLabel(k, keys) })), active, 'data-ld') + '</div><div class="ld-rows"></div>' +
    '<a class="more-link" href="' + RK.href('leaders') + '">Every leaderboard, with filters and minimum samples →</a>';
  RK.wireToggles(el, 'data-ld', k => { active = k; draw(); });
  draw();
}

function playoffBlock(po) {
  const teams = Object.keys(po || {});
  if (!teams.length) return RK.muted('Playoff odds arrive with the first season simulation.');
  let h = '';
  RK.CONFERENCES.forEach(conf => {
    const list = teams.filter(t => RK.teamConf(t) === conf).sort((a, b) => (po[b].p_playoffs || 0) - (po[a].p_playoffs || 0)).slice(0, 10);
    if (!list.length) return;
    h += '<div class="po-conf">' + esc(conf) + '</div><div class="po-row head"><span></span><span>Team</span><span>Playoffs</span><span class="v">Div</span><span class="v">Cup</span></div>' +
      list.map((t, i) => {
        const x = po[t] || {};
        return '<div class="po-row' + (i === 7 ? ' po-cut' : '') + '"><span class="lb-n">' + (i + 1) + '</span><span class="po-name">' + RK.teamLink(t, { short: true }) + '</span>' +
          '<span>' + RK.probCell(x.p_playoffs, RK.teamColour(t)) + '</span><span class="v">' + RK.pct(x.p_div, 0) + '</span><span class="v">' + RK.pct(x.p_cup, 1) + '</span></div>';
      }).join('');
  });
  return h + '<a class="more-link" href="' + RK.playoffsHref() + '">The playoff race and the bracket →</a>';
}

/* A futures key ('cup:EDM', 'playoffs:UTA') or an index.json gap kind -> a readable outcome. */
const FUT_LABEL = { cup: 'to win the Stanley Cup', playoffs: 'to make the playoffs', pres: "to win the Presidents' Trophy", presidents: "to win the Presidents' Trophy",
  east: 'to win the East', west: 'to win the West', conf: 'to win the conference', conference: 'to win the conference', div: 'to win the division', division: 'to win the division' };
const FUT_KIND = { cup: 'Stanley Cup', playoffs: 'Make the playoffs', pres: "Presidents' Trophy", presidents: "Presidents' Trophy", east: 'Eastern Conference', west: 'Western Conference',
  conf: 'Conference winner', conference: 'Conference winner', div: 'Division winner', division: 'Division winner' };
/* A futures gap's outcome: {name ('Panthers to make the playoffs'), short ('FLA make playoffs'), kind ('Make the playoffs')}. */
function futureOutcome(x) {
  const mm = typeof x.market === 'string' ? /^([^:]+):\s*(.+)$/.exec(x.market) : null;
  const kind = x.kind && x.kind !== 'game' ? String(x.kind) : (mm ? mm[1] : '');
  const team = x.team || (mm ? mm[2] : '');
  const isTeam = team && RK.TEAMS[RK.canonTeam(team)];
  const what = FUT_LABEL[kind] || (kind ? 'to win: ' + RK.titleCase(kind) : '');
  if (x.label) return { name: x.label, short: x.label, kind: FUT_KIND[kind] || RK.titleCase(kind) };
  if (!team && !kind) return { name: typeof x.market === 'string' ? RK.titleCase(x.market) : 'Season market', short: 'Season market', kind: '' };
  return { name: ((isTeam ? RK.teamShort(team) : team) + ' ' + what).trim(), short: ((isTeam ? RK.teamAbbr(team) : team) + ' ' + what.replace(/^to /, '')).trim(), kind: FUT_KIND[kind] || RK.titleCase(kind) };
}
/* index.json gaps: {kind: game|cup|conference|division|presidents|playoffs, game_id? | team?, model, market (p), edge}
 * (older shapes: market 'cup:EDM', market_p, label, side) -> rows. */
function gapsBlock(idx) {
  const cards = {};
  ['today', 'live', 'recent', 'upcoming'].forEach(k => (idx[k] || []).forEach(c => { if (c && c.game_id) cards[c.game_id] = c; }));
  let list = (idx.gaps || []).map(x => {
    let mkp = isNum(x.market) ? Number(x.market) : (isNum(x.market_p) ? Number(x.market_p) : (isNum(x.p_market) ? Number(x.p_market) : (isNum(x.price) ? Number(x.price) : null)));
    let mdp = isNum(x.model) ? Number(x.model) : (isNum(x.p_model) ? Number(x.p_model) : null);
    let what, sub = '';
    if (x.game_id) {
      const c = cards[x.game_id] || {};
      // without a side the prices are the home team's: show the side the model likes more than the market
      let side = x.side || x.team;
      if (!side) {
        side = c.home;
        if (mdp !== null && mkp !== null && mdp < mkp) { side = c.away; mdp = 1 - mdp; mkp = 1 - mkp; }
      }
      const other = RK.otherTeam(c, side);
      what = '<a href="' + RK.gameHref(x.game_id) + '">' + esc(RK.teamShort(side)) + (other ? ' to beat the ' + esc(RK.teamShort(other)) : ' to win') + '</a>';
      sub = c.start ? esc(RK.fmtDate(c.start, { year: false })) + ' ' + esc(RK.fmtTime(c.start)) : '';
      if (c.market && RK.srcLabel(c.market.sources)) sub += (sub ? ' · ' : '') + esc(RK.srcLabel(c.market.sources));
    } else {
      const fo = futureOutcome(x);
      what = (x.team && RK.TEAMS[RK.canonTeam(x.team)] ? RK.teamBar(x.team) : '') + '<a href="#/markets">' + esc(fo.name) + '</a>';
      sub = esc(x.market_label || (fo.kind ? fo.kind + ' · season market' : 'Season market'));
    }
    return { what: what, sub: sub, model: mdp, market: mkp, edge: isNum(x.edge) ? Number(x.edge) : (mdp !== null && mkp !== null ? mdp - mkp : null) };
  }).filter(r => r.model !== null && r.market !== null);
  list.sort((a, b) => Math.abs(b.edge || 0) - Math.abs(a.edge || 0));
  list = list.slice(0, 8);
  if (!list.length) return RK.muted('No model–market gaps yet: markets are fetched with the hourly build.');
  return '<div class="gap-row head"><span>Outcome</span><span class="v">Model</span><span class="v">Market</span><span class="v">Gap</span></div>' +
    list.map(r => '<div class="gap-row"><span class="what">' + r.what + (r.sub ? '<small>' + r.sub + '</small>' : '') + '</span><span class="v">' + RK.pct(r.model, 0) +
      '</span><span class="v">' + RK.pct(r.market, 0) + '</span><span class="v">' + RK.edgeHTML(r.model, r.market) + '</span></div>').join('') +
    '<a class="more-link" href="#/markets">Every market price against the model →</a>';
}

function band(idx, S, today, live, day) {
  const po = idx.playoff_odds || {};
  const fav = Object.keys(po).sort((a, b) => (po[b].p_cup || 0) - (po[a].p_cup || 0))[0];
  const next = today.filter(RK.isPre).map(g => g.start).filter(Boolean).sort()[0] || (idx.upcoming || []).map(g => g && g.start).filter(Boolean).sort()[0];
  const done = today.filter(RK.isFinal).length;
  let gapTile = '';
  const g0 = (idx.gaps || []).map(x => Object.assign({}, x, { e: isNum(x.edge) ? x.edge : (isNum(x.model) && isNum(isNum(x.market) ? x.market : x.market_p) ? x.model - (isNum(x.market) ? x.market : x.market_p) : null) }))
    .filter(x => isNum(x.e)).sort((a, b) => Math.abs(b.e) - Math.abs(a.e))[0];
  if (g0) {
    const c = ['today', 'live', 'upcoming', 'recent'].reduce((acc, k) => acc || (idx[k] || []).find(z => z && z.game_id === g0.game_id), null);
    let what;
    if (g0.game_id) {
      // the side the model likes more than the market (prices are the home team's)
      const side = g0.side || g0.team || (c ? (g0.e >= 0 ? c.home : c.away) : null);
      what = c ? RK.teamAbbr(side) + ' to beat ' + RK.teamAbbr(RK.otherTeam(c, side)) : 'Game ' + g0.game_id;
    } else what = futureOutcome(g0).short;
    const mk = isNum(g0.market) ? g0.market : g0.market_p;
    // the outcome on the tile, the two prices in its tooltip (the tile has room for one short line)
    const tip = isNum(g0.model) && isNum(mk) ? ' title="' + esc(what + ': model ' + RK.pct(g0.model, 0) + ', market ' + RK.pct(mk, 0)) + '"' : '';
    gapTile = tile(RK.signed(g0.e * 100, 1) + ' pp', 'Biggest gap', '<a href="' + (g0.game_id ? RK.gameHref(g0.game_id) : '#/markets') + '"' + tip + '>' + esc(what) + '</a>');
  }
  return '<div class="card"><div class="pad">' +
    '<div class="hb-kicker">' + esc(RK.phaseLabel() || 'The season') + (idx.updated_at ? ' · updated ' + esc(RK.fmtStamp(idx.updated_at)) : '') + '</div>' +
    '<div class="hb-week"><span class="hb-year">' + esc(RK.seasonLabel(S)) + '</span> ' + esc(day ? RK.fmtDate(day, { year: false }) : '') + '</div>' +
    '<div class="hb-sub">Every game priced by our model against prediction markets and the betting line, with live win probability, expected goals and shot maps, and the playoff race simulated on every build.</div>' +
    '<div class="hub-mini-tiles">' +
      tile(String(today.length), 'Games today', done ? done + ' final' : (next ? 'next ' + esc(RK.fmtTime(next)) : '')) +
      tile(live.length ? '<span class="edge-pos">' + live.length + '</span>' : '0', 'Live now', live.length ? live.map(g => esc(RK.teamAbbr(g.away)) + '@' + esc(RK.teamAbbr(g.home))).join(' · ') : (next && RK.countdown(next) ? 'puck drop in ' + esc(RK.countdown(next)) : '')) +
      tile(fav ? RK.teamLink(fav, { abbr: true }) + ' ' + RK.pct(po[fav].p_cup, 0) : '—', 'Stanley Cup favourite', fav ? esc(RK.teamName(fav)) + ' (model)' : '') +
      (gapTile || tile('—', 'Biggest gap', 'no markets yet')) +
    '</div></div></div>';
}

function links() {
  const L = [[RK.standingsHref(), 'Standings', 'Wild card, points %, ratings, magic numbers, lottery'], ['#/skaters', 'Skaters', 'Percentiles, RAPM, on-ice impact'],
    ['#/goalies', 'Goalies', 'GSAx by danger and shot type'], ['#/lines', 'Lines', 'Forward lines and D pairs'], ['#/lab', 'Lab', 'Build your own scatter or leaderboard'],
    ['#/calibration', 'Calibration', 'How the model did against the closing line']];
  return '<div class="hub-links">' + L.map(x => '<a href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div>';
}

RK.route('hub', function (el) {
  const idx0 = RK.index();
  return Promise.all([RK.load('glossary.json')]).then(res => {
    if (!el.isConnected) return;
    GLOSS = indexGlossary(res[0]);
    const idx = RK.index() || idx0;
    if (!idx || idx.ok === false) { el.innerHTML = RK.pageHead('The Quant Rink', 'Odds, models and analytics for the NHL') + RK.notBuilt('The hub', idx); return; }
    const S = RK.toSeason(idx.season) || RK.currentSeason();
    const today = (idx.today || []).filter(Boolean).slice().sort((a, b) => String(a.start).localeCompare(String(b.start)));
    const liveIds = {};
    today.filter(RK.isLive).forEach(g => { liveIds[g.game_id] = 1; });
    (idx.live || []).forEach(g => { if (g && RK.isLive(g)) liveIds[g.game_id] = 1; });
    const live = today.filter(g => liveIds[g.game_id]).concat((idx.live || []).filter(g => g && liveIds[g.game_id] && !today.some(x => x.game_id === g.game_id)));
    const recent = (idx.recent || []).filter(Boolean);
    const upcoming = (idx.upcoming || []).filter(Boolean).slice().sort((a, b) => String(a.start).localeCompare(String(b.start)));
    const day = today.length ? (today[0].date || RK.localDay(today[0].start)) : RK.todayISO();
    const rest = today.filter(g => !liveIds[g.game_id]);
    const recentDay = recent.length ? (recent[0].date || RK.localDay(recent[0].start)) : null;
    const nextDay = upcoming.length ? (upcoming[0].date || RK.localDay(upcoming[0].start)) : null;
    el.innerHTML =
      '<div class="rk-band"><div class="rk-band-l">' + band(idx, S, today, live, day) +
      (live.length ? RK.card('Live now', '<span class="live-dot"></span> refreshed every minute', '<div class="gc-grid">' + live.map(g => RK.gameCard(g, { goalies: true })).join('') + '</div>') : '') +
      RK.card('Today', esc(RK.fmtDate(day, { year: false })) + ' · <a href="' + RK.gamesHref(day) + '">the games page →</a>',
        rest.length ? '<div class="gc-grid">' + rest.map(g => RK.gameCard(g)).join('') + '</div>' : RK.muted(live.length ? 'Every game today is live.' : 'No games today.' + (nextDay ? ' Next: <a href="' + RK.gamesHref(nextDay) + '">' + esc(RK.fmtDate(nextDay, { year: false })) + '</a>.' : ''))) +
      '</div><div class="rk-band-r">' + RK.card('Playoff odds', 'model · <a href="' + RK.standingsHref() + '">standings</a>', playoffBlock(idx.playoff_odds)) + '</div></div>' +
      (today.length ? RK.card('Model v market v line', 'today · our price, the de-vigged market, the moneyline, puck line and total', '<div id="hub-mvm">' + mvmTable(today) + '</div>' +
        '<div class="chart-note">Win probabilities include overtime and the shootout. The puck line is shown for the favourite with our chance it covers; "Lean" compares our expected goals with the total. For information only: not betting advice.</div>') : '') +
      '<div class="hub-cols"><div>' +
        RK.card('Biggest model–market gaps', 'games and futures', gapsBlock(idx)) +
        (recent.length ? RK.card('Last results', recentDay ? '<a href="' + RK.gamesHref(recentDay) + '">' + esc(RK.fmtDate(recentDay, { year: false })) + ' →</a>' : '', '<div class="gc-grid">' + recent.map(g => RK.gameCard(g, { compact: true })).join('') + '</div>') : '') +
        (upcoming.length ? RK.card('Coming up', nextDay ? '<a href="' + RK.gamesHref(nextDay) + '">' + esc(RK.fmtDate(nextDay, { year: false })) + ' →</a>' : '', '<div class="gc-grid">' + upcoming.slice(0, 8).map(g => RK.gameCard(g, { compact: true, date: true })).join('') + '</div>') : '') +
      '</div><div>' +
        RK.card('Leaders', esc(RK.seasonLabel(S)), '<div id="hub-leaders"></div>') +
        RK.card('Explore', '', links()) +
      '</div></div>';
    leadersBlock(el.querySelector('#hub-leaders'), idx.leaders);
    RK.sortable(el);
    RK.setMeta(live.length ? '<span class="live-dot"></span> ' + live.length + ' live' : '');
    if (live.length) RK.liveRefresh([], 60000);
  });
});

})(window.RK);
