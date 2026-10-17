/* The Quant Footballer — the Analytics tab and the club page's analytics.
 *
 * Reads analytics.json (rounds, season XIs, performers, team profiles) through
 * FH.D().analytics and renders into #analytics-root. The formation drawing is
 * shared with the club page (FH.drawXI, FH.xiPoints, FH.ratingColor). Every card
 * degrades to one muted line when its slice of the payload is missing. */
(function (FH) {
'use strict';

const { C, esc, num, signed, fmtMetric, fmtDate, D, crest, teamLink, teamHref, playerLink, matchHref,
        tableHTML, setHTML, sortableIn, wireRowLinks, statTile, pctPill, pctColor, plot, layout } = FH;

// ── shared pieces ──────────────────────────────────────────────────────────

/* The match centre's thresholds: deep green from 8, green from 7.3, amber from 6.8, orange from 6.3, else red. */
function ratingColor(r) {
  if (r === undefined || r === null || isNaN(r)) return '#6e7681';
  if (r >= 8) return '#238636'; if (r >= 7.3) return '#3fb950'; if (r >= 6.8) return '#d29922'; if (r >= 6.3) return '#f97316'; return '#f85149';
}

function surname(name) {
  const parts = String(name || '').trim().split(' ');
  return parts.length > 1 && parts[parts.length - 1].length <= 3 && parts.length > 2 ? parts.slice(-2).join(' ') : parts[parts.length - 1];
}

function isNum(v) { return v !== null && v !== undefined && !isNaN(v); }

/* The left half of FH.fullPitch, turned upright: the goal at the bottom, the
   halfway line at the top, x across the pitch (0-100) and y the distance from
   the goal line (0-50). */
function halfPitchVertical() {
  const swapPath = p => {
    const tok = String(p).split(' ');
    const out = [];
    for (let i = 0; i < tok.length; i++) {
      if (isNaN(parseFloat(tok[i]))) { out.push(tok[i]); continue; }
      out.push(tok[i + 1]); out.push(tok[i]); i++;
    }
    return out.join(' ');
  };
  return (FH.fullPitch ? FH.fullPitch() : []).filter(s => {
    const xs = [s.x0, s.x1].filter(isNum);
    if (s.type === 'path') return parseFloat(String(s.path).split(' ')[1]) < 55;
    return !xs.length || Math.min.apply(null, xs) < 55;
  }).map(s => {
    const t = Object.assign({}, s);
    if (s.type === 'path') { t.path = swapPath(s.path); return t; }
    t.x0 = s.y0; t.x1 = s.y1; t.y0 = s.x0; t.y1 = s.x1;
    return t;
  });
}

/* Place eleven (or fewer) players on the upright half pitch. `formation` is a
   string like "4-3-3"; when it is missing or does not add up, the lines come
   from the players' positions (D / M / F). Returns [{p, x, y}]. */
function xiPoints(xi, formation) {
  const list = (xi || []).filter(Boolean);
  if (!list.length) return [];
  const gkIdx = list.findIndex(p => p.pos === 'G');
  const gk = gkIdx >= 0 ? list[gkIdx] : null;
  const out = list.filter((p, i) => i !== gkIdx);
  let lines = String(formation || '').split('-').map(n => parseInt(n, 10)).filter(n => n > 0);
  let ordered = out;
  if (!lines.length || lines.reduce((a, b) => a + b, 0) !== out.length) {
    const byPos = { D: [], M: [], F: [] };
    out.forEach(p => (byPos[p.pos] || byPos.M).push(p));
    lines = ['D', 'M', 'F'].map(k => byPos[k].length).filter(n => n > 0);
    ordered = byPos.D.concat(byPos.M, byPos.F);
  }
  const pts = [];
  if (gk) pts.push({ p: gk, x: 50, y: 6.5 });
  let k = 0;
  lines.forEach((n, li) => {
    const depth = 4 + (li + 1) * (44 / (lines.length + 0.6));
    const span = Math.min(80, 24 * (n - 1));
    for (let j = 0; j < n; j++, k++) {
      const across = n === 1 ? 50 : 50 - span / 2 + j * (span / (n - 1));
      if (ordered[k]) pts.push({ p: ordered[k], x: 100 - across, y: depth });
    }
  });
  return pts;
}

/* Draw an XI on the upright half pitch. Markers are coloured by rating (or by
   opts.color(p)); under each, the surname and the rating (or opts.label(p)).
   Clicking a marker opens the player's page. */
function drawXI(elId, xi, formation, opts) {
  const o = opts || {};
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  const pts = xiPoints(xi, formation);
  if (!pts.length) { el.innerHTML = '<div class="muted">No line-up to draw.</div>'; return; }
  const labelOf = o.label || (p => surname(p.name) + (isNum(p.rt) ? ' ' + num(p.rt, 1) : ''));
  const colorOf = o.color || (p => ratingColor(p.rt));
  const hoverOf = o.hover || (p => '<b>' + esc(p.name) + '</b> · ' + esc(p.pos || '') + ' · ' + esc(p.team || '') +
    (isNum(p.rt) ? '<br>rating ' + num(p.rt, 2) : '') +
    (p.g || p.a ? '<br>' + (p.g || 0) + ' G · ' + (p.a || 0) + ' A' : '') +
    (isNum(p.xg) || isNum(p.xa) ? '<br>xG ' + num(p.xg, 2) + ' · xA ' + num(p.xa, 2) : '') +
    (isNum(p.min) ? '<br>' + Math.round(p.min) + ' min' : '') +
    (p.opp ? '<br>' + (p.ha === 'A' ? '@ ' : 'v ') + esc(p.opp) + (isNum(p.gf) ? ' ' + p.gf + '–' + p.ga : '') : ''));
  const traces = [{
    type: 'scatter', mode: 'markers', x: pts.map(q => q.x), y: pts.map(q => q.y), hoverinfo: 'text', showlegend: false,
    hovertext: pts.map(q => hoverOf(q.p)), customdata: pts.map(q => q.p.id || ''),
    marker: { size: o.size || 26, color: pts.map(q => colorOf(q.p)), line: { color: '#0d1117', width: 2 } }
  }, {
    type: 'scatter', mode: 'text', x: pts.map(q => q.x), y: pts.map(q => q.y - 4.6), hoverinfo: 'skip', showlegend: false,
    text: pts.map(q => esc(labelOf(q.p))), textfont: { color: '#e6edf3', size: 11 }
  }];
  plot(el, traces, layout({
    shapes: halfPitchVertical(), plot_bgcolor: 'rgba(46,160,67,0.05)',
    xaxis: { range: [-2, 102], visible: false, fixedrange: true },
    yaxis: { range: [-8, 53], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1.544 },
    margin: { l: 4, r: 4, t: 4, b: 4 }
  }));
  if (typeof el.on === 'function') {
    el.on('plotly_click', ev => {
      const pt = ev && ev.points && ev.points[0];
      const id = pt && pt.customdata;
      if (id) location.hash = '#/' + FH.STATE.current + '/player/' + id;
    });
    el.classList.add('an-clickable');
  }
}

function posBadge(pos) { return pos ? '<span class="pos-badge pos-' + esc(pos) + '">' + esc(pos) + '</span>' : ''; }

function scoreLine(t) {
  if (!t) return '';
  const opp = t.ha === 'A' ? '@ ' : 'v ';
  return esc(t.team) + ' ' + t.gf + '–' + t.ga + ' ' + esc(t.opp) + ' (' + esc(t.ha || 'H') + ')' +
    (isNum(t.xg) ? ', xG ' + num(t.xg, 1) + '–' + num(t.xga, 1) : '') + (opp ? '' : '');
}

function matchLine(p) {
  if (!p || !p.opp) return '';
  const s = (p.ha === 'A' ? '@ ' : 'v ') + esc(p.opp) + (isNum(p.gf) ? ' ' + p.gf + '–' + p.ga : '');
  return p.gid ? '<a href="' + esc(matchHref(p.gid)) + '">' + s + '</a>' : s;
}

function playerTile(label, p, valueHtml, sub) {
  if (!p) return '';
  return '<div class="aw-tile"><div class="aw-label">' + esc(label) + '</div>' +
    '<div class="aw-name">' + playerLink(p.id, p.name) + ' ' + posBadge(p.pos) + '</div>' +
    '<div class="aw-team">' + (p.team ? '<a class="team-link" href="' + esc(teamHref(p.team)) + '">' + crest(p.team) + esc(p.team) + '</a>' : '') + '</div>' +
    (valueHtml ? '<div class="aw-value">' + valueHtml + '</div>' : '') +
    (sub ? '<div class="aw-sub">' + sub + '</div>' : '') + '</div>';
}

function metricDef(key) {
  const live = D().players_live || {};
  return (live.metrics || []).find(m => m.key === key) || null;
}

function teamMetricDef(key) {
  const an = D().analytics || {};
  return (an.team_metrics || []).find(m => m.key === key) || null;
}

function teamRanking(key) {
  const an = D().analytics || {};
  return (((an.performers || {}).teams || {})[key] || {}).ranking || [];
}

/* Whether the payload's percentile for this team metric is already turned so
   that higher = better (true when the best-ranked team carries the top percentile). */
function pctIsGoodness(key) {
  const r = teamRanking(key);
  if (r.length < 2) return true;
  return (r[0].pct || 0) >= (r[r.length - 1].pct || 0);
}

function goodPct(key, pctVal) {
  if (!isNum(pctVal)) return pctVal;
  const m = teamMetricDef(key) || {};
  if (m.lower && !pctIsGoodness(key)) return 100 - pctVal;
  return pctVal;
}

function rawPct(key, pctVal) {
  if (!isNum(pctVal)) return pctVal;
  const m = teamMetricDef(key) || {};
  if (m.lower && pctIsGoodness(key)) return 100 - pctVal;
  return pctVal;
}

// ── 1. team of the week ────────────────────────────────────────────────────

const AWARD_LABELS = { finisher: 'Finisher', creator: 'Creator', wall: 'The wall', engine: 'Engine', ball_winner: 'Ball winner' };
const TEAM_AWARD_LABELS = { best_xg_diff: 'Best xG difference', luckiest: 'Luckiest', unluckiest: 'Unluckiest', smash_and_grab: 'Smash and grab' };

function renderRound(an) {
  const sel = document.getElementById('an-round');
  const rounds = an.rounds || [];
  const r = rounds.find(x => String(x.round) === sel.value) || rounds[0];
  if (!r) { setHTML('an-totw-pitch', '<div class="muted">No completed round yet.</div>'); setHTML('an-totw-awards', ''); setHTML('an-totw-bench', ''); return; }
  const tw = r.team_of_week || {};
  const xi = tw.xi || [];
  setHTML('an-totw-head', (tw.formation ? '<span class="chip an-chip">' + esc(tw.formation) + '</span>' : '<span class="chip an-chip">by position</span>') +
    '<span class="muted-inline">' + (r.dates && r.dates[0] ? esc(fmtDate(r.dates[0])) + (r.dates[1] && r.dates[1] !== r.dates[0] ? ' – ' + esc(fmtDate(r.dates[1])) : '') : '') +
    (r.matches ? ' · ' + r.matches + ' matches' : '') + '</span>');
  if (xi.length) drawXI('an-totw-pitch', xi, tw.formation);
  else setHTML('an-totw-pitch', '<div class="muted">No team of the week for this round.</div>');
  const bench = tw.bench || [];
  setHTML('an-totw-bench', bench.length ? '<div class="an-bench"><span class="an-bench-head">Bench</span>' + bench.map(p =>
    '<span class="an-bench-item">' + posBadge(p.pos) + ' ' + playerLink(p.id, p.name) + '<span class="an-bench-rt" style="color:' + ratingColor(p.rt) + '">' + (isNum(p.rt) ? num(p.rt, 1) : '') + '</span></span>').join('') + '</div>' : '');

  let html = '';
  const potw = r.player_of_week;
  if (potw) {
    html += '<div class="aw-potw"><div class="aw-label">Player of the week</div>' +
      '<div class="aw-potw-row"><span class="aw-potw-rt" style="background:' + ratingColor(potw.rt) + '">' + (isNum(potw.rt) ? num(potw.rt, 1) : '—') + '</span>' +
      '<div><div class="aw-potw-name">' + playerLink(potw.id, potw.name) + ' ' + posBadge(potw.pos) + '</div>' +
      '<div class="aw-team">' + (potw.team ? '<a class="team-link" href="' + esc(teamHref(potw.team)) + '">' + crest(potw.team) + esc(potw.team) + '</a>' : '') + (potw.opp ? ' · ' + matchLine(potw) : '') + '</div>' +
      (potw.why ? '<div class="aw-why">' + esc(potw.why) + '</div>' : '') + '</div></div></div>';
  }
  const aw = r.awards || {};
  const tiles = Object.keys(AWARD_LABELS).filter(k => aw[k]).map(k => {
    const p = aw[k];
    return playerTile(AWARD_LABELS[k], p, (isNum(p.value) ? '<strong>' + num(p.value, 2) + '</strong> ' : '') + '<span class="aw-unit">' + esc(p.label || '') + '</span>', matchLine(p));
  });
  if (tiles.length) html += '<div class="aw-grid">' + tiles.join('') + '</div>';
  const ta = r.team_awards || {};
  const ttiles = Object.keys(TEAM_AWARD_LABELS).filter(k => ta[k]).map(k => {
    const t = ta[k];
    const line = scoreLine(t);
    return '<div class="aw-tile aw-team-tile"><div class="aw-label">' + esc(TEAM_AWARD_LABELS[k]) + '</div>' +
      '<div class="aw-name">' + teamLink(t.team) + '</div>' +
      '<div class="aw-sub">' + (t.gid ? '<a href="' + esc(matchHref(t.gid)) + '">' + line + '</a>' : line) + '</div>' +
      (isNum(t.value) ? '<div class="aw-value"><strong>' + signed(t.value, 2) + '</strong> <span class="aw-unit">' + esc(k === 'best_xg_diff' ? 'xG difference' : k === 'smash_and_grab' ? 'points above xG' : 'points above xG') + '</span></div>' : '') + '</div>';
  });
  if (ttiles.length) html += '<div class="aw-grid">' + ttiles.join('') + '</div>';
  setHTML('an-totw-awards', html || '<div class="muted">No awards for this round.</div>');
}

function totwCard(an) {
  const rounds = an.rounds || [];
  return '<div class="card"><div class="card-header">Team of the week <span class="card-sub">The best XI of the round by match rating, drawn in its formation; colour = rating. Click a player to open his page.</span>' +
    '<span class="an-ctl"><select id="an-round" class="team-select an-select">' + rounds.map(r => '<option value="' + esc(r.round) + '">' + esc(r.label || ('Round ' + r.round)) + '</option>').join('') + '</select></span></div>' +
    (rounds.length
      ? '<div class="grid-2 an-totw"><div><div id="an-totw-head" class="an-pitch-head"></div><div id="an-totw-pitch" class="an-pitch"></div><div id="an-totw-bench"></div></div>' +
        '<div id="an-totw-awards" class="pad"></div></div>'
      : '<div class="muted">No completed round yet.</div>') + '</div>';
}

// ── 2. best XIs of the season ──────────────────────────────────────────────

const BASIS_LABELS = { rating: 'Rating', output: 'Output', defence: 'Defence', form: 'Form' };

function renderSeasonXI(an) {
  const sel = document.getElementById('an-basis');
  const sx = an.season_xi || {};
  const b = sx[sel.value] || sx[Object.keys(sx)[0]];
  if (!b) { setHTML('an-xi-pitch', '<div class="muted">No season XI yet.</div>'); setHTML('an-xi-table', ''); setHTML('an-xi-head', ''); return; }
  const xi = b.xi || [];
  setHTML('an-xi-head', (b.formation ? '<span class="chip an-chip">' + esc(b.formation) + '</span>' : '') + '<span class="muted-inline">' + esc(b.basis || '') + '</span>');
  const label = (b.basis && b.basis.length < 28) ? b.basis : (BASIS_LABELS[sel.value] || 'Value');
  drawXI('an-xi-pitch', xi, b.formation, {
    label: p => surname(p.name) + (isNum(p.value) ? ' ' + num(p.value, sel.value === 'rating' || sel.value === 'form' ? 1 : 2) : (isNum(p.rt) ? ' ' + num(p.rt, 1) : '')),
    color: p => ratingColor(p.rt)
  });
  setHTML('an-xi-table', xi.length ? tableHTML([
    { label: 'Player' }, { label: 'Club' }, { label: 'Pos', align: 'center' }, { label: 'Min', align: 'right' }, { label: label, align: 'right' },
    { label: 'Rating', align: 'right' }, { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' }
  ], xi.map(p => ({ cells: [
    { v: p.name, html: playerLink(p.id, p.name) }, { v: p.team, html: teamLink(p.team) }, { v: p.pos || '', html: posBadge(p.pos), align: 'center' },
    { v: p.min || 0, html: isNum(p.min) ? String(Math.round(p.min)) : '—', align: 'right' },
    { v: isNum(p.value) ? p.value : -99, html: '<strong>' + (isNum(p.value) ? num(p.value, 2) : '—') + '</strong>', align: 'right' },
    { v: isNum(p.rt) ? p.rt : 0, html: '<span style="color:' + ratingColor(p.rt) + '">' + (isNum(p.rt) ? num(p.rt, 2) : '—') + '</span>', align: 'right' },
    { v: p.g || 0, align: 'right' }, { v: p.a || 0, align: 'right' }, { v: p.xg || 0, html: num(p.xg, 2), align: 'right' }, { v: p.xa || 0, html: num(p.xa, 2), align: 'right' }
  ] })), { compact: true }) : '');
  sortableIn('an-xi-table');
}

function seasonXICard(an) {
  const keys = Object.keys(an.season_xi || {});
  return '<div class="card"><div class="card-header">Best XIs of the season <span class="card-sub">Season totals; the basis picks the XI, the colour is the season rating.</span>' +
    '<span class="an-ctl"><select id="an-basis" class="team-select an-select">' + keys.map(k => '<option value="' + esc(k) + '">' + esc(BASIS_LABELS[k] || k) + '</option>').join('') + '</select></span></div>' +
    (keys.length
      ? '<div class="grid-2 an-totw"><div><div id="an-xi-head" class="an-pitch-head"></div><div id="an-xi-pitch" class="an-pitch"></div></div><div id="an-xi-table" class="an-xi-table"></div></div>'
      : '<div class="muted">No season XI yet: not enough minutes played.</div>') + '</div>';
}

// ── 3. top and bottom performers ───────────────────────────────────────────

function performerOptions(an) {
  const pp = (an.performers || {}).players || {};
  const live = D().players_live || {};
  const groups = [];
  const seen = {};
  (live.metrics || []).forEach(m => {
    if (!pp[m.key]) return;
    let g = groups.find(x => x.name === m.group);
    if (!g) { g = { name: m.group, items: [] }; groups.push(g); }
    g.items.push({ key: m.key, label: m.label }); seen[m.key] = true;
  });
  const rest = Object.keys(pp).filter(k => !seen[k]);
  if (rest.length) groups.push({ name: 'Other', items: rest.map(k => ({ key: k, label: pp[k].label || k })) });
  return groups.map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + '</option>').join('') + '</optgroup>').join('');
}

function performerList(rows, fmt, startRank) {
  if (!(rows || []).length) return '<div class="muted">Nobody qualifies yet.</div>';
  return '<div class="perf-list">' + rows.map((p, i) => '<div class="perf-row">' +
    '<span class="perf-rank">' + (startRank ? startRank + i : i + 1) + '</span>' +
    '<span class="perf-name">' + playerLink(p.id, p.name) + '</span>' +
    '<span class="perf-club"><a class="team-link" href="' + esc(teamHref(p.team)) + '">' + crest(p.team) + esc(p.team) + '</a></span>' +
    '<span class="perf-pos">' + posBadge(p.pos) + '</span>' +
    '<span class="perf-val" title="' + (isNum(p.minutes) ? Math.round(p.minutes) + ' minutes' : '') + '">' + fmtMetric(p.value, fmt) + '</span>' +
    '<span class="perf-pct">' + pctPill(p.pct) + '</span></div>').join('') + '</div>';
}

function renderPerformers(an) {
  const sel = document.getElementById('an-perf-metric');
  const pp = (an.performers || {}).players || {};
  const key = sel.value;
  const m = pp[key];
  if (!m) { setHTML('an-perf-desc', ''); setHTML('an-perf-top', '<div class="muted">No leaderboard for this metric.</div>'); setHTML('an-perf-bottom', ''); return; }
  const def = metricDef(key) || {};
  setHTML('an-perf-desc', '<strong>' + esc(m.label || def.label || key) + '</strong>' + (def.desc ? ' — ' + esc(def.desc) : '') +
    '<span class="muted-inline"> · ' + (m.lower ? 'lower is better' : 'higher is better') + (m.scope === 'gk' ? ' · goalkeepers' : m.scope === 'out' ? ' · outfield players' : '') +
    (an.minutes_floor ? ' · ' + an.minutes_floor + '+ minutes' : '') + '</span>');
  setHTML('an-perf-top', '<div class="perf-head">Top 8</div>' + performerList(m.top, m.fmt));
  setHTML('an-perf-bottom', '<div class="perf-head">Bottom 8</div>' + performerList(m.bottom, m.fmt));
}

function performersCard(an) {
  const pp = (an.performers || {}).players || {};
  const has = Object.keys(pp).length > 0;
  return '<div class="card"><div class="card-header">Top and bottom performers <span class="card-sub">Qualified players; the pill is the percentile against positional peers.</span>' +
    (has ? '<span class="an-ctl"><select id="an-perf-metric" class="team-select an-select">' + performerOptions(an) + '</select></span>' : '') + '</div>' +
    (has ? '<div id="an-perf-desc" class="an-desc"></div><div class="grid-2 an-perf"><div id="an-perf-top"></div><div id="an-perf-bottom"></div></div>'
         : '<div class="muted">No player leaderboards yet.</div>') + '</div>';
}

// ── 4. team rankings and the style map ─────────────────────────────────────

const STYLE_KEYS = ['xg_for', 'xg_against', 'possession', 'field_tilt', 'ppda', 'shot_quality', 'big_chances', 'aerial_pct', 'pass_pct', 'luck'];

function renderTeamRanking(an) {
  const sel = document.getElementById('an-team-metric');
  const key = sel.value;
  const pt = ((an.performers || {}).teams || {})[key];
  const def = teamMetricDef(key) || {};
  if (!pt || !(pt.ranking || []).length) { setHTML('an-team-desc', ''); setHTML('an-team-chart', '<div class="muted">No ranking for this metric.</div>'); setHTML('an-team-table', ''); return; }
  const rows = pt.ranking;
  setHTML('an-team-desc', '<strong>' + esc(pt.label || def.label || key) + '</strong>' + (def.desc ? ' — ' + esc(def.desc) : '') +
    '<span class="muted-inline"> · ' + (pt.lower || def.lower ? 'lower is better' : 'higher is better') + '</span>');
  const el = document.getElementById('an-team-chart');
  if (el) el.style.height = Math.max(240, 40 + rows.length * 24) + 'px';
  plot('an-team-chart', [{
    type: 'bar', orientation: 'h', y: rows.map(r => r.team), x: rows.map(r => r.value),
    marker: { color: rows.map(r => pctColor(goodPct(key, r.pct))) },
    text: rows.map(r => fmtMetric(r.value, pt.fmt)), textposition: 'outside', cliponaxis: false, textfont: { color: '#c9d1d9', size: 10 },
    hovertemplate: '%{y}: %{text}<extra></extra>'
  }], layout({
    margin: { l: 150, r: 50, t: 10, b: 40 }, yaxis: { automargin: true, autorange: 'reversed' },
    xaxis: { title: pt.label || def.label || key, zeroline: true, rangemode: 'tozero' }
  }));
  setHTML('an-team-table', tableHTML([
    { label: '#', sortable: false }, { label: 'Club' }, { label: pt.label || key, align: 'right' }, { label: 'Pctl', align: 'center' }
  ], rows.map((r, i) => ({ cells: [
    { v: i + 1, cls: 'pos-cell' }, { v: r.team, html: teamLink(r.team) },
    { v: r.value, html: '<strong>' + fmtMetric(r.value, pt.fmt) + '</strong>', align: 'right' },
    { v: isNum(r.pct) ? r.pct : -1, html: pctPill(r.pct), align: 'center' }
  ] })), { compact: true }));
  sortableIn('an-team-table');
}

function styleMap(an) {
  const pt = (an.performers || {}).teams || {};
  let keys = STYLE_KEYS.filter(k => pt[k] && (pt[k].ranking || []).length);
  if (keys.length < 4) keys = (an.team_metrics || []).map(m => m.key).filter(k => pt[k] && (pt[k].ranking || []).length).slice(0, 10);
  if (!keys.length) return '<div class="muted">No team metrics yet.</div>';
  const teams = Object.keys(an.teams || {});
  const names = teams.length ? teams : pt[keys[0]].ranking.map(r => r.team);
  const lookup = {};
  keys.forEach(k => { lookup[k] = {}; pt[k].ranking.forEach(r => { lookup[k][r.team] = r; }); });
  const first = (an.teams || {})[names[0]] ? null : null;
  const rows = names.map(t => {
    const profile = ((an.teams || {})[t] || {}).profile || {};
    return { _href: teamHref(t), cells: [{ v: t, html: teamLink(t) }].concat(keys.map(k => {
      const r = lookup[k][t] || (profile[k] ? { value: profile[k].v, pct: profile[k].pct } : null);
      const pv = r ? rawPct(k, r.pct) : null;
      const fmt = (pt[k] || {}).fmt || (teamMetricDef(k) || {}).fmt;
      return { v: isNum(pv) ? pv : -1, html: isNum(pv)
        ? '<span class="heat-cell" style="background:' + pctColor(pv) + '" title="' + esc((pt[k].label || k) + ': ' + fmtMetric(r.value, fmt)) + '">' + Math.round(pv) + '</span>'
        : '<span class="heat-cell empty">—</span>', align: 'center' };
    })) };
  });
  const cols = [{ label: 'Club' }].concat(keys.map(k => ({ label: (pt[k].label || (teamMetricDef(k) || {}).label || k), align: 'center', title: (teamMetricDef(k) || {}).desc || '' })));
  void first;
  return tableHTML(cols, rows, { compact: true, sticky: true });
}

function teamRankCard(an) {
  const pt = (an.performers || {}).teams || {};
  const keys = (an.team_metrics || []).map(m => m.key).filter(k => pt[k]);
  Object.keys(pt).forEach(k => { if (keys.indexOf(k) < 0) keys.push(k); });
  const groups = [];
  keys.forEach(k => {
    const m = teamMetricDef(k) || { group: 'Other', label: (pt[k] || {}).label || k };
    let g = groups.find(x => x.name === (m.group || 'Other'));
    if (!g) { g = { name: m.group || 'Other', items: [] }; groups.push(g); }
    g.items.push({ key: k, label: m.label || k });
  });
  const opts = groups.map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + '</option>').join('') + '</optgroup>').join('');
  return '<div class="card"><div class="card-header">Team rankings <span class="card-sub">Every club on one metric; bars coloured by percentile (red = best).</span>' +
    (keys.length ? '<span class="an-ctl"><select id="an-team-metric" class="team-select an-select">' + opts + '</select></span>' : '') + '</div>' +
    (keys.length ? '<div id="an-team-desc" class="an-desc"></div><div class="grid-2 an-rank"><div id="an-team-chart"></div><div id="an-team-table"></div></div>' : '<div class="muted">No team rankings yet.</div>') +
    '<div class="card-header">Style map <span class="card-sub">Percentile of each club on the headline team metrics: red = more of it, blue = less. Hover a cell for the value; click a row for the club.</span></div>' +
    '<div id="an-style-map">' + styleMap(an) + '</div></div>';
}

// ── 5. attack against defence; points against expected points ──────────────

function teamPoints(an) {
  const out = {};
  Object.keys(an.teams || {}).forEach(t => {
    const rds = (an.teams[t] || {}).rounds || [];
    out[t] = { pts: rds.reduce((s, r) => s + (r.pts || 0), 0), xpts: rds.reduce((s, r) => s + (r.xpts || 0), 0), n: rds.length };
  });
  const table = D().table || {};
  (table.standings || table.overall || []).forEach(r => { if (!out[r.team] || !out[r.team].n) out[r.team] = { pts: r.pts || 0, xpts: null, n: r.played || 0 }; });
  return out;
}

function median(arr) {
  const a = arr.filter(isNum).slice().sort((x, y) => x - y);
  if (!a.length) return null;
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
}

function renderScatter(an) {
  const xf = teamRanking('xg_for'), xa = teamRanking('xg_against');
  if (!xf.length || !xa.length) { setHTML('an-scatter', '<div class="muted">xG for and against are not both available yet.</div>'); return; }
  const rankA = {}, rankD = {};
  xf.forEach((r, i) => { rankA[r.team] = { v: r.value, rank: i + 1 }; });
  xa.forEach((r, i) => { rankD[r.team] = { v: r.value, rank: i + 1 }; });
  const pts = teamPoints(an);
  const teams = Object.keys(rankA).filter(t => rankD[t]);
  const maxPts = Math.max.apply(null, teams.map(t => (pts[t] || {}).pts || 0).concat([1]));
  const mx = median(teams.map(t => rankA[t].v)), my = median(teams.map(t => rankD[t].v));
  const n = teams.length;
  plot('an-scatter', [{
    type: 'scatter', mode: 'markers+text', x: teams.map(t => rankA[t].v), y: teams.map(t => rankD[t].v),
    text: teams.map(t => t), textposition: 'top center', textfont: { size: 10, color: '#c9d1d9' },
    marker: { size: teams.map(t => 8 + 22 * (((pts[t] || {}).pts || 0) / maxPts)), color: teams.map(t => pctColor(50 + 50 * ((rankD[t].rank - rankA[t].rank) / Math.max(1, n - 1)))), opacity: 0.85, line: { color: '#0d1117', width: 1 } },
    customdata: teams.map(t => [rankA[t].rank, rankD[t].rank, (pts[t] || {}).pts || 0, n]),
    hovertemplate: '<b>%{text}</b><br>xG for %{x:.2f} (#%{customdata[0]} of %{customdata[3]})<br>xG against %{y:.2f} (#%{customdata[1]} of %{customdata[3]})<br>%{customdata[2]} points<extra></extra>'
  }], layout({
    margin: { l: 55, r: 20, t: 20, b: 50 },
    xaxis: { title: 'xG for per match →', zeroline: false }, yaxis: { title: 'xG against per match (better ↑)', autorange: 'reversed', zeroline: false },
    shapes: [
      { type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } },
      { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }
    ],
    annotations: [{ x: 1, y: 1, xref: 'paper', yref: 'paper', text: 'strong both ways', showarrow: false, font: { size: 9, color: C.text3 }, xanchor: 'right', yanchor: 'top' },
                  { x: 0, y: 0, xref: 'paper', yref: 'paper', text: 'weak both ways', showarrow: false, font: { size: 9, color: C.text3 }, xanchor: 'left', yanchor: 'bottom' }]
  }));
}

function renderXpts(an) {
  const pts = teamPoints(an);
  const teams = Object.keys(pts).filter(t => isNum(pts[t].xpts) && pts[t].n > 0);
  if (!teams.length) { setHTML('an-xpts', '<div class="muted">No expected points yet.</div>'); return; }
  teams.sort((a, b) => (pts[b].pts - pts[b].xpts) - (pts[a].pts - pts[a].xpts));
  plot('an-xpts', [
    { type: 'bar', name: 'Points', x: teams, y: teams.map(t => pts[t].pts), marker: { color: teams.map(t => pts[t].pts >= pts[t].xpts ? C.green : C.red), opacity: 0.8 },
      hovertemplate: '%{x}: %{y} points<extra></extra>' },
    { type: 'scatter', mode: 'markers', name: 'Expected points (xPts)', x: teams, y: teams.map(t => pts[t].xpts), marker: { symbol: 'diamond', size: 11, color: '#e6edf3', line: { color: '#0d1117', width: 1 } },
      customdata: teams.map(t => pts[t].pts - pts[t].xpts), hovertemplate: '%{x}: %{y:.1f} xPts (luck %{customdata:+.1f})<extra></extra>' }
  ], layout({
    showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 45, r: 15, t: 30, b: 90 },
    xaxis: { tickangle: -45, tickfont: { size: 10 } }, yaxis: { title: 'Points', rangemode: 'tozero' }, bargap: 0.3
  }));
}

function chartsCard() {
  return '<div class="grid-2"><div class="card"><div class="card-header">Attack against defence <span class="card-sub">xG for and against per match; marker size = points; dotted lines at the medians; colour = defence rank against attack rank.</span></div><div id="an-scatter" style="height:460px"></div></div>' +
    '<div class="card"><div class="card-header">Points against expected points <span class="card-sub">Bars = points won (green when above xPts); diamonds = expected points from each match\'s xG; sorted luckiest first.</span></div><div id="an-xpts" style="height:460px"></div></div></div>';
}

// ── 6. form ────────────────────────────────────────────────────────────────

function formCard(an) {
  const teams = Object.keys(an.teams || {}).filter(t => ((an.teams[t] || {}).form || []).length);
  if (!teams.length) return '<div class="card"><div class="card-header">Form</div><div class="muted">No recent matches yet.</div></div>';
  const rows = teams.map(t => {
    const f = (an.teams[t].form || []).slice(0, 6);
    const chron = f.slice().reverse();
    const sum = k => f.reduce((s, m) => s + (isNum(m[k]) ? m[k] : 0), 0);
    const ptsW = f.reduce((s, m) => s + (isNum(m.pts) ? m.pts : (m.res === 'W' ? 3 : m.res === 'D' ? 1 : 0)), 0);
    const xpts = f.some(m => isNum(m.xpts)) ? sum('xpts') : null;
    const xgd = f.some(m => isNum(m.xg) && isNum(m.xga)) ? sum('xg') - sum('xga') : null;
    const chips = '<span class="form">' + chron.map(m => '<span class="form-chip form-' + esc(m.res || 'D') + '" title="' + esc((m.ha === 'A' ? '@ ' : 'v ') + m.opp + ' ' + m.gf + '–' + m.ga + (isNum(m.xg) ? ' · xG ' + num(m.xg, 2) + '–' + num(m.xga, 2) : '')) + '">' + esc(m.res || '') + '</span>').join('') + '</span>';
    const spark = chron.map(m => isNum(m.xg) ? num(m.xg, 1) : '—').join(' · ');
    return { _href: teamHref(t), cells: [
      { v: t, html: teamLink(t) }, { v: ptsW, html: chips, align: 'center' }, { v: f.length, align: 'right' },
      { v: ptsW, html: '<strong>' + ptsW + '</strong>', align: 'right' },
      { v: isNum(xpts) ? xpts : -1, html: isNum(xpts) ? num(xpts, 1) : '—', align: 'right' },
      { v: isNum(xpts) ? ptsW - xpts : -99, html: isNum(xpts) ? '<span class="' + (ptsW - xpts >= 1 ? 'danger' : ptsW - xpts <= -1 ? '' : 'safe') + '">' + signed(ptsW - xpts, 1) + '</span>' : '—', align: 'right' },
      { v: isNum(xgd) ? xgd : -99, html: isNum(xgd) ? signed(xgd, 2) : '—', align: 'right' },
      { v: '', html: '<span class="an-spark">' + esc(spark) + '</span>', align: 'left' }
    ] };
  }).sort((a, b) => b.cells[3].v - a.cells[3].v || b.cells[6].v - a.cells[6].v);
  return '<div class="card"><div class="card-header">Form <span class="card-sub">The last six matches, oldest to newest; points, expected points and the xG difference over that window.</span></div>' +
    '<div id="an-form">' + tableHTML([
      { label: 'Club' }, { label: 'Last six', align: 'center' }, { label: 'P', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'xPts', align: 'right' },
      { label: 'Luck', align: 'right', title: 'Points minus expected points over the window' }, { label: 'xG diff', align: 'right' }, { label: 'xG by match', align: 'left', sortable: false }
    ], rows, { compact: true }) + '</div></div>';
}

// ── the tab ────────────────────────────────────────────────────────────────

function renderAnalytics() {
  const an = D().analytics;
  const root = document.getElementById('analytics-root');
  if (!root) return;
  if (!an || (!(an.rounds || []).length && !Object.keys(an.teams || {}).length && !Object.keys((an.performers || {}).players || {}).length)) {
    root.innerHTML = '<div class="card"><div class="card-header">Analytics</div><div class="muted">No analytics for this competition yet: it needs played matches with player data.</div></div>';
    return;
  }
  const meta = [];
  if (an.season) meta.push(esc(an.season));
  if (an.minutes_floor) meta.push('percentiles over ' + an.minutes_floor + '+ minutes');
  if (an.updated_at) meta.push('updated ' + esc(FH.fmtStamp(an.updated_at)));
  root.innerHTML = '<div class="an-meta">' + meta.join(' · ') + '</div>' +
    totwCard(an) + seasonXICard(an) + performersCard(an) + teamRankCard(an) + chartsCard() + formCard(an);

  const roundSel = document.getElementById('an-round');
  if (roundSel) { roundSel.onchange = () => renderRound(an); renderRound(an); }
  const basisSel = document.getElementById('an-basis');
  if (basisSel) { basisSel.onchange = () => renderSeasonXI(an); renderSeasonXI(an); }
  const perfSel = document.getElementById('an-perf-metric');
  if (perfSel) {
    const pp = (an.performers || {}).players || {};
    if (pp.rating) perfSel.value = 'rating'; else if (pp.npxg_xa_90) perfSel.value = 'npxg_xa_90';
    perfSel.onchange = () => renderPerformers(an); renderPerformers(an);
  }
  const teamSel = document.getElementById('an-team-metric');
  if (teamSel) {
    const pt = (an.performers || {}).teams || {};
    if (pt.xg_for) teamSel.value = 'xg_for';
    teamSel.onchange = () => renderTeamRanking(an); renderTeamRanking(an);
  }
  wireRowLinks('an-style-map');
  sortableIn('an-style-map');
  renderScatter(an);
  renderXpts(an);
  wireRowLinks('an-form');
  sortableIn('an-form');
}

FH.renderAnalytics = renderAnalytics;
FH.drawXI = drawXI;
FH.xiPoints = xiPoints;
FH.ratingColor = ratingColor;
FH.halfPitchVertical = halfPitchVertical;
FH.teamPctIsGoodness = pctIsGoodness;
})(window.FH);
