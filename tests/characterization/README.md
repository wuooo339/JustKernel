# Legacy Characterization Tests

These tests pin the legacy `aworker` contracts that may be reused by the new
`justkernel` implementation:

- simulator request schema/defaults
- legacy skill frontmatter
- A2A agent card defaults
- verified fixture identity/hashes

They require the sibling legacy tree at `../../JustKernel/src` and its
dependencies. When that tree is absent (for example in CI), `conftest.py`
ignores these test modules; the new project's own tests still run.

Run locally from the `Refactor/` root:

```bash
uv run pytest -q tests/characterization
```

Before deleting a characterization test in P5/P8, add an equivalent contract
test for the new adapter under `tests/adapters/`.
