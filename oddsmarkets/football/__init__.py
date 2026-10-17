"""
Football modelling platform.

Structure:
  core/          competition-agnostic models and simulation primitives
  sources/       data providers (Sofascore, odds feeds) and name normalisation
  competitions/  per-competition configuration and tournament structure

Competition-specific code should be small: a config describing the format, plus any
structure the shared simulator cannot express generically. Everything else belongs in
core/ or sources/ so the next competition is a configuration exercise rather than a fork.
"""
