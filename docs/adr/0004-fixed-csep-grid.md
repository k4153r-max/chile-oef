# ADR-0004: Fixed CSEP-compatible publication grid

Status: accepted, 2026-08-16.

Forecast publication starts with a versioned regular 0.1 degree grid. Estimation
can use adaptive kernels and hierarchical pooling. Sparse cells return not
estimable or use a registered coarser aggregation rather than unstable local fits.

