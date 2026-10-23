/* The Quant Ace — the match centre (#/<T>/match/<mid>).
 *
 *   head: event, round, surface, the score by set (tiebreaks in superscript), status;
 *   kit v3 hero (QK.previewCard): both players with ranking and country, the score in sets (the score bug when live),
 *     our chance for the favourite as a big teal number with a "how sure" note, the bar, the market as a quiet labelled
 *     line before the first ball, and how the two match up (Elo, surface Elo, inferred hold and serve points); beside
 *     it the set-by-set board, stat tiles (our chance, likeliest score, expected games) and our forecast table;
 *   before the match: our forecast and its components (Elo, serve/return, the market-rating term), with the
 *     prediction markets and the closing line beside it as a named reference (the one place outside the Model pages
 *     where the market appears);
 *     set-score, total-games and game-handicap distributions from the exact Markov chain;
 *     the serve/return matchup (hold % and serve points won, inferred from scores); head to head;
 *   live and after: win probability game by game with set boundaries and the biggest swings,
 *     excitement and comeback; a stats comparison (real WTA statistics where they exist,
 *     otherwise the inferred serve/return numbers, labelled as such); the charting deep dive
 *     (Match Charting Project, CC BY-NC-SA 4.0) when the match is charted; awards.
 *
 * Reads <T>/matches/<mid>.json (PAYLOADS.md); falls back to the MATCH_CARD in index.json or
 * the tournament payload when the match file is not built. */
(function (TA) {
'use strict';

const esc = TA.esc;
const isNum = TA.isNum;

function ratio(a, b) { return isNum(a) && isNum(b) && b > 0 ? a / b : null; }

/* STATS (CONTRACT.md) -> derived rates for one side, given the opponent's STATS. */
function rates(s, o) {
  if (!s) return {};
  const svp = s.sv_pts, osv = (o || {}).sv_pts;
  const won = isNum(s.fs_won) && isNum(s.ss_won) ? s.fs_won + s.ss_won : null;
  const spw = ratio(won, svp);
  const rpw = ratio(s.rt_pts_won, osv);
  return {
    aces: s.aces, dfs: s.dfs, ace_pct: ratio(s.aces, svp), df_pct: ratio(s.dfs, svp),
    fs_in: ratio(s.fs_in, svp), fs_won: ratio(s.fs_won, s.fs_in), ss_won: ratio(s.ss_won, isNum(svp) && isNum(s.fs_in) ? svp - s.fs_in : null),
    spw: spw, rpw: rpw, tpw: isNum(won) && isNum(s.rt_pts_won) && isNum(svp) && isNum(osv) ? (won + s.rt_pts_won) / (svp + osv) : null,
    dr: isNum(rpw) && isNum(spw) && spw < 1 ? rpw / (1 - spw) : null,
    bp_saved: s.bp_saved, bp_faced: s.bp_faced, bp_conv: s.bp_conv, bp_opps: s.bp_opps, sv_gms: s.sv_gms,
    hold: isNum(s.sv_gms) && isNum(s.bp_faced) && isNum(s.bp_saved) && s.sv_gms > 0 ? 1 - (s.bp_faced - s.bp_saved) / s.sv_gms : null
  };
}

function vsRow(label, a, b, fmt, opts) {
  const o = opts || {};
  const f = v => (typeof fmt === 'function' ? fmt(v) : TA.fmtVal(v, fmt));
  const na = isNum(a) ? Number(a) : null, nb = isNum(b) ? Number(b) : null;
  const better = na !== null && nb !== null && na !== nb ? ((na > nb) !== !!o.lower ? 'a' : 'b') : '';
  let bars = '';
  if (na !== null && nb !== null && na + nb > 0 && na >= 0 && nb >= 0) {
    const wa = na / (na + nb) * 100;
    bars = '<div class="vs-bars"><span style="width:' + wa.toFixed(1) + '%;background:' + TA.C.p1 + '"></span><span style="width:' + (100 - wa).toFixed(1) + '%;background:' + TA.C.p2 + '"></span></div>';
  }
  return '<div class="vs-row"' + (o.title ? ' title="' + esc(o.title) + '"' : '') + '><span class="vs-v' + (better === 'a' ? ' better' : '') + '">' + (o.textA !== undefined ? o.textA : f(a)) + '</span>' +
    '<span class="vs-mid">' + esc(label) + bars + '</span><span class="vs-v r' + (better === 'b' ? ' better' : '') + '">' + (o.textB !== undefined ? o.textB : f(b)) + '</span></div>';
}
function vsHead(T, p1, p2) {
  return '<div class="vs-head"><span>' + TA.playerLink(T, p1, { surname: true }) + '</span><span>' + TA.playerLink(T, p2, { surname: true }) + '</span></div>';
}

function frac(n, d) { return isNum(n) && isNum(d) ? n + '/' + d : '—'; }

function statsBlock(T, d, which) {
  const st = d.stats;
  let s1, s2;
  if (which === 'all') { s1 = st.p1; s2 = st.p2; } else {
    const bs = (st.by_set || []).find(x => String(x.set) === String(which)) || {};
    s1 = bs.p1; s2 = bs.p2;
  }
  if (!s1 || !s2) return TA.muted('No statistics for this set.');
  const a = rates(s1, s2), b = rates(s2, s1);
  return vsHead(T, d.p1, d.p2) + '<div class="vs-rows">' +
    vsRow('Aces', a.aces, b.aces, 'int') + vsRow('Double faults', a.dfs, b.dfs, 'int', { lower: true }) +
    vsRow('1st serve in', a.fs_in, b.fs_in, 'pct') + vsRow('1st serve points won', a.fs_won, b.fs_won, 'pct') +
    vsRow('2nd serve points won', a.ss_won, b.ss_won, 'pct') + vsRow('Serve points won', a.spw, b.spw, 'pct') +
    vsRow('Return points won', a.rpw, b.rpw, 'pct') + vsRow('Total points won', a.tpw, b.tpw, 'pct') +
    vsRow('Dominance ratio', a.dr, b.dr, '2', { title: 'Return points won divided by serve points lost; above 1 means winning more than you concede' }) +
    vsRow('Break points saved', ratio(a.bp_saved, a.bp_faced), ratio(b.bp_saved, b.bp_faced), 'pct', { textA: frac(a.bp_saved, a.bp_faced), textB: frac(b.bp_saved, b.bp_faced) }) +
    vsRow('Break points converted', ratio(a.bp_conv, a.bp_opps), ratio(b.bp_conv, b.bp_opps), 'pct', { textA: frac(a.bp_conv, a.bp_opps), textB: frac(b.bp_conv, b.bp_opps) }) +
    vsRow('Service games', a.sv_gms, b.sv_gms, 'int') + '</div>';
}

function inferredBlock(T, d) {
  const inf = d.inferred || {}, sr = (d.pre || {}).sr || {};
  const hold = inf.hold || sr.hold || [], spw = inf.spw || sr.p_srv || [];
  if (!hold.length && !spw.length) return TA.muted('No serve or return numbers for this match.');
  const won = TA.setsWon(d);
  const games = (d.sets || []).reduce((acc, s) => { acc[0] += s[0] || 0; acc[1] += s[1] || 0; return acc; }, [0, 0]);
  return vsHead(T, d.p1, d.p2) + '<div class="vs-rows">' +
    vsRow('Hold % (inferred)', hold[0], hold[1], 'pct', { title: 'Probability of holding serve against this opponent, from the serve/return model fitted on game and set scores' }) +
    vsRow('Break % (inferred)', isNum(hold[1]) ? 1 - hold[1] : null, isNum(hold[0]) ? 1 - hold[0] : null, 'pct') +
    vsRow('Serve points won (inferred)', spw[0], spw[1], 'pct', { title: 'Serve-point win probability implied by the hold probability (the game formula inverted)' }) +
    (d.sets && d.sets.length ? vsRow('Sets', won[0], won[1], 'int') + vsRow('Games', games[0], games[1], 'int') : '') + '</div>' +
    '<div class="label-note"><span class="scope-tag inferred">inferred</span> ' + (d.stats && d.stats.p1
      ? 'The model’s pre-match expectations, inferred from game and set scores across each player’s matches. The real point-by-point numbers for this match are below.'
      : 'No point-by-point statistics exist for this match' + (TA.state.tour === 'atp' ? ' (the ATP publishes none we can use; ATP matches the Match Charting Project has charted show its numbers)' : '') +
        '. These numbers are the model’s serve and return strengths, inferred from game and set scores across each player’s matches — estimates, not measurements.') + '</div>';
}

function chartingBlock(T, d) {
  const c = d.charting;
  if (!c) return '';
  let h = '';
  const sides = [['p1', d.p1], ['p2', d.p2]];
  if (c.serve_dir) {
    const keys = ['wide', 'body', 't'];
    h += '<div><div class="day-head">Serve direction</div>' + TA.tableHTML([{ label: 'Player' }].concat(keys.map(k => ({ label: k === 't' ? 'T' : TA.titleCase(k), align: 'right' }))),
      sides.map(s => [{ html: TA.playerLink(T, s[1], { surname: true }) }].concat(keys.map(k => ({ v: ((c.serve_dir[s[0]] || {})[k]), html: TA.fmtVal((c.serve_dir[s[0]] || {})[k], 'pct') })))), { compact: true }) + '</div>';
  }
  if (c.rally) {
    const keys = Object.keys(c.rally.p1 || c.rally.p2 || {});
    h += '<div><div class="day-head">Rally length (shots)</div>' + TA.tableHTML([{ label: 'Player' }].concat(keys.map(k => ({ label: k, align: 'right' }))),
      sides.map(s => [{ html: TA.playerLink(T, s[1], { surname: true }) }].concat(keys.map(k => ({ v: (c.rally[s[0]] || {})[k], html: TA.fmtVal((c.rally[s[0]] || {})[k], 'pct') })))), { compact: true }) + '</div>';
  }
  if (c.outcomes) {
    const lab = { winners: 'Winners', ufe: 'Unforced errors', fe: 'Forced errors', aces: 'Aces' };
    const keys = Object.keys(c.outcomes.p1 || {});
    h += '<div><div class="day-head">Shot outcomes</div>' + vsHead(T, d.p1, d.p2) + '<div class="vs-rows">' +
      keys.map(k => vsRow(lab[k] || TA.titleCase(k), (c.outcomes.p1 || {})[k], (c.outcomes.p2 || {})[k], 'int', { lower: k === 'ufe' })).join('') + '</div></div>';
  }
  if (c.net) {
    h += '<div><div class="day-head">At the net</div>' + vsHead(T, d.p1, d.p2) + '<div class="vs-rows">' +
      vsRow('Net points won', ratio((c.net.p1 || [])[1], (c.net.p1 || [])[0]), ratio((c.net.p2 || [])[1], (c.net.p2 || [])[0]), 'pct',
        { textA: frac((c.net.p1 || [])[1], (c.net.p1 || [])[0]), textB: frac((c.net.p2 || [])[1], (c.net.p2 || [])[0]) }) + '</div></div>';
  }
  return TA.card('Charting deep dive', (isNum(c.points) ? c.points + ' charted points · ' : '') + 'shot by shot',
    '<div class="ch-grid">' + h + '</div><div class="label-note"><span class="scope-tag charted">charted</span> From the <a href="https://github.com/JeffSackmann/tennis_MatchChartingProject" target="_blank" rel="noopener">Match Charting Project</a> ' +
    '(volunteer shot-by-shot charting), licensed <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>; these derived figures are shared alike.</div>');
}

function awardsBlock(T, d) {
  const aw = d.awards || {};
  const keys = Object.keys(aw).filter(k => aw[k] && (!Array.isArray(aw[k]) || aw[k].length));
  if (!keys.length) return '';
  const label = { upset: 'Upset', comeback: 'Comeback', dominant: 'Dominant', clutch: 'Clutch', excitement: 'Thriller', tiebreaks: 'Tiebreaks' };
  const tiles = [];
  keys.forEach(k => {
    const a = aw[k];
    if (Array.isArray(a)) {
      a.forEach(x => {
        const who = x.winner || x.pid;
        const exp = isNum(x.p1_exp) ? (who === d.p2 ? 1 - x.p1_exp : x.p1_exp) : null;
        tiles.push('<div class="award"><span class="aw-title">' + esc((label[k] || TA.titleCase(k)) + (x.set ? ' · set ' + x.set : '')) + '</span><span class="aw-who">' + (who ? TA.playerLink(T, who) : '—') + '</span>' +
          (exp !== null ? '<span class="aw-val">won it at ' + TA.pct(exp, 0) + ' expected</span>' : '<span class="aw-val">' + esc(TA.awardValue(x)) + '</span>') + '</div>');
      });
      return;
    }
    const who = a.pid || a.winner || a.player;
    const val = TA.awardValue(a);
    tiles.push('<div class="award"><span class="aw-title">' + esc(label[k] || TA.titleCase(k)) + '</span><span class="aw-who">' + (who ? TA.playerLink(T, who) : '—') + '</span>' +
      (val ? '<span class="aw-val">' + esc(val) + '</span>' : '') + (a.why ? '<span class="aw-why">' + esc(a.why) + '</span>' : '') + '</div>');
  });
  return TA.card('Match awards', 'the moments that stood out', '<div class="awards">' + tiles.join('') + '</div>');
}

/* The board: one row per player with set cells and the pre-match probability. */
function board(T, d, p1) {
  const sets = d.sets || [];
  const lv = d.live || null;
  const live = TA.matchState(d) === 'live';
  const fin = TA.isFinished(d);
  const extra = live && lv && lv.games && sets.length < (lv.set || sets.length + 1);
  const row = (pid, side, p) => {
    let cells = '';
    sets.forEach(s => {
      const g = s[side], og = s[1 - side], tb = s[2 + side];
      cells += '<span class="mt-set' + (g > og ? ' won' : '') + '">' + g + (isNum(tb) && g < og ? '<sup>' + tb + '</sup>' : '') + '</span>';
    });
    if (extra) cells += '<span class="mt-set cur">' + lv.games[side] + '</span>';
    const lost = fin && d.winner && d.winner !== pid;
    const cc = TA.playerCountry(T, pid), rk = TA.playerRank(T, pid);
    return '<div class="mt-pl' + (lost ? ' lost' : '') + '"><span class="mt-sw" style="background:' + (side ? 'var(--wp-b)' : 'var(--wp-a)') + '"></span><span class="mt-name">' +
      (rk ? '<span class="seed">' + rk + '</span>' : '') + TA.playerLink(T, pid) + (cc ? '<span class="ctry">' + esc(cc) + '</span>' : '') + (fin && d.winner === pid ? ' ✓' : '') + '</span></div>' +
      '<div class="mt-sets">' + cells + '</div><span class="mt-p" title="Our pre-match win chance">' + (isNum(p) ? TA.pct(p, 0) : '') + '</span>';
  };
  return '<div class="mt-board">' + row(d.p1, 0, p1) + row(d.p2, 1, isNum(p1) ? 1 - p1 : null) + '</div>';
}

function preBoxes(T, d) {
  const pre = d.pre || {}, m = pre.model || {}, mk = pre.market || null, cl = pre.closing || null;
  const p1 = isNum(m.p1_win) ? m.p1_win : (m.dist || {}).p1_win;
  const ps = cl ? TA.devig2(cl.ps) : null, avg = cl ? (TA.devig2(cl.avg) || (isNum(cl.p1) ? cl.p1 : null)) : null;
  const sA = TA.playerSurname(T, d.p1), sB = TA.playerSurname(T, d.p2);
  // schedule and form (rest, recent load, ranking points, form, a retirement last time, head to head): our chance
  // with them minus our chance without them, for the first-named player
  const xs = isNum(m.x_dot) && isNum(p1) && m.x_dot !== 0 ? p1 - 1 / (1 + Math.exp(-(Math.log(p1 / (1 - p1)) - m.x_dot))) : null;
  const row = (label, p, cls, tip) => (isNum(p) ? '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td' + (tip ? ' data-tip="' + esc(tip) + '" tabindex="0"' : '') + '>' + label + '</td><td class="num">' + TA.pct(p, 0) + '</td><td class="num">' + TA.pct(1 - p, 0) + '</td></tr>' : '');
  const ours = row('<b>Our chance</b>', p1, 'ours', 'The blend the match centre publishes') +
    row('Elo alone', m.elo_p, 'comp', 'Our surface-blended Elo, on its own') + row('Serve and return alone', m.sr_p, 'comp', 'The exact Markov chain fed with the inferred serve and return strengths') +
    row('Market rating alone', m.mr_p, 'comp', 'A model term: each player\u2019s strength as the closing market rated it in earlier matches, never this match\u2019s own number');
  const ref = (mk && isNum(mk.p1) ? row('Market (' + esc(TA.sourceNames(mk.sources).join(' / ') || 'prediction markets') + ')', mk.p1, 'mkt', 'De-vigged, shown for reference') : '') +
    row(isNum(ps) ? 'Closing line (Pinnacle, no-vig)' : 'Closing line (bookmakers\u2019 average, no-vig)', isNum(ps) ? ps : avg, 'mkt', 'From tennis-data.co.uk after the match; shown for reference');
  return '<div class="qk-table-wrap"><table class="qk-table dense ta-fc"><thead><tr><th></th><th class="num">' + esc(sA) + '</th><th class="num">' + esc(sB) + '</th></tr></thead><tbody>' + ours +
    (ref ? '<tr class="sep"><td colspan="3">For reference</td></tr>' + ref : '') + '</tbody></table></div>' +
    (isNum(xs) ? '<div class="section-note">Schedule and form (rest, recent load, ranking points, form, head to head) move ' + esc(sA) + ' by ' + TA.signed(100 * xs, 1) + ' points.</div>' : '') +
    (!isNum(m.mr_p) && isNum(m.blend_w) ? '<div class="section-note">Blend weight on Elo ' + TA.num(m.blend_w, 2) + '.</div>' : '');
}

/* v3 (Matchday) hero: QK.previewCard on the kit shape (p1 on the left, p2 on the right; tennis has no home side, so
   the card reads "v", not "at"). The market appears here only before the first ball, as a quiet labelled line. */
function hero(T, d, p1, ev, surface) {
  const st = TA.matchState(d), fin = TA.isFinished(d), live = st === 'live', pre = !fin && !live;
  const mk = (d.pre || {}).market || null;
  const G = TA.kitGame(d, T, { initials: true });
  G.p_home = isNum(p1) ? 1 - p1 : null;
  if (live && isNum(d.wp_now)) { G.wp_home = 1 - d.wp_now; G.pre_only = undefined; }
  const rec = pid => { const rk = TA.playerRank(T, pid), cc = TA.playerCountry(T, pid); return [isNum(rk) ? 'No. ' + rk : 'Unranked', cc].filter(Boolean).join(' · '); };
  G.away.record = rec(d.p1); G.home.record = rec(d.p2);
  // how they match up: ratings and the inferred serve numbers, the better side in teal
  const e = (d.pre || {}).elo || {}, ea = e.p1 || {}, eb = e.p2 || {};
  const sf = surface && surface !== 'all' ? surface : null;
  const sa = isNum(ea.surface) ? ea.surface : (sf ? ea[sf] : null), sb = isNum(eb.surface) ? eb.surface : (sf ? eb[sf] : null);
  const inf = d.inferred || {}, sr = (d.pre || {}).sr || {};
  const hold = inf.hold || sr.hold || [], spw = inf.spw || sr.p_srv || [];
  const fx = [];
  const add = (label, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: label, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
  add('Elo rating', ea.all, eb.all, v => TA.num(v, 0));
  if (sf) add(TA.surfaceLabel(sf) + ' Elo', sa, sb, v => TA.num(v, 0));
  add('Hold % (inferred)', hold[0], hold[1], v => TA.pct(v, 0));
  add('Serve points won (inferred)', spw[0], spw[1], v => TA.pct(v, 1));
  add('Ranking', TA.playerRank(T, d.p1), TA.playerRank(T, d.p2), v => 'No. ' + v, true);
  const dist = ((d.pre || {}).model || {}).dist || {};
  const top = Object.keys(dist.sets || {}).sort((x, y) => dist.sets[y] - dist.sets[x])[0];
  let note;
  if (!fin && isNum(p1)) {
    const fav = p1 >= 0.5 ? d.p1 : d.p2, pf = live && isNum(d.wp_now) ? (fav === d.p1 ? d.wp_now : 1 - d.wp_now) : Math.max(p1, 1 - p1);
    const miss = Math.max(1, Math.round(10 * (1 - pf)));
    note = '<b>How sure are we?</b> ' + TA.pct(pf, 0) + ' means ' + esc(TA.playerShort(T, fav)) + ' loses a match like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.' +
      (pre && top ? ' The likeliest score is ' + esc(top) + ' in sets (' + TA.pct(dist.sets[top], 0) + ', ' + esc(TA.playerSurname(T, d.p1)) + ' first)' + (isNum(dist.exp_games) ? ', with about ' + Math.round(dist.exp_games) + ' games in all.' : '.') : '');
  }
  else if (fin && isNum(p1)) {
    const fav = p1 >= 0.5 ? d.p1 : d.p2;
    note = 'Our pre-match call: <b>' + esc(TA.playerShort(T, fav)) + ' ' + TA.pct(Math.max(p1, 1 - p1), 0) + '</b>. ' + esc(QK.whyLine(G));
  }
  const kick = [TA.tourName(T), TA.eventName(T, d.event), TA.roundLabel(d.round), TA.surfaceLabel(surface, ev.indoor)].filter(Boolean).join(' · ');
  const card = QK.previewCard(G, { kicker: kick, nick: t => t.name, factors: fx, factorsTitle: 'How they match up', note: note,
    market: pre && mk && isNum(mk.p1) ? { p: 1 - mk.p1, label: 'Market (' + (TA.sourceNames(mk.sources).join(' / ') || 'prediction markets') + ')' } : null }).replace('<div class="at">at</div>', '<div class="at">v</div>');
  const tba = d.tba || String(d.date || '').length <= 10;
  const meta = [ev.level ? TA.levelLabel(ev.level, T) : '', d.best_of ? 'Best of ' + d.best_of : '',
    pre ? TA.fmtDate(d.date, { year: false }) + (tba ? ', time to be announced' : ' ' + TA.fmtTime(d.date) + ' your time') : TA.fmtDate(d.date, { year: false }), isNum(d.duration_min) ? TA.fmtDuration(d.duration_min) : ''].filter(Boolean);
  return '<div class="ta-preview">' + card + '<div class="ta-hero-meta">' + meta.map(x => '<span>' + esc(x) + '</span>').join('') + '<a href="' + TA.h2hHref(T, d.p1, d.p2) + '">Head to head →</a></div></div>';
}

function render(el, params) {
  const T = params.tour, id = params.id;
  el.innerHTML = '<div class="muted">Loading the match…</div>';
  const eid = String(id).replace(/-(Q[123]|R128|R64|R32|R16|RR|QF|SF|BR|F)-.*$/, '');
  return TA.load(TA.matchPath(T, id)).then(d0 => {
    if (!el.isConnected) return null;
    if (TA.ok(d0)) return d0;
    // fall back to the card in index.json or the tournament payload
    const info = TA.tourInfo(T);
    const all = [].concat(info.live || [], info.today || [], info.upcoming || [], info.recent || []);
    const hit = all.find(c => c.id === id);
    if (hit) return Object.assign({ _card: true }, hit);
    return TA.load(TA.eventPath(T, eid)).then(ev => {
      const c = ev && ev.draw && ev.draw.matches ? ev.draw.matches[id] : null;
      return c ? Object.assign({ _card: true }, c) : { ok: false, reason: d0 && d0.reason ? d0.reason : 'not built for this match' };
    });
  }).then(d => {
    if (!el.isConnected || !d) return;
    if (!TA.ok(d)) {
      el.innerHTML = QK.sectionHead({ kicker: TA.eventName(T, eid), title: 'Match centre', size: 'lg', tag: 'h1', actions: '<a class="qk-btn" href="' + TA.eventHref(T, eid) + '">' + esc(TA.eventName(T, eid)) + '</a>' }) + TA.card('Match', '', TA.notBuilt('This match', d));
      return;
    }
    const ev = TA.eventInfo(T, d.event || eid);
    const surface = d.surface || ev.surface;
    if (d.level && !ev.level) ev.level = d.level;
    if (d.indoor !== undefined && ev.indoor === undefined) ev.indoor = d.indoor;
    const pre = d.pre || {}, m = pre.model || {};
    const dist = m.dist || {};
    const p1 = isNum(m.p1_win) ? m.p1_win : (isNum(dist.p1_win) ? dist.p1_win : (d.model || {}).p1);
    const st = TA.matchState(d);
    const fin = TA.isFinished(d);

    // ── hero and stat tiles
    const live0 = TA.matchState(d) === 'live';
    const tiles = [];
    if (isNum(p1)) tiles.push({ label: fin ? 'Our pre-match chance' : 'Our chance', value: TA.playerSurname(T, p1 >= 0.5 ? d.p1 : d.p2) + ' ' + TA.pct(Math.max(p1, 1 - p1), 0), signal: true, sub: 'Elo, serve and return and the market-rating term, blended' });
    if (live0 && isNum(d.wp_now)) tiles.push({ label: 'Live chance', value: TA.playerSurname(T, d.wp_now >= 0.5 ? d.p1 : d.p2) + ' ' + TA.pct(Math.max(d.wp_now, 1 - d.wp_now), 0), sub: 'updates after every game' });
    const top = Object.keys(dist.sets || {}).sort((x, y) => dist.sets[y] - dist.sets[x])[0];
    if (top) tiles.push({ label: 'Likeliest score', value: top, sub: TA.pct(dist.sets[top], 0) + ' · sets, ' + TA.playerSurname(T, d.p1) + ' first' });
    if (isNum(dist.exp_games)) tiles.push({ label: 'Expected games', value: TA.num(dist.exp_games, 1), sub: isNum(dist.p_tiebreak) ? 'at least one tiebreak ' + TA.pct(dist.p_tiebreak, 0) : '' });
    if (isNum(dist.p_straight)) tiles.push({ label: 'Straight sets', value: TA.pct(dist.p_straight, 0), sub: 'either player' });
    const boardH = (d.sets || []).length || live0 ? '<section class="qk-card"><div class="qk-card-body"><div class="qk-kicker" style="margin-bottom:8px">Set by set</div>' + board(T, d, p1) + '</div></section>' : '';
    el.innerHTML = '<div class="ta-gtop">' + hero(T, d, p1, ev, surface) + '<div class="ta-gside ta-stack">' + boardH + (tiles.length ? '<div class="ta-kpis">' + QK.stats(tiles) + '</div>' : '') +
      (d._card ? '' : V2card(fin || st === 'live' ? 'Our forecast before the match' : 'Our forecast', 'Our chance and how it is built. The market and the closing line sit underneath as a reference, not our forecast.', preBoxes(T, d))) + '</div></div>' + '<div id="mt-body" style="margin-top:var(--sp-6)"></div>';
    const body = document.getElementById('mt-body');
    if (d._card) {
      body.innerHTML = TA.card('Match centre', '', TA.muted('The full match centre for this match is not built yet; the score and our pre-match chance come from the schedule.' +
        ((d.model && d.model.sets_dist_top) ? ' Likeliest set scores: ' + d.model.sets_dist_top.map(x => esc(x[0]) + ' ' + TA.pct(x[1], 0)).join(', ') + '.' : '')));
      return;
    }

    let html = '';
    // ── live / after: win probability first
    const wpRows = d.wp || [];
    if (wpRows.length > 1) {
      html += TA.card('How the match swung', (fin ? 'our win chance after every game' : 'our win chance, updated after every game') + (d.reconstructed ? ' · game order within sets reconstructed from the set scores' : ''),
        '<div id="mt-wp"></div><div class="grid-2" style="padding:0 12px 12px;gap:12px"><div id="mt-tiles" class="kpi-grid three"></div><div id="mt-swings"></div></div>');
    }
    // ── before the match
    html += '<div class="grid-2"><div>' + TA.card('How it could finish', 'our chance of each score in sets, from the serve-point chances game by game' + (fin ? ' · outlined: what happened' : ''), '<div id="mt-sets"></div>' +
      '<div class="section-note">' + (isNum(dist.p_straight) ? 'Straight sets ' + TA.pct(dist.p_straight, 0) : '') + (isNum(dist.p_tiebreak) ? ' · at least one tiebreak ' + TA.pct(dist.p_tiebreak, 0) : '') + '</div>') + '</div><div>' +
      TA.card('How many games', 'our chance of each total, and of each winning margin in games', '<div class="toggle-row" id="mt-gt">' + TA.toggles([{ key: 'games', label: 'Total games' }, { key: 'handicap', label: 'Game handicap' }], 'games', 'data-gt') + '</div><div id="mt-games"></div><div class="section-note" id="mt-games-note"></div>') + '</div></div>';
    // ── matchup and h2h
    html += '<div class="grid-2"><div>' + TA.card('Serve against return', 'how each holds and breaks against this opponent on ' + esc(TA.surfaceLabel(surface, ev.indoor).toLowerCase()), inferredBlock(T, d) + eloRows(T, d, surface)) + '</div><div>' + h2hCard(T, d) + '</div></div>';
    // ── stats
    if (d.stats && d.stats.p1) {
      const sets = (d.stats.by_set || []).map(x => x.set);
      html += TA.card('The numbers', d.stats_source === 'charting' ?
        '<span class="scope-tag charted">charted</span> point by point, from the <a href="https://github.com/JeffSackmann/tennis_MatchChartingProject" target="_blank" rel="noopener">Match Charting Project</a> (CC BY-NC-SA 4.0)' :
        '<span class="scope-tag real">real</span> point by point, from the WTA',
        (sets.length ? '<div class="toggle-row" id="mt-st">' + TA.toggles([{ key: 'all', label: 'Match' }].concat(sets.map(s => ({ key: String(s), label: 'Set ' + s }))), 'all', 'data-st') + '</div>' : '') + '<div id="mt-stats"></div>');
    }
    html += chartingBlock(T, d);
    html += awardsBlock(T, d);
    body.innerHTML = html;

    if (wpRows.length > 1) {
      TA.charts.wpChart('mt-wp', wpRows, { tour: T, p1: d.p1, p2: d.p2, swings: d.swings, market: pre.market && isNum(pre.market.p1) ? pre.market.p1 : null });
      const cb = d.comeback || {};
      document.getElementById('mt-tiles').innerHTML = TA.statTile('Excitement', isNum(d.excitement) ? TA.num(d.excitement, 2) : '—', 'sum of every swing in win probability') +
        TA.statTile('Comeback', isNum(cb.min_p) ? TA.pct(cb.min_p, 0) : '—', isNum(cb.min_p) ? 'the winner’s lowest chance' + (cb.games ? ', at ' + esc(cb.games.join('-')) + ' in set ' + esc(cb.set || ((cb.sets || [0, 0])[0] + (cb.sets || [0, 0])[1] + 1)) : '') : '') +
        TA.statTile('Our pre-match chance', isNum(p1) ? TA.pct(Math.max(p1, 1 - p1), 0) : '—', isNum(p1) ? esc(TA.playerSurname(T, p1 >= 0.5 ? d.p1 : d.p2)) + ' favoured' : '');
      const sw = (d.swings || []).slice(0, 5);
      document.getElementById('mt-swings').innerHTML = sw.length ? '<div class="day-head" style="padding-left:0">Biggest swings</div><div class="swing-list">' + sw.map((s, i) => {
        const who = s.winner === 0 || s.winner === 1 ? (s.winner === 0 ? d.p1 : d.p2) : (s.delta > 0 ? d.p1 : d.p2);
        return '<div class="swing-row"><span class="swing-n">' + (i + 1) + '</span><span>' + esc(TA.playerSurname(T, who)) + ' ' + esc(kindText(s.kind)) + ' · set ' + esc(s.set) + (s.games ? ' at ' + esc(s.games.join('-')) : '') + '</span>' +
          '<span class="swing-d ' + (s.delta > 0 ? 'edge-pos' : 'edge-neg') + '">' + TA.signed((s.delta || 0) * 100, 1) + '</span></div>';
      }).join('') + '</div>' : '';
    }
    const actual = fin && d.sets && d.sets.length && TA.matchState(d) === 'done' ? TA.setsWon(d).join('-') : null;
    TA.charts.setDist('mt-sets', dist.sets || {}, { tour: T, p1: d.p1, p2: d.p2, actual: actual });
    const showGames = k => {
      const games = k === 'handicap';
      const note = document.getElementById('mt-games-note');
      if (games) {
        TA.charts.gamesDist('mt-games', dist.handicap || {}, { signed: true, xTitle: TA.playerSurname(T, d.p1) + ' games minus ' + TA.playerSurname(T, d.p2), colour: 'b',
          actual: actual ? sumSide(d, 0) - sumSide(d, 1) : null });
        note.innerHTML = 'Positive: ' + esc(TA.playerSurname(T, d.p1)) + ' wins more games. The highlighted bar is the final margin.';
      } else {
        TA.charts.gamesDist('mt-games', dist.games || {}, { exp: dist.exp_games, xTitle: 'Total games in the match', actual: actual ? TA.totalGames(d) : null });
        note.innerHTML = isNum(dist.exp_games) ? 'Expected ' + TA.num(dist.exp_games, 1) + ' games (dashed line)' + (actual ? '; the highlighted bar is what happened (' + TA.totalGames(d) + ').' : '.') : '';
      }
    };
    showGames('games');
    TA.wireToggles(document.getElementById('mt-gt'), 'data-gt', showGames);
    if (d.stats && d.stats.p1) {
      const draw = k => { document.getElementById('mt-stats').innerHTML = statsBlock(T, d, k); };
      draw('all');
      TA.wireToggles(document.getElementById('mt-st'), 'data-st', draw);
    }
    TA.sortable(el);
    document.title = TA.playerSurname(T, d.p1) + ' v ' + TA.playerSurname(T, d.p2) + ' · ' + TA.eventName(T, d.event || eid) + ' · The Quant Ace';
    TA.setMeta(esc(TA.eventName(T, d.event || eid, true)) + ' · ' + esc(TA.roundLabel(d.round)));
  });
}

function V2card(title, sub, body) { return TA.v2.card(title, sub, body, { flush: true }); }
function sumSide(d, side) { return (d.sets || []).reduce((a, s) => a + (s[side] || 0), 0); }
function kindText(k) { return { hold: 'held', break: 'broke', tiebreak: 'won the tiebreak', start: 'start', set: 'won the set' }[k] || (k || ''); }

function eloRows(T, d, surface) {
  const e = (d.pre || {}).elo || {};
  const a = e.p1 || {}, b = e.p2 || {};
  if (!isNum(a.all) && !isNum(b.all)) return '';
  const sf = surface && surface !== 'all' ? surface : null;
  // the surface rating comes as "surface" (with e.surface naming it) or under the surface's own key
  const sa = isNum(a.surface) ? a.surface : (sf ? a[sf] : null), sb = isNum(b.surface) ? b.surface : (sf ? b[sf] : null);
  const sName = e.surface || sf;
  return '<div class="vs-rows" style="padding-top:0">' + vsRow('Elo overall', a.all, b.all, '0') + (isNum(sa) || isNum(sb) ? vsRow('Elo ' + (sName ? TA.surfaceLabel(sName).toLowerCase() : 'surface'), sa, sb, '0') : '') +
    (isNum(e.p) ? vsRow('Elo win probability', e.p, 1 - e.p, 'pct') : '') + '</div>';
}

function h2hCard(T, d) {
  const h = (d.pre || {}).h2h || null;
  if (!h) return TA.card('Head to head', '', TA.muted('No meetings on record.') + '<a class="more-link" href="' + TA.h2hHref(T, d.p1, d.p2) + '">Full head to head →</a>');
  // last meetings: objects {match, date, event, winner, sets} or arrays [date, event, round, winner, score]
  const last = (h.last || []).map(x => (Array.isArray(x) ? { date: x[0], event: x[1], round: x[2], winner: x[3], score: x[4] } : x))
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  return TA.card('Head to head', 'before this match',
    '<div class="h2h-big"><span>' + esc(TA.playerSurname(T, d.p1)) + ' ' + (h.w || 0) + '</span><span class="dash">–</span><span>' + (h.l || 0) + ' ' + esc(TA.playerSurname(T, d.p2)) + '</span></div>' +
    (last.length ? TA.tableHTML([{ label: 'Date' }, { label: 'Event' }, { label: 'Winner' }, { label: 'Score' }],
      last.map(x => [{ v: x.date, html: esc(TA.fmtDate(x.date, { weekday: false })) }, { v: x.event, html: x.event ? TA.eventLink(T, x.event, { surface: true }) : '—' },
        { v: TA.playerName(T, x.winner), html: x.winner ? TA.playerLink(T, x.winner, { surname: true }) : '—' },
        { html: (x.score ? esc(x.score).replace(/\((\d+)\)/g, '<sup>$1</sup>') : TA.fmtScore({ sets: x.sets || [] })) + (x.round ? ' <span class="muted-inline">' + esc(TA.roundLabel(x.round, true)) + '</span>' : '') }]), { compact: true }) : TA.muted('They have not met before.')) +
    '<a class="more-link" href="' + TA.h2hHref(T, d.p1, d.p2) + '">Full head to head, by surface →</a>');
}

TA.route('match', render);
})(window.TA);
