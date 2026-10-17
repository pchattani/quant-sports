"""
Cup competitions: a league or group phase feeding a knockout bracket.

Three shapes share one simulator:

  swiss    UEFA's 36-team league phase (Champions, Europa, Conference League):
           one table, top 8 straight to the Round of 16, 9-24 into a two-legged
           play-off, the rest out; then two-legged rounds and a single final.
  groups   CONMEBOL's eight groups of four (Libertadores, Sudamericana): the top
           two of each group into a two-legged Round of 16, then two-legged rounds
           and a single final.
  fixed    A hand-written bracket with slots filled by name or by another
           competition's simulated winner — the FIFA Intercontinental Cup, whose
           Derby of the Americas takes the Libertadores winner.

Cups are where leagues meet. Their matches join the pooled Dixon-Coles fit, with
each club carrying its league's identity, which is what puts Arsenal and Bayern on
one scale — and, for clubs from leagues the site does not follow, leaves them at
the pool's average until their cup matches say otherwise.
"""
