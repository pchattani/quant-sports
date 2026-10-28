/* The Quant Ace — two Model tabs (round 9, 28 Oct 2026; the Model section in the standing order: How it works, How we're
 * doing, Our forecasts v the market, Who moves next, Glossary, Terms):
 *   #/<T>/versus           "Our forecasts v the market": our match chances against the closing line and Kalshi, player by
 *                          player (value.json market block, drawn by TA.value.market). The only page built around the
 *                          market; elsewhere it is a quiet grey line beside our chance.
 *   #/<T>/who-moves-next   "Who moves next": the breakout model's walk-forward record (value_validation.json, drawn by
 *                          TA.value.validation; ?h=12m|6m). The fan board ("Breakouts") stays on Value.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (TA) {
'use strict';

function versus(el, params) {
  const T = params.tour;
  el.innerHTML = QK.explain('Our chance is the headline everywhere on the site. This page lines it up against the closing line and the prediction markets, player by player, for the last 52 weeks: where the two disagree, and which one was closer. A reference, not a recommendation.', { title: 'Ours against the market.' }) +
    '<div id="vs-body" style="margin-top:var(--sp-4)">' + QK.skeleton('lines', 6) + '</div>';
  const host = el.querySelector('#vs-body');
  if (!TA.value || !TA.value.market) { host.innerHTML = QK.empty('Not available', 'The comparison did not load.'); return null; }
  return TA.value.market(T, host).then(() => {
    if (host.isConnected && !host.innerHTML.trim()) host.innerHTML = QK.empty('Not built yet', 'The market comparison comes with the next build.');
  });
}

function whoMovesNext(el, params) {
  const T = params.tour;
  const q = Object.assign({}, params.query || {});
  q._route = ch => { const h = ch.h || q.h; try { history.replaceState(null, '', TA.href(T, 'who-moves-next') + (h && h !== '12m' ? '?h=' + h : '')); } catch (e) { /* old browsers */ } };
  el.innerHTML = QK.explain('Our breakout model forecasts where each player’s ranking will be in six and twelve months. Here is how it has done when it could only see the past: every season since 2010 forecast blind and checked, the seasons from 2018 held back as the test. The picks themselves are on <a href="' + TA.href(T, 'value') + '">Value › Breakouts</a>.', { title: 'Who moves next, checked.' }) +
    '<div id="wm-body" style="margin-top:var(--sp-4)">' + QK.skeleton('lines', 6) + '</div>';
  if (!TA.value || !TA.value.validation) { el.querySelector('#wm-body').innerHTML = QK.empty('Not available', 'The validation did not load.'); return null; }
  return TA.value.validation(T, el.querySelector('#wm-body'), q);
}

TA.route('versus', versus);
TA.route('who-moves-next', whoMovesNext);
})(window.TA);
