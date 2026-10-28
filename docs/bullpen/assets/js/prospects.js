/* The Quant Bullpen — prospects (#/prospects): Triple-A players with their major-league
 * translations and call-up previews, on Design System 2.0 (stat tiles, preview cards, a v2 leaderboard).
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
  const U = BP.ui;
  el.innerHTML = QK.sectionHead({ kicker: 'Prospects · Triple-A', title: 'Triple-A to the majors', sub: 'Every Triple-A player\'s line translated to the majors, and what our model would expect on the day of a call-up.' }) +
    '<div id="pr-kpis"></div>' +
    '<section class="qk-card"><div class="qk-card-body"><div class="bp-ctl">' + U.seg('pr-kind', 'Kind', [['hitter', 'Hitters'], ['pitcher', 'Pitchers']], ST.kind) +
    '<label>Search<input id="pr-q" class="gq-search" type="search" placeholder="name or club…"></label><label>Parent club<select id="pr-parent"><option value="">All organisations</option></select></label></div></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Call-up previews', title: 'Ready now', sub: 'The six with the best major-league translation, and what our projection expects from them next season.' }) + '<div class="qk-grid" id="pr-prev"></div></section>' +
    '<section class="qk-section"><div id="pr-card"></div></section>';
  return k.ready().then(() => {
    const S = k.S({ query: params.query || {}, level: 'aaa' }, { level: 'aaa', season: (state || {}).season });
    return Promise.all([k.loadY('aaa', S, 'prospects.json'), k.loadNames()]).then(res => ({ S: S, d: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, $ = id => document.getElementById(id);
    const all = { hitter: listOf(d, 'hitter'), pitcher: listOf(d, 'pitcher') };
    if (!all.hitter.length && !all.pitcher.length) { $('pr-card').innerHTML = U.card2('Prospects', '', QK.empty('Not built yet', 'The ' + S + ' Triple-A prospect file is not available.')); $('pr-prev').innerHTML = ''; return; }
    all.hitter.concat(all.pitcher).forEach(r => { if (r.name) k.learn(r.pid, { name: r.name, pos: r.pos, team: r.team }); });
    const parents = Array.from(new Set(all.hitter.concat(all.pitcher).map(r => r.parent || r.org || r.mlb_team).filter(Boolean)));
    $('pr-parent').innerHTML = '<option value="">All organisations</option>' + parents.sort((a, b) => k.teamAbbr(a).localeCompare(k.teamAbbr(b))).map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamAbbr(t) + ' · ' + k.teamName(t)) + '</option>').join('');
    const aaa = r => Object.assign({}, r, sub(r, ['aaa', 'stats', 'line']));
    const mle = r => sub(r, ['mlb_eq', 'mle', 'translation']);
    const call = r => sub(r, ['mlb_proj', 'callup', 'preview']);
    /* the top of the ranking (ranks need 100+ PA or BF), else the best translation */
    const best = (list, key, lowerBetter) => list.filter(r => k.isNum(mle(r)[key])).sort((a, b) => ((k.isNum(a.rank) ? a.rank : 9999) - (k.isNum(b.rank) ? b.rank : 9999)) || (lowerBetter ? 1 : -1) * (mle(a)[key] - mle(b)[key]))[0];
    const bh = best(all.hitter, 'woba'), bp = best(all.pitcher, 'k_bb_pct');
    const up = all.hitter.concat(all.pitcher).filter(r => k.isNum(r.mlb_this_season) && r.mlb_this_season > 0).length;
    $('pr-kpis').innerHTML = '<div class="bp-kpis">' + QK.stats([
      bh ? { label: 'Top-ranked hitter', value: k.surname(bh.name || k.name(bh.pid)) + ' ' + k.rate3(mle(bh).woba), signal: true, sub: 'major-league equivalent wOBA · ' + k.teamAbbr(bh.parent || bh.org), href: k.hitterHref('aaa', bh.pid, S) } : null,
      bp ? { label: 'Top-ranked pitcher', value: k.surname(bp.name || k.name(bp.pid)) + ' ' + k.fmtV(mle(bp).k_bb_pct, 'pct'), signal: true, sub: 'major-league equivalent K−BB% · ' + k.teamAbbr(bp.parent || bp.org), href: k.pitcherHref('aaa', bp.pid, S) } : null,
      { label: 'Triple-A players', value: String(all.hitter.length + all.pitcher.length), sub: all.hitter.length + ' hitters, ' + all.pitcher.length + ' pitchers' },
      { label: 'Already in the majors', value: String(up), sub: 'played for the big club this season' }
    ]) + '</div>';
    const draw = () => {
      const pit = ST.kind === 'pitcher';
      const q = k.fold(ST.q.trim());
      const rows = all[ST.kind].filter(r => (!ST.parent || String(r.parent || r.org || r.mlb_team) === ST.parent) && (!q || k.fold((r.name || k.name(r.pid)) + ' ' + k.teamAbbr(r.team) + ' ' + k.teamAbbr(r.parent)).indexOf(q) >= 0));
      const AC = (pit ? PC : HC).filter(c => rows.some(r => k.isNum(aaa(r)[c[0]])));
      const MC = (pit ? MLE_P : MLE_H).filter(c => rows.some(r => k.isNum(mle(r)[c[0]])));
      const key = MC[0];
      rows.sort((a, b) => (k.isNum(a.rank) ? a.rank : 9999) - (k.isNum(b.rank) ? b.rank : 9999) || ((key ? mle(b)[key[0]] : 0) || 0) - ((key ? mle(a)[key[0]] : 0) || 0));
      const href = r => (pit ? k.pitcherHref('aaa', r.pid, S) : k.hitterHref('aaa', r.pid, S));
      $('pr-card').innerHTML = U.card2(pit ? 'Pitchers' : 'Hitters', rows.length + ' players · Triple-A ' + S + ' · sorted by the major-league translation; blue columns are the major-league equivalents', '<div id="pr-table"></div>', { flush: true,
        foot: '<span class="bp-fn">Major-league equivalents shift each Triple-A rate on the log-odds scale by the average change of players who played both levels in the same season, shrunk towards defaults. Ranks need 100+ PA or BF. Triple-A Statcast starts in 2023.</span>' });
      if (!rows.length) { $('pr-table').innerHTML = QK.empty('Nobody here', 'No prospect matches these filters.'); previews([], pit, S, mle, call); return; }
      const cols = [{ key: 'name', label: pit ? 'Pitcher' : 'Hitter', type: 'entity', sub: 'sub', mark: r => (r.parent || r.org ? U.team(r.parent || r.org, 'mlb') : null), href: href }]
        .concat(AC.map(c => ({ key: 'a_' + c[0], label: c[1], num: true, fmt: x => k.fmtV(x, c[2]), tip: 'Triple-A ' + c[1] })))
        .concat(MC.map((c, i) => (i === 0 ? { key: 'm_' + c[0], label: c[1], type: 'bar', fmt: x => k.fmtV(x, c[2]), tip: 'Major-league equivalent of this Triple-A line', cls: 'bp-mle' } : { key: 'm_' + c[0], label: c[1], num: true, fmt: x => k.fmtV(x, c[2]), tip: 'Major-league equivalent', cls: 'bp-mle' })))
        .concat([{ key: 'proj', label: 'Next season', num: true, fmt: x => k.rate3(x), tip: 'Our projection of next season\'s MLB wOBA' + (pit ? ' allowed' : '') }, { key: 'mlbn', label: 'MLB this year', num: true, fmt: x => (k.isNum(x) && x > 0 ? k.int(x) : '—'), tip: (pit ? 'Batters faced' : 'Plate appearances') + ' in the majors this season' }]);
      QK.leaderboard($('pr-table'), { dense: true, rank: true, maxHeight: 640, rowHref: href, columns: cols, rows: rows.map(r => {
        const a = aaa(r), m = mle(r), c = call(r);
        const o2 = { pid: r.pid, name: r.name || k.name(r.pid), parent: r.parent, org: r.org, sub: [r.pos, k.isNum(r.age) ? 'age ' + Math.floor(r.age) : '', r.team ? k.teamAbbr(r.team) : '', r.rank ? '#' + r.rank : ''].filter(Boolean).join(' · '), proj: c.woba, mlbn: r.mlb_this_season };
        AC.forEach(cc => { o2['a_' + cc[0]] = a[cc[0]]; });
        MC.forEach(cc => { o2['m_' + cc[0]] = m[cc[0]]; });
        return o2;
      }) });
      previews(rows.slice(0, 6), pit, S, mle, call);
    };
    QK.seg($('pr-kind'), v => { ST.kind = v; draw(); });
    let t = null;
    $('pr-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    $('pr-parent').onchange = e => { ST.parent = e.target.value; draw(); };
    draw();
    BP.setMeta(d.updated_at ? 'Prospects ' + k.esc(k.fmtDate(d.updated_at, { year: false })) : '');
  });
}

function previews(rows, pit, S, mle, call) {
  const k = K();
  const U = BP.ui;
  const host = document.getElementById('pr-prev');
  if (!host) return;
  host.innerHTML = rows.length ? rows.map(r => {
    const m = mle(r), c = call(r);
    const comp = c.components || {};
    const kk = comp.K, bb = comp.BB;
    const href = pit ? k.pitcherHref('aaa', r.pid, S) : k.hitterHref('aaa', r.pid, S);
    const lines = (pit ? MLE_P : MLE_H).filter(x => k.isNum(m[x[0]])).slice(0, 3).map(x => '<li><span>' + k.esc(x[1]) + '</span><span class="v">' + k.fmtV(m[x[0]], x[2]) + '</span></li>').join('');
    const proj = [];
    if (k.isNum(c.woba)) proj.push('<li><span>Next season wOBA' + (pit ? ' allowed' : '') + '</span><span class="v">' + k.rate3(c.woba) + '</span></li>');
    if (kk && k.isNum(kk.proj)) proj.push('<li><span>Strikeouts</span><span class="v">' + k.pct(kk.proj, 1) + (k.isNum(kk.p10) ? ' <span class="s">' + k.pct(kk.p10, 0) + '–' + k.pct(kk.p90, 0) + '</span>' : '') + '</span></li>');
    if (bb && k.isNum(bb.proj)) proj.push('<li><span>Walks</span><span class="v">' + k.pct(bb.proj, 1) + (k.isNum(bb.p10) ? ' <span class="s">' + k.pct(bb.p10, 0) + '–' + k.pct(bb.p90, 0) + '</span>' : '') + '</span></li>');
    const org = r.parent || r.org;
    return '<div class="qk-span-4"><section class="qk-card bp-prev" style="--tc:' + k.esc(org ? U.tcol(org) : 'var(--signal)') + '"><div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title"><a href="' + href + '">' + k.esc(r.name || k.name(r.pid)) + '</a></div>' +
      '<div class="qk-card-sub">' + k.esc([r.pos, k.isNum(r.age) ? 'age ' + Math.floor(r.age) : '', org ? k.teamName(org) : ''].filter(Boolean).join(' · ')) + '</div></div>' + (org ? BP.teamMark(org, 'sm') : '') + '</div>' +
      '<div class="qk-card-body flush"><ul class="bp-list">' + lines + proj.join('') + '</ul>' +
      (k.isNum(r.mlb_this_season) && r.mlb_this_season > 0 ? '<div class="bp-note" style="padding:0 16px 12px">Already ' + k.int(r.mlb_this_season) + (pit ? ' batters faced' : ' PA') + ' in the majors this season.</div>' : '') + '</div></section></div>';
  }).join('') : '<div class="qk-span-12">' + QK.empty('No previews yet') + '</div>';
}

if (typeof BP.route === 'function') { BP.route('prospects', render); try { BP.route('#/prospects', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
