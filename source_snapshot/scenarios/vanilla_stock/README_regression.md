# Vanilla stock regression suite

Golden-fingerprint regression for the stock HoMM3→Core translator.

## Scope

- Manifest: `scenarios/vanilla_stock/regression_manifest.json`
- Baselines: `scenarios/vanilla_stock/regression_baselines/<id>.fingerprint.json`
- Required eras: RoE, AB, SoD
- HotA official + fan rows: `buildOptional` soft-fail until HotA-only emit gaps close
- Proof: generated-artifact + fingerprint only (not runtime)

## Commands

```bash
python tools/build_vanilla_stock_regression.py
python tools/update_vanilla_stock_regression_baselines.py
python tools/validate_vanilla_stock_regression_contract.py
```

After intentional emit changes that alter stable metrics:

```bash
python tools/build_vanilla_stock_regression.py
python tools/update_vanilla_stock_regression_baselines.py
python tools/validate_vanilla_stock_regression_contract.py
```

Optional HotA baselines (when those maps happen to emit):

```bash
python tools/update_vanilla_stock_regression_baselines.py --include-optional
```

Fingerprints pin ownership compact renumbering, victory mode, spawn seats, event/omit histograms, access clearance counts, and serialization property keys — not absolute paths or object-id lists.
