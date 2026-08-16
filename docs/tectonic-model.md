# Tectonic model

## Current scientific status

**RECOMMENDED:** use a fixed Slab2 release, explicit hypocentral-depth uncertainty,
an `unknown` class and versioned classification results as covariates and pooling
labels. This is reproducible and exposes structural uncertainty.

**EXPERIMENTAL:** the current rule baseline returns normalized uncertainty mass
over `interface`, `intraslab`, `crustal`, `outer_rise`, `volcanic`, and `unknown`.
Its calibration status is always `uncalibrated_rule_baseline`. These numbers are
useful for soft stratification but are not empirically calibrated posterior class
probabilities.

**NOT RECOMMENDED:** treating a depth cutoff, nearest mapped fault, or Slab2
residual alone as ground truth; publishing a hard tectonic label without provenance;
or describing CHAF surface distance as distance to a 3-D seismogenic fault.

## Versioned inputs

The current implementation pins the official USGS Slab2 South America release
`sam_02.23.18` by DOI, URL, byte length and SHA-256. Slab2 provides gridded depth,
dip, strike, thickness and uncertainty. Original 0–360 longitudes are normalized
to −180–180, negative-down depths become positive depth in kilometres, and strike
is interpolated circularly. See Hayes et al. (2018) and the official USGS release.

The Chile Active Faults Database (CHAF) is pinned to PANGAEA dataset 922241 under
CC-BY-4.0. It contains 958 surface fault traces. `F_id` is retained but is not a
unique trace identifier; the stable shapefile record ordinal identifies a trace.
Numeric-looking source attributes remain in `properties_json`. Exact values are
projected into typed fields; values such as `~90` are marked approximate, while
ranges and qualitative values remain unmodeled instead of being assigned an
arbitrary midpoint.

## Phase 2 residual baseline

Let positive depth increase downward and define

\[
r_z = z_{event} - z_{slab}(\phi,\lambda).
\]

Event and Slab2 uncertainty are combined for the baseline as

\[
\sigma_r = \sqrt{\sigma_{event}^2 + \sigma_{slab}^2}.
\]

For a normally distributed residual, the implementation integrates probability
mass over declared intervals:

- interface: `−10 km ≤ r_z ≤ 10 km`;
- intraslab: `10 km < r_z ≤ slab thickness`;
- crustal: above the interface band, gated by event depth ≤ 50 km;
- unknown: deep above-slab mass, below-slab mass and low-confidence results;
- outer-rise and volcanic: disabled in v1.

Defaults are configuration, not universal geophysical constants. They live in
`config/tectonic-classifier.yaml`, and changing them requires a new
`method_version`. Missing event depth or missing Slab2 coverage returns
`unknown=1`, never an imputed class.

The stored approximate normal distance is

\[
d_n \approx r_z\cos(\delta),
\]

where `δ` is local slab dip. It is explicitly labeled a local planar vertical
projection, not the nearest Euclidean distance to a triangulated 3-D surface.

CHAF contributes horizontal geodesic distance to the mapped surface trace only.
It does not change the v1 class masses. This prevents an arbitrary fault-distance
weight from masquerading as evidence.

## Promotion and future model

Promotion to a calibrated classifier requires an independently reviewed labeled
catalog for Chile, declared ambiguous cases, spatial and temporal holdouts,
reliability curves, classwise proper scores and sensitivity to hypocentral and
Slab2 uncertainty. Monte Carlo propagation of full hypocentral covariance and a
3-D slab representation are candidates after the baseline is tested.

A later model may add Moho depth, trench-side geometry, focal mechanisms and
volcanic domains. Those inputs are not implemented now. Along-strike tectonic
segments should be hierarchical pooling units, not asserted rupture barriers. The
Chile Triple Junction and Antarctic subduction must be modeled explicitly before
claiming nationwide tectonic coverage.

References: Hayes et al. (2018), DOI `10.1126/science.aat4723`; USGS Slab2 South
America, DOI `10.5066/F7PV6JNV`; Maldonado et al. (2021), DOI
`10.1038/s41597-021-00802-4`; CHAF release, DOI `10.1594/PANGAEA.922241`.
