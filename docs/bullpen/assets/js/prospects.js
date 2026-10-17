/* The Quant Bullpen — prospects (#/prospects): Triple-A players with their major-league
 * translations and call-up previews.
 *
 * A Triple-A line becomes a major-league equivalent through the translations fitted on players
 * with both Triple-A and MLB samples in the same season (models/projections.py: the logit-scale
 * shift per component, shrunk to defaults). The call-up preview is the projection the game model
 * would use on his first day.
 *
 * Data: data/aaa/<S>/prospects.json ({"hitters": [...] | {pid: {...}}, "pitchers": [...], or
 * "players": {pid: {"kind", "aaa", "mlb"|"mle"|"translation", "callup", ...}}}). Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const ST = { kind: 'hitter', q: '', parent: '', sort: 'mle' };
const HC = [['pa', 'PA', 'int'], ['avg', 'AVG', '3'], ['obp', 'OBP', '3'], ['slg', 'SLG', '3'], ['woba', 'wOBA', '3'], ['xwoba_savant', 'xwOBA', '3'], ['k_pct', 'K%', 'pct'], ['bb_pct', 'BB%', 'pct'], ['hr', 'HR', 'int'], ['barrel_pct', 'Barrel%', 'pct'], ['bat_speed', 'Bat speed', '1'], ['sprint_speed', 'Sprint', '1']];
const PC = [['ip', 'IP', '1'], ['ra9', 'RA9', '2'], ['fip', 'FIP', '2'], ['k_pct', 'K%', 'pct'], ['bb_pct', 'BB%', 'pct'], ['k_bb_pct', 'K−BB%', 'pct'], ['csw_pct', 'CSW%', 'pct'], ['fb_velo', 'FB velo', '1'], ['stuff_plus', 'Stuff+', 'plus'], ['pitching_plus', 'Pitching+', 'plus']];
const MLE_H = [['woba', 'MLB wOBA', '3'], ['k_pct', 'MLB K%', 'pct'], ['bb_pct', 'MLB BB%', 'pct'], ['hr_pa', 'MLB HR/PA', 'pct'], ['xwobacon', 'MLB xwOBAcon', '3']];
const MLE_P = [['k_bb_pct', 'MLB K−BB%', 'pct'], ['k_pct', 'MLB K%', 'pct'], ['bb_pct', 'MLB BB%', 'pct'], ['woba', 'MLB wOBA allowed', '3'], ['gb_pct', 'MLB GB%', 'pct']];

function listOf(d, kind) {
  const k = K();
  if (!d || d.ok === false) return [];
  const take = x => (Array.isArray(x) ? x : Object.keys(x || {}).map(pid => Object.assign({ pid: pid }, x[pid])));
  let rows = [];
  if (d.hitters || d.pitchers) rows = take(kind === 'pitcher' ? d.pitchers : d.hitters);
  else rows = take(d.players || d.prospects || []).filter(r => { const kd = String(r.kind || r.role || r.type || (k.isPitcherPos(r.pos) ? 'pitcher' : 'hitter')).toLowerCase(); return kind === 'pitcher' ? /pit/.test(kd) : !/pit/.test(kd); });
  return rows.map(r => Object.assign({}, r, { pid: String(r.pid || r.id) }));
}
function sub(r, keys) { for (let i = 0; i < keys.length; i++) { const x = r[keys[i]]; if (x && typeof x === 'object') return x; } return {}; }

function render(el, params, state) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">Prospects: Triple-A to the majors <span class="card-sub" id="pr-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls">' + k.toggle('pr-kind', [['hitter', 'Hitters'], ['pitcher', 'Pitchers']], ST.kind) +
    '<label>Search<input id="pr-q" class="gq-search" type="search" placeholder="name or club…"></label><label>Parent club<select id="pr-parent"><option value="">All organisations</option></select></label></div>' +
    '<div id="pr-table"></div><div class="pg-note gq-note" id="pr-note"></div></div>' +
    '<div class="card"><div class="card-header">Call-up previews <span class="card-sub">The players most likely to matter on arrival: highest projected major-league value, with what the model would expect on day one.</span></div><div id="pr-prev" class="gq-glance"></div></div>';
  return k.ready().then(() => {
    const S = k.S({ query: params.query || {}, level: 'aaa' }, { level: 'aaa', season: (state || {}).season });
    return Promise.all([k.loadY('aaa', S, 'prospects.json'), k.loadNames()]).then(res => ({ S: S, d: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, $ = id => document.getElementById(id);
    const all = { hitter: listOf(d, 'hitter'), pitcher: listOf(d, 'pitcher') };
    if (!all.hitter.length && !all.pitcher.length) { $('pr-table').innerHTML = k.notBuilt('The ' + S + ' Triple-A prospect file', d); $('pr-sub').textContent = ''; $('pr-prev').innerHTML = ''; return; }
    all.hitter.concat(all.pitcher).forEach(r => { if (r.name) k.learn(r.pid, { name: r.name, pos: r.pos, team: r.team }); });
    const parents = Array.from(new Set(all.hitter.concat(all.pitcher).map(r => r.parent || r.org || r.mlb_team).filter(Boolean)));
    $('pr-parent').innerHTML = '<option value="">All organisations</option>' + parents.sort((a, b) => k.teamAbbr(a).localeCompare(k.teamAbbr(b))).map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamAbbr(t) + ' · ' + k.teamName(t)) + '</option>').join('');
    const draw = () => {
      const pit = ST.kind === 'pitcher';
      const q = k.fold(ST.q.trim());
      const rows = all[ST.kind].filter(r => (!ST.parent || String(r.parent || r.org || r.mlb_team) === ST.parent) && (!q || k.fold((r.name || k.name(r.pid)) + ' ' + k.teamAbbr(r.team) + ' ' + k.teamAbbr(r.parent)).indexOf(q) >= 0));
      const aaa = r => Object.assign({}, r, sub(r, ['aaa', 'stats', 'line']));
      const mle = r => sub(r, ['mlb_eq', 'mle', 'translation']);
      const call = r => sub(r, ['mlb_proj', 'callup', 'preview']);
      const AC = (pit ? PC : HC).filter(c => rows.some(r => k.isNum(aaa(r)[c[0]])));
      const MC = (pit ? MLE_P : MLE_H).filter(c => rows.some(r => k.isNum(mle(r)[c[0]])));
      const key = MC[0];
      rows.sort((a, b) => (k.isNum(a.rank) ? a.rank : 9999) - (k.isNum(b.rank) ? b.rank : 9999) || ((key ? mle(b)[key[0]] : 0) || 0) - ((key ? mle(a)[key[0]] : 0) || 0));
      $('pr-table').innerHTML = rows.length ? k.table([{ label: '#', sortable: false }, { label: pit ? 'Pitcher' : 'Hitter' }, { label: 'AAA club' }, { label: 'Org' }, { label: 'Pos' }, { label: 'Age', align: 'right' }]
        .concat(AC.map(c => ({ label: c[1], align: 'right', title: 'Triple-A ' + c[1] }))).concat(MC.map(c => ({ label: c[1], align: 'right', cls: 'gq-mle', title: 'Major-league equivalent of this Triple-A line' }))).concat([{ label: 'Next-season proj.', align: 'right', title: 'Bullpen projection of next season\'s MLB wOBA (allowed, for pitchers)' }, { label: 'MLB this year', align: 'right', title: (pit ? 'Batters faced' : 'Plate appearances') + ' in the majors this season' }]),
      rows.map((r, i) => { const a = aaa(r), m = mle(r), c = call(r);
        return { _href: (pit ? k.pitcherHref('aaa', r.pid, S) : k.hitterHref('aaa', r.pid, S)), cells: [{ v: i + 1, cls: 'pos-cell' },
          { v: r.name || k.name(r.pid), html: '<a class="ply-link" href="' + (pit ? k.pitcherHref('aaa', r.pid, S) : k.hitterHref('aaa', r.pid, S)) + '">' + k.esc(r.name || k.name(r.pid)) + '</a>' + (r.rank ? ' <span class="gq-tag">#' + k.esc(r.rank) + '</span>' : '') },
          { v: k.teamAbbr(r.team), html: r.team ? k.teamChip('aaa', r.team, S) : '—' }, { v: k.teamAbbr(r.parent || r.org), html: (r.parent || r.org) ? k.teamChip('mlb', r.parent || r.org, null) : '—' },
          { v: r.pos || '', html: k.esc(r.pos || '—') }, { v: r.age, html: k.isNum(r.age) ? k.num(r.age, 0) : '—' }]
          .concat(AC.map(cc => ({ v: a[cc[0]], html: k.fmtV(a[cc[0]], cc[2]) }))).concat(MC.map(cc => ({ v: m[cc[0]], html: '<strong>' + k.fmtV(m[cc[0]], cc[2]) + '</strong>', cls: 'gq-mle' })))
          .concat([{ v: c.woba, html: k.rate3(c.woba) }, { v: r.mlb_this_season, html: k.isNum(r.mlb_this_season) && r.mlb_this_season > 0 ? k.int(r.mlb_this_season) : '<span class="muted-inline">—</span>' }]) }; }), { compact: true, sticky: true }) : k.muted('No prospect matches these filters.');
      k.sortable($('pr-table'));
      $('pr-sub').textContent = rows.length + (pit ? ' pitchers' : ' hitters') + ' · Triple-A ' + S + ' · sorted by the major-league translation';
      previews(rows.slice(0, 6), pit, S, mle, call);
    };
    k.wireToggle(el, 'pr-kind', v => { ST.kind = v; draw(); });
    let t = null;
    $('pr-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    $('pr-parent').onchange = e => { ST.parent = e.target.value; draw(); };
    draw();
    $('pr-note').innerHTML = 'Major-league equivalents shift each Triple-A component on the log-odds scale (rates) or linearly (contact quality) by the average change of players who played both levels in the same season, weighted by the harmonic mean of the two samples and shrunk towards defaults (hitters: strikeouts +0.22, walks −0.18, home runs per ball in play −0.25 on the logit scale; pitchers the mirror image); the equivalent wOBA recombines the translated events with the season\'s wOBA weights. Ranks (hitters by equivalent wOBA, pitchers by equivalent K−BB%) need 100+ PA or BF. The next-season projection folds the translated Triple-A counts in at 0.6 weight. ' +
      (d.updated_at ? 'Updated ' + k.esc(k.fmtDate(d.updated_at, { year: false })) + '. ' : '') + 'Triple-A Statcast starts in 2023. Click a player for his Triple-A page.';
  });
}

function previews(rows, pit, S, mle, call) {
  const k = K();
  const host = document.getElementById('pr-prev');
  if (!host) return;
  host.innerHTML = rows.length ? rows.map(r => {
    const m = mle(r), c = call(r);
    const lines = (pit ? MLE_P : MLE_H).filter(x => k.isNum(m[x[0]])).slice(0, 4).map(x => '<div class="gq-mini-r"><span>' + k.esc(x[1]) + '</span><span class="gq-mini-v">' + k.fmtV(m[x[0]], x[2]) + '</span></div>').join('');
    const comp = c.components || {};
    const kk = comp.K, bb = comp.BB;
    const txt = (k.isNum(c.woba) ? 'Projected next season in the majors: ' + k.rate3(c.woba) + ' wOBA' + (pit ? ' allowed' : '') : '') +
      (kk && k.isNum(kk.proj) ? ', ' + k.pct(kk.proj, 1) + ' strikeouts' + (k.isNum(kk.p10) ? ' (' + k.pct(kk.p10, 0) + '–' + k.pct(kk.p90, 0) + ')' : '') : '') +
      (bb && k.isNum(bb.proj) ? ', ' + k.pct(bb.proj, 1) + ' walks' : '') + (k.isNum(c.woba) ? '.' : '') +
      (k.isNum(r.mlb_this_season) && r.mlb_this_season > 0 ? ' Already ' + k.int(r.mlb_this_season) + (pit ? ' batters faced' : ' PA') + ' in the majors this season.' : '');
    return '<div class="gq-mini"><div class="gq-mini-h"><a href="' + (pit ? k.pitcherHref('aaa', r.pid, S) : k.hitterHref('aaa', r.pid, S)) + '">' + k.esc(r.name || k.name(r.pid)) + '</a> <span class="muted-inline">' + k.esc([r.pos, k.isNum(r.age) ? 'age ' + Math.floor(r.age) : '', (r.parent || r.org) ? k.teamAbbr(r.parent || r.org) : ''].filter(Boolean).join(' · ')) + '</span></div>' +
      lines + (txt ? '<div class="gq-mini-t">' + k.esc(txt) + '</div>' : '') + '</div>';
  }).join('') : k.muted('No previews yet.');
}

if (typeof BP.route === 'function') { BP.route('prospects', render); try { BP.route('#/prospects', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
