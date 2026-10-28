/* The Quant Gridiron — the fourth-down centre (#/fourth-downs), in the Lab section.
 * Every fourth down of the season graded by our decision model: situation, choice, recommendation, win
 * probability by option and win probability lost; filters; a field map of every decision; the selected
 * play's options; coach aggressiveness. Also exports GI.F (readers, the play table, the coach table) for
 * the team and coach pages. Reads <S>/fourth_downs.json. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum, first = GI.first;
const MARK = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
const F = {};
F.LAB = { go: 'Go for it', punt: 'Punt', fg: 'Field goal' };
F.COL = { go: '#2fb37b', punt: '#3987e5', fg: '#e3b341' };

F.norm = r => {
  const v = function () { for (let i = 0; i < arguments.length; i++) { const x = r[arguments[i]]; if (x !== undefined && x !== null && x !== '') return x; } return null; };
  const gid = v('game_id', 'gid', 'game');
  const g = GI.parseGameId(gid) || {};
  const wpo = r.wp && typeof r.wp === 'object' ? r.wp : {};
  const wpg = first(v('wp_go', 'go_wp', 'p_go_wp'), wpo.go), wpp = first(v('wp_punt', 'punt_wp'), wpo.punt), wpf = first(v('wp_fg', 'fg_wp', 'wp_kick'), wpo.fg);
  const choice = String(v('choice', 'decision', 'actual', 'call') || '').toLowerCase();
  let rec = String(v('rec', 'recommendation', 'best', 'should') || '').toLowerCase();
  const opts = [['go', wpg], ['punt', wpp], ['fg', wpf]].filter(o => isNum(o[1]));
  if (!rec && opts.length) rec = opts.slice().sort((a, b) => b[1] - a[1])[0][0];
  const norm = c => (/go|run|pass/.test(c) ? 'go' : /punt/.test(c) ? 'punt' : /fg|field|kick/.test(c) ? 'fg' : c);
  const ch = norm(choice), rc = norm(rec);
  let lost = first(v('wp_lost', 'wpl', 'lost', 'cost'));
  if (!isNum(lost) && opts.length) { const best = Math.max.apply(null, opts.map(o => o[1])); const mine = (opts.find(o => o[0] === ch) || [])[1]; if (isNum(mine)) lost = best - mine; }
  if (isNum(lost) && Math.abs(lost) > 1) lost = lost / 100;
  const team = v('team', 'posteam', 'offense');
  return { id: v('play_id', 'id'), gid: gid, season: first(v('season'), g.season), week: first(v('week'), g.week), team: team, opp: v('opp', 'defteam', 'defense') || (g.home && team ? (team === g.home ? g.away : g.home) : null),
    qtr: first(v('qtr', 'quarter')), clock: v('clock', 'time'), diff: first(v('score_diff', 'score_differential', 'diff')), yl: first(v('yl100', 'yardline_100')), dist: first(v('dist', 'ydstogo')),
    choice: ch, rec: rc, wp: { go: wpg, punt: wpp, fg: wpf }, p_conv: first(v('p_conv', 'p_convert')), p_fg: first(v('p_fg', 'fg_p')), lost: lost, grade: v('grade', 'verdict'), coach: v('coach', 'head_coach'),
    desc: v('desc', 'description', 'text'), result: v('result', 'outcome', 'success', 'converted'), go_exp: first(v('go_exp')) };
};
F.playsOf = d => { if (!d || d.ok === false) return []; const src = d.plays || d.fourth_downs || d.decisions || (Array.isArray(d) ? d : ((d.cols || d.fields) && d.rows ? d : null)); return GI.listOf(src).map(F.norm); };
F.grade = p => GI.gradeOf(p.grade, p.lost);
F.gradeChip = p => { const g = F.grade(p); return g.key ? GI.pill(g.label, g.colour) : ''; };
F.sit = p => {
  const q = isNum(p.qtr) ? (p.qtr > 4 ? 'OT' : 'Q' + p.qtr) : '';
  const sc = isNum(p.diff) ? (p.diff > 0 ? 'up ' + p.diff : p.diff < 0 ? 'down ' + -p.diff : 'tied') : '';
  return [q + (p.clock !== null && p.clock !== undefined ? ' ' + GI.fmtClock(p.clock) : ''), sc].filter(Boolean).join(' · ');
};
F.hasModel = plays => plays.some(p => p.rec || isNum(p.lost) || isNum(p.wp.go));
F.choiceTag = c => (c ? '<span class="gi-grade" style="--g:' + (F.COL[c] || 'var(--ink-3)') + '">' + esc(F.LAB[c] || c) + '</span>' : '—');
F.resultText = p => {
  const r = String(p.result === null || p.result === undefined ? '' : p.result).toLowerCase();
  if (!r || r === p.choice) return '<span class="qk-muted">' + (p.choice === 'punt' ? 'punted' : '—') + '</span>';
  if (/^conv|^success|^made|^good|^td|^touchdown|^1$|^true$/.test(r)) return '<span class="gi-up">' + (r === 'made' ? 'Made' : 'Converted') + '</span>';
  if (/^fail|^missed|^blocked|^0$|^false$/.test(r)) return '<span class="gi-down">' + esc(GI.titleCase(r)) + '</span>';
  return esc(GI.titleCase(r));
};
F.wpCell = (p, o) => {
  const v = p.wp[o];
  if (!isNum(v)) return { v: null, html: '<span class="qk-muted">—</span>' };
  const best = Math.max.apply(null, ['go', 'punt', 'fg'].map(x => p.wp[x]).filter(isNum));
  return { v: v, html: (v === best ? '<b>' : '') + (p.choice === o ? '<u>' : '') + GI.pct(v, 1) + (p.choice === o ? '</u>' : '') + (v === best ? '</b>' : '') };
};
/* The play table (Design System 2.0 leaderboard: team marks, the win chance given up as an inline bar).
 * opts {team: false (hide the team column), max, maxHeight, onPick(p)}. */
F.table = (host, plays, S, opts) => {
  const o = opts || {};
  if (!host) return;
  const list = plays.slice(0, o.max || 400);
  if (!list.length) { host.innerHTML = GI.muted('No fourth downs match.'); return; }
  const model = F.hasModel(plays), hasExp = plays.some(p => isNum(p.go_exp));
  const rows = list.map((p, i) => ({ _i: i, p: p, wk: p.week, team: p.team, name: GI.teamAbbr(p.team), sub: p.opp ? 'v ' + GI.teamAbbr(p.opp) : '', sit: (p.qtr || 0) * 10000 - (parseInt(String(p.clock || '').replace(':', ''), 10) || 0),
    down: (p.dist || 0) + (p.yl || 0) / 1000, choice: p.choice, exp: p.go_exp, res: String(p.result || ''), rec: p.rec, go: p.wp.go, punt: p.wp.punt, fg: p.wp.fg, lost: isNum(p.lost) ? p.lost * 100 : null, grade: isNum(p.lost) ? p.lost : -1 }));
  const wp = o2 => ({ key: o2, label: o2 === 'fg' ? 'FG' : GI.titleCase(o2), num: true, fmt: (v, r) => F.wpCell(r.p, o2).html, tip: 'Our win probability if they ' + (o2 === 'go' ? 'go for it' : o2 === 'punt' ? 'punt' : 'kick the field goal') + '; best bold, the choice underlined' });
  const cols = [{ key: 'wk', label: 'Wk', num: true, fmt: (v, r) => (r.p.gid ? '<a class="gi-link" href="' + GI.gameHref(r.p.gid) + '">' + esc(v === null ? '—' : v) + '</a>' : esc(v)) }]
    .concat(o.team === false ? [{ key: 'sub', label: 'Opp', fmt: v => esc(v) }] : [{ key: 'name', label: 'Team', type: 'entity', sub: 'sub', mark: r => MARK(r.team), href: r => GI.teamHref(r.team, S) }])
    .concat([{ key: 'sit', label: 'Situation', fmt: (v, r) => esc(F.sit(r.p)) }, { key: 'down', label: 'Down', fmt: (v, r) => '4th & ' + (isNum(r.p.dist) && isNum(r.p.yl) && r.p.dist >= r.p.yl ? 'Goal' : esc(isNum(r.p.dist) ? r.p.dist : '?')) + ' <span class="qk-muted">' + esc(GI.fieldPos(r.p.yl, r.p.team, r.p.opp)) + '</span>' },
      { key: 'choice', label: 'Choice', fmt: v => F.choiceTag(v) }])
    .concat(hasExp ? [{ key: 'exp', label: 'League goes', num: true, fmt: v => GI.pct(v, 0), tip: 'How often teams go for it in this situation' }] : []).concat([{ key: 'res', label: 'Result', fmt: (v, r) => F.resultText(r.p) }])
    .concat(model ? [{ key: 'rec', label: 'Our call', fmt: v => F.choiceTag(v), tip: 'What our fourth-down model recommends' }, wp('go'), wp('punt'), wp('fg'),
      { key: 'lost', label: 'Win chance lost', type: 'bar', max: 10, fmt: v => (isNum(v) ? GI.num(v, 1) : '—'), tip: 'Win probability given up against the best option, percentage points (bar to 10)' }, { key: 'grade', label: 'Grade', fmt: (v, r) => F.gradeChip(r.p) || '—' }] : []);
  QK.leaderboard(host, { dense: true, maxHeight: o.maxHeight || 560, columns: cols, rows: rows, rowClass: r => 'fd-row fd-i' + r._i });
  if (o.onPick && !host.__fdPick) {
    host.__fdPick = true;
    host.addEventListener('click', ev => { if (ev.target.closest('a, button')) return; const tr = ev.target.closest('tr.fd-row'); if (!tr) return; const m = /fd-i(\d+)/.exec(tr.className); if (m) o.onPick(list[Number(m[1])]); });
  }
  if (o.onPick) host.querySelectorAll('tr.fd-row').forEach(tr => { tr.style.cursor = 'pointer'; });
};
F.coachRow = r => {
  const o = { coach: r.coach || r.name, season: first(r.season), team: r.team || (Array.isArray(r.teams) ? r.teams.join('/') : r.teams) || '', n: first(r.n, r.fourth_downs), go: first(r.go, r.went),
    go_rate: first(r.go_rate), go_exp: first(r.go_exp), goe: first(r.goe), should: first(r.n_rec_go, r.should_go), go_when: first(r.go_when_rec_go, r.go_rate_rec), agree: first(r.agree, r.agree_rate),
    lost: first(r.wp_lost, r.wp_lost_total), lost_per: first(r.wp_lost_per) };
  if (!isNum(o.go_rate) && isNum(o.go) && o.n) o.go_rate = o.go / o.n;
  if (!isNum(o.go) && isNum(o.go_rate) && isNum(o.n)) o.go = Math.round(o.go_rate * o.n);
  if (!isNum(o.lost_per) && isNum(o.lost) && o.n) o.lost_per = o.lost / o.n;
  if (!isNum(o.goe) && isNum(o.go_rate) && isNum(o.go_exp)) o.goe = o.go_rate - o.go_exp;
  return o;
};
F.coachesOf = (d, plays) => {
  const src = d && (d.coaches || d.coach_table);
  let rows = Array.isArray(src) ? src.map(F.coachRow) : GI.listOf(src, 'coach').map(F.coachRow);
  if (!rows.length && plays.length) {
    const by = {};
    plays.forEach(p => { const k = (p.coach || '') + '|' + p.team; const x = by[k] || (by[k] = { coach: p.coach || null, team: p.team, n: 0, go: 0, should: 0, wentWhen: 0, agree: 0, recN: 0, lost: 0, lostAny: false });
      x.n++; if (p.choice === 'go') x.go++; if (p.rec) { x.recN++; if (p.choice === p.rec) x.agree++; } if (p.rec === 'go') { x.should++; if (p.choice === 'go') x.wentWhen++; } if (isNum(p.lost)) { x.lost += p.lost; x.lostAny = true; } });
    rows = Object.keys(by).map(k => { const x = by[k]; return F.coachRow({ coach: x.coach, team: x.team, n: x.n, go: x.go, n_rec_go: x.recN ? x.should : null, go_when_rec_go: x.should ? x.wentWhen / x.should : null, agree: x.recN ? x.agree / x.recN : null, wp_lost: x.lostAny ? x.lost : null }); });
  }
  return rows;
};
F.coachTable = (host, rows, S) => {
  if (!host) return;
  if (!rows.length) { host.innerHTML = GI.muted('No coach table yet.'); return; }
  const hasModel = rows.some(r => isNum(r.should) || isNum(r.lost));
  const R = rows.map(r => Object.assign({ name: r.coach || 'unknown', t0: String(r.team || '').split('/')[0], sub: String(r.team || '').split('/').filter(Boolean).join(' · '), goeP: isNum(r.goe) ? r.goe * 100 : null, lostP: isNum(r.lost) ? r.lost * 100 : null, perP: isNum(r.lost_per) ? r.lost_per * 100 : null }, r));
  QK.leaderboard(host, { dense: true, rank: true, maxHeight: 640, sort: { key: 'goeP', dir: 'desc' }, rowHref: r => (r.coach ? GI.coachHref(r.coach, S) : ''), rows: R,
    columns: [{ key: 'name', label: 'Coach', type: 'entity', sub: 'sub', mark: r => MARK(r.t0), href: r => (r.coach ? GI.coachHref(r.coach, S) : null) }, { key: 'n', label: '4th downs', num: true }, { key: 'go', label: 'Went', num: true },
      { key: 'go_rate', label: 'Go rate', type: 'bar', max: 1, fmt: v => GI.pct(v, 0) }, { key: 'go_exp', label: 'League would', num: true, fmt: v => GI.pct(v, 0), tip: 'Expected go rate in the same situations from a league model' },
      { key: 'goeP', label: 'GOE', num: true, fmt: v => (isNum(v) ? GI.ptsEdge(v, 1) : '—'), tip: 'Go rate over expected, points: aggressiveness against the league' }]
      .concat(hasModel ? [{ key: 'should', label: 'Our model said go', num: true }, { key: 'go_when', label: 'Went when it did', num: true, fmt: v => GI.pct(v, 0) }, { key: 'agree', label: 'Agree', num: true, fmt: v => GI.pct(v, 0) },
        { key: 'lostP', label: 'Win chance lost', num: true, fmt: v => (isNum(v) ? GI.num(v, 1) : '—'), tip: 'Summed, points' }, { key: 'perP', label: 'Per call', num: true, fmt: v => (isNum(v) ? GI.num(v, 2) : '—') }] : []) });
};
F.optionChart = (id, p) => {
  if (!p) return GI.ch.none(id, 'Click a fourth down for its options.');
  const opts = ['go', 'punt', 'fg'].filter(o => isNum(p.wp[o]));
  if (!opts.length) return GI.ch.none(id, 'No option values for this play.');
  return GI.ch.bar(id, { cats: opts.map(o => F.LAB[o] + (p.choice === o ? ' (chosen)' : '') + (p.rec === o ? ' ★' : '')), series: [{ name: 'Win probability', data: opts.map(o => p.wp[o]) }], horizontal: true, labels: true, valName: 'Our win probability', catName: 'Option',
    colors: opts.map(o => F.COL[o]), fmt: v => GI.pct(v, 1), labelWidth: 120, max: Math.min(1, Math.max.apply(null, opts.map(o => p.wp[o])) * 1.2 + 0.05), label: 'Win probability by option' });
};
GI.F = F;

// ── page ──────────────────────────────────────────────────────────────────

const ST = { team: '', week: '', choice: '', rec: '', grade: '', season: null, sel: null };

/* round 9: "Fourth-down calls", one page with two tabs: every decision (this file) and the coaches (coaches.js) */
function headOf(S, tab) {
  return GI.pageHead('Teams · ' + S, 'Fourth-down calls', 'Every fourth down graded by our decision model (go, punt or kick, valued with our own win-probability model), and the coaches behind the calls.') +
    GI.sectionNav('teams', 'fourth') + GI.subnav([[GI.ghref('fourth-downs', S), 'Every decision', 'dec'], [GI.ghref('fourth-downs', S, { tab: 'coaches' }), 'Coaches', 'co']], tab, 'Fourth-down views');
}
GI.route('fourth', function (el, params) {
  const S = Number(params.season);
  const qy = params.query || {};
  if (qy.tab === 'coaches' && GI.coachesPage) return GI.coachesPage(el, params, headOf(S, 'co'));
  if (qy.team) ST.team = String(qy.team).toUpperCase();
  return GI.loadAll([GI.ypath('fourth_downs.json', S)]).then(res => {
    if (!el.isConnected) return;
    const d = res[0];
    const plays = F.playsOf(d), model = F.hasModel(plays);
    const head = headOf(S, 'dec') + QK.note('<b>How the grades work:</b> for every fourth down our model works out the win chance after going for it, punting and kicking. The grade is how much win chance the call gave up against the best option: under 1.5 points is the right call.');
    if (!plays.length) { el.innerHTML = head + GI.notBuilt('The ' + S + ' fourth-down file', d); return; }
    if (ST.season !== S) { ST.season = S; ST.week = ''; ST.sel = null; }
    const teams = Array.from(new Set(plays.map(p => p.team).filter(Boolean))).sort();
    const weeks = Array.from(new Set(plays.map(p => p.week).filter(isNum))).sort((a, b) => a - b);
    el.innerHTML = head + (model ? '' : GI.note('<b>The fourth-down model has not graded this season yet.</b> Until it does, each decision shows how often the league goes for it in that spot; recommendations and grades stay empty rather than guessed.')) +
      '<div id="fd-kpis"></div>' +
      GI.secHead({ kicker: 'Fourth downs', title: 'Every call this season', sub: 'Filter by team, week, choice, our model\'s call or the grade; click a decision for its options.' }) +
      GI.card('Filters', '', '<div class="gi-toolbar">' + GI.field('Team', GI.select('fd-team', [['', 'All teams']].concat(teams.map(t => [t, t + ' · ' + GI.teamName(t)])), ST.team, 'Team')) +
        GI.field('Week', GI.select('fd-week', [['', 'All weeks']].concat(weeks.map(w => [String(w), GI.weekLabel(w, S)])), ST.week, 'Week')) +
        GI.field('Choice', GI.select('fd-choice', [['', 'Any'], ['go', 'Went for it'], ['punt', 'Punted'], ['fg', 'Kicked a field goal']], ST.choice, 'Choice')) +
        (model ? GI.field('Our model said', GI.select('fd-rec', [['', 'Any'], ['go', 'Go for it'], ['punt', 'Punt'], ['fg', 'Field goal']], ST.rec, 'Model said')) +
          GI.field('Grade', GI.select('fd-grade', [['', 'Any'], ['good', 'Right call'], ['close', 'Close call'], ['bad', 'Mistake'], ['disagree', 'Disagreed with the model']], ST.grade, 'Grade')) : '') + '</div>') +
      GI.grid(GI.card('The field', 'every fourth down by field position and distance · colour: ' + (model ? 'the model\'s call' : 'the choice') + ' · ringed: mistakes', GI.chartBox('fd-map', 380, 'Fourth downs on the field'), { span: 7 }) +
        GI.card('Win probability by option', 'the selected play · ★ the model\'s pick', GI.chartBox('fd-opt', 220, 'Options for the selected play') + '<p class="gi-cap" id="fd-opt-n"></p>', { span: 5 })) +
      GI.card('Every decision', '<span id="fd-tsub"></span>', '<div id="fd-table"></div>', { flush: true }) +
      '<p class="gi-cap">Who goes for it, coach by coach, against the league and our model: <a href="' + GI.ghref('fourth-downs', S, { tab: 'coaches' }) + '">the Coaches tab →</a></p>' +
      GI.note('<p>For every fourth down (kneels and the last seconds of a half excluded) our model values <b>go for it</b> (conversion probability, then the win probability after a conversion or a turnover on downs), <b>punt</b> (expected net distance) and <b>field goal</b> (our make probability by distance, kicker, weather and roof), each valued with our win-probability model. <b>WP lost</b> is the best option minus the chosen one: up to 1.5 points is a right call, up to 3 a close call (the model\'s own uncertainty is about that size), beyond that a mistake. <a href="#/methodology/fourth">Methodology →</a></p>');
    const filt = () => plays.filter(p => (!ST.team || p.team === ST.team) && (!ST.week || String(p.week) === ST.week) && (!ST.choice || p.choice === ST.choice) && (!ST.rec || p.rec === ST.rec) &&
      (!ST.grade || (ST.grade === 'disagree' ? p.rec && p.choice !== p.rec : F.grade(p).key === ST.grade)));
    const pick = p => {
      ST.sel = p;
      if (model) F.optionChart('fd-opt', p); else GI.ch.none('fd-opt', p && isNum(p.go_exp) ? 'In this spot the league goes for it ' + GI.pct(p.go_exp, 0) + ' of the time.' : 'Options appear once the model has graded the season.');
      GI.set('fd-opt-n', p ? (p.desc ? '<b>' + esc((p.team || '') + ' v ' + (p.opp || '') + ', ' + GI.weekLabel(p.week, S)) + ':</b> ' + esc(p.desc) + ' ' : '') + (isNum(p.lost) ? 'WP lost ' + GI.num(p.lost * 100, 1) + ' pts. ' : '') + (p.coach ? 'Coach ' + GI.coachLink(p.coach, S) + '. ' : '') + (p.gid ? '<a href="' + GI.gameHref(p.gid) + '">Game centre →</a>' : '') : '');
    };
    const draw = () => {
      const list = filt().sort(model ? ((a, b) => (isNum(b.lost) ? b.lost : -1) - (isNum(a.lost) ? a.lost : -1)) : ((a, b) => String(b.gid).localeCompare(String(a.gid))));
      const n = list.length, go = list.filter(p => p.choice === 'go').length, rec = list.filter(p => p.rec === 'go').length;
      const recN = list.filter(p => p.rec).length, agree = list.filter(p => p.rec && p.choice === p.rec).length, lost = GI.sum(list.map(p => p.lost));
      const worst = list.filter(p => isNum(p.lost)).sort((a, b) => b.lost - a.lost)[0];
      GI.set('fd-kpis', GI.kpis([GI.kpi('Fourth downs', GI.int(n), n !== plays.length ? 'of ' + GI.int(plays.length) + ' this season' : 'this season'),
        GI.kpi('Went for it', n ? GI.pct(go / n, 0) : '—', GI.int(go) + ' times' + (model ? ' · model said go ' + GI.int(rec) : '')),
        model ? GI.kpi('Agreed with our model', recN ? GI.pct(agree / recN, 0) : '—', recN ? GI.int(agree) + ' of ' + GI.int(recN) + ' calls matched the model’s pick; ' + GI.int(list.filter(p => p.rec === 'go' && p.choice !== 'go').length) + ' times it said go and they kicked' : '') : '',
        model ? GI.kpi('Win chance given away', GI.num(lost * 100, 1), 'percentage points, summed over these decisions', { unit: 'pts', signal: true }) : '',
        worst ? GI.kpi('Costliest call', GI.num(worst.lost * 100, 1),  esc((worst.team || '') + ' ' + GI.weekLabel(worst.week, S, true) + ': ' + (F.LAB[worst.choice] || worst.choice) + ' on 4th & ' + (worst.dist || '?')), { unit: 'pts', href: worst.gid ? GI.gameHref(worst.gid) : null }) : '']));
      F.table(document.getElementById('fd-table'), list, S, { onPick: pick, max: 500 });
      GI.set('fd-tsub', n + ' decisions' + (n > 500 ? ' (first 500)' : '') + ' · ' + (model ? 'sorted by win probability lost; best option bold, the choice underlined' : 'newest first') + ' · click a row for its options');
      const pts = list.filter(p => isNum(p.yl) && isNum(p.dist));
      if (pts.length) GI.ch.mount('fd-map', T => { const xa = GI.ch.ax(T, { min: 0, max: 100, inverse: true, interval: 10 }), ya = GI.ch.ax(T, { min: 0, max: 16, interval: 2 });
        /* the legend on its own row, the y title under it (it was clipped by the legend) */
        const gB = 8 + QKC.nameAxis(xa, 'Yards to the end zone', 'bottom'), gT = 34 + QKC.nameAxis(ya, 'Yards to go (capped at 15)', 'side');
        return {
        grid: { left: 8, right: 14, top: gT, bottom: gB, containLabel: true },
        legend: GI.ch.legend(T, { data: ['go', 'punt', 'fg'].map(x => F.LAB[x]) , icon: 'circle', itemWidth: 9, itemHeight: 9 }),
        xAxis: xa,
        yAxis: ya,
        tooltip: GI.ch.tip(T, { formatter: q => { const p = q.data.p; return GI.ch.thead(esc((p.team || '') + ' ' + GI.weekLabel(p.week, S, true) + ': 4th & ' + p.dist + ' at ' + GI.fieldPos(p.yl, p.team, p.opp))) + GI.ch.trow(F.COL[p.choice], 'Did', F.LAB[p.choice] || p.choice) + (p.rec ? GI.ch.trow(F.COL[p.rec], 'Model', F.LAB[p.rec]) : '') + (isNum(p.lost) ? GI.ch.trow(T.ink3, 'WP lost', GI.num(p.lost * 100, 1) + ' pts') : ''); } }),
        series: ['go', 'punt', 'fg'].map(rc => ({ type: 'scatter', name: F.LAB[rc], symbolSize: 8, itemStyle: { color: F.COL[rc], opacity: 0.8 },
          data: pts.filter(p => (model ? p.rec : p.choice) === rc).map(p => ({ value: [p.yl, Math.min(p.dist, 15) + (((p.id || 0) % 7) - 3) * 0.05], p: p, itemStyle: F.grade(p).key === 'bad' ? { borderColor: GI.BAD, borderWidth: 2.5 } : undefined })) }))
      }; }, 'Fourth downs on the field', { onClick: q => { if (q.data && q.data.p) pick(q.data.p); } });
      else GI.ch.none('fd-map', 'No field positions in this selection.');
      if (!ST.sel || list.indexOf(ST.sel) < 0) pick(list[0] || null); else pick(ST.sel);
    };
    ['team', 'week', 'choice', 'rec', 'grade'].forEach(x => { const n = document.getElementById('fd-' + x); if (n) n.addEventListener('change', () => { ST[x] = n.value; draw(); }); });
    draw();
  });
});

})(window.GI);
