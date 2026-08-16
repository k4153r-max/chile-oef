# Data directories

`raw/`, `processed/`, and `artifacts/` are runtime directories and are ignored by
Git. Each stored object is content-addressed by SHA-256 and registered in the
database. Small, curated, non-sensitive test fixtures live under `tests/fixtures`.

