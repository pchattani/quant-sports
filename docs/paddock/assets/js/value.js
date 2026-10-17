/* The Quant Paddock — driver value (#/value[/<year>]).
 *
 * Driver value from the season's car/driver decomposition, in % of a lap (positive = faster): pace
 * above the team-mate (the driver effect, race and qualifying, with its standard error) and pace above
 * the field (the car's latest race-pace state plus the driver). No positions in F1. Constructors are
 * ranked by the car's latest race-pace state, with the season mean, qualifying and the change over
 * the last five rounds. Trend: pace above team-mate against last season.
 *
 * Data: data/<y>/value.json (1994 onward). */
(function (PD) {
'use strict';

const { esc, num, pct, signed, isNum, card, muted, tableHTML, sortable, pctPill } = PD;
const PG = () => PD.pg;

function rowsOf(cols, rows) {
  return (rows || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}
const pctLap = (v, d) => (isNum(v) ? signed(v, d === undefined ? 3 : d) + '%' : '—');
const band = (v, se) => (isNum(v) && isNum(se) ? '<span class="muted-inline">±' + num(se, 2) + '</span>' : '');

function render(el, params, state) {
  const y = PG().yearOf(params, state);
  el.innerHTML = muted('Loading…');
  return PD.load(y + '/value.json').then(d => {
    if (!PG().alive(el)) return;
    if (!PD.ok(d) || !d.drivers) {
      el.innerHTML = card('Driver value ' + y, '', '<div class="pad">' + PG().notBuilt('The ' + y + ' value table', d) +
        (y < 1994 ? ' <span class="muted-inline">The decomposition starts in 1994, when lap times begin.</span>' : '') + '</div>');
      return;
    }
    const D = rowsOf(d.driver_cols, d.drivers), T = rowsOf(d.team_cols, d.teams);
    const by = {};
    D.forEach(r => { by[r.id] = r; });
    const minR = d.min_races || 5;
    let h = '<div class="page-head"><div><h2>Driver value ' + y + '</h2><div class="ph-sub muted-inline">' + esc(d.unit || '') + '</div></div>' +
      '<div class="ph-nav"><a href="#/swap">Driver-swap simulator →</a> <a href="#/methodology/value">How it works →</a></div></div>';
    const list = (ids, key, label) => '<div class="pv-mini"><div class="pv-mini-h">' + esc(label) + '</div>' + ids.filter(id => by[id]).map((id, i) => {
      const r = by[id];
      return '<div class="pv-mini-r"><span class="pv-n">' + (i + 1) + '</span>' + PD.driverLink(id, r.name) + ' <span class="muted-inline">' + esc(PD.teamName(r.team)) + '</span><span class="pv-v">' + pctLap(r[key], 2) + '</span></div>';
    }).join('') + '</div>';
    h += card('The best drivers', 'By pace above the team-mate (the driver alone) and above the field (driver and car now); at least ' + minR + ' races.',
      '<div class="pv-best">' + list((d.best || {}).pace_tm || [], 'pace_tm', 'Pace above team-mate') + list((d.best || {}).pace_field || [], 'pace_field', 'Pace above the field') + '</div>');
    const dcols = [{ label: '#', sortable: false }, { label: 'Driver' }, { label: 'Team' }, { label: 'Races', align: 'right' },
      { label: 'Above team-mate', align: 'right', title: 'Race pace: minus the decomposition driver effect, % of a lap (± standard error)' },
      { label: 'Pct', align: 'right' }, { label: 'Quali v team-mate', align: 'right' }, { label: 'Above the field', align: 'right', title: 'The car\'s latest race-pace state plus the driver' },
      { label: 'Trend', align: 'right', title: 'Pace above team-mate v last season' }, { label: 'Points', align: 'right' }, { label: 'Exp. points', align: 'right', title: 'Season total expected by the championship simulation' },
      { label: 'Title', align: 'right' }];
    const drows = D.map((r, i) => ({ _href: '#/driver/' + encodeURIComponent(r.id), cells: [{ v: i + 1 }, { v: r.name, html: PD.driverLink(r.id, r.name) + (r.races < minR ? ' <span class="muted-inline">(few races)</span>' : '') },
      { v: r.team || '', html: PD.teamLink(r.team) }, { v: r.races, html: String(r.races) }, { v: r.pace_tm, html: '<strong>' + pctLap(r.pace_tm) + '</strong> ' + band(r.pace_tm, r.pace_tm_se) },
      { v: r.pct, html: pctPill(r.pct) }, { v: r.quali_tm, html: pctLap(r.quali_tm) + ' ' + band(r.quali_tm, r.quali_tm_se) }, { v: r.pace_field, html: pctLap(r.pace_field) },
      { v: r.trend, html: isNum(r.trend) ? signed(r.trend, 3) : '<span class="muted-inline">—</span>' }, { v: r.points, html: isNum(r.points) ? num(r.points, r.points % 1 ? 1 : 0) : '—' },
      { v: r.exp_points, html: isNum(r.exp_points) ? num(r.exp_points, 1) : '—' }, { v: r.p_title, html: isNum(r.p_title) ? pct(r.p_title, 1) : '—' }] }));
    h += card('Drivers', 'Sorted by pace above the field; click a heading to sort. ' + esc((d.notes || {}).teammate || ''), tableHTML(dcols, drows, { compact: true, sticky: true, id: 'pv-dtab' }) +
      '<div class="pg-note">' + esc((d.notes || {}).field || '') + ' ' + esc((d.notes || {}).trend || '') + ' Percentile: of pace above team-mate among drivers with ' + minR + '+ races.</div>');
    const tcols = [{ label: 'Rank', align: 'right' }, { label: 'Constructor' }, { label: 'Car, latest', align: 'right', title: 'The car\'s race-pace state at the latest round, % of a lap v the field (± se)' },
      { label: 'Season mean', align: 'right' }, { label: 'Qualifying car', align: 'right' }, { label: 'Last 5 rounds', align: 'right', title: 'Change in the race-pace state over the last five rounds (positive = faster)' },
      { label: 'Points', align: 'right' }, { label: 'Title', align: 'right' }];
    const trows = T.map(r => ({ _href: '#/team/' + encodeURIComponent(r.id), cells: [{ v: r.rank }, { v: r.name, html: PD.teamLink(r.id, r.name) },
      { v: r.car, html: '<strong>' + pctLap(r.car) + '</strong> ' + band(r.car, r.car_se) }, { v: r.car_mean, html: pctLap(r.car_mean) }, { v: r.quali_car, html: pctLap(r.quali_car) },
      { v: r.trend, html: isNum(r.trend) ? signed(r.trend, 3) : '—' }, { v: r.points, html: isNum(r.points) ? num(r.points, 0) : '—' }, { v: r.p_title, html: isNum(r.p_title) ? pct(r.p_title, 1) : '—' }] }));
    h += card('Constructors by car pace', 'The car part of the decomposition: a random walk from round to round, so upgrades show up as movement.', tableHTML(tcols, trows, { compact: true, id: 'pv-ttab' }));
    el.innerHTML = h;
    sortable(el);
    PD.setMeta('Driver value · ' + y);
  });
}

PD.route('value', render);
PD.route('value/:year', render);
})(window.PD);
