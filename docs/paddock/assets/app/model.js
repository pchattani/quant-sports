/* The Quant Paddock — Model: how good the forecasts have been (#/model, #/calibration), how every
 * model works (#/methodology[/<section>]), the glossary (#/glossary[/<key>|g:<group>]) and the terms
 * (#/disclaimer). Reads calibration.json, glossary.json; the methodology text is method-text.js. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
function nav(active) { return PD.subnav([['#/model', 'Calibration', 'calibration'], ['#/methodology', 'Methodology', 'methodology'], ['#/glossary', 'Glossary', 'glossary'], ['#/disclaimer', 'Terms', 'disclaimer']], active, 'Model views'); }

// ── calibration ───────────────────────────────────────────────────────────

var LABELS = { model_pre: 'Race simulator, before qualifying', model_post: 'Race simulator, after qualifying', model_pre_results_only: 'Simulator, results-only pace (pre)',
  grid_order: 'Grid order (logistic on slot)', previous_results: 'Previous 5 results', elo: 'Field Elo (Plackett-Luce)', plackett_luce: 'Plackett-Luce on past orders' };
var EVENTS = [['win', 'Win'], ['podium', 'Podium'], ['points', 'Points'], ['dnf', 'DNF']];
var label = function (k) { return LABELS[k] || PD.titleCase(k); };

function reading(d) {
  var M = d.metrics || {}, pre = d.pre_quali_models || [], post = d.post_quali_models || [], out = [];
  var ll = function (m, e) { return (((M[m] || {})[e]) || {}).logloss; };
  var wmc = function (m) { return ((M[m] || {}).win_multiclass || {}).logloss; };
  var cmp = function (model, pool, phase) {
    var others = pool.filter(function (x) { return x !== model && x.indexOf('model_') !== 0 && isNum(wmc(x)); });
    if (!isNum(wmc(model)) || !others.length) return;
    var best = others.sort(function (a, b) { return wmc(a) - wmc(b); })[0];
    var diff = wmc(best) - wmc(model);
    out.push('<p><b>' + esc(phase) + ':</b> the simulator gives the actual winner, on average, ' + (diff >= 0 ? 'more' : 'less') + ' probability than the best baseline (' + esc(label(best)) + '): winner log-loss ' + PD.num(wmc(model), 3) + ' against ' + PD.num(wmc(best), 3) +
      ' (lower is better; a gap of ' + PD.num(Math.abs(diff), 3) + ' nats is about ' + PD.num(100 * (Math.exp(Math.abs(diff)) - 1), 0) + '% more probability on the winner, geometrically averaged).</p>');
    var evs = EVENTS.map(function (e) { return e[0]; }).filter(function (e) { return isNum(ll(model, e)); });
    var wins = evs.filter(function (e) { return others.every(function (o) { return !isNum(ll(o, e)) || ll(model, e) <= ll(o, e); }); });
    var lab = function (e) { return EVENTS.filter(function (x) { return x[0] === e; })[0][1].toLowerCase(); };
    if (evs.length) out.push('<p>On the binary events it has the lowest log-loss for ' + (wins.length ? wins.map(lab).join(', ') : 'none of them') + (wins.length < evs.length ? ' and trails a baseline on ' + evs.filter(function (e) { return wins.indexOf(e) < 0; }).map(lab).join(', ') : '') + '.</p>');
  };
  if (pre.indexOf('model_pre') >= 0) cmp('model_pre', pre, 'Before qualifying');
  if (post.indexOf('model_post') >= 0) cmp('model_post', post, 'After qualifying');
  var main = M.model_post ? 'model_post' : 'model_pre';
  var bins = ((((M[main] || {}).win) || {}).reliability || []).filter(function (b) { return b.n >= 10; });
  if (bins.length) {
    var worst = bins.slice().sort(function (a, b) { return Math.abs(b.freq - b.mean_p) - Math.abs(a.freq - a.mean_p); })[0];
    out.push('<p><b>Calibration</b> (' + esc(label(main)) + ', win, bins with 10+ forecasts): the largest gap is in the ' + PD.pct(worst.lo, 0) + '–' + PD.pct(worst.hi, 0) + ' bin, where forecasts averaged ' + PD.pct(worst.mean_p) + ' and the event happened ' + PD.pct(worst.freq) + ' of the time (' + worst.n + ' forecasts). With a few dozen forecasts in a bin, a gap of ten points is within noise.</p>');
  }
  var dnfM = ll(main, 'dnf'), dnfB = (((M[main] || {}).dnf) || {}).base_rate;
  if (isNum(dnfM) && isNum(dnfB) && dnfB > 0 && dnfB < 1) { var h0 = -(dnfB * Math.log(dnfB) + (1 - dnfB) * Math.log(1 - dnfB)); out.push('<p><b>Retirements</b> are close to unpredictable race by race: DNF log-loss ' + PD.num(dnfM, 4) + ' against ' + PD.num(h0, 4) + ' for forecasting the base rate (' + PD.pct(dnfB) + ') for everyone.</p>'); }
  return out.join('') || '<p>Not enough scored races for a reading.</p>';
}

function calibration(el) {
  el.innerHTML = PD.pageHead('How good is the model?', 'Model', 'Walk-forward backtest: every Grand Prix predicted using only the data before it, scored against what happened.') + nav('calibration') + '<div id="cal-body">' + PD.empty('Loading the backtest', '') + '</div>';
  return PD.load('calibration.json').then(function (d) {
    if (!PD.alive(el)) return;
    if (!d || d.ok === false || !d.metrics) { PD.set('cal-body', PD.notBuilt('The backtest', d)); return; }
    var M = d.metrics;
    var pre = (d.pre_quali_models || Object.keys(M).filter(function (k) { return k !== 'model_post' && k !== 'grid_order'; })).filter(function (k) { return M[k]; });
    var post = (d.post_quali_models || ['model_post', 'grid_order']).filter(function (k) { return M[k]; });
    var used = d.seasons_used || d.seasons || {};
    var usedList = Array.isArray(used) ? used : Object.keys(used);
    var main = M.model_post ? 'model_post' : 'model_pre';
    PD.set('cal-body', PD.kpis([
      PD.kpi('Races scored', String(d.races || '—'), usedList.length ? usedList[0] + '–' + usedList[usedList.length - 1] : ''),
      PD.kpi('Winner log-loss', PD.num(((M[main] || {}).win_multiclass || {}).logloss, 3), esc(label(main))),
      PD.kpi('Driver-races', PD.int(((M[pre[0]] || {}).win || {}).n), 'one forecast per driver per event'),
      PD.kpi('Simulations', d.n_sims ? PD.int(d.n_sims) : '—', 'per race and model variant'),
      PD.kpi('Win base rate', PD.pct((((M[pre[0]] || {}).win) || {}).base_rate), 'one winner per race'),
      PD.kpi('Updated', esc(PD.fmtStamp(d.updated_at || d.generated_at) || '—'), d.runtime_s ? PD.num(d.runtime_s / 60, 0) + ' min run' : '')
    ]) + '<div class="pd-mt">' + PD.note('<div>' + reading(d) + '</div>') + '</div>' + PD.grid(
      PD.card('The winner’s probability, race by race', 'What each model gave the driver who won; higher is better.', PD.chartBox('cal-races', 340), { span: 12 }) +
      PD.card('Reliability: win', 'Forecasts in ten equal bins; marker size by the number of forecasts. On the diagonal = calibrated.', PD.chartBox('cal-rw', 400), { span: 6 }) +
      PD.card('Reliability: podium', '', PD.chartBox('cal-rp', 400), { span: 6 }) +
      PD.card('Scores', 'Binary log-loss and Brier (lower is better); highlighted: the best in its group (before qualifying and after compete separately).', '<div id="cal-t"></div>', { span: 12, flush: true,
        right: '<select class="qk-select" id="cal-season" aria-label="Season"><option value="">All seasons</option>' + Object.keys(d.per_season || {}).sort().reverse().map(function (y) { return '<option value="' + esc(y) + '">' + esc(y) + '</option>'; }).join('') + '</select>' }) +
      PD.card('Reliability bins', 'The numbers behind the diagrams, with ±2 binomial standard errors.', '<div id="cal-b"></div>', { span: 12, flush: true,
        right: '<div class="pd-toolbar pd-tight"><select class="qk-select" id="cal-bm" aria-label="Model">' + pre.concat(post).map(function (k) { return '<option value="' + esc(k) + '">' + esc(label(k)) + '</option>'; }).join('') + '</select><select class="qk-select" id="cal-be" aria-label="Event">' + EVENTS.map(function (e) { return '<option value="' + e[0] + '">' + e[1] + '</option>'; }).join('') + '</select></div>' }) +
      PD.card('Baselines', 'What the simulator has to beat.', '<div class="pd-prose"><ul><li><b>Grid order</b> (after qualifying): p = sigmoid(a + b × grid slot), fitted by maximum likelihood on previous seasons, rescaled so the field sums to 1 / 3 / 10 for win / podium / points.</li>' +
        '<li><b>Previous results</b>: each driver’s frequency of the event in his last 5 starts, shrunk to the field base rate with 2 pseudo-starts.</li><li><b>Field Elo</b>: Elo before the race as Plackett-Luce log-strengths θ = Elo × ln 10 / 400.</li>' +
        '<li><b>Plackett-Luce</b>: strengths fitted to earlier finishing orders (this season weight 1, last season 0.35, two back 0.12).</li></ul><p>Details in the <a href="#/methodology">methodology</a>.</p></div>', { span: 12 }), 'pd-mt'));
    var pr = d.per_race || [];
    if (pr.length) {
      var xs = pr.map(function (r) { return r.year + ' R' + r.round; });
      PD.ch.lines('cal-races', ['model_pre', 'model_post', 'grid_order', 'elo'].filter(function (k) { return M[k]; }).map(function (k, i) { return { name: label(k), data: pr.map(function (r) { return (r.p_winner || {})[k]; }), width: k.indexOf('model') === 0 ? 2 : 1.2, colour: ['#3987e5', '#2fb37b', '#e8833a', '#c95ac9'][i] }; }),
        { xs: xs, yFmt: function (v) { return Math.round(v * 100) + '%'; }, xLabel: function (v) { var r = pr[xs.indexOf(v)]; return r ? v + ' ' + (r.name || '') + ': ' + PD.driverName(r.winner) : v; }, yMin: 0, label: 'Winner probability by race' });
    } else PD.ch.none('cal-races', 'No per-race records.');
    var rel = ['model_pre', 'model_post', 'grid_order', 'previous_results'].filter(function (k) { return M[k]; });
    PD.ch.reliability('cal-rw', rel.map(function (k) { return { name: label(k), bins: (((M[k] || {}).win) || {}).reliability || [] }; }));
    PD.ch.reliability('cal-rp', rel.map(function (k) { return { name: label(k), bins: (((M[k] || {}).podium) || {}).reliability || [] }; }));
    var drawT = function (season) {
      var src = season ? ((d.per_season || {})[season] || {}) : M;
      var rows = [];
      [['before quali', pre], ['after quali', post]].forEach(function (g) {
        var group = g[1].filter(function (k) { return src[k]; });
        var best = {};
        ['logloss', 'brier'].forEach(function (k) { EVENTS.forEach(function (e) { var b = null; group.forEach(function (m) { var v = ((src[m] || {})[e[0]] || {})[k]; if (isNum(v) && (b === null || v < b.v)) b = { m: m, v: v }; }); best[k + e[0]] = b ? b.m : null; }); });
        var bw = null; group.forEach(function (m) { var v = ((src[m] || {}).win_multiclass || {}).logloss; if (isNum(v) && (bw === null || v < bw.v)) bw = { m: m, v: v }; });
        group.forEach(function (m) {
          var r = { k: m, model: label(m), when: g[0], best: best, bw: bw ? bw.m : null, n: ((src[m] || {}).win || {}).n, wm: ((src[m] || {}).win_multiclass || {}).logloss };
          ['logloss', 'brier'].forEach(function (k) { EVENTS.forEach(function (e) { r[k + e[0]] = ((src[m] || {})[e[0]] || {})[k]; }); });
          rows.push(r);
        });
      });
      var cell = function (key, d0) { return function (v, r) { return isNum(v) ? (r.best[key] === r.k ? '<b class="pd-up">' + PD.num(v, d0) + '</b>' : PD.num(v, d0)) : '—'; }; };
      PD.table('cal-t', [{ key: 'model', label: 'Model', sticky: true, fmt: function (v) { return '<b>' + esc(v) + '</b>'; } }, { key: 'when', label: 'When' }]
        .concat(EVENTS.map(function (e) { return { key: 'logloss' + e[0], label: e[1] + ' LL', num: true, fmt: cell('logloss' + e[0], 4) }; }))
        .concat(EVENTS.map(function (e) { return { key: 'brier' + e[0], label: e[1] + ' Brier', num: true, fmt: cell('brier' + e[0], 4) }; }))
        .concat([{ key: 'wm', label: 'Winner LL', num: true, fmt: function (v, r) { return isNum(v) ? (r.bw === r.k ? '<b class="pd-up">' + PD.num(v, 3) + '</b>' : PD.num(v, 3)) : '—'; } }, { key: 'n', label: 'N', num: true }]), rows);
    };
    drawT('');
    document.getElementById('cal-season').onchange = function (e) { drawT(e.target.value); };
    var drawB = function () {
      var m = document.getElementById('cal-bm').value, e = document.getElementById('cal-be').value;
      var bins = (((M[m] || {})[e]) || {}).reliability || [];
      if (!bins.length) { PD.set('cal-b', PD.muted('No bins.')); return; }
      PD.table('cal-b', [{ key: 'bin', label: 'Bin', sort: false }, { key: 'n', label: 'Forecasts', num: true }, { key: 'mean_p', label: 'Mean forecast', num: true, fmt: function (v) { return PD.pct(v); } }, { key: 'freq', label: 'Observed', num: true, fmt: function (v) { return PD.pct(v); } },
        { key: 'gap', label: 'Gap', num: true, fmt: function (v, r) { return '<span class="' + (Math.abs(v) > 2 * r.se ? 'pd-down' : '') + '">' + PD.signed(100 * v, 1) + ' pts</span>'; } }, { key: 'se', label: '±2 se', num: true, fmt: function (v) { return '±' + PD.num(200 * v, 1) + ' pts'; } }],
        bins.map(function (b) { return { bin: PD.pct(b.lo, 0) + '–' + PD.pct(b.hi, 0), n: b.n, mean_p: b.mean_p, freq: b.freq, gap: b.freq - b.mean_p, se: Math.sqrt(Math.max(1e-9, b.mean_p * (1 - b.mean_p)) / b.n) }; }));
    };
    document.getElementById('cal-bm').onchange = drawB; document.getElementById('cal-be').onchange = drawB;
    drawB();
  });
}

// ── methodology ───────────────────────────────────────────────────────────

function methodology(el, params) {
  var want = params.sec || '';
  var tmp = document.createElement('div');
  tmp.innerHTML = PD.fixLinks(PD.METHOD_HTML || '');
  var secs = Array.prototype.slice.call(tmp.querySelectorAll('section[id]')).map(function (s) {
    var h2 = s.querySelector('h2'), title = h2 ? h2.textContent : s.id;
    if (h2) h2.parentNode.removeChild(h2);
    return { id: s.id.replace(/^m-/, ''), title: title, html: s.innerHTML };
  });
  var idx = PD.index() || {};
  el.innerHTML = PD.pageHead('How it works', 'Methodology', 'Where the data comes from, how every model works and where it is wrong. Every constant is the one in the code; each section names its source file.' + (idx.updated_at ? ' Site updated ' + esc(PD.fmtStamp(idx.updated_at)) + '.' : '')) + nav('methodology') +
    '<div class="pd-doc"><nav class="pd-toc qk-card" aria-label="Sections"><div class="qk-kicker">' + secs.length + ' sections</div><ol>' + secs.map(function (s) { return '<li><a href="#/methodology/' + esc(s.id) + '" data-t="m-' + esc(s.id) + '">' + esc(s.title) + '</a></li>'; }).join('') + '</ol></nav>' +
    '<div class="pd-doc-body">' + secs.map(function (s, i) { return '<section class="qk-card pd-prose" id="m-' + esc(s.id) + '"><div class="qk-card-body"><h2><span class="pd-num">' + (i + 1) + '</span> ' + esc(s.title) + '</h2>' + s.html + '</div></section>'; }).join('') + '</div></div>';
  Array.prototype.forEach.call(el.querySelectorAll('.pd-toc a[data-t]'), function (a) {
    a.addEventListener('click', function (ev) { ev.preventDefault(); var t = document.getElementById(a.getAttribute('data-t')); if (t) t.scrollIntoView({ block: 'start' }); PD.setHashQuiet(a.getAttribute('href')); });
  });
  if (want) { var t = document.getElementById('m-' + want.replace(/^m-/, '')); if (t) setTimeout(function () { t.scrollIntoView({ block: 'start' }); }, 30); }
}

// ── glossary ──────────────────────────────────────────────────────────────

function slug(s) { return String(s || 'group').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
function glossary(el, params) {
  var key = params.key || '';
  el.innerHTML = PD.pageHead('Every metric and model term', 'Glossary', 'How each is computed is in the methodology.') + nav('glossary') + '<div id="gl-body">' + PD.empty('Loading the glossary', '') + '</div>';
  return PD.load('glossary.json').then(function (g) {
    if (!PD.alive(el)) return;
    var ready = g && g.ok !== false && (g.groups || []).length ? Promise.resolve(g) : PD.loadAll([PD.currentSeason() + '/drivers.json', PD.currentSeason() + '/teams.json']).then(function (res) {
      var groups = [];
      [[res[0], 'Driver: '], [res[1], 'Team: ']].forEach(function (p) { ((p[0] || {}).metrics || []).forEach(function (m) { var n = p[1] + (m.group || 'Other'); var grp = groups.filter(function (x) { return x.name === n; })[0]; if (!grp) { grp = { name: n, entries: [] }; groups.push(grp); } grp.entries.push(m); }); });
      return { groups: groups, model: [] };
    });
    return ready.then(function (G) {
      if (!PD.alive(el)) return;
      var groups = (G.groups || []).map(function (x) { return { name: x.name, sl: slug(x.name), entries: x.entries || [], model: false }; });
      var mg = [];
      (G.model || []).forEach(function (t) { var n = t.group || 'Model'; var grp = mg.filter(function (x) { return x.name === n; })[0]; if (!grp) { grp = { name: n, sl: 'model-' + slug(n), entries: [], model: true }; mg.push(grp); } grp.entries.push(t); });
      var all = groups.concat(mg.map(function (x) { return Object.assign(x, { name: 'Model terms: ' + x.name }); }));
      var total = all.reduce(function (s, x) { return s + x.entries.length; }, 0);
      var tag = function (e) { var t = []; if (e.fmt === 'pct') t.push('%'); else if (e.fmt === 'prob') t.push('probability'); else if (e.fmt === 'int') t.push('count'); else if (e.fmt === 'ms' || e.fmt === 'gap') t.push('time'); if (e.lower) t.push('lower is better'); if (e.scope) t.push(String(e.scope)); return t.map(function (x) { return '<span class="qk-badge">' + esc(x) + '</span>'; }).join(''); };
      PD.set('gl-body', '<div class="pd-toolbar"><input id="gl-q" class="qk-input" type="search" placeholder="Filter the glossary…" aria-label="Filter the glossary"><span class="qk-sub" id="gl-n"></span></div>' +
        '<div class="qk-chips scroll pd-gl-index">' + all.map(function (x) { return '<a class="qk-chip" href="#/glossary/g:' + esc(x.sl) + '" data-g="' + esc(x.sl) + '">' + esc(x.name) + ' <span class="n">' + x.entries.length + '</span></a>'; }).join('') + '</div>' +
        all.map(function (x) {
          return '<section class="qk-card pd-gl-group pd-mt" data-g="' + esc(x.sl) + '" id="glg-' + esc(x.sl) + '"><div class="qk-card-head"><h3 class="qk-card-title">' + esc(x.name) + '</h3><span class="qk-sub">' + x.entries.length + '</span></div><dl class="pd-gl">' + x.entries.map(function (e) {
            return '<div class="pd-gl-e" id="gl-' + esc(e.key) + '" data-q="' + esc((e.label || '') + ' ' + e.key + ' ' + (e.desc || '')) + '"><dt><a href="#/glossary/' + encodeURIComponent(e.key) + '">' + esc(e.label || e.key) + '</a> <code>' + esc(e.key) + '</code> ' + (x.model ? '<span class="qk-badge accent">model</span>' : tag(e)) + '</dt><dd>' + (e.desc ? esc(e.desc) : '<span class="qk-muted">No definition yet.</span>') + '</dd></div>';
          }).join('') + '</dl></section>';
        }).join('') + '<p class="pd-muted" id="gl-none" hidden>Nothing in the glossary matches that.</p>');
      var input = document.getElementById('gl-q'), es = Array.prototype.slice.call(el.querySelectorAll('.pd-gl-e')), cards = Array.prototype.slice.call(el.querySelectorAll('.pd-gl-group'));
      var norm = function (s) { return String(s || '').toLowerCase(); };
      var filter = function () {
        var n = norm(input.value.trim()), shown = 0;
        es.forEach(function (e) { var hit = !n || norm(e.getAttribute('data-q')).indexOf(n) >= 0; e.hidden = !hit; if (hit) shown++; });
        cards.forEach(function (c) { c.hidden = !c.querySelector('.pd-gl-e:not([hidden])'); });
        document.getElementById('gl-none').hidden = !!shown;
        PD.set('gl-n', n ? shown + ' of ' + total + ' entries' : total + ' entries');
      };
      input.addEventListener('input', filter);
      filter();
      Array.prototype.forEach.call(el.querySelectorAll('.pd-gl-index a'), function (a) { a.addEventListener('click', function (ev) { ev.preventDefault(); var c = document.getElementById('glg-' + a.getAttribute('data-g')); if (c) c.scrollIntoView({ block: 'start' }); PD.setHashQuiet(a.getAttribute('href')); }); });
      if (key) {
        var target = key.indexOf('g:') === 0 ? document.getElementById('glg-' + key.slice(2)) : document.getElementById('gl-' + key);
        if (target) { target.classList.add('pd-hit'); setTimeout(function () { target.scrollIntoView({ block: 'center' }); }, 60); }
      }
    });
  });
}

function disclaimer(el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = PD.pageHead('Legal', 'Disclaimer and terms', '') + nav('disclaimer') + '<section class="qk-card pd-prose pd-mt"><div class="qk-card-body">' + (t ? t.innerHTML : '') + '</div></section>';
}

PD.route('model', calibration);
PD.route('calibration', calibration);
PD.route('methodology', methodology);
PD.route('glossary', glossary);
PD.route('disclaimer', disclaimer);
})(window.PD);
