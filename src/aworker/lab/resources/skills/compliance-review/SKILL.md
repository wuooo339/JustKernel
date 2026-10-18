---
name: compliance-review
description: Review the entire Host and Device implementation against the provided competition constraints.
---

Use the actual /CONSTRAINTS.md as the authority for this challenge.
Host only validates metadata, computes integer tiling and launches.
All mathematical operations specified by this operator must execute in the same
single physical kernel on every invocation. Do not replace them with Host math,
precomputed tables, cached results, stale outputs or uninitialized memory.
Do not match complete test cases, skip computation, change judge/precision/timing,
detect warmups or move work outside timing. Review all fallbacks and helpers.
Run inspect_policy, but do not call its automated checks a compliance certificate.
List unresolved items and evidence still needed, including physical launches.
