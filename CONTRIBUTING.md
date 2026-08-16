# Contributing

Scientific behavior changes require a versioned decision record, a model or method
card, tests on synthetic data, and regression tests on frozen historical fixtures.

No model may read observations whose `available_at` is later than its issue time.
No forecast row may be updated after publication. Experimental code belongs under
`research/` until it satisfies `research/PROMOTION_POLICY.md`.

Data-source changes must update `config/source-registry.yaml` and preserve the raw
response that motivated the change.

