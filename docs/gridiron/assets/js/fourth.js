/* The Quant Gridiron — the fourth-down centre (#/fourth-downs).
 *
 * Every fourth down of the season graded by our decision model: the situation, what the team did,
 * what the model recommended, the win probability of going for it, punting and kicking, and the win
 * probability lost against the best choice. Filters by team, week, choice, recommendation and grade;
 * a field map of every decision; the selected play's win probability by option; and the coach
 * aggressiveness table (how often each head coach went for it against how often the model said to).
 *
 * Data: data/<S>/fourth_downs.json ({"plays": [...] | {cols, rows}, "coaches": [...]}).
 * Also exports GI.fk.F (readers and the play table) for the team and coach pages. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const F = {};

/* A 4th-down row in any of the payload's shapes -> a normalised object. */
F.norm = r => {
  const k = K();
  const v = (...keys) => { for (let i = 0; i < keys.length; i++) { const x = r[keys[i]]; if (x !== undefined && x !== null && x !== '') return x; } return null; };
  const gid = v('game_id', 'gid', 'game');
  const g = k.parseGid(gid);
  const wpg = k.first(v('wp_go', 'go_wp', 'p_go_wp', 'wp_go_for_it')), wpp = k.first(v('wp_punt', 'punt_wp')), wpf = k.first(v('wp_fg', 'fg_wp', 'wp_kick'));
  const choice = String(v('choice', 'decision', 'actual', 'call', 'play_choice') || '').toLowerCase();
  let rec = String(v('rec', 'recommendation', 'model', 'best', 'should') || '').toLowerCase();
  const opts = [['go', wpg], ['punt', wpp], ['fg', wpf]].filter(o => k.isNum(o[1]));
  if (!rec && opts.length) rec = opts.slice().sort((a, b) => b[1] - a[1])[0][0];
  const ch = /go|run|pass/.test(choice) ? 'go' : /punt/.test(choice) ? 'punt' : /fg|field|kick/.test(choice) ? 'fg' : choice;
  const rc = /go|run|pass/.test(rec) ? 'go' : /punt/.test(rec) ? 'punt' : /fg|field|kick/.test(rec) ? 'fg' : rec;
  let lost = k.first(v('wp_lost', 'wpl', 'lost', 'cost'));
  if (!k.isNum(lost) && opts.length) { const best = Math.max.apply(null, opts.map(o => o[1])); const mine = (opts.find(o => o[0] === ch) || [])[1]; if (k.isNum(mine)) lost = best - mine; }
  if (k.isNum(lost) && Math.abs(lost) > 1) lost = lost / 100;
  const team = v('team', 'posteam', 'offense');
  return {
    id: v('play_id', 'id'), gid: gid, season: k.first(v('season'), g.season), week: k.first(v('week'), g.week), team: team, opp: v('opp', 'defteam', 'defense') || (g.home && team ? (team === g.home ? g.away : g.home) : null),
    qtr: k.first(v('qtr', 'quarter', 'q')), clock: v('clock', 'time', 'clock_s', 'quarter_seconds_remaining'), diff: k.first(v('score_diff', 'score_differential', 'diff', 'margin')),
    yl: k.first(v('yl100', 'yardline_100', 'yardline')), dist: k.first(v('dist', 'ydstogo', 'distance', 'togo')), choice: ch, rec: rc,
    wp: { go: wpg, punt: wpp, fg: wpf }, p_conv: k.first(v('p_conv', 'conv_p', 'p_convert', 'go_prob', 'first_down_prob')), p_fg: k.first(v('p_fg', 'fg_p', 'fg_prob', 'fg_make_prob')),
    wpBefore: k.first(v('wp', 'wp_before', 'pre_wp')), lost: lost, grade: v('grade', 'verdict'), coach: v('coach', 'head_coach'), desc: v('desc', 'description', 'text'),
    result: v('result', 'outcome', 'success', 'converted'), go_exp: k.first(v('go_exp')), gtype: v('gtype'), margin: k.first(v('margin_go', 'go_margin', 'edge', 'wp_gap'))
  };
};
F.playsOf = d => { const k = K(); if (!d || d.ok === false) return []; const src = d.plays || d.fourth_downs || d.decisions || (Array.isArray(d) ? d : ((d.cols || d.fields) && d.rows ? d : null)); return k.listOf(src).map(F.norm); };
F.LAB = { go: 'Go for it', punt: 'Punt', fg: 'Field goal' };
F.COL = { go: '#3fb950', punt: '#58a6ff', fg: '#d29922' };
F.grade = p => {
  if (GI.gradeOf) { const g = GI.gradeOf(p.grade, p.lost); if (g && g.key) return g; }
  const a = K().isNum(p.lost) ? Math.abs(p.lost) : null;
  if (a === null) return { key: '', label: '—', colour: '#6e7681' };
  return a <= 0.015 ? { key: 'good', label: 'Right call', colour: '#3fb950' } : a <= 0.03 ? { key: 'close', label: 'Close call', colour: '#d29922' } : { key: 'bad', label: 'Mistake', colour: '#f85149' };
};
F.gradeChip = p => { const g = F.grade(p); return g.key ? '<span class="gf-grade gf-grade-' + g.key + '" style="--gc:' + g.colour + '">' + K().esc(g.label) + '</span>' : ''; };
F.sit = p => {
  const k = K();
  const q = k.isNum(p.qtr) ? (p.qtr > 4 ? 'OT' : 'Q' + p.qtr) : '';
  const clk = p.clock !== null && p.clock !== undefined ? (k.isNum(p.clock) ? k.clock(p.clock) : String(p.clock)) : '';
  const sc = k.isNum(p.diff) ? (p.diff > 0 ? 'up ' + p.diff : p.diff < 0 ? 'down ' + -p.diff : 'tied') : '';
  return [q + (clk ? ' ' + clk : ''), sc].filter(Boolean).join(' · ');
};
F.wpCell = (p, o) => {
  const k = K(), v = p.wp[o];
  if (!k.isNum(v)) return { v: null, html: '<span class="muted-inline">—</span>', align: 'right' };
  const best = Math.max.apply(null, ['go', 'punt', 'fg'].map(x => p.wp[x]).filter(k.isNum));
  return { v: v, html: '<span class="' + (v === best ? 'gf-best' : '') + (p.choice === o ? ' gf-chosen' : '') + '">' + k.pct(v, 1) + '</span>', align: 'right' };
};
F.hasModel = plays => plays.some(p => p.rec || K().isNum(p.lost) || K().isNum(p.wp.go));
F.resultText = p => {
  const r = String(p.result === null || p.result === undefined ? '' : p.result).toLowerCase();
  if (!r || r === p.choice) return '<span class="muted-inline">' + (p.choice === 'punt' ? 'punted' : '—') + '</span>';
  if (/^conv|^success|^made|^good|^td|^touchdown|^1$|^true$/.test(r)) return '<span class="gq-ok">' + K().esc(r === 'made' ? 'Made' : 'Converted') + '</span>';
  if (/^fail|^missed|^blocked|^0$|^false$/.test(r)) return '<span class="gq-no">' + K().esc(K().titleCase(r)) + '</span>';
  return K().esc(K().titleCase(r));
};
/* The play table. opts {team: true (show the team column), max, onPick(p)}. */
F.table = (host, plays, S, opts) => {
  const k = K(), o = opts || {};
  if (!host) return;
  const list = plays.slice(0, o.max || 400);
  if (!list.length) { host.innerHTML = k.muted('No fourth downs match.'); return; }
  const model = o.model !== undefined ? !!o.model : F.hasModel(plays);
  const hasExp = plays.some(p => k.isNum(p.go_exp));
  const cols = [{ label: 'Wk' }].concat(o.team === false ? [] : [{ label: 'Team' }]).concat([{ label: 'Opp' }, { label: 'Situation' }, { label: 'Down', title: 'Distance and field position' }, { label: 'Choice' }])
    .concat(hasExp ? [{ label: 'League goes', align: 'right', title: 'How often teams go for it in this situation (a league model of the decision fitted on the season)' }] : [])
    .concat([{ label: 'Result' }])
    .concat(model ? [{ label: 'Model' }, { label: 'Go', align: 'right', title: 'Win probability if they go for it' }, { label: 'Punt', align: 'right' }, { label: 'FG', align: 'right' }, { label: 'WP lost', align: 'right', title: 'Win probability given up against the best choice (percentage points)' }, { label: 'Grade' }] : []);
  host.innerHTML = k.table(cols, list.map((p, i) => ({ _class: 'gf-4row', cells: [{ v: p.week, html: p.gid ? '<a href="' + k.gameHref(p.gid, S) + '">' + k.esc(p.week === null ? '—' : p.week) + '</a>' : k.esc(p.week) }]
    .concat(o.team === false ? [] : [{ v: p.team, html: k.teamChip(p.team, S) }])
    .concat([{ v: p.opp || '', html: p.opp ? k.teamChip(p.opp, S) : '—' }, { v: (p.qtr || 0) * 1000 - (k.isNum(p.clock) ? p.clock : 0), html: k.esc(F.sit(p)) },
      { v: (p.dist || 0) + (p.yl || 0) / 1000, html: '4th & ' + (k.isNum(p.dist) && k.isNum(p.yl) && p.dist >= p.yl ? 'Goal' : k.esc(k.isNum(p.dist) ? p.dist : '?')) + ' <span class="muted-inline">' + k.yardLine(p.yl, p.team, p.opp) + '</span>' },
      { v: p.choice, html: '<span class="gf-choice" style="--cc:' + (F.COL[p.choice] || '#8b949e') + '">' + k.esc(F.LAB[p.choice] || p.choice || '—') + '</span>' }])
    .concat(hasExp ? [{ v: p.go_exp, html: k.isNum(p.go_exp) ? k.pct(p.go_exp, 0) : '—', align: 'right' }] : [])
    .concat([{ v: String(p.result || ''), html: F.resultText(p) }])
    .concat(model ? [{ v: p.rec, html: '<span class="gf-choice gf-rec" style="--cc:' + (F.COL[p.rec] || '#8b949e') + '">' + k.esc(F.LAB[p.rec] || p.rec || '—') + '</span>' },
      F.wpCell(p, 'go'), F.wpCell(p, 'punt'), F.wpCell(p, 'fg'),
      { v: p.lost, html: k.isNum(p.lost) ? (p.lost > 0.0005 ? k.num(p.lost * 100, 1) : '0.0') : '—', align: 'right' },
      { v: k.isNum(p.lost) ? p.lost : -1, html: F.gradeChip(p) }] : []) })), { compact: true, sticky: true });
  k.sortable(host);
  if (o.onPick) host.querySelectorAll('tbody tr').forEach((tr, i) => tr.addEventListener('click', ev => { if (ev.target.closest('a')) return; host.querySelectorAll('tr.on').forEach(x => x.classList.remove('on')); tr.classList.add('on'); o.onPick(list[Number(tr.dataset.i)]); }));
  host.querySelectorAll('tbody tr').forEach((tr, i) => { tr.dataset.i = String(i); });
};
/* Coach rows from the payload (fourth_downs.json "coaches": {coach, team, n, go, go_rate, go_exp, goe, n_rec_go, go_when_rec_go,
 * agree, wp_lost, wp_lost_per}), else computed from the plays. goe = go rate over a league model of going for it (aggressiveness
 * against the league); go_when = how often he went when our model said go; rec_rate = the share of his fourth downs where it said go. */
F.coachRow = r => {
  const k = K();
  const o = { coach: r.coach || r.name, season: k.first(r.season), team: r.team || (Array.isArray(r.teams) ? r.teams.join('/') : r.teams) || '', n: k.first(r.n, r.fourth_downs, r.decisions), go: k.first(r.go, r.went),
    go_rate: k.first(r.go_rate), go_exp: k.first(r.go_exp), goe: k.first(r.goe, r.go_over_expected), should: k.first(r.n_rec_go, r.should_go, r.rec_go, r.model_go), go_when: k.first(r.go_when_rec_go, r.go_rate_rec),
    agree: k.first(r.agree, r.agree_rate, r.agreement), lost: k.first(r.wp_lost, r.wp_lost_total), lost_per: k.first(r.wp_lost_per), games: k.first(r.games, r.g) };
  if (!k.isNum(o.go_rate) && k.isNum(o.go) && o.n) o.go_rate = o.go / o.n;
  if (!k.isNum(o.go) && k.isNum(o.go_rate) && k.isNum(o.n)) o.go = Math.round(o.go_rate * o.n);
  o.rec_rate = k.isNum(o.should) && o.n ? o.should / o.n : k.first(r.rec_go_rate, r.model_go_rate);
  if (!k.isNum(o.lost_per) && k.isNum(o.lost) && o.n) o.lost_per = o.lost / o.n;
  if (!k.isNum(o.goe) && k.isNum(o.go_rate) && k.isNum(o.go_exp)) o.goe = o.go_rate - o.go_exp;
  return o;
};
F.coachesOf = (d, plays) => {
  const k = K();
  const src = d && (d.coaches || d.coach_table);
  let rows = Array.isArray(src) ? src.map(F.coachRow) : k.listOf(src, 'coach').map(F.coachRow);
  if (!rows.length && plays.length) {
    const by = {};
    plays.forEach(p => { const c = p.coach || ('(' + p.team + ')'); const x = by[c + '|' + p.team] || (by[c + '|' + p.team] = { coach: p.coach || null, team: p.team, n: 0, go: 0, should: 0, wentWhen: 0, agree: 0, recN: 0, lost: 0, lostAny: false, exp: 0, expN: 0 });
      x.n++; if (p.choice === 'go') x.go++; if (p.rec) { x.recN++; if (p.choice === p.rec) x.agree++; } if (p.rec === 'go') { x.should++; if (p.choice === 'go') x.wentWhen++; } if (k.isNum(p.lost)) { x.lost += p.lost; x.lostAny = true; } if (k.isNum(p.go_exp)) { x.exp += p.go_exp; x.expN++; } });
    rows = Object.keys(by).map(c => { const x = by[c]; return F.coachRow({ coach: x.coach, team: x.team, n: x.n, go: x.go, go_exp: x.expN ? x.exp / x.expN : null, n_rec_go: x.recN ? x.should : null, go_when_rec_go: x.should ? x.wentWhen / x.should : null, agree: x.recN ? x.agree / x.recN : null, wp_lost: x.lostAny ? x.lost : null }); });
  }
  return rows;
};
F.coachTable = (host, rows, S, opts) => {
  const k = K(), o = opts || {};
  if (!host) return;
  if (!rows.length) { host.innerHTML = k.muted('No coach table yet.'); return; }
  const hasModel = rows.some(r => k.isNum(r.should) || k.isNum(r.lost));
  host.innerHTML = k.table([{ label: 'Coach' }, { label: 'Team' }, { label: '4th downs', align: 'right' }, { label: 'Went', align: 'right', title: 'Went for it' }, { label: 'Go rate', align: 'right' },
    { label: 'League would', align: 'right', title: 'Expected go rate in the same situations from a league model of going for it (same season)' },
    { label: 'GOE', align: 'right', title: 'Go rate over expected (percentage points): aggressiveness against the league, not against the optimum' }]
    .concat(hasModel ? [{ label: 'Model said go', align: 'right', title: 'Fourth downs where our model recommended going for it' }, { label: 'Went when it did', align: 'right', title: 'Share of those where he went for it' },
      { label: 'Agree', align: 'right', title: 'Share of decisions matching the model' }, { label: 'WP lost', align: 'right', title: 'Win probability given up against the model\'s best choice, summed (percentage points)' }, { label: 'per call', align: 'right', title: 'Average WP lost per fourth down (pp)' }] : []),
  rows.slice().sort((a, b) => (k.isNum(b.goe) ? b.goe : (k.isNum(b.go_rate) ? b.go_rate - 1 : -9)) - (k.isNum(a.goe) ? a.goe : (k.isNum(a.go_rate) ? a.go_rate - 1 : -9))).map(r => ({ _href: r.coach && o.link !== false ? k.coachHref(r.coach, S) : null, cells: [
    { v: r.coach || '', html: r.coach ? k.coachLink(r.coach, S) : '<span class="muted-inline">unknown</span>' }, { v: r.team || '', html: String(r.team || '').split('/').filter(Boolean).map(t => k.teamChip(t, S)).join(' ') || '—' },
    { v: r.n, html: k.int(r.n) }, { v: r.go, html: k.int(r.go) }, { v: r.go_rate, html: k.pct(r.go_rate, 0) }, { v: r.go_exp, html: k.pct(r.go_exp, 0) },
    { v: r.goe, html: k.isNum(r.goe) ? '<span class="' + (r.goe > 0.005 ? 'gq-ok' : r.goe < -0.005 ? 'gq-no' : '') + '">' + k.signed(r.goe * 100, 1) + '</span>' : '—' }]
    .concat(hasModel ? [{ v: r.should, html: k.int(r.should) }, { v: r.go_when, html: k.pct(r.go_when, 0) }, { v: r.agree, html: k.pct(r.agree, 0) },
      { v: r.lost, html: k.isNum(r.lost) ? k.num(r.lost * 100, 1) : '—' }, { v: r.lost_per, html: k.isNum(r.lost_per) ? k.num(r.lost_per * 100, 2) : '—' }] : []) })), { compact: true, sticky: true });
  k.sortable(host);
};
/* Win probability by option for one play (bars), into node. */
F.optionChart = (node, p) => {
  const k = K();
  if (!node) return;
  if (!p) { node.innerHTML = k.muted('Click a fourth down in the table for its options.'); return; }
  const opts = ['go', 'punt', 'fg'].filter(o => k.isNum(p.wp[o]));
  if (!opts.length) { node.innerHTML = k.muted('No option values for this play.'); return; }
  const shell = k.chart('fourthOptions') || k.chart('optionBars');
  if (shell) { try { shell(node, p); return; } catch (e) { /* local */ } }
  k.plot(node, [{ type: 'bar', orientation: 'h', y: opts.map(o => F.LAB[o] + (p.choice === o ? ' (chosen)' : '')), x: opts.map(o => p.wp[o]), marker: { color: opts.map(o => F.COL[o]), line: { color: opts.map(o => (p.choice === o ? '#e6edf3' : 'rgba(0,0,0,0)')), width: 2 } },
    text: opts.map(o => k.pct(p.wp[o], 1) + (o === 'go' && k.isNum(p.p_conv) ? ' · converts ' + k.pct(p.p_conv, 0) : '') + (o === 'fg' && k.isNum(p.p_fg) ? ' · makes ' + k.pct(p.p_fg, 0) : '')), textposition: 'auto', hovertemplate: '%{y}: %{x:.1%}<extra></extra>' }],
    k.layout({ margin: { l: 110, r: 16, t: 34, b: 34 }, title: { text: k.esc((p.team || '') + ' v ' + (p.opp || '') + ', week ' + (p.week || '?') + ': 4th & ' + (p.dist || '?') + ', ' + k.yardLine(p.yl, p.team, p.opp).replace(/<[^>]+>/g, '') + ' · ' + F.sit(p)), font: { size: 11, color: k.C.text2 }, x: 0.02 },
      xaxis: { tickformat: '.0%', range: [0, Math.min(1, Math.max.apply(null, opts.map(o => p.wp[o])) * 1.25 + 0.05)] }, yaxis: { automargin: true, autorange: 'reversed' } }));
};
GI.fk = GI.fk || {};
GI.fk.F = F;

// ── page ───────────────────────────────────────────────────────────────────

const ST = { team: '', week: '', choice: '', rec: '', grade: '', q: '', season: null, sel: null };

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  if (qy.team) ST.team = String(qy.team).toUpperCase();
  el.innerHTML = '<div class="card"><div class="card-header">Fourth downs <span class="card-sub" id="fd-sub">Loading…</span></div><div id="fd-tiles"></div>' +
    '<div class="lab-controls gq-controls"><label>Team<select id="fd-team"><option value="">All teams</option></select></label><label>Week<select id="fd-week"><option value="">All weeks</option></select></label>' +
    '<label>Choice<select id="fd-choice"><option value="">Any</option><option value="go">Went for it</option><option value="punt">Punted</option><option value="fg">Kicked a field goal</option></select></label>' +
    '<label>Model said<select id="fd-rec"><option value="">Any</option><option value="go">Go for it</option><option value="punt">Punt</option><option value="fg">Field goal</option></select></label>' +
    '<label>Grade<select id="fd-grade"><option value="">Any</option><option value="good">Right call</option><option value="close">Close call</option><option value="bad">Mistake</option><option value="disagree">Disagreed with the model</option></select></label>' +
    '<label>Coach<input id="fd-q" class="gq-search" type="search" placeholder="coach…"></label></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">The field <span class="card-sub">Every fourth down by field position and distance; colour is the model\'s call (the team\'s choice until the model grades the season), the symbol what the team did (circle go, square punt, diamond field goal); rings are mistakes. Click a dot.</span></div><div id="fd-map" class="gf-chart"></div></div>' +
    '<div class="card"><div class="card-header">Win probability by option <span class="card-sub">For the selected play: the win probability of each choice, with the conversion and make probabilities behind them.</span></div><div id="fd-opt" class="gf-chart"></div><div class="pg-note gq-note" id="fd-opt-n"></div></div></div>' +
    '<div class="card"><div class="card-header">Every decision <span class="card-sub" id="fd-tsub">Sorted by win probability lost. The best option is bold, the chosen one underlined. Click a row for its options.</span></div><div id="fd-table"></div></div>' +
    '<div class="card"><div class="card-header">Coach aggressiveness <span class="card-sub">How often each head coach went for it against what the league does in the same spots (GOE), how often he went when our model said go, and the win probability his calls gave away. End-of-half and garbage-time fourth downs are left out. Click a coach for his page.</span></div><div id="fd-coaches"></div></div>' +
    '<div class="card"><div class="card-header">How the grades work</div><div class="gq-read"><p>For every fourth down (kneels and the final seconds of a half excluded) the model prices three choices: <strong>go for it</strong> (the conversion probability from distance, field position and the two teams\' strength, then the win probability after a conversion or a turnover on downs), <strong>punt</strong> (expected net distance from the spot) and <strong>field goal</strong> (our make probability by distance, kicker, weather, altitude and roof). Each outcome is valued with our own win-probability model. <strong>WP lost</strong> is the best option\'s win probability minus the chosen one\'s, and each decision gets a letter from it: A up to 0.5 percentage points, B up to 1.5, C up to 3, D up to 6, F beyond. A and B are a <span class="gf-grade gf-grade-good" style="--gc:#3fb950">Right call</span> (at most 1.5 points lost), C a <span class="gf-grade gf-grade-close" style="--gc:#d29922">Close call</span> (more than 1.5, at most 3), D and F a <span class="gf-grade gf-grade-bad" style="--gc:#f85149">Mistake</span> (more than 3). Close calls are genuinely close: the model\'s own uncertainty is about that size. See the <a href="#/methodology/fourth">methodology</a>.</p></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'fourth_downs.json'), k.loadNames()]).then(res => ({ S: S, d: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, $ = k.$;
    const plays = F.playsOf(d);
    const model = F.hasModel(plays);
    if (!model && plays.length) {
      const note = '<div class="card gq-warn"><div class="pad muted-inline"><strong>The fourth-down model has not graded this season yet.</strong> Until it does, this page shows every decision with how often the league goes for it in the same spot (from a league model of the decision fitted on the season), and the recommendations, win probability by option and grades stay empty rather than guessed.</div></div>';
      el.insertAdjacentHTML('afterbegin', note);
      ['fd-rec', 'fd-grade'].forEach(x => { const e = k.$(x); if (e) e.parentNode.style.display = 'none'; });
    }
    if (!plays.length) { k.set('fd-table', k.notBuilt('The ' + S + ' fourth-down file', d)); k.set('fd-sub', ''); k.set('fd-map', ''); k.set('fd-opt', ''); k.set('fd-coaches', ''); return; }
    if (ST.season !== S) { ST.season = S; ST.week = ''; ST.sel = null; }
    const teams = Array.from(new Set(plays.map(p => p.team).filter(Boolean))).sort();
    const weeks = Array.from(new Set(plays.map(p => p.week).filter(k.isNum))).sort((a, b) => a - b);
    $('fd-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '">' + k.esc(t + ' · ' + k.teamName(t)) + '</option>').join('');
    $('fd-week').innerHTML = '<option value="">All weeks</option>' + weeks.map(w => '<option value="' + w + '">' + (k.has('weekLabel') ? k.esc(GI.weekLabel(w, S)) : 'Week ' + w) + '</option>').join('');
    $('fd-team').value = ST.team; $('fd-week').value = ST.week; $('fd-choice').value = ST.choice; $('fd-rec').value = ST.rec; $('fd-grade').value = ST.grade; $('fd-q').value = ST.q;
    const filt = () => plays.filter(p => (!ST.team || p.team === ST.team) && (!ST.week || String(p.week) === ST.week) && (!ST.choice || p.choice === ST.choice) && (!ST.rec || p.rec === ST.rec) &&
      (!ST.grade || (ST.grade === 'disagree' ? p.rec && p.choice !== p.rec : F.grade(p).key === ST.grade)) && (!ST.q || k.fold(p.coach || '').indexOf(k.fold(ST.q)) >= 0));
    const pick = p => { ST.sel = p; if (model) F.optionChart(k.$('fd-opt'), p); else { const n = k.$('fd-opt'); if (n) { n.style.height = 'auto'; n.innerHTML = k.muted('Win probability by option appears here once the model has graded the season.' + (p && k.isNum(p.go_exp) ? ' In this spot the league goes for it ' + k.pct(p.go_exp, 0) + ' of the time; ' + k.esc(p.team || 'the team') + ' chose to ' + (p.choice === 'go' ? 'go for it' : p.choice === 'fg' ? 'kick' : 'punt') + '.' : '')); } } k.set('fd-opt-n', p ? optNote(p, S) : ''); };
    const draw = () => {
      const list = filt().sort(model ? ((a, b) => (k.isNum(b.lost) ? b.lost : -1) - (k.isNum(a.lost) ? a.lost : -1)) : ((a, b) => String(b.gid).localeCompare(String(a.gid)) || (b.id || 0) - (a.id || 0)));
      tiles(list, plays, model);
      F.table(k.$('fd-table'), list, S, { onPick: pick, max: 500 });
      fieldMap(list, S, pick, model);
      if (!ST.sel || list.indexOf(ST.sel) < 0) pick(list[0] || null);
      k.set('fd-sub', list.length + ' of ' + plays.length + ' fourth downs · ' + S + (d.updated_at ? ' · updated ' + k.esc(k.fmtDate(d.updated_at, { year: false })) : ''));
      if (!model) k.set('fd-tsub', 'Newest first' + (list.length > 500 ? ' (first 500 of ' + list.length + ')' : '') + '. "League goes" is how often teams go for it in that situation; a low number on a go is a bold call. Click a header to sort.');
      else k.set('fd-tsub', 'Sorted by win probability lost' + (list.length > 500 ? ' (first 500 of ' + list.length + ')' : '') + '. The best option is bold, the chosen one underlined. Click a row for its options.');
    };
    ['team', 'week', 'choice', 'rec', 'grade'].forEach(x => { $('fd-' + x).onchange = e => { ST[x] = e.target.value; draw(); }; });
    let t = null;
    $('fd-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 200); };
    draw();
    F.coachTable(k.$('fd-coaches'), F.coachesOf(d, plays), S);
  });
}

function optNote(p, S) {
  const k = K();
  const parts = [];
  if (p.desc) parts.push('<strong>Play:</strong> ' + k.esc(p.desc));
  if (k.isNum(p.lost)) parts.push('<strong>WP lost:</strong> ' + k.num(p.lost * 100, 1) + ' pp (' + F.grade(p).label.toLowerCase() + ').');
  if (p.coach) parts.push('Coach: ' + k.coachLink(p.coach, S) + '.');
  if (p.gid) parts.push('<a href="' + k.gameHref(p.gid, S) + '">Game centre →</a>');
  return parts.join(' ');
}

function tiles(list, all, model) {
  const k = K();
  const n = list.length;
  if (!n) { k.set('fd-tiles', ''); return; }
  const go = list.filter(p => p.choice === 'go').length, rec = list.filter(p => p.rec === 'go').length;
  const agree = list.filter(p => p.rec && p.choice === p.rec).length, recN = list.filter(p => p.rec).length;
  const lost = k.sum(list.map(p => p.lost));
  const missed = list.filter(p => p.rec === 'go' && p.choice !== 'go').length;
  const conv = list.filter(p => p.choice === 'go' && p.result !== null && p.result !== undefined);
  const convOk = conv.filter(p => p.result === true || p.result === 1 || /^(conv|success|first|1|true|td|touchdown)/i.test(String(p.result))).length;
  const convN = conv.filter(p => /^(conv|fail|success|first|1|0|true|false|td|touchdown|turnover)/i.test(String(p.result))).length;
  const worst = list.filter(p => k.isNum(p.lost)).sort((a, b) => b.lost - a.lost)[0];
  k.set('fd-tiles', k.tiles([
    k.tile('Fourth downs', k.int(n), n !== all.length ? 'of ' + k.int(all.length) + ' this season' : 'this season'),
    k.tile('Went for it', k.pct(go / n, 0), k.int(go) + ' times' + (model ? ' · model said go ' + k.int(rec) + ' times (' + k.pct(rec / n, 0) + ')' : '')),
    model ? k.tile('Agreed with the model', recN ? k.pct(agree / recN, 0) : '—', k.int(missed) + ' times the model said go and they kicked') : '',
    model ? k.tile('WP given away', k.num(lost * 100, 1) + '<span class="kpi-dim"> pp</span>', 'summed over these decisions') : '',
    !model && list.some(p => k.isNum(p.go_exp)) ? k.tile('League would have gone', k.pct(k.mean(list.map(p => p.go_exp)), 0), 'expected go rate in these situations') : '',
    convN ? k.tile('Conversions', k.pct(convOk / convN, 0), convOk + ' of ' + convN + ' attempts') : '',
    worst ? k.tile('Costliest call', k.num(worst.lost * 100, 1) + '<span class="kpi-dim"> pp</span>', k.esc((worst.team || '') + ' week ' + (worst.week || '?') + ': ' + (F.LAB[worst.choice] || worst.choice) + ' on 4th & ' + (worst.dist || '?'))) : ''
  ]));
}

function fieldMap(list, S, pick, model) {
  const k = K(), node = k.$('fd-map');
  if (!node) return;
  const pts = list.filter(p => k.isNum(p.yl) && k.isNum(p.dist));
  if (!pts.length) { node.innerHTML = k.muted('No field positions in this selection.'); return; }
  const SYM = { go: 'circle', punt: 'square', fg: 'diamond' };
  const traces = ['go', 'punt', 'fg'].map(rc => {
    const ps = pts.filter(p => (model ? p.rec : p.choice) === rc);
    return { type: 'scatter', mode: 'markers', name: (model ? 'Model: ' : '') + F.LAB[rc], x: ps.map(p => p.yl), y: ps.map(p => Math.min(p.dist, 15) + (((p.id || 0) % 7) - 3) * 0.04),
      customdata: ps.map(p => list.indexOf(p)), text: ps.map(p => k.esc((p.team || '') + ' wk ' + (p.week || '?') + ': 4th & ' + p.dist + ' at ' + k.yardLine(p.yl, p.team, p.opp).replace(/<[^>]+>/g, '') + '<br>did: ' + (F.LAB[p.choice] || p.choice) + ' · model: ' + (F.LAB[p.rec] || p.rec) + (k.isNum(p.lost) ? '<br>WP lost ' + k.num(p.lost * 100, 1) + ' pp' : ''))),
      hovertemplate: '%{text}<extra></extra>',
      marker: { size: 9, color: F.COL[rc], opacity: 0.8, symbol: ps.map(p => SYM[p.choice] || 'circle'), line: { color: ps.map(p => (F.grade(p).key === 'bad' ? '#f85149' : '#0d1117')), width: ps.map(p => (F.grade(p).key === 'bad' ? 2.5 : 0.6)) } } };
  }).filter(t => t.x.length);
  k.plot(node, traces, k.layout(Object.assign({ margin: { l: 44, r: 10, t: 30, b: 44 }, xaxis: { title: 'Yards to the end zone (own goal line at 100)', range: [100, 0], dtick: 10 }, yaxis: { title: 'Yards to go (15 = 15+)', range: [0, 16], dtick: 2 },
    shapes: [{ type: 'line', x0: 50, x1: 50, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot' } }, { type: 'rect', x0: 40, x1: 0, yref: 'paper', y0: 0, y1: 1, fillcolor: 'rgba(210,153,34,0.05)', line: { width: 0 }, layer: 'below' }] }, k.legendTop())));
  if (node.on) node.on('plotly_click', ev => { const i = ev.points && ev.points[0] ? ev.points[0].customdata : null; if (K().isNum(i) && list[i]) pick(list[i]); });
}

if (typeof GI.route === 'function') { try { GI.route('fourth', render); GI.route('fourth-downs', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
