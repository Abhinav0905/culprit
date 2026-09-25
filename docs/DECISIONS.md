# Decisions

## D1 – loadgen: separate rngs by concern
Using four independent `random.Random` instances (seeded SEED, SEED+1, SEED+2, SEED+3)
for timing jitter, address selection, payment fields, and latency/noise respectively.
This ensures address distributions are not perturbed by timing jitter, making the
8% failure rate stable across runs.

## D2 – loadgen: first ERROR timing
The spec says the first orders ERROR is "~09:07". The DACH campaign starts at 09:06, and
with the flag already on since 08:55, the first unicode address (from a DACH city with a
non-ASCII street) can arrive at any time after 09:06:00. With seed 7 this lands at
09:06:16. This is within the "~09:07" tolerance and matches spec intent.

## D3 – loadgen: pool_high threshold
`db_pool_high` WARN fires once per minute starting at 09:10 as spec requires.
Pool usage is modelled as 60% baseline + ~5% per minute since the first error
(retries adding load), capped at 98%. This matches the spec's narrative without
needing a real connection pool in the simulation.

## D4 – pyproject.toml build backend
Used `setuptools.build_meta` instead of `setuptools.backends.legacy:build` because
the installed setuptools version does not expose the `backends.legacy` path on this
Python 3.11 environment.
