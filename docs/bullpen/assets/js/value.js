/* The Quant Bullpen — player value (#/<L>/value), the trade simulator (#/<L>/trade) and the team pages' "Strengths and
 * needs" (BP.valueTeam(host, L, S, tid), called by teams.js and npb.js).
 *
 * Value: the leaderboard (WAR this season, the rate per 600 PA / 700 BF, the percentile, last season, next season's
 * projection, the components behind it) with level, kind, club, position and sample filters, valuation v2 (MLB: the next
 * five seasons with bands, injured-list risk and wins over the median starter; Triple-A: the prospect model's value), and
 * the best at each position (C 1B 2B 3B SS LF CF RF DH SP RP).
 * Trade: two clubs and the players moving each way; per club the value in and out, the depth chart after the trade
 * (the same allocation as oddsmarkets/baseball/analytics/trade.allocate: positions by scarcity, the best available
 * eligible player by projected value, 80% caps at catcher and 95% elsewhere, a fifth of the starts per starter, a
 * seventh of the relief work per reliever, each scaled by the player's expected playing time, the rest at replacement
 * level), the change in wins and in the postseason,
 * division and title odds read off each club's sensitivity curve (the season simulation re-run at seven rating
 * shifts; linear interpolation in expected wins), age and next seasons, a verdict, and the state in the URL:
 * #/<L>/trade?a=<tid>&b=<tid>&ao=<pid,pid>&bo=<pid,pid>.
 *
 * Data: data/<L>/<S>/value.json, data/<L>/<S>/value/<tid>.json, data/<L>/<S>/trade.json (PAYLOADS.md, "Value and
 * trade"). No optional chaining or nullish coalescing (older browsers). */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const POS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'SP', 'RP'];
const ORDER = ['C', 'SS', 'CF', '2B', '3B', 'RF', 'LF', '1B', 'DH', 'SP', 'RP'];
const GRADE_CLS = { A: 'vg-a', B: 'vg-b', C: 'vg-c', D: 'vg-d', F: 'vg-f' };
const CUR = { mlb: 'Bullpen WAR', aaa: 'Bullpen WAR', npb: 'WAR-lite' };
const V = { kind: 'H', lg: '', team: '', pos: '', min: null, q: '', L: '', S: null };

function Lof(params) { const l = (params && params.level) || BP.state.level || 'mlb'; return ['mlb', 'aaa', 'npb'].indexOf(l) >= 0 ? l : 'mlb'; }
function Sof(params, L) { return Number((params && params.season) || BP.currentSeason(L)); }
function y(L, S, f) { return L + '/' + S + '/' + f; }
function n1(v) { return isNum(v) ? Number(v).toFixed(1) : '—'; }
function s1(v) { return isNum(v) ? BP.signed(v, 1) : '—'; }
function phref(L, pid, S, kind) {
  if (L === 'npb') return BP.href('player/' + encodeURIComponent(pid), L, S);
  return BP.href((kind === 'P' ? 'pitcher/' : 'hitter/') + encodeURIComponent(pid), L, S);
}
function plink(L, pid, name, S, kind) { return pid ? '<a class="ply-link" href="' + phref(L, pid, S, kind) + '">' + esc(name || pid) + '</a>' : esc(name || '—'); }
function tlink(L, tid, S) { return BP.teamLink(tid, { level: L, season: S, abbr: true }); }
function gradeChip(g) { return g ? '<span class="vg ' + (GRADE_CLS[g] || '') + '">' + esc(g) + '</span>' : '—'; }
function learnTeams(d) { const T = (d && d.teams) || {}; Object.keys(T).forEach(t => { if (!BP.TEAMS[t] && T[t] && T[t].name) BP.TEAMS[t] = Object.assign({}, T[t]); }); }

// ── the value page ──────────────────────────────────────────────────────────

function valuePage(el, params) {
  const L = Lof(params), S = Sof(params, L);
  el.innerHTML = BP.muted('Loading…');
  return BP.load(y(L, S, 'value.json')).then(d => {
    if (!el.isConnected) return;
    const head = BP.pageHead('Player value', BP.levelName(L) + ' ' + S + ' · ' + esc(CUR[L] || 'WAR') + ' · the leaderboard and the best at each position',
      '<a href="' + BP.href('trade', L, S) + '">Trade simulator →</a>');
    if (!BP.ok(d)) { el.innerHTML = head + BP.notBuilt('The value file for ' + BP.levelName(L) + ' ' + S, d); return; }
    if (V.L !== L || V.S !== S) { V.L = L; V.S = S; V.min = null; V.team = ''; V.pos = ''; V.lg = ''; }
    const F = {};
    (d.fields || []).forEach((f, i) => { F[f] = i; });
    const rows = d.rows || [];
    const fl = d.floors || { H: 100, P: 80 };
    if (V.min === null) V.min = fl[V.kind] || 100;
    const teams = Array.from(new Set(rows.map(r => r[F.team]).filter(Boolean))).sort((a, b) => BP.teamAbbr(a).localeCompare(BP.teamAbbr(b)));
    const lgOf = t => (BP.teamInfo(t) || {}).league || '';
    const leagues = Array.from(new Set(teams.map(lgOf).filter(Boolean))).sort();
    const v2box = (d.valuation || d.prospects) ? '<div class="card"><div class="card-header" id="val-v2-h"></div><div id="val-v2" class="val-v2"></div><div class="npb-note" id="val-v2-note"></div></div>' : '';
    let h = head + '<div class="card"><div class="card-header">Leaderboard <span class="card-sub" id="val-sub"></span></div>' +
      '<div class="val-controls"><span class="tgl" id="val-kind">' + BP.toggles([{ key: 'H', label: 'Hitters' }, { key: 'P', label: 'Pitchers' }], V.kind) + '</span>' +
      (leagues.length > 1 ? '<label>League <select id="val-lg"><option value="">All</option>' + leagues.map(g => '<option value="' + esc(g) + '"' + (g === V.lg ? ' selected' : '') + '>' + esc(g) + '</option>').join('') + '</select></label>' : '') +
      '<label>Club <select id="val-team"><option value="">All</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === V.team ? ' selected' : '') + '>' + esc(BP.teamAbbr(t) + ' · ' + BP.teamShort(t)) + '</option>').join('') + '</select></label>' +
      '<label>Position <select id="val-pos"><option value="">All</option></select></label>' +
      '<label>Min <span id="val-min-u"></span> <span id="val-min-v"></span><input id="val-min" type="range" min="0" max="700" step="10"></label>' +
      '<label>Find <input id="val-q" type="search" placeholder="player…" value="' + esc(V.q) + '"></label></div>' +
      '<div id="val-table"></div><div class="npb-note" id="val-note"></div></div>';
    h += v2box;
    h += '<div class="card"><div class="card-header">Best at each position <span class="card-sub">Players whose primary position it is (most games there; pitchers by role), at least half the leaderboard floor; the percentile is within the position.</span></div><div class="val-best" id="val-best"></div></div>';
    el.innerHTML = h;
    const $ = id => document.getElementById(id);
    const posOpts = () => { $('val-pos').innerHTML = '<option value="">All</option>' + POS.filter(p => (V.kind === 'P') === (p === 'SP' || p === 'RP')).map(p => '<option value="' + p + '"' + (p === V.pos ? ' selected' : '') + '>' + p + '</option>').join(''); };
    const draw = () => {
      posOpts();
      $('val-min').value = V.min; $('val-min-v').textContent = V.min; $('val-min-u').textContent = V.kind === 'P' ? 'BF' : 'PA';
      const q = V.q.trim().toLowerCase();
      const sel = rows.filter(r => r[F.kind] === V.kind && (r[F.n] || 0) >= V.min && (!V.team || r[F.team] === V.team) && (!V.lg || lgOf(r[F.team]) === V.lg) &&
        (!V.pos || r[F.pos] === V.pos || (r[F.elig] || []).indexOf(V.pos) >= 0) && (!q || String(r[F.name] || '').toLowerCase().indexOf(q) >= 0))
        .sort((a, b) => (b[F.war] || 0) - (a[F.war] || 0));
      $('val-sub').textContent = sel.length + (V.kind === 'P' ? ' pitchers' : ' hitters') + ' · ' + (d.units || {})[V.kind];
      const cols = [{ label: '#', sortable: false }, { label: V.kind === 'P' ? 'Pitcher' : 'Hitter' }, { label: 'Club' }, { label: 'Pos' }, { label: 'Age', align: 'right' },
        { label: V.kind === 'P' ? 'BF' : 'PA', align: 'right' }, { label: 'WAR', align: 'right' }, { label: V.kind === 'P' ? '/700 BF' : '/600 PA', align: 'right', title: 'WAR rate' },
        { label: 'Pct', align: 'right', title: 'Percentile of WAR among qualified players of the same kind' }, { label: 'Last season', align: 'right' }, { label: 'Δ', align: 'right' },
        { label: 'Next season', align: 'right', title: 'Projected WAR next season (Marcel-style rate x playing time)' }, { label: 'Why', title: 'The components behind the value' }];
      const body = sel.slice(0, 400).map((r, i) => {
        const dd = isNum(r[F.war]) && isNum(r[F.war_prev]) ? r[F.war] - r[F.war_prev] : null;
        const elig = (r[F.elig] || []).filter(p => p !== r[F.pos]);
        return [{ v: i + 1, cls: 'pos-cell' }, { v: r[F.name], html: plink(L, r[F.pid], r[F.name], S, r[F.kind]) }, { v: BP.teamAbbr(r[F.team]), html: tlink(L, r[F.team], S) },
          { v: r[F.pos], html: esc(r[F.pos] || '—') + (elig.length ? ' <span class="muted-inline">' + esc(elig.join(' ')) + '</span>' : '') },
          { v: r[F.age], html: isNum(r[F.age]) ? n1(r[F.age]) : '—', align: 'right' }, { v: r[F.n], html: BP.int(r[F.n]), align: 'right' },
          { v: r[F.war], html: '<strong>' + s1(r[F.war]) + '</strong>', align: 'right' }, { v: r[F.rate], html: isNum(r[F.rate]) ? BP.signed(r[F.rate], 2) : '—', align: 'right' },
          { v: r[F.pct], html: BP.pctPill(r[F.pct]), align: 'right' }, { v: r[F.war_prev], html: s1(r[F.war_prev]), align: 'right' },
          { v: dd, html: isNum(dd) ? '<span class="' + (dd >= 0 ? 'pos-num' : 'neg-num') + '">' + BP.signed(dd, 1) + '</span>' : '—', align: 'right' },
          { v: r[F.proj], html: s1(r[F.proj]), align: 'right' }, { v: r[F.why], html: '<span class="val-why">' + esc(r[F.why] || '') + '</span>' }];
      });
      $('val-table').innerHTML = BP.tableHTML(cols, body, { compact: true, sticky: true });
      BP.sortable($('val-table'));
      const pj = d.projection || {};
      const vtxt = ['H', 'P'].map(k => { const v = (pj[k] || {}).validation; if (!v) return ''; const r = v.rmse || {};
        return (k === 'H' ? 'Hitters' : 'Pitchers') + ': out-of-sample RMSE ' + BP.num(r.projection, 2) + ' against ' + BP.num(r.last_season, 2) + ' for last season\'s rate and ' + BP.num(r.league_rate, 2) + ' for the league rate (' + esc(v.unit) + ', ' + (v.targets || []).length + ' target seasons, players with ' + v.min_n + '+).'; }).filter(Boolean).join(' ');
      $('val-note').innerHTML = esc((d.notes || []).join(' ')) + (vtxt ? ' Projection check: ' + vtxt : '') + ' Floors: ' + fl.H + ' PA, ' + fl.P + ' BF.';
      if ($('val-v2')) drawV2(d, F, sel, L, S, $);
    };
    const best = d.best || {};
    $('val-best').innerHTML = POS.map(p => {
      const list = best[p] || [];
      return '<div class="val-pos"><div class="val-pos-h">' + esc(p) + '</div>' + (list.length ? '<ol>' + list.map(r => '<li><span class="val-bn">' + plink(L, r[0], r[1], S, (p === 'SP' || p === 'RP') ? 'P' : 'H') + ' ' + tlink(L, r[2], S) + '</span>' +
        '<span class="val-bw"><strong>' + s1(r[3]) + '</strong> <span class="muted-inline">pct ' + (isNum(r[5]) ? Math.round(r[5]) : '—') + '</span></span>' +
        '<div class="val-why">' + esc(r[8] || '') + (r[9] ? ' · ' + esc(r[9]) : '') + '</div></li>').join('') + '</ol>' : BP.muted('No qualified player.')) + '</div>';
    }).join('');
    BP.wireToggles($('val-kind'), 'data-k', k => { V.kind = k; V.pos = ''; V.min = fl[k] || 100; draw(); });
    $('val-team').onchange = e => { V.team = e.target.value; draw(); };
    if ($('val-lg')) $('val-lg').onchange = e => { V.lg = e.target.value; draw(); };
    $('val-pos').onchange = e => { V.pos = e.target.value; draw(); };
    $('val-min').oninput = e => { V.min = parseInt(e.target.value, 10); $('val-min-v').textContent = V.min; };
    $('val-min').onchange = draw;
    let timer = null;
    $('val-q').oninput = e => { V.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 200); };
    draw();
  });
}

// ── valuation v2 (the next five seasons; Triple-A: the prospect model) ──────

function band(lo, hi) { return isNum(lo) && isNum(hi) ? '<span class="muted-inline">' + n1(lo) + ' to ' + n1(hi) + '</span>' : ''; }
function drawV2(d, F, sel, L, S, $) {
  if (d.valuation && F.v5 !== undefined) {
    const vm = d.valuation;
    const list = sel.filter(r => isNum(r[F.v5])).sort((a, b) => b[F.v5] - a[F.v5]).slice(0, 300);
    $('val-v2-h').innerHTML = 'Valuation: the next five seasons <span class="card-sub">Expected WAR next season and over three, with the 80% band of what players with that expectation went on to produce; the five-season value (discounted 8% a year); injured-list history and risk; wins over the median starter at his position. Same filters as the leaderboard.</span>';
    const rows = list.map(r => {
      const il = r[F.il3] || [];
      return [{ v: r[F.name], html: plink(L, r[F.pid], r[F.name], S, r[F.kind]) }, { v: BP.teamAbbr(r[F.team]), html: tlink(L, r[F.team], S) }, esc(r[F.pos] || ''),
        { v: r[F.age], html: n1(r[F.age]), align: 'right' }, { v: r[F.e1], html: '<strong>' + s1(r[F.e1]) + '</strong> ' + band(r[F.lo1], r[F.hi1]), align: 'right' },
        { v: r[F.e3], html: s1(r[F.e3]) + ' ' + band(r[F.lo3], r[F.hi3]), align: 'right' }, { v: r[F.v5], html: '<strong>' + s1(r[F.v5]) + '</strong>', align: 'right' },
        { v: r[F.over_line], html: isNum(r[F.over_line]) ? BP.signed(r[F.over_line], 1) : '—', align: 'right' },
        { v: (il[0] || 0) + (il[1] || 0) + (il[2] || 0), html: il.length ? il.map(x => BP.int(x)).join(' / ') : '—', align: 'right' },
        { v: r[F.il_p30], html: isNum(r[F.il_exp]) ? BP.int(r[F.il_exp]) + ' d · ' + BP.pct(r[F.il_p30], 0) : '—', align: 'right' }];
    });
    $('val-v2').innerHTML = BP.tableHTML([{ label: 'Player' }, { label: 'Club' }, { label: 'Pos' }, { label: 'Age', align: 'right' },
      { label: 'Next season', align: 'right', title: 'Expected WAR next season and its 80% band' }, { label: '3 seasons', align: 'right', title: 'Expected WAR over the next three seasons and its 80% band' },
      { label: 'Value (5 yrs)', align: 'right', title: 'Expected WAR over five seasons, discounted 8% a year' },
      { label: 'v median starter', align: 'right', title: 'Projected full-season wins at his position minus the median starter there (the 15th best)' },
      { label: 'IL days', align: 'right', title: 'Days on the injured list: two seasons ago / last season / this season' },
      { label: 'IL risk', align: 'right', title: 'Expected injured-list days next season and the chance of 30 or more' }], rows, { compact: true, sticky: true });
    BP.sortable($('val-v2'));
    const pos = vm.positions || {};
    const cov = (vm.band_fit || {}).coverage || {};
    const ilv = vm.il_fit || {};
    const lines = Object.keys(pos).filter(p => isNum((pos[p] || {}).delta)).map(p => p + ' ' + n1(pos[p].line) + (pos[p].delta > 0 ? ' (scarce, ' + BP.signed(pos[p].delta, 1) + ')' : '')).join(', ');
    const ivh = (ilv.H || {}).validation, ivp = (ilv.P || {}).validation;
    $('val-v2-note').innerHTML = esc((vm.notes || []).join(' ')) + ' Median-starter lines (full-season wins): ' + esc(lines) + '.' +
      (cov.H1 ? ' Band check (out of sample): ' + BP.pct(cov.H1.rate, 0) + ' of hitters and ' + BP.pct((cov.P1 || {}).rate, 0) + ' of pitchers landed inside next season\'s 80% band; ' + BP.pct((cov.H3 || {}).rate, 0) + ' and ' + BP.pct((cov.P3 || {}).rate, 0) + ' inside the three-season band.' : '') +
      (ivh && ivp ? ' Injured-list model: mean absolute error ' + n1(ivh.mae_model) + ' days against ' + n1(ivh.mae_mean) + ' for the league mean (hitters), ' + n1(ivp.mae_model) + ' against ' + n1(ivp.mae_mean) + ' (pitchers); it did not improve playing-time projections walk-forward, so it is shown as risk and not used in them.' : '');
  } else if (d.prospects && F.p_value !== undefined) {
    const LV = { aaa: 'Triple-A', aa: 'Double-A', hia: 'High-A', a: 'Single-A' };
    const list = sel.filter(r => isNum(r[F.p_value])).sort((a, b) => b[F.p_value] - a[F.p_value]).slice(0, 200);
    $('val-v2-h').innerHTML = 'Prospect value <span class="card-sub">Expected MLB WAR over the next four seasons (discounted) from the season\'s minor-league line at his highest level; the same filters as the leaderboard.</span>';
    $('val-v2').innerHTML = BP.tableHTML([{ label: 'Player' }, { label: 'Club' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'Line' }, { label: 'Performance z', align: 'right' }, { label: 'Expected MLB WAR', align: 'right' }],
      list.map(r => [{ v: r[F.name], html: plink(L, r[F.pid], r[F.name], S, r[F.kind]) }, { v: BP.teamAbbr(r[F.team]), html: tlink(L, r[F.team], S) }, esc(r[F.pos] || ''),
        { v: r[F.age], html: n1(r[F.age]), align: 'right' }, esc(LV[r[F.p_level]] || r[F.p_level] || ''), { v: r[F.p_z], html: isNum(r[F.p_z]) ? BP.signed(r[F.p_z], 1) : '—', align: 'right' },
        { v: r[F.p_value], html: '<strong>' + n1(r[F.p_value]) + '</strong>', align: 'right' }]), { compact: true, sticky: true });
    BP.sortable($('val-v2'));
    $('val-v2-note').innerHTML = esc(((d.prospects || {}).notes || []).join(' '));
  }
}

// ── the depth-chart allocation (mirror of analytics/trade.allocate) ─────────

function allocate(players, dh, caps) {
  const c = caps || {};
  const avail = {};
  players.forEach(p => { avail[p.pid] = isNum(p.avail) ? Number(p.avail) : 1.0; });
  const share = {};
  let wins = 0;
  const repl = {};
  ORDER.forEach(pos => {
    if (pos === 'DH' && !dh) return;
    const cap = pos === 'C' ? (c.C || 0.8) : pos === 'SP' ? (c.SP || 0.2) : pos === 'RP' ? (c.RP || 1 / 7) : (c.other || 0.95);
    const cands = players.filter(p => p.ft && isNum(p.ft[pos])).sort((a, b) => (b.ft[pos] - a.ft[pos]) || (String(a.pid) < String(b.pid) ? -1 : 1));
    let left = 1.0;
    cands.forEach(p => {
      if (left <= 1e-9) return;
      const ra = p['avail_' + pos.toLowerCase()];
      const take = (pos === 'SP' || pos === 'RP') ? Math.min(cap * (isNum(ra) ? Number(ra) : 1.0), left) : Math.min(cap, left, avail[p.pid]);
      if (take <= 1e-9) return;
      if (pos !== 'SP' && pos !== 'RP') avail[p.pid] -= take;
      if (!share[p.pid]) share[p.pid] = {};
      share[p.pid][pos] = (share[p.pid][pos] || 0) + take;
      wins += take * p.ft[pos];
      left -= take;
    });
    repl[pos] = Math.max(left, 0);
  });
  return { share: share, wins: wins, repl: repl };
}
function interp(curve, x, key) {
  const xs = (curve && curve.exp_w) || [], ys = (curve && curve[key]) || [];
  if (!xs.length || xs.length !== ys.length) return null;
  const pts = xs.map((v, i) => [v, ys[i]]).sort((a, b) => a[0] - b[0]);
  if (x <= pts[0][0]) return pts[0][1];
  if (x >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    if (x >= a[0] && x <= b[0]) return b[0] === a[0] ? a[1] : a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]);
  }
  return pts[pts.length - 1][1];
}

// ── the trade simulator ─────────────────────────────────────────────────────

function parseIds(s) { return String(s || '').split(',').map(x => x.trim()).filter(Boolean); }
function tradeHash(L, S, st) {
  const q = ['a=' + encodeURIComponent(st.a || ''), 'b=' + encodeURIComponent(st.b || '')];
  if (st.ao.length) q.push('ao=' + st.ao.map(encodeURIComponent).join(','));
  if (st.bo.length) q.push('bo=' + st.bo.map(encodeURIComponent).join(','));
  if (Number(S) !== BP.currentSeason(L)) q.push('s=' + S);
  return '#/' + L + '/trade?' + q.join('&');
}

function tradePage(el, params) {
  const L = Lof(params), S = Sof(params, L);
  const qy = params.query || {};
  const st = { a: qy.a || '', b: qy.b || '', ao: parseIds(qy.ao), bo: parseIds(qy.bo) };
  el.innerHTML = BP.muted('Loading…');
  if (L === 'aaa') { el.innerHTML = BP.pageHead('Trade simulator', 'Triple-A') + BP.muted('The trade simulator covers MLB and NPB; Triple-A rosters turn over too fast for it to mean much. <a href="' + BP.href('trade', 'mlb') + '">MLB trade simulator →</a>'); return null; }
  return BP.load(y(L, S, 'trade.json')).then(ix => {
    if (!el.isConnected) return null;
    const head = BP.pageHead('Trade simulator', BP.levelName(L) + ' ' + S + ' · how a trade stacks up for both clubs', '<a href="' + BP.href('value', L, S) + '">Player value →</a>');
    if (!BP.ok(ix)) { el.innerHTML = head + BP.notBuilt('The trade file for ' + BP.levelName(L) + ' ' + S, ix); return null; }
    learnTeams(ix);
    const T = ix.teams || {};
    const tids = Object.keys(T).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
    const files = [st.a, st.b].map(t => (t && T[t] ? BP.load(y(L, S, 'value/' + t + '.json')) : Promise.resolve(null)));
    return Promise.all(files).then(res => {
      if (!el.isConnected) return;
      const A = BP.ok(res[0]) ? res[0] : null, B = BP.ok(res[1]) ? res[1] : null;
      const sel = (id, v, other) => '<select id="' + id + '"><option value="">Pick a club…</option>' + tids.filter(t => t !== other).map(t => '<option value="' + esc(t) + '"' + (t === v ? ' selected' : '') + '>' + esc(BP.teamName(t)) + '</option>').join('') + '</select>';
      const hz = ix.horizon === 'rest' ? 'the rest of the regular season (' + n1(ix.games_per_club) + ' games a club)' : 'next season (this season\'s schedule replayed with every rating carried forward)';
      let h = head + '<div class="card"><div class="card-header">The trade <span class="card-sub">Pick two clubs, then tick the players each sends. Horizon: ' + esc(hz) + '.</span></div>' +
        '<div class="trd-pick"><div><span class="gq-dot a"></span>' + sel('trd-a', st.a, st.b) + '<div id="trd-ra" class="trd-roster"></div></div>' +
        '<div><span class="gq-dot b"></span>' + sel('trd-b', st.b, st.a) + '<div id="trd-rb" class="trd-roster"></div></div></div>' +
        '<div class="trd-actions"><button type="button" class="tbtn" id="trd-clear">Clear players</button> <button type="button" class="tbtn" id="trd-copy">Copy link</button> <span id="trd-copied" class="muted-inline"></span></div></div>' +
        '<div id="trd-out"></div>' +
        '<div class="npb-note">' + esc(ix.not_checked || '') + ' ' + esc((ix.notes || []).join(' ')) + ' Values: ' + esc(CUR[L] || 'WAR') + '; a full season at a position is ' + BP.int((ix.units || {}).pa) + ' PA in a lineup slot, ' + BP.int((ix.units || {}).sp) + ' BF for a rotation and ' + BP.int((ix.units || {}).rp) + ' for a bullpen.</div>';
      el.innerHTML = h;
      const $ = id => document.getElementById(id);
      const go = () => { location.hash = tradeHash(L, S, st); };
      $('trd-a').onchange = e => { st.a = e.target.value; st.ao = []; go(); };
      $('trd-b').onchange = e => { st.b = e.target.value; st.bo = []; go(); };
      $('trd-clear').onclick = () => { st.ao = []; st.bo = []; go(); };
      $('trd-copy').onclick = () => {
        const url = location.href.split('#')[0] + tradeHash(L, S, st);
        const done = () => { $('trd-copied').textContent = 'Copied.'; };
        try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, () => { $('trd-copied').textContent = url; }); else $('trd-copied').textContent = url; } catch (e) { $('trd-copied').textContent = url; }
      };
      const rosterBox = (X, side, ids) => {
        if (!X) return BP.muted(side === 'a' ? (st.a ? 'This club\'s file is not available.' : '') : (st.b ? 'This club\'s file is not available.' : ''));
        const R = (X.roster || []).slice().sort((p, q) => ((q.kind === 'H') - (p.kind === 'H')) || ((q.proj || 0) - (p.proj || 0)));
        return '<div class="trd-list">' + R.map(p => '<label class="trd-p' + (ids.indexOf(p.pid) >= 0 ? ' on' : '') + '"><input type="checkbox" data-side="' + side + '" value="' + esc(p.pid) + '"' + (ids.indexOf(p.pid) >= 0 ? ' checked' : '') + '>' +
          '<span class="trd-pn">' + esc(p.name || p.pid) + '</span><span class="trd-pp">' + esc(p.pos || '') + '</span><span class="trd-pw" title="WAR this season · projected next season">' + s1(p.war) + ' · ' + s1(p.proj) + '</span></label>').join('') + '</div>';
      };
      $('trd-ra').innerHTML = rosterBox(A, 'a', st.ao);
      $('trd-rb').innerHTML = rosterBox(B, 'b', st.bo);
      el.querySelectorAll('input[type=checkbox][data-side]').forEach(cb => cb.addEventListener('change', () => {
        const list = cb.dataset.side === 'a' ? st.ao : st.bo;
        const i = list.indexOf(cb.value);
        if (cb.checked && i < 0) list.push(cb.value);
        if (!cb.checked && i >= 0) list.splice(i, 1);
        go();
      }));
      if (!A || !B) { $('trd-out').innerHTML = BP.card('', '', BP.muted('Pick two clubs to start.')); return; }
      $('trd-out').innerHTML = result(L, S, ix, st, A, B);
      BP.sortable($('trd-out'));
    });
  });
}

function sideResult(L, S, ix, tid, X, outIds, inc, Y) {
  const R = X.roster || [];
  const byId = {};
  R.forEach(p => { byId[p.pid] = p; });
  (Y.roster || []).forEach(p => { if (!byId[p.pid]) byId[p.pid] = p; });
  const dh = ix.dh ? ix.dh[tid] !== false : true;
  const before = allocate(R, dh, ix.caps);
  const afterR = R.filter(p => outIds.indexOf(p.pid) < 0).concat(inc);
  const after = allocate(afterR, dh, ix.caps);
  const dWins = after.wins - before.wins;
  const scale = ix.horizon === 'rest' ? (ix.games_per_club || 0) / ({ mlb: 162, npb: 143 }[L] || 162) : 1;
  const dNow = dWins * scale;
  const curve = (ix.curves || {})[tid] || {};
  const base = (ix.base || {})[tid] || {};
  const x0 = isNum(base.exp_w) ? base.exp_w : null;
  const odds = ['p_post', 'p_div', 'p_title'].map(k => {
    const a = isNum(x0) ? interp(curve, x0, k) : null, b = isNum(x0) ? interp(curve, x0 + dNow, k) : null;
    return { k: k, label: (ix.keys || {})[k] || k, a: a, b: b };
  });
  // time lost, in seasons of his role: a position's share for a hitter, a rotation slot (a fifth) for a starter,
  // a bullpen slot (a seventh) for a reliever
  const caps = ix.caps || {};
  const seasonOf = sh => Object.keys(sh).reduce((s, k) => s + sh[k] / (k === 'SP' ? (caps.SP || 0.2) : k === 'RP' ? (caps.RP || 1 / 7) : 1), 0);
  const displaced = [];
  Object.keys(before.share).forEach(pid => {
    if (outIds.indexOf(pid) >= 0) return;
    const a = before.share[pid], b = after.share[pid] || {};
    const lost = seasonOf(a) - seasonOf(b);
    if (lost > 0.01) displaced.push([pid, lost, Object.keys(a).join('/')]);
  });
  const moved = [];
  outIds.forEach(pid => { const p = byId[pid]; if (p) moved.push(['out', p]); });
  inc.forEach(p => { moved.push(['in', p]); });
  const sum = (dir, k) => moved.filter(m => m[0] === dir).reduce((s, m) => s + (isNum(m[1][k]) ? m[1][k] : 0), 0);
  const long3 = sum('in', 'proj3') - sum('out', 'proj3');
  const verdict = (dNow > 0.5 ? 'wins now (' + BP.signed(dNow, 1) + ' wins)' : dNow < -0.5 ? 'weakens now (' + BP.signed(dNow, 1) + ' wins)' : 'about even now (' + BP.signed(dNow, 1) + ' wins)') +
    (long3 > 1 ? '; long-term gain (' + BP.signed(long3, 1) + ' WAR over three seasons)' : long3 < -1 ? '; long-term cost (' + BP.signed(long3, 1) + ' WAR over three seasons)' : '; about even over three seasons (' + BP.signed(long3, 1) + ' WAR)');
  const seen = {};
  const newDepth = afterR.filter(p => { if (!after.share[p.pid] || seen[p.pid]) return false; seen[p.pid] = 1; return true; }).map(p => [p, after.share[p.pid]]);
  return { tid: tid, dWins: dWins, dNow: dNow, odds: odds, displaced: displaced, moved: moved, verdict: verdict, long3: long3, base: base, x0: x0,
    inWar: sum('in', 'war'), outWar: sum('out', 'war'), inProj: sum('in', 'proj'), outProj: sum('out', 'proj'), depth: newDepth, byId: byId, repl: after.repl, rpw: ix.rpw };
}

function result(L, S, ix, st, A, B) {
  const ra = (A.roster || []), rb = (B.roster || []);
  const pick = (R, ids) => R.filter(p => ids.indexOf(p.pid) >= 0);
  const fromA = pick(ra, st.ao), fromB = pick(rb, st.bo);
  if (!fromA.length && !fromB.length) return BP.card('', '', BP.muted('Tick the players each club sends.'));
  const X = sideResult(L, S, ix, st.a, A, st.ao, fromB, B);
  const Y = sideResult(L, S, ix, st.b, B, st.bo, fromA, A);
  const block = (R, other) => {
    const oddsRows = R.odds.map(o => [o.label, { v: o.a, html: isNum(o.a) ? BP.pct(o.a, 1) : '—', align: 'right' }, { v: o.b, html: isNum(o.b) ? BP.pct(o.b, 1) : '—', align: 'right' },
      { v: isNum(o.a) && isNum(o.b) ? o.b - o.a : null, html: isNum(o.a) && isNum(o.b) ? BP.pp(o.b, o.a, 1) : '—', align: 'right' }]);
    const mv = R.moved.map(m => { const p = m[1]; return [{ v: m[0], html: m[0] === 'in' ? '<span class="pos-num">in</span>' : '<span class="neg-num">out</span>' }, { v: p.name, html: plink(L, p.pid, p.name, S, p.kind) },
      esc(p.pos || ''), { v: p.age, html: isNum(p.age) ? n1(p.age) : '—', align: 'right' }, { v: p.war, html: s1(p.war), align: 'right' }, { v: p.proj, html: s1(p.proj), align: 'right' }, { v: p.proj3, html: s1(p.proj3), align: 'right' }]; });
    const disp = R.displaced.length ? R.displaced.sort((a, b) => b[1] - a[1]).map(x => { const p = R.byId[x[0]] || {}; return esc(p.name || x[0]) + ' (' + esc(x[2]) + ', −' + Math.round(100 * x[1]) + '% of a season)'; }).join(', ') : 'nobody';
    const depth = R.depth.slice().sort((a, b) => ORDER.indexOf(Object.keys(a[1])[0]) - ORDER.indexOf(Object.keys(b[1])[0])).map(x => {
      const p = x[0], sh = x[1];
      return esc(p.name || p.pid) + ' <span class="muted-inline">' + Object.keys(sh).map(k => k + ' ' + Math.round(100 * sh[k]) + '%').join(', ') + '</span>';
    }).join(' · ');
    const repl = Object.keys(R.repl || {}).filter(k => R.repl[k] > 0.05).map(k => k + ' ' + Math.round(100 * R.repl[k]) + '%').join(', ');
    return '<div class="card trd-side"><div class="card-header">' + BP.teamLink(R.tid, { level: L, season: S }) + '</div>' +
      '<div class="trd-verdict"><strong>' + esc(BP.teamShort(R.tid)) + ':</strong> ' + esc(R.verdict) + '.</div>' +
      '<div class="kpi-grid">' + BP.statTile('Value in / out', s1(R.inWar) + ' / ' + s1(R.outWar), 'WAR this season') + BP.statTile('Next season', s1(R.inProj - R.outProj), 'projected WAR in minus out') +
      BP.statTile('Depth chart', BP.signed(R.dWins, 1), 'wins over a full season, position by position') + BP.statTile('Rating', BP.signed(R.dWins / ({ mlb: 162, npb: 143 }[L] || 162) * (R.rpw || 10), 2), 'runs a game (' + BP.signed(R.dWins * (R.rpw || 10), 0) + ' a season)') + '</div>' +
      '<div class="pad trd-text"><b>Who loses time:</b> ' + disp + '.' + (repl ? ' <b>Left at replacement level:</b> ' + esc(repl) + '.' : '') + '</div>' +
      BP.tableHTML([{ label: 'Our chance' }, { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, { label: 'Change', align: 'right' }], oddsRows, { compact: true }) +
      '<div class="pad trd-text muted-inline">Expected wins ' + n1(R.x0) + ' → ' + n1(isNum(R.x0) ? R.x0 + R.dNow : null) + ' over the horizon.</div>' +
      BP.tableHTML([{ label: '' }, { label: 'Player' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'WAR', align: 'right', title: 'This season' },
        { label: 'Next', align: 'right', title: 'Projected WAR next season' }, { label: '3 seasons', align: 'right', title: 'Projected WAR over the next three seasons, aged' }], mv, { compact: true }) +
      '<details class="trd-depth"><summary>Depth chart after the trade</summary><div class="pad trd-text">' + depth + '</div></details></div>';
  };
  return '<div class="trd-grid">' + block(X, Y) + block(Y, X) + '</div>';
}

// ── the team page's "Strengths and needs" ───────────────────────────────────

function valueTeam(host, L, S, tid) {
  if (!host) return;
  if (Number(S) !== BP.currentSeason(L)) { host.innerHTML = ''; return; }     // built for the current season only
  host.innerHTML = BP.muted('Loading strengths and needs…');
  BP.load(y(L, S, 'value/' + tid + '.json')).then(d => {
    if (!host.isConnected) return;
    if (!BP.ok(d)) { host.innerHTML = BP.card('Strengths and needs', '', BP.notBuilt('The strengths-and-needs file for this club', d)); return; }
    const G = d.grades || [];
    const by = {};
    G.forEach(g => { by[g.pos] = g; });
    const names = g => (g.players || []).map(p => plink(L, p[0], p[1], S, (g.pos === 'SP' || g.pos === 'RP') ? 'P' : 'H') + ' <span class="muted-inline">' + s1(p[3]) + '</span>').join(', ');
    const gradeRows = POS.filter(p => by[p]).map(p => { const g = by[p]; return [{ v: p, html: '<b>' + esc(p) + '</b>' }, { v: g.grade, html: gradeChip(g.grade) },
      { v: g.war, html: s1(g.war), align: 'right' }, { v: g.rank, html: g.ungraded ? '—' : (g.rank || '—') + ' of ' + (g.of || '—'), align: 'right' }, { v: g.pct, html: BP.pctPill(g.pct), align: 'right' }, { v: '', html: g.ungraded ? '<span class="muted-inline">' + esc(g.evidence || '') + '</span>' : names(g) }]; });
    const tile = (list, kind) => (list || []).map(p => { const g = by[p] || {}; return '<div class="val-sn ' + kind + '"><div class="val-sn-h">' + gradeChip(g.grade) + ' <b>' + esc(p) + '</b> <span class="muted-inline">' + (g.ungraded ? 'not graded' : s1(g.war) + ' WAR · ' + (g.rank || '—') + ' of ' + (g.of || '—')) + '</span></div><div class="val-sn-b">' + esc(g.evidence || '') + '</div></div>'; }).join('');
    let h = '<div class="card"><div class="card-header">Strengths and needs <span class="card-sub">Every position\'s ' + esc((d.units || {}).war || 'WAR') + ' this season (a player\'s WAR split by his games at each position) against the other clubs: A top fifth … F bottom fifth.</span></div>' +
      '<div class="val-sn-grid"><div><div class="val-sn-t">Strongest</div>' + tile(d.strengths, 'good') + '</div><div><div class="val-sn-t">Weakest</div>' + tile(d.weaknesses, 'bad') + '</div></div>' +
      BP.tableHTML([{ label: 'Pos' }, { label: 'Grade' }, { label: 'WAR', align: 'right' }, { label: 'Rank', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Players (WAR there)' }], gradeRows, { compact: true }) + '</div>';
    const imp = d.improve || {};
    h += '<div class="card"><div class="card-header">Ways to improve <span class="card-sub">' + esc(d.label || '') + '</span></div>' + (d.weaknesses || []).map(p => {
      const list = imp[p] || [];
      const inc = (by[p] || {}).incumbent_ft;
      const g0 = by[p] || {};
      const lead = g0.ungraded ? esc(g0.evidence || '') : (p === 'SP' || p === 'RP' ? 'the club\'s ' + (p === 'SP' ? 'fifth starter' : 'seventh reliever') + ' projects at ' + s1(inc) + ' wins a slot over a full season' : 'the incumbent projects at ' + s1(inc) + ' wins over a full season there');
      return '<div class="val-imp"><div class="val-imp-h"><b>' + esc(p) + '</b> <span class="muted-inline">' + lead + '</span></div>' +
        (list.length ? BP.tableHTML([{ label: 'Candidate' }, { label: 'Club' }, { label: 'Age', align: 'right' }, { label: 'WAR', align: 'right', title: 'This season' },
          { label: 'Projected there', align: 'right', title: 'Wins over a full season at ' + p }, { label: 'Gain', align: 'right', title: 'Wins over the incumbent' }, { label: 'Feasibility (from the data)' }, { label: '' }],
        list.map(c => [{ v: c.name, html: plink(L, c.pid, c.name, S, (p === 'SP' || p === 'RP') ? 'P' : 'H') + ' <span class="muted-inline">' + esc(c.pos || '') + '</span>' }, { v: BP.teamAbbr(c.team), html: tlink(L, c.team, S) },
          { v: c.age, html: isNum(c.age) ? n1(c.age) : '—', align: 'right' }, { v: c.war, html: s1(c.war), align: 'right' }, { v: c.proj_ft, html: s1(c.proj_ft), align: 'right' },
          { v: c.gain, html: '<strong>' + s1(c.gain) + '</strong>', align: 'right' }, { v: (c.hints || []).length, html: esc((c.hints || []).join('; ') || '—') },
          { v: '', html: (L !== 'aaa' ? '<a href="' + tradeHash(L, S, { a: tid, b: c.team, ao: [], bo: [c.pid] }) + '">Trade →</a>' : '') }]), { compact: true }) : BP.muted('No candidate on another club projects more than a third of a win better.')) + '</div>';
    }).join('') + '<div class="npb-note">' + esc(d.free_agents || '') + ' Gains are projected wins over a full season at the position (next season\'s projection: three seasons of WAR rate, regressed and aged), against the player with the most games there.</div></div>';
    host.innerHTML = h;
    BP.sortable(host);
  });
}

BP.valueTeam = valueTeam;
BP.valueAllocate = allocate;
BP.valueInterp = interp;
if (typeof BP.route === 'function') {
  BP.route('value', valuePage);
  BP.route('trade', tradePage);
}
if (typeof BP.routeNpb === 'function') {
  BP.routeNpb('value', valuePage);
  BP.routeNpb('trade', tradePage);
}
})(window.BP || (window.BP = {}));
