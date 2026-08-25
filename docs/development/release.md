# Release engineering

Lacuna distributes a mixed Python/Rust package. Releases must prove correctness, schema compatibility, and wheel usability—not merely produce an archive.

## Version surfaces

Keep these distinct:

- **package version** — SemVer release identity in `pyproject.toml` and Cargo workspace;
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

## Pre-release gate

1. Working tree and lockfiles are clean.
2. Ruff formatting/lint and strict mypy pass.
3. Python unit, reference, property, statistical, integration, and regression suites pass as applicable.
4. Rust formatting, Clippy, tests, fuzz targets, and benchmarks pass as applicable.
5. Documentation builds in strict mode.
6. Stable benchmark cases meet regression policy.
7. Result-schema fixtures and method versions are reviewed.
8. Wheels build for the platform matrix.
9. Each wheel installs in a clean environment and passes an import/native smoke test.
10. Source distribution contains Rust sources, Python sources, stubs, licenses, and required docs.
11. Changelog is complete and target APIs are not presented as shipped.
12. Security advisories and dependency changes are reviewed.

## Wheel smoke test

A clean wheel environment should verify:

```python
import lacuna
from lacuna import _native

assert lacuna.__version__ == _native.version()
```

It then runs a minimal native kernel, imports every public package, checks `py.typed` and stubs, and exercises the CLI `doctor` command.

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
PyPI and GitHub release
```

Do not rebuild release artifacts from a different source state after approval.

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
