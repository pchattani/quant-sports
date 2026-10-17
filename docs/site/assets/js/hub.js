/* The Quant Footballer — the hub (#/).
 *
 *   a header band: today's numbers and the quick links
 *   the scoreboard: results and fixtures by day, grouped by competition
 *   the competitions: cards by family with a filter
 *   across the site: title races, leaders, national teams, competitions between editions
 *
 * Replaces the hub renderer in pages.js (this file loads last). Reads
 * competitions.json (INDEX), hub.json, and two small site-wide payloads. */
(function (FH) {
'use strict';

const { INDEX, C, esc, num, pct, fmtDate, fmtTime, fmtMetric, localDay, crest, teamHref, playerLink, matchHref, probBar,
        statusChip, setHTML, wireRowLinks, loadSite, ROUND_LABELS, FAMILY_LABELS } = FH;

let HUB = null, day = null, family = 'all', query = '';
const RECENT = '__recent', UPCOMING = '__upcoming';
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const FAMILIES = [['all', 'All'], ['league', 'Leagues'], ['cup', 'Continental & world'], ['domestic', 'National cups'], ['super', 'Super cups'], ['international', 'National teams']];

function famOf(c) { return c.kind !== 'cup' ? 'league' : (c.family || 'cup'); }
/* Crest files are named by team id (assets/crests/<tid>.png): the unified club page without a lookup. */
function tidFromCrest(src) { const m = /crests\/(\d+)\.png$/.exec(String(src || '')); return m ? m[1] : null; }
function clubHrefOf(team, slug, src) { const t = tidFromCrest(src); return t ? FH.clubHref(t, slug) : teamHref(team, slug); }
/* The first past season of a competition, when competitions.json lists them. */
function pastSeason(c) { return (c.seasons || []).find(s => s.source !== 'live') || null; }
function firstTab(c) { return (c.tabs || ['overview'])[0]; }

// ── header band ────────────────────────────────────────────────────────────

function renderBand() {
  const comps = INDEX.competitions, live = comps.filter(c => c.ok);
  const hub = HUB || {}, days = hub.days || {};
  const today = localDay(new Date().toISOString());
  const all = [].concat.apply([], Object.keys(days).map(k => days[k]));
  const todays = all.filter(i => localDay(i.date) === today);
  const inPlay = all.filter(i => i.status === 'live');
  const d = new Date();
  setHTML('hub-date', DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()]);
  const between = live.filter(c => FH.isLastEdition(c)).length;
  setHTML('hub-stats',
    tile(todays.length, 'matches today') + tile(inPlay.length, 'in play', inPlay.length ? 'live' : '') +
    tile(live.length - between, 'competitions in season') + tile(between, 'between editions'));
  const upd = hub.updated_at || INDEX.updated_at;
  setHTML('hub-updated', upd ? 'Updated ' + esc(FH.fmtStamp(upd)) : '');
}

function tile(v, label, cls) {
  return '<div class="hb-tile' + (cls ? ' ' + cls : '') + '"><span class="hb-v">' + v + '</span><span class="hb-l">' + esc(label) + '</span></div>';
}

// ── scoreboard ─────────────────────────────────────────────────────────────

function renderScoreboard() {
  const hub = HUB || {}, days = hub.days || {};
  const local = {};
  Object.keys(days).forEach(k => days[k].forEach(it => { const d = localDay(it.date) || k; (local[d] = local[d] || []).push(it); }));
  const localKeys = Object.keys(local).sort();
  const today = localDay(new Date().toISOString());
  const buckets = Object.assign({}, local), order = localKeys.slice();
  if ((hub.recent || []).length) { buckets[RECENT] = hub.recent; order.unshift(RECENT); }
  if ((hub.upcoming || []).length) { buckets[UPCOMING] = hub.upcoming; order.push(UPCOMING); }
  if (!order.length) { setHTML('scoreboard', '<div class="muted pad">No matches across the competitions followed.</div>'); setHTML('date-strip', ''); return; }
  if (!day || order.indexOf(day) < 0) {
    day = localKeys.indexOf(today) >= 0 ? today : (localKeys.find(k => k > today) || (buckets[UPCOMING] ? UPCOMING : order[order.length - 1]));
  }
  setHTML('date-strip', order.map(k => {
    const n = buckets[k].length, lv = buckets[k].filter(i => i.status === 'live').length;
    let name, date;
    if (k === RECENT) { name = 'Latest'; date = 'results'; }
    else if (k === UPCOMING) { name = 'Next up'; date = 'fixtures'; }
    else { const d = FH.parseDate(k + 'T12:00:00Z'); name = k === today ? 'Today' : DAYS[d.getDay()]; date = d.getDate() + ' ' + MONTHS[d.getMonth()]; }
    return '<button class="day-btn' + (k === day ? ' active' : '') + (k === today ? ' today' : '') + (k === RECENT || k === UPCOMING ? ' bucket' : '') + '" data-day="' + k + '">' +
      '<span class="day-name">' + name + '</span><span class="day-date">' + date + '</span><span class="day-n">' + n + (lv ? ' · <span class="live-dot"></span>' : '') + '</span></button>';
  }).join(''));
  document.querySelectorAll('#date-strip .day-btn').forEach(b => b.addEventListener('click', () => { day = b.dataset.day; renderScoreboard(); }));
  const showDate = day === RECENT || day === UPCOMING;
  const items = buckets[day].slice().sort((a, b) => String(a.date).localeCompare(String(b.date)) || a.comp.localeCompare(b.comp));
  const byComp = {};
  items.forEach(it => (byComp[it.comp] = byComp[it.comp] || []).push(it));
  const compOrder = INDEX.competitions.map(c => c.slug).filter(s => byComp[s]);
  setHTML('scoreboard', '<div class="sb-grid">' + compOrder.map(slug => {
    const c = INDEX.competitions.find(x => x.slug === slug) || { name: slug };
    return '<div class="sb-comp"><div class="sb-comp-head"><a href="#/' + esc(slug) + '/fixtures">' + esc(c.name) + '</a><span class="sb-country">' + esc(c.country || FAMILY_LABELS[c.family] || '') + '</span></div>' +
      byComp[slug].map(it => row(it, slug, showDate)).join('') + '</div>';
  }).join('') + '</div>');
  wireRowLinks('scoreboard');
}

function row(it, slug, showDate) {
  const href = it.detail ? matchHref(it.id, slug) : '#/' + slug + '/fixtures';
  const done = it.status === 'finished' || it.status === 'live';
  const when = showDate ? '<span class="sb-when">' + esc(fmtDate(it.date)) + '</span>' : '';
  const tag = it.round && it.stage !== 'league' ? '<span class="sb-round">' + esc(FH.roundText(it, it.comp)) + '</span>' : '';
  return '<div class="sb-row' + (it.status === 'live' ? ' live' : '') + '" data-href="' + esc(href) + '">' +
    '<div class="sb-meta">' + when + statusChip(it) + tag + '</div>' +
    '<div class="sb-h"><a href="' + esc(clubHrefOf(it.home, slug, it.crests && it.crests[0])) + '">' + esc(it.home) + '</a>' + crest(it.home, it.crests && it.crests[0]) + '</div>' +
    '<div class="sb-score">' + (done ? '<b>' + it.hs + '</b><span>–</span><b>' + it.as + '</b>' : '<span class="vs">v</span>') + '</div>' +
    '<div class="sb-a">' + crest(it.away, it.crests && it.crests[1]) + '<a href="' + esc(clubHrefOf(it.away, slug, it.crests && it.crests[1])) + '">' + esc(it.away) + '</a></div>' +
    '<div class="sb-extra">' + (done ? (it.xg ? '<span class="xg-line">xG ' + num(it.xg[0], 2) + '–' + num(it.xg[1], 2) + '</span>' : '') : (it.model ? probBar(it.model, { small: true }) : '')) + '</div>' +
    '</div>';
}

// ── competitions ───────────────────────────────────────────────────────────

function renderCompetitions() {
  const comps = INDEX.competitions;
  setHTML('home-family', FAMILIES.map(([k, l]) => {
    const n = comps.filter(c => (k === 'all' || famOf(c) === k) && c.ok).length;
    return '<button class="fam-btn' + (k === family ? ' active' : '') + '" data-fam="' + k + '">' + esc(l) + ' <span>' + n + '</span></button>';
  }).join(''));
  document.querySelectorAll('#home-family .fam-btn').forEach(b => b.addEventListener('click', () => { family = b.dataset.fam; renderCompetitions(); }));
  const q = query.trim().toLowerCase();
  const list = comps.filter(c => (family === 'all' || famOf(c) === family) && (!q || (c.name + ' ' + (c.country || '')).toLowerCase().indexOf(q) >= 0));
  const live = list.filter(c => c.ok), soon = list.filter(c => !c.ok);
  setHTML('home-sub', live.length + ' live · ' + soon.length + ' waiting for their first fetch');
  setHTML('home-grid', live.map(card).join('') + (soon.length ? '<div class="home-soon"><span class="muted-inline">Coming as the data arrives:</span> ' +
    soon.map(c => '<span class="chip">' + esc(c.name) + '</span>').join(' ') + '</div>' : ''));
}

function card(c) {
  const frac = c.games_total ? Math.min(1, (c.games_played || 0) / c.games_total) : 0;
  const tabs = c.tabs || [];
  const link = (t, label) => tabs.indexOf(t) >= 0 ? '<a href="#/' + esc(c.slug) + '/' + t + '">' + label + '</a>' : '';
  const last = FH.isLastEdition(c), lastSeason = FH.currentSeason(c).season;
  const won = c.winner && c.winner.team ? c.winner.team : (c.favourite && (c.complete || (c.p_favourite || 0) >= 0.995) ? c.favourite : null);
  const fav = last
    ? '<div class="cc-fav"><span class="cc-fav-l">Last edition</span><span class="cc-fav-t">' + esc(lastSeason) + (won ? ' · won by ' + esc(won) : '') + '</span></div>'
    : c.favourite
    ? '<div class="cc-fav"><span class="cc-fav-l">' + esc(c.favourite_label || 'Title') + '</span><span class="cc-fav-t">' + esc(c.favourite) + '</span><span class="cc-fav-p">' + pct(c.p_favourite) + '</span></div>' +
      '<div class="cc-bar"><div style="width:' + ((c.p_favourite || 0) * 100).toFixed(1) + '%"></div></div>'
    : '<div class="cc-fav muted-inline">' + esc(c.unsimulated ? 'Not simulated: tables as played' : (c.reason || '')) + '</div>';
  const facts = [];
  if (c.leader) facts.push('<span>Leader <b>' + esc(c.leader.team) + '</b> ' + c.leader.pts + ' pts</span>');
  if (c.top_scorer) facts.push('<span>Top scorer <b>' + esc(c.top_scorer.name) + '</b> ' + c.top_scorer.goals + '</span>');
  const nxt = c.next ? '<div class="cc-next">' + esc(fmtDate(c.next.date)) + ' ' + esc(fmtTime(c.next.date)) + ' · ' + esc(c.next.home) + ' v ' + esc(c.next.away) + '</div>' : '';
  const chips = [];
  if (c.phase === 'pre') chips.push('<span class="chip">not started</span>');
  if (last) chips.push('<span class="chip warn" title="The latest edition in the data has finished; the next appears once its fixtures are published">between editions</span>');
  else if (c.complete) chips.push('<span class="chip">complete</span>');
  const ps = pastSeason(c);
  if (c.synthetic) chips.push('<span class="chip warn">sample data</span>');
  if (c.store_fresh === false) chips.push('<span class="chip warn">stale</span>');
  return '<div class="cc">' +
    '<a class="cc-head" href="#/' + esc(c.slug) + '/' + firstTab(c) + '"><span class="cc-country">' + esc(c.country || FAMILY_LABELS[c.family] || '') + '</span><span class="cc-name">' + esc(c.name) + '</span></a>' +
    fav +
    '<div class="cc-progress" title="' + (c.games_played || 0) + ' of ' + (c.games_total || 0) + ' played"><div style="width:' + (frac * 100).toFixed(1) + '%"></div></div>' +
    (facts.length ? '<div class="cc-facts">' + facts.join('') + '</div>' : '') + nxt +
    '<div class="cc-links">' + [link('table', 'Table'), link('fixtures', 'Fixtures'), link('analytics', 'Analytics'), link('players', 'Players'), last ? '' : link('probs', 'Odds'),
      ps ? '<a href="#/' + esc(c.slug) + '/p-table?s=' + esc(ps.sid) + '" title="Earlier editions, from ' + esc(ps.season) + '">Past seasons</a>' : ''].filter(Boolean).join('') + chips.join('') + '</div>' +
    '</div>';
}

// ── across the site ────────────────────────────────────────────────────────

function renderRaces() {
  // Only races still open: a decided cup at 100% is a result, not a race.
  const rows = INDEX.competitions.filter(c => c.ok && c.favourite && c.p_favourite && !c.complete && !FH.isLastEdition(c) && c.p_favourite < 0.995).sort((a, b) => b.p_favourite - a.p_favourite);
  setHTML('hub-races', rows.length ? rows.slice(0, 14).map(c =>
    '<a class="race" href="#/' + esc(c.slug) + '/probs"><span class="race-c">' + esc(c.short_name || c.name) + '</span><span class="race-t">' + esc(c.favourite) + '</span>' +
    '<span class="race-bar"><span style="width:' + (c.p_favourite * 100).toFixed(1) + '%"></span></span><span class="race-p">' + pct(c.p_favourite) + '</span></a>').join('') : '<div class="muted">Nothing simulated yet.</div>');
}

function renderLeaders() {
  const L = (HUB || {}).leaders || {};
  const block = (rows, label, fmt, extraKey, extraLabel) => (rows || []).length ? '<div class="mini-card"><div class="mini-head">' + esc(label) + '</div>' + rows.slice(0, 6).map((p, i) =>
    '<div class="mini-row"><span class="mini-rank">' + (i + 1) + '</span><span class="mini-name">' + playerLink(p.id, p.name, p.comp) + '<span class="mini-sub">' + esc(p.team) + ' · ' + esc(p.comp_name) + '</span></span><span class="mini-val">' + fmtMetric(p.value, fmt) +
    (extraKey && p[extraKey] !== undefined ? '<span class="mini-extra">' + extraLabel + ' ' + num(p[extraKey], 2) + '</span>' : '') + '</span></div>').join('') + '</div>' : '';
  const rated = (L.rating || []).filter(p => (p.minutes || 0) >= 450);          // a one-match 10.0 is not a leader
  const html = [block(L.goals, 'Goals', 'int', 'xg', 'xG'), block(L.assists, 'Assists', 'int', 'xa', 'xA'), block(rated, 'Rating (450+ minutes)', '2', 'minutes', 'min')].filter(Boolean).join('');
  setHTML('hub-leaders', html ? '<div class="mini-grid">' + html + '</div>' : '<div class="muted">No player data yet.</div>');
}

function renderTeasers() {
  const last = INDEX.competitions.filter(c => c.ok && FH.isLastEdition(c));
  setHTML('hub-last', last.length ? last.map(c => {
    const won = c.winner && c.winner.team ? c.winner.team : (c.favourite && (c.complete || (c.p_favourite || 0) >= 0.995) ? c.favourite : null);
    return '<a class="tz-row" href="#/' + esc(c.slug) + '/' + firstTab(c) + '"><span class="tz-name">' + esc(c.name) + '<span class="mini-sub">' + esc(FAMILY_LABELS[c.family] || c.country || '') + '</span></span>' +
      '<span class="tz-v">' + esc(FH.currentSeason(c).season) + '<span class="mini-sub">' + (won ? esc(won) : 'last edition') + '</span></span></a>';
  }).join('') : '<div class="muted">Every competition followed has an edition in progress.</div>');
  loadSite('nations.json').then(n => {
    const t = (n || {}).teams || [];
    if (!t.length) { setHTML('hub-nations', '<div class="muted">No international fit yet.</div>'); return; }
    setHTML('hub-nations', t.slice(0, 6).map(x => '<div class="tz-row"><span class="mini-rank">' + x.rank + '</span><span class="tz-name">' + esc(x.team) + '<span class="mini-sub">' + esc(x.confederation || '') + '</span></span><span class="tz-v">' + num(x.strength, 2) + '<span class="mini-sub">PPG v avg</span></span></div>').join('') +
      '<a class="tz-more" href="#/nations">All national teams →</a>');
  });
}

// ── page ───────────────────────────────────────────────────────────────────

function renderHome() {
  const draw = () => { renderBand(); renderScoreboard(); renderCompetitions(); renderRaces(); renderLeaders(); renderTeasers(); };
  const search = document.getElementById('home-search');
  if (search && !search.dataset.wired) { search.dataset.wired = '1'; search.addEventListener('input', e => { query = e.target.value; renderCompetitions(); }); }
  if (HUB) draw();
  else FH.fetchJSON('data/hub.json', { days: {}, leaders: {} }).then(h => { HUB = h; draw(); });
}

FH.RENDERERS.home = renderHome;
})(window.FH);
