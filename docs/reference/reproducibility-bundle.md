# Reproducibility bundle v1

Lacuna `0.7` adds a deterministic `.lacuna` evidence archive. A bundle preserves the canonical
audit, human-readable projections, resolved runtime context, and optional structured evidence behind
one checksummed manifest. It is a portable review artifact, not an executable notebook, a source-data
backup, or proof that a third party can access the original environment.

## Create and verify

```python
import lacuna as lc

report = study.audit(seed=42)
report.bundle(
    "study.lacuna",
    evidence={"experiment_history": registry.to_result()},
    provenance={
        "code_fingerprint": "git:0123456789abcdef",
        "dataset_fingerprint": "sha256:dataset-manifest",
    },
    invocation={
        "api": "SignalStudy.audit",
        "parameters": {"seed": 42},
    },
)

verification = lc.verify_bundle("study.lacuna")
print(verification.archive_sha256)
print(verification.manifest.report_method)
```

`lacuna.create_bundle(report, ...)` is the functional equivalent of `report.bundle(...)`. Existing
files are not replaced unless `overwrite=True` is explicit. Bundle names must end in `.lacuna` and
named evidence must use a conservative lowercase identifier such as `experiment_history`.

The signal CLI can create the report and bundle in one run:

```bash
lacuna signal \
  --signal factor.parquet \
  --prices prices.parquet \
  --horizon 5D \
  --seed 42 \
  --out audit.json \
  --bundle study.lacuna

lacuna bundle verify study.lacuna
lacuna bundle verify study.lacuna --json
```

Verification returns exit code `0` only after the archive structure, manifest, canonical JSON,
declared sizes, and every artifact SHA-256 pass. It reads in place and never extracts content or
activates plugins.

## Version-1 members

Every bundle contains:

| Path | Role |
| --- | --- |
| `manifest.json` | format, producer/report identity, trust policy, artifact set digest |
| `report/audit.json` | canonical machine-readable `AnalysisResult` |
| `report/audit.md` | deterministic review projection |
| `report/audit.html` | escaped self-contained projection |
| `metadata/configuration.json` | resolved execution settings supplied to the bundle |
| `metadata/environment.json` | Python, platform class, core dependency, Lacuna, and native versions |

Optional caller input adds `metadata/provenance.json`, `metadata/invocation.json`, and
`evidence/<name>.json`. A `metadata/redactions.json` member appears when supplemental metadata needed
redaction. Optional evidence accepts only `AnalysisResult` values so the archive remains structured,
finite JSON rather than arbitrary files.

The default operation does not add proprietary input tables, arbitrary attachments, credentials,
environment variables, lockfile contents, executable code, or plugins. A caller may put compact
derived rows inside an `AnalysisResult`; the caller still owns the redistribution decision for that
evidence.

## Manifest contract

The language-independent JSON Schema is
`schemas/lacuna-bundle-manifest-v1.schema.json`. The identical installed resource is available from
`lacuna.schemas.bundle_manifest_v1_text()`. The committed
`tests/fixtures/bundle-manifest-v1.json` preserves the first migration fixture.

Each artifact entry records:

- canonical POSIX-relative path;
- semantic role and media type;
- exact byte size;
- lowercase SHA-256 digest.

`artifact_set_sha256` commits to the sorted artifact descriptors. The report identity repeats its
result schema, method, method version, and optional input fingerprint so verification can reject a
manifest/report mismatch without interpreting the analytical result.

Consumers select behavior from `format` plus `bundle_version`. Version 1 rejects unknown top-level
or nested fields, unsupported versions, unsorted/duplicate artifact paths, extra archive members,
and a missing canonical report. A later incompatible archive layout must publish another bundle
schema and migration guidance; it must not reinterpret version 1.

## Determinism

The writer uses:

- lexically sorted member paths;
- canonical compact JSON with one trailing newline;
- stored, uncompressed ZIP members;
- fixed ZIP timestamps, regular-file type, and non-executable permissions;
- no archive/member comments or extra fields.

Creating a bundle twice from the same immutable `AuditReport`, configuration, environment summary,
and supplemental evidence produces identical bytes. A newly computed report normally has a new
`created_at`, and dependency/platform changes alter the environment member, so bitwise identity is
not promised across distinct executions or machines.

## Reproducibility claim

Bundle v1 claims only **identifiable** reproducibility: artifact identities and archive integrity
have been verified. It does not claim that inputs are accessible, that the analysis is recomputable,
that numerical outputs match a tolerance, or that bytes reproduce on another system. Those stronger
levels require a future reproducer with explicit input retrieval, environment construction, command
execution, and comparison policy.

`BundleVerification.authenticity_verified` is always false in its serialized summary. Internal
SHA-256 consistency detects corruption but is not a signature: an attacker can construct a new,
self-consistent archive. Establish origin separately through a signed release, attestation, trusted
transport, or an independently communicated archive digest.

## Privacy and security

Canonical audit and named evidence are never silently modified. Bundling fails if they contain:

- credential-shaped mapping keys;
- URLs with user information, query parameters, or fragments;
- machine-specific absolute paths.

The caller must remove those values at their source so the canonical report stays canonical.
Supplemental configuration, provenance, and invocation metadata are safer to project, so the writer:

- renames credential-shaped keys with `_redacted` and replaces the value;
- removes URL user information, query, and fragment components;
- replaces absolute paths with `<absolute-path>/<basename>`;
- records artifact, JSON path, and reason without recording the removed value.

The verifier treats every bundle as untrusted data. Version 1 permits at most 256 members, 16 MiB
per member, 64 MiB total uncompressed content, and a 64 MiB archive. It rejects absolute paths,
Windows drives, backslashes, `.`/`..`, NULs, duplicates, directories, links, executable modes,
encryption, compression, ZIP comments, noncanonical ZIP encoding, duplicate JSON keys, non-finite
JSON, and manifest/member disagreement. It never uses pickle and never renders HTML during
verification.

## Operational failures

`ReportError` is raised for an unsafe destination, overwrite refusal, unsafe canonical evidence,
malformed archive, unsupported manifest, digest/size mismatch, or safety-limit violation.
`DataContractError` is raised when supplemental metadata cannot be represented as deterministic,
finite canonical JSON. Both inherit from `LacunaError`, so the CLI reports them as execution errors
rather than as audit findings.

Integrity verification says nothing about methodological correctness. Consumers must still inspect
the report's findings, evidence coverage, method versions, unknown checks, and input identities.
