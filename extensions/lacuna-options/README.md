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

Install the extension from PyPI. Its dependency resolves the compatible `lacuna-quant` core while
Python imports remain `lacuna_options` and `lacuna`:

```bash
python -m pip install lacuna-options
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

Version `0.2.0` preserves the exact `0.1.x` Python surface while moving dependency metadata to
`lacuna-quant>=0.13,<0.14`. The `0.2` fixture explicitly inherits the complete `0.1` contract.
Validated chain evidence is recognized by the required `options_evidence` capability in Lacuna's
standardized options audit profile.
