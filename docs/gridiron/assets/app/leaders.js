/* The Quant Gridiron — Leaders (#/leaders?g=&m=), on Design System 2.0 and the metrics spec (spec.js): the top five on
 * the headline metrics of every comparison group (QB, RB, WR, TE, the five defensive roles, K, P) at a glance, then any
 * metric (the group's headline set first, then the rest of the catalogue) as a ranked bar chart and a leaderboard with
 * heat cells against the group, qualified players only (or everyone), best or worst, one team or all.
 * Reads <S>/players.json and <S>/value.json (leaders.json as a fallback). */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const ST = { group: 'qb', metric: '', qual: true, team: '', dir: 'best', n: 25, season: null };

GI.route('leaders', function (el, params) {
  const S = Number(params.season);
  const qy = params.query || {};
  if (GI.cat.groupFromQuery(qy.g)) ST.group = GI.cat.groupFromQuery(qy.g);
  if (qy.m) ST.metric = String(qy.m);
  return GI.loadAll([GI.ypath('players.json', S), GI.ypath('value.json', S)]).then(res => {
    if (!el.isConnected) return;
    const raw = res[0];
    const head = GI.pageHead('Players · ' + S, 'Leaders', 'Qualified players only unless you say otherwise; each player is ranked within their comparison group (QB, RB, WR, TE, outside pass rushers, interior linemen, LB, CB, S, K, P).') + GI.sectionNav('players', 'leaders');
    const X = GI.cat.prepare(raw);
    if (!X) {
      return GI.load(GI.ypath('leaders.json', S)).then(d => {
        if (!el.isConnected) return;
        const B = GI.ok(d) ? (d.boards || d.leaders || d) : null;
        const keys = B ? Object.keys(B).filter(k => Array.isArray(B[k]) && B[k].length) : [];
        el.innerHTML = head + (keys.length ? '<div class="qk-auto" style="--min:260px">' + keys.map(k => GI.card(esc(GI.titleCase(k)), '', '<ol class="gi-ldl">' + B[k].slice(0, 10).map(r => '<li>' + GI.playerLink(String(r[0])) + '<b class="gi-num">' + GI.fmtVal(r[1]) + '</b></li>').join('') + '</ol>')).join('') + '</div>' : GI.notBuilt('The ' + S + ' leaderboards', raw));
      });
    }
    const P = X.P, cat = X.cat;
    const cx = GI.SP.ctx(cat, GI.ok(res[1]) ? res[1] : null);
    if (ST.season !== S) { ST.season = S; ST.team = ''; }
    const G = GI.SP.PLAYER;
    // at a glance: the first headline metrics of every group
    const glance = [];
    G.forEach(g => {
      const ids = GI.SP.members(cx, g.id).filter(id => P[id].qualified !== false);
      if (!ids.length) return;
      GI.SP.headline(g).slice(0, g.id === 'qb' || g.id === 'wr' ? 2 : 1).forEach(m => {
        const top = ids.map(id => [id, GI.SP.value(P[id], id, m, cx)]).filter(x => isNum(x[1])).sort((a, b) => (m[3] ? a[1] - b[1] : b[1] - a[1])).slice(0, 5);
        if (top.length) glance.push(GI.card('<a class="gi-link" href="' + GI.ghref('leaders', S, { g: g.code, m: m[0] }) + '">' + esc(g.code + ' · ' + m[1]) + '</a>', '', '<ol class="gi-ldl gi-lead">' + top.map(x => '<li>' + GI.mark(P[x[0]].team) + GI.playerLink(x[0], { name: P[x[0]].name, season: S }) + '<b class="gi-num">' + GI.SP.fmt(m, x[1], cx) + '</b></li>').join('') + '</ol>'));
      });
    });
    el.innerHTML = head + '<div class="qk-auto" style="--min:250px">' + glance.join('') + '</div>' +
      GI.card('Leaderboard', '<span id="ld-sub"></span>', '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.seg('ld-group', G.map(g => [g.id, g.code, !GI.SP.members(cx, g.id).length]), ST.group, 'Group') +
        GI.field('Metric', '<select id="ld-metric" class="qk-select"></select>') + GI.field('Team', '<select id="ld-team" class="qk-select"></select>') +
        GI.field('Show', GI.select('ld-dir', [['best', 'Best first'], ['worst', 'Worst first']], ST.dir, 'Order')) + GI.field('How many', GI.select('ld-n', [['10', '10'], ['25', '25'], ['50', '50'], ['999', 'All']], String(ST.n), 'How many')) +
        '<label class="gi-check"><input id="ld-qual" type="checkbox"' + (ST.qual ? ' checked' : '') + '> qualified only</label></div>' +
        GI.chartBox('ld-chart', 420, 'Leaderboard') + '<div id="ld-table" style="margin-top:12px"></div><p class="gi-cap" id="ld-note"></p>');
    const $ = id => document.getElementById(id);
    let ms = [];
    /* the group's metrics as spec tuples: the headline set first, then the catalogue's other metrics for the group */
    const setup = () => {
      const g = GI.SP.BY[ST.group];
      const cm = GI.metricsFor(cat, GI.cat.CORE[g.id]);
      const ids0 = g.m.map(m => m[0]);
      ms = g.m.map(m => ({ t: m, set: true })).concat(cm.filter(m => ids0.indexOf(m.key) < 0).map(m => ({ t: [m.key, m.label, '', m.lower ? 1 : 0, 0, GI.copyText(m.desc || ''), null], set: false, group: m.group })));
      if (!ms.some(x => x.t[0] === ST.metric)) ST.metric = GI.SP.headline(g)[0][0];
      $('ld-metric').innerHTML = '<optgroup label="Headline set">' + ms.filter(x => x.set).map(x => '<option value="' + esc(x.t[0]) + '"' + (x.t[0] === ST.metric ? ' selected' : '') + '>' + esc(x.t[1]) + (x.t[3] ? ' ↓' : '') + '</option>').join('') + '</optgroup>' +
        '<optgroup label="More">' + ms.filter(x => !x.set).map(x => '<option value="' + esc(x.t[0]) + '"' + (x.t[0] === ST.metric ? ' selected' : '') + '>' + esc(x.t[1]) + (x.t[3] ? ' ↓' : '') + '</option>').join('') + '</optgroup>';
      const teams = Array.from(new Set(GI.SP.members(cx, g.id).map(id => P[id].team).filter(Boolean))).sort();
      $('ld-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + esc(t) + '</option>').join('');
    };
    const draw = () => {
      const g = GI.SP.BY[ST.group];
      const x = ms.find(z => z.t[0] === ST.metric);
      if (!x) { GI.set('ld-table', GI.muted('No metrics for this group yet.')); GI.ch.none('ld-chart', 'No metrics for this group yet.'); return; }
      const m = x.t;
      const core = GI.cat.CORE[g.id];
      const sub = {}; GI.SP.members(cx, g.id).forEach(id => { sub[id] = P[id]; });
      const sk = GI.sampleKey(sub, core);
      let list = GI.SP.members(cx, g.id).map(id => ({ id: id, v: GI.SP.value(P[id], id, m, cx) })).filter(r => isNum(r.v) && (!ST.qual || P[r.id].qualified !== false) && (!ST.team || P[r.id].team === ST.team));
      list.sort((a, b) => { const d = b.v - a.v; return (m[3] ? -d : d) * (ST.dir === 'worst' ? -1 : 1); });
      const total = list.length;
      list = list.slice(0, ST.n);
      const top = list.slice(0, 15);
      const ch = $('ld-chart');
      if (ch) ch.style.setProperty('--h', Math.max(220, top.length * 26 + 30) + 'px');
      if (top.length) GI.ch.bar('ld-chart', { cats: top.map(r => P[r.id].name + ' · ' + GI.teamAbbr(P[r.id].team)), series: [{ name: m[1], data: top.map(r => r.v) }], horizontal: true, labels: true, colors: top.map(r => (m[4] ? QK.cssVar('--ink-3') : QK.pctHex(GI.SP.pct(P[r.id], r.id, g, m, cx)))), hrefs: top.map(r => GI.playerHref(r.id, S)), fmt: v => GI.SP.fmt(m, v, cx), labelWidth: 170, valName: m[1], catName: 'Player' });
      else GI.ch.none('ld-chart', 'Nobody with this metric matches.');
      const lrows = list.map(r => { const p = P[r.id]; return { id: r.id, name: p.name, team: p.team, sub: GI.posLabel(p.pos || '') + ' · ' + GI.teamAbbr(p.team) + (p.qualified === false ? ' · below the minimum' : ''), games: p.games, n: GI.sampleOf(p, sk[0]), v: r.v, p: GI.SP.pct(p, r.id, g, m, cx) }; });
      if (lrows.length) QK.leaderboard($('ld-table'), { dense: true, rank: true, maxHeight: 640, rowHref: r => GI.playerHref(r.id, S), rows: lrows,
        columns: [{ key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => ({ name: GI.teamName(r.team), abbr: GI.teamAbbr(r.team), colour: GI.teamInfo(r.team).colour }), href: r => GI.playerHref(r.id, S), sort: false },
          { key: 'games', label: 'G', num: true, sort: false }, { key: 'n', label: sk[1], num: true, sort: false },
          m[4] ? { key: 'v', label: m[1], num: true, fmt: v => '<b>' + GI.SP.fmt(m, v, cx) + '</b>', tip: m[5] + ' (style: no better or worse)', sort: false }
            : { key: 'v', label: m[1] + (m[3] ? ' ↓' : ''), type: 'pctl', pctl: 'p', fmt: v => '<b>' + GI.SP.fmt(m, v, cx) + '</b>', tip: m[5], sort: false }]
          .concat(m[4] ? [] : [{ key: 'p', label: 'Percentile', type: 'bar', max: 100, fmt: v => (isNum(v) ? String(Math.round(v)) : '—'), tip: 'Against ' + g.peer + ', qualified (100 = best)', sort: false }]) });
      else GI.set('ld-table', GI.muted('Nobody with this metric matches.'));
      GI.set('ld-sub', (ST.dir === 'worst' ? 'Bottom ' : 'Top ') + Math.min(ST.n, total) + ' of ' + total + ' ' + esc(g.name.toLowerCase()) + ' · ' + S);
      GI.set('ld-note', '<b>' + esc(m[1]) + '</b>: ' + esc(m[5] || '') + (m[4] ? ' A style metric: it describes how a player plays, not how well.' : '') + ' Qualified: ' + esc(GI.SP.minLine(g)) + '.' + (GI.SP.NOTE[g.id] ? ' ' + esc(GI.SP.NOTE[g.id]) : '') +
        ' ' + GI.glossLink(m[0], 'Glossary →') + ' · <a href="' + GI.ghref('lab', S, { g: core, x: m[0] }) + '">In the lab →</a>');
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
