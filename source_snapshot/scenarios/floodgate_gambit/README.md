# The Floodgate Gambit

A custom single-player Castle scenario for Golden Era.

## Premise

The dead have sabotaged a river-control network. Recover three ancient seals,
choose whether to fight the sluice wardens, then take Floodgate Citadel before
the valley is drowned.

## Build and install

```text
python experiments/campaign_port_poc/build_floodgate_gambit_scenario.py
python tools/validate_floodgate_gambit_scenario_contract.py --repo-root .
python tools/install_floodgate_gambit_scenario.py --repo-root .
```

Restart the game after installation, then choose `The Floodgate Gambit` from
QuickStart.

## Proof boundary

The generated map and Core overlay are contract-validated. Runtime loading and
user-visible gameplay still require a Golden Era playtest.
