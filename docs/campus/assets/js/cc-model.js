/* The Quant Campus — Model (#/<L>/model?tab=method|calibration|market|moves|glossary|terms). The Lab became the
 * Scouting Room's Chart view and the Teams page's style map (round 9; cc-scout.js, cc-teamspage.js).
 * Model: the "How we're doing" tab (?tab=calibration; round 6: QK.doing, our favourites' record this week and QK.howSure from
 * <L>/calibration.json, shown only when the file is there, then the backtest), methodology (docs/campus/MODELS_CFB.md or MODELS_HOOPS.md rendered), the walk-forward backtest against
 * closing lines (calibration.json), the glossary (data/glossary.json) and the terms.
 * Payload copy still reworded here for the local payloads (23 Oct 2026): noteV2 (the local mbb / wbb / cfb
 * calibration.json notes say "price"), GLOSS_V2 / GLOSS_DROP (the local glossary.json carries "Edge", "Fair spread"
 * and the market's "price"). The deployed payloads are clean (checked 23 Oct), so these go after the next local
 * rebuild. */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

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

/* Builder notes in the v2 voice (the payload text is shared; the wording is changed for display only). */
function noteV2(n) {
  return String(n || '').replace(/where both prices are stored/g, 'where both sides are stored').replace(/put the price \(-110\)/g, 'take the usual margin out').replace(/the -110 quote/g, 'a placeholder quote').replace(/-110/g, 'the standard line')
    .replace(/\bprices?\b/gi, 'numbers').replace(/\bpriced\b/gi, 'posted').replace(/\bedge\b/gi, 'advantage');
}
/* Glossary in the v2 voice (the payload is shared with the builder; these entries are reworded here, betting terms
 * the site no longer shows are dropped). */
var GLOSS_DROP = { edge: 1 };
var GLOSS_V2 = {
  p_home: { label: 'Our win chance', desc: 'Our pre-game chance the home side wins, from the two ratings, home field and rest.' },
  spread_fair: { label: 'Our margin', desc: 'Our expected winning margin in points ("OSU by 7.5").' },
  market: { label: 'Market (reference)', desc: 'The market’s chance (Kalshi or Polymarket, with its margin taken out; else the closing line ESPN shows), shown beside ours on game pages and the Model page as a reference.' },
  ats: { label: 'Our side v the closing spread', desc: 'On the Model page: how often our margin landed on the right side of the market’s closing line; 50% means no better than the market.' },
  p_cfp: { label: 'Playoff chance' },
  upset: { label: 'Upset chance', desc: 'Our chance the lower seed wins a game.' },
  wp: { label: 'Win chance chart', desc: 'Our chance of winning after each play; the steepest swings are the game’s highest-leverage moments.' }
};

/* The market-informed model (calibration.json "informed"): status, dev and sealed-test numbers, v the market. */
function informedCard(L, inf) {
  if (!inf || !(inf.test || inf.dev)) return '';
  var ci = function (x) { return x && isNum(x[0]) ? (x[0] > 0 ? '+' : '') + CC.f(x[0], 4) + ' [' + CC.f(x[1], 4) + ', ' + CC.f(x[2], 4) + ']' : '—'; };
  var row = function (lab, r) {
    if (!r) return null;
    return [lab, isNum(r.n) ? QK.fmt.num(r.n) : '—', CC.f(r.ll0, 4) + ' → ' + CC.f(r.ll1, 4), ci(r.d_ll), CC.f(r.brier0, 4) + ' → ' + CC.f(r.brier1, 4), CC.f(r.slope0, 2) + ' → ' + CC.f(r.slope1, 2)];
  };
  var rows = [row('Dev seasons (choices made here)', inf.dev), row('Sealed test seasons', inf.test)].filter(Boolean);
  var tbl = U.table(['', { label: 'Games', align: 'right' }, { label: 'Log loss, base → informed', align: 'right' }, { label: 'Difference [95% CI]', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Calibration slope', align: 'right' }], rows, { sticky: false });
  var mg = (inf.test || {}).ml_games, mc = (inf.test || {}).mae_close_games, mkt = '';
  if (mg) {
    mkt = U.table(['On test games with a closing moneyline', { label: 'Log loss', align: 'right' }, { label: 'Minus the market [95% CI]', align: 'right' }],
      [['Base model', CC.f(mg.ll0, 4), ci(mg.m0_minus_mkt)], ['Market-informed', CC.f(mg.ll1, 4), ci(mg.new_minus_mkt)], ['De-vigged closing moneyline', CC.f(mg.ll_market, 4), '']], { sticky: false }) +
      '<p class="cc-note">' + (isNum(mg.gap_closed) ? 'Share of the base model’s gap to the market closed: <b>' + CC.pct(mg.gap_closed, 0) + '</b>. ' : '') +
      (mc ? 'Margin error on games with a close: base ' + CC.f(mc.m0, 2) + ', informed ' + CC.f(mc.new, 2) + ', closing line ' + CC.f(mc.close, 2) + '.' : '') + '</p>';
  }
  var ps = inf.per_season ? Object.keys(inf.per_season).sort().map(function (k) { var r = inf.per_season[k]; return [{ v: Number(k), html: esc(CC.seasonLabel(L, Number(k))) }, r.n, ci(r.d_ll)]; }) : [];
  var per = ps.length ? U.table([{ label: 'Test season', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'Log-loss difference [95% CI]', align: 'right' }], ps, { sticky: false }) : '';
  var lab = { promoted: 'Published', trial: 'On trial', 'not promoted': 'Not promoted' }[inf.status] || inf.status;
  return U.card('Market-informed model · ' + esc(lab), esc(noteV2(inf.text || '')) + ' Ratings learned from earlier games’ closing lines (and, where it helped, what the market says beyond our ratings) are stacked with the ratings model; every number is walk-forward and the promotion rule (a paired log-loss interval below zero, Brier and calibration no worse) was fixed before the test.',
    '<div class="qk-stack">' + tbl + mkt + per + '</div>');
}

/* "How we're doing" (?tab=calibration): our own record, walk-forward: calibration, Brier and log loss against the Elo
   baseline, season by season, and the season-simulation backtest. The market's numbers are on their own tab. */
function calibration(node, L, d) {
  if (!CC.ok(d)) { node.innerHTML = U.missing('The backtest', d); return; }
  var s = d.summary || {}, m = s.model || {}, el0 = s.elo || {};
  var html = U.stats([
    { label: 'Brier score, ours', value: CC.f(m.brier, 3), signal: true, sub: 'Elo baseline ' + CC.f(el0.brier, 3) + ' · a coin flip 0.250', tip: 'Mean squared error of our win chance; lower is better; 0.250 is a coin flip' },
    { label: 'Winner right', value: CC.pct(m.acc, 1), sub: 'our favourite won' },
    { label: 'Margin error, ours', value: CC.f(m.mae, 2), unit: 'pts', sub: 'mean absolute error of the predicted margin', tip: 'Mean absolute error of the predicted margin, points' },
    { label: 'Games tested', value: isNum(d.n_games) ? QK.fmt.num(d.n_games) : '—', sub: (d.seasons || []).length ? CC.seasonLabel(L, d.seasons[0]) + ' to ' + CC.seasonLabel(L, d.seasons[d.seasons.length - 1]) + ', walk-forward' : '' }]);
  html += '<p class="cc-note">Walk-forward: every game is predicted with ratings fitted only on games before its date, and nothing is tuned on the season being tested.</p>';
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Calibration', 'When we say 70%, does the team win about 70% of the time? Points on the diagonal are well calibrated; dot size is the number of games.', U.chart('cal-rel', 320, 'Reliability diagram')) + '</div>' +
    '<div class="qk-span-6">' + U.card('Brier score by season', 'Ours (blue) and the Elo baseline (grey); lower is better.', U.chart('cal-br', 320, 'Brier score by season')) + '</div></div>';
  var summ = [['Ours', m], ['Elo baseline', el0]].concat(s.espn_predictor ? [['ESPN predictor', s.espn_predictor]] : []);
  html += U.card('Summary', '', U.table(['', { label: 'Games', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Log loss', align: 'right' }, { label: 'Winner right', align: 'right' }, { label: 'Margin MAE', align: 'right' }],
    summ.map(function (r) { var x = r[1] || {}; return [r[0], isNum(x.n) ? QK.fmt.num(x.n) : '—', CC.f(x.brier, 4), CC.f(x.logloss, 4), CC.pct(x.acc, 1), CC.f(x.mae, 2)]; }), { sticky: false }));
  html += '<details class="cc-data"><summary>Season by season</summary>' + U.table([{ label: 'Season', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Margin MAE', align: 'right' }], (d.per_season || []).slice().reverse().map(function (r) {
    var mm = r.model || {};
    return [{ v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, r.n, CC.f(mm.brier, 4), CC.f(mm.mae, 2)];
  }), { maxHeight: 520 }) + '</details>';
  if (d.sim && Object.keys(d.sim).length) {
    /* numbers at the top level and one level down (e.g. "tournament"); text becomes a note; per-season lists are left out */
    var srows = [], snotes = [];
    Object.keys(d.sim).forEach(function (k) {
      var v = d.sim[k];
      if (isNum(v)) srows.push([k, v]);
      else if (typeof v === 'string') snotes.push(noteV2(v));
      else if (v && typeof v === 'object' && !Array.isArray(v)) Object.keys(v).forEach(function (k2) { if (isNum(v[k2])) srows.push([k + ' · ' + k2, v[k2]]); else if (typeof v[k2] === 'string') snotes.push(noteV2(v[k2])); });
    });
    if (srows.length) html += U.card('Season simulation backtest', snotes.map(esc).join(' '), U.table(['Measure', { label: 'Value', align: 'right' }], srows.map(function (r) {
      return [esc(r[0].replace(/_/g, ' ')), { v: r[1], html: Math.round(r[1]) === r[1] ? String(r[1]) : CC.f(r[1], 3) }]; }), { sticky: false }));
  }
  node.innerHTML = html;
  U.wire(node);
  var cal = (d.calibration || []).filter(function (r) { return isNum(r.p_mean) && isNum(r.y_mean); });
  if (cal.length) QKC.scatter('#cal-rel', { points: cal.map(function (r) { return { x: r.p_mean, y: r.y_mean, name: CC.pct(r.lo, 0) + '–' + CC.pct(r.hi, 0) + ' (' + r.n + ' games)', size: Math.max(7, Math.min(22, Math.sqrt(r.n) / 2)) }; }),
    xName: 'Our chance (predicted)', yName: 'How often it happened', xMin: 0, xMax: 1, yMin: 0, yMax: 1, diagonal: { label: 'spot on' }, xFmt: function (v) { return CC.pct(v, 0); }, yFmt: function (v) { return CC.pct(v, 0); } });
  var ps = (d.per_season || []).filter(function (r) { return r.model && isNum(r.model.brier); });
  if (ps.length) QKC.line('#cal-br', { x: ps.map(function (r) { return CC.seasonLabel(L, r.season); }), series: [{ name: 'Ours', data: ps.map(function (r) { return r.model.brier; }), color: QK.cssVar('--signal'), symbols: true }].concat(ps.some(function (r) { return r.elo && isNum(r.elo.brier); }) ? [{ name: 'Elo', data: ps.map(function (r) { return r.elo && isNum(r.elo.brier) ? r.elo.brier : null; }), color: QK.cssVar('--c-market'), symbols: true }] : []), yScale: true, yFmt: function (v) { return CC.f(v, 3); }, legend: true, xName: 'Season', yName: 'Brier score' });
}

/* "Our forecasts v the market" (?tab=market): ours beside the market's closing numbers, a reference, on the same games:
   margin and total error, our side of the closing spread, the market-informed model's sealed test. */
function marketTab(node, L, d) {
  if (!CC.ok(d)) { node.innerHTML = U.missing('The backtest', d); return; }
  var s = d.summary || {}, m = s.model || {}, c = s.close || {}, vc = s.vs_close || {};
  var html = U.stats([
    { label: 'Brier score, ours', value: CC.f(m.brier, 3), signal: true, sub: 'market (closing moneyline) ' + CC.f(c.brier, 3), tip: 'Mean squared error of the win chance; lower is better' },
    { label: 'Margin error, ours', value: CC.f(vc.mae_model, 2), unit: 'pts', sub: 'market (closing line) ' + CC.f(vc.mae_close, 2) + ' on the same games', tip: 'Mean absolute error of the predicted margin, points' },
    { label: 'Our side of the closing spread', value: CC.pct(vc.ats_hit, 1), sub: (isNum(vc.ats_n) ? QK.fmt.num(vc.ats_n) + ' games' : '') + (isNum(vc.ats_se) ? ' · ± ' + CC.pct(vc.ats_se, 1) : ''), tip: 'Share of games in which our margin landed on the right side of the closing line; 50% means no better than the market' },
    isNum(vc.total_mae_model) ? { label: 'Total error, ours', value: CC.f(vc.total_mae_model, 2), unit: 'pts', sub: 'market (closing total) ' + CC.f(vc.total_mae_close, 2) } : null]);
  html += '<p class="cc-note">The market’s closing numbers are the hardest benchmark there is, shown here as a reference: matching them is good, beating them is rare. The rest of the site leads with our own forecasts.</p>';
  html += informedCard(L, d.informed);
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Margin error by season', 'Mean absolute error of the predicted margin: ours (blue) and the closing line (grey).', U.chart('cal-ps', 320, 'Margin error by season')) + '</div>' +
    '<div class="qk-span-6">' + U.card('By size of the spread', '', U.table([{ label: 'Spread', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'Our margin error', align: 'right' }, { label: 'Closing line’s', align: 'right' }, { label: 'Our side', align: 'right' }], (d.by_spread || []).map(function (r) {
      return [r.lo + '–' + r.hi, r.n, CC.f(r.mae_model, 2), CC.f(r.mae_close, 2), CC.pct(r.ats_hit, 1)]; }), { sticky: false })) + '</div></div>';
  html += '<details class="cc-data"><summary>Season by season</summary>' + U.table([{ label: 'Season', align: 'right' }, { label: 'Games', align: 'right' }, { label: 'With a close', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Brier close', align: 'right' }, { label: 'MAE', align: 'right' }, { label: 'MAE close', align: 'right' }, { label: 'Our side', align: 'right' }], (d.per_season || []).slice().reverse().map(function (r) {
    var mm = r.model || {}, cc = r.close || {};
    return [{ v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, r.n, r.n_close, CC.f(mm.brier, 4), CC.f(cc.brier, 4), CC.f(mm.mae, 2), CC.f(cc.mae, 2), CC.pct(r.ats_hit, 1)];
  }), { maxHeight: 520 }) + '</details>';
  if ((d.notes || []).length) html += '<ul class="cc-notes">' + d.notes.map(function (n) { return '<li>' + esc(noteV2(n)) + '</li>'; }).join('') + '</ul>';
  node.innerHTML = html;
  U.wire(node);
  var ps = (d.per_season || []).filter(function (r) { return r.model && isNum(r.model.mae); });
  if (ps.length) QKC.line('#cal-ps', { x: ps.map(function (r) { return CC.seasonLabel(L, r.season); }), series: [{ name: 'Ours', data: ps.map(function (r) { return r.model.mae; }), color: QK.cssVar('--signal'), symbols: true }, { name: 'Closing line', data: ps.map(function (r) { return r.close && isNum(r.close.mae) ? r.close.mae : null; }), color: QK.cssVar('--c-market'), symbols: true }], yScale: true, yFmt: function (v) { return CC.f(v, 1); }, legend: true, xName: 'Season', yName: 'Margin error (points)' });
}

/* Who moves next (MOVES_VIEWS.md): movement.json's method and its pre-registered validation, once published. The
 * top-rated team's page says whether it is (its `movement` key), so nothing is fetched before it exists. */
function movesMethod(L, node) {
  var S = CC.cur(L), top = (CC.info(L).model_top || [])[0];
  if (!node || !S || !top) return;
  CC.load(CC.path(L, S, 'teams/' + top.team + '.json')).then(function (tp) {
    return CC.ok(tp) && tp.movement ? CC.load(CC.path(L, S, 'movement.json')) : null;
  }).then(function (mv) {
    if (!mv || !U.alive(node)) return;
    var meta = mv.meta || {}, val = meta.validation || {};
    if (!CC.ok(mv)) { node.innerHTML = U.card('Who moves next', QK.tag('Inferred from box scores, not the official transfer portal'), QK.empty('Not published yet', mv.reason || '')); return; }
    var rows = Object.keys(val).filter(function (k) { return val[k] && typeof val[k] === 'object'; }).map(function (k) {
      var v = val[k], ci = v.ci || v.d_ci || null;
      var num = function (x) { return isNum(x) ? CC.f(x, 4) : '—'; };
      return [esc(k), num(v.model !== undefined ? v.model : v.ll1), num(v.base !== undefined ? v.base : v.ll0), Array.isArray(ci) ? '[' + num(ci[0]) + ', ' + num(ci[1]) + ']' : '—', v.passed === true ? 'passed' : v.passed === false ? 'did not pass' : '—'];
    });
    node.innerHTML = '<div class="qk-card cc-prose" style="margin-top:var(--sp-4)"><h3>Who moves next</h3>' + QK.tag('Inferred from box scores, not the official transfer portal') +
      (meta.method ? CC.md(String(meta.method)) : '') + (rows.length ? U.table(['Test', { label: 'Model', align: 'right' }, { label: 'Base', align: 'right' }, { label: '95% CI', align: 'right' }, 'Result'], rows, { sticky: false }) : '') + '</div>';
  });
}

CC.route('model', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L);
  /* the standing Model order (round 9): How it works, How we're doing, the other Model tabs, Glossary, Terms */
  var list = [['method', 'How it works'], ['calibration', 'How we’re doing'], ['market', 'Our forecasts v the market'], ['moves', 'Who moves next'], ['glossary', 'Glossary'], ['terms', 'Terms']];
  var tab = U.tab(p, list.map(function (x) { return x[0]; }), 'method');
  el.innerHTML = U.head('Model', 'How our numbers are made, how well they have done, and what every term means.', U.kicker(L, S)) +
    U.tabs(L, 'model', list, null, tab) + (tab === 'calibration' ? '<div id="mb-sure"></div>' : '') + '<div id="mb">' + QK.skeleton('lines', 8) + '</div>';
  var body = QK.$('#mb', el);
  /* round 6, "How we're doing" (QK.doing) at the top of its tab: our favourites' record this week (index.json
     levels.<L>.digest.record), then our chance against how often the home team won, walk-forward, from the level's
     calibration.json when it is there (CC.calib reads the kit's shape and the builder's own) */
  if (QK.$('#mb-sure', el)) CC.load(CC.lpath(L, 'calibration.json')).then(function (cj) {
    var host = QK.$('#mb-sure', el);
    var cb = CC.calib(cj);
    if (!host || !U.alive(host) || !cb) return;
    var ss = (cj.seasons || []).map(Number).filter(isNum).sort(function (x, y) { return x - y; });
    host.innerHTML = '<section class="qk-section cc-sec" style="margin-top:var(--sp-6)" id="mb-sure-m"></section>';
    var rec = (CC.info(L).digest || {}).record;
    QK.doing(QK.$('#mb-sure-m', host), { record: rec, bins: cb.bins, brier: cb.brier, n: cb.n, league: CC.LSHORT[L], span: ss.length ? CC.seasonLabel(L, ss[0]) + ' to ' + CC.seasonLabel(L, ss[ss.length - 1]) : '', subject: 'the home team', unit: 'games',
      sub: (rec && rec.n ? 'Our favourites this week, then every ' : 'Every ') + 'pre-game forecast from the game model, each made with only the games before it, grouped by the chance we gave the home team. When the two match, our numbers mean what they say.' });
  });
  if (tab === 'terms') { var t = document.getElementById('disclaimer-template'); body.innerHTML = t ? t.innerHTML : ''; return null; }
  if (tab === 'calibration') return CC.load(CC.lpath(L, 'calibration.json')).then(function (d) { if (U.alive(el)) calibration(body, L, d); });
  if (tab === 'market') return CC.load(CC.lpath(L, 'calibration.json')).then(function (d) { if (U.alive(el)) marketTab(body, L, d); });
  if (tab === 'moves') { body.innerHTML = '<div id="mb-moves">' + QK.empty('Who moves next appears once it is published', 'Our model of who leaves each roster is published for a level once a quarter of the season’s box scores are in.') + '</div>'; movesMethod(L, QK.$('#mb-moves', el)); return null; }
  if (tab === 'glossary') return CC.load('glossary.json').then(function (g) {
    if (!U.alive(el)) return;
    if (!CC.ok(g)) { body.innerHTML = U.missing('The glossary', g); return; }
    /* round 9: search first, then the groups; the payload metrics split by level (the label's "(CFB)" suffix) */
    var groups = [];
    (g.groups || []).forEach(function (gr) {
      var es = (gr.entries || []).filter(function (e) { return !GLOSS_DROP[e.key]; }).map(function (e) { var o = GLOSS_V2[e.key] || {}; return { key: e.key, label: CC.uk(o.label || e.label), desc: CC.uk(o.desc || e.desc) }; });
      if (gr.name !== 'Metrics') { groups.push({ name: gr.name, entries: es }); return; }
      ['CFB', 'MBB', 'WBB'].forEach(function (lv) {
        var sub = es.filter(function (e) { return / \((CFB|MBB|WBB)\)$/.test(e.label) ? e.label.slice(-4, -1) === lv : lv === 'CFB'; }).map(function (e) { return { key: e.key, label: e.label.replace(/ \((CFB|MBB|WBB)\)$/, ''), desc: e.desc }; });
        if (sub.length) groups.push({ name: 'Metrics: ' + CC.LNAME[lv.toLowerCase()], entries: sub });
      });
    });
    var mine = L.toUpperCase();
    groups.sort(function (a, b) { var x = a.name.indexOf('Metrics') === 0, y = b.name.indexOf('Metrics') === 0; if (x !== y) return x ? 1 : -1; if (x) return (b.name.indexOf(CC.LNAME[L]) >= 0) - (a.name.indexOf(CC.LNAME[L]) >= 0); return 0; });
    var n = groups.reduce(function (t, gr) { return t + gr.entries.length; }, 0);
    body.innerHTML = '<div class="cc-gsearch"><label class="qk-sbar-f grow"><span class="qk-within-l">Find a term</span><input class="qk-input" id="gl-q" type="search" placeholder="Rating, EPA, value, true shooting…" autocomplete="off" aria-label="Find a term"></label><span class="cc-note" id="gl-n">' + n + ' terms</span></div>' +
      '<div class="cc-gloss">' + groups.map(function (gr) {
        return '<div class="cc-gl-g">' + U.card(gr.name, '', '<dl class="cc-dl">' + gr.entries.map(function (e) { return '<div class="cc-gl-e" data-t="' + esc((e.label + ' ' + e.desc).toLowerCase()) + '"><dt id="g-' + esc(e.key) + '">' + esc(e.label) + '</dt><dd>' + esc(e.desc) + '</dd></div>'; }).join('') + '</dl>') + '</div>';
      }).join('') + '</div>';
    void mine;
    var qi = QK.$('#gl-q', body);
    qi.addEventListener('input', function () {
      var q = qi.value.trim().toLowerCase(), hit = 0;
      QK.$$('.cc-gl-e', body).forEach(function (x) { var on = !q || x.getAttribute('data-t').indexOf(q) >= 0; x.hidden = !on; if (on) hit++; });
      QK.$$('.cc-gl-g', body).forEach(function (x) { x.hidden = !QK.$$('.cc-gl-e', x).some(function (e) { return !e.hidden; }); });
      QK.$('#gl-n', body).textContent = q ? hit + ' of ' + n + ' terms' : n + ' terms';
    });
  });
  /* round 9, "How it works" for fans: what the site does, then one chart per model in plain words (from this
     season's payloads); the developer document (MODELS_CFB.md / MODELS_HOOPS.md) is folded under "Technical detail" */
  var file = fb ? 'MODELS_CFB.md' : 'MODELS_HOOPS.md';
  var Sx = CC.cur(L) || S;
  return Promise.all([new Promise(function (resolve) {
    fetch(file, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }).then(function (txt) { resolve(txt); }, function () { resolve(null); });
  }), CC.season(L, Sx), CC.load(CC.path(L, Sx, 'value.json')), CC.load(CC.lpath(L, 'calibration.json'))]).then(function (a) {
    if (!U.alive(el)) return;
    var txt = a[0], season = CC.ok(a[1]) ? a[1] : null, val = CC.ok(a[2]) ? a[2] : null, cal = CC.ok(a[3]) ? a[3] : null;
    body.innerHTML = methodFans(L, Sx, season, val, cal) +
      '<details class="cc-tech qk-card"><summary>Technical detail: the models, the code and the tests</summary><div class="cc-prose">' + (txt ? CC.md(txt) : CC.md(fb ? FALLBACK.cfb : FALLBACK.bb) + '<p class="qk-muted">The full methodology document is published with the next build.</p>') +
      '<h3>Data</h3><p>Schedules, scores, box scores, plays, rankings, rosters and betting lines come from ESPN’s public data; prediction-market probabilities from Kalshi and Polymarket where listed. Sources whose terms forbid reuse are left out: no Sports-Reference, KenPom, Barttorvik, 247Sports, On3, Rivals, Massey or NCAA.com data. ' +
      'Recruiting rankings and the official transfer portal are not used; transfers here are inferred from rosters and box scores.</p></div></details>';
    methodCharts(L, Sx, season, val, cal, body);
  });
});

/* the fan-first opening of "How it works": what we do, then each model as a picture and a few plain sentences */
var SD_MARGIN = { cfb: 14.5, mbb: 11, wbb: 11 };
function methodFans(L, S, season, val, cal) {
  var fb = CC.fb(L), lw = fb ? 'college football (every FBS team)' : (L === 'mbb' ? 'men’s' : 'women’s') + ' college basketball (every Division I team)';
  var n = season && season.sim && isNum(season.sim.n_sims) ? QK.fmt.num(season.sim.n_sims) : 'thousands of';
  var card = function (k, title, text, chart) { return '<article class="qk-card cc-mx"><div class="qk-card-body"><div class="qk-kicker">' + esc(k) + '</div><h3 class="cc-mx-t">' + esc(title) + '</h3><p>' + text + '</p>' + chart + '</div></article>'; };
  var sm = cal && cal.summary && cal.summary.model ? cal.summary.model : null;
  return '<section class="qk-section cc-sec" style="margin-top:var(--sp-6)">' + QK.sectionHead({ kicker: 'How it works', title: 'Four models, in plain words',
    sub: 'The Quant Campus rates every team in ' + esc(lw) + ', turns two ratings into a chance for every game, plays the rest of the season ' + esc(n) + ' times for the playoff, tournament and title chances, and values every player against a replacement at the same position. Each one below, with a picture from this season.' }) +
    '<div class="cc-mx-grid">' +
    card('1 · Team ratings', 'How good is each team?', 'A rating is the margin we expect against an average ' + (fb ? 'FBS team on a neutral field, in points: +14 is two touchdowns better' : 'Division I team, in points per 100 possessions') + '. It is built from every result so far, adjusted for the opponent, with recent games counting a little more' + (fb ? ', and from how efficiently each side moves the ball play by play (expected points added)' : '') + '. The whiskers are the uncertainty: one standard error either side.', U.chart('mx-r', 300, 'Our top ten ratings with their uncertainty')) +
    card('2 · The game model', 'From two ratings to a chance', 'The gap between two ratings, plus home advantage and rest, is the margin we expect. Real games scatter around that margin (about ' + SD_MARGIN[L] + ' points either way), so a ' + (fb ? '7-point' : '5-point') + ' favourite still loses fairly often. The curve turns the expected margin into our win chance.', U.chart('mx-g', 300, 'Win chance by expected margin')) +
    card('3 · The season simulation', 'Playing the season ' + n + ' times', 'We play every remaining game with those chances, again and again, with the ratings themselves allowed to be wrong. ' + (fb ? 'Conference title games, the committee’s 12-team field (a model fitted on its past rankings) and the playoff are played out too.' : 'Conference tournaments, the selection committee’s field of 68 (a model fitted on past fields) and the bracket are played out too.') + ' A team’s title chance is the share of simulated seasons it wins it all.', '<div id="mx-s"></div>') +
    card('4 · Player value', 'What a player adds', fb ? 'Value is the expected points a player adds on their own plays over a replacement-level player at the same position (the non-starters), so a quarterback is judged against quarterbacks. Defenders and specialists are valued from the box score, so theirs is a floor.' : 'Value is a box-score rating per 100 possessions over a replacement-level player, scaled so a team’s players add up to its margin. Compare it within a position: guards against guards.', U.chart('mx-v', 300, 'The most valuable player at each position')) +
    '</div>' + (sm ? QK.explain('<b>How sure are we?</b> Over ' + QK.fmt.num(sm.n || cal.n_games || 0) + ' games, every one predicted with only the games before it, our favourite won ' + CC.pct(sm.acc, 0) + ' of the time. The calibration chart and the season-by-season record are on <a class="qk-link" href="' + esc(CC.href(L, 'model', null, null, 'tab=calibration')) + '">How we’re doing</a>.') : '') + '</section>';
}
function normCdf(z) { var t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2), p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - p : p; }
function methodCharts(L, S, season, val, cal, body) {
  var fb = CC.fb(L);
  var R = (season && season.ratings) || {};
  var top = ((season && season.power) || []).slice(0, 10);
  if (top.length && QK.$('#mx-r', body)) QKC.bar(QK.$('#mx-r', body), { cats: top.map(function (r) { return CC.tshort(L, r.team); }), horizontal: true, fmt: function (v) { return CC.signed(v, 1); },
    series: [{ name: 'Rating', data: top.map(function (r) { return r.rating; }), lo: top.map(function (r) { var x = R[String(r.team)] || {}; return isNum(x.se) ? r.rating - x.se : null; }), hi: top.map(function (r) { var x = R[String(r.team)] || {}; return isNum(x.se) ? r.rating + x.se : null; }) }],
    colors: top.map(function (r) { return CC.tcol(L, r.team); }), labelWidth: 96, valName: fb ? 'Rating (points v average)' : 'Rating (per 100 v average)', catName: 'Team' });
  else if (QK.$('#mx-r', body)) QK.$('#mx-r', body).innerHTML = QK.empty('Ratings appear with the season', '');
  var sd = SD_MARGIN[L], xs = [];
  for (var m = -24; m <= 24; m += 2) xs.push(m);
  QKC.line(QK.$('#mx-g', body), { xType: 'value', x: xs, series: [{ name: 'Our win chance', color: QK.cssVar('--signal'), data: xs.map(function (x) { return [x, Math.round(1000 * normCdf(x / sd)) / 10]; }) }],
    xName: 'Expected margin (points)', yName: 'Win chance (%)', yMin: 0, yMax: 100, xMin: -24, xMax: 24, yFmt: function (v) { return v + '%'; }, xFmt: function (v) { return CC.signed(v, 0); }, ref: { y: 50, label: 'Coin flip' }, endLabels: false, label: 'Win chance by expected margin' });
  var sim = (season && season.sim && season.sim.teams) || {};
  var tt = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title) && sim[t].p_title > 0; }).sort(function (a, b) { return sim[b].p_title - sim[a].p_title; }).slice(0, 6);
  QK.$('#mx-s', body).innerHTML = tt.length ? QK.chances(tt.map(function (t) { return { label: CC.tshort(L, t), p: sim[t].p_title, href: CC.teamHref(L, t, S), color: CC.traw(L, t), mark: U.mark(L, t) }; }), { key: false }) : QK.empty('The simulation runs with the season', '');
  var bp = (val && val.by_position) || {}, ord = fb ? ['QB', 'RB', 'WR', 'TE', 'DL', 'LB', 'DB'] : ['G', 'F', 'C'];
  var best = ord.filter(function (k) { return (bp[k] || []).length; }).map(function (k) { return { k: k, r: bp[k][0] }; });
  if (best.length) QKC.bar(QK.$('#mx-v', body), { cats: best.map(function (b) { return b.k + ' · ' + QK.surname(b.r.name || ''); }), horizontal: true, labels: true, fmt: function (v) { return CC.f(v, 1); },
    series: [{ name: 'Value', data: best.map(function (b) { return b.r.value; }) }], colors: best.map(function (b) { return CC.tcol(L, b.r.team); }), labelWidth: 120, valName: 'Value (points above replacement)', catName: 'Position' });
  else QK.$('#mx-v', body).innerHTML = QK.empty('Player values appear with the first games', '');
}

})(window.CC);
