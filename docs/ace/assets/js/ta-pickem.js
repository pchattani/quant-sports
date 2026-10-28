/* The Quant Ace — the draw pick'em (round 9, Phase 4; in place of Fantasy, which tennis does not have). On a tournament
 * page while the draw is open: pick the winner of every match whose two players are known and the champion; the picks are
 * kept in this browser only (localStorage, no account, nothing sent anywhere) and scored as the results come in, against
 * our model's pick on the same matches (the player we gave the higher chance before the first ball). A finished event
 * shows the final tally if picks were made. TA.pickem.mount(host, T, eventId, cards, sim, done) (done: the champion's id once the event is over). If storage is blocked
 * (private windows), picks last until the page is left.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (TA) {
'use strict';

const esc = s => TA.esc(s);
const isNum = v => typeof v === 'number' && isFinite(v);
const MEM = {};
function key(T, id) { return 'qa-pick-' + T + '-' + id; }
function read(T, id) {
  try { const v = JSON.parse(window.localStorage.getItem(key(T, id)) || 'null'); if (v && typeof v === 'object') return v; } catch (e) { /* blocked or bad */ }
  return MEM[key(T, id)] || { m: {}, champ: '' };
}
function save(T, id, v) {
  MEM[key(T, id)] = v;
  try { window.localStorage.setItem(key(T, id), JSON.stringify(v)); } catch (e) { /* private mode: kept for this visit */ }
}
const real = p => p && !/^tbd:/.test(String(p));

function mount(host, T, id, cards, sim, done) {
  if (!host) return;
  const P = read(T, id);
  P.m = P.m || {};
  const list = Object.keys(cards || {}).map(k => cards[k]).filter(c => c && real(c.p1) && real(c.p2) && ['Q1', 'Q2', 'Q3'].indexOf(c.round) < 0)
    .sort((a, b) => TA.roundIndex(a.round) - TA.roundIndex(b.round) || String(a.date).localeCompare(String(b.date)));
  const open = list.filter(c => TA.matchState(c) === 'pre');
  const scored = list.filter(c => TA.isFinished(c) && c.winner && P.m[c.id]);
  if (done && !scored.length && !P.champ) { host.innerHTML = ''; return; }
  const ours = c => (isNum((c.model || {}).p1) ? (c.model.p1 >= 0.5 ? String(c.p1) : String(c.p2)) : null);
  const youRight = scored.filter(c => String(P.m[c.id]) === String(c.winner)).length;
  const oursN = scored.filter(c => ours(c)), oursRight = oursN.filter(c => ours(c) === String(c.winner)).length;
  const alive = Object.keys(sim || {}).filter(p => isNum(sim[p].p_title) && sim[p].p_title > 0).sort((a, b) => sim[b].p_title - sim[a].p_title);
  const btn = (c, pid) => {
    const on = String(P.m[c.id] || '') === String(pid);
    const p = isNum((c.model || {}).p1) ? (String(pid) === String(c.p1) ? c.model.p1 : 1 - c.model.p1) : null;
    return '<button type="button" class="ta-pk-b' + (on ? ' on' : '') + '" data-m="' + esc(c.id) + '" data-p="' + esc(pid) + '" aria-pressed="' + on + '">' + esc(TA.playerShort(T, pid)) +
      (isNum(p) ? '<small>ours ' + TA.pct(p, 0) + '</small>' : '') + '</button>';
  };
  const rows = open.slice(0, 24).map(c => '<li><span class="ta-pk-r">' + esc(TA.roundLabel(c.round, true)) + '</span>' + btn(c, c.p1) + '<span class="ta-pk-v">v</span>' + btn(c, c.p2) + '</li>').join('');
  const champSel = alive.length ? '<label class="ta-pk-ch"><span>Your champion</span><select class="qk-select" id="pk-champ"><option value="">Pick one…</option>' +
    alive.map(p => '<option value="' + esc(p) + '"' + (String(P.champ) === p ? ' selected' : '') + '>' + esc(TA.playerName(T, p)) + ' (ours ' + TA.pct(sim[p].p_title, 0) + ')</option>').join('') + '</select></label>' : '';
  const champLine = P.champ ? '<p class="ta-pk-note">Your champion: <b>' + esc(TA.playerName(T, P.champ)) + '</b>' + (typeof done === 'string' ? (String(done) === String(P.champ) ? ' ✓ right' : ' ✗ (' + esc(TA.playerName(T, done)) + ' won it)') : '') + '</p>' : '';
  const tally = scored.length ? QK.stats([{ label: 'Your picks right', value: youRight + ' of ' + scored.length, sub: TA.pct(youRight / scored.length, 0) + ' of your finished picks', signal: true },
    { label: 'Our model on the same', value: oursRight + ' of ' + oursN.length, sub: 'the player we gave the higher chance' }]) : '';
  host.innerHTML = '<section class="qk-section ta-pk">' + QK.sectionHead({ kicker: 'Pick’em', title: done ? 'How your picks did' : 'Pick the draw, beat our model', sub: done ? 'Your picks for this draw against what happened, and our model on the same matches.' : 'Tap the winner of each match still to play and pick a champion. We keep score as the results come in, against our model’s pick on the same matches. Saved in this browser only: no account, nothing sent anywhere.' }) +
    (tally ? '<div class="ta-kpis">' + tally + '</div>' : '') +
    (!done ? '<article class="qk-card"><div class="qk-card-body">' + champSel + (rows ? '<ol class="ta-pk-list">' + rows + '</ol>' : '<p class="ta-pk-note">No match with both players known is still to play. Come back when the next round is set.</p>') +
      (open.length > 24 ? '<p class="ta-pk-note">The first 24 matches still to play are listed.</p>' : '') + '<button type="button" class="qk-btn sm" id="pk-clear">Clear my picks</button></div></article>' : champLine) + '</section>';
  host.querySelectorAll('.ta-pk-b').forEach(b => b.addEventListener('click', () => {
    const m = b.getAttribute('data-m'), p = b.getAttribute('data-p');
    if (String(P.m[m] || '') === p) delete P.m[m]; else P.m[m] = p;
    save(T, id, P);
    mount(host, T, id, cards, sim, done);
  }));
  const cs = host.querySelector('#pk-champ');
  if (cs) cs.addEventListener('change', () => { P.champ = cs.value; save(T, id, P); });
  const cl = host.querySelector('#pk-clear');
  if (cl) cl.addEventListener('click', () => { save(T, id, { m: {}, champ: '' }); mount(host, T, id, cards, sim, done); });
}

TA.pickem = { mount: mount };
})(window.TA);
