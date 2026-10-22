/* The Quant Hardwood — markets (#/<L>/markets).
 *
 *   futures, our forecasts beside the market as a reference: champion, conference titles, awards,
 *   win totals, playoffs and play-in (yes/no markets);
 *   per-game lines: model win %, spread and total against the market;
 *   how the comparison works: removing the margin, thin and one-sided markets, what a difference means.
 *
 * Reads <L>/<S>/markets.json, season.json (model odds), awards.json, and the games list
 * (for team names on the per-game table). */
(function (HW) {
'use strict';

const esc = HW.esc;
const AWARD = { mvp: 'MVP', roy: 'Rookie of the Year', dpoy: 'Defensive Player', sixth: 'Sixth player', mip: 'Most Improved', clutch: 'Clutch Player' };

function srcText(t) {
  if (!t) return '';
  const s = t.sources ? (Array.isArray(t.sources) ? t.sources : Object.keys(t.sources)) : Object.keys(t.by_source || {});
  const bits = [];
  if (s.length) bits.push(HW.ui.srcLabel(s).split(' / ').map(x => '<span class="src-chip">' + esc(x) + '</span>').join(''));
  if (HW.isNum(t.overround)) bits.push('overround ' + HW.pct(t.overround - (t.overround > 0.5 ? 1 : 0), 1));
  if (HW.isNum(t.implied_total) && !HW.isNum(t.overround)) bits.push('implied total ' + HW.pct(t.implied_total, 0));
  return bits.join(' · ');
}

/* One futures table: rows [{id, label(html), model, market, floor}]. */
function futuresTable(rows, opts) {
  const o = opts || {};
  const list = rows.filter(r => (HW.isNum(r.model) && r.model > 0) || HW.isNum(r.market) || r.floor).sort((a, b) => (b.model || 0) - (a.model || 0) || (b.market || 0) - (a.market || 0)).slice(0, o.top || 30);
  if (!list.length) return HW.muted(o.empty || 'No market numbers.');
  const max = Math.max.apply(null, list.map(r => Math.max(r.model || 0, r.market || 0))) || 1;
  return HW.tableHTML([{ label: o.who || 'Team' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right', title: 'De-vigged market probability' },
    { label: 'Difference', align: 'right', title: 'Ours minus the market, percentage points' }],
  list.map(r => [{ v: r.sort || r.labelText, html: r.label }, { v: r.model, html: HW.probCell(r.model, r.colour || null, max) },
    { v: r.market, html: HW.isNum(r.market) ? HW.pct(r.market, 1) : (r.floor ? '<span class="thin" title="Only a no-bid floor: the market is too thin to read">thin</span>' : '—') },
    { v: HW.isNum(r.model) && HW.isNum(r.market) ? r.model - r.market : null, html: HW.edgeHTML(r.model, r.market) },
    { v: r.model, html: HW.american(r.model) }]), { compact: true });
}

function teamRows(L, sim, key, t) {
  const mk = HW.titleProbs(t);
  const floor = (t && t.floor) || [];
  const ids = {};
  Object.keys(sim).forEach(x => { ids[x] = 1; });
  Object.keys(mk).forEach(x => { ids[x] = 1; });
  return Object.keys(ids).map(id => ({ id: id, label: HW.teamLink(L, id), labelText: HW.teamName(L, id), model: (sim[id] || {})[key], market: mk[id],
    floor: floor.indexOf ? floor.indexOf(id) >= 0 : false, colour: HW.teamColour(L, id) }));
}

function gamesTable(L, games, cards) {
  const ids = Object.keys(games || {});
  if (!ids.length) return '';
  const byId = {};
  (cards || []).forEach(c => { byId[String(c.id)] = c; });
  const rows = ids.map(id => {
    const x = games[id] || {}, c = byId[id] || {};
    const m = x.model || c.model || {}, mk = x.market || c.market || {};
    const home = x.home || c.home, away = x.away || c.away;
    const ms = HW.isNum(m.margin) ? -m.margin : (HW.isNum(m.spread_fair) ? m.spread_fair : null);
    return { date: x.date || c.date, cells: [
      { v: x.date || c.date, html: esc(HW.fmtDate(x.date || c.date, { year: false, time: true })) },
      { v: home ? HW.teamName(L, home) : id, html: home ? HW.teamLink(L, away, { abbr: true }) + ' @ ' + HW.teamLink(L, home, { abbr: true }) : HW.gameLink(L, id, 'Game ' + id) },
      { v: m.p_home, html: HW.isNum(m.p_home) ? HW.pct(m.p_home, 0) : '—' }, { v: mk.p_home, html: HW.isNum(mk.p_home) ? HW.pct(mk.p_home, 0) : '—' },
      { v: HW.isNum(m.p_home) && HW.isNum(mk.p_home) ? m.p_home - mk.p_home : null, html: HW.edgeHTML(m.p_home, mk.p_home) },
      { v: ms, html: HW.fmtSpread(ms) }, { v: mk.spread_home, html: HW.fmtSpread(mk.spread_home) },
      { v: m.total, html: HW.num(m.total, 1), cls: 'hide-sm' }, { v: mk.total, html: HW.num(mk.total, 1), cls: 'hide-sm' },
      { html: HW.gameLink(L, id, '→') }
    ] };
  }).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  return HW.tableHTML([{ label: 'Tip-off' }, { label: 'Game' }, { label: 'Home win', align: 'right', title: 'Model home win probability' }, { label: 'Market', align: 'right' },
    { label: 'Difference', align: 'right' }, { label: 'Margin', align: 'right', title: 'Our expected margin for the home team' }, { label: 'Market', align: 'right' },
    { label: 'Total', align: 'right', cls: 'hide-sm' }, { label: 'Market', align: 'right', cls: 'hide-sm' }, { label: '', sortable: false }], rows, { compact: true });
}

function explainer() {
  return '<div class="mk-explain">' +
    '<p><b>De-vigging.</b> A bookmaker’s or exchange’s numbers add up to more than 100% (the overround, or vig). We read the middle of each market’s bid and ask, ' +
    'then scale a whole field (every team for the title, every player for an award) so it sums to 100%. Two-way markets (over/under, yes/no) are normalised the same way. ' +
    'When several sources quote the same market we average them.</p>' +
    '<p><b>Thin markets.</b> Long shots often have only a bid of 1¢ or nothing at all. Those are marked <span class="thin">thin</span> and left out of the difference: a no-bid floor says ' +
    'the market is uninterested, not that the probability is 1%. Award markets before the season, and anything with few traders, deserve the same caution.</p>' +
    '<p><b>Differences.</b> The difference is ours minus the market in percentage points. A positive difference means we rate the outcome more likely than the market does. ' +
    'It is not advice: models miss injuries, rest and trades that markets take in quickly, and the calibration page shows how often each side has been right.</p>' +
    '<p>For information and entertainment only; 18+; gamble responsibly. <a href="#/disclaimer">Disclaimer &amp; terms</a>.</p></div>';
}

function render(el, params) {
  const L = params.league, S = params.season;
  el.innerHTML = HW.pageHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S) + ' markets', 'The model against the market, futures and games',
    '<a href="' + HW.href(L, 'calibration') + '">Calibration</a><a href="' + HW.seasonHref(L, S) + '">Season</a>') + '<div id="mk-body"><div class="muted">Loading…</div></div>';
  return HW.loadAll([HW.lpath('markets.json', L), HW.path('season.json', L, S), HW.path('awards.json', L, S), HW.path('players.json', L, S)]).then(arr => {
    if (!el.isConnected) return;
    const mk = HW.ok(arr[0]) ? arr[0] : null, season = HW.ok(arr[1]) ? arr[1] : null, awards = HW.ok(arr[2]) ? arr[2] : null;
    const body = document.getElementById('mk-body');
    if (!mk && !season) { body.innerHTML = HW.card('Markets', '', HW.notBuilt('The markets payload', arr[0])) + HW.card('How to read this page', '', explainer()); return; }
    const fut = (mk && mk.futures) || {};
    const sim = HW.simTeams(season);
    let html = '';
    const tabs = [];
    const panels = {};
    // champion
    panels.champion = futuresTable(teamRows(L, sim, 'p_title', fut.champion), { empty: 'No title market.' });
    tabs.push({ key: 'champion', label: 'Champion', sub: srcText(fut.champion) });
    // conferences
    const confs = fut.conference && typeof fut.conference === 'object' ? Object.keys(fut.conference) : [];
    confs.forEach(c => {
      const t = fut.conference[c];
      const inConf = {};
      Object.keys(sim).forEach(id => { if (String(sim[id].conference || HW.team(L, id).conference || '').toLowerCase() === c.toLowerCase()) inConf[id] = sim[id]; });
      panels['conf_' + c] = futuresTable(teamRows(L, Object.keys(inConf).length ? inConf : sim, 'p_conf', t), { empty: 'No ' + c + ' market.' });
      tabs.push({ key: 'conf_' + c, label: c, sub: srcText(t) });
    });
    // playoffs / play-in
    ['playoffs', 'playin'].forEach(k => {
      if (!fut[k] && (!Object.keys(sim).length || (k === 'playin' && !Object.keys(sim).some(t => sim[t].p_playin > 0)))) return;
      panels[k] = futuresTable(teamRows(L, sim, k === 'playoffs' ? 'p_playoffs' : 'p_playin', fut[k]), { empty: 'No market.' });
      tabs.push({ key: k, label: k === 'playoffs' ? 'Make playoffs' : 'Play-in', sub: srcText(fut[k]) });
    });
    // awards
    Object.keys(AWARD).forEach(k => {
      const a = awards && awards[k];
      const t = (a && a.market) || fut[k];
      if (!a && !t) return;
      const model = (a && a.model) || {};
      const m = HW.titleProbs(t);
      const ids = {};
      Object.keys(model).forEach(x => { ids[x] = 1; });
      Object.keys(m).forEach(x => { ids[x] = 1; });
      panels[k] = futuresTable(Object.keys(ids).map(pid => ({ id: pid, label: HW.playerLink(L, pid, { team: (HW.NAMES[L].players[pid] || {}).team }), labelText: HW.playerName(L, pid),
        model: model[pid], market: m[pid], colour: HW.teamColour(L, (HW.NAMES[L].players[pid] || {}).team) })), { who: 'Player', top: 15, empty: 'No ' + AWARD[k] + ' market.' });
      tabs.push({ key: k, label: AWARD[k], sub: srcText(t) });
    });
    // win totals
    const wt = (mk && mk.win_totals) || (season && season.win_totals) || fut.win_totals || {};
    const wtIds = Object.keys(wt);
    const pre = (season && season.phase === 'preseason');
    if (wtIds.length) {
      panels.wins = HW.tableHTML([{ label: 'Team' }, { label: 'Line', align: 'right' }, { label: 'Proj W', align: 'right' }, { label: 'Over (model)', align: 'right' },
        { label: 'Over (market)', align: 'right' }, { label: 'Difference', align: 'right' }],
      wtIds.map(t => {
        const w = wt[t] || {}, s = sim[t] || {};
        const pm = HW.isNum(w.p_over_model) ? w.p_over_model : w.model, pk = HW.isNum(w.p_over_market) ? w.p_over_market : (HW.isNum(w.p_over) ? w.p_over : w.market);
        return [{ v: HW.teamName(L, t), html: HW.teamLink(L, t) }, { v: w.line, html: HW.num(w.line, 1) }, { v: s.exp_w, html: HW.num(s.exp_w, 1) },
          { v: pm, html: HW.isNum(pm) ? HW.pct(pm, 0) : '—' }, { v: pk, html: HW.isNum(pk) ? HW.pct(pk, 0) : '—' },
          pre ? { v: null, html: '<span class="muted-inline">hidden</span>' } : { v: HW.isNum(pm) && HW.isNum(pk) ? pm - pk : null, html: HW.edgeHTML(pm, pk) }];
      }), { compact: true }) + (pre ? '<div class="section-note">Differences are hidden in the preseason: the preseason ratings are last season carried forward plus a roster term that counts rookies at replacement level, so model-against-market gaps would partly measure what that term misses. They appear once games are played.</div>' : '');
      tabs.push({ key: 'wins', label: 'Win totals', sub: 'over/under season wins' });
    }
    html += HW.card('Futures', 'model against the de-vigged market', '<div class="toggle-row" id="mk-tabs">' + HW.toggles(tabs, tabs[0].key, 'data-mk') + '</div><div class="section-note" id="mk-sub"></div><div id="mk-panel"></div>');
    html += HW.card('Game lines', 'model against the market for upcoming games', '<div id="mk-games"><div class="muted">Loading games…</div></div>');
    html += HW.card('How to read this page', 'removing the margin, thin markets and differences', explainer());
    body.innerHTML = html;
    const show = k => {
      const tab = tabs.find(t => t.key === k) || tabs[0];
      document.getElementById('mk-panel').innerHTML = panels[tab.key] || HW.muted('No market numbers.');
      document.getElementById('mk-sub').innerHTML = tab.sub || '';
      HW.sortable(document.getElementById('mk-panel'));
    };
    show(tabs[0].key);
    HW.wireToggles(document.getElementById('mk-tabs'), 'data-mk', show);
    const info = HW.leagueInfo(L);
    const cards = (info.today || []).concat(info.next_games || [], info.last_games || []);
    const gm = (mk && mk.games) || {};
    let gl = gamesTable(L, gm, cards);
    if (!gl) {
      const upcoming = cards.filter(c => HW.gameState(c) !== 'post' && (c.model || c.market));
      const synth = {};
      upcoming.forEach(c => { synth[c.id] = { model: c.model, market: c.market, home: c.home, away: c.away, date: c.date }; });
      gl = gamesTable(L, synth, cards);
    }
    document.getElementById('mk-games').innerHTML = gl || HW.muted('No upcoming games with lines.');
    HW.sortable(document.getElementById('mk-games'));
    HW.setMeta(mk && mk.updated_at ? 'Market numbers ' + esc(HW.fmtStamp(mk.updated_at)) : '');
  });
}

HW.route('markets', render);
})(window.HW);
