/* The Quant Campus — Lab (#/<L>/lab) and Model (#/<L>/model?tab=method|calibration|glossary|terms).
 * Lab: build-your-own scatter and table over lab_teams.json / lab_players.json (pick x, y, filter, colour by
 * conference or position; the table beside the chart holds the same rows).
 * Model: methodology (docs/campus/MODELS_CFB.md or MODELS_HOOPS.md rendered), the walk-forward backtest against
 * closing lines (calibration.json), the glossary (data/glossary.json) and the terms. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

/* ── lab ─────────────────────────────────────────────────────────────── */
CC.route('lab', function (el, p) {
  var L = p.L, S = p.S, q = p.query || {};
  var kind = q.kind === 'players' ? 'players' : 'teams';
  el.innerHTML = U.head('Lab', 'Pick any two numbers and see every ' + (kind === 'players' ? 'player' : 'team') + ' at once. Click a point to open its page.', U.kicker(L, S)) + QK.skeleton('chart', 1);
  return Promise.all([CC.load(CC.path(L, S, kind === 'players' ? 'lab_players.json' : 'lab_teams.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var d = a[0];
    var segHtml = '<div class="qk-seg" id="lab-kind" role="group" aria-label="Rows"><button type="button" data-value="teams" aria-pressed="' + (kind === 'teams') + '">Teams</button><button type="button" data-value="players" aria-pressed="' + (kind === 'players') + '">Players</button></div>';
    if (!CC.ok(d) || !(d.rows || []).length) {
      el.innerHTML = U.head('Lab', '', U.kicker(L, S)) + '<div class="cc-toolbar">' + segHtml + '</div>' + (CC.ok(d) ? QK.empty('No rows yet', 'Nothing has been played this season. Try last season.') : U.missing('The lab data', d));
      QK.seg(QK.$('#lab-kind', el), function (v) { CC.go(CC.href(L, 'lab', null, S, 'kind=' + v)); });
      return;
    }
    var F = d.fields || [], ix = {};
    F.forEach(function (f, i) { ix[f] = i; });
    var mets = (d.metrics || []).filter(function (m) { return ix[m.key] !== undefined; });
    var num = mets.length ? mets : F.filter(function (f) { return d.rows.some(function (r) { return isNum(r[ix[f]]); }); }).map(function (f) { return { key: f, label: f, fmt: '2' }; });
    var mk = {}; num.forEach(function (m) { mk[m.key] = m; });
    var xk = mk[q.x] ? q.x : (num[1] || num[0]).key, yk = mk[q.y] ? q.y : (num[2] || num[0]).key;
    var grpKey = kind === 'players' ? 'pos' : 'conference';
    var groups = {};
    d.rows.forEach(function (r) { var g = r[ix[grpKey]]; if (g !== undefined && g !== null) groups[g] = (groups[g] || 0) + 1; });
    var gk = Object.keys(groups).sort(function (x, y) { return groups[y] - groups[x]; });
    var opt = function (sel) { return num.map(function (m) { return '<option value="' + esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + esc(m.label) + '</option>'; }).join(''); };
    var minGp = kind === 'players' && ix.gp !== undefined;
    el.innerHTML = U.head('Lab', 'Pick any two numbers and see every ' + (kind === 'players' ? 'player' : 'team') + ' at once. Click a point to open its page; the table below holds the same rows.', U.kicker(L, S)) +
      '<div class="cc-toolbar">' + segHtml + '<label class="cc-lab-sel">X <select class="qk-select" id="lab-x">' + opt(xk) + '</select></label><label class="cc-lab-sel">Y <select class="qk-select" id="lab-y">' + opt(yk) + '</select></label>' +
      '<select class="qk-select" id="lab-g" aria-label="' + (kind === 'players' ? 'Position' : 'Conference') + '"><option value="">' + (kind === 'players' ? 'All positions' : 'All conferences') + '</option>' + gk.map(function (g) { return '<option value="' + esc(g) + '">' + esc(kind === 'players' ? g : CC.cname(L, g)) + '</option>'; }).join('') + '</select>' +
      (minGp ? '<label class="cc-lab-sel">Min games <input class="qk-input" type="number" id="lab-gp" min="0" value="' + (kind === 'players' ? 3 : 0) + '" style="width:72px"></label>' : '') + '</div>' +
      U.card('Chart', '<span id="lab-t"></span>', U.chart('lab-sc', 460, 'Scatter of the chosen metrics')) + '<div id="lab-tbl"></div>';
    function paint() {
      var x = QK.$('#lab-x', el).value, y = QK.$('#lab-y', el).value, g = QK.$('#lab-g', el).value, gp = minGp ? Number(QK.$('#lab-gp', el).value || 0) : 0;
      var rs = d.rows.filter(function (r) { return isNum(r[ix[x]]) && isNum(r[ix[y]]) && (!g || String(r[ix[grpKey]]) === g) && (!minGp || (r[ix.gp] || 0) >= gp); });
      rs.sort(function (r1, r2) { return mk[y].lower ? r1[ix[y]] - r2[ix[y]] : r2[ix[y]] - r1[ix[y]]; });
      var tn = QK.$('#lab-t', el); if (tn) tn.textContent = mk[y].label + ' against ' + mk[x].label + (mk[y].lower ? ' (lower is better on the vertical axis, so it is flipped: better is up)' : '') + '.';
      var href = function (r) { return kind === 'players' ? CC.playerHref(L, r[ix.id], S) : CC.teamHref(L, r[ix.id], S); };
      var col = function (r) { return kind === 'players' ? CC.tcol(L, r[ix.team]) : CC.tcol(L, r[ix.id]); };
      QKC.scatter('#lab-sc', { points: rs.map(function (r) { return { x: r[ix[x]], y: r[ix[y]], name: r[ix.name] + (kind === 'players' ? ' · ' + CC.tabbr(L, r[ix.team]) : ''), label: kind === 'players' ? String(r[ix.name]).split(' ').slice(-1)[0] : CC.tabbr(L, r[ix.id]), color: col(r), href: href(r), size: rs.length > 300 ? 7 : 10 }; }),
        xName: mk[x].label, yName: mk[y].label, xFmt: function (v) { return CC.fmtMetric(mk[x], v); }, yFmt: function (v) { return CC.fmtMetric(mk[y], v); }, labelTop: 10, xInverse: false, yInverse: !!mk[y].lower });
      var cols = ['Name'].concat(kind === 'players' ? ['Team', 'Pos'] : ['Conf.']).concat(num.map(function (m) { return { label: m.label, align: 'right', title: m.desc || '' }; }));
      QK.$('#lab-tbl', el).innerHTML = U.card(rs.length + ' rows', '', U.table(cols, rs.slice(0, 600).map(function (r) {
        return { cells: [{ html: '<a href="' + esc(href(r)) + '">' + esc(r[ix.name]) + '</a>', v: r[ix.name] }].concat(kind === 'players' ? [{ html: U.teamEnt(L, r[ix.team], { abbr: true, season: S }), v: CC.tname(L, r[ix.team]) }, esc(r[ix.pos] || '—')] : [esc(CC.cname(L, r[ix.conference]))])
          .concat(num.map(function (m) { var v = r[ix[m.key]]; return { v: isNum(v) ? v : null, html: CC.fmtMetric(m, v) }; })), _href: href(r) };
      }), { maxHeight: 560 }));
      U.wire(QK.$('#lab-tbl', el));
    }
    ['#lab-x', '#lab-y', '#lab-g', '#lab-gp'].forEach(function (s) { var n = QK.$(s, el); if (n) n.addEventListener(s === '#lab-gp' ? 'input' : 'change', paint); });
    QK.seg(QK.$('#lab-kind', el), function (v) { CC.go(CC.href(L, 'lab', null, S, 'kind=' + v)); });
    paint();
  });
});

/* ── model ───────────────────────────────────────────────────────────── */
/* A small Markdown renderer for the methodology files (headings, paragraphs, lists, tables, code, emphasis, links). */
function inline(s) {
  return esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
CC.md = function (txt) {
  /* unfilled template tokens (a line that is only CAPS_WITH_UNDERSCORES) are dropped */
  var lines = String(txt || '').replace(/\r/g, '').split('\n').filter(function (l) { return !/^\s*[A-Z][A-Z0-9]*(_[A-Z0-9]+)+\s*$/.test(l); }), out = [], i = 0;
  while (i < lines.length) {
    var l = lines[i];
    if (/^```/.test(l)) { var code = []; i++; while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]); i++; out.push('<pre class="cc-pre"><code>' + esc(code.join('\n')) + '</code></pre>'); continue; }
    var h = /^(#{1,4})\s+(.*)$/.exec(l);
    if (h) { var n = Math.min(4, h[1].length + 1); out.push('<h' + n + '>' + inline(h[2]) + '</h' + n + '>'); i++; continue; }
    if (/^\|/.test(l)) {
      var rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) { rows.push(lines[i]); i++; }
      var cells = function (r) { return r.replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); }); };
      var head = cells(rows[0]), body = rows.slice(1).filter(function (r) { return !/^\|[\s:|-]+\|?$/.test(r); });
      out.push('<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr>' + head.map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        body.map(function (r) { return '<tr>' + cells(r).map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>');
      continue;
    }
    if (/^\s*[-*]\s+/.test(l)) {
      var items = [];
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (/^\s*[-*]\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*[-*]\s+/, '')); else items[items.length - 1] += ' ' + lines[i].trim();
        i++;
      }
      out.push('<ul>' + items.map(function (x) { return '<li>' + inline(x) + '</li>'; }).join('') + '</ul>');
      continue;
    }
    if (/^\s*\d+\.\s+/.test(l)) {
      var ol = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) ol.push(lines[i++].replace(/^\s*\d+\.\s+/, ''));
      out.push('<ol>' + ol.map(function (x) { return '<li>' + inline(x) + '</li>'; }).join('') + '</ol>');
      continue;
    }
    if (!l.trim()) { i++; continue; }
    var para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\||\s*[-*]\s+|\s*\d+\.\s+)/.test(lines[i])) para.push(lines[i++]);
    out.push('<p>' + inline(para.join(' ')) + '</p>');
  }
  return out.join('');
};
var FALLBACK = {
  cfb: '## Football models\n\n- **Expected points (EP) and EPA** from every ESPN play: down, distance, field position and time, fitted on college plays. Garbage time (lopsided scores late) is flagged and left out of team ratings.\n' +
    '- **Team ratings**: opponent-adjusted offense and defense (EPA per play and success rate) and a points rating (margin, recency-weighted, capped), blended with weights fitted walk-forward. Preseason: last season regressed toward the conference.\n' +
    '- **Game model**: expected margin from the two ratings, home field, rest and travel; a normal margin distribution gives the win probability, total and fair spread.\n' +
    '- **Season simulation**: the remaining schedule thousands of times; conference title games; the 12-team College Football Playoff seeded by a committee-ranking proxy fitted on the committee’s past rankings.\n' +
    '- **Players**: EPA above replacement by position; transfers inferred from box scores and rosters; fantasy projections from usage and the opponent.\n',
  bb: '## Basketball models\n\n- **Ratings**: opponent-adjusted offensive and defensive efficiency per 100 possessions and tempo (ridge regression with recency weights and home court), with a Kalman path through the season. Preseason: last season regressed.\n' +
    '- **Game model**: expected margin and total from efficiency and tempo; win probability from the margin distribution.\n' +
    '- **Season simulation**: regular season, conference tournaments (formats approximated where no bracket is published), automatic bids, a selection and seeding model fitted on past fields, and the 68-team bracket with the First Four.\n' +
    '- **Players**: a box-score value above replacement scaled so a team’s players add up to its margin; transfers inferred; fantasy points and 9-category projections.\n'
};

function calibration(node, L, d) {
  if (!CC.ok(d)) { node.innerHTML = U.missing('The backtest', d); return; }
  var s = d.summary || {}, m = s.model || {}, c = s.close || {}, vc = s.vs_close || {}, el0 = s.elo || {};
  var html = '<div class="qk-kpis cc-kpis">' +
    QK.kpi({ label: 'Games tested', value: isNum(d.n_games) ? QK.fmt.num(d.n_games) : '—', sub: (d.seasons || []).length ? d.seasons[0] + '–' + d.seasons[d.seasons.length - 1] : '' }) +
    QK.kpi({ label: 'Margin error, model', value: CC.f(vc.mae_model, 2), sub: 'closing line ' + CC.f(vc.mae_close, 2) + ' (same games)', tip: 'Mean absolute error of the predicted margin, points' }) +
    QK.kpi({ label: 'Against the spread', value: CC.pct(vc.ats_hit, 1), sub: (isNum(vc.ats_n) ? QK.fmt.num(vc.ats_n) + ' games' : '') + (isNum(vc.ats_se) ? ' · ± ' + CC.pct(vc.ats_se, 1) : ''), tip: 'Share of games in which the model’s side beat the closing spread; 52.4% is the break-even at a −110 price' }) +
    QK.kpi({ label: 'Brier score', value: CC.f(m.brier, 3), sub: 'closing moneyline ' + CC.f(c.brier, 3) + ' · Elo ' + CC.f(el0.brier, 3), tip: 'Mean squared error of the win probability; lower is better' }) +
    (isNum(vc.total_mae_model) ? QK.kpi({ label: 'Total error', value: CC.f(vc.total_mae_model, 2), sub: 'closing total ' + CC.f(vc.total_mae_close, 2) }) : '') + '</div>';
  html += '<p class="cc-note">Walk-forward: every game is predicted with ratings fitted only on games before its date, and nothing is tuned on the season being tested. The closing line is the hardest benchmark there is; matching it is good, beating it is rare.</p>';
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Calibration', 'When the model says 70%, does the team win about 70% of the time? Points on the diagonal are well calibrated.', U.chart('cal-rel', 320, 'Reliability diagram')) + '</div>' +
    '<div class="qk-span-6">' + U.card('Margin error by season', 'Mean absolute error of the predicted margin, model against the closing line.', U.chart('cal-ps', 320, 'Margin error by season')) + '</div></div>';
  var summ = [['Model', m], ['Closing line', c], ['Elo baseline', el0]].concat(s.espn_predictor ? [['ESPN predictor', s.espn_predictor]] : []);
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Summary', '', U.table(['', { label: 'Games', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Log loss', align: 'right' }, { label: 'Winner right', align: 'right' }, { label: 'Margin MAE', align: 'right' }],
    summ.map(function (r) { var x = r[1] || {}; return [r[0], isNum(x.n) ? QK.fmt.num(x.n) : '—', CC.f(x.brier, 4), CC.f(x.logloss, 4), CC.pct(x.acc, 1), CC.f(x.mae, 2)]; }), { sticky: false })) + '</div>' +
    '<div class="qk-span-6">' + U.card('By size of the spread', '', U.table([{ label: 'Spread', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'MAE model', align: 'right' }, { label: 'MAE close', align: 'right' }, { label: 'ATS', align: 'right' }], (d.by_spread || []).map(function (r) {
      return [r.lo + '–' + r.hi, r.n, CC.f(r.mae_model, 2), CC.f(r.mae_close, 2), CC.pct(r.ats_hit, 1)]; }), { sticky: false })) + '</div></div>';
  html += U.card('Season by season', '', U.table([{ label: 'Season', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'With a close', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Brier close', align: 'right' }, { label: 'MAE', align: 'right' }, { label: 'MAE close', align: 'right' }, { label: 'ATS', align: 'right' }], (d.per_season || []).slice().reverse().map(function (r) {
    var mm = r.model || {}, cc = r.close || {};
    return [{ v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, r.n, r.n_close, CC.f(mm.brier, 4), CC.f(cc.brier, 4), CC.f(mm.mae, 2), CC.f(cc.mae, 2), CC.pct(r.ats_hit, 1)];
  }), { maxHeight: 520 }));
  if (d.sim && Object.keys(d.sim).length) {
    /* numbers at the top level and one level down (e.g. "tournament"); text becomes a note; per-season lists are left out */
    var srows = [], snotes = [];
    Object.keys(d.sim).forEach(function (k) {
      var v = d.sim[k];
      if (isNum(v)) srows.push([k, v]);
      else if (typeof v === 'string') snotes.push(v);
      else if (v && typeof v === 'object' && !Array.isArray(v)) Object.keys(v).forEach(function (k2) { if (isNum(v[k2])) srows.push([k + ' · ' + k2, v[k2]]); else if (typeof v[k2] === 'string') snotes.push(v[k2]); });
    });
    if (srows.length) html += U.card('Season simulation backtest', snotes.map(esc).join(' '), U.table(['Measure', { label: 'Value', align: 'right' }], srows.map(function (r) {
      return [esc(r[0].replace(/_/g, ' ')), { v: r[1], html: Math.round(r[1]) === r[1] ? String(r[1]) : CC.f(r[1], 3) }]; }), { sticky: false }));
  }
  if ((d.notes || []).length) html += '<ul class="cc-notes">' + d.notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>';
  node.innerHTML = html;
  U.wire(node);
  var cal = (d.calibration || []).filter(function (r) { return isNum(r.p_mean) && isNum(r.y_mean); });
  if (cal.length) QKC.scatter('#cal-rel', { points: cal.map(function (r) { return { x: r.p_mean, y: r.y_mean, name: CC.pct(r.lo, 0) + '–' + CC.pct(r.hi, 0) + ' (' + r.n + ' games)', size: Math.max(7, Math.min(22, Math.sqrt(r.n) / 2)) }; }),
    xName: 'Predicted', yName: 'Observed', xMin: 0, xMax: 1, yMin: 0, yMax: 1, diagonal: { label: 'perfect' }, xFmt: function (v) { return CC.pct(v, 0); }, yFmt: function (v) { return CC.pct(v, 0); } });
  var ps = (d.per_season || []).filter(function (r) { return r.model && isNum(r.model.mae); });
  if (ps.length) QKC.line('#cal-ps', { x: ps.map(function (r) { return CC.seasonLabel(L, r.season); }), series: [{ name: 'Model', data: ps.map(function (r) { return r.model.mae; }), color: QK.cssVar('--c-1'), symbols: true }, { name: 'Closing line', data: ps.map(function (r) { return r.close && isNum(r.close.mae) ? r.close.mae : null; }), color: QK.cssVar('--c-2'), symbols: true }], yScale: true, yFmt: function (v) { return CC.f(v, 1); }, legend: true });
}

CC.route('model', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  var list = [['method', 'Methodology'], ['calibration', 'Calibration'], ['glossary', 'Glossary'], ['terms', 'Terms']];
  var tab = U.tab(p, ['method', 'calibration', 'glossary', 'terms'], 'method');
  el.innerHTML = U.head('Model', 'How the numbers are made, how well they have done against the closing line, and what every term means.', CC.LNAME[L]) + U.tabs(L, 'model', list, null, tab) + '<div id="mb">' + QK.skeleton('lines', 8) + '</div>';
  var body = QK.$('#mb', el);
  if (tab === 'terms') { var t = document.getElementById('disclaimer-template'); body.innerHTML = t ? t.innerHTML : ''; return null; }
  if (tab === 'calibration') return CC.load(CC.lpath(L, 'calibration.json')).then(function (d) { if (U.alive(el)) calibration(body, L, d); });
  if (tab === 'glossary') return CC.load('glossary.json').then(function (g) {
    if (!U.alive(el)) return;
    if (!CC.ok(g)) { body.innerHTML = U.missing('The glossary', g); return; }
    body.innerHTML = '<div class="cc-gloss">' + (g.groups || []).map(function (gr) {
      return U.card(gr.name, '', '<dl class="cc-dl">' + (gr.entries || []).map(function (e) { return '<dt id="g-' + esc(e.key) + '">' + esc(e.label) + '</dt><dd>' + esc(e.desc) + '</dd>'; }).join('') + '</dl>');
    }).join('') + '</div>';
  });
  var file = fb ? 'MODELS_CFB.md' : 'MODELS_HOOPS.md';
  return new Promise(function (resolve) {
    fetch(file, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }).then(function (txt) { resolve(txt); }, function () { resolve(null); });
  }).then(function (txt) {
    if (!U.alive(el)) return;
    body.innerHTML = '<div class="qk-card cc-prose">' + (txt ? CC.md(txt) : CC.md(fb ? FALLBACK.cfb : FALLBACK.bb) + '<p class="qk-muted">The full methodology document is published with the next build.</p>') +
      '<h3>Data</h3><p>Schedules, scores, box scores, plays, rankings, rosters and betting lines come from ESPN’s public data; prediction-market prices from Kalshi and Polymarket where listed. Sources whose terms forbid reuse are left out: no Sports-Reference, KenPom, Barttorvik, 247Sports, On3, Rivals, Massey or NCAA.com data. ' +
      'Recruiting rankings and the official transfer portal are not used; transfers here are inferred from rosters and box scores.</p></div>';
  });
});

})(window.CC);
