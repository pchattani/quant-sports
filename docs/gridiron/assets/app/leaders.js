/* The Quant Gridiron — Leaders (#/leaders?g=&m=), on Design System 2.0: the top five on the headline metrics of every
 * position group at a glance, then any catalogue metric as a ranked bar chart and table, qualified players only (or
 * above a sample floor), best or worst, one team or all. Reads <S>/players.json (leaders.json as a fallback). */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const ST = { group: 'QB', metric: '', qual: true, team: '', dir: 'best', n: 25, season: null };

GI.route('leaders', function (el, params) {
  const S = Number(params.season);
  const qy = params.query || {};
  if (qy.g && GI.GROUPS.indexOf(String(qy.g).toUpperCase()) >= 0) ST.group = String(qy.g).toUpperCase();
  if (qy.m) ST.metric = String(qy.m);
  return GI.load(GI.ypath('players.json', S)).then(raw => {
    if (!el.isConnected) return;
    const head = GI.pageHead('Players · ' + S, 'Leaders', 'Qualified players only unless you say otherwise; percentiles against each player\'s peer group (QB, RB, WR/TE, DL and outside rushers, LB, DB, K, P) after shrinking small samples towards the group mean.') + GI.sectionNav('players', 'leaders');
    const X = GI.cat.prepare(raw);
    if (!X) {
      return GI.load(GI.ypath('leaders.json', S)).then(d => {
        if (!el.isConnected) return;
        const B = GI.ok(d) ? (d.boards || d.leaders || d) : null;
        const keys = B ? Object.keys(B).filter(k => Array.isArray(B[k]) && B[k].length) : [];
        el.innerHTML = head + (keys.length ? '<div class="qk-auto" style="--min:260px">' + keys.map(k => GI.card(esc(GI.titleCase(k)), '', '<ol class="gi-ldl">' + B[k].slice(0, 10).map(r => '<li>' + GI.playerLink(String(r[0])) + '<b class="gi-num">' + GI.fmtVal(r[1]) + '</b></li>').join('') + '</ol>')).join('') + '</div>' : GI.notBuilt('The ' + S + ' leaderboards', raw));
      });
    }
    const P = X.P, by = X.by, cat = X.cat;
    if (ST.season !== S) { ST.season = S; ST.team = ''; }
    // at a glance
    const glance = [];
    GI.GROUPS.forEach(g => {
      const ids = (by[g] || []).filter(id => P[id].qualified !== false);
      if (!ids.length) return;
      GI.headline(GI.metricsFor(cat, g), GI.PREFS[g] || [], g === 'QB' || g === 'WR' ? 2 : 1).forEach(m => {
        const top = ids.filter(id => isNum((P[id].values || {})[m.key])).sort((a, b) => { const d = P[b].values[m.key] - P[a].values[m.key]; return m.lower ? -d : d; }).slice(0, 5);
        if (top.length) glance.push(GI.card('<a class="gi-link" href="' + GI.ghref('leaders', S, { g: g, m: m.key }) + '">' + esc(g + ' · ' + m.label) + '</a>', '', '<ol class="gi-ldl gi-lead">' + top.map(id => '<li>' + GI.mark(P[id].team) + GI.playerLink(id, { name: P[id].name, season: S }) + '<b class="gi-num">' + GI.fmtVal(P[id].values[m.key], m.fmt) + '</b></li>').join('') + '</ol>'));
      });
    });
    el.innerHTML = head + '<div class="qk-auto" style="--min:250px">' + glance.join('') + '</div>' +
      GI.card('Leaderboard', '<span id="ld-sub"></span>', '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.seg('ld-group', GI.GROUPS.map(g => [g, g, !(by[g] || []).length]), ST.group, 'Group') +
        GI.field('Metric', '<select id="ld-metric" class="qk-select"></select>') + GI.field('Team', '<select id="ld-team" class="qk-select"></select>') +
        GI.field('Show', GI.select('ld-dir', [['best', 'Best first'], ['worst', 'Worst first']], ST.dir, 'Order')) + GI.field('How many', GI.select('ld-n', [['10', '10'], ['25', '25'], ['50', '50'], ['999', 'All']], String(ST.n), 'How many')) +
        '<label class="gi-check"><input id="ld-qual" type="checkbox"' + (ST.qual ? ' checked' : '') + '> qualified only</label></div>' +
        GI.chartBox('ld-chart', 420, 'Leaderboard') + '<div id="ld-table" style="margin-top:12px"></div><p class="gi-cap" id="ld-note"></p>');
    const $ = id => document.getElementById(id);
    let ms = [];
    const setup = () => {
      ms = GI.metricsFor(cat, ST.group);
      if (!ms.some(m => m.key === ST.metric)) ST.metric = (GI.headline(ms, GI.PREFS[ST.group] || [], 1)[0] || ms[0] || {}).key || '';
      $('ld-metric').innerHTML = GI.metricGroups(ms).map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '"' + (m.key === ST.metric ? ' selected' : '') + '>' + esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      const teams = Array.from(new Set((by[ST.group] || []).map(id => P[id].team).filter(Boolean))).sort();
      $('ld-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + esc(t) + '</option>').join('');
    };
    const draw = () => {
      const m = ms.find(x => x.key === ST.metric);
      if (!m) { GI.set('ld-table', GI.muted('No metrics for this group yet.')); GI.ch.none('ld-chart', 'No metrics for this group yet.'); return; }
      const sub = {}; (by[ST.group] || []).forEach(id => { sub[id] = P[id]; });
      const sk = GI.sampleKey(sub, ST.group);
      let ids = (by[ST.group] || []).filter(id => isNum((P[id].values || {})[m.key]) && (!ST.qual || P[id].qualified !== false) && (!ST.team || P[id].team === ST.team));
      ids.sort((a, b) => { const d = P[b].values[m.key] - P[a].values[m.key]; return (m.lower ? -d : d) * (ST.dir === 'worst' ? -1 : 1); });
      const total = ids.length;
      ids = ids.slice(0, ST.n);
      const top = ids.slice(0, 15);
      const ch = $('ld-chart');
      if (ch) ch.style.setProperty('--h', Math.max(220, top.length * 26 + 30) + 'px');
      if (top.length) GI.ch.bar('ld-chart', { cats: top.map(id => P[id].name + ' · ' + GI.teamAbbr(P[id].team)), series: [{ name: m.label, data: top.map(id => P[id].values[m.key]) }], horizontal: true, labels: true, colors: top.map(id => QK.pctHex(GI.peerPct(P[id], ST.group)[m.key])), hrefs: top.map(id => GI.playerHref(id, S)), fmt: v => GI.fmtVal(v, m.fmt), labelWidth: 170, valName: m.label, catName: 'Player' });
      else GI.ch.none('ld-chart', 'Nobody with this metric matches.');
      const lrows = ids.map(id => { const p = P[id], pc = GI.peerPct(p, ST.group); return { id: id, name: p.name, team: p.team, sub: GI.posLabel(p.pos || '') + ' · ' + GI.teamAbbr(p.team) + (p.qualified === false ? ' · small sample' : ''), games: p.games, n: GI.sampleOf(p, sk[0]), v: p.values[m.key], p: isNum(pc[m.key]) ? pc[m.key] : null }; });
      if (lrows.length) QK.leaderboard($('ld-table'), { dense: true, rank: true, maxHeight: 640, rowHref: r => GI.playerHref(r.id, S), rows: lrows,
        columns: [{ key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => ({ name: GI.teamName(r.team), abbr: GI.teamAbbr(r.team), colour: GI.teamInfo(r.team).colour }), href: r => GI.playerHref(r.id, S), sort: false },
          { key: 'games', label: 'G', num: true, sort: false }, { key: 'n', label: sk[1], num: true, sort: false }, { key: 'v', label: m.label + (m.lower ? ' ↓' : ''), type: 'pctl', pctl: 'p', fmt: v => '<b>' + GI.fmtVal(v, m.fmt) + '</b>', tip: GI.copyText(m.desc || ''), sort: false },
          { key: 'p', label: 'Percentile', type: 'bar', max: 100, fmt: v => (isNum(v) ? String(Math.round(v)) : '—'), tip: 'Against his peer group, qualified players (100 = best)', sort: false }] });
      else GI.set('ld-table', GI.muted('Nobody with this metric matches.'));
      GI.set('ld-sub', (ST.dir === 'worst' ? 'Bottom ' : 'Top ') + Math.min(ST.n, total) + ' of ' + total + ' ' + esc((GI.GROUP_NAME[ST.group] || '').toLowerCase()) + ' · ' + S);
      const qn = (cat.qualification || {})[ST.group];
      GI.set('ld-note', '<b>' + esc(m.label) + '</b>: ' + esc(m.desc || '') + (isNum(m.stabilises_at) ? ' Stabilises at about ' + GI.int(m.stabilises_at) + ' ' + esc(sk[1].toLowerCase()) + '.' : '') + (qn ? ' Qualified: ' + esc(qn) + '.' : '') +
        ' ' + GI.glossLink(m.key, 'Glossary →') + ' · <a href="' + GI.ghref('lab', S, { g: ST.group, x: m.key }) + '">In the lab →</a>');
    };
    setup();
    GI.wireSeg(el, 'ld-group', v => { ST.group = v; ST.metric = ''; ST.team = ''; setup(); draw(); });
    $('ld-metric').addEventListener('change', e => { ST.metric = e.target.value; draw(); });
    $('ld-team').addEventListener('change', e => { ST.team = e.target.value; draw(); });
    $('ld-dir').addEventListener('change', e => { ST.dir = e.target.value; draw(); });
    $('ld-n').addEventListener('change', e => { ST.n = Number(e.target.value); draw(); });
    $('ld-qual').addEventListener('change', e => { ST.qual = e.target.checked; draw(); });
    draw();
  });
});

})(window.GI);
