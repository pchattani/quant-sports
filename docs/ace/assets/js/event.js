/* The Quant Ace — the tournament page (#/<T>/event/<event_id>).
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

function render(el, params) {
  const T = params.tour, id = params.id;
  el.innerHTML = '<div class="muted">Loading the tournament…</div>';
  return TA.loadAll([TA.eventPath(T, id), TA.tpath('history.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const d = arr[0], hist = TA.ok(arr[1]) ? arr[1] : null;
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
    const col = TA.surfaceColour(ev.surface, ev.indoor);
    const Y = TA.yearOfId(id);
    const st = String(ev.status || '');
    const champ = ev.champion;
    const live = Object.keys(cards).filter(k => TA.matchState(cards[k]) === 'live').length;

    // ── head
    let side = '';
    if (champ) side = '<div class="ev-champ">🏆 ' + TA.playerLink(T, champ) + '</div>' + (ev.runner_up ? '<div class="muted-inline">runner-up ' + TA.playerLink(T, ev.runner_up) + '</div>' : '');
    else if (st === 'live') {
      const fav = Object.keys(sim).sort((a, b) => (sim[b].p_title || 0) - (sim[a].p_title || 0))[0];
      side = '<span class="chip st-live"><span class="live-dot"></span> In play' + (live ? ' · ' + live + ' live' : '') + '</span>' +
        (fav ? '<div class="muted-inline">our favourite ' + TA.playerLink(T, fav) + ' ' + TA.pct(sim[fav].p_title, 0) + '</div>' : '');
    } else if (st === 'upcoming') side = '<span class="chip st-time">Starts ' + esc(TA.fmtDate(ev.start, { year: false })) + '</span>';
    void col;
    el.innerHTML = '<div class="ta-ev-head" style="--sf:' + col + '">' + QK.sectionHead({ kicker: [TA.levelLabel(ev.level, T), TA.surfaceLabel(ev.surface, ev.indoor), [ev.city, ev.country].filter(Boolean).join(', ')].filter(Boolean).join(' · '),
      title: esc(ev.name || TA.eventName(T, id)) + ' ' + (Y || ''), html: true, size: 'lg', tag: 'h1',
      sub: esc(TA.fmtRange(ev.start, ev.end)) + (ev.draw_size ? ' · draw of ' + esc(ev.draw_size) : '') + (ev.best_of ? ' · best of ' + esc(ev.best_of) : '') +
        ' · <a href="' + TA.href(T, 'calendar', Y) + '">' + esc(TA.tourName(T)) + ' tournaments</a>', actions: '<div class="ev-side">' + side + '</div>' }) + '</div>' +
      '<div id="ev-draw"></div><div id="ev-pick"></div><div class="grid-2"><div id="ev-odds"></div><div id="ev-side"></div></div><div id="ev-race"></div><div id="ev-results"></div><div id="ev-more"></div>';

    /* round 9: the draw pick'em (ta-pickem.js), in this browser only */
    if (TA.pickem) TA.pickem.mount(document.getElementById('ev-pick'), T, id, cards, sim, champ ? String(champ) : (st === 'done' ? true : false));
    // ── the draw
    const hasDraw = (draw.slots || []).length > 0;
    const drawSub = (draw.source === 'reconstructed' ? 'rebuilt from the matches played; seeds not shown' : draw.source === 'wta' ? 'the WTA draw with seeds and entry types' : '') +
      (draw.complete === false ? ' · some first-round blocks are not yet linked' +
        (draw.source === 'reconstructed' ? ' (ESPN gives no bracket order or seeds, so later-round paths are approximate until the next round is set)' : '') : '');
    document.getElementById('ev-draw').innerHTML = TA.card('The draw', (drawSub ? esc(drawSub) + ' · ' : '') + 'percentages are our chance of winning each match',
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

    // ── our title chances
    const oddsEl = document.getElementById('ev-odds');
    if (d.sim && !champ) {
      const items = Object.keys(sim).filter(p => (sim[p].p_title || 0) > 0).sort((a, b) => sim[b].p_title - sim[a].p_title).slice(0, 12)
        .map(p => ({ label: TA.playerShort(T, p), p: sim[p].p_title, href: TA.playerHref(T, p), sub: TA.isNum(TA.playerRank(T, p)) ? 'No. ' + TA.playerRank(T, p) : '' }));
      oddsEl.innerHTML = TA.v2.card('Title chances', 'Our chance of winning it, from ' + (d.sim.n_sims ? Number(d.sim.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated draws', items.length ? QK.chances(items, { oursName: 'Our title chance' }) : QK.empty('No title chances yet')) +
        TA.card('Round by round', 'our chance of reaching each round, and the title', oddsTable(T, sim, draw.rounds || []));
    } else {
      const cs = sim[champ] || {};
      oddsEl.innerHTML = TA.card('Title chances', champ ? 'the tournament is over' : '', champ ? '<div class="pad">' + TA.playerLink(T, champ) + ' won the title' +
        (ev.runner_up ? ', beating ' + TA.playerLink(T, ev.runner_up) + ' in the final' : '') + '. ' +
        (TA.isNum(cs.exp_points) ? 'Ranking points: ' + TA.num(cs.exp_points, 0) + '. ' : '') + 'The draw above opens on the champion’s path; click any other player to follow theirs.</div>'
        : TA.notBuilt('The tournament simulation', null));
    }

    // ── side: upsets, draw difficulty, awards
    const ups = d.upsets || [];
    let sideHtml = '';
    if (ups.length) {
      sideHtml += TA.card('Upsets', 'winners we gave under 40% before the match', TA.tableHTML([{ label: 'Round' }, { label: 'Winner' }, { label: 'Beat' }, { label: 'Pre-match', align: 'right' }, { label: '', sortable: false }],
        ups.map(u => [{ v: TA.roundIndex(u.round), html: esc(TA.roundLabel(u.round, true)) }, { v: TA.playerName(T, u.winner), html: TA.playerLink(T, u.winner, { short: true }) },
          { v: TA.playerName(T, u.loser), html: TA.playerLink(T, u.loser, { short: true }) }, { v: TA.isNum(u.p_pre) ? u.p_pre : u.p, html: TA.pct(TA.isNum(u.p_pre) ? u.p_pre : u.p, 0) },
          { html: u.match ? TA.matchLink(T, u.match, '→') : '' }]), { compact: true }));
    }
    const dd = d.draw_difficulty || {};
    const ddIds = Object.keys(dd).filter(p => TA.isNum(dd[p].exp_opp_elo));
    if (ddIds.length) {
      ddIds.sort((a, b) => (dd[a].rank || 999) - (dd[b].rank || 999) || dd[b].exp_opp_elo - dd[a].exp_opp_elo);
      const seeded = (TA.charts.bracketModel(draw) || { leaves: [] }).leaves.filter(l => l.seed).map(l => l.pid);
      const pick = seeded.length ? ddIds.filter(p => seeded.indexOf(p) >= 0) : ddIds.slice(0, 16);
      sideHtml += TA.card('Draw difficulty', 'expected Elo of the opponents along each path · 1 = toughest' + (seeded.length ? ' · seeds' : ''),
        TA.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Exp. opponent Elo', align: 'right' }, { label: 'Title', align: 'right' }],
          pick.slice(0, 16).map(p => [{ v: dd[p].rank, html: TA.isNum(dd[p].rank) ? String(dd[p].rank) : '—' }, { v: TA.playerName(T, p), html: TA.playerLink(T, p, { rank: true }) },
            { v: dd[p].exp_opp_elo, html: TA.num(dd[p].exp_opp_elo, 0) }, { v: (sim[p] || {}).p_title, html: TA.isNum((sim[p] || {}).p_title) ? TA.pct(sim[p].p_title, 1) : '—' }]), { compact: true }));
    }
    const aw = awardTiles(T, d.awards);
    if (aw) sideHtml += TA.card('Awards', 'so far', aw);
    document.getElementById('ev-side').innerHTML = sideHtml || TA.card('Upsets', '', TA.muted('No upsets yet.'));

    // ── results
    const res = (d.results && d.results.length ? d.results : Object.keys(cards).map(k => cards[k]).filter(TA.isFinished));
    document.getElementById('ev-results').innerHTML = TA.card('Results', res.length + ' match' + (res.length === 1 ? '' : 'es') + ' · by round', '<div id="ev-res"></div>');
    results(document.getElementById('ev-res'), T, res.concat(Object.keys(cards).map(k => cards[k]).filter(c => !TA.isFinished(c) && res.indexOf(c) < 0)));

    // ── champions history
    let hrows = (d.history || []).slice();
    const tid = String(id).replace(/-(19|20)\d\d$/, '');
    const he = hist && hist.events ? hist.events[tid] : null;
    if (!hrows.length && he) hrows = (he.champions || []).slice().reverse();
    hrows = hrows.filter(r => Number(r[0]) !== Number(Y)).sort((a, b) => b[0] - a[0]);
    const counts = {};
    hrows.forEach(r => { if (r[1]) counts[r[1]] = (counts[r[1]] || 0) + 1; });
    const most = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
    document.getElementById('ev-more').innerHTML = TA.card('Past champions', hrows.length ? hrows.length + ' editions' + (most && counts[most] > 1 ? ' · most titles: ' + TA.playerLink(T, most) + ' (' + counts[most] + ')' : '') : '',
      hrows.length ? TA.tableHTML([{ label: 'Year' }, { label: 'Champion' }, { label: 'Runner-up' }, { label: '', sortable: false }],
        hrows.map(r => [{ v: r[0], html: String(r[0]) }, { v: TA.playerName(T, r[1]), html: TA.playerLink(T, r[1]) }, { v: TA.playerName(T, r[2]), html: r[2] ? TA.playerLink(T, r[2]) : '—' },
          { html: '<a href="' + TA.eventHref(T, tid + '-' + r[0]) + '">draw →</a>' }]), { compact: true }) : TA.muted('No earlier editions on record.'));
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
    TA.setMeta(esc(ev.name || TA.eventName(T, id)) + (d.sim && d.sim.n_sims ? ' · ' + TA.num(d.sim.n_sims, 0) + ' simulations' : ''));
  });
}

TA.route('event', render);
})(window.TA);
