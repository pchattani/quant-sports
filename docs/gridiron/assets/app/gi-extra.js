/* The Quant Gridiron — round 9, phase 4 (28 Oct 2026): two new pages from data the site already has.
 *   #/referees     Referees (in Teams): each crew chief's flags this season against the league (penalties a game, yards,
 *                  the share called on the home side, the calls they make most) and every season since 1999 for one
 *                  referee; the league's penalties a game by season. Reads referees.json (built every run; the route
 *                  used to redirect to Coaches).
 *   #/prospects    Draft prospects (in the Scouting Room): the best draft-eligible college players (juniors and seniors)
 *                  by The Quant Campus's value model, by position, each linked to the player's Campus page. Reads the
 *                  Campus site's cfb value and team files (same origin on the live hub; ../campus locally). No new fetch.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;

/* ── referees ─────────────────────────────────────────────────────────── */
const RST = { ref: '' };
GI.route('referees', function (el, params) {
  const S = Number(params.season);
  return GI.load('referees.json').then(d => {
    if (!el.isConnected) return;
    const head = GI.pageHead('Teams · ' + S, 'Referees', 'Who throws the flags: each crew chief’s penalties a game against the league, the share called on the home side and the calls they make most.') + GI.sectionNav('teams', 'referees');
    if (!GI.ok(d)) { el.innerHTML = head + GI.notBuilt('The referee file', d); return; }
    const L = d.league || {};
    const lg = isNum(L[String(S)]) ? L[String(S)] : null;
    const R = d.referees || {};
    /* the season on screen: the current list, or each referee's row for a past season */
    const cur = S === Number(d.season) ? (d.current || []) : Object.keys(R).map(n => { const r = (R[n].seasons || []).filter(x => x.season === S)[0]; return r ? Object.assign({ referee: n }, r) : null; }).filter(Boolean);
    const list = cur.filter(r => r.games > 0).sort((a, b) => (b.penalties_pg || 0) - (a.penalties_pg || 0));
    if (!RST.ref || !R[RST.ref]) RST.ref = list[0] ? list[0].referee : Object.keys(R)[0];
    const most = list[0], least = list[list.length - 1];
    const homeTilt = list.filter(r => r.games >= 3 && isNum(r.home_share)).sort((a, b) => b.home_share - a.home_share)[0];
    el.innerHTML = head +
      GI.kpis([isNum(lg) ? GI.kpi('League, ' + S, GI.num(lg, 1), 'penalties a game (both teams)', { signal: true }) : '',
        most ? GI.kpi('Most flags', esc(GI.surnameOf(most.referee)) + ' ' + GI.num(most.penalties_pg, 1), most.games + ' games · ' + GI.signed(most.vs_league, 1) + ' a game on the league') : '',
        least ? GI.kpi('Fewest flags', esc(GI.surnameOf(least.referee)) + ' ' + GI.num(least.penalties_pg, 1), least.games + ' games · ' + GI.signed(least.vs_league, 1) + ' a game on the league') : '',
        homeTilt ? GI.kpi('Most called on the home side', esc(GI.surnameOf(homeTilt.referee)) + ' ' + GI.pct(homeTilt.home_share, 0), 'of the flags in his games (an even split is 50%)') : '']) +
      (list.length ? GI.card('Flags a game, crew by crew', S + ' · penalties a game in each referee’s games, with the league line', GI.chartBox('rf-bar', Math.max(320, list.length * 24 + 50), 'Penalties a game by referee')) : QK.empty('No games yet', 'The referee table fills in after the first week.')) +
      (list.length ? GI.card('Every crew chief', 'Sortable · home share is the share of the flags called on the home team', GI.tableHTML([{ label: 'Referee' }, { label: 'Games', align: 'right' }, { label: 'Penalties a game', align: 'right' }, { label: 'v league', align: 'right', title: 'Penalties a game above (+) or below the league this season' },
        { label: 'Yards a game', align: 'right' }, { label: 'On the home side', align: 'right' }, { label: 'Home teams', align: 'right', title: 'The home teams’ record in his games' }, { label: 'Calls most', sortable: false }],
        list.map(r => [{ html: '<button type="button" class="gi-linkbtn" data-ref="' + esc(r.referee) + '">' + esc(r.referee) + '</button>', v: r.referee }, r.games, { html: GI.num(r.penalties_pg, 1), v: r.penalties_pg }, { html: GI.signed(r.vs_league, 1), v: r.vs_league },
          { html: GI.num(r.yards_pg, 0), v: r.yards_pg }, { html: GI.pct(r.home_share, 0), v: r.home_share }, { html: Array.isArray(r.home_record) ? GI.record(r.home_record[0], r.home_record[1], r.home_record[2]) : '—', v: Array.isArray(r.home_record) ? r.home_record[0] : null },
          { html: '<span class="qk-sub">' + esc((r.top_calls || []).slice(0, 3).map(c => c[0] + ' ' + c[1]).join(' · ')) + '</span>' }]), { sticky: true }), { flush: true }) : '') +
      GI.grid(GI.card('<span id="rf-name">' + esc(RST.ref) + '</span>', 'Every season in our data: his penalties a game against the league’s', GI.chartBox('rf-car', 300, 'One referee by season'), { span: 7 }) +
        GI.card('The league since 1999', 'Penalties a game (both teams), by season', GI.chartBox('rf-lg', 300, 'League penalties a game'), { span: 5 })) +
      QK.explain('Penalties depend on the teams as much as the crew: a referee who drew two undisciplined teams looks flag-happy. Read a few games as noise; the career line is steadier. Penalty counts are from the play-by-play (accepted and declined flags on scrimmage plays).', { title: 'How sure are we?' });
    GI.sortable(el);
    if (list.length) GI.ch.bar('rf-bar', { cats: list.map(r => r.referee), series: [{ name: 'Penalties a game', data: list.map(r => r.penalties_pg) }], horizontal: true, labels: true, fmt: v => GI.num(v, 1), labelWidth: 150, valName: 'Penalties a game (both teams)', catName: 'Referee' });
    const yrs = Object.keys(L).map(Number).sort((a, b) => a - b);
    GI.ch.lines('rf-lg', [{ name: 'League', x: yrs, y: yrs.map(y => L[String(y)]), symbol: true, area: true }], { legend: false, xName: 'Season', yName: 'Penalties a game', yFmt: v => GI.num(v, 0), xFmt: String, xLabel: String });
    const car = () => {
      const x = R[RST.ref];
      GI.set('rf-name', esc(RST.ref));
      const ss = ((x && x.seasons) || []).filter(z => z.games > 0).sort((a, b) => a.season - b.season);
      if (ss.length < 1) { GI.ch.none('rf-car', 'No seasons on record.'); return; }
      GI.ch.lines('rf-car', [{ name: RST.ref, x: ss.map(z => z.season), y: ss.map(z => z.penalties_pg), symbol: true }, { name: 'League', x: ss.map(z => z.season), y: ss.map(z => L[String(z.season)]), dash: true, colour: QK.cssVar('--ink-3') }],
        { xName: 'Season', yName: 'Penalties a game', yFmt: v => GI.num(v, 0), xFmt: String, xLabel: String });
    };
    car();
    el.querySelectorAll('[data-ref]').forEach(b => b.addEventListener('click', () => { RST.ref = b.getAttribute('data-ref'); car(); const t = document.getElementById('rf-car'); if (t) t.scrollIntoView({ block: 'center', behavior: 'smooth' }); }));
  });
});

/* ── draft prospects from the Campus site ─────────────────────────────── */
function campusBase() {
  const p = location.pathname || '';
  return /\/the-quant-gridiron\//.test(p) ? p.replace(/\/the-quant-gridiron\/.*$/, '/the-quant-campus/') : '../campus/';
}
const PST = { pos: 'ALL' };
const ELIG = { SR: 'Senior', JR: 'Junior' };
GI.route('prospects', function (el) {
  const B = campusBase(), S = GI.currentSeason();
  const head = GI.pageHead('Scouting Room · ' + S, 'Draft prospects', 'The best draft-eligible college players this season (juniors and seniors) by The Quant Campus’s value model, position by position. Each name opens the player’s page on Campus.') + GI.sectionNav('scout', 'prospects');
  el.innerHTML = head + '<div id="pr-body">' + QK.skeleton('lines', 4) + '</div>';
  const get = f => fetch(B + 'data/cfb/' + S + '/' + f, { cache: 'no-cache' }).then(r => (r.ok ? r.json() : null)).catch(() => null);
  return Promise.all([get('value.json'), get('teams.json')]).then(res => {
    if (!el.isConnected) return;
    const v = res[0], t = res[1];
    if (!v || v.ok === false) { GI.set('pr-body', QK.empty('Campus is not built for ' + S, 'The prospect board reads The Quant Campus’s college value file, which is not available right now.')); return; }
    const T = (t && t.teams) || {};
    const rows = [];
    const seen = {};
    const add = r => { if (!r || !r.id || seen[r.id] || !ELIG[String(r.class || '').toUpperCase()]) return; seen[r.id] = 1; rows.push(r); };
    (v.leaders || []).forEach(add);
    Object.keys(v.by_position || {}).forEach(k => (Array.isArray(v.by_position[k]) ? v.by_position[k] : []).forEach(add));
    const POS = ['ALL'].concat(Object.keys(v.by_position || {}).filter(k => rows.some(r => r.pos === k)));
    if (POS.indexOf(PST.pos) < 0) PST.pos = 'ALL';
    const unit = ((v.currency || {}).label) || 'Value';
    const draw = () => {
      const list = rows.filter(r => PST.pos === 'ALL' || r.pos === PST.pos).sort((a, b) => (PST.pos === 'ALL' ? ((b.pctl || 0) - (a.pctl || 0)) : 0) || (b.value || 0) - (a.value || 0)).slice(0, 60);   /* values compare within a position: every position at once ranks on the percentile */
      const link = r => '<a href="' + esc(B + '#/cfb/player/' + encodeURIComponent(r.id)) + '">' + esc(r.name) + '</a>';
      const top = list.slice(0, 5).map(r => ({ sport: 'college', kicker: r.pos + ' · ' + (ELIG[String(r.class).toUpperCase()] || r.class), name: r.name, title: (T[r.team] || {}).name || '', value: GI.num(r.value, 1), href: B + '#/cfb/player/' + encodeURIComponent(r.id), expl: r.why || '' }));
      GI.set('pr-body', GI.seg('pr-pos', POS.map(p => [p, p === 'ALL' ? 'Every position' : p]), PST.pos, 'Position') +
        (top.length ? QK.band(QK.sectionHead({ kicker: 'Top of the board', title: PST.pos === 'ALL' ? 'The five best, each against their position' : 'The best ' + PST.pos + 's', sub: unit + ' this season, our college value model' + (PST.pos === 'ALL' ? '; across positions they are ranked on the percentile, since the values compare within a position.' : '.') }) + QK.hotRow(top)) : '') +
        GI.card('The board', list.length + ' draft-eligible players · ' + esc(unit) + ' (' + esc(((v.currency || {}).desc || '').slice(0, 140)) + ')', GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Pos' }, { label: 'Class' }, { label: 'School' }, { label: 'Games', align: 'right' }, { label: 'Value', align: 'right' }, { label: 'A game', align: 'right' }, { label: 'Percentile', align: 'right', title: 'Among the position in college this season' }, { label: 'The season', sortable: false }],
          list.map((r, i) => [i + 1, { html: link(r), v: r.name }, r.pos, ELIG[String(r.class).toUpperCase()] || r.class, esc((T[r.team] || {}).name || r.team), r.gp, { html: '<b class="gi-ours">' + GI.num(r.value, 1) + '</b>', v: r.value }, { html: GI.num(r.value_pg, 2), v: r.value_pg },
            { html: isNum(r.pctl) ? QK.pctlChip(r.pctl) : '—', v: r.pctl }, { html: '<span class="qk-sub">' + esc(r.why || '') + '</span>' }]), { sticky: true, maxHeight: 720 }), { flush: true }) +
        QK.explain('College production is a guide to the draft, not a forecast of it: the NFL drafts on traits, size and speed as much as numbers, and a junior may stay in school. Juniors and seniors only (draft-eligible), from the top of each position in our college value model. More on <a href="' + esc(B + '#/cfb/value') + '">The Quant Campus</a>.', { title: 'How to read it' }));
      GI.sortable(el);
      GI.wireSeg(el, 'pr-pos', x => { PST.pos = x; draw(); });
    };
    draw();
  });
});

})(window.GI);
