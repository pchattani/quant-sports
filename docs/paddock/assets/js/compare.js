/* The Quant Paddock — compare two drivers (#/compare/drivers/<a>/<b>) or two teams
 * (#/compare/teams/<a>/<b>); #/compare alone shows the pickers.
 *
 * Drivers: identity cards, a verdict strip (who wins more of the percentile metrics,
 * and the biggest gaps each way), a radar, the full catalogue with gap bars and
 * percentile pills, the races they shared (by season), Elo histories overlaid, and
 * the two careers side by side. Teams: the same furniture over the team catalogue,
 * plus car pace overlaid, pit crews, reliability and points. */
(function (PD) {
'use strict';

const { esc, num, pct, signed, isNum, card, muted, tableHTML, sortable, pctPill, statTile, plot, layout, C } = PD;
const PG = () => PD.pg;
const CA = C.blue, CB = C.orange;

function divergingBar(gap) {
  if (!PG().has(gap)) return '<span class="cmp-gap" title="no percentile on one side"></span>';
  const w = Math.min(50, Math.abs(gap) / 2);
  return '<span class="cmp-gap" title="' + signed(gap, 0) + ' percentile points"><span class="' + (gap >= 0 ? 'a' : 'b') + '" style="width:' + w + '%"></span></span>';
}

/* Verdict strip and the two metric-table orders, from metrics and two {values, pct}. */
function verdictAndTables(metrics, A, B, nameA, nameB, scopeNote) {
  const has = PG().has;
  const comparable = metrics.map(m => ({ m: m, a: (A.pct || {})[m.key], b: (B.pct || {})[m.key] })).filter(x => has(x.a) && has(x.b)).map(x => Object.assign(x, { gap: x.a - x.b }));
  let verdict;
  if (!comparable.length) verdict = muted('No metric has a percentile for both.');
  else {
    const wa = comparable.filter(x => x.gap > 0).length, wb = comparable.filter(x => x.gap < 0).length, lv = comparable.length - wa - wb, n = comparable.length;
    const topA = comparable.filter(x => x.gap > 0).sort((x, y) => y.gap - x.gap).slice(0, 3);
    const topB = comparable.filter(x => x.gap < 0).sort((x, y) => x.gap - y.gap).slice(0, 3);
    const say = (list, who) => list.length ? '<strong>' + esc(who) + '</strong>: ' + list.map(x => '+' + Math.round(Math.abs(x.gap)) + ' pct on ' + esc(x.m.label)).join('; ') : '<strong>' + esc(who) + '</strong>: leads on nothing';
    verdict = '<div class="cmp-verdict"><div class="cmp-verdict-side a">' + say(topA, nameA) + '</div>' +
      '<div class="cmp-verdict-mid"><div class="cmp-score"><span class="a">' + wa + '</span><span class="dash">–</span><span class="b">' + wb + '</span></div>' +
      '<div class="cmp-wins"><span class="a" style="width:' + (100 * wa / n) + '%"></span><span class="t" style="width:' + (100 * lv / n) + '%"></span><span class="b" style="width:' + (100 * wb / n) + '%"></span></div>' +
      '<div class="cmp-score-sub">metrics won of ' + n + (lv ? ' · ' + lv + ' level' : '') + (scopeNote ? ' · ' + scopeNote : '') + '</div></div>' +
      '<div class="cmp-verdict-side b">' + say(topB, nameB) + '</div></div>';
  }
  const row = (m, withGroup) => {
    const va = (A.values || {})[m.key], vb = (B.values || {})[m.key];
    const qa = (A.pct || {})[m.key], qb = (B.pct || {})[m.key];
    const gap = has(qa) && has(qb) ? qa - qb : null;
    const better = has(va) && has(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    const cells = [{ v: m.label, html: PG().glossLink(m.key, esc(m.label)) + (m.lower ? ' <span class="muted-inline">↓</span>' : '') }];
    if (withGroup) cells.push({ v: m.group, html: '<span class="muted-inline">' + esc(m.group) + '</span>' });
    cells.push({ v: has(va) ? va : -1e9, html: (better === 'a' ? '<strong>' : '') + PG().fmt(m, va) + (better === 'a' ? '</strong>' : ''), align: 'right' });
    cells.push({ v: has(qa) ? qa : -1, html: pctPill(qa), align: 'center' });
    cells.push({ v: gap === null ? -1 : Math.abs(gap), html: divergingBar(gap), align: 'center' });
    cells.push({ v: has(qb) ? qb : -1, html: pctPill(qb), align: 'center' });
    cells.push({ v: has(vb) ? vb : -1e9, html: (better === 'b' ? '<strong>' : '') + PG().fmt(m, vb) + (better === 'b' ? '</strong>' : ''), align: 'right' });
    return { cells: cells };
  };
  const cols = wg => [{ label: 'Metric' }].concat(wg ? [{ label: 'Group' }] : []).concat([{ label: nameA, align: 'right' }, { label: 'Pct', align: 'center' },
    { label: 'Gap', align: 'center', title: 'Percentile-point gap: blue when ' + nameA + ' leads, orange when ' + nameB + ' does' }, { label: 'Pct', align: 'center' }, { label: nameB, align: 'right' }]);
  const byGroup = PG().groups(metrics).map(g => '<div class="cmp-group-head">' + esc(g.name) + '</div>' + tableHTML(cols(false), g.items.map(m => row(m, false)), { compact: true })).join('');
  const flat = metrics.map(m => ({ m: m, g: has((A.pct || {})[m.key]) && has((B.pct || {})[m.key]) ? Math.abs(A.pct[m.key] - B.pct[m.key]) : -1 })).sort((x, y) => y.g - x.g);
  const byGap = tableHTML(cols(true), flat.map(x => row(x.m, true)), { compact: true, sticky: true });
  return { verdict: verdict, byGroup: byGroup, byGap: byGap, n: comparable.length };
}

function wireMetricTable(el, t) {
  const sel = document.getElementById('cmp-metric-mode');
  const draw = () => { document.getElementById('cmp-metrics').innerHTML = sel.value === 'gap' ? t.byGap : t.byGroup; sortable('cmp-metrics'); };
  sel.onchange = draw;
  draw();
}
const METRIC_CARD = sub => '<div class="card"><div class="card-header">Every metric <span class="card-sub">' + sub + '</span><label class="pg-ctl">order <select id="cmp-metric-mode"><option value="group">by group</option><option value="gap">by size of gap</option></select></label></div><div id="cmp-metrics"></div></div>';

function pickerHTML(kind, a, b, opts) {
  const sel = (id, cur) => '<select id="' + id + '" style="min-width:220px"><option value="">— pick —</option>' + opts.map(o => '<option value="' + esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>';
  return '<div class="card"><div class="card-header">Compare ' + kind + ' <span class="card-sub">Pick two; the address updates so a comparison can be shared.</span>' +
    '<span class="pg-ctl">' + PG().toggle('cmp-kind', [['drivers', 'Drivers'], ['teams', 'Teams']], kind) + '</span></div>' +
    '<div class="controls"><span class="cmp-pill-a"></span>' + sel('cmp-a', a) + '<span class="muted-inline">v</span><span class="cmp-pill-b"></span>' + sel('cmp-b', b) + '<button type="button" id="cmp-swap" class="pg-search" style="min-width:0;cursor:pointer">⇄ swap</button></div></div>';
}
function wirePicker(el, kind, a, b) {
  const go = () => { const x = document.getElementById('cmp-a').value, y = document.getElementById('cmp-b').value; if (x && y && x !== y) location.hash = '#/compare/' + kind + '/' + x + '/' + y; };
  document.getElementById('cmp-a').onchange = go; document.getElementById('cmp-b').onchange = go;
  document.getElementById('cmp-swap').onclick = () => { if (a && b) location.hash = '#/compare/' + kind + '/' + b + '/' + a; };
  PG().wireToggle(el, 'cmp-kind', v => { if (v !== kind) location.hash = '#/compare/' + v; });
}

// ── drivers ────────────────────────────────────────────────────────────────

/* A driver's season record: the picked season if they raced in it, else their latest season with a catalogue. */
function driverSeason(id, y, career) {
  return PD.load(y + '/drivers.json').then(dj => {
    if (dj && dj.drivers && dj.drivers[id]) return { year: y, cat: dj, d: dj.drivers[id] };
    const yrs = ((career || {}).seasons || []).map(s => s.year).filter(v => v !== y).sort((p, q) => q - p);
    const tryY = i => i >= yrs.length || i > 3 ? Promise.resolve({ year: null, cat: null, d: null }) : PD.load(yrs[i] + '/drivers.json').then(d2 => (d2 && d2.drivers && d2.drivers[id] ? { year: yrs[i], cat: d2, d: d2.drivers[id] } : tryY(i + 1)));
    return tryY(0);
  });
}

function renderCompareDrivers(el, params, state) {
  const a = params.a || '', b = params.b || '';
  const y = state.year || PD.currentSeason();
  el.innerHTML = '<div id="cmp-pick"></div><div id="cmp-body"></div>';
  return PD.load(y + '/drivers.json').then(dj => {
    if (!PG().alive(el)) return null;
    const ids = Object.keys(((dj || {}).drivers) || {}).concat(Object.keys(PD.NAMES.drivers));
    const uniq = Array.from(new Set(ids.concat([a, b].filter(Boolean))));
    const opts = uniq.map(k => [k, PD.driverName(k) + (((dj || {}).drivers || {})[k] ? ' (' + PD.teamName(dj.drivers[k].team) + ')' : '')]).sort((p, q) => p[1].localeCompare(q[1]));
    document.getElementById('cmp-pick').innerHTML = pickerHTML('drivers', a, b, opts);
    wirePicker(el, 'drivers', a, b);
    if (!a || !b) { document.getElementById('cmp-body').innerHTML = card('', '', muted('Pick two drivers. Teammates make the cleanest comparison: same car, same races.')); return null; }
    document.getElementById('cmp-body').innerHTML = muted('Loading…');
    return Promise.all([PD.load('drivers/' + a + '.json'), PD.load('drivers/' + b + '.json'), PD.load('elo.json'), PD.load(y + '/season.json')]).then(r1 => {
      const careers = [r1[0], r1[1]], elo = r1[2], season = r1[3];
      return Promise.all([driverSeason(a, y, careers[0]), driverSeason(b, y, careers[1])]).then(ss => {
        if (!PG().alive(el)) return;
        buildDrivers(el, [a, b], ss, careers, elo, season, y);
      });
    });
  });
}

function buildDrivers(el, ids, ss, careers, elo, season, y) {
  const has = PG().has;
  const names = ids.map((id, i) => (ss[i].d && ss[i].d.name) || (careers[i] && careers[i].name) || PD.driverName(id));
  const short = ids.map(id => PD.driverSurname(id));
  const sameSeason = ss[0].year && ss[0].year === ss[1].year;
  const metrics = ((ss[0].cat || ss[1].cat || {}).metrics) || [];
  const stand = {};
  (((season || {}).standings || {}).drivers || []).forEach(s => { stand[s.driver] = s; });
  const idCard = i => {
    const id = ids[i], d = ss[i].d || {}, car = careers[i] || {}, info = PD.NAMES.drivers[id] || {};
    const tot = car.totals || {};
    const seasons = car.seasons || [];
    const sum = k => seasons.reduce((s, r) => s + (r[k] || 0), 0);
    const st = ss[i].year === y ? (stand[id] || {}) : {};
    const age = PG().ageOf(car.dob);
    const e = (((elo || {}).current || {})[id] || {}).elo;
    const facts = [['Season', ss[i].year || '—'], ['Races', has(d.races) ? d.races : '—'], ['Points', has(st.points) ? num(st.points, 0) : '—'], ['Wins', has(st.wins) ? st.wins : '—'],
      ['Career starts', has(tot.races) ? tot.races : sum('races')], ['Career wins', has(tot.wins) ? tot.wins : sum('wins')], ['Titles', has(tot.titles) ? tot.titles : seasons.filter(s => s.pos === 1).length], ['Elo', isNum(e) ? num(e, 0) : '—']];
    return '<div class="cmp-id ' + (i ? 'b' : 'a') + '"><div class="pg-num" style="--team:' + esc(PD.teamColour(d.team || info.team)) + ';width:52px;height:52px;font-size:1.3rem">' + esc(info.number || PD.driverCode(id)) + '</div><div class="cmp-id-body">' +
      '<div class="cmp-id-name">' + PD.driverLink(id, { name: names[i] }) + '</div><div class="cmp-id-sub">' + (d.team ? PD.teamLink(d.team) : '') + (car.nationality ? ' · ' + esc(car.nationality) : '') + (age !== null ? ' · age ' + age : '') + '</div>' +
      '<div class="cmp-id-facts">' + facts.map(f => '<div class="cmp-fact"><span>' + f[0] + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div></div>';
  };
  const t = verdictAndTables(metrics, ss[0].d || {}, ss[1].d || {}, short[0], short[1], sameSeason ? 'field percentiles, ' + ss[0].year : 'different seasons (' + (ss[0].year || '—') + ' v ' + (ss[1].year || '—') + '): each percentile is against its own field');
  let h = '<div class="cmp-ids">' + idCard(0) + idCard(1) + '</div>';
  h += '<div class="card"><div class="card-header">Verdict <span class="card-sub">Who wins each catalogue metric on field percentile, and the three biggest gaps each way.</span></div>' + t.verdict + '</div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Eight headline metrics, field percentiles.</span></div><div id="cmp-radar" style="height:400px"></div></div>' +
    '<div class="card"><div class="card-header">Races together <span class="card-sub" id="cmp-shared-sub">Head to head in every season both raced (from each season\'s race logs).</span></div><div id="cmp-shared">' + muted('Loading…') + '</div></div></div>';
  h += METRIC_CARD('The whole driver catalogue: value, field percentile and the gap in percentile points. Bold marks the better raw figure.');
  h += '<div class="card"><div class="card-header">Elo through their careers <span class="card-sub">Field Elo after every race (solid) and Elo against the teammate (dotted).</span></div><div id="cmp-elo" style="height:360px"></div></div>';
  h += '<div class="card"><div class="card-header">Careers <span class="card-sub">Totals from every world championship start, then season by season.</span></div><div id="cmp-career"></div></div>';
  h += '<div class="card"><div class="muted">' + ids.map((id, i) => PD.driverLink(id, { name: names[i] + ' →' })).join(' &nbsp;·&nbsp; ') + ' &nbsp;·&nbsp; <a href="#/lab">Driver lab →</a> &nbsp;·&nbsp; <a href="#/glossary">Glossary →</a></div></div>';
  document.getElementById('cmp-body').innerHTML = h;

  const axes = PG().headline(metrics, ['race_pace', 'quali_pace', 'driver_effect', 'quali_driver_effect', 'overtakes_made', 'lap1_gain', 'tyre_mgmt', 'points_v_expected'], 8, true).map(m => ({ key: m.key, label: PG().shortLabel(m.label) }));
  PG().radar('cmp-radar', axes, [{ name: names[0] + (sameSeason ? '' : ' ' + ss[0].year), pct: (ss[0].d || {}).pct, colour: CA }, { name: names[1] + (sameSeason ? '' : ' ' + ss[1].year), pct: (ss[1].d || {}).pct, colour: CB }]);
  wireMetricTable(el, t);

  // Shared seasons: intersect career years, load each season's catalogue for the logs.
  const yearsOf = c => ((c || {}).seasons || []).map(s => s.year);
  let shared = yearsOf(careers[0]).filter(v => yearsOf(careers[1]).indexOf(v) >= 0);
  if (!shared.length && sameSeason) shared = [ss[0].year];
  shared.sort((p, q) => q - p);
  Promise.all(shared.map(yy => PD.load(yy + '/drivers.json'))).then(cats => {
    if (!PG().alive(el)) return;
    const rows = [], tot = { q: [0, 0], r: [0, 0], p: [0, 0], n: 0 };
    let detail = null;
    cats.forEach((cat, i) => {
      const D = (cat || {}).drivers || {};
      const da = D[ids[0]], db = D[ids[1]];
      const ca = (careers[0].seasons || []).find(s => s.year === shared[i]) || {}, cb = (careers[1].seasons || []).find(s => s.year === shared[i]) || {};
      if (da && db) {
        const hh = PG().h2h(da.log, db.log);
        tot.q[0] += hh.quali[0]; tot.q[1] += hh.quali[1]; tot.r[0] += hh.race[0]; tot.r[1] += hh.race[1]; tot.p[0] += hh.points[0]; tot.p[1] += hh.points[1]; tot.n += hh.both;
        rows.push({ cells: [shared[i], { v: PD.teamName(da.team), html: PD.teamLink(da.team) + (da.team === db.team ? ' <span class="pg-tag good">teammates</span>' : ' v ' + PD.teamLink(db.team)) }, hh.both,
          { v: hh.quali[0] - hh.quali[1], html: '<span style="color:' + CA + '">' + hh.quali[0] + '</span>–<span style="color:' + CB + '">' + hh.quali[1] + '</span>' },
          { v: hh.race[0] - hh.race[1], html: '<span style="color:' + CA + '">' + hh.race[0] + '</span>–<span style="color:' + CB + '">' + hh.race[1] + '</span>' },
          { v: hh.points[0] - hh.points[1], html: num(hh.points[0], 0) + '–' + num(hh.points[1], 0) }] });
        if (!detail) detail = { year: shared[i], hh: hh };
      } else if (ca.year && cb.year) {
        rows.push({ cells: [shared[i], { v: '', html: PD.teamLink(ca.team) + ' v ' + PD.teamLink(cb.team) }, Math.min(ca.races || 0, cb.races || 0), { v: 0, html: '<span class="muted-inline">no log</span>' }, { v: 0, html: '<span class="muted-inline">no log</span>' }, { v: (ca.points || 0) - (cb.points || 0), html: num(ca.points, 0) + '–' + num(cb.points, 0) }] });
      }
    });
    const host = document.getElementById('cmp-shared');
    if (!rows.length) { host.innerHTML = muted('They never raced in the same season.'); return; }
    host.innerHTML = '<div class="pg-h2h">' + PG().h2hBar('Qualifying, all shared rounds with logs', tot.q[0], tot.q[1], CA, CB, short[0], short[1]) + PG().h2hBar('Race', tot.r[0], tot.r[1], CA, CB, short[0], short[1]) + '</div>' +
      tableHTML([{ label: 'Season' }, { label: 'Cars' }, { label: 'Rounds', align: 'right' }, { label: 'Quali', align: 'right' }, { label: 'Race', align: 'right' }, { label: 'Points', align: 'right' }], rows, { compact: true }) +
      (detail ? '<div class="cmp-group-head">' + detail.year + ' round by round</div>' + tableHTML([{ label: 'Rd', align: 'right' }, { label: 'Race' }, { label: 'Q ' + short[0], align: 'right' }, { label: 'Q ' + short[1], align: 'right' }, { label: short[0], align: 'right' }, { label: short[1], align: 'right' }],
        detail.hh.rows.map(p => ({ _href: PD.raceHref(detail.year, p[0].round), cells: [p[0].round, p[0].name || '', { v: p[0].quali_pos, html: isNum(p[0].quali_pos) ? String(p[0].quali_pos) : '—' }, { v: p[1].quali_pos, html: isNum(p[1].quali_pos) ? String(p[1].quali_pos) : '—' },
          { v: p[0].pos, html: PG().posHTML(p[0].pos, p[0].status) }, { v: p[1].pos, html: PG().posHTML(p[1].pos, p[1].status) }] })), { compact: true }) : '');
    sortable(host);
  });

  // Elo overlay on a calendar axis.
  const eloTr = [];
  careers.forEach((c, i) => {
    const e = (c || {}).elo || [];
    if (!e.length) return;
    const x = e.map(r => r[0] + (r[1] - 1) / 25), lab = e.map(r => r[0] + ' R' + r[1]);
    eloTr.push({ type: 'scatter', mode: 'lines', name: names[i] + ' field', x: x, y: e.map(r => r[2]), text: lab, line: { color: i ? CB : CA, width: 2 }, hovertemplate: '%{text}: %{y:.0f}<extra>' + esc(short[i]) + ' field</extra>' });
    eloTr.push({ type: 'scatter', mode: 'lines', name: names[i] + ' v teammate', x: x, y: e.map(r => r[3]), text: lab, line: { color: i ? CB : CA, width: 1.2, dash: 'dot' }, hovertemplate: '%{text}: %{y:.0f}<extra>' + esc(short[i]) + ' v teammate</extra>' });
  });
  if (eloTr.length) plot('cmp-elo', eloTr, layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 55, r: 15, t: 30, b: 40 }, xaxis: { title: 'Season', tickformat: 'd' }, yaxis: { title: 'Elo' } }));
  else document.getElementById('cmp-elo').innerHTML = muted('No Elo history for either driver.');

  // Careers.
  const totals = careers.map(c => {
    const s = (c || {}).seasons || [], tt = (c || {}).totals || {};
    const sum = k => s.reduce((acc, r) => acc + (r[k] || 0), 0);
    return { starts: has(tt.races) ? tt.races : sum('races'), wins: has(tt.wins) ? tt.wins : sum('wins'), podiums: has(tt.podiums) ? tt.podiums : sum('podiums'), poles: has(tt.poles) ? tt.poles : sum('poles'),
      points: has(tt.points) ? tt.points : sum('points'), titles: has(tt.titles) ? tt.titles : s.filter(r => r.pos === 1).length, seasons: s.length };
  });
  const lines = [['Seasons', 'seasons'], ['Starts', 'starts'], ['Titles', 'titles'], ['Wins', 'wins'], ['Podiums', 'podiums'], ['Poles', 'poles'], ['Points', 'points']];
  const rate = (k, i) => totals[i].starts ? totals[i][k] / totals[i].starts : null;
  const bars = lines.map(l => {
    const va = totals[0][l[1]], vb = totals[1][l[1]], mx = Math.max(va || 0, vb || 0) || 1;
    const better = va !== vb ? (va > vb ? 'a' : 'b') : '';
    return '<div class="cmp-h2h-label">' + l[0] + (['wins', 'podiums', 'poles'].indexOf(l[1]) >= 0 ? ' <span class="muted-inline">(' + pct(rate(l[1], 0), 0) + ' v ' + pct(rate(l[1], 1), 0) + ' of starts)</span>' : '') + '</div><div class="cmp-h2h-row">' +
      '<div class="l"><span class="num">' + num(va, 0) + '</span><div class="cmp-h2h-bar left"><div style="width:' + 100 * (va || 0) / mx + '%"></div></div></div>' +
      '<div class="cmp-h2h-val' + (better ? ' win' : '') + '">' + (better ? esc(better === 'a' ? short[0] : short[1]) : 'level') + '</div>' +
      '<div class="r"><span class="num">' + num(vb, 0) + '</span><div class="cmp-h2h-bar right"><div style="width:' + 100 * (vb || 0) / mx + '%"></div></div></div></div>';
  }).join('');
  const seasonsTable = i => tableHTML([{ label: 'Year' }, { label: 'Team' }, { label: 'Races', align: 'right' }, { label: 'W', align: 'right' }, { label: 'Pod', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Pos', align: 'right' }],
    (((careers[i] || {}).seasons) || []).slice().sort((p, q) => q.year - p.year).map(s => [s.year, { v: PD.teamName(s.team), html: PD.teamLink(s.team) }, s.races, s.wins, s.podiums, { v: s.points, html: num(s.points, 0) }, { v: s.pos || 99, html: s.pos ? String(s.pos) : '—' }]), { compact: true });
  document.getElementById('cmp-career').innerHTML = '<div class="cmp-h2h">' + bars + '</div><div class="pg-split"><div><div class="cmp-group-head"><span class="cmp-pill-a"></span>' + esc(names[0]) + '</div>' + seasonsTable(0) + '</div><div><div class="cmp-group-head"><span class="cmp-pill-b"></span>' + esc(names[1]) + '</div>' + seasonsTable(1) + '</div></div>';
  sortable('cmp-career');
}

// ── teams ──────────────────────────────────────────────────────────────────

function renderCompareTeams(el, params, state) {
  const a = params.a || '', b = params.b || '';
  const y = state.year || PD.currentSeason();
  el.innerHTML = '<div id="cmp-pick"></div><div id="cmp-body"></div>';
  return PG().season(y).then(res => {
    if (!PG().alive(el)) return;
    const drivers = res[0], teams = res[1], season = res[2];
    const T = ((teams || {}).teams) || {};
    const ids = Array.from(new Set(Object.keys(T).concat(Object.keys((season || {}).teams || {})).concat([a, b].filter(Boolean))));
    document.getElementById('cmp-pick').innerHTML = pickerHTML('teams', a, b, ids.map(k => [k, PD.teamName(k)]).sort((p, q) => p[1].localeCompare(q[1])));
    wirePicker(el, 'teams', a, b);
    if (!a || !b) { document.getElementById('cmp-body').innerHTML = card('', '', muted('Pick two teams from the ' + y + ' season.')); return; }
    buildTeams(el, [a, b], T, teams, drivers, season, y);
  });
}

function buildTeams(el, ids, T, teams, drivers, season, y) {
  const has = PG().has;
  const names = ids.map(id => (T[id] || {}).name || PD.teamName(id));
  const metrics = (teams || {}).metrics || [];
  const stand = {};
  (((season || {}).standings || {}).constructors || []).forEach(s => { stand[s.team] = s; });
  const champ = (((season || {}).championship || {}).constructors) || {};
  const drvOf = id => ((((season || {}).teams || {})[id] || {}).drivers) || Object.keys(((drivers || {}).drivers) || {}).filter(k => drivers.drivers[k].team === id);
  const idCard = i => {
    const id = ids[i], t = T[id] || {}, s = stand[id] || {}, ch = champ[id], pit = t.pit || {};
    const facts = [['Position', s.pos ? PD.ordinal(s.pos) : '—'], ['Points', has(s.points) ? num(s.points, 0) : '—'], ['Wins', s.wins || 0], ['Title', ch ? pct(ch.p_title) : '—'],
      ['Median stop', isNum(pit.median_ms) ? num(pit.median_ms / 1000, 2) + 's' : '—'], ['DNFs', (t.log || []).reduce((acc, r) => acc + (r.dnfs || 0), 0)]];
    return '<div class="cmp-id ' + (i ? 'b' : 'a') + '"><div class="pg-num" style="--team:' + esc(PD.teamColour(id)) + ';width:52px;height:52px;font-size:0.95rem">' + esc(String(names[i]).slice(0, 3).toUpperCase()) + '</div><div class="cmp-id-body">' +
      '<div class="cmp-id-name">' + PD.teamLink(id, { name: names[i] }) + '</div><div class="cmp-id-sub">' + drvOf(id).map(d => PD.driverLink(d)).join(' · ') + '</div>' +
      '<div class="cmp-id-facts">' + facts.map(f => '<div class="cmp-fact"><span>' + f[0] + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div></div>';
  };
  const t = verdictAndTables(metrics, T[ids[0]] || {}, T[ids[1]] || {}, names[0], names[1], 'field percentiles, ' + y);
  let h = '<div class="cmp-ids">' + idCard(0) + idCard(1) + '</div>';
  h += '<div class="card"><div class="card-header">Verdict <span class="card-sub">Who wins each team metric on field percentile, and the three biggest gaps each way.</span></div>' + t.verdict + '</div>';
  h += '<div class="card"><div class="card-header">Car pace <span class="card-sub">The car effect by round from the decomposition, % of lap against the field (up = faster), ±1 se shaded.</span>' + PG().toggle('cmp-pace-kind', [['race', 'Race'], ['quali', 'Qualifying']], 'race') + '</div><div id="cmp-pace" style="height:360px"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Headline team metrics, field percentiles.</span></div><div id="cmp-radar" style="height:380px"></div></div>' +
    '<div class="card"><div class="card-header">Points <span class="card-sub">Cumulative constructors\' points by round.</span></div><div id="cmp-pts" style="height:380px"></div></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Pit crews <span class="card-sub">Median and best stationary time, share under 2.5 s, and every stop.</span></div><div id="cmp-pit"></div><div id="cmp-pit-chart" style="height:240px"></div></div>' +
    '<div class="card"><div class="card-header">Reliability <span class="card-sub">Retirements per round, cumulative.</span></div><div id="cmp-rel" style="height:320px"></div></div></div>';
  h += METRIC_CARD('The whole team catalogue: value, field percentile and the gap in percentile points.');
  document.getElementById('cmp-body').innerHTML = h;
  wireMetricTable(el, t);

  const axes = PG().headline(metrics, ['car_race_pace', 'car_quali_pace', 'top_speed', 'corner_speed', 'tyre_mgmt', 'pit_stop_ms', 'strategy_gain', 'dnf_rate'], 8, true).map(m => ({ key: m.key, label: PG().shortLabel(m.label) }));
  PG().radar('cmp-radar', axes, [{ name: names[0], pct: (T[ids[0]] || {}).pct, colour: CA }, { name: names[1], pct: (T[ids[1]] || {}).pct, colour: CB }]);

  const drawPace = kind => {
    const tr = [];
    ids.forEach((id, i) => { const rows = ((((season || {}).car_pace || {})[kind] || {})[id] || []).slice().sort((p, q) => p.round - q.round); if (rows.length) tr.push.apply(tr, PD.pg_bandTraces(rows, i ? CB : CA, names[i])); });
    if (tr.length) plot('cmp-pace', tr, layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 55, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: '% of lap v field (up = faster)', autorange: 'reversed' } }));
    else document.getElementById('cmp-pace').innerHTML = muted('No car-pace series.');
  };
  drawPace('race');
  PG().wireToggle(el, 'cmp-pace-kind', drawPace);

  const prog = (((season || {}).progression || {}).constructors) || {};
  const ptr = ids.map((id, i) => ({ type: 'scatter', mode: 'lines+markers', name: names[i], x: (prog[id] || []).map((v, k) => k + 1), y: prog[id] || [], line: { color: i ? CB : CA, width: 2 }, marker: { size: 5 }, hovertemplate: names[i] + ' after R%{x}: %{y}<extra></extra>' })).filter(tr => tr.y.length);
  if (ptr.length) plot('cmp-pts', ptr, layout({ showlegend: true, legend: { orientation: 'h', y: 1.1, font: { color: C.text2 } }, margin: { l: 50, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: 'Points', rangemode: 'tozero' } }));
  else {
    const lg = ids.map(id => ((T[id] || {}).log || []).slice().sort((p, q) => p.round - q.round));
    const tr2 = lg.map((l, i) => { let c = 0; return { type: 'scatter', mode: 'lines+markers', name: names[i], x: l.map(r => r.round), y: l.map(r => (c += r.points || 0)), line: { color: i ? CB : CA, width: 2 } }; }).filter(tr => tr.y.length);
    if (tr2.length) plot('cmp-pts', tr2, layout({ showlegend: true, legend: { orientation: 'h', y: 1.1 }, margin: { l: 50, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round' }, yaxis: { title: 'Points' } }));
    else document.getElementById('cmp-pts').innerHTML = muted('No points progression.');
  }

  const pits = ids.map(id => (T[id] || {}).pit || {});
  document.getElementById('cmp-pit').innerHTML = tableHTML([{ label: '' }, { label: names[0], align: 'right' }, { label: names[1], align: 'right' }], [
    ['Median stop', pits[0].median_ms, pits[1].median_ms, v => (isNum(v) ? num(v / 1000, 2) + 's' : '—'), true],
    ['Best stop', pits[0].best_ms, pits[1].best_ms, v => (isNum(v) ? num(v / 1000, 2) + 's' : '—'), true],
    ['Under 2.5 s', pits[0].p_under_2500, pits[1].p_under_2500, v => pct(v, 0), false],
    ['Stops', Array.isArray(pits[0].stops) ? pits[0].stops.length : pits[0].stops, Array.isArray(pits[1].stops) ? pits[1].stops.length : pits[1].stops, v => (isNum(v) ? String(v) : '—'), null]
  ].map(r => {
    const better = isNum(r[1]) && isNum(r[2]) && r[1] !== r[2] && r[4] !== null ? ((r[4] ? r[1] < r[2] : r[1] > r[2]) ? 0 : 1) : -1;
    return [r[0], { v: r[1], html: (better === 0 ? '<strong>' : '') + r[3](r[1]) + (better === 0 ? '</strong>' : '') }, { v: r[2], html: (better === 1 ? '<strong>' : '') + r[3](r[2]) + (better === 1 ? '</strong>' : '') }];
  }), { compact: true });
  const hist = (stops, i) => ({ type: 'histogram', name: names[i], x: stops.filter(v => isNum(v) && v > 0 && v < 15000).map(v => v / 1000), opacity: 0.6, xbins: { size: 0.2 }, marker: { color: i ? CB : CA }, hovertemplate: '%{x} s: %{y}<extra>' + esc(names[i]) + '</extra>' });
  const drawHist = arr => {
    if (!arr.some(a2 => a2.length)) { document.getElementById('cmp-pit-chart').innerHTML = muted('No individual stops recorded.'); return; }
    document.getElementById('cmp-pit-chart').innerHTML = '';
    plot('cmp-pit-chart', arr.map(hist), layout({ barmode: 'overlay', showlegend: true, legend: { orientation: 'h', y: 1.15, font: { color: C.text2 } }, margin: { l: 40, r: 10, t: 30, b: 40 }, xaxis: { title: 'Stationary time (s)' }, yaxis: { title: 'Stops' },
      shapes: [{ type: 'line', x0: 2.5, x1: 2.5, yref: 'paper', y0: 0, y1: 1, line: { color: C.yellow, dash: 'dot', width: 1.5 } }] }));
  };
  if (pits.every(p => Array.isArray(p.stops) && isNum(p.stops[0]))) drawHist(pits.map(p => p.stops));
  else {
    const rounds = (((season || {}).calendar) || []).filter(c => c.status === 'done').map(c => c.round);
    const drv = ids.map(drvOf);
    Promise.all(rounds.map(r => PD.load(y + '/races/' + r + '.json'))).then(races => {
      if (!PG().alive(el)) return;
      const out = [[], []];
      races.forEach(rc => (((rc || {}).pits) || []).forEach(p => { [0, 1].forEach(i => { if (drv[i].indexOf(p.driver) >= 0 && isNum(p.stop_ms)) out[i].push(p.stop_ms); }); }));
      drawHist(out);
    });
  }

  const rel = ids.map((id, i) => { const l = ((T[id] || {}).log || []).slice().sort((p, q) => p.round - q.round); let c = 0; return { type: 'scatter', mode: 'lines+markers', line: { shape: 'hv', color: i ? CB : CA, width: 2 }, name: names[i], x: l.map(r => r.round), y: l.map(r => (c += r.dnfs || 0)), hovertemplate: names[i] + ' after R%{x}: %{y} DNFs<extra></extra>' }; }).filter(tr => tr.x.length);
  if (rel.length) plot('cmp-rel', rel, layout({ showlegend: true, legend: { orientation: 'h', y: 1.1, font: { color: C.text2 } }, margin: { l: 45, r: 10, t: 30, b: 40 }, xaxis: { title: 'Round', dtick: 2 }, yaxis: { title: 'Cumulative retirements', rangemode: 'tozero', dtick: 1 } }));
  else document.getElementById('cmp-rel').innerHTML = muted('No per-round log.');
}

function renderCompare(el, params, state) {
  if (params.kind === 'teams') return renderCompareTeams(el, params, state);
  return renderCompareDrivers(el, params, state);
}

PD.route('compare-drivers', renderCompareDrivers);
PD.route('compare-teams', renderCompareTeams);
PD.route('compare', renderCompare);
})(window.PD);
