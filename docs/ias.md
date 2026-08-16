# IAS: Indice de Anomalia Sismica

IAS measures how unusual elevated activity is relative to a conditional reference
distribution. It is neither seismic risk nor the probability of a large event.

The preferred design is a one-sided anomaly deviance `D` transformed to a local,
network-epoch-aware historical percentile:

\[
IAS = 100 F_{0,c}(D).
\]

Inputs can include ETAS count residuals, energy-proxy residuals, spatial
concentration, persistence, and statistically supported depth migration. Correlated
components must not be double counted. Explanations report component deviance
contributions, not causal claims.

Expert-weighted logistic scores are research prototypes only. A model trained on
future M>=m targets is a forecast model and must not be relabeled as IAS.

