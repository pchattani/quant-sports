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
  el.innerHTML = QK.sectionHead({ kicker: 'Award races · MLB', title: 'Who wins the awards', sub: 'Our chance for every candidate from the season so far: a conditional logit on value and the features voters reward, fitted on the 2015–2025 winners. The grey tick is the Kalshi / Polymarket number, de-vigged across the field, for reference.' }) +
    '<p class="bp-note" id="aw-sub"></p><div id="aw-body"></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(L, S, 'awards.json'), k.loadNames()]).then(res => ({ S: S, d: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d, body = document.getElementById('aw-body');
    const A = d && d.ok !== false ? (d.awards || d.races || d) : null;
    const keys = A ? Object.keys(A).filter(x => A[x] && typeof A[x] === 'object' && (A[x].model || A[x].probs || A[x].candidates)) : [];
    if (!keys.length) { body.innerHTML = k.card('Awards', '', k.notBuilt('The ' + S + ' award model', d)); document.getElementById('aw-sub').textContent = ''; return; }
    keys.sort((a, b) => (ORDER.indexOf(a) < 0 ? 99 : ORDER.indexOf(a)) - (ORDER.indexOf(b) < 0 ? 99 : ORDER.indexOf(b)));
    document.getElementById('aw-sub').textContent = keys.length + ' races · ' + S + (d.updated_at ? ' · updated ' + k.fmtDate(d.updated_at, { year: false }) : '');
    let h = '<div class="grid-2 gq-awards">';
    keys.forEach((key, i) => { h += '<div class="qk-card"><div class="qk-card-head"><div><div class="qk-card-title">' + k.esc(awardLabel(key, A[key])) + '</div><div class="qk-card-sub" id="aw-s-' + i + '"></div></div></div><div class="qk-card-body"><div id="aw-c-' + i + '"></div><div id="aw-t-' + i + '" style="margin-top:12px"></div></div></div>'; });
    body.innerHTML = h + '</div>';
    keys.forEach((key, i) => race(L, S, A[key], i));
  });
}

function race(L, S, a, i) {
  const k = K();
  const model = probsOf(a.model || a.probs), market = probsOf(a.market);
  // E: rows [{pid, name, p, value, team}], features = the model's feature names; else {pid: {...}}.
  const feats = Array.isArray(a.rows) ? a.rows.reduce((o, r) => { if (r && r.pid !== undefined) o[String(r.pid)] = Object.assign({}, r, { p: undefined }); return o; }, {}) : (Array.isArray(a.features) ? {} : (a.features || {}));
  (a.vs_market || []).forEach(x => { if (x && x.pid !== undefined && K().isNum(x.market) && market[String(x.pid)] === undefined) market[String(x.pid)] = x.market; });
  (a.candidates || []).forEach(c => { if (c && (c.pid || c.id) && c.name) k.learn(String(c.pid || c.id), { name: c.name }); });
  Object.keys(feats).forEach(pid => { if (feats[pid] && feats[pid].name) k.learn(pid, { name: feats[pid].name, team: feats[pid].team }); });
  const ids = Array.from(new Set(Object.keys(model).concat(Object.keys(market)))).sort((x, y) => (model[y] || 0) - (model[x] || 0) || (market[y] || 0) - (market[x] || 0));
  const top = ids.slice(0, 12);
  const fkeys = Array.from(new Set([].concat.apply([], top.map(pid => Object.keys(feats[pid] || {}).filter(f => k.isNum(feats[pid][f]) && !/^(z_|p$|rank|pid|league|team$)/.test(f)))))).slice(0, 5);
  const pitch = /cy/i.test(a.label || '') || fkeys.some(f => /^(ip|ra9|era)$/.test(f));
  document.getElementById('aw-t-' + i).innerHTML = top.length ? k.table([{ label: 'Candidate' }, { label: 'Our chance', align: 'right' }, { label: 'Market', align: 'right', title: 'Kalshi / Polymarket, de-vigged: a reference' }]
    .concat(fkeys.map(f => ({ label: FEAT[f] || k.titleCase(f), align: 'right' }))),
  top.map(pid => { const f = feats[pid] || {}, m = model[pid], mk = market[pid];
    return [{ v: k.name(pid), html: k.playerLink(L, pid, (f.name || null), S, pitch ? 'pitcher' : null) + (f.team ? ' ' + k.teamChip(L, f.team, S) : '') }, { v: m, html: k.isNum(m) ? '<strong>' + k.pct(m, 1) + '</strong>' : '—' }, { v: mk, html: k.isNum(mk) ? '<span class="qk-muted">' + k.pct(mk, 1) + '</span>' : '—' }]
      .concat(fkeys.map(fk => ({ v: f[fk], html: k.isNum(f[fk]) ? (/win|wpct/.test(fk) ? k.rate3(f[fk]) : /woba/.test(fk) ? k.rate3(f[fk]) : /ra9|era|fip/.test(fk) ? k.num(f[fk], 2) : /value|war/.test(fk) ? k.num(f[fk], 1) : /^ip$/.test(fk) ? k.fmtV(f[fk], 'ip') : k.int(f[fk])) : '—' }))); }), { compact: true })
    : k.muted('No candidates yet.');
  const s = document.getElementById('aw-s-' + i);
  const FN = { value: 'value (WAR)', hr: 'home runs', team: 'team win %', woba: 'wOBA', k: 'strikeouts', ip: 'innings', ra9: 'RA9', pa_ip: 'playing time' };
  if (s) s.innerHTML = (Object.keys(market).length ? 'our chance, the market a grey tick' : 'our chance' + (a.market && a.market.reason ? ' (no market: ' + k.esc(a.market.reason) + ')' : '')) + ' · ' + ids.length + ' candidates' +
    (Array.isArray(a.features) ? ' · weighs ' + a.features.map(f => FN[f] || f).join(', ') : '') + (a.reason ? ' · ' + k.esc(a.reason) : '');
  const node = document.getElementById('aw-c-' + i);
  const bars = top.slice(0, 8);
  if (!bars.length) { node.style.display = 'none'; return; }
  node.innerHTML = QK.chances(bars.map(pid => ({ label: k.name(pid), p: model[pid] || 0, market: k.isNum(market[pid]) ? market[pid] : null, href: BP.playerHref(pid, { level: L, role: pitch ? 'pitcher' : null }) })), { marketName: 'Market (Kalshi / Polymarket)' });
}

if (typeof BP.route === 'function') { BP.route('awards', render); try { BP.route('#/awards', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
