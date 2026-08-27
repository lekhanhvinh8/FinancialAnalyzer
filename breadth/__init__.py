"""
Breadth timing: read the whole basket, act on one instrument.

THE QUESTION

  portfolio/ asks WHICH symbols a shared wallet should buy. This package asks
  WHEN, on a single instrument -- the index -- using the rest of the basket as
  evidence about the market rather than as a list to choose from.

  Same database, same loader, opposite role for the same fifty-three symbols:
  none of them is ever bought here.

WHY IT IS WORTH TRYING AFTER portfolio/ WAS CLOSED

  That strand stopped because the database cannot identify a good company.
  Market capitalisation was standing in for quality and is not free-float
  adjusted, so ranking by size partly ranked by who was not selling.

  Breadth needs neither. It COUNTS symbols instead of weighting them, so free
  float never enters, and it never has to judge a company -- only whether the
  market as a whole is cheap or extended. Both data gaps that closed the last
  strand are irrelevant here.

  THE WEAKNESS MOVES RATHER THAN DISAPPEARING, and it is worth stating before
  any number is quoted. Fifty-four symbols gave fifty-four observations. One
  instrument over 137 months gives perhaps a dozen independent cycles, so
  anything measured here overfits far more easily and a difference of a few
  points means nothing at all.

MODULE MAP

    signals.py    the basket reduced to a handful of numbers per day
    series.py     one signal dressed as a SymbolSeries, so core rules apply
    strategy.py   Plan: which signals each arm reads, and the pace
    engine.py     the daily loop
    config.py     the parameters
    run.py        CLI

  Everything about reading the market comes from core/.
"""
