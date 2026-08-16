# Backtesting and prospective evaluation

## Walk-forward protocol

Each fold contains chronological training, optional calibration, and untouched
test periods. Hyperparameters, feature selection, Mc, probability calibration,
and ensemble weights are fitted before the test period. Overlapping targets use
an embargo at least as long as the forecast horizon.

Dependence is handled with time/sequence block bootstrap rather than treating
every cell-hour as independent.

## 27F experiment

The nominal freeze time is 2010-02-26 23:59 Chile continental time, stored as a
timezone-aware value and converted with a pinned tzdb. The result is labeled
pseudoprospective unless archival source revisions and receipt times can be
recovered. Maule is evaluated alongside matched quiet windows and all scheduled
forecast windows, never alone.

## Prospective protocol

From the first operational run, forecast artifacts are immutable and hashed.
Preliminary evaluation can occur after the horizon; adjudicated evaluation occurs
after the registered catalog-maturation delay. Both are retained.

## Metrics

Primary metrics are log score/point-process log likelihood, information gain per
event, Brier score, reliability/calibration, PR-AUC for rare binary targets, count
deviance, predictive coverage, and CSEP number/spatial/magnitude tests. Accuracy
is not a primary metric.

