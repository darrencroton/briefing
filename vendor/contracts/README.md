# Vendored Contracts

This directory is the pinned `briefing-noted-contracts` snapshot used by
`briefing` tests. The contract payload lives under `contracts/` to match the
submodule layout documented by the contracts repo.

Refresh procedure after a new contracts tag is cut:

```bash
ditto ../contracts vendor/contracts/contracts
printf "vX.Y.Z\n" > vendor/contracts/CONTRACTS_TAG
uv run --extra dev pytest tests/test_contract_fixtures.py
```

Do not edit files under `vendor/contracts/contracts/` directly. Make contract
changes in the root contracts repo first, tag them, then refresh this snapshot.
