/* The Quant Footballer — competition tabs.
 *
 * Every renderer reads the open competition's payloads through FH.D() and writes
 * into the pane of its tab. RENDERERS maps tab names (from the manifest) to
 * renderers; the shared pieces (standings tables, ladders, the players
 * leaderboard) are exported for the pages module. */
(function (FH) {
'use strict';

const { C, PALETTE, ROUND_LABELS, esc, pct, num, signed, fmtNum, fmtMetric, fmtDate, fmtTime, localDay,
        D, comp, kind, cupKind, crest, teamLink, teamHref, playerLink, matchHref,
        tableHTML, setHTML, sortableIn, wireRowLinks, statTile, formChips, resultClass, riskClass,
        bandClass, bandColor, pctPill, probBar, statusChip, scoreText, plot, layout, renderShotMap, renderRadar, renderProbBars } = FH;

// ── overview ───────────────────────────────────────────────────────────────

function fixtureRow(f, opts) {
  const o = opts || {};
  const score = f.status === 'finished' || f.status === 'live'
    ? '<span class="score">' + esc(FH.scoreText(f)) + '</span>' : '<span class="score vs">v</span>';
  const xg = f.xg ? '<span class="xg-line">xG ' + num(f.xg[0], 2) + ' – ' + num(f.xg[1], 2) + '</span>' : '';
  const href = f.detail ? matchHref(f.id, f.comp) : null;      // f.comp set on site-wide lists
  return '<div class="fx-row' + (href ? ' has-link' : '') + '"' + (href ? ' data-href="' + esc(href) + '"' : '') + '>' +
    '<div class="fx-when">' + (o.showDate ? '<span>' + esc(fmtDate(f.date)) + '</span>' : '') + statusChip(f) + '</div>' +
    '<div class="fx-home">' + esc(f.home) + crest(f.home) + '</div>' +
    '<div class="fx-score">' + score + xg + '</div>' +
    '<div class="fx-away">' + crest(f.away) + esc(f.away) + '</div>' +
    '<div class="fx-extra">' + (f.status === 'finished' ? (f.detail ? '<a href="' + esc(href) + '">Analysis →</a>' : '') : probBar(f.model, { small: true })) + '</div>' +
    '</div>';
}

function leadersMini(players, key, label, fmt) {
  // A leaderboard of zeros (a one-match super cup's goals) lists only who actually scored.
  const rows = players.filter(p => p[key] !== undefined && p[key] !== null && (key !== 'rating' ? p[key] > 0 : p.qualified)).sort((a, b) => b[key] - a[key]).slice(0, 5);
  if (!rows.length) return '';
  return '<div class="mini-card"><div class="mini-head">' + esc(label) + '</div>' + rows.map((p, i) =>
    '<div class="mini-row"><span class="mini-rank">' + (i + 1) + '</span><span class="mini-name">' + playerLink(p.player_id, p.name) +
    '<span class="mini-sub">' + esc(p.team) + '</span></span><span class="mini-val">' + fmtMetric(p[key], fmt) + '</span></div>').join('') + '</div>';
}

function renderOverview() {
  const d = D();
  const c = comp() || {};
  const m = d.meta || {};
  const k = kind();
  const fx = (d.fixtures || {}).matches || [];
  const players = (d.players_live || {}).players || [];
  const probs = (d.probs || {}).teams || [];
  const pane = document.getElementById('tab-overview');

  // Header strip: leader, favourite, top scorer, progress, coverage.
  const t = d.table || {};
  const standings = t.standings || t.overall || (t.conferences ? [] : []);
  let leaderHtml = '—', leaderSub = '';
  if (k === 'liga' && d.zones) {
    const zs = d.zones.zones || {};
    const tops = Object.keys(zs).map(z => (zs[z].standings || [])[0]).filter(Boolean);
    leaderHtml = tops.map(r => teamLink(r.team)).join('<br>');
    leaderSub = tops.map(r => r.pts + ' pts').join(' · ');
  } else if (standings.length) {
    leaderHtml = teamLink(standings[0].team);
    leaderSub = standings[0].pts + ' pts from ' + standings[0].played;
  } else if (t.conferences) {
    const tops = Object.keys(t.conferences).map(g => (t.conferences[g] || [])[0]).filter(Boolean);
    leaderHtml = tops.slice(0, 4).map(r => teamLink(r.team)).join('<br>');
    leaderSub = 'top of each ' + ((t.group_label || 'group').toLowerCase());
  }
  const favKey = (k === 'conference' || k === 'playoff' || k === 'cup') ? 'p_cup' : 'p_title';
  const fav = probs.slice().sort((a, b) => (b[favKey] || b.p_title || 0) - (a[favKey] || a.p_title || 0))[0];
  const scorer = players.slice().sort((a, b) => (b.goals - a.goals) || (b.xg - a.xg))[0];
  // A competition between editions has a result, not a favourite: the final's winner.
  const last = FH.isLastEdition && FH.isLastEdition(c);
  const final = last ? fx.filter(f => f.round === 'final' && f.status === 'finished').slice(-1)[0] : null;
  const champ = last && c.winner && c.winner.team ? c.winner.team : final ? (final.winner || final.agg_winner || (final.hs > final.as ? final.home : final.as > final.hs ? final.away : null)) : (last && c.favourite && (c.complete || c.p_favourite >= 0.995) ? c.favourite : null);
  // A knockout cup has no table to lead: say which round it is in instead.
  let leadLabel = 'Leader';
  if (leaderHtml === '—' && fx.length) {
    const next = fx.find(f => f.status === 'scheduled' || f.status === 'live');
    const prev = fx.filter(f => f.status === 'finished').slice(-1)[0];
    const f0 = next || prev;
    if (f0) { leadLabel = 'Round'; leaderHtml = esc(FH.roundText(f0) || '—'); leaderSub = next ? 'next match ' + esc(fmtDate(next.date)) : 'latest round played'; }
  }
  // The final's score from the winner's side ("won 3–0 v Senegal"), whoever was at home.
  const finalLine = final && champ ? (() => {
    const home = final.home === champ, gf = home ? final.hs : final.as, ga = home ? final.as : final.hs;
    return ' · final ' + (gf > ga ? 'won ' : gf === ga ? 'drew ' : 'lost ') + gf + '–' + ga + ' v ' + esc(home ? final.away : final.home) + (gf === ga ? ', won on penalties' : '');
  })() : '';
  // A cup's games_played / games_total count its group or league phase only: count the fixture list.
  const real = fx.filter(f => f.status !== 'cancelled' && f.status !== 'postponed');
  const gp = k === 'cup' && real.length ? real.filter(f => f.status === 'finished').length : (m.games_played || 0);
  const gt = k === 'cup' && real.length ? real.length : (m.games_total || 0);
  const tiles = [
    statTile(leadLabel, leaderHtml, leaderSub),
    last ? statTile('Winner', champ ? teamLink(champ) : '—', champ ? 'last edition, ' + esc(FH.currentSeason(c).season) + finalLine : 'last edition') :
    statTile((c.favourite_label || 'Title') + ' favourite', fav ? teamLink(fav.team) : '—', fav ? '<strong>' + pct(fav[favKey] || fav.p_title) + '</strong> in ' + (m.n_sims || 0).toLocaleString('en-US') + ' simulations' : ''),
    statTile('Top scorer', scorer ? playerLink(scorer.player_id, scorer.name) : '—', scorer ? scorer.goals + ' goals · xG ' + num(scorer.xg, 2) + ' · ' + esc(scorer.team) : ''),
    statTile('Season', gp + ' <span class="kpi-dim">/ ' + gt + '</span>', 'matches played · ' + (m.detail_matches || 0) + ' with full match data')
  ];
  setHTML('ov-tiles', '<div class="kpi-grid">' + tiles.join('') + '</div>');
  setHTML('ov-note', '');     // the phase note is the page banner already

  // Latest results and next fixtures.
  const played = fx.filter(f => f.status === 'finished');
  const upcoming = fx.filter(f => f.status === 'scheduled' || f.status === 'live');
  setHTML('ov-results', played.length ? played.slice(-8).reverse().map(f => fixtureRow(f, { showDate: true })).join('') : '<div class="muted">No results yet.</div>');
  setHTML('ov-fixtures', upcoming.length ? upcoming.slice(0, 8).map(f => fixtureRow(f, { showDate: true })).join('') : '<div class="muted">No fixtures scheduled.</div>');
  wireRowLinks('ov-results');

  // The race.
  const race = probs.map(p => ({ label: p.team, p: p[favKey] !== undefined ? p[favKey] : (p.p_title || 0) })).sort((a, b) => b.p - a.p).slice(0, 8);
  if (last) setHTML('ov-race', '<div class="muted">This edition is over' + (champ ? ': ' + esc(champ) + ' won it' : '') + '. The next edition is not in the data yet, so there is nothing to simulate.</div>');
  else if (race.length && race[0].p > 0) renderProbBars('ov-race', race, 'Probability of winning ' + (c.favourite_label === 'Title' ? 'the title' : (c.favourite_label || 'the competition')));
  else setHTML('ov-race', '<div class="muted">No simulation for this competition yet.</div>');

  // Leaders.
  const minis = [leadersMini(players, 'goals', 'Goals', 'int'), leadersMini(players, 'assists', 'Assists', 'int'),
                 leadersMini(players, 'xg', 'Expected goals', '2'), leadersMini(players, 'rating', 'Rating', '2')].filter(Boolean);
  setHTML('ov-leaders', minis.length ? '<div class="mini-grid">' + minis.join('') + '</div>' : '<div class="muted">No player data yet.</div>');
  if (pane) pane.dataset.rendered = '1';
}

// ── fixtures & results ─────────────────────────────────────────────────────

function renderFixtures() {
  const d = D();
  const all = (d.fixtures || {}).matches || [];
  if (!all.length) { setHTML('fx-list', '<div class="muted">No fixtures yet.</div>'); return; }
  const stageSel = document.getElementById('fx-stage'), teamSel = document.getElementById('fx-team'), statusSel = document.getElementById('fx-status');
  const stages = Array.from(new Set(all.map(f => f.stage || 'league')));
  const rounds = Array.from(new Set(all.map(f => String(f.round === null || f.round === undefined ? '' : f.round)).filter(Boolean)));
  // Rounds in the order they were played (a cup's numbered early rounds, then its knockout rounds).
  const firstDate = {};
  all.forEach(f => { const r = String(f.round === null || f.round === undefined ? '' : f.round); const d = String(f.date || '9999'); if (!(r in firstDate) || d < firstDate[r]) firstDate[r] = d; });
  rounds.sort((a, b) => firstDate[a].localeCompare(firstDate[b]) || String(a).localeCompare(String(b)));
  stageSel.innerHTML = '<option value="">All stages</option>' + stages.map(s => '<option value="' + esc(s) + '">' + esc(FH.stageLabel(s)) + '</option>').join('') +
    (rounds.length > 1 ? '<optgroup label="Rounds">' + rounds.map(r => { const f0 = all.find(f => String(f.round) === r) || { round: r }; return '<option value="round:' + esc(r) + '">' + esc(FH.roundText(f0)) + '</option>'; }).join('') + '</optgroup>' : '');
  const teams = Array.from(new Set(all.map(f => f.home).concat(all.map(f => f.away)))).sort((a, b) => a.localeCompare(b));
  teamSel.innerHTML = '<option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('');
  // Default to the week around today when the season is under way.
  const today = localDay(new Date().toISOString());
  const hasUpcoming = all.some(f => f.status !== 'finished');
  statusSel.value = hasUpcoming ? 'upcoming' : 'all';

  function draw() {
    const stage = stageSel.value, team = teamSel.value, status = statusSel.value;
    let rows = all.filter(f => {
      if (stage && stage.indexOf('round:') === 0 && String(f.round) !== stage.slice(6)) return false;
      if (stage && stage.indexOf('round:') !== 0 && (f.stage || 'league') !== stage) return false;
      if (team && f.home !== team && f.away !== team) return false;
      if (status === 'played' && f.status !== 'finished') return false;
      if (status === 'upcoming' && f.status === 'finished') return false;
      return true;
    });
    if (status === 'played') rows = rows.slice().reverse();
    if (status === 'upcoming') rows = rows.slice(0, 120);
    if (status === 'played') rows = rows.slice(0, 200);
    setHTML('fx-count', rows.length + ' of ' + all.length + ' matches');
    if (!rows.length) { setHTML('fx-list', '<div class="muted">No matches match the filters.</div>'); return; }
    let html = '', lastDay = null;
    rows.forEach(f => {
      const day = localDay(f.date) || 'TBD';
      if (day !== lastDay) {
        html += '<div class="fx-day' + (day === today ? ' today' : '') + '">' + esc(fmtDate(f.date, true)) + (day === today ? ' <span class="chip st-live">today</span>' : '') + '</div>';
        lastDay = day;
      }
      html += fixtureDetailRow(f);
    });
    setHTML('fx-list', html);
    wireRowLinks('fx-list');
  }
  stageSel.onchange = draw; teamSel.onchange = draw; statusSel.onchange = draw;
  draw();
}

/* A fixture line with the model's full line for matches still to play. */
function fixtureDetailRow(f) {
  const href = f.detail ? matchHref(f.id) : null;
  const m = f.model;
  let extra = '';
  if (f.status === 'finished') {
    extra = (f.xg ? '<span class="xg-line">xG ' + num(f.xg[0], 2) + ' – ' + num(f.xg[1], 2) + '</span>' : '') +
            (f.detail ? '<a class="fx-link" href="' + esc(href) + '">Analysis →</a>' : '<span class="muted-inline">no match data</span>');
  } else if (m) {
    extra = '<div class="fx-model">' + probBar(m) +
      '<div class="fx-model-line"><span title="Fair decimal odds, no margin">Fair ' + esc(m.fair.map(o => o === null ? '—' : o.toFixed(2)).join(' / ')) + '</span>' +
      '<span>xG ' + num(m.lh, 2) + ' – ' + num(m.la, 2) + '</span><span>Likely ' + esc(m.score) + ' (' + pct(m.p_score, 0) + ')</span>' +
      '<span>O2.5 ' + pct(m.o25, 0) + '</span><span>BTTS ' + pct(m.btts, 0) + '</span></div></div>';
  } else {
    extra = '<span class="muted-inline">no model line</span>';
  }
  const roundTxt = FH.roundText(f, null, true);
  return '<div class="fx-row detail' + (href ? ' has-link' : '') + '"' + (href ? ' data-href="' + esc(href) + '"' : '') + '>' +
    '<div class="fx-when">' + statusChip(f) + '<span class="fx-round">' + esc(roundTxt) + (f.group ? ' · ' + esc(f.group) : '') + '</span></div>' +
    '<div class="fx-home">' + teamLink(f.home).replace('<a class="team-link"', '<a class="team-link rev"') + '</div>' +
    '<div class="fx-score"><span class="score' + (f.status === 'finished' || f.status === 'live' ? '' : ' vs') + '">' + esc(scoreText(f)) + '</span></div>' +
    '<div class="fx-away">' + teamLink(f.away) + '</div>' +
    '<div class="fx-extra">' + extra + '</div></div>';
}

// ── league table ───────────────────────────────────────────────────────────

function standingsTable(rows, bands, opts) {
  const o = opts || {};
  const upBands = (bands || []).filter(b => b.kind === 'up').slice(0, o.maxUp === undefined ? 2 : o.maxUp);
  const downBands = (bands || []).filter(b => b.kind === 'down');
  const cols = [
    { label: '#', sortable: false }, { label: 'Club' }, { label: 'P', align: 'right' },
    { label: 'W', align: 'right' }, { label: 'D', align: 'right' }, { label: 'L', align: 'right' },
    { label: 'GF', align: 'right' }, { label: 'GA', align: 'right' },
    { label: 'GD', align: 'right' }, { label: 'Pts', align: 'right' },
    { label: 'Proj.', align: 'right', title: 'Expected final points' },
    { label: 'Range', align: 'right', title: '5th–95th percentile of final points', sortable: false }
  ];
  if (o.plain) { cols.splice(10, 2); }          // no projection columns for an unsimulated competition
  if (o.titleLabel !== null && !o.plain) cols.push({ label: o.titleLabel || 'Title', align: 'right' });
  (o.extra || []).forEach(x => cols.push({ label: x.label, align: 'right', title: x.title }));
  upBands.forEach(b => cols.push({ label: b.label, align: 'right' }));
  if (downBands.length) cols.push({ label: downBands.length > 1 ? 'Drop' : downBands[0].label, align: 'right', title: downBands.map(b => b.label).join(' + ') });

  const trs = rows.map(r => {
    const cells = [
      { v: r.pos, cls: 'pos-cell ' + bandClass(bands, r.pos) },
      { v: r.team, html: teamLink(r.team) },
      { v: r.played, align: 'right' }, { v: r.w, align: 'right' }, { v: r.d, align: 'right' }, { v: r.l, align: 'right' },
      { v: r.gf, align: 'right' }, { v: r.ga, align: 'right' },
      { v: r.gd, html: (r.gd > 0 ? '+' : '') + r.gd, align: 'right' },
      { v: r.pts, html: '<strong>' + r.pts + '</strong>', align: 'right' }
    ];
    if (!o.plain) cells.push(
      { v: r.exp_pts, html: '<span class="ko-prob">' + num(r.exp_pts) + '</span>', align: 'right' },
      { v: r.p50, html: '<span class="ko-prob">' + num(r.p05, 0) + '–' + num(r.p95, 0) + '</span>', align: 'right' }
    );
    if (o.titleLabel !== null && !o.plain) cells.push({ v: r.p_title, html: '<strong>' + pct(r.p_title) + '</strong>', align: 'right' });
    (o.extra || []).forEach(x => cells.push({ v: r[x.key] || 0, html: pct(r[x.key]), align: 'right' }));
    upBands.forEach(b => cells.push({ v: (r.bands || {})[b.key] || 0, html: pct((r.bands || {})[b.key]), align: 'right' }));
    if (downBands.length) {
      const p = downBands.reduce((s, b) => s + ((r.bands || {})[b.key] || 0), 0);
      cells.push({ v: p, html: pct(p), cls: riskClass(p), align: 'right' });
    }
    return { cells: cells };
  });
  return tableHTML(cols, trs, { sticky: true });
}

function legendHTML(bands) {
  return (bands || []).map(b =>
    '<span style="--c:' + bandColor(bands, b.key) + '">' + esc(b.label) + ' (' +
    (b.first === b.last ? b.first : b.first + '–' + b.last) + ')</span>').join('');
}

function renderTable() {
  const t = D().table;
  if (!t || (!t.standings && !t.conferences) || ((t.standings || []).length === 0 && !t.conferences)) { setHTML('table-grid', '<div class="muted">No table for this competition.</div>'); setHTML('position-heatmap', ''); setHTML('upcoming-fixtures', ''); return; }
  setHTML('table-sub', esc(t.season || '') + ' · ' + t.games_played + '/' + t.total_games + ' matches' +
    (t.h2h_tiebreak ? ' · ties on points are broken by goal difference here; the league uses head-to-head' : ''));
  setHTML('band-legend', legendHTML(t.bands));

  if (t.conferences) {
    const isCup = kind() === 'cup';
    const label = t.group_label || (isCup ? 'Group' : 'Conference');
    let html = '<div class="zone-grid">';
    Object.keys(t.conferences).forEach(conf => {
      html += '<div class="group-card"><div class="group-card-header">' + (isCup ? label + ' ' + esc(conf) : esc(conf) + ' Conference') + '</div>' +
        standingsTable(t.conferences[conf], t.bands, { titleLabel: null, maxUp: 2, plain: !!t.unsimulated }) + '</div>';
    });
    html += '</div>';
    if ((t.overall || []).length) {
      html += '<div class="group-card" style="margin-top:16px"><div class="group-card-header">' + esc(t.overall_label || 'Overall') + '</div>' +
        standingsTable(t.overall, [], { titleLabel: 'Shield', maxUp: 0 }) + '</div>';
    }
    setHTML('table-grid', html);
  } else if (t.split) {
    setHTML('table-grid', standingsTable(t.standings, t.bands, { titleLabel: 'Title', extra: [
      { label: 'Top ' + t.split.top, key: 'p_top_group', title: 'Reaches the championship group' }
    ] }));
  } else {
    setHTML('table-grid', standingsTable(t.standings, t.bands, { titleLabel: kind() === 'cup' ? 'Winner' : 'Title', plain: !!t.unsimulated }));
  }
  document.querySelectorAll('#table-grid table').forEach(FH.makeSortable);

  const rows = t.standings || t.overall || [];
  const teams = rows.map(r => r.team);
  const z = rows.map(r => (t.split ? (r.p_final_pos || r.p_pos) : r.p_pos) || []);
  if (t.unsimulated) {
    setHTML('position-heatmap', '<div class="muted">Not simulated: national-team competitions show the tables as played.</div>');
  } else if (t.conferences && kind() === 'cup' && cupKind() === 'groups') {
    setHTML('position-heatmap', '<div class="muted">Group tables above carry the finishing odds per group.</div>');
  } else if (z.length && z[0].length && !t.conferences) {
    const shapes = [];
    (t.bands || []).forEach(b => {
      shapes.push({ type: 'line', x0: b.last + 0.5, x1: b.last + 0.5, y0: -0.5, y1: teams.length - 0.5,
                    line: { color: bandColor(t.bands, b.key), width: 1, dash: 'dash' } });
    });
    plot('position-heatmap', [{
      z: z, x: z[0].map((_, i) => i + 1), y: teams, type: 'heatmap', colorscale: 'YlGnBu',
      reversescale: true, showscale: false, hovertemplate: '%{y} — position %{x}: %{z:.1%}<extra></extra>'
    }], layout({
      margin: { l: 150, r: 20, t: 20, b: 40 },
      xaxis: { title: t.split ? 'Final position after the split' : 'Final position' },
      yaxis: { automargin: true, autorange: 'reversed' },
      shapes: shapes
    }));
  } else if (t.conferences) {
    const traces = [];
    const names = Object.keys(t.conferences).filter(n => (t.conferences[n] || []).length);
    names.forEach((conf, i) => {
      const cr = t.conferences[conf];
      traces.push({
        z: cr.map(r => r.p_pos || []), x: (cr[0].p_pos || []).map((_, k) => k + 1), y: cr.map(r => r.team),
        type: 'heatmap', colorscale: 'YlGnBu', reversescale: true, showscale: false,
        xaxis: 'x' + (i ? i + 1 : ''), yaxis: 'y' + (i ? i + 1 : ''),
        hovertemplate: '%{y} — position %{x}: %{z:.1%}<extra>' + esc(conf) + '</extra>'
      });
    });
    const lay = layout({ grid: { rows: 1, columns: names.length, pattern: 'independent' }, margin: { l: 140, r: 20, t: 20, b: 40 },
      xaxis: { title: names[0] }, yaxis: { automargin: true, autorange: 'reversed' } });
    names.slice(1).forEach((n, i) => { lay['xaxis' + (i + 2)] = Object.assign({}, FH.DARK_LAYOUT.xaxis, { title: n }); lay['yaxis' + (i + 2)] = Object.assign({}, FH.DARK_LAYOUT.yaxis, { automargin: true, autorange: 'reversed' }); });
    plot('position-heatmap', traces, lay);
  } else {
    setHTML('position-heatmap', '<div class="muted">No distribution data.</div>');
  }
  upcomingTable('upcoming-fixtures', (t.fixtures || []).filter(f => !f.done));
}

function upcomingTable(elId, fixtures) {
  const upcoming = fixtures.slice().sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
  const rows = upcoming.slice(0, 30).map(f => ({ cells: [
    { v: f.date || '', html: esc(f.date || '—') },
    { v: f.round || '', align: 'right' },
    { v: f.home, html: teamLink(f.home) },
    { v: f.away, html: teamLink(f.away) }
  ] }));
  setHTML(elId, rows.length
    ? tableHTML([{ label: 'Date' }, { label: 'Round', align: 'right' }, { label: 'Home' }, { label: 'Away' }], rows)
    : '<div class="muted">No matches left to play.</div>');
}

// ── Argentina: zones, anual, relegation ────────────────────────────────────

function renderZones() {
  const z = D().zones;
  if (!z) { setHTML('zone-grid', '<div class="muted">No zone tables yet.</div>'); return; }
  const cut = z.qualifiers_per_zone || 8;
  setHTML('zones-sub', z.tournament === 'clausura' ? 'Torneo Clausura' : 'Torneo Apertura');
  let html = '';
  ['A', 'B'].forEach(key => {
    const zone = z.zones[key];
    if (!zone) return;
    const rows = zone.standings.map(s => ({
      _class: s.pos === cut ? 'cutline' : '',
      cells: [
        { v: s.pos, cls: 'pos-cell' },
        { v: s.team, html: teamLink(s.team) },
        { v: s.played, align: 'right' },
        { v: s.gd, html: (s.gd > 0 ? '+' : '') + s.gd, align: 'right' },
        { v: s.pts, html: '<strong>' + s.pts + '</strong>', align: 'right' },
        { v: s.exp_pts, align: 'right', html: '<span class="ko-prob">' + num(s.exp_pts) + '</span>' },
        { v: s.p_top8, html: pct(s.p_top8), align: 'right' }
      ]
    }));
    html += '<div class="group-card"><div class="group-card-header">Zona ' + key +
            ' <span class="card-sub">' + zone.games_played + '/' + zone.total_games + ' matches</span></div>' +
            tableHTML([
              { label: '#', sortable: false }, { label: 'Club' }, { label: 'P', align: 'right' },
              { label: 'GD', align: 'right' }, { label: 'Pts', align: 'right' },
              { label: 'Proj.', align: 'right' }, { label: 'Top 8', align: 'right' }
            ], rows) + '</div>';
  });
  setHTML('zone-grid', html);
  document.querySelectorAll('#zone-grid table').forEach(FH.makeSortable);
  const upcoming = [];
  ['A', 'B'].forEach(key => { const zone = z.zones[key]; if (zone) zone.fixtures.filter(f => !f.done).forEach(f => upcoming.push(f)); });
  upcomingTable('zone-upcoming', upcoming);
}

function renderAnual() {
  const a = D().anual;
  if (!a) { setHTML('anual-table', '<div class="muted">No Tabla Anual yet.</div>'); return; }
  const lib = a.berths.libertadores, sud = a.berths.sudamericana;
  setHTML('anual-sub', lib + ' Libertadores berths, ' + sud + ' Sudamericana, and last place goes down.');
  setHTML('anual-note', '<p>' + esc(a.berths.note_en || a.berths.note || '') + '</p>');
  const rows = a.rows.map(r => {
    let cls = '';
    if (r.pos <= lib) cls = 'band-lib'; else if (r.pos <= lib + sud) cls = 'band-sud'; else if (r.pos === a.rows.length) cls = 'band-rel';
    return { cells: [
      { v: r.pos, cls: 'pos-cell ' + cls },
      { v: r.team, html: teamLink(r.team) },
      { v: r.played, align: 'right' },
      { v: r.pts_now, html: '<strong>' + r.pts_now + '</strong>', align: 'right' },
      { v: r.exp_pts, html: num(r.exp_pts), align: 'right' },
      { v: r.p_champion, html: pct(r.p_champion), align: 'right' },
      { v: r.p_libertadores, html: pct(r.p_libertadores), align: 'right' },
      { v: r.p_sudamericana, html: pct(r.p_sudamericana), align: 'right' }
    ] };
  });
  setHTML('anual-table', tableHTML([
    { label: '#', sortable: false }, { label: 'Club' }, { label: 'P', align: 'right' },
    { label: 'Pts', align: 'right' }, { label: 'Proj.', align: 'right' },
    { label: 'Champion', align: 'right' }, { label: 'Libertadores', align: 'right' }, { label: 'Sudamericana', align: 'right' }
  ], rows));
  sortableIn('anual-table');

  const teams = a.rows.map(r => r.team);
  const z = a.rows.map(r => r.p_pos || []);
  if (z.length && z[0].length) {
    plot('anual-heatmap', [{
      z: z, x: z[0].map((_, i) => i + 1), y: teams, type: 'heatmap', colorscale: 'YlGnBu',
      reversescale: true, showscale: false, hovertemplate: '%{y} — position %{x}: %{z:.1%}<extra></extra>'
    }], layout({
      margin: { l: 150, r: 20, t: 20, b: 40 }, xaxis: { title: 'Final position' },
      yaxis: { automargin: true, autorange: 'reversed' },
      shapes: [lib, lib + sud].map(x => ({ type: 'line', x0: x + 0.5, x1: x + 0.5, y0: -0.5, y1: teams.length - 0.5, line: { color: C.green, width: 1, dash: 'dash' } }))
    }));
  } else {
    setHTML('anual-heatmap', '<div class="muted">No distribution data.</div>');
  }
}

function renderRelegation() {
  const r = D().relegation;
  if (!r) { setHTML('releg-table', '<div class="muted">No relegation data yet.</div>'); return; }
  setHTML('releg-sub', r.rules.places + ' clubs go down.');
  setHTML('releg-explainer', '<p>' + esc(r.rules.note_en || r.rules.note) + '</p>' +
    '<p><span class="rel-route rel-route-prom">promedio</span> <span class="rel-route rel-route-anual">tabla anual</span></p>');
  const lo = Math.min.apply(null, r.rows.map(x => x.p05).concat([0.5]));
  const hi = Math.max.apply(null, r.rows.map(x => x.p95).concat([2.5]));
  const span = (hi - lo) || 1;
  const rows = r.rows.map(x => {
    const left = ((x.p05 - lo) / span) * 100, width = Math.max(((x.p95 - x.p05) / span) * 100, 1.5), mid = ((x.p50 - lo) / span) * 100;
    const band = '<div class="rel-band"><div class="rel-band-fill" style="left:' + left.toFixed(1) + '%;width:' + width.toFixed(1) + '%"></div>' +
      '<div class="rel-band-median" style="left:' + mid.toFixed(1) + '%"></div></div>';
    return { cells: [
      { v: x.pos, cls: 'pos-cell' },
      { v: x.team, html: teamLink(x.team) },
      { v: x.promedio_now, html: num(x.promedio_now, 3), align: 'right' },
      { v: x.p50, html: band, align: 'right' },
      { v: x.p_promedio, html: pct(x.p_promedio), align: 'right' },
      { v: x.p_anual, html: pct(x.p_anual), align: 'right' },
      { v: x.p_any, html: '<strong>' + pct(x.p_any) + '</strong>', cls: riskClass(x.p_any), align: 'right' }
    ] };
  });
  setHTML('releg-table', tableHTML([
    { label: '#', sortable: false }, { label: 'Club' }, { label: 'Promedio', align: 'right' },
    { label: 'Projection (p05–p95)', align: 'right', sortable: false },
    { label: 'Via promedio', align: 'right' }, { label: 'Via anual', align: 'right' }, { label: 'Relegated', align: 'right' }
  ], rows));
  sortableIn('releg-table');
  const risky = r.rows.filter(x => x.p_any > 0.001).sort((a, b) => a.p_any - b.p_any).slice(-14);
  if (risky.length) {
    plot('releg-chart', [
      { type: 'bar', orientation: 'h', name: 'Promedio', y: risky.map(x => x.team), x: risky.map(x => x.p_promedio), marker: { color: C.orange }, hovertemplate: '%{y}: %{x:.1%} via promedio<extra></extra>' },
      { type: 'bar', orientation: 'h', name: 'Tabla Anual', y: risky.map(x => x.team), x: risky.map(x => x.p_anual), marker: { color: C.purple }, hovertemplate: '%{y}: %{x:.1%} via the annual table<extra></extra>' }
    ], layout({
      barmode: 'stack', showlegend: true, legend: { orientation: 'h', y: 1.08, font: { color: C.text2 } },
      margin: { l: 160, r: 30, t: 30, b: 40 },
      xaxis: { tickformat: '.0%', title: 'Probability of relegation' }, yaxis: { automargin: true }
    }));
  } else {
    setHTML('releg-chart', '<div class="muted">No club at appreciable risk.</div>');
  }
}

// ── playoffs and knockout brackets ─────────────────────────────────────────

function renderBracket() {
  if (kind() === 'conference' || kind() === 'playoff' || kind() === 'cup') return renderLadder();
  const b = D().bracket;
  if (!b || !(b.rounds || []).length) { setHTML('bracket-body', '<div class="muted">No bracket yet.</div>'); return; }
  setHTML('bracket-sub', 'Round of 16 to the final, all single-leg. A1–B8, A2–B7 and so on.');
  setHTML('bracket-note', '');
  const perRound = { r16: 8, qf: 4, sf: 2, final: 1 };
  let html = '<div class="bracket-grid">';
  b.rounds.forEach(round => {
    html += '<div><div class="bracket-col-title">' + esc(ROUND_LABELS[round] || round) + '</div>';
    const n = perRound[round] || 1;
    for (let slot = 0; slot < n; slot++) {
      const forced = b.results[round + ':' + slot];
      if (round === 'r16') {
        const a = b.seeds[slot * 2], c = b.seeds[slot * 2 + 1];
        html += '<div class="ko-card">' + seedLine(a, forced) + seedLine(c, forced) + '</div>';
      } else {
        html += '<div class="ko-card">' + (forced
          ? '<div class="ko-line ko-winner"><span>' + crest(forced) + esc(forced) + '</span></div>'
          : '<div class="ko-line"><span style="color:var(--text3)">To be decided</span></div>') + '</div>';
      }
    }
    html += '</div>';
  });
  setHTML('bracket-body', html + '</div>');
  function seedLine(seed, forced) {
    if (!seed) return '';
    const team = seed.likely;
    return '<div class="ko-line' + (forced && forced === team ? ' ko-winner' : '') + '">' +
      '<span><span class="ko-seed">' + esc(seed.label) + '</span>' +
      (team ? crest(team) + esc(team) : '<span style="color:var(--text3)">—</span>') + '</span>' +
      '<span class="ko-prob">' + (team ? pct((b.reach[team] || {}).r16) : '') + '</span></div>';
  }
  const teams = Object.keys(b.reach).sort((x, y) => (b.p_title[y] || 0) - (b.p_title[x] || 0));
  setHTML('reach-table', tableHTML([
    { label: 'Club' }, { label: 'Round of 16', align: 'right' }, { label: 'Quarter', align: 'right' },
    { label: 'Semi', align: 'right' }, { label: 'Final', align: 'right' }, { label: 'Champion', align: 'right' }
  ], teams.map(t => ({ cells: [
    { v: t, html: teamLink(t) },
    { v: b.reach[t].r16, html: pct(b.reach[t].r16), align: 'right' },
    { v: b.reach[t].qf, html: pct(b.reach[t].qf), align: 'right' },
    { v: b.reach[t].sf, html: pct(b.reach[t].sf), align: 'right' },
    { v: b.reach[t].final, html: pct(b.reach[t].final), align: 'right' },
    { v: b.p_title[t] || 0, html: '<strong>' + pct(b.p_title[t]) + '</strong>', align: 'right' }
  ] }))));
  sortableIn('reach-table');
}

function renderLadder() {
  const b = D().bracket;
  if (!b || !b.rounds || !b.rounds.length) { setHTML('bracket-body', '<div class="muted">' + esc((b || {}).note || 'No knockout picture yet.') + '</div>'); setHTML('reach-table', ''); return; }
  const f = b.format || {};
  const k = kind();
  if (k === 'conference') {
    setHTML('bracket-sub', (b.confirmed ? 'Seeds confirmed' : 'Seeds as the table stands') + ' · top ' + f.direct_per_conference +
      ' qualify directly, seeds ' + (f.wildcard_seeds || []).join(' and ') + ' play a wild card');
  } else if (k === 'playoff') {
    setHTML('bracket-sub', (b.confirmed ? 'Seeds confirmed' : 'Seeds as the table stands') + ' · top ' + f.direct + ' qualify directly, ' +
      (f.play_in || []).join('–') + ' play the play-in');
  } else {
    setHTML('bracket-sub', b.confirmed ? 'League phase complete' : 'Bracket as the tables stand');
  }
  setHTML('bracket-note', '<p>' + esc(b.note || '') + '</p>');
  const labels = Object.assign({}, ROUND_LABELS, b.round_labels || {});
  let html = '';
  const known = b.known || {};
  const knownRounds = Object.keys(known).filter(r => (known[r] || []).length);
  if (knownRounds.length) {
    html += '<div class="bracket-grid" style="grid-template-columns:repeat(' + Math.min(knownRounds.length, 4) + ',1fr)">';
    knownRounds.forEach(r => {
      html += '<div><div class="bracket-col-title">' + esc(labels[r] || r) + '</div>';
      const nxt = nextRound(b.rounds, r);
      // The chance of going through: reaching the next round, or winning it all from the final.
      const through = t => nxt === 'win' ? (b.p_cup || {})[t] : ((b.reach || {})[t] || {})[nxt];
      known[r].forEach(pair => {
        const w = (b.forced || {})[[pair[0], pair[1]].sort().join(' v ')];
        html += '<div class="ko-card">' +
          '<div class="ko-line' + (w === pair[0] ? ' ko-winner' : '') + '"><span>' + teamLink(pair[0]) + '</span><span class="ko-prob">' + pct(through(pair[0])) + '</span></div>' +
          '<div class="ko-line' + (w === pair[1] ? ' ko-winner' : '') + '"><span>' + teamLink(pair[1]) + '</span><span class="ko-prob">' + pct(through(pair[1])) + '</span></div>' +
          '</div>';
      });
      html += '</div>';
    });
    html += '</div>';
  }
  html += '<div class="bracket-grid cols-2">';
  Object.keys(b.seeds || {}).forEach(conf => {
    const rows = b.seeds[conf].map(s => ({
      _class: s.direct ? 'seed-direct' : 'seed-wild',
      cells: [
        { v: s.seed, cls: 'pos-cell' },
        { v: s.team || '', html: s.team ? teamLink(s.team) : '<span style="color:var(--text3)">—</span>' },
        { v: s.team ? (b.p_playoffs[s.team] || 0) : 0, html: s.team ? pct(b.p_playoffs[s.team]) : '', align: 'right' },
        { v: s.team ? (b.p_cup[s.team] || 0) : 0, html: s.team ? pct(b.p_cup[s.team]) : '', align: 'right' }
      ]
    }));
    html += '<div class="group-card"><div class="group-card-header">' + esc(conf) + (k === 'conference' ? ' Conference' : '') + '</div>' +
      tableHTML([{ label: 'Seed', sortable: false }, { label: 'Club', sortable: false },
                 { label: k === 'playoff' ? 'Liguilla' : 'Playoffs', align: 'right', sortable: false }, { label: 'Winner', align: 'right', sortable: false }], rows) + '</div>';
  });
  setHTML('bracket-body', html + '</div>');

  const cupLabel = k === 'conference' ? 'MLS Cup' : k === 'playoff' ? 'Champion' : 'Winner';
  const teams = Object.keys(b.reach || {}).sort((x, y) => (b.p_cup[y] || 0) - (b.p_cup[x] || 0));
  const confOf = t => (((D().teams || {}).teams || {})[t] || {}).conference || '';
  const hasConf = teams.some(t => confOf(t));
  const cols = [{ label: 'Club' }];
  if (hasConf) cols.push({ label: k === 'cup' ? ((D().table || {}).group_label || 'Group') : 'Conf.', align: 'center' });
  if (k === 'conference' || k === 'playoff') cols.push({ label: k === 'playoff' ? 'Liguilla' : 'Playoffs', align: 'right' });
  b.rounds.forEach(r => cols.push({ label: labels[r] || r, align: 'right' }));
  cols.push({ label: cupLabel, align: 'right' });
  setHTML('reach-table', tableHTML(cols, teams.map(t => {
    const r = b.reach[t] || {};
    const cells = [{ v: t, html: teamLink(t) }];
    if (hasConf) cells.push({ v: confOf(t), html: esc(String(confOf(t)).slice(0, 4)), align: 'center' });
    if (k === 'conference' || k === 'playoff') cells.push({ v: (b.p_playoffs || {})[t] || 0, html: pct((b.p_playoffs || {})[t]), align: 'right' });
    b.rounds.forEach(rd => cells.push({ v: r[rd] || 0, html: pct(r[rd]), align: 'right' }));
    cells.push({ v: b.p_cup[t] || 0, html: '<strong>' + pct(b.p_cup[t]) + '</strong>', align: 'right' });
    return { cells: cells };
  }), { sticky: true }));
  sortableIn('reach-table');
}

function nextRound(rounds, r) {
  const i = rounds.indexOf(r);
  return i >= 0 && i + 1 < rounds.length ? rounds[i + 1] : 'win';
}

// ── probabilities ──────────────────────────────────────────────────────────

function renderProbs() {
  const p = D().probs || { teams: [] };
  const k = kind();
  if (!(p.teams || []).length) { setHTML('probs-table', '<div class="muted">No simulation for this competition yet.</div>'); return; }
  let cols, rows;
  if (k === 'liga') {
    cols = [{ label: 'Club' }, { label: 'Zone', align: 'center' }, { label: 'Proj. pts', align: 'right' },
            { label: 'Top 8', align: 'right' }, { label: 'Champion', align: 'right' }, { label: 'Anual', align: 'right' },
            { label: 'Libertadores', align: 'right' }, { label: 'Sudamericana', align: 'right' }, { label: 'Relegation', align: 'right' }];
    rows = p.teams.map(t => ({ cells: [
      { v: t.team, html: teamLink(t.team) }, { v: t.zone || '', align: 'center' },
      { v: t.exp_pts, html: num(t.exp_pts), align: 'right' }, { v: t.p_top8, html: pct(t.p_top8), align: 'right' },
      { v: t.p_title, html: '<strong>' + pct(t.p_title) + '</strong>', align: 'right' }, { v: t.p_anual, html: pct(t.p_anual), align: 'right' },
      { v: t.p_libertadores, html: pct(t.p_libertadores), align: 'right' }, { v: t.p_sudamericana, html: pct(t.p_sudamericana), align: 'right' },
      { v: t.p_relegation, html: pct(t.p_relegation), cls: riskClass(t.p_relegation), align: 'right' }
    ] }));
  } else if (k === 'playoff' || k === 'cup') {
    const bands = p.bands || [];
    const isCup = k === 'cup';
    const showPts = !isCup || ['swiss', 'groups', 'regional_swiss'].indexOf(cupKind()) >= 0;
    cols = [{ label: 'Club' }];
    if (isCup && p.teams.some(t => t.conference)) cols.push({ label: (D().table || {}).group_label || 'Group', align: 'center' });
    if (showPts) cols.push({ label: 'Proj. pts', align: 'right' });
    bands.forEach(b => cols.push({ label: b.label, align: 'right' }));
    cols.push({ label: isCup ? 'Reaches final' : 'Final', align: 'right' }, { label: isCup ? 'Winner' : 'Champion', align: 'right' });
    rows = p.teams.map(t => {
      const cells = [{ v: t.team, html: teamLink(t.team) }];
      if (isCup && p.teams.some(x => x.conference)) cells.push({ v: t.conference || '', align: 'center' });
      if (showPts) cells.push({ v: t.exp_pts, html: num(t.exp_pts), align: 'right' });
      bands.forEach(b => { const v = (t.bands || {})[b.key] || 0; cells.push({ v: v, html: pct(v), cls: b.kind === 'down' ? riskClass(v) : '', align: 'right' }); });
      cells.push({ v: t.p_conference, html: pct(t.p_conference), align: 'right' }, { v: t.p_cup, html: '<strong>' + pct(t.p_cup) + '</strong>', align: 'right' });
      return { cells: cells };
    });
  } else if (k === 'conference') {
    cols = [{ label: 'Club' }, { label: 'Conf.', align: 'center' }, { label: 'Proj. pts', align: 'right' },
            { label: 'Shield', align: 'right', title: "Supporters' Shield: best regular-season record" },
            { label: 'Playoffs', align: 'right' }, { label: 'Conf. title', align: 'right' }, { label: 'MLS Cup', align: 'right' }];
    rows = p.teams.map(t => ({ cells: [
      { v: t.team, html: teamLink(t.team) }, { v: t.conference || '', html: esc(String(t.conference || '').slice(0, 4)), align: 'center' },
      { v: t.exp_pts, html: num(t.exp_pts), align: 'right' }, { v: t.p_title, html: pct(t.p_title), align: 'right' },
      { v: t.p_playoffs, html: pct(t.p_playoffs), align: 'right' }, { v: t.p_conference, html: pct(t.p_conference), align: 'right' },
      { v: t.p_cup, html: '<strong>' + pct(t.p_cup) + '</strong>', align: 'right' }
    ] }));
  } else {
    const bands = p.bands || [];
    cols = [{ label: 'Club' }, { label: 'Proj. pts', align: 'right' }, { label: 'Title', align: 'right' }];
    bands.forEach(b => cols.push({ label: b.label, align: 'right' }));
    rows = p.teams.map(t => {
      const cells = [
        { v: t.team, html: teamLink(t.team) },
        { v: t.exp_pts, html: num(t.exp_pts), align: 'right' },
        { v: t.p_title, html: '<strong>' + pct(t.p_title) + '</strong>', align: 'right' }
      ];
      bands.forEach(b => {
        const v = (t.bands || {})[b.key] || 0;
        cells.push({ v: v, html: pct(v), cls: b.kind === 'down' ? riskClass(v) : '', align: 'right' });
      });
      return { cells: cells };
    });
  }
  setHTML('probs-table', tableHTML(cols, rows, { sticky: true }));
  sortableIn('probs-table');
}

// ── power rankings ─────────────────────────────────────────────────────────

function renderPower() {
  const st = D().strength || { rows: [], notes: {} };
  const rows = st.rows || [];
  if (!rows.length) { setHTML('power-table', '<div class="muted">No strength data yet.</div>'); return; }
  const n = st.notes_en || st.notes || {};
  setHTML('power-explainer', '<p>' + esc(n.strength_ppg || '') + '</p><p>' + esc(n.rank_delta || '') + '</p>');
  const played = rows.filter(r => r.played > 0);
  const hasXg = played.some(r => r.expected_points > 0);
  const hasZone = rows.some(r => r.zone || r.conference);
  const zoneOf = r => r.zone || (r.conference ? String(r.conference).slice(0, 4) : '');
  const trs = rows.map(r => {
    const d = r.rank_delta;
    const dHtml = d === 0 ? '—' : '<span class="' + (d > 0 ? 'danger' : '') + '">' + (d > 0 ? '+' : '') + d + '</span>';
    const cells = [
      { v: r.strength_rank, cls: 'pos-cell' },
      { v: r.team, html: teamLink(r.team) }
    ];
    if (hasZone) cells.push({ v: zoneOf(r), align: 'center' });
    cells.push(
      { v: r.strength_ppg, html: num(r.strength_ppg, 3), align: 'right' },
      { v: r.elo, html: num(r.elo, 0), align: 'right' },
      { v: r.table_rank, align: 'right' },
      { v: d, html: dHtml, align: 'right' },
      { v: r.ppg, html: num(r.ppg, 2), align: 'right' },
      { v: r.form_ppg, html: formChips(r.form_results) + ' ' + num(r.form_ppg, 2), align: 'right' },
      { v: r.xg_diff, html: signed(r.xg_diff, 1), align: 'right' },
      { v: r.luck, html: luckCell(r.luck, hasXg), align: 'right' },
      { v: r.sos_delta, html: signed(r.sos_delta, 3), align: 'right' }
    );
    return { cells: cells };
  });
  const cols = [{ label: '#', sortable: false }, { label: 'Club' }];
  if (hasZone) cols.push({ label: kind() === 'liga' ? 'Zone' : 'Conf.', align: 'center' });
  cols.push({ label: 'Strength', align: 'right' }, { label: 'Elo', align: 'right' }, { label: 'Pos.', align: 'right' },
            { label: 'Δ', align: 'right' }, { label: 'PPG', align: 'right' }, { label: 'Form', align: 'right' },
            { label: 'xG diff', align: 'right' }, { label: 'Luck', align: 'right' }, { label: 'Schedule', align: 'right' });
  setHTML('power-table', tableHTML(cols, trs, { sticky: true }));
  sortableIn('power-table');

  if (hasXg) {
    const byLuck = played.slice().sort((a, b) => a.luck - b.luck);
    plot('luck-chart', [{
      type: 'bar', orientation: 'h', y: byLuck.map(r => r.team), x: byLuck.map(r => r.luck),
      marker: { color: byLuck.map(r => (r.luck >= 0 ? C.green : C.red)) },
      hovertemplate: '%{y}: %{x:+.2f} points against expectation<extra></extra>'
    }], layout({ margin: { l: 170, r: 30, t: 20, b: 45 }, xaxis: { title: 'Actual points − expected points from xG', zeroline: true }, yaxis: { automargin: true } }));
  } else {
    setHTML('luck-chart', '<div class="muted">No xG coverage for the current season yet.</div>');
  }
  const bySos = played.slice().sort((a, b) => a.sos_delta - b.sos_delta);
  plot('sos-chart', [
    { type: 'bar', name: 'Played', orientation: 'h', y: bySos.map(r => r.team), x: bySos.map(r => r.sos_played), marker: { color: C.text3 }, hovertemplate: '%{y}: opponents played %{x:.3f}<extra></extra>' },
    { type: 'bar', name: 'To play', orientation: 'h', y: bySos.map(r => r.team), x: bySos.map(r => r.sos_remaining), marker: { color: C.blue }, hovertemplate: '%{y}: opponents to play %{x:.3f}<extra></extra>' }
  ], layout({ barmode: 'group', showlegend: true, legend: { orientation: 'h', y: 1.06, font: { color: C.text2 } }, margin: { l: 170, r: 30, t: 40, b: 45 }, xaxis: { title: 'Mean opponent strength' }, yaxis: { automargin: true } }));
  const hist = st.elo_history || {};
  const top = rows.slice(0, 8).filter(r => (hist[r.team] || []).length > 1);
  if (top.length) {
    plot('elo-chart', top.map((r, i) => ({
      type: 'scatter', mode: 'lines', name: r.team,
      x: (hist[r.team] || []).map(p => p.date), y: (hist[r.team] || []).map(p => p.elo),
      line: { width: 2, color: PALETTE[i % 8] }, hovertemplate: r.team + ': %{y:.0f}<extra></extra>'
    })), layout({ showlegend: true, legend: { orientation: 'h', y: -0.18, font: { color: C.text2 } }, margin: { l: 60, r: 20, t: 20, b: 80 } }));
  } else {
    setHTML('elo-chart', '<div class="muted">Not enough matches played yet.</div>');
  }
}

function luckCell(v, hasXg) {
  if (!hasXg) return '—';
  const cls = v >= 1.5 ? 'danger' : v <= -1.5 ? '' : 'safe';
  return '<span class="' + cls + '">' + signed(v, 2) + '</span>';
}

// ── clubs ──────────────────────────────────────────────────────────────────

function teamHeadline(prob, k) {
  if (!prob) return [];
  if (k === 'liga') return [['Champion', prob.p_title], ['Top 8', prob.p_top8], ['Relegation', prob.p_relegation]];
  if (k === 'conference') return [['MLS Cup', prob.p_cup], ['Playoffs', prob.p_playoffs], ['Shield', prob.p_title]];
  if (k === 'playoff') return [['Champion', prob.p_cup], ['Liguilla', prob.p_playoffs]];
  if (k === 'cup') return [['Winner', prob.p_cup], ['Final', prob.p_conference]];
  const bands = (D().probs || {}).bands || [];
  const up = bands.filter(b => b.kind === 'up')[0];
  const downs = bands.filter(b => b.kind === 'down');
  const out = [['Title', prob.p_title]];
  if (up) out.push([up.label, (prob.bands || {})[up.key]]);
  if (downs.length) out.push(['Relegation', downs.reduce((s, b) => s + ((prob.bands || {})[b.key] || 0), 0)]);
  return out;
}

function renderTeams() {
  const d = D();
  const k = kind();
  const probs = (d.probs || {}).teams || [];
  const teamsMap = (d.teams || {}).teams || {};
  const names = Object.keys(teamsMap).length ? Object.keys(teamsMap) : probs.map(p => p.team);
  names.sort((a, b) => a.localeCompare(b));
  if (!names.length) { setHTML('team-grid', '<div class="muted">No clubs yet.</div>'); return; }
  const select = document.getElementById('team-select');
  select.innerHTML = '<option value="">Jump to a club…</option>' + names.map(t => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('');
  select.onchange = () => { if (select.value) location.hash = teamHref(select.value); };
  const strength = {};
  ((d.strength || {}).rows || []).forEach(r => { strength[r.team] = r; });
  const stats = (d.team_stats || {}).teams || {};
  let rank = {};
  const t = d.table || {};
  (t.standings || t.overall || []).forEach(r => { rank[r.team] = r; });
  if (t.conferences) Object.keys(t.conferences).forEach(g => t.conferences[g].forEach(r => { rank[r.team] = r; }));
  const cards = names.map(team => {
    const p = probs.find(x => x.team === team);
    const s = strength[team] || {};
    const r = rank[team];
    const season = (stats[team] || {}).season || {};
    const lines = teamHeadline(p, k).map(([label, v]) => '<span class="tc-prob"><span>' + esc(label) + '</span><strong>' + pct(v) + '</strong></span>').join('');
    return '<a class="team-card" href="' + esc(teamHref(team)) + '">' +
      '<div class="tc-head">' + crest(team, null, 'lg') + '<div><div class="tc-name">' + esc(team) + '</div>' +
      '<div class="tc-sub">' + (r ? 'P' + r.pos + ' · ' + r.pts + ' pts' : (teamsMap[team] || {}).conference ? esc(teamsMap[team].conference) : '') +
      (s.form_results ? ' ' + formChips(s.form_results) : '') + '</div></div></div>' +
      '<div class="tc-probs">' + lines + '</div>' +
      '<div class="tc-stats"><span>Strength <strong>' + num(s.strength_ppg, 2) + '</strong></span><span>xG diff <strong>' + (season.xg_diff === undefined || season.xg_diff === null ? '—' : signed(season.xg_diff, 2)) + '</strong>/m</span><span>Luck <strong>' + (s.luck === undefined ? '—' : signed(s.luck, 1)) + '</strong></span></div>' +
      '</a>';
  });
  setHTML('team-grid', '<div class="team-grid">' + cards.join('') + '</div>');
}

// ── players ────────────────────────────────────────────────────────────────

const RADAR_OUT = [
  { key: 'npxg_90', label: 'npxG/90' }, { key: 'shots_90', label: 'Shots/90' }, { key: 'xa_90', label: 'xA/90' },
  { key: 'key_passes_90', label: 'Key passes/90' }, { key: 'pass_pct', label: 'Pass %' }, { key: 'dribbles_90', label: 'Dribbles/90' },
  { key: 'prog_carries_90', label: 'Prog. carries/90' }, { key: 'tackles_90', label: 'Tackles/90' }, { key: 'interceptions_90', label: 'Interceptions/90' },
  { key: 'aerial_pct', label: 'Aerial %' }, { key: 'recoveries_90', label: 'Recoveries/90' }, { key: 'rating', label: 'Rating' }
];
const RADAR_GK = [
  { key: 'saves_90', label: 'Saves/90' }, { key: 'save_pct', label: 'Save %' }, { key: 'goals_prevented_90', label: 'Goals prevented/90' },
  { key: 'conceded_90', label: 'Conceded/90' }, { key: 'sweeper_90', label: 'Sweeper/90' }, { key: 'high_claims_90', label: 'High claims/90' },
  { key: 'pass_pct', label: 'Pass %' }, { key: 'long_ball_pct', label: 'Long-ball %' }, { key: 'rating', label: 'Rating' }
];

function metricOptions(metrics, scope) {
  const groups = [];
  metrics.filter(m => scope === 'all' || m.scope === 'all' || m.scope === scope).forEach(m => {
    let g = groups.find(x => x.name === m.group);
    if (!g) { g = { name: m.group, items: [] }; groups.push(g); }
    g.items.push(m);
  });
  return groups.map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + '</option>').join('') + '</optgroup>').join('');
}

function renderPlayers() {
  const d = D();
  const live = d.players_live || {};
  const all = live.players || [];
  const metrics = live.metrics || [];
  if (!all.length) { setHTML('players-table', '<div class="muted">No player data yet.</div>'); setHTML('scorer-race', ''); return; }
  setHTML('players-sub', all.length + ' players · ' + (live.matches_covered || 0) + ' matches with player data · percentiles against positional peers over ' + (live.minutes_floor || 0) + ' minutes');

  const race = ((d.player_leaders || {}).top_scorer || []).filter(r => r.model);
  setHTML('scorer-race', race.length ? tableHTML([
    { label: 'Player' }, { label: 'Club' }, { label: 'Goals', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'P(top scorer)', align: 'right' }
  ], race.slice(0, 25).map(r => ({ cells: [
    { v: r.name, html: playerLink(r.id, r.name) }, { v: r.team, html: teamLink(r.team) }, { v: r.goals, align: 'right' },
    { v: r.xg, html: num(r.xg, 2), align: 'right' }, { v: r.model, html: '<strong>' + pct(r.model) + '</strong>', align: 'right' }
  ] }))) : '<div class="muted">No top-scorer race yet.</div>');
  sortableIn('scorer-race');

  const metricSel = document.getElementById('metric-select');
  const posSel = document.getElementById('player-pos-filter');
  const teamFilter = document.getElementById('player-team-filter');
  const minMin = document.getElementById('min-minutes');
  const qualOnly = document.getElementById('qualified-only');
  const teams = Array.from(new Set(all.map(p => p.team))).sort((a, b) => a.localeCompare(b));
  teamFilter.innerHTML = '<option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('');
  minMin.value = live.minutes_floor || 270;

  function fillMetrics() {
    const scope = posSel.value === 'G' ? 'gk' : posSel.value ? 'out' : 'all';
    const keep = metricSel.value;
    metricSel.innerHTML = metricOptions(metrics, scope);
    metricSel.value = Array.from(metricSel.options).some(o => o.value === keep) ? keep : (scope === 'gk' ? 'saves_90' : 'goals');
  }
  fillMetrics();

  function drawTable() {
    const metric = metrics.find(m => m.key === metricSel.value) || metrics[0];
    const key = metric.key;
    // A total's percentile is its per-90 rate's (goals -> goals /90).
    const pctKey = metric.pct ? key : (metrics.some(m => m.key === key + '_90' && m.pct) ? key + '_90' : null);
    const floor = parseInt(minMin.value, 10) || 0;
    const club = teamFilter.value, pos = posSel.value;
    const rows = all.filter(p => p.minutes >= floor && (!club || p.team === club) && (!pos || (pos === 'G' ? p.is_gk : p.position === pos)) && (!qualOnly.checked || p.qualified) && p[key] !== undefined && p[key] !== null)
      .sort((a, b) => metric.lower ? (a[key] - b[key]) : (b[key] - a[key])).slice(0, 80);
    setHTML('players-table', rows.length ? tableHTML([
      { label: '#', sortable: false }, { label: 'Player' }, { label: 'Club' }, { label: 'Pos', align: 'center' }, { label: 'Age', align: 'right' },
      { label: 'Apps', align: 'right' }, { label: 'Min', align: 'right' }, { label: metric.label, align: 'right' },
      { label: 'Pctl', align: 'center', title: 'Percentile against positional peers' + (pctKey && pctKey !== key ? ' (per-90 rate)' : '') }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' },
      { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }, { label: 'Rating', align: 'right' }
    ], rows.map((p, i) => ({ cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: p.name, html: playerLink(p.player_id, p.name) }, { v: p.team, html: teamLink(p.team) },
      { v: p.position || (p.is_gk ? 'G' : ''), html: (p.position || p.is_gk) ? '<span class="pos-badge pos-' + esc(p.position || 'G') + '">' + esc(p.position || 'G') + '</span>' : '', align: 'center' },
      { v: p.age || 0, html: p.age || '—', align: 'right' },
      { v: p.matches, align: 'right' }, { v: p.minutes, align: 'right' },
      { v: p[key], html: '<strong>' + fmtMetric(p[key], metric.fmt) + '</strong>', align: 'right' },
      { v: pctKey && (p.pct || {})[pctKey] !== undefined ? p.pct[pctKey] : -1, html: pctPill(pctKey ? (p.pct || {})[pctKey] : undefined), align: 'center' },
      { v: p.goals, align: 'right' }, { v: p.assists, align: 'right' },
      { v: p.xg, html: num(p.xg, 2), align: 'right' }, { v: p.xa, html: num(p.xa, 2), align: 'right' },
      { v: p.rating || 0, html: p.rating === null || p.rating === undefined ? '—' : num(p.rating, 2), align: 'right' }
    ] })), { sticky: true }) : '<div class="muted">No player clears the filters.</div>');
    sortableIn('players-table');
  }
  metricSel.onchange = drawTable; teamFilter.onchange = drawTable; posSel.onchange = () => { fillMetrics(); drawTable(); };
  qualOnly.onchange = drawTable; minMin.onchange = drawTable; minMin.oninput = drawTable;
  drawTable();

  // Compare two players on percentiles.
  const pool = all.filter(p => p.qualified);
  const opts = pool.slice().sort((a, b) => (b.goals + b.assists) - (a.goals + a.assists) || b.minutes - a.minutes)
    .map(p => '<option value="' + esc(p.player_id) + '">' + esc(p.name) + ' — ' + esc(p.team) + (p.position ? ' (' + p.position + ')' : '') + '</option>').join('');
  const cmpA = document.getElementById('cmp-a'), cmpB = document.getElementById('cmp-b');
  cmpA.innerHTML = opts; cmpB.innerHTML = opts;
  if (pool.length > 1) cmpB.selectedIndex = 1;
  function drawCompare() {
    const a = pool.find(p => p.player_id === cmpA.value), b = pool.find(p => p.player_id === cmpB.value);
    if (!a) { setHTML('compare-chart', '<div class="muted">Not enough qualified players yet.</div>'); return; }
    const axes = a.is_gk ? RADAR_GK : RADAR_OUT;
    renderRadar('compare-chart', axes, [a, b].filter(Boolean));
  }
  cmpA.onchange = drawCompare; cmpB.onchange = drawCompare;
  drawCompare();

  const scatter = all.filter(p => p.qualified && !p.is_gk);
  if (scatter.length) {
    plot('player-scatter', [{
      type: 'scatter', mode: 'markers', x: scatter.map(p => p.npxg_90 || 0), y: scatter.map(p => p.xa_90 || 0),
      text: scatter.map(p => p.name + ' (' + p.team + ')'),
      marker: { size: scatter.map(p => 6 + Math.min(p.goals, 12)), color: scatter.map(p => p.rating || 6.5), colorscale: 'Viridis', showscale: false, opacity: 0.85 },
      hovertemplate: '%{text}<br>npxG/90 %{x:.2f} · xA/90 %{y:.2f}<extra></extra>'
    }], layout({ xaxis: { title: 'Non-penalty xG per 90' }, yaxis: { title: 'xA per 90' } }));
  } else {
    setHTML('player-scatter', '<div class="muted">Not enough minutes played yet.</div>');
  }

  const shotPlayers = Object.keys((d.shots || {}).players || {}).sort((a, b) => a.localeCompare(b));
  const shotSel = document.getElementById('shotmap-player');
  if (!shotPlayers.length) {
    setHTML('shotmap', '<div class="muted">No shot data yet.</div>');
  } else {
    const shotsOf = n => (((d.shots || {}).players || {})[n] || {}).shots || [];
    const ordered = shotPlayers.slice().sort((a, b) => shotsOf(b).length - shotsOf(a).length);
    shotSel.innerHTML = ordered.map(n => '<option value="' + esc(n) + '">' + esc(n) + ' (' + shotsOf(n).length + ')</option>').join('');
    const drawShots = () => renderShotMap('shotmap', shotsOf(shotSel.value).map(s => Object.assign({}, s, { player: shotSel.value })));
    shotSel.onchange = drawShots;
    drawShots();
  }
}

// ── matches ────────────────────────────────────────────────────────────────

function renderMatches() {
  const d = D();
  const all = ((d.matches || {}).matches || []);
  if (!all.length) { setHTML('matches-list', '<div class="muted">No matches played yet.</div>'); return; }
  const teamSel = document.getElementById('matches-team');
  const teams = Array.from(new Set(all.map(m => m.home).concat(all.map(m => m.away)))).sort((a, b) => a.localeCompare(b));
  teamSel.innerHTML = '<option value="">All clubs</option>' + teams.map(t => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('');
  const detailOnly = document.getElementById('matches-detail-only');
  setHTML('matches-sub', all.length + ' played · ' + (d.matches.with_detail || 0) + ' with full match data');
  function draw() {
    const team = teamSel.value;
    const rows = all.filter(m => (!team || m.home === team || m.away === team) && (!detailOnly.checked || m.detail)).slice(0, 250);
    setHTML('matches-list', rows.length ? tableHTML([
      { label: 'Date' }, { label: 'Round', align: 'right' }, { label: 'Home' }, { label: 'Score', align: 'center', sortable: false },
      { label: 'Away' }, { label: 'xG', align: 'center', sortable: false }, { label: '', sortable: false }
    ], rows.map(m => ({ _href: m.detail ? matchHref(m.id) : null, cells: [
      { v: m.date || '', html: esc(fmtDate(m.date, true)) }, { v: m.round === undefined ? '' : m.round, html: esc(FH.roundText(m, null, true)), align: 'right' },
      { v: m.home, html: teamLink(m.home) }, { v: m.hs + '-' + m.as, html: '<span class="score">' + esc(FH.scoreText(Object.assign({ status: 'finished' }, m))) + '</span>', align: 'center' },
      { v: m.away, html: teamLink(m.away) },
      { v: m.xg ? m.xg[0] : '', html: m.xg ? '<span class="xg-line">' + num(m.xg[0], 2) + ' – ' + num(m.xg[1], 2) + '</span>' : '', align: 'center' },
      { v: '', html: m.detail ? '<a href="' + esc(matchHref(m.id)) + '">Analysis →</a>' : '<span class="muted-inline">—</span>' }
    ] })), { sticky: true }) : '<div class="muted">No matches for that filter.</div>');
    wireRowLinks('matches-list');
    sortableIn('matches-list');
  }
  teamSel.onchange = draw; detailOnly.onchange = draw;
  draw();
}

// ── market ─────────────────────────────────────────────────────────────────

function renderMarket() {
  const m = D().market_odds || {};
  const sub = document.getElementById('market-sub');
  sub.textContent = m.ok === false ? 'Odds could not be refreshed.' : '';
  const SRC = { polymarket: 'Polymarket', kalshi: 'Kalshi' };
  const srcNames = (m.sources || []).map(x => SRC[x] || 'bookmakers');
  setHTML('market-explainer', '<p>Prices come from the prediction markets Polymarket and Kalshi (their public data; no bets are placed or offered here)' +
    ((m.sources || []).some(x => !SRC[x]) ? ' and from bookmakers via The Odds API' : '') + '. A market price is the midpoint of the best bid and ask. ' +
    'Each source is de-vigged (its three prices rescaled to sum to one) and the sources are pooled, so a gap against the model is a real disagreement, not a margin.</p>' +
    '<p>Edge is relative: two percentage points do not mean the same thing at 5% as at 50%. Markets usually list a matchday about a week ahead; the Fixtures tab carries the model&rsquo;s fair odds for every match regardless.</p>');
  const matches = (m.matches || {}).fixtures || [];
  if (!matches.length) {
    setHTML('market-matches', '<div class="muted pad">No market lists these fixtures yet. Polymarket and Kalshi usually open a matchday about a week before it.</div>');
  } else {
    const minEdge = (m.matches || {}).min_edge || 0.03;
    setHTML('market-matches', tableHTML([
      { label: 'Match' }, { label: 'Sources', align: 'right', title: 'How many markets price this match' }, { label: 'Model H/D/A', align: 'center', sortable: false },
      { label: 'Market H/D/A', align: 'center', sortable: false }, { label: 'Best', align: 'center' }, { label: 'Edge', align: 'right' }
    ], matches.map(f => {
      const trio = o => ['home', 'draw', 'away'].map(k => pct(o[k], 0)).join(' / ');
      const label = { home: 'Home', draw: 'Draw', away: 'Away' }[f.best_outcome] || '—';
      return { cells: [
        { v: f.home + ' ' + f.away, html: teamLink(f.home) + ' <span style="color:var(--text3)">v</span> ' + teamLink(f.away) },
        { v: f.books, align: 'right' }, { v: f.model.home, html: trio(f.model), align: 'center' }, { v: f.market.home, html: trio(f.market), align: 'center' },
        { v: f.best_outcome || '', html: esc(label), align: 'center' },
        { v: f.best_edge, html: '<span class="' + (f.actionable ? 'danger' : 'safe') + '">' + signed(f.best_edge * 100, 1) + '%</span>', align: 'right' }
      ] };
    })));
    sortableIn('market-matches');
    sub.textContent = matches.length + ' matches · ' + ((m.matches || {}).actionable || 0) + ' with edge over ' + pct(minEdge, 0) + (srcNames.length ? ' · ' + Array.from(new Set(srcNames)).join(', ') : '');
  }
  const out = m.outrights || {};
  if (!out.available || !(out.teams || []).length) { setHTML('market-outrights', '<div class="muted">No outright market available for this competition.</div>'); return; }
  const warn = out.field_complete === false ? '<div class="stale-banner">The market does not price every team, so de-vigged probabilities are inflated and the edge looks better than it is.</div>' : '';
  setHTML('market-outrights', warn + tableHTML([{ label: 'Club' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Edge', align: 'right' }],
    out.teams.map(t => ({ cells: [
      { v: t.team, html: teamLink(t.team) }, { v: t.model, html: pct(t.model), align: 'right' }, { v: t.market, html: pct(t.market), align: 'right' },
      { v: t.edge, html: '<span class="' + (t.actionable ? 'danger' : 'safe') + '">' + signed(t.edge * 100, 1) + '%</span>', align: 'right' }
    ] }))));
  sortableIn('market-outrights');
}

// ── history ────────────────────────────────────────────────────────────────

function renderHistory() {
  const snaps = (D().history || {}).snapshots || [];
  const el = document.getElementById('history-chart');
  const select = document.getElementById('history-series');
  const k = kind();
  let options;
  if (k === 'liga') {
    options = [['title', 'Clausura champion'], ['anual', 'Campeón de Liga (Anual)'], ['relegation', 'Relegation']];
  } else if (k === 'conference') {
    options = [['title', 'MLS Cup'], ['shield', "Supporters' Shield"]];
  } else if (k === 'cup') {
    options = [['title', 'Winner']];
    const first = (((D().table || {}).bands) || []).filter(b => b.kind === 'up')[0];
    if (first) options.push(['band', first.label]);
  } else if (k === 'playoff') {
    options = [['title', 'Champion'], ['band', 'Liguilla']];
  } else {
    const bands = (D().table || {}).bands || (D().probs || {}).bands || [];
    const first = bands.filter(b => b.kind === 'up')[0];
    options = [['title', 'Title']];
    if (first) options.push(['band', first.label]);
    if (bands.some(b => b.kind === 'down')) options.push(['relegation', 'Relegation']);
  }
  select.innerHTML = options.map(o => '<option value="' + o[0] + '">' + esc(o[1]) + '</option>').join('');
  function draw() {
    const key = select.value;
    if (snaps.length < 2) { el.innerHTML = '<div class="muted">Not enough history yet. The chart appears after a few runs.</div>'; return; }
    const latest = snaps[snaps.length - 1][key] || {};
    const teams = Object.keys(latest).sort((a, b) => latest[b] - latest[a]).slice(0, 8);
    plot(el, teams.map((team, i) => ({
      type: 'scatter', mode: 'lines', name: team, x: snaps.map(s => s.ts), y: snaps.map(s => (s[key] || {})[team] || 0),
      line: { width: 2, color: PALETTE[i % 8] }, hovertemplate: team + ': %{y:.1%}<extra></extra>'
    })), layout({ showlegend: true, legend: { orientation: 'h', y: -0.18, font: { color: C.text2 } }, margin: { l: 60, r: 20, t: 20, b: 80 }, yaxis: { tickformat: '.0%', rangemode: 'tozero' } }));
  }
  select.onchange = draw;
  draw();
}

// ── methodology ────────────────────────────────────────────────────────────

/* The full methodology document lives in docs.js (FH.renderMethodologyDoc); the
   competition tab prepends a "This competition" card built from meta, table and
   bracket, then the same document the site-wide #/methodology page shows. */
function renderMethodology() {
  const el = document.getElementById('methodology-doc');
  if (!el) return;
  if (typeof FH.renderMethodologyDoc !== 'function') {
    el.innerHTML = '<div class="card"><div class="muted">The methodology module did not load.</div></div>';
    return;
  }
  const d = D();
  FH.renderMethodologyDoc(el, { competition: { comp: comp() || {}, kind: kind(), meta: d.meta || {}, table: d.table || null, bracket: d.bracket || null } });
}

// ── wiring ─────────────────────────────────────────────────────────────────

function renderAnalytics() { if (FH.renderAnalytics) FH.renderAnalytics(); }   // the tab itself lives in analytics.js, loaded later
const RENDERERS = {
  overview: renderOverview, table: renderTable, fixtures: renderFixtures, zones: renderZones, bracket: renderBracket,
  anual: renderAnual, relegation: renderRelegation, probs: renderProbs, power: renderPower,
  team: renderTeams, players: renderPlayers, matches: renderMatches, market: renderMarket,
  history: renderHistory, methodology: renderMethodology, analytics: renderAnalytics
};
Object.assign(FH.RENDERERS, RENDERERS);
FH.fixtureRow = fixtureRow;
FH.fixtureDetailRow = fixtureDetailRow;
FH.standingsTable = standingsTable;
FH.teamHeadline = teamHeadline;
FH.RADAR_OUT = RADAR_OUT;
FH.RADAR_GK = RADAR_GK;
})(window.FH);
