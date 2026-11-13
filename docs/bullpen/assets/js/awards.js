/* The Quant Bullpen — awards (#/awards): MVP, Cy Young and Rookie of the Year per league, the
 * model against the prediction markets, with the features the model weighs.
 *
 * The model (models/awards.py) is a conditional logit over each race's candidates,
 * P(i) = exp(β·x_i) / Σ_j exp(β·x_j), with features z-scored within the league-season (MVP:
 * value, home runs, team win %, wOBA; Cy Young: value, strikeouts, innings, RA9; ROY: value and
 * playing time) and β fitted on the 2015–2025 winners with a pull towards default weights.
 *
 * Data: data/<L>/<S>/awards.json ({award: {"label", "model": {pid: p}, "market": {pid: p} | null,
 * "features": {pid: {...}}}} or wrapped in {"awards": {...}}). Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const ORDER = ['al_mvp', 'nl_mvp', 'al_cy', 'nl_cy', 'al_roy', 'nl_roy', 'al_cy_young', 'nl_cy_young', 'al_rookie', 'nl_rookie'];
const NAME = { mvp: 'Most Valuable Player', cy: 'Cy Young', cy_young: 'Cy Young', roy: 'Rookie of the Year', rookie: 'Rookie of the Year' };
const FEAT = { value: 'Value (WAR)', war: 'WAR', hr: 'HR', team_win: 'Team win %', team_wpct: 'Team win %', win_pct: 'Team win %', woba: 'wOBA', k: 'Strikeouts', so: 'Strikeouts', ip: 'IP', ra9: 'RA9', pa_ip: 'Playing time', pa: 'PA', era: 'ERA', fip: 'FIP' };
function awardLabel(key, a) {
  if (a && a.label) return a.label;
  const m = /^(al|nl)_?(.*)$/i.exec(key);
  return m ? m[1].toUpperCase() + ' ' + (NAME[m[2].toLowerCase()] || K().titleCase(m[2])) : K().titleCase(key);
}
function probsOf(x) {
  const k = K();
  if (!x || x.available === false) return {};
  const src = x.probs || x.prices || x.p || x;
  if (Array.isArray(src)) { const o = {}; src.forEach(r => { if (Array.isArray(r)) o[String(r[0])] = r[1]; else if (r) o[String(r.pid || r.id)] = [r.p, r.prob, r.value].find(k.isNum); }); return o; }
  const o = {};
  Object.keys(src || {}).forEach(pid => { const v = src[pid]; if (k.isNum(v)) o[pid] = Number(v); else if (v && typeof v === 'object') { const p = [v.p, v.prob, v.mid].find(k.isNum); if (k.isNum(p)) o[pid] = p; } });
  return o;
}

function render(el, params, state) {
  const k = K();
  const L = 'mlb';   // the award models are MLB only
  el.innerHTML = '<div id="aw-head">' + QK.sectionHead({ kicker: 'Award races · MLB', title: 'Who wins the awards', sub: 'Our chance for every candidate from the season so far: a conditional logit on value and the features voters reward, fitted on the 2015–2025 winners.' }) + '</div>' +
    '<p class="bp-note" id="aw-sub"></p><div id="aw-body"></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(L, S, 'awards.json'), k.loadNames()]).then(res => ({ S: S, d: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, body = document.getElementById('aw-body');
    const A = d && d.ok !== false ? (d.awards || d.races || d) : null;
    const keys = A ? Object.keys(A).filter(x => A[x] && typeof A[x] === 'object' && (A[x].model || A[x].probs || A[x].candidates)) : [];
    if (!keys.length) { body.innerHTML = k.card('Awards', '', k.notBuilt('The ' + S + ' award model', d)); document.getElementById('aw-sub').textContent = ''; histHost(el); return; }
    keys.sort((a, b) => (ORDER.indexOf(a) < 0 ? 99 : ORDER.indexOf(a)) - (ORDER.indexOf(b) < 0 ? 99 : ORDER.indexOf(b)));
    const won = keys.filter(x => A[x].winner && A[x].winner.pid);
    if (won.length) {
      const tops = won.filter(x => A[x].winner.rank === 1).length;
      document.getElementById('aw-head').innerHTML = QK.sectionHead({ kicker: 'Award races · MLB · ' + S, title: won.length === keys.length ? 'Who won the awards' : 'The awards so far',
        sub: 'The BBWAA winners against the chance we gave each candidate before the vote, from the full regular season with a model fitted on the 2015–' + (Number(S) - 1) + ' winners. ' +
          tops + ' of ' + won.length + ' winners were our top pick.' });
    }
    document.getElementById('aw-sub').textContent = keys.length + ' races · ' + S + (won.length ? ' · ' + won.length + ' decided' : '') + (d.updated_at ? ' · updated ' + k.fmtDate(d.updated_at, { year: false }) : '');
    let h = '<div class="grid-2 gq-awards">';
    histHost(el);
    keys.forEach((key, i) => { h += '<div class="qk-card"><div class="qk-card-head"><div><div class="qk-card-title">' + k.esc(awardLabel(key, A[key])) + '</div><div class="qk-card-sub" id="aw-s-' + i + '"></div></div></div><div class="qk-card-body"><div id="aw-c-' + i + '"></div><div id="aw-t-' + i + '" style="margin-top:12px"></div></div></div>'; });
    body.innerHTML = h + '</div>';
    keys.forEach((key, i) => race(L, S, A[key], i));
  });
}

/* Every winner against our pre-vote call (round 9, Phase 4): data/mlb/award_history.json (the award model fitted only on
   earlier seasons' winners, scoring each season's full regular-season lines). A grid of seasons by award: the winner, our
   chance for them, the cell coloured by the chance, a ring where the winner was our top pick. */
function histHost(el) {
  if (el.querySelector('#aw-hist')) return;
  const box = document.createElement('section');
  box.className = 'qk-section';
  box.id = 'aw-hist';
  el.appendChild(box);
  BP.load('mlb/award_history.json').then(ah => {
    if (!box.isConnected || !ah || ah.ok === false) { box.remove(); return; }
    const k = K(), U = BP.ui;
    const seasons = Object.keys(ah.seasons || {}).sort().reverse();
    const keys = Object.keys(ah.labels || {});
    const sm = ah.summary || {};
    const by = sm.by_award || {};
    const cell = r => {
      if (!r) return '<td class="aw-h-c none">—</td>';
      const w = r.winner;
      if (!w) return '<td class="aw-h-c open"><span class="qk-kicker">Our pick</span><b>' + k.esc(r.pick.name || '—') + '</b><span class="num">' + U.pct(r.pick.p) + '</span></td>';
      const p = isNum(w.p) ? w.p : 0;
      return '<td class="aw-h-c' + (w.rank === 1 ? ' hit' : '') + '" style="--cc:' + QK.pctColor(Math.round(100 * p)) + '" title="' + k.esc((w.rank === 1 ? 'Our top pick' : 'Our pick was ' + r.pick.name + ' (' + U.pct(r.pick.p) + '); the winner was our ' + ordinal(w.rank))) + '">' +
        '<b>' + (w.pid ? BP.playerLink(w.pid, { name: w.name, level: 'mlb' }) : k.esc(w.name)) + '</b><span class="num">' + U.pct(p) + (w.rank > 1 ? ' <small>' + ordinal(w.rank) + '</small>' : '') + '</span></td>';
    };
    box.innerHTML = QK.sectionHead({ kicker: 'Our record', title: 'Every winner, and what we said', sub: 'Each season’s winners against the chance we gave them before the vote, from the full regular season and a model fitted only on the seasons before. A volt underline marks a winner who was our top pick; the colour is our chance for the winner.' }) +
      '<div class="bp-kpis">' + QK.stats([
        { label: 'Winners we picked', value: sm.top_pick_won + ' of ' + sm.n, signal: true, sub: 'our top pick won' },
        { label: 'In our top three', value: sm.winner_in_top3 + ' of ' + sm.n, sub: 'the winner was one of our three favourites' },
        { label: 'Our average chance for the winner', value: U.pct(sm.mean_p_winner), sub: 'a coin among 15 candidates would give about 7%' },
        { label: 'By award', value: ['mvp', 'cy', 'roy'].map(a => (by[a] ? by[a].top_pick_won + '/' + by[a].n : '')).join(' · '), sub: 'MVP · Cy Young · Rookie of the Year', text: true }
      ]) + '</div>' +
      '<div class="qk-card"><div class="qk-card-body flush"><div class="qk-table-wrap"><table class="qk-table aw-h"><thead><tr><th>Season</th>' + keys.map(x => '<th>' + k.esc(ah.labels[x]) + '</th>').join('') + '</tr></thead><tbody>' +
      seasons.map(sn => '<tr><th scope="row">' + sn + '</th>' + keys.map(x => cell((ah.seasons[sn] || {})[x])).join('') + '</tr>').join('') + '</tbody></table></div></div></div>' +
      QK.explain(k.esc(ah.method || '') + ' Winners: ' + k.esc(ah.source || '') + '. A blank is a race whose winner was not among the candidates our model scores (2020’s 60-game MVP races fall under its 300 plate-appearance floor).', { title: 'How the calls were made' });
  });
}
function ordinal(n) { const sx = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (sx[(v - 20) % 10] || sx[v] || sx[0]); }
const isNum = v => typeof v === 'number' && isFinite(v);

function race(L, S, a, i) {
  const k = K();
  // v3: our chance only; the market sits on game pages and the Model page
  const model = probsOf(a.model || a.probs), market = {};
  // E: rows [{pid, name, p, value, team}], features = the model's feature names; else {pid: {...}}.
  const feats = Array.isArray(a.rows) ? a.rows.reduce((o, r) => { if (r && r.pid !== undefined) o[String(r.pid)] = Object.assign({}, r, { p: undefined }); return o; }, {}) : (Array.isArray(a.features) ? {} : (a.features || {}));
  (a.candidates || []).forEach(c => { if (c && (c.pid || c.id) && c.name) k.learn(String(c.pid || c.id), { name: c.name }); });
  Object.keys(feats).forEach(pid => { if (feats[pid] && feats[pid].name) k.learn(pid, { name: feats[pid].name, team: feats[pid].team }); });
  const ids = Array.from(new Set(Object.keys(model).concat(Object.keys(market)))).sort((x, y) => (model[y] || 0) - (model[x] || 0) || (market[y] || 0) - (market[x] || 0));
  const top = ids.slice(0, 12);
  const fkeys = Array.from(new Set([].concat.apply([], top.map(pid => Object.keys(feats[pid] || {}).filter(f => k.isNum(feats[pid][f]) && !/^(z_|p$|rank|pid|league|team$)/.test(f)))))).slice(0, 5);
  const pitch = /cy/i.test(a.label || '') || fkeys.some(f => /^(ip|ra9|era)$/.test(f));
  document.getElementById('aw-t-' + i).innerHTML = top.length ? k.table([{ label: 'Candidate' }, { label: 'Our chance', align: 'right' }]
    .concat(fkeys.map(f => ({ label: FEAT[f] || k.titleCase(f), align: 'right' }))),
  top.map(pid => { const f = feats[pid] || {}, m = model[pid];
    return [{ v: k.name(pid), html: k.playerLink(L, pid, (f.name || null), S, pitch ? 'pitcher' : null) + (f.team ? ' ' + k.teamChip(L, f.team, S) : '') }, { v: m, html: k.isNum(m) ? '<strong>' + k.pct(m, 1) + '</strong>' : '—' }]
      .concat(fkeys.map(fk => ({ v: f[fk], html: k.isNum(f[fk]) ? (/win|wpct/.test(fk) ? k.rate3(f[fk]) : /woba/.test(fk) ? k.rate3(f[fk]) : /ra9|era|fip/.test(fk) ? k.num(f[fk], 2) : /value|war/.test(fk) ? k.num(f[fk], 1) : /^ip$/.test(fk) ? k.fmtV(f[fk], 'ip') : k.int(f[fk])) : '—' }))); }), { compact: true })
    : k.muted('No candidates yet.');
  const W = a.winner && a.winner.pid ? a.winner : null, wid = W ? String(W.pid) : null;
  if (W) {
    k.learn(wid, { name: W.name });
    const rk = W.rank === 1 ? 'our top pick' : W.rank ? 'our ' + ordinal(W.rank) + ' pick' : 'not among the candidates we scored';
    const tb = document.getElementById('aw-t-' + i);
    document.getElementById('aw-c-' + i).insertAdjacentHTML('beforebegin', '<div id="aw-w-' + i + '" style="margin:0 0 12px">' + QK.stats([
      { label: 'Winner', value: W.name || k.name(wid), text: true, sub: (W.date ? 'Announced ' + QK.fmt.date(W.date + 'T12:00:00Z') : 'Announced') + ' · ' + rk, href: BP.playerHref(wid, { level: L, role: pitch ? 'pitcher' : null }) },
      { label: 'Our chance before the vote', value: k.isNum(W.p) ? k.pct(W.p, 1) : '—', signal: W.rank === 1,
        sub: W.rank === 1 ? 'The call came in.' : (ids[0] && ids[0] !== wid ? 'Our pick was ' + k.esc(k.name(ids[0])) + ' at ' + k.pct(model[ids[0]] || 0, 1) + '.' : ''), html: true }]) + '</div>');
    tb.querySelectorAll('tbody tr').forEach(tr => { const a0 = tr.querySelector('a[href*="' + wid + '"]'); if (a0) { tr.classList.add('hl'); a0.insertAdjacentHTML('afterend', ' <span class="qk-tag" style="margin-left:6px">Won</span>'); } });
  }
  const s = document.getElementById('aw-s-' + i);
  const FN = { value: 'value (WAR)', hr: 'home runs', team: 'team win %', woba: 'wOBA', k: 'strikeouts', ip: 'innings', ra9: 'RA9', pa_ip: 'playing time' };
  if (s) s.innerHTML = (W ? 'decided · our chance before the vote · ' : 'our chance · ') + ids.length + ' candidates' +
    (Array.isArray(a.features) ? ' · weighs ' + a.features.map(f => FN[f] || f).join(', ') : '') + (a.reason ? ' · ' + k.esc(a.reason) : '');
  const node = document.getElementById('aw-c-' + i);
  const bars = top.slice(0, 8);
  if (!bars.length) { node.style.display = 'none'; return; }
  node.innerHTML = QK.chances(bars.map(pid => ({ label: k.name(pid) + (pid === wid ? ' · won' : ''), p: model[pid] || 0, href: BP.playerHref(pid, { level: L, role: pitch ? 'pitcher' : null }) })));
}

if (typeof BP.route === 'function') { BP.route('awards', render); try { BP.route('#/awards', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
