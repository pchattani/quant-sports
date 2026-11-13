/* The Quant Ace — the tournament page (#/<T>/event/<event_id>).
 *
 *   sweep (12 Nov 2026): the family hero (QK.playerHeader on cobalt, the year outlined, level, surface, dates and draw
 *   as chips), the black strip (the champion against our pre-match chances, our top-rated entrant going in, upsets, the
 *   toughest path; our title favourite while it is in play), "The short version"; then title chances (QK.chances, or
 *   the champion's path once it is over) with "How sure are we?" beside upsets and awards; the draw; the tables.
 *   Also reads <T>/favourites.json (our top-rated entrant going in, Elo before the first ball).
 *
 *   head: level, surface, dates, draw size, status or champion;
 *   the draw: an interactive bracket (click a player to light up their path; the panel below
 *             gives the probability of reaching each round and the likeliest opponents there);
 *             on phones the rounds collapse into a round picker;
 *   our title chances (Design System 2.0 chance bars), with the chance of reaching each round and expected points;
 *   results by round;
 *   ?p=<pid> in the hash preselects a player in the draw; upsets (winners we gave under 40%); draw difficulty (expected
 *   opponents' Elo along the path); awards; past champions;
 *   for an event in progress or about to start: what is at stake in it for the race to the Finals and the year-end
 *   No. 1 (race.json "stakes", drawn by race-shape.js; round 5, 24 Oct 2026).
 *
 * Reads <T>/events/<event_id>.json (PAYLOADS.md) and <T>/history.json for older champions. */
(function (TA) {
'use strict';

const esc = TA.esc;

function awardTiles(T, aw) {
  const keys = Object.keys(aw || {}).filter(k => aw[k]);
  if (!keys.length) return '';
  const label = { upset: 'Biggest upset', comeback: 'Best comeback', dominant: 'Most dominant', clutch: 'Clutch performer', player: 'Player of the tournament',
    excitement: 'Most exciting match', longest: 'Longest match', luck: 'Toughest draw' };
  return '<div class="awards">' + keys.map(k => {
    const a = aw[k];
    const who = a.pid || a.winner || a.player || (Array.isArray(a) ? a[0] : null);
    const val = TA.awardValue(a);
    const why = a.why || a.text || (a.loser ? 'beat ' + TA.playerName(T, a.loser) + (a.round ? ' in the ' + TA.roundLabel(a.round).toLowerCase() : '') : '');
    const mid = a.match || a.mid;
    return '<div class="award"><span class="aw-title">' + esc(label[k] || TA.titleCase(k)) + '</span><span class="aw-who">' + (who ? TA.playerLink(T, who) : '—') + '</span>' +
      (val ? '<span class="aw-val">' + esc(val) + '</span>' : '') + (why ? '<span class="aw-why">' + esc(why) + '</span>' : '') +
      (mid ? '<span class="aw-why">' + TA.matchLink(T, mid, 'Match centre →') + '</span>' : '') + '</div>';
  }).join('') + '</div>';
}

function pathPanel(T, model, sim, pid, cards) {
  if (!pid) return '<div class="path-panel muted-inline">Click any player in the draw to light up their path: the chance of reaching each round, and who they are likeliest to meet there.</div>';
  const steps = TA.charts.pathOdds(model, sim, pid);
  const s = sim[pid] || {};
  let html = '<div class="path-panel"><div class="path-head"><span class="ph-name">' + TA.playerLink(T, pid, { rank: true, country: true }) + '</span>' +
    (TA.isNum(s.p_title) ? '<span class="muted-inline">title ' + TA.pct(s.p_title, 1) + (TA.isNum(s.exp_points) ? ' · ' + TA.num(s.exp_points, 0) + ' expected ranking points' : '') + '</span>' : '') +
    '<a class="muted-inline" href="' + TA.h2hHref(T, pid) + '">head to head →</a></div><div class="path-steps">';
  html += steps.map(st => {
    const m = st.match;
    const fin = m.winner && !m.bye && (m.a === pid || m.b === pid);
    const won = fin && m.winner === pid, lost = fin && m.winner !== pid;
    const opp = (m.a === pid ? m.b : m.a);
    let body;
    if (m.bye && (m.a === pid || m.b === pid)) {
      body = '<div class="ps-o">Bye</div>';
    } else if (fin || (m.card && opp)) {
      body = '<div class="ps-o">' + (won ? 'Beat ' : lost ? 'Lost to ' : 'v ') + '<b>' + esc(opp ? TA.playerSurname(T, opp) : 'bye') + '</b>' +
        (m.card && m.card.sets && m.card.sets.length ? ' ' + TA.fmtScore(m.card, { winner: true }) : '') + '</div>';
    } else {
      body = st.opponents.length ? st.opponents.slice(0, 3).map(o => '<div class="ps-o"><b>' + esc(TA.playerSurname(T, o[0])) + '</b> ' + TA.pct(o[1], 0) + '</div>').join('') : '<div class="ps-o">—</div>';
    }
    const pr = m.bye ? 'Through' : won ? 'Won' : lost ? 'Out' : (TA.isNum(st.p_reach) ? TA.pct(st.p_reach, 0) : '—');
    return '<div class="path-step' + (won ? ' done-w' : lost ? ' done-l' : '') + '"><div class="ps-r">' + esc(TA.roundLabel(st.round)) + '</div>' +
      '<div class="ps-p" title="Probability of reaching this round">' + pr + '</div>' + body + '</div>';
  }).join('');
  void cards;
  return html + '</div><div class="section-note">The percentage is the chance of reaching the round. Likely opponents assume the other half plays out independently: an opponent’s share is their own chance of reaching that round.</div></div>';
}

function oddsTable(T, sim, rounds) {
  const ids = Object.keys(sim).filter(p => (sim[p].p_title || 0) > 0);
  if (!ids.length) return TA.muted('No title chances: every player in the draw is out or the simulation has not run.');
  ids.sort((a, b) => (sim[b].p_title || 0) - (sim[a].p_title || 0));
  const max = Math.max.apply(null, ids.map(p => sim[p].p_title || 0)) || 1;
  const show = ['QF', 'SF', 'F'].filter(r => rounds.indexOf(r) >= 0);
  const key = { QF: 'p_qf', SF: 'p_sf', F: 'p_final' };
  return TA.tableHTML([{ label: 'Player' }].concat(show.map(r => ({ label: TA.roundLabel(r, true), align: 'right', title: 'Probability of reaching the ' + TA.roundLabel(r).toLowerCase(), cls: 'hide-sm' })),
    [{ label: 'Title', align: 'right', title: 'Our chance of winning the title' }, { label: 'Exp. pts', align: 'right', title: 'Expected ranking points from this event', cls: 'hide-sm' }]),
  ids.slice(0, 40).map(p => {
    const s = sim[p];
    return [{ v: TA.playerName(T, p), html: TA.playerLink(T, p, { rank: true }) }].concat(show.map(r => {
      const v = TA.isNum(s[key[r]]) ? s[key[r]] : (s.reach || {})[r];
      return { v: v, html: TA.isNum(v) ? TA.pct(v, 0) : '—' };
    }), [{ v: s.p_title, html: TA.probCell(s.p_title, 'var(--signal)', max) }, { v: s.exp_points, html: TA.num(s.exp_points, 0) }]);
  }), { compact: true });
}

function results(el, T, cards) {
  const byR = {};
  (cards || []).forEach(c => { (byR[c.round] = byR[c.round] || []).push(c); });
  const rounds = Object.keys(byR).sort((a, b) => TA.roundIndex(b) - TA.roundIndex(a));
  if (!rounds.length) { el.innerHTML = TA.muted('No results yet.'); return; }
  let active = rounds[0];
  const draw = () => {
    el.querySelector('.ev-res').innerHTML = '<div class="gc-grid ta-gc-grid">' + byR[active].slice().sort((a, b) => String(a.date).localeCompare(String(b.date)))
      .map(c => TA.matchCard(c, { tour: T, event: false, date: true })).join('') + '</div>';
  };
  el.innerHTML = '<div class="toggle-row">' + TA.toggles(rounds.map(r => ({ key: r, label: TA.roundLabel(r, true) + ' (' + byR[r].length + ')' })), active, 'data-rr') + '</div><div class="ev-res"></div>';
  TA.wireToggles(el, 'data-rr', k => { active = k; draw(); });
  draw();
}

/* Our chance for pid before a match card was played (the card's pre-match model chance for p1, set before the first
   ball), or null. */
function pFor(c, pid) {
  const p = ((c || {}).model || {}).p1;
  if (!TA.isNum(p)) return null;
  return String(c.p1) === String(pid) ? p : String(c.p2) === String(pid) ? 1 - p : null;
}
const asOf = iso => (iso ? 'as of ' + QK.fmt.date(iso) + ' ' + QK.fmt.time(iso) : '');
/* Round 10 (13 Nov 2026): our title chances before the first ball (d.pre, events.pre_events): the simulation over the
   draw as it stood, qualifiers unknown, on ratings from matches before the day the event began. Kept once play begins.
   -> { at: 'the date', n, chance(pid) (a qualifier holds their slot's chance), rank(pid) (1 = our favourite), fav, ids }
   or null while the field is missing (an older file, an event still to start). */
function preOf(d) {
  const P = d && d.pre;
  if (!P || !P.title) return null;
  const t = P.title, q = P.qualifier || {};
  const ids = Object.keys(t).filter(k => TA.isNum(t[k]) && t[k] > 0).sort((a, b) => t[b] - t[a]);
  if (!ids.length) return null;
  const chance = pid => { const k = q[pid] || pid; return TA.isNum(t[k]) ? t[k] : (P.title && pid in q ? 0 : null); };
  const rank = pid => { const c = chance(pid); return TA.isNum(c) ? 1 + ids.filter(k => t[k] > c).length : null; };
  return { at: P.asof ? QK.fmt.date(P.asof + 'T12:00:00', { day: 'numeric', month: 'short', year: 'numeric' }) : '', n: P.n_sims, t: t, q: q,
    chance: chance, rank: rank, fav: ids[0], ids: ids };
}
/* a pre-event entry's label: the player, or "Qualifier" for a slot no one held yet */
const preLabel = (T, k, P) => {
  if (!String(k).startsWith('tbd:')) return TA.playerShort(T, k);
  const who = Object.keys(P.q).filter(p => P.q[p] === k)[0];
  return who ? TA.playerShort(T, who) + ' (Q)' : 'A qualifier';
};
const prePct = p => TA.pct(p, p < 0.1 ? 1 : 0);
/* a pre-event entry in running text: the surname, or "a qualifier" */
const preSur = (T, k) => (String(k).startsWith('tbd:') ? 'a qualifier' : TA.playerSurname(T, k));
/* two blocks side by side (the kit's .qk-g2), or the one that exists at full width */
const pair = (a, b) => (a && b ? '<div class="qk-g2"><div>' + a + '</div><div>' + b + '</div></div>' : (a || b || ''));

/* v4 (sweep, 12 Nov 2026): the family hero for a tournament. QK.playerHeader on the cobalt block (tennis has no
   colours), the year in the outline, the tour and level in the kicker, surface, dates, draw and place as chips; the
   black strip of key numbers under it; "The short version" in plain words. Only numbers the event file, the draw and
   favourites.json carry: the champion against our pre-match chances, our top-rated entrant going in (Elo before the
   first ball), upsets, the toughest path (opponents' Elo at the start), and for an event in play or to come, our title
   favourite from the simulation. Once play begins the event file keeps our title chances from before the first ball
   (d.pre, round 10): a finished event shows the champion against them; a file without it (an older season) shows our
   pre-match chances only. */
function heroBlock(T, id, d, ev, fav) {
  const sim = (d.sim && d.sim.players) || {};
  const cards = (d.draw || {}).matches || {};
  const Y = TA.yearOfId(id) || ev.year;
  const st = String(ev.status || ''), champ = ev.champion;
  const sur = p => TA.playerSurname(T, p);
  const nm = ev.name || TA.eventName(T, id);
  const heroName = nm.length > 28 && ev.city ? ev.city : nm;
  const played = Object.keys(cards).map(k => cards[k]).filter(c => c && c.winner && TA.isFinished(c));
  const ups = d.upsets || [];
  const dd = d.draw_difficulty || {};
  const ddIds = Object.keys(dd).filter(p => TA.isNum(dd[p].exp_opp_elo)).sort((a, b) => (dd[a].rank || 999) - (dd[b].rank || 999));
  const ranked = Object.keys(sim).filter(p => (sim[p].p_title || 0) > 0).sort((a, b) => sim[b].p_title - sim[a].p_title);
  const nSims = d.sim && d.sim.n_sims ? QK.fmt.num(Number(d.sim.n_sims)) : '';
  /* a surname as a tile's value: big Bebas when it fits, the kit's text size when it is long */
  const nameTile = p => (sur(p).length > 9 ? { value: sur(p), text: true } : { value: sur(p) });
  const tiles = [];
  let short = '';
  // the champion's matches, first round to the final, with our pre-match chance in each
  const path = champ ? played.filter(c => String(c.p1) === String(champ) || String(c.p2) === String(champ))
    .sort((a, b) => TA.roundIndex(a.round) - TA.roundIndex(b.round) || String(a.date).localeCompare(String(b.date))) : [];
  const pathP = path.map(c => ({ c: c, p: pFor(c, champ), opp: String(c.p1) === String(champ) ? c.p2 : c.p1 })).filter(x => TA.isNum(x.p));
  const under = pathP.filter(x => x.p < 0.5).length;
  const low = pathP.slice().sort((a, b) => a.p - b.p)[0];
  const P = preOf(d);
  const cp = P && champ ? P.chance(champ) : null, cr = P && champ ? P.rank(champ) : null;
  if (champ) {
    tiles.push(Object.assign({ label: 'Champion', href: TA.playerHref(T, champ),
      sub: (ev.runner_up ? 'Beat ' + sur(ev.runner_up) + ' in the final' : 'Won the title') + (pathP.length ? '; our underdog in ' + under + ' of ' + pathP.length + ' matches' : '') + '.' }, nameTile(champ)));
    if (TA.isNum(cp)) tiles.push({ label: 'Our chance going in', value: prePct(cp), signal: true,
      sub: 'Before ' + P.at + (P.q[champ] ? ', as an unknown qualifier' : '') + ': ' + (cr === 1 ? 'our favourite.' : 'No. ' + cr + ' in our order; ' + preSur(T, P.fav) + ' led on ' + prePct(P.t[P.fav]) + '.'),
      tip: 'Our title chance for the champion from ' + (P.n ? QK.fmt.num(Number(P.n)) + ' ' : '') + 'simulated draws before a ball was struck, on ratings from matches before ' + P.at + ': nothing from the event enters.' });
    if (low) tiles.push({ label: 'Champion’s lowest chance', value: TA.pct(low.p, 0), signal: true,
      sub: 'Our chance before the ' + TA.roundLabel(low.c.round).toLowerCase() + ' against ' + sur(low.opp) + '.', tip: 'Our pre-match chance for the champion in the hardest match on the way, set before the first ball.' });
  } else if (ranked.length) {
    const f = ranked[0];
    const fp0 = P ? P.chance(f) : null;
    tiles.push({ label: st === 'live' ? 'Our favourite now' : 'Our favourite', value: sur(f) + ' ' + TA.pct(sim[f].p_title, 0), signal: true, href: TA.playerHref(T, f),
      sub: 'To win the title, from ' + (nSims ? nSims + ' ' : '') + 'simulated draws' + (st === 'live' ? ' of the matches left' + (TA.isNum(fp0) ? '; ' + prePct(fp0) + ' before the first ball' : '') + '.' : '.') });
    if (ranked[1]) tiles.push({ label: 'Next best', value: sur(ranked[1]) + ' ' + TA.pct(sim[ranked[1]].p_title, 0), href: TA.playerHref(T, ranked[1]),
      sub: ranked.length + ' player' + (ranked.length === 1 ? '' : 's') + ' still with a chance' + (ev.draw_size ? ', of ' + ev.draw_size : '') + '.' });
  }
  // our top-rated entrant going in (favourites.json: the highest surface-blended Elo before a first match there)
  let favLine = '';
  if (fav && fav[0]) {
    const fp = String(fav[0]);
    /* out = a knockout defeat; a round-robin defeat is not one, and while the event runs a player the simulation still
       gives a chance to is still in */
    const losses = played.filter(c => (String(c.p1) === fp || String(c.p2) === fp) && String(c.winner) !== fp);
    const lost = losses.filter(c => c.round !== 'RR')[0];
    const alive = !champ && sim[fp] && (sim[fp].p_title || 0) > 0;
    const fate = String(champ) === fp ? 'won the title' : alive ? 'still in'
      : lost ? 'out in the ' + TA.roundLabel(lost.round).toLowerCase() + ' to ' + sur(lost.winner) + (TA.isNum(pFor(lost, fp)) ? ' (we had ' + TA.pct(pFor(lost, fp), 0) + ')' : '')
      : losses.length ? 'out in the round robin' : (st === 'live' ? 'still in' : '');
    tiles.push(Object.assign({ label: 'Top-rated going in', href: TA.playerHref(T, fp),
      sub: 'Elo ' + TA.num(fav[1], 0) + ' for the surface before a ball' + (fate ? '; ' + fate : '') + '.', tip: 'The main-draw player with the highest surface-blended Elo before their first match here: nothing from the event itself enters.' }, nameTile(fp)));
    favLine = String(champ) === fp ? ' Our top-rated entrant going in won it.' : fate === 'still in' ? ' Our top-rated entrant going in, ' + sur(fp) + ', is still in.' : fate ? ' Our top-rated entrant going in, ' + sur(fp) + ', was ' + fate + '.' : '';
  }
  if (played.length) {
    const big = ups.slice().sort((a, b) => (TA.isNum(a.p_pre) ? a.p_pre : a.p) - (TA.isNum(b.p_pre) ? b.p_pre : b.p))[0];
    const bp = big ? (TA.isNum(big.p_pre) ? big.p_pre : big.p) : null;
    tiles.push({ label: champ ? 'Upsets' : 'Upsets so far', value: String(ups.length),
      sub: 'Of ' + played.length + ' matches, won by the player we had under 40%' + (big && TA.isNum(bp) ? '; the biggest, ' + sur(big.winner) + ' at ' + TA.pct(bp, 0) : '') + '.' });
  }
  if (ddIds.length) {
    const t0 = ddIds[0];
    const avg = ddIds.reduce((a, p) => a + dd[p].exp_opp_elo, 0) / ddIds.length;
    tiles.push(Object.assign({ label: 'Toughest path', href: TA.playerHref(T, t0),
      sub: 'Expected opponents’ Elo ' + TA.num(dd[t0].exp_opp_elo, 0) + ' at the start; the average path ' + TA.num(avg, 0) + '.', tip: 'Draw difficulty: the mean Elo of the likely opponent in each round, from ratings at the start of the event. It measures the strength of the field each player had to get through.' }, nameTile(t0)));
  }
  if (!champ && !played.length && (ev.draw_size || ranked.length)) tiles.push({ label: 'The field', value: String(ev.draw_size || ranked.length), sub: (ev.draw_size ? 'players in the draw' : 'players') + (ev.best_of ? ', best of ' + ev.best_of + ' sets' : '') + '.' });
  if (champ) short = sur(champ) + ' won the title' + (ev.runner_up ? ', beating ' + sur(ev.runner_up) + ' in the final' : '') + '.' +
    (TA.isNum(cp) ? ' Before the first ball we gave ' + sur(champ) + ' ' + prePct(cp) + (cr === 1 ? ', our favourite.' : ', our No. ' + cr + ' (' + preSur(T, P.fav) + ' led on ' + prePct(P.t[P.fav]) + ').') : '') +
    (pathP.length ? ' Our underdog in ' + under + ' of ' + pathP.length + ' matches on the way' + (low ? ', ' + TA.pct(low.p, 0) + ' at the lowest' : '') + '.' : '') + favLine +
    (played.length ? ' ' + ups.length + ' of ' + played.length + ' matches went to the player we had under 40%.' : '');
  else if (ranked.length) short = sur(ranked[0]) + ' is our favourite at ' + TA.pct(sim[ranked[0]].p_title, 0) + (ranked[1] ? ', ahead of ' + sur(ranked[1]) + ' at ' + TA.pct(sim[ranked[1]].p_title, 0) : '') + '.' +
    (st === 'live' && ev.round_now ? ' Next up: the ' + TA.roundLabel(ev.round_now).toLowerCase() + '.' : '') + favLine + (played.length ? ' ' + ups.length + ' upset' + (ups.length === 1 ? '' : 's') + ' in ' + played.length + ' matches so far.' : '');
  const place = [ev.city, ev.country].filter(Boolean).join(', ');
  const tags = st === 'live' && !champ ? [QK.tag('In play' + (ev.round_now ? ' · ' + TA.roundLabel(ev.round_now) : ''), 'live')] : st === 'upcoming' ? [QK.tag('Starts ' + QK.fmt.date(ev.start + 'T12:00:00'), 'signal')] : [];
  return QK.playerHeader({ name: heroName, face: String(Y || ''), kicker: [TA.tourName(T), TA.levelLabel(ev.level, T), Y].filter(Boolean).join(' · '),
    meta: [heroName !== nm ? nm : null, TA.surfaceLabel(ev.surface, ev.indoor), TA.fmtRange(ev.start, ev.end), ev.draw_size ? 'Draw of ' + ev.draw_size : null,
      ev.best_of ? 'Best of ' + ev.best_of : null, place && place !== heroName ? place : null],
    tags: tags, strip: tiles, short: short ? { title: 'The short version', text: short } : null });
}

/* The title-chances block: our chance of winning it (QK.chances) for an event in play or to come; once it is over, the
   champion's path with our chance before each match. "How sure are we?" says what the top number means. */
function chancesBlock(T, d, ev) {
  const sim = (d.sim && d.sim.players) || {};
  const champ = ev.champion;
  const sur = p => TA.playerSurname(T, p);
  const as = asOf(d.updated_at);
  if (d.sim && !champ) {
    const ids = Object.keys(sim).filter(p => (sim[p].p_title || 0) > 0).sort((a, b) => sim[b].p_title - sim[a].p_title);
    const items = ids.slice(0, 12).map(p => ({ label: TA.playerShort(T, p), p: sim[p].p_title, href: TA.playerHref(T, p), sub: TA.isNum(TA.playerRank(T, p)) ? 'No. ' + TA.playerRank(T, p) : '' }));
    if (!items.length) return '';
    const f = ids[0], p = sim[f].p_title, miss = Math.max(1, Math.round(10 * (1 - p)));
    const n = d.sim.n_sims ? QK.fmt.num(Number(d.sim.n_sims)) + ' ' : '';
    const sure = '<b>How sure are we?</b> ' + esc(sur(f)) + ' at ' + TA.pct(p, 0) + (p < 0.95 ? ' still misses the title about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10' : ' is close to certain') + '. ' +
      (String(ev.status) === 'live' ? 'The chances come from ' + n + 'simulated draws of the matches left and move after every result.' : 'From ' + n + 'simulated draws before a ball is struck: the draw, not just the ratings, shapes them.');
    return QK.sectionHead({ kicker: 'Title chances', title: 'Who lifts the trophy?', sub: 'Our chance of winning it, from ' + n + 'simulated draws' + (as ? ' · ' + as : '') + '.' }) +
      '<article class="qk-card"><div class="qk-card-body">' + QK.chances(items, { oursName: 'Our title chance' }) + '</div></article>' + QK.explain(sure);
  }
  if (!champ) return '';
  const cards = (d.draw || {}).matches || {};
  const path = Object.keys(cards).map(k => cards[k]).filter(c => c && c.winner && TA.isFinished(c) && (String(c.p1) === String(champ) || String(c.p2) === String(champ)))
    .sort((a, b) => TA.roundIndex(a.round) - TA.roundIndex(b.round) || String(a.date).localeCompare(String(b.date)));
  const rows = path.map(c => { const opp = String(c.p1) === String(champ) ? c.p2 : c.p1; return { label: TA.roundLabel(c.round, true) + ' · ' + sur(opp), p: pFor(c, champ), href: c.id ? TA.matchHref(T, c.id) : null, sub: String(c.winner) === String(champ) ? 'won' : 'lost' }; })
    .filter(r => TA.isNum(r.p));
  if (!rows.length) return '';
  const low = rows.slice().sort((a, b) => a.p - b.p)[0];
  const hits = Math.max(1, Math.round(10 * low.p));
  const nUps = (d.upsets || []).length, nPlayed = Object.keys(cards).filter(k => cards[k] && cards[k].winner && TA.isFinished(cards[k])).length;
  const sure = '<b>How sure are we?</b> Each bar is our chance for ' + esc(sur(champ)) + ' before that match, set before the first ball. ' + TA.pct(low.p, 0) + ' still comes off about ' + hits + ' time' + (hits === 1 ? '' : 's') + ' in 10' +
    (nPlayed ? '; across the draw, ' + nUps + ' of ' + nPlayed + ' matches went to the player we had under 40%.' : '.');
  return QK.sectionHead({ kicker: 'The champion’s path', title: 'How ' + sur(champ) + ' won it', sub: 'Our chance before each match on the way to the title' + (as ? ' · ' + as : '') + '.' }) +
    '<article class="qk-card"><div class="qk-card-body">' + QK.chances(rows, { sort: false, max: 1, oursName: 'Our pre-match chance for ' + sur(champ) }) + '</div></article>' + QK.explain(sure);
}

/* "Going in": our title chances before the first ball (top eight, the champion added when outside them), each with how
   far the player went (finished) or whether still in (in play). The kit's one-line explain says what the top number
   meant. Empty without d.pre. */
function goingInBlock(T, d, ev) {
  const P = preOf(d);
  if (!P) return '';
  const champ = ev.champion ? String(ev.champion) : null;
  const cards = (d.draw || {}).matches || {};
  const out = {};
  Object.keys(cards).forEach(k => { const c = cards[k]; if (c && c.winner && TA.isFinished(c) && c.round !== 'RR') [c.p1, c.p2].forEach(x => { if (x && String(x) !== String(c.winner)) out[String(x)] = c.round; }); });
  /* in play, "still in" only while the simulation of the matches left still gives a chance (a round robin's losses do
     not knock anyone out) */
  const sim = (d.sim && d.sim.players) || null;
  const fate = pid => (!pid ? '' : champ === pid ? 'won the title' : out[pid] ? 'out in the ' + TA.roundLabel(out[pid], true) : champ ? ''
    : sim && sim[pid] ? ((sim[pid].p_title || 0) > 0 ? 'still in' : 'out') : 'still in');
  const who = k => (String(k).startsWith('tbd:') ? Object.keys(P.q).filter(p => P.q[p] === k)[0] || null : String(k));
  let keys = P.ids.slice(0, 8);
  const ck = champ ? (P.q[champ] || champ) : null;
  if (ck && keys.indexOf(ck) < 0 && TA.isNum(P.t[ck])) keys = keys.concat([ck]);
  const rows = keys.map(k => { const pid = who(k); return { label: preLabel(T, k, P), p: P.t[k], href: pid ? TA.playerHref(T, pid) : null, sub: fate(pid) }; });
  const f = P.fav, pf = P.t[f], miss = Math.max(1, Math.round(10 * (1 - pf)));
  const cr = champ ? P.rank(champ) : null;
  const sure = '<b>How sure are we?</b> Our favourite going in, ' + esc(preSur(T, f)) + ', at ' + prePct(pf) + ' misses the title about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10' +
    (champ && cr ? (cr === 1 ? '; this time the favourite won.' : '; ' + esc(TA.playerSurname(T, champ)) + ' won from our No. ' + cr + '.') : '.');
  return QK.sectionHead({ kicker: 'Going in', title: 'Who we had before a ball was struck', sub: 'Our title chances before ' + P.at + ', from ' + (P.n ? QK.fmt.num(Number(P.n)) + ' ' : '') + 'simulated draws: ratings from matches before that day only' + (Object.keys(P.q).length ? ', qualifiers not yet known.' : '.') }) +
    '<article class="qk-card"><div class="qk-card-body">' + QK.chances(rows, { sort: false, oursName: 'Our title chance before the first ball' }) + '</div></article>' + QK.explain(sure);
}

function render(el, params) {
  const T = params.tour, id = params.id;
  el.innerHTML = '<div class="muted">Loading the tournament…</div>';
  return TA.loadAll([TA.eventPath(T, id), TA.tpath('history.json', T), TA.tpath('favourites.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const d = arr[0], hist = TA.ok(arr[1]) ? arr[1] : null, FV = TA.ok(arr[2]) ? (arr[2].events || {}) : {};
    if (!TA.ok(d)) {
      const e0 = TA.eventInfo(T, id);
      el.innerHTML = TA.pageHead(TA.eventName(T, id, true), e0.level ? esc(TA.levelLabel(e0.level, T)) + ' · ' + esc(TA.surfaceLabel(e0.surface, e0.indoor)) : '', '<a href="' + TA.href(T, 'calendar') + '">Calendar</a>') +
        TA.card('Tournament', '', TA.notBuilt('This tournament page', d));
      return;
    }
    const ev = Object.assign({}, TA.eventInfo(T, id), d.event || {});
    const sim = (d.sim && d.sim.players) || {};
    const draw = d.draw || {};
    const cards = draw.matches || {};
    const Y = TA.yearOfId(id);
    const st = String(ev.status || '');
    const champ = ev.champion;

    // ── the family hero, the strip, the short version; then title chances beside upsets and awards, the draw, the tables
    const crumb = '<nav class="ta-crumb" aria-label="Breadcrumb"><a href="' + TA.href(T, 'calendar', Y) + '">' + esc(TA.tourName(T)) + ' tournaments</a><span aria-hidden="true">›</span>' + esc((ev.name || TA.eventName(T, id)) + ' ' + (Y || '')) + '</nav>';
    const oddsH = chancesBlock(T, d, ev);
    el.innerHTML = crumb + heroBlock(T, id, d, ev, FV[id]) +
      '<section class="qk-section ta-ev-s1" id="ev-s1"></section>' +
      '<section class="qk-section"><div id="ev-draw"></div><div id="ev-pick"></div></section>' +
      '<section class="qk-section" id="ev-s3"></section><div id="ev-race"></div><section class="qk-section"><div id="ev-results"></div></section><section class="qk-section" id="ev-more"></section>';

    /* round 9: the draw pick'em (ta-pickem.js), in this browser only */
    if (TA.pickem) TA.pickem.mount(document.getElementById('ev-pick'), T, id, cards, sim, champ ? String(champ) : (st === 'done' ? true : false));
    // ── the draw
    const hasDraw = (draw.slots || []).length > 0;
    const drawSub = (draw.source === 'reconstructed' ? 'rebuilt from the matches played; seeds not shown' : draw.source === 'wta' ? 'the WTA draw with seeds and entry types' : '') +
      (draw.complete === false ? ' · some first-round blocks are not yet linked' +
        (draw.source === 'reconstructed' ? ' (ESPN gives no bracket order or seeds, so later-round paths are approximate until the next round is set)' : '') : '');
    document.getElementById('ev-draw').innerHTML = TA.card('The draw', (drawSub ? esc(drawSub) + ' · ' : '') + 'percentages are our chance of winning each match' + (champ ? '; it opens on the champion’s path, click any player to follow theirs' : ''),
      hasDraw ? '<div id="ev-bracket"></div><div id="ev-path"></div>' : TA.muted('The draw is not available yet.'));
    let api = null;
    if (hasDraw) {
      api = TA.charts.bracket('ev-bracket', draw, {
        tour: T, sim: sim,
        onPick: pid => { const p = document.getElementById('ev-path'); if (p) p.innerHTML = pathPanel(T, api.model, sim, pid, cards); }
      });
      const p = document.getElementById('ev-path');
      if (p && api) p.innerHTML = pathPanel(T, api.model, sim, null, cards);
      // #/<T>/event/<id>?p=<pid> opens the draw with that player's path lit
      const q = (params.query || {}).p;
      if (api && q && api.model.leafOf[q] !== undefined) api.pick(q);
      else if (api && champ && api.model.leafOf[champ] !== undefined) api.pick(champ);   // a finished event opens on the champion's path
    }

    // ── the tables: upsets, awards, round by round, draw difficulty, past champions (number, then chart, then table)
    const ups = d.upsets || [];
    const upsH = ups.length ? TA.card('Upsets', 'winners we gave under 40% before the match' + (asOf(d.updated_at) ? ' · ' + asOf(d.updated_at) : ''), TA.tableHTML([{ label: 'Round' }, { label: 'Winner' }, { label: 'Beat' }, { label: 'Pre-match', align: 'right' }, { label: '', sortable: false }],
      ups.map(u => [{ v: TA.roundIndex(u.round), html: esc(TA.roundLabel(u.round, true)) }, { v: TA.playerName(T, u.winner), html: TA.playerLink(T, u.winner, { short: true }) },
        { v: TA.playerName(T, u.loser), html: TA.playerLink(T, u.loser, { short: true }) }, { v: TA.isNum(u.p_pre) ? u.p_pre : u.p, html: TA.pct(TA.isNum(u.p_pre) ? u.p_pre : u.p, 0) },
        { html: u.match ? TA.matchLink(T, u.match, '→') : '' }]), { compact: true })) : '';
    const aw = awardTiles(T, d.awards);
    const awH = aw ? TA.card('Awards', champ ? 'the tournament’s standouts' : 'so far', aw) : '';
    const rbr = d.sim && !champ && Object.keys(sim).length ? TA.card('Round by round', 'our chance of reaching each round, and the title', oddsTable(T, sim, draw.rounds || [])) : '';
    const dd = d.draw_difficulty || {};
    const ddIds = Object.keys(dd).filter(p => TA.isNum(dd[p].exp_opp_elo));
    let ddH = '';
    if (ddIds.length) {
      ddIds.sort((a, b) => (dd[a].rank || 999) - (dd[b].rank || 999) || dd[b].exp_opp_elo - dd[a].exp_opp_elo);
      const seeded = (TA.charts.bracketModel(draw) || { leaves: [] }).leaves.filter(l => l.seed).map(l => l.pid);
      const pick = seeded.length ? ddIds.filter(p => seeded.indexOf(p) >= 0) : ddIds.slice(0, 16);
      /* once it is over the title chances are gone: the column says how far each player went instead */
      const outIn = {};
      if (champ) Object.keys(cards).forEach(k => { const c = cards[k]; if (c && c.winner && TA.isFinished(c)) [c.p1, c.p2].forEach(x => { if (x && String(x) !== String(c.winner) && TA.roundIndex(c.round) > TA.roundIndex(outIn[x] || '')) outIn[x] = c.round; }); });
      const lastCol = champ ? { label: 'Went out', align: 'right', title: 'The round each player lost in' } : { label: st === 'live' ? 'Title now' : 'Title', align: 'right', title: 'Our chance of winning the title' + (st === 'live' ? ', from the matches left' : '') };
      const lastCell = p => (champ ? (String(champ) === String(p) ? { v: 99, html: '<b>Won</b>' } : { v: TA.roundIndex(outIn[p] || ''), html: outIn[p] ? esc(TA.roundLabel(outIn[p], true)) : '—' })
        : { v: (sim[p] || {}).p_title, html: TA.isNum((sim[p] || {}).p_title) ? TA.pct(sim[p].p_title, 1) : '—' });
      ddH = TA.card('Draw difficulty', 'expected Elo of the opponents along each path, from ratings at the start · 1 = toughest' + (seeded.length ? ' · seeds' : ''),
        TA.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Exp. opponent Elo', align: 'right' }, lastCol],
          pick.slice(0, 16).map(p => [{ v: dd[p].rank, html: TA.isNum(dd[p].rank) ? String(dd[p].rank) : '—' }, { v: TA.playerName(T, p), html: TA.playerLink(T, p, { rank: st === 'upcoming' }) },
            { v: dd[p].exp_opp_elo, html: TA.num(dd[p].exp_opp_elo, 0) }, lastCell(p)]), { compact: true }));
    }
    // champions history
    let hrows = (d.history || []).slice();
    const tid = String(id).replace(/-(19|20)\d\d$/, '');
    const he = hist && hist.events ? hist.events[tid] : null;
    if (!hrows.length && he) hrows = (he.champions || []).slice().reverse();
    hrows = hrows.filter(r => Number(r[0]) !== Number(Y)).sort((a, b) => b[0] - a[0]);
    const counts = {};
    hrows.forEach(r => { if (r[1]) counts[r[1]] = (counts[r[1]] || 0) + 1; });
    const most = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
    const pastH = TA.card('Past champions', hrows.length ? hrows.length + ' editions' + (most && counts[most] > 1 ? ' · most titles: ' + TA.playerLink(T, most) + ' (' + counts[most] + ')' : '') : '',
      hrows.length ? TA.tableHTML([{ label: 'Year' }, { label: 'Champion' }, { label: 'Runner-up' }, { label: '', sortable: false }],
        hrows.map(r => [{ v: r[0], html: String(r[0]) }, { v: TA.playerName(T, r[1]), html: TA.playerLink(T, r[1]) }, { v: TA.playerName(T, r[2]), html: r[2] ? TA.playerLink(T, r[2]) : '—' },
          { html: '<a href="' + TA.eventHref(T, tid + '-' + r[0]) + '">draw →</a>' }]), { compact: true }) : TA.muted('No earlier editions on record.'));
    /* 1. title chances (or the champion's path) beside upsets and awards; with neither, the round-by-round table */
    let side = upsH + awH, rbrUsed = false;
    if (!side && rbr) { side = rbr; rbrUsed = true; }
    document.getElementById('ev-s1').innerHTML = pair(oddsH, side);
    /* 3. round by round (in play), or once it is over our chances going in, or past champions; beside draw difficulty.
       In play, "Going in" sits beside past champions under it. */
    const goH = goingInBlock(T, d, ev);
    const left3 = rbr && !rbrUsed ? rbr : (champ && goH ? goH : pastH);
    document.getElementById('ev-s3').innerHTML = pair(left3, ddH);
    const moreEl = document.getElementById('ev-more');
    const more = left3 === pastH ? (goH && left3 !== goH ? goH : '') : (goH && left3 !== goH ? pair(goH, pastH) : pastH);
    moreEl.innerHTML = more;
    moreEl.hidden = !more;

    // ── results
    const res = (d.results && d.results.length ? d.results : Object.keys(cards).map(k => cards[k]).filter(TA.isFinished));
    document.getElementById('ev-results').innerHTML = TA.card('Results', res.length + ' match' + (res.length === 1 ? '' : 'es') + ' · by round', '<div id="ev-res"></div>');
    results(document.getElementById('ev-res'), T, res.concat(Object.keys(cards).map(k => cards[k]).filter(c => !TA.isFinished(c) && res.indexOf(c) < 0)));
    if (!champ && Number(Y) === Number(TA.currentYear(T))) {
      TA.load(TA.tpath('race.json', T)).then(race => {
        const box = document.getElementById('ev-race');
        if (!box || !TA.ok(race) || !TA.shape) return;
        const q = TA.shape.stakesHTML(T, race, 'finals_qual', { event: id, limit: 6 }), n1 = TA.shape.stakesHTML(T, race, 'year_end_no1', { event: id, limit: 3 });
        if (!q && !n1) return;
        box.innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'What’s at stake', title: 'What this event means for the race',
          sub: 'Our chance of reaching the Finals (and of finishing the year No. 1) if the next match here is won or lost. <a href="' + TA.href(T, 'race') + '">The full race →</a>', html: true }) +
          (q ? '<h3 class="rs-h3">Finals qualification</h3>' + q : '') + (n1 ? '<h3 class="rs-h3">Year-end No. 1</h3>' + n1 : '') + '</section>';
      });
    }
    TA.sortable(el);
    document.title = (ev.name || TA.eventName(T, id)) + ' ' + (Y || '') + ' · ' + TA.tourName(T) + ' · The Quant Ace';
    TA.setMeta(esc(ev.name || TA.eventName(T, id)) + (d.sim && d.sim.n_sims ? ' · ' + QK.fmt.num(Number(d.sim.n_sims)) + ' simulations' : ''));
  });
}

TA.route('event', render);
})(window.TA);
