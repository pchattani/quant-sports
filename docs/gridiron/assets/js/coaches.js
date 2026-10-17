/* The Quant Gridiron — coaches (#/coaches) and one coach (#/coach/<name>).
 *
 * Fourth-down decision grades by head coach and season: his go rate against what the league does
 * in the same situations (go rate over expected, GOE: aggressiveness relative to the league), how
 * often he went when our model said go, how often he agreed with it, and the win probability his
 * calls gave up. The coach page adds his season-by-season line, his record, and this season's
 * fourth downs.
 *
 * Data: data/coaches.json ({"coaches": {name: {"seasons": [{season, team, n, go, go_rate, go_exp, goe, n_rec_go,
 * go_when_rec_go, agree, wp_lost, wp_lost_per}], "career": {...}, "record": {w, l, t, post_w, post_l}}}, "current": [...]}),
 * data/<S>/fourth_downs.json. Uses GI.fk and GI.fk.F (fourth.js). */
(function (GI) {
'use strict';

const K = () => GI.fk;
const F = () => GI.fk.F;

/* coaches.json -> {rows: [season rows], info: {name: {career, record, teams}}}. */
function readCoaches(d) {
  const k = K(), rows = [], info = {};
  if (!d || d.ok === false || !F()) return { rows: rows, info: info };
  const src = d.coaches || d.rows || d.data;
  const push = (name, r) => { const o = F().coachRow(Object.assign({ coach: name }, r)); if (o.coach) rows.push(o); };
  if (Array.isArray(src)) src.forEach(r => push(r.coach || r.name, r));
  else if (src && (src.cols || src.fields)) k.colRows(src).forEach(r => push(r.coach || r.name, r));
  else if (src && typeof src === 'object') Object.keys(src).forEach(name => {
    const x = src[name];
    if (!x || typeof x !== 'object') return;
    info[name] = { career: x.career || null, record: x.record || null, teams: x.teams || [] };
    const ss = x.seasons || x.by_season;
    if (Array.isArray(ss)) ss.forEach(r => push(name, r));
    else if (ss && typeof ss === 'object') Object.keys(ss).forEach(s => push(name, Object.assign({ season: Number(s) }, ss[s])));
  });
  return { rows: rows, info: info };
}
/* Sum season rows into one per coach (careers, or one season across two teams). */
function aggregate(rows) {
  const k = K(), by = {};
  rows.forEach(r => {
    const x = by[r.coach] || (by[r.coach] = { coach: r.coach, teams: {}, seasons: {}, n: 0, go: 0, exp: 0, expN: 0, should: 0, shouldAny: false, went: 0, agreeN: 0, agreeD: 0, lost: 0, lostAny: false });
    String(r.team || '').split('/').forEach(t => { if (t) x.teams[t] = Math.max(x.teams[t] || 0, r.season || 0); });
    if (k.isNum(r.season)) x.seasons[r.season] = 1;
    const n = r.n || 0;
    x.n += n; x.go += k.isNum(r.go) ? r.go : 0;
    if (k.isNum(r.go_exp)) { x.exp += r.go_exp * n; x.expN += n; }
    if (k.isNum(r.should)) { x.should += r.should; x.shouldAny = true; if (k.isNum(r.go_when)) x.went += r.go_when * r.should; }
    if (k.isNum(r.agree)) { x.agreeN += r.agree * n; x.agreeD += n; }
    if (k.isNum(r.lost)) { x.lost += r.lost; x.lostAny = true; }
  });
  return Object.keys(by).map(c => {
    const x = by[c], ss = Object.keys(x.seasons).map(Number);
    const teams = Object.keys(x.teams).sort((a, b) => x.teams[b] - x.teams[a]);
    return { coach: c, team: teams.join('/'), first: ss.length ? Math.min.apply(null, ss) : null, last: ss.length ? Math.max.apply(null, ss) : null, nSeasons: ss.length,
      n: x.n, go: x.go, go_rate: x.n ? x.go / x.n : null, go_exp: x.expN ? x.exp / x.expN : null, goe: x.n && x.expN ? x.go / x.n - x.exp / x.expN : null,
      should: x.shouldAny ? x.should : null, rec_rate: x.shouldAny && x.n ? x.should / x.n : null, go_when: x.should ? x.went / x.should : null, agree: x.agreeD ? x.agreeN / x.agreeD : null,
      lost: x.lostAny ? x.lost : null, lost_per: x.lostAny && x.n ? x.lost / x.n : null };
  });
}

const ST = { scope: 'season', min: 10, q: '' };

function renderList(el, params, state) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">Coaches <span class="card-sub" id="co-sub">Loading…</span><span class="gq-ctl" id="co-ctl"></span></div>' +
    '<div class="lab-controls gq-controls"><label>Search<input id="co-q" class="gq-search" type="search" placeholder="coach or team…"></label><label><span>Min fourth downs <span id="co-min-v"></span></span><input id="co-min" type="range" min="0" max="200" step="5"></label></div>' +
    '<div id="co-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note">GOE (go rate over expected) is the share of fourth downs a coach went for it minus a league model\'s expected share in the same situations (distance, field position, score, time and win probability, fitted on the same season): it measures aggressiveness against the league, not whether the calls were right. ' +
    'The model columns grade the calls against our fourth-down model: how often he went when it said go, how often his choice matched its recommendation, and the win probability given up against its best option. End-of-half and garbage-time fourth downs (win probability under 5% or over 95%) are left out.</div></div>' +
    '<div class="card"><div class="card-header">Aggressiveness against cost <span class="card-sub">Each coach: go rate over expected (x) against the win probability his calls gave up per fourth down (y). Marker size is the number of decisions; click for the coach.</span></div><div id="co-chart" class="gf-chart-lg"></div></div>' +
    '<div class="card"><div class="card-header">The league over time <span class="card-sub">League go rate on fourth down by season, and how often teams went when the model said go.</span></div><div id="co-league" class="gf-chart"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([GI.load('coaches.json'), k.loadY(S, 'fourth_downs.json')]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, $ = k.$;
    if (!F()) { k.set('co-table', k.muted('The fourth-down module did not load.')); return; }
    const C = readCoaches(o.res[0]);
    let rows = C.rows;
    if (!rows.some(r => r.season === S) && o.res[1] && o.res[1].ok !== false) F().coachesOf(o.res[1], F().playsOf(o.res[1])).filter(r => r.coach && r.coach !== '?').forEach(r => rows.push(Object.assign({}, r, { season: S })));
    if (!rows.length) { k.set('co-table', k.notBuilt('The coach table', o.res[0])); k.set('co-sub', ''); k.set('co-chart', ''); k.set('co-league', ''); return; }
    const seasons = Array.from(new Set(rows.map(r => r.season).filter(k.isNum))).sort((a, b) => b - a);
    const SS = seasons.indexOf(S) >= 0 ? S : seasons[0];
    k.set('co-ctl', k.toggle('co-scope', [['season', String(SS)], ['career', 'Careers' + (seasons.length ? ' ' + seasons[seasons.length - 1] + '–' + seasons[0] : '')]], ST.scope));
    $('co-min').value = ST.min; $('co-min-v').textContent = ST.min; $('co-q').value = ST.q;
    const draw = () => {
      const base = ST.scope === 'career' ? aggregate(rows) : aggregate(rows.filter(r => r.season === SS));
      const q = k.fold(ST.q);
      const list = base.filter(r => (r.n || 0) >= (ST.scope === 'career' ? ST.min * 4 : ST.min) && (!q || k.fold(r.coach + ' ' + r.team).indexOf(q) >= 0));
      table(list, S, C.info);
      chart(list, S);
      k.set('co-sub', list.length + ' head coaches · ' + (ST.scope === 'career' ? 'careers' : SS) + ' · sorted by GOE');
    };
    k.wireToggle(el, 'co-scope', v => { ST.scope = v; draw(); });
    $('co-q').oninput = e => { ST.q = e.target.value; draw(); };
    $('co-min').oninput = e => { ST.min = Number(e.target.value); $('co-min-v').textContent = ST.min; };
    $('co-min').onchange = draw;
    draw();
    league(rows, o.res[1]);
  });
}

function table(list, S, info) {
  const k = K(), host = k.$('co-table');
  if (!host) return;
  if (!list.length) { host.innerHTML = k.muted('No coach matches.'); return; }
  const career = ST.scope === 'career';
  const hasModel = list.some(r => k.isNum(r.should) || k.isNum(r.lost));
  host.innerHTML = k.table([{ label: 'Coach' }, { label: career ? 'Teams' : 'Team' }].concat(career ? [{ label: 'Seasons', align: 'right' }, { label: 'Record', align: 'right', title: 'Regular season (playoffs)' }] : [])
    .concat([{ label: '4th downs', align: 'right' }, { label: 'Go rate', align: 'right' }, { label: 'League would', align: 'right', title: 'Expected go rate from the league model' }, { label: 'GOE', align: 'right', title: 'Go rate over expected, percentage points' }])
    .concat(hasModel ? [{ label: 'Went when model said go', align: 'right' }, { label: 'Agree', align: 'right' }, { label: 'WP lost', align: 'right', title: 'Summed, percentage points' }, { label: 'per call', align: 'right', title: 'Percentage points per fourth down' }] : []),
    list.slice().sort((a, b) => (k.isNum(b.goe) ? b.goe : -9) - (k.isNum(a.goe) ? a.goe : -9)).map(r => {
      const rec = (info[r.coach] || {}).record;
      return { _href: k.coachHref(r.coach, S), cells: [{ v: r.coach, html: k.coachLink(r.coach, S) }, { v: r.team, html: String(r.team || '').split('/').filter(Boolean).slice(0, 4).map(t => k.teamChip(t, career ? null : S)).join(' ') || '—' }]
        .concat(career ? [{ v: r.nSeasons, html: k.int(r.nSeasons) + ' <span class="muted-inline">' + (r.first ? r.first + '–' + r.last : '') + '</span>' }, { v: rec ? rec.w - rec.l : null, html: rec ? k.esc(rec.w + '–' + rec.l + (rec.t ? '–' + rec.t : '') + (rec.post_w || rec.post_l ? ' (' + (rec.post_w || 0) + '–' + (rec.post_l || 0) + ')' : '')) : '—' }] : [])
        .concat([{ v: r.n, html: k.int(r.n) }, { v: r.go_rate, html: k.pct(r.go_rate, 1) }, { v: r.go_exp, html: k.pct(r.go_exp, 1) },
          { v: r.goe, html: k.isNum(r.goe) ? '<span class="' + (r.goe > 0.005 ? 'gq-ok' : r.goe < -0.005 ? 'gq-no' : '') + '">' + k.signed(r.goe * 100, 1) + '</span>' : '—' }])
        .concat(hasModel ? [{ v: r.go_when, html: k.isNum(r.go_when) ? k.pct(r.go_when, 0) + ' <span class="muted-inline">of ' + k.int(r.should) + '</span>' : '—' }, { v: r.agree, html: k.pct(r.agree, 0) },
          { v: r.lost, html: k.isNum(r.lost) ? k.num(r.lost * 100, 1) : '—' }, { v: r.lost_per, html: k.isNum(r.lost_per) ? k.num(r.lost_per * 100, 2) : '—' }] : []) };
    }), { compact: true, sticky: true });
  k.sortable(host);
}

function chart(list, S) {
  const k = K(), node = k.$('co-chart');
  if (!node) return;
  const yk = list.some(r => k.isNum(r.lost_per)) ? 'lost_per' : null;
  const pts = list.filter(r => k.isNum(r.goe) && (!yk || k.isNum(r[yk])));
  if (pts.length < 3) { node.innerHTML = k.muted('Needs three or more coaches with a go rate over expected.'); node.style.height = 'auto'; return; }
  const maxN = Math.max.apply(null, pts.map(r => r.n || 1));
  const y = r => (yk ? r[yk] * 100 : r.go_rate);
  k.plot(node, [{ type: 'scatter', mode: 'markers+text', x: pts.map(r => r.goe * 100), y: pts.map(y), text: pts.map(r => k.surname(r.coach)), textposition: 'top center', textfont: { size: 9, color: k.C.text2 },
    customdata: pts.map(r => k.coachHref(r.coach, S)), hovertext: pts.map(r => k.esc(r.coach) + ' (' + k.esc(r.team) + ')<br>GOE ' + k.signed(r.goe * 100, 1) + ' pp' + (yk ? ' · WP lost ' + k.num(r[yk] * 100, 2) + ' pp a call' : ' · go rate ' + k.pct(r.go_rate, 0)) + ' · ' + r.n + ' decisions'), hoverinfo: 'text',
    marker: { size: pts.map(r => 7 + 16 * Math.sqrt((r.n || 1) / maxN)), color: pts.map(r => k.teamColour(String(r.team || '').split('/')[0])), line: { color: '#0d1117', width: 1 }, opacity: 0.9 } }],
  k.layout({ margin: { l: 56, r: 12, t: 10, b: 46 }, xaxis: { title: 'Go rate over expected (pp): bolder than the league to the right', zeroline: true, zerolinecolor: '#6e7681' }, yaxis: yk ? { title: 'WP lost per fourth down (pp)', rangemode: 'tozero' } : { title: 'Go rate', tickformat: '.0%' } }));
  k.clickThrough(node);
}

function league(rows, fd) {
  const k = K(), node = k.$('co-league');
  if (!node) return;
  const by = {};
  rows.forEach(r => { if (!k.isNum(r.season) || !r.n) return; const x = by[r.season] || (by[r.season] = { n: 0, go: 0, should: 0, went: 0 }); x.n += r.n; x.go += r.go || 0; if (k.isNum(r.should)) { x.should += r.should; if (k.isNum(r.go_when)) x.went += r.go_when * r.should; } });
  const pts = Object.keys(by).map(s => ({ s: Number(s), go: by[s].n ? by[s].go / by[s].n : null, when: by[s].should ? by[s].went / by[s].should : null })).sort((a, b) => a.s - b.s);
  const L = fd && fd.league;
  if (L && pts.length && k.isNum(L.go_rate)) { const last = pts.find(p => p.s === fd.season); if (last) { last.go = L.go_rate; if (k.isNum(L.go_rate_rec)) last.when = L.go_rate_rec; } }
  if (pts.length < 2) { node.innerHTML = k.muted('Needs two or more seasons in the coach file.'); node.style.height = 'auto'; return; }
  const tr = [{ type: 'scatter', mode: 'lines+markers', name: 'League go rate', x: pts.map(p => p.s), y: pts.map(p => p.go), line: { color: k.ACC, width: 2 } }];
  if (pts.some(p => k.isNum(p.when))) tr.push({ type: 'scatter', mode: 'lines+markers', name: 'Went when the model said go', x: pts.map(p => p.s), y: pts.map(p => p.when), line: { color: '#58a6ff', width: 2, dash: 'dot' } });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 36 }, yaxis: { tickformat: '.0%', rangemode: 'tozero' }, xaxis: { dtick: 2 } }, k.legendTop())));
}

function renderCoach(el, params, state) {
  const k = K();
  const name = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([GI.load('coaches.json'), k.loadY(S, 'fourth_downs.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S;
    if (!F()) { el.innerHTML = k.muted('The fourth-down module did not load.'); return; }
    const C = readCoaches(o.res[0]);
    const nk = k.fold(name);
    let mine = C.rows.filter(r => k.fold(r.coach) === nk);
    const plays = F().playsOf(o.res[1]).filter(p => k.fold(p.coach || '') === nk);
    if (!mine.some(r => r.season === S) && plays.length) F().coachesOf({}, plays).forEach(r => mine.push(Object.assign({}, r, { season: S, coach: name })));
    if (!mine.length && !plays.length) { el.innerHTML = k.card('Coach', '', k.muted('No fourth-down record for <strong>' + k.esc(name) + '</strong>. <a href="#/coaches">All coaches →</a>')); return; }
    mine = mine.sort((a, b) => (a.season || 0) - (b.season || 0) || String(a.team).localeCompare(String(b.team)));
    const car = aggregate(mine)[0] || {};
    const inf = C.info[Object.keys(C.info).find(n => k.fold(n) === nk)] || {};
    const rec = inf.record;
    const last = mine[mine.length - 1] || {};
    const team = String(last.team || car.team || '').split('/')[0];
    const sub = [String(car.team || '').split('/').filter(Boolean).map(t => k.teamChip(t, null)).join(' '), car.nSeasons ? '<span>' + car.nSeasons + ' season' + (car.nSeasons === 1 ? '' : 's') + ' graded' + (car.first ? ', ' + car.first + '–' + car.last : '') + '</span>' : '',
      rec ? '<span>Record ' + rec.w + '–' + rec.l + (rec.t ? '–' + rec.t : '') + (rec.post_w || rec.post_l ? ', playoffs ' + (rec.post_w || 0) + '–' + (rec.post_l || 0) : '') + '</span>' : ''].filter(Boolean).join(' ');
    let h = k.head(k.esc(name), sub, '<a href="#/coaches">All coaches →</a>' + (team ? '<a href="' + k.teamHref(team, S) + '">' + k.esc(k.teamNick(team)) + ' →</a>' : ''), k.esc(initials(name)), team ? k.teamColour(team) : null);
    h += k.tiles([k.tile('Fourth downs', k.int(car.n), 'graded, career'), k.tile('Go rate', k.pct(car.go_rate, 1), 'league would: ' + k.pct(car.go_exp, 1)),
      k.tile('Go rate over expected', k.isNum(car.goe) ? k.signed(car.goe * 100, 1) + '<span class="kpi-dim"> pp</span>' : '—', 'aggressiveness against the league'),
      k.isNum(car.go_when) ? k.tile('Went when the model said go', k.pct(car.go_when, 0), k.int(car.should) + ' such fourth downs') : '',
      k.isNum(car.agree) ? k.tile('Agreed with the model', k.pct(car.agree, 0), '') : '',
      k.isNum(car.lost) ? k.tile('WP given away', k.num(car.lost * 100, 1) + '<span class="kpi-dim"> pp</span>', k.num(car.lost_per * 100, 2) + ' pp per fourth down') : '']);
    h += '<div class="card"><div class="card-header">Season by season <span class="card-sub">His go rate against what the league would have done in the same spots, and the cost of his calls where the model graded them.</span></div><div id="cp-chart" class="gf-chart"></div><div id="cp-table"></div></div>';
    h += '<div class="card"><div class="card-header">' + S + ' fourth downs <span class="card-sub">Every decision this season, graded.</span></div><div id="cp-plays"></div></div>';
    el.innerHTML = h;
    k.setMeta(k.esc(name));
    const node = k.$('cp-chart');
    if (mine.length >= 2) {
      const tr = [{ type: 'scatter', mode: 'lines+markers', name: 'Go rate', x: mine.map(r => String(r.season)), y: mine.map(r => r.go_rate), line: { color: k.ACC, width: 2 } },
        { type: 'scatter', mode: 'lines+markers', name: 'League would', x: mine.map(r => String(r.season)), y: mine.map(r => r.go_exp), line: { color: '#58a6ff', width: 2, dash: 'dot' } }];
      if (mine.some(r => k.isNum(r.lost_per))) tr.unshift({ type: 'bar', name: 'WP lost per call (pp)', x: mine.map(r => String(r.season)), y: mine.map(r => (k.isNum(r.lost_per) ? r.lost_per * 100 : null)), yaxis: 'y2', marker: { color: 'rgba(248,81,73,0.35)' } });
      k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 50, t: 30, b: 36 }, yaxis: { tickformat: '.0%', rangemode: 'tozero' }, yaxis2: { overlaying: 'y', side: 'right', showgrid: false, title: 'WP lost / call (pp)', rangemode: 'tozero' }, xaxis: { type: 'category' } }, k.legendTop())));
    } else node.style.display = 'none';
    const hm = mine.some(r => K().isNum(r.should) || K().isNum(r.lost) || K().isNum(r.agree)) ? '' : 'gf-hide';
    k.set('cp-table', k.table([{ label: 'Season' }, { label: 'Team' }, { label: '4th downs', align: 'right' }, { label: 'Went', align: 'right' }, { label: 'Go rate', align: 'right' }, { label: 'League would', align: 'right' }, { label: 'GOE', align: 'right' },
      { label: 'Went when model said go', align: 'right', cls: hm }, { label: 'Agree', align: 'right', cls: hm }, { label: 'WP lost', align: 'right', cls: hm }, { label: 'per call', align: 'right', cls: hm }],
      mine.slice().reverse().map(r => [{ v: r.season, html: '<strong>' + k.esc(r.season) + '</strong>' }, { v: r.team, html: String(r.team || '').split('/').filter(Boolean).map(t => k.teamChip(t, r.season)).join(' ') || '—' }, { v: r.n, html: k.int(r.n) }, { v: r.go, html: k.int(r.go) },
        { v: r.go_rate, html: k.pct(r.go_rate, 1) }, { v: r.go_exp, html: k.pct(r.go_exp, 1) }, { v: r.goe, html: k.isNum(r.goe) ? k.signed(r.goe * 100, 1) + ' pp' : '—' },
        { v: r.go_when, html: k.isNum(r.go_when) ? k.pct(r.go_when, 0) + ' <span class="muted-inline">of ' + k.int(r.should) + '</span>' : '—' }, { v: r.agree, html: k.pct(r.agree, 0) },
        { v: r.lost, html: k.isNum(r.lost) ? k.num(r.lost * 100, 1) : '—' }, { v: r.lost_per, html: k.isNum(r.lost_per) ? k.num(r.lost_per * 100, 2) : '—' }]), { compact: true }));
    k.sortable(k.$('cp-table'));
    if (plays.length) F().table(k.$('cp-plays'), plays.sort((a, b) => (k.isNum(b.lost) ? b.lost : -1) - (k.isNum(a.lost) ? a.lost : -1)), S, { team: true, max: 120 });
    else k.set('cp-plays', k.muted('No fourth downs for him in ' + S + '.'));
  });
}
function initials(n) { return String(n || '?').split(/\s+/).filter(Boolean).map(w => w.charAt(0).toUpperCase()).slice(0, 3).join(''); }

if (typeof GI.route === 'function') { try { GI.route('coaches', renderList); GI.route('coach', renderCoach); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
