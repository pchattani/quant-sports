/* The Quant Gridiron — Overview (#/): the week at a glance, led by numbers and charts.
 *   ticker of this week's games; hero (season, week, KPI tiles) beside the game of the week;
 *   this week's games; who wins it all (model v market); the biggest model-market gaps; power map
 *   (offence v defence); the playoff race by conference; divisions at a glance; leaders; last week.
 * Reads index.json, <S>/season.json, <S>/markets.json, glossary.json (leader labels). */
(function (GI) {
'use strict';

const QK = window.QK;
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

/* The game of the week: live first, else the upcoming game with the most at stake and the closest odds. */
function featured(games, po) {
  const live = games.filter(GI.isLive);
  if (live.length) return live[0];
  const pre = games.filter(GI.isPre);
  if (!pre.length) return games[games.length - 1] || null;
  let best = null, bs = -1;
  pre.forEach(g => {
    const p = isNum((g.model || {}).p_home) ? g.model.p_home : 0.5;
    const stake = ((po[g.home] || {}).p_playoffs || 0.5) + ((po[g.away] || {}).p_playoffs || 0.5);
    const s = stake * (1 - Math.abs(p - 0.5) * 1.6);
    if (s > bs) { bs = s; best = g; }
  });
  return best;
}
function featureCard(g, po) {
  if (!g) return GI.card('Game of the week', '', GI.muted('No games scheduled.'));
  const st = GI.gameState(g), live = GI.isLive(g), fin = st === 'final';
  const m = g.model || {}, mk = g.market || {}, ln = g.line || {};
  const pH = live && isNum(g.wp_home) ? g.wp_home : m.p_home;
  const side = (t, p, sc) => '<a class="gi-vs-team" href="' + GI.teamHref(t) + '">' + GI.mark(t, 'lg') + '<span class="nm">' + esc(GI.teamShort(t)) + '</span>' +
    '<span class="p">' + (fin ? esc(sc) : (isNum(p) ? GI.pct(p, 0) : '')) + '</span><span class="qk-sub">' + esc(GI.teamAbbr(t)) + (po[t] ? ' · playoffs ' + GI.pct(po[t].p_playoffs, 0) : '') + '</span></a>';
  const mid = '<div class="gi-vs-mid">' + (live ? '<span class="qk-badge live">' + esc(GI.clockText(g.qtr, g.clock) || 'Live') + '</span><span class="sc">' + esc(g.as) + '–' + esc(g.hs) + '</span>'
    : fin ? '<span class="qk-badge final">Final</span>' : '<span>' + esc(GI.fmtDate(g.kickoff, { year: false })) + '</span><span class="sc gi-vs-t">' + esc(GI.fmtTime(g.kickoff)) + '</span><span>' + esc(GI.countdown(g.kickoff) ? 'in ' + GI.countdown(g.kickoff) : '') + '</span>') + '</div>';
  const T = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
  const facts = [];
  if (isNum(GI.homeLine(m))) facts.push('Model <b>' + esc(GI.spreadText(g.home, g.away, GI.homeLine(m))) + '</b>');
  if (isNum(GI.homeLine(ln))) facts.push('Line <b>' + esc(GI.spreadText(g.home, g.away, GI.homeLine(ln))) + '</b>');
  if (isNum(m.total)) facts.push('Total <b>' + GI.num(m.total, 1) + '</b>' + (isNum(ln.total) ? ' v ' + GI.num(ln.total, 1) : ''));
  if (isNum(m.home_pts) && isNum(m.away_pts)) facts.push('Projected <b>' + GI.num(m.away_pts, 0) + '–' + GI.num(m.home_pts, 0) + '</b>');
  return '<section class="qk-card gi-feature" style="--fa:' + esc(GI.tc(g.away)) + ';--fh:' + esc(GI.tc(g.home)) + '"><div class="qk-card-body">' +
    '<div class="gi-feature-top"><span class="qk-kicker">' + (live ? 'Live now' : fin ? 'Final' : 'Game of the week') + '</span><a class="gi-more" href="' + GI.gameHref(g.game_id) + '">Game centre →</a></div>' +
    '<div class="gi-vs">' + side(g.away, isNum(pH) ? 1 - pH : null, g.as) + mid + side(g.home, pH, g.hs) + '</div>' +
    (!fin && isNum(pH) ? QK.probBar(1 - pH, null, pH, T(g.away), T(g.home)) : '') +
    (!fin && !live && isNum(mk.p_home) && isNum(m.p_home) ? '<div style="margin-top:10px">' + QK.mvm(m.p_home, mk.p_home, GI.teamAbbr(g.home) + ' model v mkt') + '</div>' : '') +
    (facts.length ? '<div class="gi-feature-foot">' + facts.map(f => '<span>' + f + '</span>').join('') + '</div>' : '') + '</div></section>';
}

/* index.json gaps + this week's game markets -> dumbbell rows. */
function gapRows(idx) {
  const out = [];
  (idx.games || []).forEach(g => {
    const m = g.model || {}, mk = g.market || {};
    if (!GI.isPre(g) || !isNum(m.p_home) || !isNum(mk.p_home)) return;
    const fav = m.p_home >= 0.5 ? 'home' : 'away';
    const a = fav === 'home' ? m.p_home : 1 - m.p_home, b = fav === 'home' ? mk.p_home : 1 - mk.p_home;
    out.push({ label: GI.teamAbbr(g[fav]) + ' to beat ' + GI.teamAbbr(GI.otherTeam(g, g[fav])), a: a, b: b, href: GI.gameHref(g.game_id), sub: GI.fmtDate(g.kickoff, { year: false }) + ' · ' + (mk.sources || []).join(', ') });
  });
  const KIND = { playoffs: 'make playoffs', sb: 'win Super Bowl', conf_afc: 'win AFC', conf_nfc: 'win NFC', seed1_afc: 'AFC No. 1 seed', seed1_nfc: 'NFC No. 1 seed' };
  (idx.gaps || []).forEach(x => {
    const mm = /^([^:]+):\s*(.+)$/.exec(x.name || x.label || '');
    if (!mm || !isNum(x.model) || !isNum(x.market)) return;
    const kind = mm[1], t = mm[2];
    const what = KIND[kind] || (/^div_/.test(kind) ? 'win ' + kind.replace(/^div_/, '').replace('_', ' ').toUpperCase().replace(/ (EAST|WEST|NORTH|SOUTH)$/, s => ' ' + s.trim().charAt(0) + s.trim().slice(1).toLowerCase()) : GI.titleCase(kind));
    out.push({ label: GI.teamAbbr(t) + ' to ' + what, a: x.model, b: x.market, href: '#/futures', sub: 'Season market' });
  });
  out.sort((p, q) => Math.abs(q.a - q.b) - Math.abs(p.a - p.b));
  return out.slice(0, 10);
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

GI.route('overview', function (el) {
  const idx = GI.index() || {};
  if (!GI.ok(idx)) { el.innerHTML = GI.pageHead('NFL', 'The Quant Gridiron', '') + GI.notBuilt('The overview', idx); return; }
  const S = GI.currentSeason(), W = GI.currentWeek();
  return GI.loadAll([GI.ypath('season.json', S), GI.ypath('markets.json', S), 'glossary.json']).then(res => {
    if (!el.isConnected) return;
    const season = GI.ok(res[0]) ? res[0] : null, mkts = GI.ok(res[1]) ? res[1] : null, G = glossIndex(res[2]);
    const games = (idx.games || []).slice().sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
    const liveIds = {};
    games.filter(GI.isLive).forEach(g => { liveIds[g.game_id] = 1; });
    (idx.live || []).forEach(g => { if (g && GI.isLive(g)) liveIds[g.game_id] = 1; });
    const live = games.filter(g => liveIds[g.game_id]);
    const po = idx.playoff_odds || {};
    const rows = seasonRows(season);
    const fav = Object.keys(po).sort((a, b) => (po[b].p_sb || 0) - (po[a].p_sb || 0))[0];
    const next = games.filter(GI.isPre).map(g => g.kickoff).filter(Boolean).sort()[0];
    const done = games.filter(GI.isFinal).length;
    const gaps = gapRows(idx);
    const ratings = (season && season.ratings) || {};
    const topR = Object.keys(ratings).sort((a, b) => ((ratings[b].values || {}).rating || -99) - ((ratings[a].values || {}).rating || -99))[0];
    const ph = GI.phase();
    const phaseText = ph === 'playoffs' ? 'Playoffs' : ph === 'offseason' ? 'Offseason' : ph === 'preseason' ? 'Preseason' : 'Regular season';
    const feat = featured(games, po);
    const ticker = games.length ? '<div class="qk-ticker gi-ticker" aria-label="This week\'s games">' + games.map(g => QK.tick(GI.qkGame(g))).join('') + '</div>' : '';

    el.innerHTML = ticker +
      '<section class="gi-hero">' +
        '<div class="gi-hero-main"><div class="qk-kicker">NFL ' + S + ' · ' + esc(phaseText) + ' · updated ' + esc(GI.fmtStamp(idx.updated_at)) + '</div>' +
          '<h1 class="gi-hero-title">' + esc(GI.weekLabel(W, S)) + ', <span>priced.</span></h1>' +
          '<p class="gi-hero-sub">Every game priced by our model against the prediction markets and the betting line, the playoff race simulated 20,000 times on every build, and every fourth down graded.</p>' +
          GI.kpis([
            GI.kpi('Games this week', String(games.length), live.length ? live.length + ' live now' : done ? done + ' final' : (next ? 'next ' + esc(GI.fmtDate(next, { year: false })) : '')),
            GI.kpi('Super Bowl favourite', fav ? GI.teamLink(fav, { abbr: true }) : '—', fav ? GI.pct(po[fav].p_sb, 0) + ' · ' + esc(GI.teamShort(fav)) + ' · model' : '', { accent: fav ? GI.tc(fav) : null }),
            GI.kpi('Best team rating', topR ? GI.teamLink(topR, { abbr: true }) : '—', topR ? GI.signed((ratings[topR].values || {}).rating, 1) + ' pts/g v average' : '', { tip: 'Our team-strength rating: points per game better than an average team on a neutral field' }),
            GI.kpi('Biggest model-market gap', gaps.length ? GI.signed((gaps[0].a - gaps[0].b) * 100, 0) : '—', gaps.length ? 'pts · ' + esc(gaps[0].label) : 'no markets yet', { tip: 'A disagreement, not a recommendation: the model trails the closing line in the backtest' })
          ], 'gi-kpis-4') +
          '<div class="gi-hero-links"><a class="qk-btn primary" href="' + GI.weekHref(S, W) + '">All ' + esc(GI.weekLabel(W, S)) + ' games</a><a class="qk-btn" href="#/standings">Standings</a><a class="qk-btn" href="#/playoffs">Playoff picture</a></div>' +
        '</div>' +
        '<div class="gi-hero-side">' + featureCard(feat, po) + '</div>' +
      '</section>' +

      '<section class="qk-section"><div class="qk-section-head"><div><h2>' + esc(GI.weekLabel(W, S)) + ' games</h2><div class="qk-sub">Model win probability on every card; the model-v-market strip before kickoff where a market exists.</div></div>' +
        '<a class="qk-btn" href="' + GI.weekHref(S, W) + '">Week page →</a></div>' +
        (games.length ? '<div class="qk-auto gi-games" style="--min:290px">' + games.map(g => GI.gameCard(g)).join('') + '</div>' : QK.empty('No games this week', 'The schedule is being set.')) + '</section>' +

      '<section class="qk-section"><div class="qk-section-head"><div><h2>Who wins it all</h2><div class="qk-sub">Super Bowl odds from the season simulation; the orange tick is the de-vigged market.</div></div><a class="qk-btn" href="#/futures">Every future →</a></div>' +
        GI.grid(GI.card('Super Bowl', 'model bar, market tick', GI.chartBox('ov-sb', 420, 'Super Bowl odds, model and market'), { span: 7 }) +
          GI.card('Biggest disagreements', 'blue model, orange market, this week and the season markets', GI.chartBox('ov-gaps', 420, 'Model v market gaps'), { span: 5 })) + '</section>' +

      '<section class="qk-section"><div class="qk-section-head"><div><h2>Power map</h2><div class="qk-sub">Our offence and defence ratings in points per game against an average team; up and right is better.</div></div><a class="qk-btn" href="' + GI.standingsHref(S, 'ratings') + '">Power ratings →</a></div>' +
        GI.grid(GI.card('Offence v defence', 'points per game v average', GI.chartBox('ov-power', 440, 'Offence against defence rating, every team'), { span: 7 }) +
          GI.card('Rating through the season', 'the top eight teams, week by week', GI.chartBox('ov-trend', 440, 'Team rating by week'), { span: 5 })) + '</section>' +

      '<section class="qk-section"><div class="qk-section-head"><div><h2>The playoff race</h2><div class="qk-sub">Chance to make the playoffs; the orange tick is the market where one trades.</div></div><a class="qk-btn" href="#/playoffs">Seeds and bracket →</a></div>' +
        GI.grid(GI.card('AFC', '', GI.chartBox('ov-afc', 520, 'AFC playoff odds'), { span: 6 }) + GI.card('NFC', '', GI.chartBox('ov-nfc', 520, 'NFC playoff odds'), { span: 6 })) + '</section>' +

      '<section class="qk-section"><div class="qk-section-head"><div><h2>Divisions</h2><div class="qk-sub">Record and playoff odds; tap a team for its page.</div></div><a class="qk-btn" href="#/standings">Full standings →</a></div>' +
        GI.card('', '', divisionsGrid(rows)) + '</section>' +

      '<section class="qk-section"><div class="qk-section-head"><div><h2>Leaders</h2><div class="qk-sub">' + S + ' to date, qualified players.</div></div><a class="qk-btn" href="#/leaders">Every leaderboard →</a></div>' +
        GI.card('', '', '<div id="ov-ld-seg"></div>' + GI.chartBox('ov-leaders', 380, 'Leaderboard')) + '</section>' +

      ((idx.recent || []).length ? '<section class="qk-section"><div class="qk-section-head"><div><h2>Last week</h2><div class="qk-sub">' + esc(GI.weekLabel(Math.max(1, W - 1), S)) + ' results.</div></div><a class="qk-btn" href="' + GI.weekHref(S, Math.max(1, W - 1)) + '">Week page →</a></div>' +
        '<div class="qk-auto gi-games" style="--min:240px">' + idx.recent.map(g => GI.gameCard(g, { compact: true, date: true })).join('') + '</div></section>' : '');

    // Super Bowl: model bars, market ticks
    const sbM = {};
    ((mkts && mkts.futures && mkts.futures.sb) || []).forEach(r => { if (r && r.team) sbM[r.team] = r.market; });
    const sb = Object.keys(po).map(t => ({ label: GI.teamName(t), p: po[t].p_sb || 0, market: isNum(sbM[t]) ? sbM[t] : null, colour: GI.teamColour(t), href: GI.teamHref(t) }))
      .sort((a, b) => b.p - a.p).slice(0, 12);
    GI.ch.probBars('ov-sb', sb, { keepHeight: true, labelWidth: 150, valName: 'Super Bowl probability' });
    if (gaps.length) GI.ch.dumbbell('ov-gaps', { rows: gaps.map(r => ({ label: r.label, a: r.a, b: r.b, href: r.href, sub: r.sub })), labelWidth: 150 });
    else GI.ch.none('ov-gaps', 'No market prices yet: markets are fetched with the hourly build.');

    // power map and trend
    const teams = Object.keys(ratings).filter(t => isNum((ratings[t].values || {}).off_rating));
    if (teams.length) {
      GI.ch.scatter('ov-power', { points: teams.map(t => ({ x: ratings[t].values.off_rating, y: ratings[t].values.def_rating, name: GI.teamName(t), label: t, color: GI.teamColour(t), href: GI.teamHref(t), size: 13 })),
        xName: 'Offence (pts/g)', yName: 'Defence (pts/g)', xFmt: v => GI.signed(v, 0), yFmt: v => GI.signed(v, 0), refX: 0, refY: 0, labelAll: true,
        quadrants: ['Defence carries', 'Contenders', 'Rebuilding', 'Offence carries'], label: 'Offence against defence rating' });
      const top = Object.keys(ratings).sort((a, b) => (ratings[b].values.rating || 0) - (ratings[a].values.rating || 0)).slice(0, 8);
      const weeks = {};
      top.forEach(t => (ratings[t].history || []).forEach(h => { weeks[h[0]] = 1; }));
      const wk = Object.keys(weeks).map(Number).sort((a, b) => a - b);
      GI.ch.line('ov-trend', { x: wk.map(w => 'W' + w), series: top.map(t => ({ name: t, color: GI.teamColour(t), data: wk.map(w => { const h = (ratings[t].history || []).find(r => r[0] === w); return h ? h[1] : null; }) })), yFmt: v => GI.signed(v, 1), xName: 'Week', yName: 'Rating (pts/g v average)', label: 'Team rating by week' });
    } else { GI.ch.none('ov-power', 'Ratings arrive with the first build.'); GI.ch.none('ov-trend', 'Ratings arrive with the first build.'); }

    // playoff race
    const plM = {};
    ((mkts && mkts.futures && mkts.futures.playoffs) || []).forEach(r => { if (r && r.team) plM[r.team] = r.market; });
    GI.CONFERENCES.forEach(c => {
      const list = Object.keys(po).filter(t => GI.teamInfo(t).conference === c).map(t => ({ label: GI.teamName(t), p: po[t].p_playoffs || 0, market: isNum(plM[t]) ? plM[t] : null, colour: GI.teamColour(t), href: GI.teamHref(t) }))
        .sort((a, b) => b.p - a.p);
      GI.ch.probBars('ov-' + c.toLowerCase(), list, { top: 16, keepHeight: true, labelWidth: 150, valName: 'Playoff probability' });
    });

    // leaders
    const L = idx.leaders || {};
    const keys = Object.keys(L).filter(k => (L[k] || []).length);
    const segHost = el.querySelector('#ov-ld-seg');
    if (keys.length && segHost) {
      const lab = k => { const m = leaderMeta(k, G); return (m.pre ? m.pre + ' · ' : '') + m.label; };
      segHost.innerHTML = '<div class="qk-chips scroll gi-ld-chips" role="group" aria-label="Leaderboard">' + keys.map((k, i) => '<button type="button" class="qk-chip" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(lab(k)) + '</button>').join('') + '</div>';
      const draw = k => {
        const m = leaderMeta(k, G);
        const list = (L[k] || []).slice(0, 10);
        GI.ch.bar('ov-leaders', { cats: list.map(r => GI.playerName(r[0]) + ' · ' + GI.teamAbbr(GI.player(r[0]).team)), series: [{ name: m.label, data: list.map(r => Number(r[1])) }], horizontal: true, labels: true,
          colors: list.map(r => GI.teamColour(GI.player(r[0]).team)), hrefs: list.map(r => GI.playerHref(r[0])), fmt: v => GI.fmtVal(v, m.fmt), labelWidth: 170, label: m.label + ' leaders' });
      };
      QK.chips(segHost.firstChild, v => draw(v[0]));
      draw(keys[0]);
    } else GI.ch.none('ov-leaders', 'Leaderboards arrive with the first build.');

    if (live.length) GI.liveRefresh([], 60000);
  });
});


})(window.GI);
