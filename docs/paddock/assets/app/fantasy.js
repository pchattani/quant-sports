/* The Quant Paddock — Fantasy (#/fantasy).
 * Our own fantasy-style points table with every projection from the race simulation: the next weekend
 * with a floor and a ceiling (10th / 90th percentiles), the rest of the season, tiers, value against
 * our form line (a cost proxy: no official F1 Fantasy data is used), the picks with their reasons,
 * where the points come from, the schedule ahead, the season so far and the walk-forward backtest.
 * Reads <y>/fantasy.json (current season), fantasy_backtest.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var COMP = {
  quali: ['Qualifying', '#3987e5'], race_pos: ['Race finish', '#2fb37b'], race_gain: ['Places gained', '#46b9c9'], race_fl: ['Fastest lap', '#c95ac9'],
  overtakes: ['Overtakes', '#e3b341'], sprint_pos: ['Sprint finish', '#7ee787'], sprint_gain: ['Sprint places', '#8e8cf0'], sprint_fl: ['Sprint fastest lap', '#ff9bce'],
  race_dnf: ['Retirement risk', '#e05d5d'], sprint_dnf: ['Sprint retirement risk', '#e8833a']
};
var METHODS = { model: 'Our projection', std: 'Season-to-date average', prev: 'Previous weekend', last: 'Last season’s average', blend: 'Half ours, half season average' };
var PICKS = [['top', 'Top picks', 'The five highest projections for the next weekend.'], ['boost', 'Boost pick', 'The highest expected score: the one to double.'],
  ['value', 'Value', 'Projection above the form line, among drivers who score.'], ['differentials', 'Differentials', 'Projection ranks well above the form line.'],
  ['risers', 'Risers / buy low', 'Pace, development or bad luck ahead of the form.'], ['fades', 'Form flatters / sell high', 'Form line above the rest-of-season projection.'],
  ['constructors', 'Constructors', 'The two highest constructor projections.'], ['constructor_value', 'Constructor value', 'Projection above the form line.']];
var pts = function (v, d) { return isNum(v) ? PD.num(v, d === undefined ? 1 : d) : '—'; };
var pc = function (v) { return isNum(v) ? Math.round(100 * v) + '%' : '—'; };
var tier = function (t) { return isNum(t) ? '<span class="pd-tier t' + t + '">T' + t + '</span>' : '—'; };

function render(el) {
  var y = PD.currentSeason();
  el.innerHTML = PD.pageHead('Season ' + y, 'Fantasy', '', '<a class="qk-btn" href="#/methodology/fantasy">How it works</a>') + '<div id="ft-body">' + PD.empty('Loading', '') + '</div>';
  return PD.loadAll([y + '/fantasy.json', 'fantasy_backtest.json']).then(function (res) {
    if (!PD.alive(el)) return;
    var F = res[0], BT = res[1];
    if (!PD.ok(F) || !F.drivers) { PD.set('ft-body', PD.notBuilt('The ' + y + ' fantasy page', F)); return; }
    var D = PD.rowsOf(F.driver_cols, F.drivers), T = PD.rowsOf(F.team_cols, F.teams);
    var byId = {};
    D.forEach(function (r) { byId[r.id] = r; });
    var tById = {};
    T.forEach(function (r) { tById[r.id] = r; });
    var nx = F.next || {};
    var live = D.filter(function (r) { return isNum(r.next); });
    var sub = el.querySelector('.pd-head .qk-sh-sub');
    var subText = F.projection_ok ? 'Next: ' + esc(nx.name || 'round ' + nx.round) + ' (round ' + esc(nx.round) + ')' + (nx.sprint ? ', a sprint weekend' : '') + (nx.quali_known ? ' · qualifying is in: its points are actual' : ' · projected before qualifying') : esc(F.reason || 'No rounds left to project');
    if (sub) sub.innerHTML = subText; else { var hl = el.querySelector('.pd-head-l'); if (hl) hl.insertAdjacentHTML('beforeend', '<p class="qk-sub">' + subText + '</p>'); }
    var top = live.slice().sort(function (a, b) { return b.next - a.next; })[0];
    var bv = live.filter(function (r) { return isNum(r.value) && (r.next || 0) >= 5; }).sort(function (a, b) { return b.value - a.value; })[0];
    var bd = (F.backtest || {}).drivers_core || {};
    var h = PD.kpis([
      PD.kpi('Next weekend', esc(nx.name ? PD.shortRace(nx.name) : '—'), nx.round ? 'round ' + esc(nx.round) + (nx.sprint ? ' · sprint' : '') : '', { text: true }),
      PD.kpi('Top projection', top ? PD.driverLink(top.id, { code: true, team: top.team }) + ' <span class="pd-dim">' + pts(top.next) + '</span>' : '—', top ? 'floor ' + pts(top.p10, 0) + ', ceiling ' + pts(top.p90, 0) : '', { text: true }),
      PD.kpi('Best value', bv ? PD.driverLink(bv.id, { code: true, team: bv.team }) + ' <span class="pd-dim">' + PD.signed(bv.value, 1) + '</span>' : '—', 'projection v form line', { text: true }),
      PD.kpi('Backtest MAE', bd.model ? PD.num(bd.model.mae, 2) : '—', bd.std ? 'season average ' + PD.num(bd.std.mae, 2) : ''),
      PD.kpi('Rank correlation', bd.model ? PD.num(bd.model.spearman, 2) : '—', bd.std ? 'season average ' + PD.num(bd.std.spearman, 2) : '')
    ]);
    if (F.label) h += PD.note(esc(PD.v2.copy(F.label)));
    if (F.picks && Object.keys(F.picks).length) {
      h += '<section class="qk-section pd-sec">' + PD.secHead('Fantasy', 'Our picks', 'Suggestions from our projections, with the reasons the numbers give. Not the official game’s player costs or ownership.') + '<div class="qk-auto pd-picks" style="--min:260px">' +
        PICKS.map(function (g) {
          var list = F.picks[g[0]];
          list = Array.isArray(list) ? list : (list ? [list] : []);
          if (!list.length) return '';
          var isT = g[0].indexOf('constructor') === 0;
          return '<div class="qk-card pd-pick"><div class="qk-card-head"><div><h3 class="qk-card-title">' + esc(g[1]) + '</h3><div class="qk-card-sub">' + esc(g[2]) + '</div></div></div><div class="qk-card-body"><ol>' + list.map(function (p) {
            var who = isT ? PD.teamLink(p.id, (tById[p.id] || {}).name) : PD.driverLink(p.id, { name: ((F.names || {}).drivers || {})[p.id], team: (byId[p.id] || {}).team });
            return '<li><div class="pd-pick-top">' + who + '<span class="pd-num"><b>' + pts(p.proj) + '</b> pts' + (isNum(p.value) ? ' · ' + PD.deltaHTML(p.value, 1) : '') + '</span></div>' + (p.why && p.why.length ? '<ul class="pd-why">' + p.why.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>' : '') + '</li>';
          }).join('') + '</ol></div></div>';
        }).join('') + '</div></section>';
    }
    h += PD.grid(
      PD.card('Where the points come from', 'Expected points by item next weekend; the diamond is the total.', PD.chartBox('ft-break', Math.max(360, live.length * 22 + 90)), { span: 7 }) +
      PD.card('Projection v form', 'Above the diagonal: we expect more than the form line (our cost proxy) says.', PD.chartBox('ft-val', 420), { span: 5 }) +
      PD.card('Drivers', 'Projections from ' + (F.n ? PD.int(F.n) + ' ' : '') + 'simulated seasons; floor and ceiling are the 10th and 90th percentiles (a retirement costs 20).', '<div id="ft-d"></div>', { span: 12, flush: true, right: PD.seg('ft-v', [['next', 'Next weekend'], ['ros', 'Rest of season']], 'next', 'Horizon') }) +
      PD.card('Constructors', 'Both drivers plus qualifying progression and pit-stop bands.', '<div id="ft-t"></div>', { span: 12, flush: true }) +
      PD.card('The schedule ahead', 'Expected points per remaining round, against the round’s median (blue above). S = sprint weekend.', '<div id="ft-s"></div>', { span: 7, flush: true, right: PD.seg('ft-sk', [['drivers', 'Drivers'], ['teams', 'Constructors']], 'drivers', 'Schedule') }) +
      PD.card('Season so far', 'Actual points per weekend with our table, the last ten rounds.', '<div id="ft-h"></div>', { span: 5, flush: true }), 'pd-mt');
    h += '<div id="ft-bt"></div>' + '<div id="ft-sc"></div>';
    PD.set('ft-body', h);

    // breakdown
    var ci = {};
    (F.comp_cols || []).forEach(function (c, i) { ci[c] = i; });
    var rows = live.filter(function (r) { return F.comp && F.comp[r.id]; }).sort(function (a, b) { return b.next - a.next; });
    var keys = Object.keys(COMP).filter(function (k) { return ci[k] !== undefined && rows.some(function (r) { return Math.abs(F.comp[r.id][ci[k]] || 0) > 0.05; }); });
    if (rows.length) {
      var labels = rows.map(function (r) { return PD.driverCode(r.id); });
      window.QKC.mount(document.getElementById('ft-break'), function (Tk) {
        var ya = window.QKC.axis(Tk, { type: 'category', data: labels, split: false, inverse: true }); ya.axisLabel.fontFamily = Tk.fontNum; ya.axisLabel.color = Tk.ink2; ya.axisLabel.interval = 0;
        return {
          grid: { left: 6, right: 16, top: 50, bottom: 30, containLabel: true },
          legend: { top: 0, left: 0, type: 'scroll', icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: Tk.ink2, fontSize: 11 }, pageTextStyle: { color: Tk.ink3 } },
          xAxis: window.QKC.axis(Tk, { fmt: function (v) { return PD.num(v, 0); }, name: 'Projected fantasy points', nameLocation: 'middle', nameGap: 26 }), yAxis: ya,
          tooltip: window.QKC.tooltip(Tk, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: function (ps) { var r = rows[ps[0].dataIndex]; return '<b>' + esc(r.name) + '</b> · ' + pts(r.next) + ' pts<br>' + ps.filter(function (p) { return p.seriesType === 'bar' && Math.abs(p.value) > 0.05; }).map(function (p) { return window.QKC.tipRow(p.color, p.seriesName, PD.num(p.value, 1)); }).join(''); } }),
          series: keys.map(function (k) { return { type: 'bar', name: COMP[k][0], stack: 'c', barMaxWidth: 14, itemStyle: { color: COMP[k][1] }, data: rows.map(function (r) { return F.comp[r.id][ci[k]] || 0; }) }; })
            .concat([{ type: 'scatter', name: 'Total', symbol: 'diamond', symbolSize: 9, itemStyle: { color: Tk.ink1 }, data: rows.map(function (r) { return r.next; }), z: 5 }])
        };
      }, { label: 'Where the points come from' });
    } else PD.ch.none('ft-break', 'No projection.');

    // projection v form
    var vr = live.filter(function (r) { return isNum(r.price); });
    PD.ch.scatter('ft-val', vr.map(function (r) { return { x: r.price, y: r.next, name: r.name, short: PD.driverCode(r.id), colour: PD.teamColour(r.team), href: PD.driverHref(r.id), label: true, size: 10, sub: 'value ' + PD.signed(r.value, 1) }; }),
      { xName: 'Form line (points per weekend so far)', yName: 'Projected next weekend', diag: true, xFmt: function (v) { return PD.num(v, 0); }, yFmt: function (v) { return PD.num(v, 0); }, emptyText: 'No form line yet.', label: 'Projection against form' });

    // drivers
    var drawD = function (view) {
      var lo = Math.min.apply(null, live.map(function (r) { return view === 'next' ? r.p10 : r.ros_p10; }).filter(isNum).concat([0]));
      var hi = Math.max.apply(null, live.map(function (r) { return view === 'next' ? r.p90 : r.ros_p90; }).filter(isNum).concat([1]));
      var bar = function (a, m, b) { if (!isNum(a) || !isNum(b) || !isNum(m) || hi <= lo) return ''; var x = function (v) { return Math.max(0, Math.min(100, 100 * (v - lo) / (hi - lo))).toFixed(1); };
        return '<span class="pd-range"><span class="pd-range-t"><span style="left:' + x(a) + '%;width:' + Math.max(1, x(b) - x(a)) + '%"></span><i style="left:' + x(m) + '%"></i></span><span class="pd-range-v">' + pts(a, 0) + '–' + pts(b, 0) + '</span></span>'; };
      var name = { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { name: v, team: r.team }); } };
      if (view === 'next') PD.table('ft-d', [
        { key: 'tier_next', label: 'Tier', fmt: tier }, name,
        { key: 'next', label: 'Projected', num: true, fmt: function (v) { return '<b>' + pts(v) + '</b>'; } },
        { key: 'p10', label: 'Floor – ceiling', sort: false, fmt: function (v, r) { return bar(r.p10, r.next, r.p90); } },
        { key: 'p_q3', label: 'Q3', num: true, fmt: pc }, { key: 'p_front', label: 'Front rows', num: true, fmt: pc }, { key: 'p_dnf', label: 'DNF', num: true, fmt: pc }, { key: 'p_fl', label: 'Fastest lap', num: true, fmt: pc },
        { key: 'price', label: 'Form line', num: true, tip: 'Our cost proxy: (n × form + 3 × last season) / (n + 3)', fmt: function (v) { return pts(v); } },
        { key: 'value', label: 'Value', num: true, fmt: function (v) { return PD.deltaHTML(v, 1); } }
      ], live, { sort: { key: 'next', dir: 'desc' }, rank: true });
      else PD.table('ft-d', [
        { key: 'tier', label: 'Tier', fmt: tier }, name,
        { key: 'ros', label: 'Rest of season', num: true, fmt: function (v) { return '<b>' + pts(v, 0) + '</b>'; } },
        { key: 'ros_p10', label: 'Range', sort: false, fmt: function (v, r) { return bar(r.ros_p10, r.ros, r.ros_p90); } },
        { key: 'rounds_left', label: 'Rounds', num: true }, { key: 'ros_per', label: 'Per weekend', num: true, fmt: function (v) { return pts(v); } },
        { key: 'price', label: 'Form line', num: true, fmt: function (v) { return pts(v); } },
        { key: 'value_ros', label: 'Value / weekend', num: true, fmt: function (v) { return PD.deltaHTML(v, 1); } },
        { key: 'form', label: 'Season so far', num: true, fmt: function (v, r) { return pts(v) + ' <span class="qk-muted">(' + (r.form_n || 0) + ')</span>'; } }
      ], live, { sort: { key: 'ros', dir: 'desc' }, rank: true });
    };
    drawD('next');
    PD.wireSeg(document, 'ft-v', drawD);
    PD.table('ft-t', [
      { key: 'tier', label: 'Tier', fmt: tier },
      { key: 'name', label: 'Constructor', sticky: true, fmt: function (v, r) { return PD.teamLink(r.id, v); } },
      { key: 'next', label: 'Projected', num: true, fmt: function (v) { return '<b>' + pts(v) + '</b>'; } },
      { key: 'drivers', label: 'Drivers', num: true, fmt: function (v) { return pts(v); } },
      { key: 'q_bonus', label: 'Qualifying', num: true, fmt: function (v) { return pts(v); } },
      { key: 'pit', label: 'Pit stops', num: true, fmt: function (v) { return pts(v); } },
      { key: 'ros', label: 'Rest of season', num: true, fmt: function (v) { return pts(v, 0); } },
      { key: 'price', label: 'Form line', num: true, fmt: function (v) { return pts(v); } },
      { key: 'value', label: 'Value', num: true, fmt: function (v) { return PD.deltaHTML(v, 1); } }
    ], T.filter(function (r) { return isNum(r.next); }), { sort: { key: 'next', dir: 'desc' }, rank: true });

    // schedule and history
    var drawS = function (kind) {
      var S = F.schedule || {}, rounds = S.rounds || [];
      if (!rounds.length) { PD.set('ft-s', PD.muted('No rounds left.')); return; }
      var src = kind === 'teams' ? (S.teams || {}) : (S.drivers || {});
      var order = (kind === 'teams' ? T : D).filter(function (r) { return src[r.id]; }).map(function (r) { return r.id; });
      PD.set('ft-s', PD.heatTable({ corner: kind === 'teams' ? 'Constructor' : 'Driver', cols: rounds.map(function (r) { return { label: 'R' + r[0] + (r[2] ? ' S' : ''), title: r[1] || '' }; }),
        rows: order.map(function (id) { return { label: kind === 'teams' ? PD.teamLink(id) : PD.driverLink(id, { code: true, team: (byId[id] || {}).team }), values: src[id] }; }), fmt: function (v) { return PD.num(v, 1); }, center: 'col' }));
    };
    drawS('drivers');
    PD.wireSeg(document, 'ft-sk', drawS);
    var H = F.history || {}, hr = (H.rounds || []).slice(-10), k0 = (H.rounds || []).length - hr.length;
    PD.set('ft-h', hr.length ? PD.heatTable({ corner: 'Driver', cols: hr.map(function (r) { return { label: 'R' + r[0], title: r[1] || '' }; }),
      rows: D.map(function (r) { return r.id; }).filter(function (id) { return (H.drivers || {})[id]; }).map(function (id) { return { label: PD.driverLink(id, { code: true, team: (byId[id] || {}).team }), values: H.drivers[id].slice(k0) }; }), fmt: function (v) { return PD.num(v, 0); }, center: 'col' }) : PD.muted('No rounds run yet this season.'));

    backtest(F, BT);
    scoring(F);
  });
}

function backtest(F, BT) {
  var B = PD.ok(BT) && BT.metrics ? BT : null;
  var M = B ? B.metrics : (F.backtest && F.backtest.ok ? F.backtest : null);
  if (!M) { PD.set('ft-bt', PD.card('Does it work? The backtest', '', PD.notBuilt('The fantasy backtest', BT), { cls: 'pd-mt' })); return; }
  var seasons = B ? B.seasons : M.seasons;
  var span = seasons && seasons.length ? seasons[0] + '–' + seasons[seasons.length - 1] : '';
  var dc = M.drivers_core || {};
  var read = '';
  if (dc.model && dc.std) read = 'Over ' + (dc.model.races || 0) + ' weekends (' + esc(span) + '), projected before qualifying with only the data before each weekend, our projection misses a driver’s weekend score by ' + PD.num(dc.model.mae, 1) + ' points on average against ' + PD.num(dc.std.mae, 1) +
    ' for the season-to-date average (' + PD.num(100 * (1 - dc.model.mae / dc.std.mae), 0) + '% smaller), ' + PD.num((dc.prev || {}).mae, 1) + ' for the previous weekend and ' + PD.num((dc.last || {}).mae, 1) + ' for last season’s average; rank correlation ' + PD.num(dc.model.spearman, 2) + ' against ' + PD.num(dc.std.spearman, 2) + '.';
  var groups = [['drivers_core', 'Drivers, core scoring'], ['drivers_full', 'Drivers, full scoring (' + ((B && B.full_from) || 2024) + ' on)'], ['teams_core', 'Constructors, core scoring'], ['teams_full', 'Constructors, full scoring']].filter(function (g) { return M[g[0]] && M[g[0]].model; });
  PD.set('ft-bt', '<section class="qk-section pd-sec">' + PD.secHead('Backtest', 'Does it work?', 'The walk-forward backtest: every weekend ' + esc(span) + ' projected before qualifying with only the data before it.') +
    (read ? PD.note(read) : '') + PD.grid((B && (B.per_race || []).length ? PD.card('Error through time', 'Mean absolute error per weekend, 10-weekend rolling mean.', PD.chartBox('ft-bt-ch', 300), { span: 12 }) : '') +
    groups.map(function (g, i) { return PD.card(esc(g[1]), PD.int((M[g[0]].model || {}).n) + ' weekends scored', '<div id="ft-bt-' + i + '"></div>', { span: 6, flush: true }); }).join(''), 'pd-mt') + '</section>');
  groups.forEach(function (g, i) {
    var m = M[g[0]];
    var names = ['model', 'std', 'prev', 'last', 'blend'].filter(function (k) { return m[k]; });
    var best = function (key, low) { var b = null; names.forEach(function (k) { var v = m[k][key]; if (isNum(v) && (b === null || (low ? v < b.v : v > b.v))) b = { k: k, v: v }; }); return b ? b.k : null; };
    var bm = best('mae', true), bs = best('spearman'), bt = best('top5');
    var hl = function (k, kk, v, d) { return isNum(v) ? (k === kk ? '<b class="pd-up">' + PD.num(v, d) + '</b>' : PD.num(v, d)) : '—'; };
    PD.table('ft-bt-' + i, [
      { key: 'label', label: 'Method', sticky: true, sort: false, fmt: function (v, r) { return r.k === 'model' ? '<b>' + esc(v) + '</b>' : esc(v); } },
      { key: 'mae', label: 'MAE', num: true, tip: 'Mean absolute error, points per weekend (lower is better)', fmt: function (v, r) { return hl(r.k, bm, v, 2); } },
      { key: 'bias', label: 'Bias', num: true, fmt: function (v) { return isNum(v) ? PD.signed(v, 2) : '—'; } },
      { key: 'spearman', label: 'Rank corr.', num: true, fmt: function (v, r) { return hl(r.k, bs, v, 3); } },
      { key: 'top5', label: 'Top-5', num: true, tip: 'Share of the actual top five in the method’s top five', fmt: function (v, r) { return hl(r.k, bt, v, 2); } },
      { key: 'coverage_80', label: '80% band', num: true, tip: 'Share of actual totals inside the floor-ceiling interval (target 80%)', fmt: function (v) { return isNum(v) ? pc(v) : '—'; } }
    ], names.map(function (k) { return Object.assign({ k: k, label: METHODS[k] }, m[k]); }));
  });
  var pr = (B && B.per_race) || [];
  if (pr.length) {
    var roll = function (arr) { return arr.map(function (v, i) { var s = arr.slice(Math.max(0, i - 9), i + 1).filter(isNum); return s.length ? s.reduce(function (a, b) { return a + b; }, 0) / s.length : null; }); };
    var xs = pr.map(function (r) { return r[0] + ' R' + r[1]; });
    PD.ch.lines('ft-bt-ch', [{ name: 'Our projection', data: roll(pr.map(function (r) { return r[2]; })), colour: '#3987e5' }, { name: 'Season-to-date average', data: roll(pr.map(function (r) { return r[3]; })), colour: '#e8833a' }],
      { xs: xs, xName: 'Race', yName: 'MAE, points', yFmt: function (v) { return PD.num(v, 1); }, label: 'Backtest error through time' });
  }
}

function scoring(F) {
  if (!(F.scoring || []).length) return;
  PD.set('ft-sc', PD.card('Our scoring table', 'Ours, in the usual shape of F1 fantasy games; computed from Jolpica results and OpenF1 records.', '<div id="ft-sc-t"></div>' +
    ((F.excluded || []).length ? '<div class="pd-pad pd-prose"><p><b>Left out, and why:</b></p><ul>' + F.excluded.map(function (r) { return '<li><b>' + esc(PD.v2.copy(r[0])) + '.</b> ' + esc(PD.v2.copy(r[1])) + '</li>'; }).join('') + '</ul></div>' : ''), { flush: true, cls: 'pd-mt' }));
  PD.table('ft-sc-t', [{ key: 'a', label: 'Part', sort: false, fmt: function (v) { return '<b>' + esc(v) + '</b>'; } }, { key: 'b', label: 'Item', sort: false }, { key: 'c', label: 'Points', sort: false, fmt: function (v) { return '<span class="pd-num">' + esc(v) + '</span>'; } }, { key: 'd', label: 'Notes', sort: false, fmt: function (v) { return '<span class="qk-muted">' + esc(v) + '</span>'; } }],
    F.scoring.map(function (r) { return { a: r[0], b: r[1], c: r[2], d: r[3] }; }));
}

PD.route('fantasy', render);
})(window.PD);
