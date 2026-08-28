<div align="center">
  <table>
    <tr>
      <td align="center" bgcolor="#0b0d0e">
        <img src="https://raw.githubusercontent.com/eyenoticeall/Lacuna/main/logos/lacuna-logo-lockup.png" alt="Lacuna" width="520" />
      </td>
    </tr>
  </table>

  <p><strong>Stress-test your alpha before the market does.</strong></p>
  <p>Open-source quantitative research validation for finding where alpha breaks.</p>

  <p>
    <a href="https://github.com/eyenoticeall/Lacuna/actions/workflows/ci.yml"><img src="https://github.com/eyenoticeall/Lacuna/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/releases/latest"><img src="https://img.shields.io/github/v/release/eyenoticeall/Lacuna?display_name=tag&amp;sort=semver&amp;style=flat" alt="Latest release" /></a>&nbsp;&nbsp;
    <a href="https://pypi.org/project/lacuna-quant/"><img src="https://img.shields.io/pypi/v/lacuna-quant?label=PyPI&amp;logo=pypi&amp;logoColor=white&amp;style=flat&amp;cacheSeconds=300" alt="PyPI" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/pyproject.toml"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&amp;logoColor=white&amp;style=flat" alt="Python 3.11+" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/Cargo.toml"><img src="https://img.shields.io/badge/Rust-2024-000000?logo=rust&amp;logoColor=white&amp;style=flat" alt="Rust 2024" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/data-boundary.md"><img src="https://img.shields.io/badge/Arrow-compatible-2563EB?logo=apachearrow&amp;logoColor=white&amp;style=flat" alt="Arrow compatible" /></a>&nbsp;&nbsp;
    <a href="https://github.com/eyenoticeall/Lacuna/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-3DA639?style=flat" alt="MIT License" /></a>
  </p>

  <p>
    <a href="#quick-start">Quick start</a> ·
    <a href="#what-lacuna-validates">Capabilities</a> ·
    <a href="https://github.com/eyenoticeall/Lacuna/tree/main/docs">Documentation</a> ·
    <a href="https://github.com/eyenoticeall/Lacuna/releases/tag/v0.14.0">v0.14.0</a>
  </p>
</div>

---

Lacuna is the evidence layer between quantitative research and confidence in a backtest. Give it
signals, returns, trades, events, or experiment history; it looks for leakage, instability,
overfitting, unrealistic costs, and missing point-in-time evidence.

It complements your research stack instead of replacing it. Results are returned as structured,
versioned evidence that can be inspected, audited, rendered, and archived.

> [!IMPORTANT]
> **v0.14.0 is current.** Lacuna is alpha, pre-1.0 software. This release preserves the v0.13
> public API while hardening performance, memory use, native boundaries, and release verification.

## Quick start

Install the core distribution and verify the runtime:

```bash
python -m pip install --upgrade lacuna-quant
lacuna doctor --strict
```

> [!NOTE]
> The distribution is `lacuna-quant`; the Python import and CLI remain `lacuna`. The PyPI project
> named `lacuna` is unrelated.

Given explicit signal and price frames, a complete study is deliberately small:

```python
import lacuna as lc

study = lc.SignalStudy(
    signal=signal,
    prices=prices,
    horizons=("1D", "5D", "20D"),
    signal_observed_at="open",
    entry="current_close",
    price_adjustment="total_return_adjusted",
)

report = study.audit(bootstrap_resamples=2_000, seed=42)

print(report.summary())
report.to_html("lacuna-audit.html")
report.bundle("study.lacuna")
```

Lacuna preserves weak or missing evidence as `UNKNOWN`; it never silently turns uncertainty into a
pass. See the
[copy-pasteable guided signal audit](https://github.com/eyenoticeall/Lacuna/blob/main/docs/getting-started/index.md)
for runnable data, output inspection, CLI usage, and bundle verification.

Optional method families stay explicit:

```bash
python -m pip install "lacuna-quant[statistics,report,pandas]"
python -m pip install lacuna-options
```

Stable-ABI wheels support CPython 3.11+ on Linux x86-64/arm64, macOS arm64, and Windows x86-64.

## What Lacuna validates

| Research risk | Evidence Lacuna provides |
| --- | --- |
| **Weak signals** | Group-aware IC, flexible buckets, neutralization, decay, multi-lag turnover, and diagnostic portfolio projections |
| **Leakage and bad timing** | Availability-safe joins, explicit label boundaries, purged/CPCV splits, revisions, membership history, and future-data checks |
| **Overfitting** | Bootstrap and permutation inference, PBO/CSCV, PSR/DSR, Reality Check, SPA, and multiple-testing correction |
| **Fragile conclusions** | Parameter surfaces, perturbations, subperiods, regimes, universe transitions, and append-only trial history |
| **Unrealistic trading assumptions** | Commission, spread, slippage, impact, borrow, stress, break-even, liquidity, and capacity evidence |
| **Unreproducible research** | Immutable `AnalysisResult` values, standardized audits, deterministic JSON/HTML, and verifiable `.lacuna` bundles |

Additional support includes availability-anchored event studies, generic factor-panel ingestion,
DuckDB and scikit-learn adapters, Arrow-compatible and optional pandas boundaries, and an
independently versioned options-research extension.

> [!WARNING]
> Lacuna does **not** source market data, generate signals, compound portfolios, resolve overlapping
> holdings, simulate orders or fills, route trades, or run live strategies. It is a validation
> library, not a backtester or execution engine.

## Evidence first

```text
signals · returns · trades · events · trials
                      │
                      ▼
            explicit Python policy
                      │
          Polars · NumPy/SciPy · Rust
                      │
                      ▼
               AnalysisResult
                      │
          audit · report · JSON · bundle
```

Python owns methodology, temporal semantics, validation, provenance, findings, and public result
construction. Renderers only present stored evidence; they do not recalculate statistics.

Findings keep state separate from severity:

- `PASS`: the supplied evidence satisfies the declared rule;
- `WARN` / `FAIL`: weakness or a violated contract is visible;
- `UNKNOWN`: the source cannot establish the claim;
- `NOT_APPLICABLE`: the methodology does not apply.

## Performance without a Rust quota

Most work belongs in optimized Polars or NumPy. Rust ships only when full-call benchmarks beat an
already optimized reference without changing public semantics.

In v0.14, grouped rank IC and built-in PBO/CSCV cleared that admission gate. Other candidates either
improved without Rust or closed with a documented negative decision. Native execution remains
single-threaded, reference implementations remain directly testable, and `cp311-abi3` portability
is a release requirement.

See the
[native decision ledger](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/rust-migration-decisions.md)
for workloads, measurements, correctness evidence, and rejected migrations.

## Documentation

| Start here | Use it for |
| --- | --- |
| [Getting started](https://github.com/eyenoticeall/Lacuna/blob/main/docs/getting-started/index.md) | Installation and a first complete audit |
| [Concepts](https://github.com/eyenoticeall/Lacuna/blob/main/docs/concepts/architecture.md) | Architecture, data semantics, and evidence contracts |
| [Subsystems](https://github.com/eyenoticeall/Lacuna/blob/main/docs/subsystems/signal-labels.md) | Method contracts, formulas, edge cases, and failure behavior |
| [Public API](https://github.com/eyenoticeall/Lacuna/blob/main/docs/reference/public-api.md) | Import paths and callable reference |
| [Alphalens migration](https://github.com/eyenoticeall/Lacuna/blob/main/docs/getting-started/alphalens-migration.md) | Moving factor workflows without importing hidden semantics |
| [Engineering handbook](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/index.md) | Development, testing, native work, performance, and releases |

The [technical specification](https://github.com/eyenoticeall/Lacuna/blob/main/LACUNA_TECHNICAL_SPEC.md)
defines the full product boundary. The
[roadmap](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/roadmap.md) and
[v1 readiness ledger](https://github.com/eyenoticeall/Lacuna/blob/main/docs/development/v1-readiness.md)
separate completed work from the remaining independent-user evidence requirement.

<details>
<summary><strong>Development setup</strong></summary>

```bash
git clone https://github.com/eyenoticeall/Lacuna.git
cd Lacuna
uv sync --group dev --group docs --extra all

uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest

cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
uv run mkdocs build --strict
```

Read [CONTRIBUTING.md](https://github.com/eyenoticeall/Lacuna/blob/main/CONTRIBUTING.md) before
submitting changes. Security reports follow
[SECURITY.md](https://github.com/eyenoticeall/Lacuna/blob/main/SECURITY.md).

</details>

## License

Lacuna is released under the [MIT License](https://github.com/eyenoticeall/Lacuna/blob/main/LICENSE).
Artifacts published before the MIT-only change retain their original grants.

---

<div align="center">
  <img src="https://raw.githubusercontent.com/eyenoticeall/Lacuna/main/logos/lacuna-logo-icon.webp" alt="Lacuna mark" width="72" />
  <p><strong>Bring the research. Lacuna will look for the gaps in the evidence.</strong></p>
</div>
