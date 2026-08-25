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

The `0.1` native surface is compatible with PyO3's `abi3-py311` mode: it exchanges owned Python
sequences and scalar results rather than borrowing Arrow buffers through version-specific CPython
APIs. The release therefore builds one CPython 3.11 stable-ABI wheel per platform and smoke-tests it
under Python 3.13 on the target architecture. The ordinary CI matrix separately verifies the full
Python 3.11–3.14 range. Revisit `abi3` before introducing native Arrow capsules, buffer borrowing, or
another CPython API that the stable ABI cannot represent safely.

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

CI rebuilds the wheel through the source distribution (`maturin build --sdist`) so omitted Rust,
Python, typing, license, or schema files fail before release. The package job then installs that
wheel into a separate environment and checks version agreement, the native module, packaged JSON
Schema, and CLI diagnostics.

## Wheel smoke test

A clean wheel environment should verify:

```python
import lacuna
from lacuna import _native

assert lacuna.__version__ == _native.version()
```

It then runs a minimal native kernel, imports every public package, checks `py.typed` and stubs, and exercises the CLI `doctor` command.

The canonical audit schema is available both as the repository publication artifact at
`schemas/audit-result-v1.schema.json` and as the installed
`lacuna.schemas/audit-result-v1.schema.json` resource. Schema tests require these copies to be
byte-for-byte identical.

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

## Tagged release workflow

`.github/workflows/release.yml` runs only for a pushed `v*` tag and rejects the event unless:

- Python, Rust, source-code, changelog, and tag versions agree;
- the annotated tag resolves to the checked-out commit;
- that commit is an ancestor of `main`;
- the commit's stable `CI gate` check concluded successfully;
- the public API fixture belongs to the same package series.

The release builds a source distribution plus Linux x86_64, Linux aarch64, macOS arm64, and Windows
x86_64 wheels. Every wheel is installed into a new environment on its target architecture and runs
the package/native/schema/CLI smoke contract. A separate job downloads the complete matrix, rejects
missing or unexpected filenames and tags, inspects wheel and source contents, and writes
`SHA256SUMS`.

Only the final publication job has `contents: write`, attestation, and OIDC permissions. Build jobs
remain read-only. GitHub receives an explicitly marked prerelease with the verified artifacts and
checksum manifest; GitHub provenance attestations are generated from that manifest.

Registry publication is deliberately disabled for RC1. The PyPI distribution name `lacuna` is
already owned by an unrelated project, so this repository must not configure a trusted publisher or
upload credentials for that name. Choose and review a distinct distribution name before adding a
PyPI job; the Python import package can remain `lacuna`. RC1 is distributed through its checksummed,
attested GitHub release artifacts.

For a candidate tag, use the Cargo/SemVer spelling:

```text
v0.1.0-rc.1
```

Python package metadata normalizes that identity to `0.1.0rc1`. The release verifier owns this
mapping and prevents the two surfaces from drifting.

## Candidate feedback gate

Artifact publication begins the release-candidate evaluation; it does not complete it. The
[release-candidate feedback protocol](release-candidate-feedback.md) requires independent users,
multiple platforms/input boundaries, an external numerical comparison, and disposition of all
release blockers before the candidate can graduate.

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
