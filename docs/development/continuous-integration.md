# Continuous integration

Lacuna's GitHub Actions workflow is an executable release-candidate gate, not a collection of
independent green badges. It validates the supported language boundary, statistical test layers,
documentation, and installed artifact before producing one stable `CI gate` result for branch
protection.

## Trigger and concurrency policy

CI runs for every pull request, every push to `main`, and manual dispatches. Pull-request runs use a
workflow-and-PR concurrency key and cancel an older run when a newer commit arrives. Main-branch runs
are not cancelled, preserving an audit trail for every merged commit.

The workflow declares only `contents: read`. Checkout does not persist Git credentials. No CI job
receives a publishing token, deployment credential, or repository write permission.

## Gate graph

```text
Quality ───────────────┐
Python compatibility ─┤
Rust stable + MSRV ───┤
Interoperability ─────┼──> Package ──> CI gate
Optional extensions ─┤
Documentation ────────┘
```

The prerequisite layers run in parallel. Packaging starts only after all of them pass, so a source
distribution and wheel are never presented as validated artifacts when a prerequisite failed. The
final gate checks every required result explicitly; a failed or skipped prerequisite cannot turn into
a successful branch-protection check.

## Job contracts

| Layer | Contract |
| --- | --- |
| `Quality` | Frozen lockfile install without building Lacuna; Ruff format/lint, strict mypy, and whitespace checks |
| `Python` | Complete suite on Python 3.11–3.14/Linux and Python 3.13/macOS/Windows; branch coverage on the primary Linux runtime |
| `Rust` | rustfmt, Clippy with warnings denied, workspace tests, and Criterion benchmark compilation under `Cargo.lock` |
| `Rust / MSRV 1.85` | Every target compiles and the workspace tests pass on the declared minimum Rust version |
| `Interoperability` | pandas, Arrow, Polars, NumPy, lazy/eager, and SciPy-reference comparisons with optional extras installed |
| `Optional extensions` | Locked workspace install; extension Ruff/mypy; branch-aware options tests and independent API contract |
| `Documentation` | Strict MkDocs build with the rendered handbook retained for inspection |
| `Package` | Build core sdist/wheel plus options wheel/sdist, install all wheels into a clean environment, then exercise both distributions, typing resources, result/bundle schemas, CLI, bundles, public APIs, adapters/plugins, and native kernels |
| `CI gate` | Stable aggregate result intended for branch protection |

Every job has a bounded timeout. The Python matrix uses `fail-fast: false` so one compatibility
failure does not hide results from the other supported runtimes or platforms.

## Reproducible and secure setup

- Python dependencies come from `uv.lock` via `uv sync --frozen`.
- Cargo commands use `--locked` where dependency resolution applies.
- CI installs an explicit uv release rather than an implicit latest version.
- Concurrent dependency profiles use distinct uv cache suffixes, avoiding cache-save races while
  preserving reuse within each job type.
- Every external action is pinned to a full commit SHA and annotated with its reviewed release.
- Dependabot groups GitHub Actions updates into a weekly pull request so immutable pins remain
  maintainable and changes still pass the complete gate.
- Repository code from a pull request receives no secrets and cannot push through the checkout token.

When updating a pin, verify that the SHA belongs to the upstream action repository and leave the
human-readable release comment beside it. Do not replace a SHA with a mutable branch or major tag.

## Evidence and artifacts

CI retains evidence for diagnosis without turning the repository into permanent artifact storage:

- JUnit XML from every Python platform/version for 7 days;
- primary-runtime branch coverage XML for 7 days;
- optional-adapter/reference JUnit XML for 7 days;
- options-extension coverage and JUnit XML for 7 days;
- the rendered documentation site for 7 days;
- the verified Linux source distribution and wheel for 14 days.

Artifacts are test evidence only. Publishing to PyPI or attaching files to a GitHub release belongs
in a separately permissioned release workflow triggered from an exact approved tag.

## Coverage policy

The primary Python 3.13/Linux run measures statement and branch coverage and currently enforces an
80% total floor. Coverage is a regression guard, not proof of statistical correctness. Reference,
property, differential, temporal-boundary, and simulation tests remain required even when the line
coverage floor passes.

Raise the floor only after adding meaningful tests. Do not exclude difficult analytical branches or
write implementation-replay tests merely to increase a percentage.

## Local equivalence

Before opening a pull request, run:

```bash
uv sync --frozen --group dev --group docs --extra pandas --extra statistics
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=lacuna --cov-branch --cov-fail-under=80
uv run pytest extensions/lacuna-options/tests --cov=lacuna_options --cov-branch --cov-fail-under=85
uv run mypy --config-file extensions/lacuna-options/pyproject.toml extensions/lacuna-options/src/lacuna_options

cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo test --locked --workspace
cargo bench --locked --bench kernels --no-run

uv run mkdocs build --strict
uv run maturin build --release --locked --sdist --out dist
```

The macOS and Windows matrix remains authoritative for platform-specific behavior even when local
development occurs on one operating system.

## Branch protection

Configure the default branch ruleset to require the single `CI gate` check. Individual job and matrix
names can evolve without repeatedly editing branch protection, while the aggregate gate cannot pass
unless every layer succeeds. Also require the branch to be up to date before merging when the project
begins accepting concurrent external contributions.

Do not make only `Package` required: GitHub marks a dependency-skipped job differently from a failed
aggregate contract, and the explicit final gate makes that state visible.

## Intentionally separate workflows

CI does not publish packages, sign artifacts, deploy documentation, or enforce noisy benchmark timing
thresholds on shared runners. Release credentials and provenance attestations require a narrower,
tag-driven workflow. Performance regression policy requires controlled baselines rather than treating
variable hosted-runner timings as exact measurements.

The separate `Release` workflow consumes a version-matching core tag only after the tagged commit's
`CI gate` succeeded. It builds and target-smoke-tests the complete stable-ABI core wheel matrix,
builds and jointly smoke-tests the independently versioned universal options distribution, validates
both source distributions and every packaged resource as one set, generates checksums and provenance,
and creates a GitHub prerelease for SemVer candidate tags or a normal release for stable tags. Any future
PyPI trusted-publishing job must be isolated in its own
environment and permission boundary after a non-conflicting distribution name is selected. RC1 does
not publish to PyPI, and neither does `0.1.0`. See [Release engineering](release.md) for the tag and
artifact contract.
