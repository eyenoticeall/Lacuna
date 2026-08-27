# Release engineering

Lacuna distributes a mixed Python/Rust package. Releases must prove correctness, schema compatibility, and wheel usability—not merely produce an archive.

## Version surfaces

Keep these distinct:

- **package version** — SemVer release identity in `pyproject.toml` and Cargo workspace;
- **extension package version** — independent SemVer identity, dependency range, changelog, and API
  fixture for each separately distributed workspace extension;
- **result schema version** — compatibility of persisted structured results;
- **method version** — value-affecting semantics of a statistic or rule;
- **scoring model version** — audit score weights and missing-evidence policy;
- **reproducibility bundle version** — future archive/container format.

A package patch may include an unchanged method version. A method correction can require both a package release and a method-version increment.

## Supported Python and platforms

The initial Python floor is 3.11. Test the minimum, a primary development version, and the newest supported version.

Target wheels:

- Linux x86_64;
- Linux aarch64;
- macOS arm64;
- Windows x86_64;
- macOS x86_64 only if maintained demand justifies it.

Normal users should not need a Rust toolchain.

The current native surface is compatible with PyO3's `abi3-py311` mode: it exchanges owned Python
sequences and scalar results rather than borrowing Arrow buffers through version-specific CPython
APIs. The release therefore builds one CPython 3.11 stable-ABI wheel per platform and smoke-tests it
under Python 3.13 on the target architecture. The ordinary CI matrix separately verifies the full
Python 3.11–3.14 range. Revisit `abi3` before introducing native Arrow capsules, buffer borrowing, or
another CPython API that the stable ABI cannot represent safely.

## Release gate

1. Working tree and lockfiles are clean.
2. Ruff formatting/lint and strict mypy pass.
3. Python unit, reference, property, statistical, integration, and regression suites pass as applicable.
4. Rust formatting, Clippy, tests, fuzz targets, and benchmarks pass as applicable.
5. Documentation builds in strict mode.
6. Stable benchmark cases meet regression policy.
7. Result-schema fixtures and method versions are reviewed.
8. Wheels build for the platform matrix.
9. Each wheel installs in a clean environment and passes an import/native smoke test.
10. Source distribution contains Rust sources, Python sources, stubs, the MIT license, and required docs.
11. Changelog is complete and target APIs are not presented as shipped.
12. Security advisories and dependency changes are reviewed.
13. Each independently versioned extension passes its own format/type/test/API gate and clean joint
    installation with the exact core wheel.

CI rebuilds the wheel through the source distribution (`maturin build --sdist`) so omitted Rust,
Python, typing, MIT license, or schema files fail before release. The package job then installs that
wheel into a separate environment and checks version agreement, the native module, packaged JSON
Schema, and CLI diagnostics.

## Wheel smoke test

A clean wheel environment should verify:

```python
import lacuna
from lacuna import _native

assert lacuna.__version__ == _native.version()
```

It then runs a minimal native kernel, imports every public package, checks `py.typed` and stubs,
exercises experiment/multiplicity and regime APIs, values a two-point cost-stress surface, creates
and verifies a `.lacuna` bundle, and exercises the CLI `doctor` command.

The canonical audit schema is available both as the repository publication artifact at
`schemas/audit-result-v1.schema.json` and as the installed
`lacuna.schemas/audit-result-v1.schema.json` resource. Schema tests require these copies to be
byte-for-byte identical.

The bundle-manifest schema has the same two-surface contract at
`schemas/lacuna-bundle-manifest-v1.schema.json` and the installed
`lacuna.schemas/lacuna-bundle-manifest-v1.schema.json`. Release inspection requires both the bundle
implementation and packaged schema in every core wheel/source distribution.

The options extension has a second installed-artifact smoke test. It verifies its distribution and
source versions, typed marker, chain validation/derived coordinates, delta buckets, and empirical
residual evidence after installing the extension wheel beside a verified core wheel.

## Release flow

```text
pull request
    ↓
correctness + reference + statistical suites
    ↓
benchmark regression review
    ↓
wheel matrix build and smoke install
    ↓
merge to main
    ↓
version/tag from the exact tested commit
    ↓
signed/attested artifacts
    ↓
GitHub Release
    ↓
PyPI Trusted Publishing and registry-install smoke
```

Do not rebuild release artifacts from a different source state after approval.

## Tagged release workflow

`.github/workflows/release.yml` runs only for a pushed `v*` tag and rejects the event unless:

- Python, Rust, source-code, changelog, and tag versions agree;
- the annotated tag resolves to the checked-out commit;
- that commit is an ancestor of `main`;
- the commit's stable `CI gate` check concluded successfully;
- the public API fixture belongs to the same package series.

The release builds a core source distribution plus Linux x86_64, Linux aarch64, macOS arm64, and
Windows x86_64 core wheels. Every native wheel is installed into a new environment on its target
architecture and runs the package/native/schema/CLI smoke contract. It separately builds the
universal `lacuna-options` wheel and source distribution, installs that wheel with the already
target-smoke-tested Linux core wheel, and runs the extension smoke contract.

A separate job downloads the complete matrix, rejects missing or unexpected filenames/tags/names/
versions, inspects both wheels and source archives, and writes one `SHA256SUMS`. For a `v0.13.0`
tag with extension `0.2.0`, the release set is exactly four `lacuna-quant` wheels, one
`lacuna-options` wheel, two source distributions, and the checksum manifest.

Only the GitHub publication job has `contents: write` and GitHub attestation permissions. The two
PyPI publication jobs have only `actions: read`, `contents: read`, and `id-token: write`; build and
verification jobs remain read-only. GitHub receives the verified artifacts and checksum manifest;
SemVer prerelease tags are explicitly marked as prereleases, while stable tags create normal
releases. GitHub provenance attestations are generated from the checksum manifest for all seven
distributions.

Core publishes to PyPI as `lacuna-quant`; the Python import package and CLI remain `lacuna`. The
PyPI name `lacuna` belongs to an unrelated project and is a prohibited release target. The optional
extension publishes independently as `lacuna-options` and depends on
`lacuna-quant>=0.13,<0.14` from its `0.2.0` release onward.

Registry publication uses PyPI Trusted Publishing only—no long-lived API token is stored. Both
PyPI projects authorize repository `eyenoticeall/Lacuna` and workflow `release.yml`. The core
publisher is bound to the protected GitHub environment `pypi`; the independently named extension
publisher is bound to `pypi-options`. PyPI requires distinct pending-publisher identity tuples for
different project names, so the environment split is part of the trust contract rather than a
release-method difference. Publication begins only after the complete release set passes archive
verification and is attached to GitHub:

1. isolate and publish the five verified `lacuna-quant` distributions;
2. isolate and publish the two verified `lacuna-options` distributions after core succeeds;
3. wait for index propagation, then install both exact versions from `https://pypi.org/simple` in a
   clean Python 3.13 environment;
4. rerun the native, schema, CLI, diagnostics, and extension wheel-smoke contracts.

The publisher uses `skip-existing` only to make an interrupted immutable upload retryable; the
post-publication smoke remains mandatory. PyPI does not permit overwriting a published filename or
version. Never add `password`, repository token, or arbitrary artifact paths to the publish jobs.

Users migrating from GitHub wheels distributed under the old metadata name `lacuna` must uninstall
that distribution before installing `lacuna-quant`. Both distributions own the import path
`lacuna`, so a dual installation is invalid and the `DISTRIBUTION_NAME_COLLISION` doctor check
fails it explicitly.

Stable and candidate tags use Cargo/SemVer spelling:

```text
v0.9.0
v0.9.0-rc.1
```

Python package metadata normalizes a candidate such as `0.9.0-rc.1` to `0.9.0rc1`; stable package
metadata is `0.9.0`. The release verifier owns this mapping and prevents the two surfaces from
drifting.

The core tag does not rename the extension. The verifier independently checks the extension
`pyproject.toml`, source version, dated changelog, public API series fixture, artifact metadata, and
contents. A core release may carry an unchanged compatible extension version; an extension version
changes only when its own package contract changes.

## Initial release decision

Independent-user validation was planned as an acceptance gate for `0.1.0`, but no external testers
were available. The maintainer explicitly waived that gate on 2026-08-26 after the tagged candidate
passed the complete CI, target-native wheel, source-distribution, checksum, and provenance workflow.
This decision permits publication; it does not convert maintainer and CI evidence into a claim of
independent validation. Future feedback remains welcome through ordinary GitHub issues.

## Pre-1.0 policy

Pre-1.0 APIs can evolve, but changes are intentional:

- update the changelog;
- prefer deprecation warnings when practical;
- retain old result fixtures when persisted artifacts exist;
- distinguish renames from semantic changes;
- explain migration for column, finding code, or configuration changes.

## Benchmark releases

Publish benchmark environment details and relative comparisons, not universal hardware claims. Performance regressions accepted for correctness or safety are called out in release notes.

## Failure and rollback

If a released method is statistically incorrect:

1. document affected package and method versions;
2. add a minimal regression/reference test;
3. correct the implementation and increment its method version;
4. release promptly with a clear advisory;
5. preserve the ability to identify old persisted results;
6. never silently reinterpret old audit artifacts as corrected results.
