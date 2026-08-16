# Magnitude completeness policy

Mc is estimated by source, network epoch, space, time, tectonic class where
supported, magnitude type, and method version.

The initial primary estimator is Entire Magnitude Range with bootstrap uncertainty;
Goodness-of-Fit is a cross-check. Maximum Curvature is diagnostic only. B-positive
and detection-function methods are research challengers for transiently incomplete
aftershock catalogs.

Spatial estimates use adaptive neighborhoods with minimum sample and maximum
radius. Temporal estimates follow network epochs and detected changes rather than
arbitrary small rolling windows. Every downstream statistic stores the Mc result
it used.

Initial reporting bands are:

- at least 200 events: supported;
- 100-199: high uncertainty;
- 50-99: research only;
- fewer than 50: not estimable.

These bands are configuration defaults to be replaced only after a registered
simulation study of estimator precision.

