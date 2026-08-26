# Installation diagnostics

Lacuna `0.9` exposes one versioned, non-invasive health check through
`lacuna.diagnose_installation()` and `lacuna doctor`. It answers whether the installed package can
run the released contract on the current runtime. It does not judge research evidence, scan input
data, access the network, write files, discover plugins, or activate third-party code.

## Use the diagnostic gate

For a person inspecting a development environment:

```bash
lacuna doctor
```

For automation and release verification:

```bash
lacuna doctor --json --strict
```

The default command exits `1` when any check is `FAIL`; a `WARN` remains exit `0`. `--strict`
promotes either `WARN` or `FAIL` to exit `1`. Requested JSON is the only stdout content, with no
progress text or terminal styling. The diagnostic itself does not emit stderr.

Python callers receive an immutable report:

```python
import lacuna as lc

diagnostics = lc.diagnose_installation()
if not diagnostics.healthy:
    for check in diagnostics.checks:
        if check.state == lc.DiagnosticState.FAIL:
            print(check.code, check.message)
```

`healthy` means no release-blocking check failed; it does not suppress warnings. Use `status` when
the distinction among `PASS`, `WARN`, and `FAIL` matters.

## Machine contract

The JSON payload has `schema_version: "1"` and `diagnostic_version: 1`. It retains the original
`lacuna_version`, `python_version`, `platform`, `native`, and `config` keys and adds aggregate
`status`, `healthy`, distribution/dependency/runtime identity, and a code-sorted `checks` array.
Check codes are stable within the `0.9.x` public API series; messages may become more specific.

| Code | Failure or warning meaning | Operator action |
|---|---|---|
| `PACKAGE_VERSION` | source version is not a supported release identity | install an official matching release |
| `DISTRIBUTION_METADATA` | metadata is absent in a source tree, or disagrees with the package | accept the source-tree warning or reinstall one wheel |
| `PYTHON_RUNTIME` | Python is below 3.11 or outside the tested 3.11-3.14 minors | select a release-tested Python |
| `PLATFORM_WHEEL` | current system/architecture is outside the published wheel matrix | use a published target or an explicit source build |
| `RUNTIME_DEPENDENCIES` | NumPy/Polars metadata differs from the imported runtime | rebuild the environment from one resolver state |
| `NATIVE_CORE` | native import, version identity, or smoke operation failed | reinstall a target-matching wheel |
| `AUDIT_RESULT_SCHEMA` | result schema is missing or has the wrong identity | reinstall the wheel |
| `BUNDLE_MANIFEST_SCHEMA` | bundle manifest schema is missing or invalid | reinstall the wheel |
| `PERSISTED_ARTIFACT_COMPATIBILITY` | the compatibility manifest is missing or invalid | reinstall the wheel |
| `STANDARD_AUDIT_PROFILE_SCHEMA` | standardized-profile schema is missing or invalid | reinstall the wheel |
| `RUNTIME_CONFIGURATION` | a documented `LACUNA_*` setting cannot be parsed | correct the named setting and rerun |

The optional `lacuna-options` distribution version is inventory, not a core health requirement.
Extension compatibility remains enforced by its own metadata, contract tests, and release smoke.

## Security and privacy boundary

Diagnostics return versions, operating-system identity, machine architecture, supported-version
declarations, and resolved non-secret runtime settings. A configured cache path is reported only as
`<configured>`; native loader details are reduced to a generic unavailable state or exception type.
No environment dump, credentials, research rows, proprietary query text, plugin entry points, or
raw filesystem path is included.

Platform and version fields can still reveal basic host information. Review JSON before attaching
it to a public issue. Diagnostic output is operational evidence, not authenticity evidence: verify
release checksums and GitHub artifact attestations separately.

## Adding a check

A new check must be deterministic, read-only, bounded, and safe before plugin activation. Give it a
stable uppercase code, one actionable message, JSON-compatible finite evidence, explicit
`PASS`/`WARN`/`FAIL` semantics, failure-path unit tests, public-contract coverage when exported, and
clean-wheel coverage when it protects release contents. Keep checks code-sorted so humans and
automation receive stable output.

Do not make network availability, optional integrations, private data sources, or analytical
quality a package-health requirement. Those belong in separate capability or audit evidence.
