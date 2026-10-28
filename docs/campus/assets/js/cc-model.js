/* The Quant Campus — Lab (#/<L>/lab) and Model (#/<L>/model?tab=method|calibration|glossary|terms).
 * Lab: build-your-own scatter and table over lab_teams.json / lab_players.json (pick x, y, filter, colour by
 * conference or position; the table beside the chart holds the same rows).
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

/* ── lab ─────────────────────────────────────────────────────────────── */
/* ── compare (#/<L>/lab?kind=compare&p=<pid>,<pid>[,<pid>]) ────────────────────────────────────────────────
 * Two or three players side by side on the spec's headline set for their peer group (METRICS_SPEC.md: football by
 * position, basketball by role), percentiles against that group, the better value bold, the difference for two; then
 * where each sits in the group's distribution. Players from different groups, or a group whose rates the payload does
 * not carry yet, fall back to the catalogue's own metrics against all qualified players, and the page says so. */
var CMP_COL = ['wpA', 'wpB', 'c5'];
/* The type a player's best metric suggests (verdicts), by the spec's metric id. */
var CMP_TYPE = { value_pg: 'The most valuable', epa_play: 'The efficient one', sr_db: 'The steady passer', cmp_pct: 'The accurate passer', ypa: 'The big-play passer', td_rate: 'The touchdown maker', int_rate: 'The ball-protector',
  sr_rush: 'The steady runner', ypc: 'The big-play runner', rush_share: 'The workhorse', tgt_share: 'The go-to target', yptpa: 'The yardage machine', ypr: 'The deep threat', sr_tgt: 'The reliable target', havoc_pg: 'The disruptor', sacks_pg: 'The pass rusher',
  hurries_pg: 'The pass rusher', tkl_pg: 'The tackler', pd_pg: 'The ball hawk', tfl_pg: 'The backfield wrecker', def_int_pg: 'The ball hawk', fg_pct: 'The accurate kicker', r: 'The difference-maker', pts100: 'The scorer', ts_add: 'The efficient scorer',
  ast_pct: 'The playmaker', tov_pct: 'The careful one', fta100: 'The rim attacker', stl_pct: 'The pickpocket', trb_pct: 'The rebounder', orb_pct: 'The glass cleaner', blk_pct: 'The rim protector' };
function labSeg(kind) {
  return '<div class="qk-seg" id="lab-kind" role="group" aria-label="View">' + [['teams', 'Teams chart'], ['players', 'Players chart'], ['compare', 'Compare players']].map(function (x) {
    return '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (kind === x[0]) + '">' + x[1] + '</button>'; }).join('') + '</div>';
}
function compare(el, p) {
  var L = p.L, S = p.S, q = p.query || {};
  var ids = String(q.p || '').split(',').filter(Boolean).slice(0, 3);
  var head = function (sub) { return U.head('Compare', sub || 'Two or three players side by side on the metrics that best describe and predict their play, ranked against their own position group.', U.kicker(L, S)) + '<div class="cc-toolbar">' + labSeg('compare') + '</div>'; };
  el.innerHTML = head() + QK.skeleton('lines', 6);
  var wireSeg = function () { QK.seg(QK.$('#lab-kind', el), function (v) { CC.go(CC.href(L, 'lab', null, S, 'kind=' + v)); }); };
  return Promise.all([CC.load(CC.path(L, S, 'players.json')), CC.season(L, S), CC.metrics()]).then(function (a) {
    if (!U.alive(el)) return;
    var cat = a[0];
    if (!CC.ok(cat) || !Object.keys(cat.players || {}).length) { el.innerHTML = head() + U.missing('The player catalogue', cat); wireSeg(); return; }
    var P = cat.players;
    Object.keys(P).forEach(function (k) { var nm = String((P[k] || {}).name || '').trim(); if (!nm || /^team$/i.test(nm) || Number(k) < 0) delete P[k]; });
    var meta = {}; (cat.metrics || []).forEach(function (m) { meta[m.key] = m; });
    ids = ids.filter(function (id) { return P[id]; });
    if (!ids.length) {
      var top = Object.keys(P).filter(function (k) { return P[k].qualified !== false && isNum((P[k].values || {}).value); }).sort(function (x, y) { return P[y].values.value - P[x].values.value; });
      var first = top[0], second = first ? top.filter(function (k) { return k !== first && P[k].pos === P[first].pos; })[0] : null;
      ids = [first, second].filter(Boolean);
    }
    var opts = Object.keys(P).filter(function (k) { return P[k].qualified !== false; }).map(function (k) { return [k, P[k].name + ' (' + CC.tabbr(L, P[k].team) + ', ' + (P[k].pos || '') + ')']; }).sort(function (x, y) { return x[1].localeCompare(y[1]); });
    var lab = function (id) { var o = opts.filter(function (x) { return x[0] === id; })[0]; return o ? o[1] : ''; };
    var picker = '<div class="cc-cmp-pick">' + [0, 1, 2].map(function (i) { return '<label class="cc-cmp-slot" style="--ec:var(--' + ['wp-a', 'wp-b', 'c-5'][i] + ')"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span><input class="qk-input" list="cmp-names" data-i="' + i + '" value="' + esc(ids[i] ? lab(ids[i]) : '') + '" placeholder="Type a name" autocomplete="off"></label>'; }).join('') +
      '<datalist id="cmp-names">' + opts.map(function (o) { return '<option value="' + esc(o[1]) + '"></option>'; }).join('') + '</datalist></div>';
    var E = ids.map(function (id) { return { id: id, p: P[id] }; });
    var html = head() + U.card('Players', 'Qualified players this season; pick two or three', picker);
    if (E.length < 2) { el.innerHTML = html + QK.empty('Pick at least two players', 'Type a name in each box.'); wire(); wireSeg(); return; }
    var G = CC.group(L, 'player', E[0].p);
    var same = G && E.every(function (e) { return CC.group(L, 'player', e.p) === G; });
    var hs = same ? G.m.filter(function (m) { return m.set === 'h' && E.some(function (e) { return isNum((e.p.values || {})[m.id]) && isNum((e.p[G.pct] || {})[m.id]); }); }) : [];
    var useSpec = same && hs.length >= 2;
    var samePos = E.every(function (e) { return e.p.pos === E[0].p.pos; });
    var peer = useSpec ? G.d : samePos ? ((cat.positions || {})[E[0].p.pos] || {}).label || E[0].p.pos : 'all qualified players';
    var pcKey = useSpec ? G.pct : samePos ? 'pct_pos' : 'pct';
    var rowsOf = function (list) {
      return list.map(function (m) {
        var mt = meta[m.id || m.key] || { fmt: '2' }, key = m.id || m.key;
        return { key: key, style: !!m.style, label: m.d || m.label, tip: (m.x || m.desc || '') + (m.style ? ' Describes playing style, not how well.' : ''), better: (m.low || m.lower) ? 'low' : 'high',
          values: E.map(function (e) { return (e.p.values || {})[key]; }), pctls: m.style ? E.map(function () { return null; }) : E.map(function (e) { return (e.p[pcKey] || {})[key]; }), fmt: function (v) { return CC.fmtMetric(mt, v); } };
      });
    };
    var groups = useSpec ? [{ label: 'Headline: ' + G.d.toLowerCase(), rows: rowsOf(hs) }, { label: 'More', rows: rowsOf(G.m.filter(function (m) { return m.set === 's' && E.some(function (e) { return isNum((e.p.values || {})[m.id]); }); }).slice(0, 6)) }]
      : [{ label: 'Season numbers', rows: rowsOf((cat.metrics || []).slice(0, 10)) }];
    /* v4: two players draw the tale of the tape in their team colours (QK.tape via QK.compareView); three keep the table */
    var ents = E.map(function (e) { return { name: e.p.name, short: QK.surname(e.p.name || '') || e.p.name, href: CC.playerHref(L, e.id, S), colour: CC.traw(L, e.p.team), alt: CC.talt(L, e.p.team) || undefined, sub: [CC.tabbr(L, e.p.team), e.p.pos, isNum(e.p.gp) ? e.p.gp + ' GP' : ''].filter(Boolean).join(' · ') }; });
    /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
    var short = E.map(function (e) { return QK.surname(e.p.name || ''); });
    var verd = E.map(function (e, i) {
      var bd = 0, br = null;
      groups[0].rows.forEach(function (r) {
        var mine = r.pctls[i]; if (!isNum(mine) || r.style) return;
        var dd = mine - Math.max.apply(null, r.pctls.filter(function (_, j) { return j !== i; }).map(function (v) { return isNum(v) ? v : 0; }));
        if (dd > bd) { bd = dd; br = r; }
      });
      return br ? { title: CMP_TYPE[br.key] || 'The standout', who: short[i], text: 'best of the ' + E.length + ' on ' + (/^[A-Z][a-z]/.test(br.label) ? br.label.charAt(0).toLowerCase() + br.label.slice(1) : br.label) + ' (' + br.fmt(br.values[i]) + ', ' + QK.ordinal(Math.round(br.pctls[i])) + ' percentile).' } : null;
    });
    var q = short.length === 2 ? short[0] + ' or ' + short[1] + '?' : short.slice(0, -1).join(', ') + ' or ' + short[short.length - 1] + '?';
    html += '<section class="qk-section" style="margin-top:var(--sp-8)">' + QK.sectionHead({ kicker: 'Side by side', title: esc(q), html: true, sub: (E.length === 2 ? 'Bar length = percentile against ' : 'Value and percentile against ') + esc(/^[A-Z][a-z]/.test(peer) ? peer.charAt(0).toLowerCase() + peer.slice(1) : peer) + ' (100 = best). ' + (E.length === 2 ? 'The better number in each row is solid.' : 'The best in each row is highlighted.') }) +
      U.card(E.length + ' players, one metric set', 'The headline set for the group from our metrics spec: stable and predictive rates first',
      QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) +
      (!useSpec ? '<p class="cc-note">' + (same || samePos ? 'The spec’s headline rates for this group are not in this season’s payload yet, so the catalogue’s own numbers are shown.' : 'Different positions: percentiles are against all qualified players, so position effects stay in. Compare players of one position for the spec’s headline set.') + '</p>' : '')) + '</section>';
    var dm = useSpec ? hs.filter(function (m) { return !m.style; }).slice(0, 4).map(function (m) { return [m.id, m.d, !!m.low]; }) : (cat.metrics || []).slice(0, 4).map(function (m) { return [m.key, m.label, !!m.lower]; });
    html += '<section class="qk-section">' + U.card('Where they sit', 'Every qualified ' + esc(peer.toLowerCase()) + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px">' +
      dm.map(function (o, i) { return '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + esc(o[0]) + '">' + esc(o[1]) + '</button>'; }).join('') + '</div>' + U.chart('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
    el.innerHTML = html;
    wire(); wireSeg();
    var peers = Object.keys(P).map(function (k) { return P[k]; }).filter(function (x) { return x.qualified !== false && (useSpec ? CC.group(L, 'player', x) === G : !samePos || x.pos === E[0].p.pos); });
    var dd = function (key) {
      var o = dm.filter(function (x) { return x[0] === key; })[0] || [key, key, false];
      var vs = peers.map(function (x) { return (x.values || {})[key]; }).filter(isNum).sort(function (x, y) { return x - y; });
      if (vs.length < 10) { QK.$('#cmp-dist', el).innerHTML = QK.empty('Too few qualified peers yet', 'The distribution appears with ten or more.'); return; }
      var mt = meta[key] || { fmt: '2' };
      QKC.distribution('#cmp-dist', { values: vs, binCount: 22, lowerBetter: o[2], colorBy: 'flat', fmt: function (v) { return CC.fmtMetric(mt, v); }, xName: o[1] + ' · ' + vs.length + ' qualified peers', yName: 'Players',
        marks: E.map(function (e, i) { return { x: (e.p.values || {})[key], label: QK.surname(e.p.name || ''), color: CMP_COL[i] }; }).filter(function (x) { return isNum(x.x); }), label: 'Distribution of ' + o[1] });
    };
    if (dm.length) { dd(dm[0][0]); QK.seg(QK.$('#cmp-dist-m', el), dd); }
    function wire() {
      QK.$$('.cc-cmp-pick input', el).forEach(function (inp) {
        inp.addEventListener('change', function () {
          var pick = [0, 1, 2].map(function (i) {
            var v = ((QK.$('.cc-cmp-pick input[data-i="' + i + '"]', el) || {}).value || '').trim();
            var hit = opts.filter(function (o) { return o[1] === v; })[0] || (v ? opts.filter(function (o) { return o[1].toLowerCase().indexOf(v.toLowerCase()) === 0; })[0] : null);
            return hit ? hit[0] : null;
          }).filter(Boolean);
          if (pick.length) CC.go(CC.href(L, 'lab', null, S, 'kind=compare&p=' + pick.join(',')));
        });
      });
    }
  });
}

CC.route('lab', function (el, p) {
  var L = p.L, S = p.S, q = p.query || {};
  if (q.kind === 'compare') return compare(el, p);
  var kind = q.kind === 'players' ? 'players' : 'teams';
  el.innerHTML = U.head('Lab', 'Pick any two numbers and see every ' + (kind === 'players' ? 'player' : 'team') + ' at once. Click a point to open its page.', U.kicker(L, S)) + QK.skeleton('chart', 1);
  return Promise.all([CC.load(CC.path(L, S, kind === 'players' ? 'lab_players.json' : 'lab_teams.json')), CC.season(L, S), CC.metrics(), CC.specP]).then(function (a) {
    if (!U.alive(el)) return;
    var d = a[0];
    var segHtml = labSeg(kind);
    if (!CC.ok(d) || !(d.rows || []).length) {
      el.innerHTML = U.head('Lab', '', U.kicker(L, S)) + '<div class="cc-toolbar">' + segHtml + '</div>' + (CC.ok(d) ? QK.empty('No rows yet', 'Nothing has been played this season. Try last season.') : U.missing('The lab data', d));
      QK.seg(QK.$('#lab-kind', el), function (v) { CC.go(CC.href(L, 'lab', null, S, 'kind=' + v)); });
      return;
    }
    var F = d.fields || [], ix = {};
    F.forEach(function (f, i) { ix[f] = i; });
    var ent = kind === 'players' ? 'player' : 'team';
    /* the level's spec names and explanations (cc-metrics.js), our models first, then the headline box score */
    var mets = (d.metrics || []).filter(function (m) { return ix[m.key] !== undefined; }).map(function (m) {
      var sm = CC.specMeta(L, ent, m.key), o = {}, k;
      for (k in m) if (Object.prototype.hasOwnProperty.call(m, k)) o[k] = m[k];
      if (sm) { o.label = sm.d; if (sm.x) o.desc = sm.x; if (sm.low) o.lower = true; }
      return o;
    });
    var num0 = mets.length ? mets : F.filter(function (f) { return d.rows.some(function (r) { return isNum(r[ix[f]]); }); }).map(function (f) { return { key: f, label: f, fmt: '2' }; });
    var ordered = CC.orderMetrics(L, ent, num0), num = [];
    ordered.forEach(function (g) { num = num.concat(g.items); });
    var mk = {}; num.forEach(function (m) { mk[m.key] = m; });
    var dx0 = kind === 'teams' && mk.off && mk.def ? 'off' : (num[0] || {}).key, dy0 = kind === 'teams' && mk.off && mk.def ? 'def' : (num[1] || num[0] || {}).key;
    var xk = mk[q.x] ? q.x : dx0, yk = mk[q.y] ? q.y : dy0;
    var grpKey = kind === 'players' ? 'pos' : 'conference';
    var groups = {};
    d.rows.forEach(function (r) { var g = r[ix[grpKey]]; if (g !== undefined && g !== null) groups[g] = (groups[g] || 0) + 1; });
    var gk = Object.keys(groups).sort(function (x, y) { return groups[y] - groups[x]; });
    var opt = function (sel) { return ordered.map(function (g) { return '<optgroup label="' + esc(g.label) + '">' + g.items.map(function (m) { return '<option value="' + esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + esc(m.label) + '</option>'; }).join('') + '</optgroup>'; }).join(''); };
    var minGp = kind === 'players' && ix.gp !== undefined;
    el.innerHTML = U.head('Lab', 'Pick any two numbers and see every ' + (kind === 'players' ? 'player' : 'team') + ' at once. Click a point to open its page; the table below holds the same rows.', U.kicker(L, S)) +
      '<div class="cc-toolbar">' + segHtml + '<label class="cc-lab-sel">X <select class="qk-select" id="lab-x">' + opt(xk) + '</select></label><label class="cc-lab-sel">Y <select class="qk-select" id="lab-y">' + opt(yk) + '</select></label>' +
      '<select class="qk-select" id="lab-g" aria-label="' + (kind === 'players' ? 'Position' : 'Conference') + '"><option value="">' + (kind === 'players' ? 'All positions' : 'All conferences') + '</option>' + gk.map(function (g) { return '<option value="' + esc(g) + '">' + esc(kind === 'players' ? g : CC.cname(L, g)) + '</option>'; }).join('') + '</select>' +
      (minGp ? '<label class="cc-lab-sel">Min games <input class="qk-input" type="number" id="lab-gp" min="0" value="' + (kind === 'players' ? 3 : 0) + '" style="width:72px"></label>' : '') + '</div>' +
      U.card('Chart', '<span id="lab-t"></span>', U.chart('lab-sc', 460, 'Scatter of the chosen metrics') + '<div id="lab-ours" class="cc-lab-ours"></div>') + '<div id="lab-tbl"></div>';
    function paint() {
      var x = QK.$('#lab-x', el).value, y = QK.$('#lab-y', el).value, g = QK.$('#lab-g', el).value, gp = minGp ? Number(QK.$('#lab-gp', el).value || 0) : 0;
      var rs = d.rows.filter(function (r) { return isNum(r[ix[x]]) && isNum(r[ix[y]]) && (!g || String(r[ix[grpKey]]) === g) && (!minGp || (r[ix.gp] || 0) >= gp); });
      rs.sort(function (r1, r2) { return mk[y].lower ? r1[ix[y]] - r2[ix[y]] : r2[ix[y]] - r1[ix[y]]; });
      var tn = QK.$('#lab-t', el); if (tn) tn.innerHTML = esc(mk[y].label) + CC.oursTag(y, false, mk[y].desc) + ' against ' + esc(mk[x].label) + CC.oursTag(x, false, mk[x].desc) + (mk[y].lower ? ' (lower is better on the vertical axis, so it is flipped: better is up)' : '') + '.';
      var models = [];
      [CC.ours(x), CC.ours(y)].forEach(function (o) { if (o && models.every(function (z) { return z.key !== o.key; })) models.push(o); });
      var on = QK.$('#lab-ours', el);
      if (on) on.innerHTML = models.length ? QK.oursExplain(models.map(function (o) { return '<b>' + esc(o.name) + '.</b> ' + esc(o.about); }).join(' '), { title: models.length > 1 ? 'Our models.' : 'Our model.' })
        : QK.explain('Neither axis comes from our models. ' + (kind === 'teams' ? 'Our rating and its offence and defence split' : CC.fb(L) ? 'Value and EPA' : 'Value and the box rating') + ' are ours: they lead the metric lists, tagged ' + QK.ours({ short: true }) + '.');
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
      var hm = {}; num.forEach(function (m) { hm[m.label] = m.key; });
      CC.oursHeads(QK.$('#lab-tbl', el), hm);
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

/* Builder notes in the v2 voice (the payload text is shared; the wording is changed for display only). */
function noteV2(n) {
  return String(n || '').replace(/where both prices are stored/g, 'where both sides are stored').replace(/put the price \(-110\)/g, 'put the -110 vig')
    .replace(/\bprices?\b/gi, 'numbers').replace(/\bpriced\b/gi, 'posted').replace(/\bedge\b/gi, 'advantage');
}
/* Glossary in the v2 voice (the payload is shared with the builder; these entries are reworded here, betting terms
 * the site no longer shows are dropped). */
var GLOSS_DROP = { edge: 1 };
var GLOSS_V2 = {
  p_home: { label: 'Our win chance', desc: 'Our pre-game chance the home side wins, from the two ratings, home field and rest.' },
  spread_fair: { label: 'Our margin', desc: 'Our expected winning margin in points ("OSU by 7.5").' },
  market: { label: 'Market (reference)', desc: 'The market’s chance (Kalshi or Polymarket, de-vigged; else the sportsbook closing line ESPN shows), shown beside ours on game pages and the Model page as a reference.' },
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

function calibration(node, L, d) {
  if (!CC.ok(d)) { node.innerHTML = U.missing('The backtest', d); return; }
  var s = d.summary || {}, m = s.model || {}, c = s.close || {}, vc = s.vs_close || {}, el0 = s.elo || {};
  var html = U.stats([
    { label: 'Brier score, ours', value: CC.f(m.brier, 3), signal: true, sub: 'market (closing moneyline) ' + CC.f(c.brier, 3) + ' · Elo ' + CC.f(el0.brier, 3), tip: 'Mean squared error of our win chance; lower is better; 0.250 is a coin flip' },
    { label: 'Margin error, ours', value: CC.f(vc.mae_model, 2), unit: 'pts', sub: 'market (closing line) ' + CC.f(vc.mae_close, 2) + ' on the same games', tip: 'Mean absolute error of the predicted margin, points' },
    { label: 'Games tested', value: isNum(d.n_games) ? QK.fmt.num(d.n_games) : '—', sub: (d.seasons || []).length ? CC.seasonLabel(L, d.seasons[0]) + ' to ' + CC.seasonLabel(L, d.seasons[d.seasons.length - 1]) + ', walk-forward' : '' },
    { label: 'Our side v the closing spread', value: CC.pct(vc.ats_hit, 1), sub: (isNum(vc.ats_n) ? QK.fmt.num(vc.ats_n) + ' games' : '') + (isNum(vc.ats_se) ? ' · ± ' + CC.pct(vc.ats_se, 1) : ''), tip: 'Share of games in which our margin landed on the right side of the closing line; 50% means no better than the market' },
    isNum(vc.total_mae_model) ? { label: 'Total error, ours', value: CC.f(vc.total_mae_model, 2), unit: 'pts', sub: 'market (closing total) ' + CC.f(vc.total_mae_close, 2) } : null]);
  html += '<p class="cc-note">Walk-forward: every game is predicted with ratings fitted only on games before its date, and nothing is tuned on the season being tested. The closing line is the hardest benchmark there is; matching it is good, beating it is rare.</p>';
  html += informedCard(L, d.informed);
  html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Calibration', 'When we say 70%, does the team win about 70% of the time? Points on the diagonal are well calibrated; dot size is the number of games.', U.chart('cal-rel', 320, 'Reliability diagram')) + '</div>' +
    '<div class="qk-span-6">' + U.card('Margin error by season', 'Mean absolute error of the predicted margin: ours (blue) and the closing line (grey, the market reference).', U.chart('cal-ps', 320, 'Margin error by season')) + '</div></div>';
  var summ = [['Ours', m], ['Market (closing line)', c], ['Elo baseline', el0]].concat(s.espn_predictor ? [['ESPN predictor', s.espn_predictor]] : []);
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
      else if (typeof v === 'string') snotes.push(noteV2(v));
      else if (v && typeof v === 'object' && !Array.isArray(v)) Object.keys(v).forEach(function (k2) { if (isNum(v[k2])) srows.push([k + ' · ' + k2, v[k2]]); else if (typeof v[k2] === 'string') snotes.push(noteV2(v[k2])); });
    });
    if (srows.length) html += U.card('Season simulation backtest', snotes.map(esc).join(' '), U.table(['Measure', { label: 'Value', align: 'right' }], srows.map(function (r) {
      return [esc(r[0].replace(/_/g, ' ')), { v: r[1], html: Math.round(r[1]) === r[1] ? String(r[1]) : CC.f(r[1], 3) }]; }), { sticky: false }));
  }
  if ((d.notes || []).length) html += '<ul class="cc-notes">' + d.notes.map(function (n) { return '<li>' + esc(noteV2(n)) + '</li>'; }).join('') + '</ul>';
  node.innerHTML = html;
  U.wire(node);
  var cal = (d.calibration || []).filter(function (r) { return isNum(r.p_mean) && isNum(r.y_mean); });
  if (cal.length) QKC.scatter('#cal-rel', { points: cal.map(function (r) { return { x: r.p_mean, y: r.y_mean, name: CC.pct(r.lo, 0) + '–' + CC.pct(r.hi, 0) + ' (' + r.n + ' games)', size: Math.max(7, Math.min(22, Math.sqrt(r.n) / 2)) }; }),
    xName: 'Predicted', yName: 'Observed', xMin: 0, xMax: 1, yMin: 0, yMax: 1, diagonal: { label: 'perfect' }, xFmt: function (v) { return CC.pct(v, 0); }, yFmt: function (v) { return CC.pct(v, 0); } });
  var ps = (d.per_season || []).filter(function (r) { return r.model && isNum(r.model.mae); });
  if (ps.length) QKC.line('#cal-ps', { x: ps.map(function (r) { return CC.seasonLabel(L, r.season); }), series: [{ name: 'Ours', data: ps.map(function (r) { return r.model.mae; }), color: QK.cssVar('--signal'), symbols: true }, { name: 'Closing line', data: ps.map(function (r) { return r.close && isNum(r.close.mae) ? r.close.mae : null; }), color: QK.cssVar('--c-market'), symbols: true }], yScale: true, yFmt: function (v) { return CC.f(v, 1); }, legend: true, xName: 'Season', yName: 'MAE (pts)' });
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
  var list = [['method', 'Methodology'], ['calibration', 'How we’re doing'], ['glossary', 'Glossary'], ['terms', 'Terms']];
  var tab = U.tab(p, ['method', 'calibration', 'glossary', 'terms'], 'method');
  el.innerHTML = U.head('Model', 'How our numbers are made, how well they have done (with the market’s closing numbers as the benchmark), and what every term means.', U.kicker(L, S)) +
    U.tabs(L, 'model', list, null, tab) + (tab === 'calibration' ? '<div id="mb-sure"></div>' : tab === 'method' ? '<div style="margin-top:var(--sp-6)">' + QK.explain('<b>How we’re doing.</b> Our recent record and how often our chances came true are on <a class="qk-link" href="' + esc(CC.href(L, 'model', null, null, 'tab=calibration')) + '">the How we’re doing tab</a>.') + '</div>' : '') + '<div id="mb">' + QK.skeleton('lines', 8) + '</div>';
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
  if (tab === 'glossary') return CC.load('glossary.json').then(function (g) {
    if (!U.alive(el)) return;
    if (!CC.ok(g)) { body.innerHTML = U.missing('The glossary', g); return; }
    body.innerHTML = '<div class="cc-gloss">' + (g.groups || []).map(function (gr) {
      return U.card(gr.name, '', '<dl class="cc-dl">' + (gr.entries || []).filter(function (e) { return !GLOSS_DROP[e.key]; }).map(function (e) { var o = GLOSS_V2[e.key] || {}; return '<dt id="g-' + esc(e.key) + '">' + esc(o.label || e.label) + '</dt><dd>' + esc(o.desc || e.desc) + '</dd>'; }).join('') + '</dl>');
    }).join('') + '</div>';
  });
  var file = fb ? 'MODELS_CFB.md' : 'MODELS_HOOPS.md';
  return new Promise(function (resolve) {
    fetch(file, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }).then(function (txt) { resolve(txt); }, function () { resolve(null); });
  }).then(function (txt) {
    if (!U.alive(el)) return;
    body.innerHTML = '<div class="qk-card cc-prose">' + (txt ? CC.md(txt) : CC.md(fb ? FALLBACK.cfb : FALLBACK.bb) + '<p class="qk-muted">The full methodology document is published with the next build.</p>') +
      '<h3>Data</h3><p>Schedules, scores, box scores, plays, rankings, rosters and betting lines come from ESPN’s public data; prediction-market probabilities from Kalshi and Polymarket where listed. Sources whose terms forbid reuse are left out: no Sports-Reference, KenPom, Barttorvik, 247Sports, On3, Rivals, Massey or NCAA.com data. ' +
      'Recruiting rankings and the official transfer portal are not used; transfers here are inferred from rosters and box scores.</p></div><div id="mb-moves"></div>';
    movesMethod(L, QK.$('#mb-moves', el));
  });
});

})(window.CC);
