/* The Quant Gridiron — Coaches (#/coaches) and one coach (#/coach/<name>), in the Lab.
 * Fourth-down decisions by head coach and season: go rate against what the league does in the same spots
 * (GOE), how often he went when our model said go, agreement and the win probability his calls gave up.
 * Aggressiveness-against-cost map, the league over time, careers. Reads coaches.json and <S>/fourth_downs.json. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const MARK = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
const ST = { scope: 'season', min: 10, q: '' };

function readCoaches(d) {
  const rows = [], info = {};
  if (!GI.ok(d)) return { rows: rows, info: info };
  const src = d.coaches || {};
  const push = (name, r) => { const o = GI.F.coachRow(Object.assign({ coach: name }, r)); if (o.coach) rows.push(o); };
  if (Array.isArray(src)) src.forEach(r => push(r.coach || r.name, r));
  else Object.keys(src).forEach(name => { const x = src[name]; if (!x) return; info[name] = { record: x.record || null, teams: x.teams || [] }; (x.seasons || []).forEach(r => push(name, r)); });
  return { rows: rows, info: info };
}
function aggregate(rows) {
  const by = {};
  rows.forEach(r => {
    const x = by[r.coach] || (by[r.coach] = { coach: r.coach, teams: {}, seasons: {}, n: 0, go: 0, exp: 0, expN: 0, should: 0, shouldAny: false, went: 0, agreeN: 0, agreeD: 0, lost: 0, lostAny: false });
    String(r.team || '').split('/').forEach(t => { if (t) x.teams[t] = Math.max(x.teams[t] || 0, r.season || 0); });
    if (isNum(r.season)) x.seasons[r.season] = 1;
    const n = r.n || 0;
    x.n += n; x.go += isNum(r.go) ? r.go : 0;
    if (isNum(r.go_exp)) { x.exp += r.go_exp * n; x.expN += n; }
    if (isNum(r.should)) { x.should += r.should; x.shouldAny = true; if (isNum(r.go_when)) x.went += r.go_when * r.should; }
    if (isNum(r.agree)) { x.agreeN += r.agree * n; x.agreeD += n; }
    if (isNum(r.lost)) { x.lost += r.lost; x.lostAny = true; }
  });
  return Object.keys(by).map(c => {
    const x = by[c], ss = Object.keys(x.seasons).map(Number);
    return { coach: c, team: Object.keys(x.teams).sort((a, b) => x.teams[b] - x.teams[a]).join('/'), first: ss.length ? Math.min.apply(null, ss) : null, last: ss.length ? Math.max.apply(null, ss) : null, nSeasons: ss.length,
      n: x.n, go: x.go, go_rate: x.n ? x.go / x.n : null, go_exp: x.expN ? x.exp / x.expN : null, goe: x.n && x.expN ? x.go / x.n - x.exp / x.expN : null,
      should: x.shouldAny ? x.should : null, go_when: x.should ? x.went / x.should : null, agree: x.agreeD ? x.agreeN / x.agreeD : null, lost: x.lostAny ? x.lost : null, lost_per: x.lostAny && x.n ? x.lost / x.n : null };
  });
}

/* round 9: the Coaches tab of "Fourth-down calls" (#/fourth-downs?tab=coaches; #/coaches redirects there): fourth.js
   renders the page head and the tabs, this the body (GI.coachesPage) */
function page(el, params, head0) {
  const S = Number(params.season);
  return GI.loadAll(['coaches.json', GI.ypath('fourth_downs.json', S)]).then(res => {
    if (!el.isConnected) return;
    const head = (head0 || GI.pageHead('Teams · ' + S, 'Coaches', 'Who goes for it on fourth down, against the league and against our model.') + GI.sectionNav('teams', 'fourth')) + QK.note('<b>Go rate over expected</b> compares how often a coach went for it with how often the league goes in the same spots. Above zero is bolder than the league; the win chance given up says whether the boldness paid.');
    const C = readCoaches(res[0]);
    const rows = C.rows;
    if (!rows.some(r => r.season === S) && GI.ok(res[1])) GI.F.coachesOf(res[1], GI.F.playsOf(res[1])).filter(r => r.coach).forEach(r => rows.push(Object.assign({}, r, { season: S })));
    if (!rows.length) { el.innerHTML = head + GI.notBuilt('The coach table', res[0]); return; }
    const seasons = Array.from(new Set(rows.map(r => r.season).filter(isNum))).sort((a, b) => b - a);
    const SS = seasons.indexOf(S) >= 0 ? S : seasons[0];
    el.innerHTML = head + '<div class="gi-toolbar">' + GI.seg('co-scope', [['season', String(SS)], ['career', 'Careers ' + seasons[seasons.length - 1] + '–' + seasons[0]]], ST.scope, 'Scope') +
      GI.field('Search', '<input id="co-q" class="qk-input" type="search" placeholder="Coach or team">') + '<label class="gi-field"><span>Min fourth downs <b id="co-min-v"></b></span><input id="co-min" type="range" min="0" max="200" step="5"></label></div>' +
      GI.grid(GI.card('Aggressiveness against cost', 'go rate over expected (right is bolder than the league) against the win probability given up per call; dot size: decisions', GI.chartBox('co-chart', 460, 'Aggressiveness against cost'), { span: 7 }) +
        GI.card('The league over time', 'league go rate on fourth down, and how often teams went when the model said go', GI.chartBox('co-league', 460, 'League go rate by season'), { span: 5 })) +
      GI.card('<span id="co-title">Head coaches</span>', '<span id="co-sub"></span>', '<div id="co-table"></div>', { flush: true }) +
      GI.note('<p><b>GOE</b> (go rate over expected) is the share of fourth downs a coach went for it minus a league model\'s expected share in the same situations: aggressiveness against the league, not whether the calls were right. The model columns grade the calls against our fourth-down model. End-of-half and garbage-time fourth downs are left out.</p>');
    const $ = id => document.getElementById(id);
    $('co-min').value = ST.min; $('co-min-v').textContent = ST.min; $('co-q').value = ST.q;
    const draw = () => {
      const career = ST.scope === 'career';
      const base = career ? aggregate(rows) : aggregate(rows.filter(r => r.season === SS));
      const q = GI.fold(ST.q);
      const list = base.filter(r => (r.n || 0) >= (career ? ST.min * 4 : ST.min) && (!q || GI.fold(r.coach + ' ' + r.team).indexOf(q) >= 0)).sort((a, b) => (isNum(b.goe) ? b.goe : -9) - (isNum(a.goe) ? a.goe : -9));
      const hasModel = list.some(r => isNum(r.should) || isNum(r.lost));
      GI.set('co-sub', list.length + ' head coaches · ' + (career ? 'careers' : SS) + ' · sorted by GOE');
      const R = list.map(r => { const rec = (C.info[r.coach] || {}).record; return Object.assign({ name: r.coach, t0: String(r.team || '').split('/')[0], sub: String(r.team || '').split('/').filter(Boolean).slice(0, 4).join(' · '),
        rec: rec ? GI.record(rec.w, rec.l, rec.t) + (rec.post_w || rec.post_l ? ' (' + (rec.post_w || 0) + '-' + (rec.post_l || 0) + ')' : '') : '', goeP: isNum(r.goe) ? r.goe * 100 : null, lostP: isNum(r.lost) ? r.lost * 100 : null, perP: isNum(r.lost_per) ? r.lost_per * 100 : null }, r); });
      if (R.length) QK.leaderboard($('co-table'), { dense: true, rank: true, maxHeight: 680, rows: R, sort: { key: 'goeP', dir: 'desc' }, rowHref: r => GI.coachHref(r.coach, S),
        columns: [{ key: 'name', label: 'Coach', type: 'entity', sub: 'sub', mark: r => MARK(r.t0), href: r => GI.coachHref(r.coach, S) }]
          .concat(career ? [{ key: 'nSeasons', label: 'Seasons', num: true, fmt: (v, r) => v + ' <span class="qk-muted">' + (r.first ? r.first + '–' + r.last : '') + '</span>' }, { key: 'rec', label: 'Record', num: true, sort: false }] : [])
          .concat([{ key: 'n', label: '4th downs', num: true }, { key: 'go_rate', label: 'Go rate', type: 'bar', max: 1, fmt: v => GI.pct(v, 1) }, { key: 'go_exp', label: 'League would', num: true, fmt: v => GI.pct(v, 1) },
            { key: 'goeP', label: 'GOE', num: true, fmt: v => (isNum(v) ? GI.ptsEdge(v, 1) : '—'), tip: 'Go rate over expected, points' }])
          .concat(hasModel ? [{ key: 'go_when', label: 'Went when our model said go', num: true, fmt: (v, r) => (isNum(v) ? GI.pct(v, 0) + ' <span class="qk-muted">of ' + GI.int(r.should) + '</span>' : '—') }, { key: 'agree', label: 'Agree', num: true, fmt: v => GI.pct(v, 0) },
            { key: 'lostP', label: 'Win chance lost', num: true, fmt: v => (isNum(v) ? GI.num(v, 1) : '—') }, { key: 'perP', label: 'Per call', num: true, fmt: v => (isNum(v) ? GI.num(v, 2) : '—') }] : []) });
      else GI.set('co-table', GI.muted('No coach matches.'));
      const pts = list.filter(r => isNum(r.goe) && isNum(r.lost_per));
      const maxN = Math.max.apply(null, pts.map(r => r.n || 1).concat([1]));
      if (pts.length >= 3) GI.ch.scatter('co-chart', { points: pts.map(r => ({ x: r.goe * 100, y: r.lost_per * 100, name: r.coach + ' (' + r.team + ')', label: GI.surnameOf(r.coach), color: GI.teamColour(String(r.team || '').split('/')[0]), href: GI.coachHref(r.coach, S), size: 7 + 16 * Math.sqrt((r.n || 1) / maxN) })),
        xName: 'Go rate over expected (pts)', yName: 'WP lost per call (pts)', refX: 0, labelTop: 12, xFmt: v => GI.signed(v, 0), yFmt: v => GI.num(v, 1) });
      else GI.ch.none('co-chart', 'Needs three or more coaches with model grades.');
    };
    const by = {};
    rows.forEach(r => { if (!isNum(r.season) || !r.n) return; const x = by[r.season] || (by[r.season] = { n: 0, go: 0, should: 0, went: 0 }); x.n += r.n; x.go += r.go || 0; if (isNum(r.should)) { x.should += r.should; if (isNum(r.go_when)) x.went += r.go_when * r.should; } });
    const L = Object.keys(by).map(s => ({ s: Number(s), go: by[s].n ? by[s].go / by[s].n : null, when: by[s].should ? by[s].went / by[s].should : null })).sort((a, b) => a.s - b.s);
    if (L.length > 1) GI.ch.lines('co-league', [{ name: 'League go rate', x: L.map(p => p.s), y: L.map(p => p.go), symbol: true }].concat(L.some(p => isNum(p.when)) ? [{ name: 'Went when the model said go', x: L.map(p => p.s), y: L.map(p => p.when), dash: true, symbol: true }] : []), { yFmt: v => GI.pct(v, 0), xFmt: String, xLabel: x => String(x), yMin: 0, xName: 'Season', yName: 'Go rate on fourth down' });
    else GI.ch.none('co-league', 'Needs two or more seasons.');
    GI.wireSeg(el, 'co-scope', v => { ST.scope = v; draw(); });
    $('co-q').addEventListener('input', e => { ST.q = e.target.value; draw(); });
    $('co-min').addEventListener('input', e => { ST.min = Number(e.target.value); $('co-min-v').textContent = ST.min; });
    $('co-min').addEventListener('change', draw);
    draw();
  });
}
GI.route('coaches', page);
GI.coachesPage = page;

GI.route('coach', function (el, params) {
  const name = String(params.id || '');
  const S = Number(params.season);
  return GI.loadAll(['coaches.json', GI.ypath('fourth_downs.json', S)]).then(res => {
    if (!el.isConnected) return;
    const C = readCoaches(res[0]);
    const nk = GI.fold(name);
    let mine = C.rows.filter(r => GI.fold(r.coach) === nk);
    const plays = GI.F.playsOf(res[1]).filter(p => GI.fold(p.coach || '') === nk);
    if (!mine.some(r => r.season === S) && plays.length) GI.F.coachesOf({}, plays).forEach(r => mine.push(Object.assign({}, r, { season: S, coach: name })));
    const nav = GI.sectionNav('teams', 'fourth');
    if (!mine.length && !plays.length) { el.innerHTML = GI.pageHead('Teams · coaches', name || 'Coach', 'No fourth-down record for this coach. <a href="#/fourth-downs?tab=coaches">All coaches →</a>') + nav; return; }
    mine = mine.sort((a, b) => (a.season || 0) - (b.season || 0));
    const car = aggregate(mine)[0] || {};
    const inf = C.info[Object.keys(C.info).find(n => GI.fold(n) === nk)] || {};
    const rec = inf.record;
    const team = String((mine[mine.length - 1] || {}).team || car.team || '').split('/')[0];
    const col = team ? GI.tc(team) : 'var(--accent)';
    document.title = name + ' · ' + GI.SITE;
    el.innerHTML = QK.playerHeader({ name: name, kicker: 'Head coach', pos: '', team: team ? { name: GI.teamName(team), abbr: GI.teamAbbr(team), colour: GI.teamInfo(team).colour, alt: GI.teamInfo(team).alt, href: GI.teamHref(team) } : null,
      meta: [car.nSeasons ? ['Graded', car.nSeasons + ' season' + (car.nSeasons === 1 ? '' : 's') + (car.first ? ', ' + car.first + '–' + car.last : '')] : null, rec ? ['Record', GI.record(rec.w, rec.l, rec.t)] : null],
      stats: [{ label: 'Go rate', value: GI.pct(car.go_rate, 0) }, { label: 'GOE (pts)', value: isNum(car.goe) ? GI.signed(car.goe * 100, 1) : '—' }].concat(isNum(car.lost) ? [{ label: 'Win chance lost', value: GI.num(car.lost * 100, 1) }] : []) }) + nav +
      GI.kpis([GI.kpi('Fourth downs', GI.int(car.n), 'graded, career'), GI.kpi('League would', GI.pct(car.go_exp, 1), 'expected go rate in the same spots'), isNum(car.go_when) ? GI.kpi('Went when our model said go', GI.pct(car.go_when, 0), GI.int(car.should) + ' such fourth downs') : '',
        isNum(car.agree) ? GI.kpi('Agreed with our model', GI.pct(car.agree, 0), '') : '', isNum(car.lost_per) ? GI.kpi('Per call', GI.num(car.lost_per * 100, 2), 'win chance given up, percentage points', { unit: 'pts', signal: true }) : '']) +
      GI.card('Season by season', 'go rate against what the league would have done in the same spots', (mine.length >= 2 ? GI.chartBox('cp-chart', 300, 'Go rate by season') : '') + '<div id="cp-table"></div>') +
      GI.card(S + ' fourth downs', 'every decision this season, graded', '<div id="cp-plays"></div>', { flush: true });
    if (mine.length >= 2) GI.ch.lines('cp-chart', [{ name: 'Go rate', x: mine.map(r => r.season), y: mine.map(r => r.go_rate), symbol: true, colour: team ? GI.teamColour(team) : null }, { name: 'League would', x: mine.map(r => r.season), y: mine.map(r => r.go_exp), dash: true, symbol: true }], { yFmt: v => GI.pct(v, 0), xFmt: String, xLabel: x => String(x), yMin: 0, xName: 'Season', yName: 'Go rate on fourth down' });
    GI.set('cp-table', GI.tableHTML([{ label: 'Season' }, { label: 'Team' }, { label: '4th downs', align: 'right' }, { label: 'Went', align: 'right' }, { label: 'Go rate', align: 'right' }, { label: 'League would', align: 'right' }, { label: 'GOE', align: 'right' }, { label: 'Went when model said go', align: 'right' }, { label: 'Agree', align: 'right' }, { label: 'WP lost', align: 'right' }],
      mine.slice().reverse().map(r => [{ html: '<b>' + r.season + '</b>', v: r.season }, { html: String(r.team || '').split('/').filter(Boolean).map(t => GI.teamChip(t, r.season)).join(' ') || '—', v: r.team }, { v: r.n }, { v: r.go }, { html: GI.pct(r.go_rate, 1), v: r.go_rate }, { html: GI.pct(r.go_exp, 1), v: r.go_exp },
        { html: isNum(r.goe) ? GI.ptsEdge(r.goe * 100, 1) : '—', v: r.goe }, { html: isNum(r.go_when) ? GI.pct(r.go_when, 0) : '—', v: r.go_when }, { html: GI.pct(r.agree, 0), v: r.agree }, { html: isNum(r.lost) ? GI.num(r.lost * 100, 1) : '—', v: r.lost }])));
    GI.sortable(document.getElementById('cp-table'));
    if (plays.length) GI.F.table(document.getElementById('cp-plays'), plays.sort((a, b) => (isNum(b.lost) ? b.lost : -1) - (isNum(a.lost) ? a.lost : -1)), S, { max: 120 });
    else GI.set('cp-plays', GI.muted('No fourth downs for this coach in ' + S + '.'));
  });
});

})(window.GI);
