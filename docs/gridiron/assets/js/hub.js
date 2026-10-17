/* The Quant Gridiron — the hub (#/).
 *
 *   band: the season and week, at a glance (games this week and live now, the Super Bowl
 *         favourite, the biggest model–market gap, the next kickoff) and the playoff-odds snapshot;
 *   live games (refreshed every minute while any game is live);
 *   this week's games as cards, then the model v market v line table with live win probability;
 *   the biggest model–market gaps (games and futures), leaders, last week's results, explore links.
 *
 * Reads index.json (games, live, recent, playoff_odds, standings_top, leaders, gaps, teams) and
 * glossary.json (leader labels). Shares GI.mvmTable (the model v market v line table) with week.js. */
(function (GI) {
'use strict';

const esc = GI.esc;
const isNum = GI.isNum;

/* Labels and formats for the leader keys the build is likely to write; glossary.json wins when it loads. */
const LEADER_META = {
  epa_per_play: ['EPA per play', 'epa'], epa_per_db: ['EPA per dropback', 'epa'], qb_epa: ['QB EPA per play', 'epa'], cpoe: ['CPOE', 'pctpts'],
  value: ['Gridiron Value', '1'], gv: ['Gridiron Value', '1'], pass_yards: ['Passing yards', 'int'], pass_td: ['Passing TDs', 'int'],
  rush_yards: ['Rushing yards', 'int'], rush_td: ['Rushing TDs', 'int'], ryoe: ['Rush yards over expected', 'int'], ryoe_per_att: ['RYOE per carry', 'signed'],
  rec_yards: ['Receiving yards', 'int'], rec_td: ['Receiving TDs', 'int'], yprr: ['Yards per route run', '2'], target_share: ['Target share', 'pct'],
  yac_oe: ['YAC over expected', '1'], separation: ['Separation (yds)', '1'], sacks: ['Sacks', '1'], pressures: ['Pressures', 'int'],
  fg_oe: ['FG points over expected', 'signed1'], ttt: ['Time to throw', 'sec'], adot: ['aDOT', '1'], success_rate: ['Success rate', 'pct']
};
let GLOSS = null;
function indexGlossary(g) {
  const out = {};
  if (!g) return out;
  const visit = x => {
    if (Array.isArray(x)) { x.forEach(visit); return; }
    if (!x || typeof x !== 'object') return;
    if (x.key && x.label) out[x.key] = x;
    ['groups', 'items', 'metrics', 'entries', 'terms'].forEach(k => { if (x[k]) visit(x[k]); });
    if (!x.key && !x.groups && !x.items && !x.metrics && !x.terms) Object.keys(x).forEach(k => { if (x[k] && typeof x[k] === 'object') visit(x[k]); });
  };
  visit(g);
  return out;
}
const GROUP_RE = /^(qb|rb|wr|te|k|p|def)_/;
function glossMeta(key0) {
  const gm = GROUP_RE.exec(key0);
  const key = String(key0).replace(GROUP_RE, '');
  const pre = gm ? gm[1].toUpperCase() + ' · ' : '';
  if (GLOSS && (GLOSS[key0] || GLOSS[key])) { const x = GLOSS[key0] || GLOSS[key]; return Object.assign({}, x, { label: pre + x.label }); }
  const m = LEADER_META[key];
  return m ? { label: pre + m[0], fmt: m[1] } : { label: pre + GI.titleCase(key), fmt: null };
}
function fmtLeader(key, v) {
  const m = glossMeta(key);
  if (m.fmt === 'pctpts') return isNum(v) ? GI.signed(Math.abs(v) < 1 ? v * 100 : v, 1) : '—';
  if (m.fmt) return GI.fmtVal(v, m.fmt);
  if (!isNum(v)) return '—';
  return Number.isInteger(Number(v)) ? GI.int(v) : Math.abs(v) < 1 ? GI.signed(v, 3) : GI.num(v, 1);
}

function tile(v, label, sub) { return '<div class="hb-tile"><span class="hb-v">' + v + '</span><span class="hb-l">' + esc(label) + '</span>' + (sub ? '<span class="hb-s">' + sub + '</span>' : '') + '</div>'; }

// ── the model v market v line table (shared with week.js) ──────────────────

/* The side the model prefers against the line, in points: {team, pts} (null without both lines). */
function lineLean(g, mLine, lLine) {
  if (!isNum(mLine) || !isNum(lLine)) return null;
  const d = Number(lLine) - Number(mLine);           // > 0: the model makes home a bigger favourite than the line
  if (Math.abs(d) < 0.05) return { team: null, pts: 0 };
  return { team: d > 0 ? g.home : g.away, pts: Math.abs(d) };
}
function mvmTable(cards, opts) {
  const o = opts || {};
  const list = (cards || []).filter(Boolean);
  if (!list.length) return GI.muted('No games to price.');
  const cols = [
    { label: 'Game', sortable: false }, { label: 'Status', sortable: false },
    { label: 'Model', align: 'right', title: 'Our pre-game win probability for the side we favour (live: our live win probability)' },
    { label: 'Market', align: 'right', title: 'De-vigged prediction-market or bookmaker probability for the same side' },
    { label: 'Model − market', align: 'right', title: 'Model minus market, percentage points: a disagreement, not a recommendation' },
    { label: 'Model line', align: 'right', title: 'Our fair spread' }, { label: 'Line', align: 'right', title: 'The current (or closing) spread; open in grey' },
    { label: 'Line gap', align: 'right', title: 'Where our fair line differs from the market line, in points: a disagreement, not a recommendation' },
    { label: 'Model total', align: 'right' }, { label: 'O/U', align: 'right' }, { label: 'Over/under', align: 'right', title: 'Model total minus the line' }
  ];
  const rows = list.map(g => {
    const m = g.model || {}, mk = g.market || {}, ln = g.line || {};
    const st = GI.gameState(g);
    const live = st === 'live' || st === 'half', fin = st === 'final';
    const pH = live && isNum(g.wp_home) ? Number(g.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
    const fav = pH === null ? (isNum(mk.p_home) && mk.p_home < 0.5 ? 'away' : 'home') : (pH >= 0.5 ? 'home' : 'away');
    const mp = pH === null ? null : (fav === 'home' ? pH : 1 - pH);
    const kp = isNum(mk.p_home) ? (fav === 'home' ? Number(mk.p_home) : 1 - Number(mk.p_home)) : null;
    const mLine = GI.homeLine(m), lLine = GI.homeLine(ln), oLine = ln.open ? GI.homeLine(ln.open) : null;
    const lean = lineLean(g, mLine, lLine);
    const status = fin ? '<b>' + esc(GI.teamAbbr(g.away)) + ' ' + esc(g.as) + ', ' + esc(GI.teamAbbr(g.home)) + ' ' + esc(g.hs) + '</b>' + (GI.isOT(g) ? ' OT' : '')
      : live ? '<span class="edge-pos">' + esc(GI.clockText(g.qtr, g.clock) || 'Live') + '</span>' + (isNum(g.as) && isNum(g.hs) ? ' · ' + esc(g.as) + '-' + esc(g.hs) : '')
        : esc(GI.fmtDate(g.kickoff, { year: false })) + ' ' + esc(GI.fmtTime(g.kickoff));
    const tot = isNum(m.total) && isNum(ln.total) ? Number(m.total) - Number(ln.total) : null;
    return { _href: GI.gameHref(g.game_id), _class: live ? 'row-live' : '', cells: [
      { html: GI.matchupLink(g.game_id, g.away, g.home) + (o.week && isNum(g.week) ? '<span class="sub-line">' + esc(GI.weekLabel(g.week, GI.gameSeason(g.game_id))) + '</span>' : ''), v: g.game_id, cls: 'mvm-game' },
      { html: status, v: g.kickoff || '' },
      { html: mp === null ? '—' : esc(GI.teamAbbr(g[fav])) + ' <b>' + GI.pct(mp, 1) + '</b>' + (live ? ' <span class="sub-line">live</span>' : ''), v: mp },
      { html: kp === null ? '—' : GI.pct(kp, 1) + (mk.sources && mk.sources.length ? '<span class="sub-line">' + esc(mk.sources.join(' · ')) + '</span>' : ''), v: kp },
      { html: fin || live ? '<span class="muted-inline">—</span>' : GI.edgeHTML(mp, kp), v: mp !== null && kp !== null ? mp - kp : null },
      { html: esc(GI.spreadText(g.home, g.away, mLine)), v: mLine },
      { html: esc(GI.spreadText(g.home, g.away, lLine)) + (isNum(oLine) && isNum(lLine) && oLine !== lLine ? '<span class="sub-line">open ' + esc(GI.spreadText(g.home, g.away, oLine)) + '</span>' : ''), v: lLine },
      { html: lean ? (lean.team ? esc(GI.teamAbbr(lean.team)) + ' ' + GI.num(lean.pts, 1) : '—') : '—', v: lean ? lean.pts : null },
      { html: GI.num(m.total, 1), v: m.total },
      { html: GI.num(ln.total, 1) + (ln.open && isNum(ln.open.total) && isNum(ln.total) && ln.open.total !== ln.total ? '<span class="sub-line">open ' + GI.num(ln.open.total, 1) + '</span>' : ''), v: ln.total },
      { html: tot === null ? '—' : (Math.abs(tot) < 0.05 ? '—' : (tot > 0 ? 'Over ' : 'Under ') + GI.num(Math.abs(tot), 1)), v: tot }
    ] };
  });
  return GI.tableHTML(cols, rows, { cls: 'mvm', compact: true });
}
GI.mvmTable = mvmTable;
GI.lineLean = lineLean;

// ── blocks ─────────────────────────────────────────────────────────────────

function leadersBlock(el, leaders) {
  const keys = Object.keys(leaders || {}).filter(k => (leaders[k] || []).length);
  if (!keys.length) { el.innerHTML = GI.muted('Leaderboards arrive with the first build.'); return; }
  let active = keys[0];
  const draw = () => {
    const rows = leaders[active] || [];
    const vals = rows.map(r => Number(r[1])).filter(isNum);
    const max = Math.max.apply(null, vals), min = Math.min.apply(null, vals);
    const lower = !!(glossMeta(active) || {}).lower;
    el.querySelector('.ld-rows').innerHTML = rows.map((r, i) => {
      const t = max > min ? (lower ? (max - r[1]) / (max - min) : (r[1] - min) / (max - min)) : 1;
      const x = GI.player(r[0]);
      return '<div class="rk-row"><span class="rk-n">' + (i + 1) + '</span><span class="rk-name">' + GI.playerLink(r[0]) +
        (x.team ? '<span class="pl-team">' + esc(GI.teamAbbr(x.team)) + '</span>' : '') + (x.pos ? '<span class="pl-pos">' + esc(x.pos) + '</span>' : '') + '</span>' +
        '<span class="rk-bar"><span style="width:' + (30 + 70 * t).toFixed(0) + '%"></span></span><span class="rk-v">' + fmtLeader(active, r[1]) + '</span></div>';
    }).join('');
  };
  el.innerHTML = '<div class="toggle-row">' + GI.toggles(keys.map(k => ({ key: k, label: glossMeta(k).label })), active, 'data-ld') + '</div><div class="ld-rows"></div>' +
    '<a class="more-link" href="' + GI.ghref('leaders') + '">Every leaderboard, with filters and minimum samples →</a>';
  GI.wireToggles(el, 'data-ld', k => { active = k; draw(); });
  draw();
}

function playoffBlock(po) {
  const teams = Object.keys(po || {});
  if (!teams.length) return GI.muted('Playoff odds arrive with the first season simulation.');
  let h = '';
  GI.CONFERENCES.forEach(conf => {
    const list = teams.filter(t => GI.teamInfo(t).conference === conf).sort((a, b) => (po[b].p_playoffs || 0) - (po[a].p_playoffs || 0)).slice(0, 9);
    if (!list.length) return;
    h += '<div class="po-conf">' + esc(conf) + '</div><div class="po-row head"><span></span><span>Team</span><span>Playoffs</span><span class="v">Div</span><span class="v">SB</span></div>' +
      list.map((t, i) => {
        const x = po[t] || {};
        return '<div class="po-row' + (i === 6 ? ' po-cut' : '') + '"><span class="rk-n">' + (i + 1) + '</span><span class="po-name">' + GI.teamLink(t, { short: true }) + '</span>' +
          '<span>' + GI.probCell(x.p_playoffs, GI.teamColour(t)) + '</span><span class="v">' + GI.pct(x.p_div, 0) + '</span><span class="v">' + GI.pct(x.p_sb, 1) + '</span></div>';
      }).join('');
  });
  return h + '<a class="more-link" href="' + GI.playoffsHref() + '">The playoff picture, seeds and bracket →</a>';
}

/* index.json gaps: {game_id | market, model, market (p) | market_p, edge, label?, side?} -> rows. */
function gapsBlock(idx) {
  const cards = {};
  ['games', 'live', 'recent'].forEach(k => (idx[k] || []).forEach(c => { if (c && c.game_id) cards[c.game_id] = c; }));
  let list = (idx.gaps || []).map(x => {
    const label0 = x.label || x.name || (typeof x.market === 'string' ? x.market : '');
    const mkp = isNum(x.market) ? Number(x.market) : (isNum(x.market_p) ? Number(x.market_p) : (isNum(x.p_market) ? Number(x.p_market) : (isNum(x.price) ? Number(x.price) : null)));
    const mdp = isNum(x.model) ? Number(x.model) : (isNum(x.p_model) ? Number(x.p_model) : null);
    let what, sub = '';
    if (x.game_id) {
      const c = cards[x.game_id] || GI.parseGameId(x.game_id) || {};
      const side = x.side || x.team || (mdp !== null && mkp !== null && mdp >= mkp ? c.home : c.away);
      const other = GI.otherTeam(c, side);
      what = '<a href="' + GI.gameHref(x.game_id) + '">' + esc(GI.teamShort(side)) + (other ? ' to beat the ' + esc(GI.teamShort(other)) : ' to win') + '</a>';
      sub = c.kickoff ? esc(GI.fmtDate(c.kickoff, { year: false })) + ' ' + esc(GI.fmtTime(c.kickoff)) : '';
      if (c.market && c.market.sources) sub += (sub ? ' · ' : '') + esc(c.market.sources.join(', '));
    } else {
      const mm = /^([^:]+):\s*(.+)$/.exec(label0);
      const name = mm ? (GI.TEAMS[GI.canonTeam(mm[2])] ? GI.teamShort(mm[2]) : mm[2]) + ' · ' + (GI.marketLabel ? GI.marketLabel(mm[1]) : GI.titleCase(mm[1])) : (label0 ? GI.titleCase(label0) : 'Future');
      what = '<a href="#/markets">' + esc(name) + '</a>';
      sub = esc(x.market_label || 'season market');
    }
    return { what: what, sub: sub, model: mdp, market: mkp, edge: isNum(x.edge) ? Number(x.edge) : (mdp !== null && mkp !== null ? mdp - mkp : null) };
  }).filter(r => r.model !== null && r.market !== null);
  list.sort((a, b) => Math.abs(b.edge || 0) - Math.abs(a.edge || 0));
  list = list.slice(0, 8);
  if (!list.length) return GI.muted('No model–market gaps yet: markets are fetched with the hourly build.');
  return '<div class="gap-row head"><span>Outcome</span><span class="v">Model</span><span class="v">Market</span><span class="v" title="Model minus market, percentage points">Gap</span></div>' +
    list.map(r => '<div class="gap-row"><span class="what">' + r.what + (r.sub ? '<small>' + r.sub + '</small>' : '') + '</span><span class="v">' + GI.pct(r.model, 0) +
      '</span><span class="v">' + GI.pct(r.market, 0) + '</span><span class="v">' + GI.edgeHTML(r.model, r.market) + '</span></div>').join('') +
    '<div class="chart-note">A gap is a disagreement, not a recommendation: the model trails the closing line in our <a href="#/calibration">backtest</a>.</div>' +
    '<a class="more-link" href="#/markets">Every market price against the model →</a>';
}

function band(idx, S, W) {
  const games = idx.games || [];
  const live = games.filter(GI.isLive).concat((idx.live || []).filter(c => !games.some(g => g.game_id === c.game_id)));
  const po = idx.playoff_odds || {};
  const fav = Object.keys(po).sort((a, b) => (po[b].p_sb || 0) - (po[a].p_sb || 0))[0];
  const next = games.filter(GI.isPre).map(g => g.kickoff).filter(Boolean).sort()[0];
  const done = games.filter(GI.isFinal).length;
  const ph = GI.phase();
  const phaseText = ph === 'playoffs' ? 'The playoffs' : ph === 'offseason' ? 'The offseason' : ph === 'preseason' ? 'Before the season' : 'The regular season';
  let gapTile = '';
  const g0 = (idx.gaps || []).filter(x => isNum(x.edge)).sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))[0];
  if (g0) {
    const nm = g0.label || g0.name || (typeof g0.market === 'string' ? g0.market : '');
    const mm = /^([^:]+):\s*(.+)$/.exec(nm);
    const what = g0.game_id ? g0.game_id.replace(/^\d{4}_\d\d_/, '').replace('_', ' @ ') : (mm ? GI.teamAbbr(mm[2]) + ' · ' + (GI.marketLabel ? GI.marketLabel(mm[1]) : mm[1]) : nm);
    gapTile = tile(GI.signed(g0.edge * 100, 1) + ' pp', 'Biggest model − market gap', esc(what));
  }
  return '<div class="card"><div class="pad">' +
    '<div class="hb-kicker">' + esc(phaseText) + ' · updated ' + esc(GI.fmtStamp(idx.updated_at)) + '</div>' +
    '<div class="hb-week"><span class="hb-year">' + S + '</span> ' + esc(GI.weekLabel(W, S)) + '</div>' +
    '<div class="hb-sub">Every game priced by our model against prediction markets and the betting line, with live win probability, every fourth down graded and the playoff race simulated on every build.</div>' +
    '<div class="hub-mini-tiles">' +
      tile(String(games.length), 'Games this ' + (GI.weekType(W, S) === 'REG' ? 'week' : 'round'), done ? done + ' final' : (next ? 'next ' + esc(GI.fmtDate(next, { year: false })) + ' ' + esc(GI.fmtTime(next)) : '')) +
      tile(live.length ? '<span class="edge-pos">' + live.length + '</span>' : '0', 'Live now', live.length ? live.map(g => esc(GI.teamAbbr(g.away)) + '@' + esc(GI.teamAbbr(g.home))).join(' · ') : (next ? 'kickoff in ' + esc(GI.countdown(next)) : '')) +
      tile(fav ? GI.teamLink(fav, { abbr: true }) + ' ' + GI.pct(po[fav].p_sb, 0) : '—', 'Super Bowl favourite', fav ? esc(GI.teamName(fav)) + ' (model)' : '') +
      (gapTile || tile('—', 'Biggest gap', 'no markets yet')) +
    '</div></div></div>';
}

function links() {
  const L = [['#/fourth-downs', 'Fourth downs', 'Every decision this season, graded'], [GI.standingsHref(), 'Standings', 'Ratings, SOS, magic numbers, draft order'],
    ['#/players', 'Players', 'Percentiles by position'], ['#/teams', 'Teams', 'Units, tendencies, schedule v model'], ['#/lab', 'Lab', 'Build your own scatter or leaderboard'],
    ['#/calibration', 'Calibration', 'How the model did against the closing line']];
  return '<div class="hub-links">' + L.map(x => '<a href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div>';
}

GI.route('hub', function (el) {
  const idx0 = GI.index();
  return Promise.all([GI.load('glossary.json')]).then(res => {
    if (!el.isConnected) return;
    GLOSS = indexGlossary(res[0]);
    const idx = GI.index() || idx0;
    if (!idx || idx.ok === false) { el.innerHTML = GI.pageHead('The Quant Gridiron', 'Odds, models and analytics for the NFL') + GI.notBuilt('The hub', idx); return; }
    const S = GI.isNum(idx.season) ? Number(idx.season) : GI.currentSeason();
    const W = GI.isNum(idx.week) ? Number(idx.week) : GI.currentWeek();
    const games = (idx.games || []).slice().sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
    const liveIds = {};
    games.filter(GI.isLive).forEach(g => { liveIds[g.game_id] = 1; });
    (idx.live || []).forEach(g => { if (g && GI.isLive(g)) liveIds[g.game_id] = 1; });
    const live = games.filter(g => liveIds[g.game_id]).concat((idx.live || []).filter(g => g && liveIds[g.game_id] && !games.some(x => x.game_id === g.game_id)));
    const recent = (idx.recent || []).filter(Boolean);
    const weekHref = GI.weekHref(S, W);
    el.innerHTML =
      '<div class="gi-band">' + band(idx, S, W) +
        GI.card('Playoff odds', 'model · <a href="' + GI.standingsHref() + '">standings</a>', playoffBlock(idx.playoff_odds)) + '</div>' +
      (live.length ? GI.card('Live now', '<span class="live-dot"></span> refreshed every minute', '<div class="gc-grid">' + live.map(g => GI.gameCard(g)).join('') + '</div>') : '') +
      GI.card(GI.weekLabel(W, S) + ' games', '<a href="' + weekHref + '">the week page →</a>', games.length ? '<div class="gc-grid">' + games.filter(g => !liveIds[g.game_id]).map(g => GI.gameCard(g)).join('') + '</div>' : GI.muted('No games this week.')) +
      GI.card('Model v market v line', GI.weekLabel(W, S) + ' · our price, the de-vigged market and the spread and total', '<div id="hub-mvm">' + mvmTable(games) + '</div>' +
        '<div class="chart-note">Spreads are shown for the favourite. "Line gap" is where our fair line differs from the market line, in points; "Over/under" compares our total with the line. Gaps are disagreements, not recommendations: the model trails the closing line in our <a href="#/calibration">backtest</a>. For information only: not betting advice.</div>') +
      '<div class="hub-cols"><div>' +
        GI.card('Biggest model–market gaps', 'games and futures', gapsBlock(idx)) +
        (recent.length ? GI.card('Last week', '<a href="' + GI.weekHref(S, Math.max(1, W - 1)) + '">' + esc(GI.weekLabel(Math.max(1, W - 1), S)) + ' →</a>', '<div class="gc-grid">' + recent.map(g => GI.gameCard(g, { compact: true })).join('') + '</div>') : '') +
      '</div><div>' +
        GI.card('Leaders', esc(String(S)), '<div id="hub-leaders"></div>') +
        GI.card('Explore', '', links()) +
      '</div></div>';
    leadersBlock(el.querySelector('#hub-leaders'), idx.leaders);
    GI.sortable(el);
    GI.setMeta(live.length ? '<span class="live-dot"></span> ' + live.length + ' live' : '');
    if (live.length) GI.liveRefresh([], 60000);
  });
});

})(window.GI);
