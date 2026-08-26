# lacuna-options

`lacuna-options` is the separately packaged empirical options-research extension for
[Lacuna](https://github.com/eyenoticeall/Lacuna). It does not add options, solver, or plotting
dependencies to Lacuna core.

The initial `0.1.x` contract provides:

- a normalized, point-in-time-conscious option-chain schema;
- validated bid/ask/mid and expiration invariants;
- carry-based forwards and log-forward moneyness;
- deterministic absolute-delta buckets; and
- structured empirical implied-volatility residual evidence.

Install the matching Lacuna core wheel and the extension wheel from the same GitHub Release:

```bash
python -m pip install ./lacuna-0.8.0-*.whl ./lacuna_options-0.1.2-py3-none-any.whl
```

```python
import lacuna_options as lo

chain = lo.validate_chain(option_quotes)
bucketed = lo.delta_buckets(chain)
residuals = lo.empirical_residual(chain, expected="fair_iv")
```

The package does not claim a universal implied-volatility solver, Greeks model, surface fit, or
arbitrage-free calibration. Those depend on explicit model, day-count, exercise, settlement,
dividend, and numerical policies and belong in later separately versioned capabilities.

Version `0.1.2` preserves the exact `0.1.x` Python surface while expanding its compatible core range
to include additive Lacuna `0.8.x` releases. Validated chain evidence is recognized by the required
`options_evidence` capability in Lacuna's standardized options audit profile.
