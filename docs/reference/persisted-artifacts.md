# Persisted-artifact compatibility

Lacuna `0.9` makes the pre-v1 persistence boundary explicit. Every persisted format keeps its own
version selector, and compatibility is chosen from that selector rather than guessed from a package
version or filename.

The published machine-readable matrix is
`schemas/persisted-artifact-compatibility-v1.json`. The installed copy is available from
`lacuna.schemas.persisted_artifact_compatibility_v1_text()`. Its format version is independent of
the result, bundle, and audit-profile versions it describes.

## Supported release lines

| Artifact | Producers accepted by `0.9` | Version selector | Current version | Migration |
| --- | --- | --- | ---: | --- |
| `AnalysisResult` JSON | `0.1`–`0.9` | `schema_version` | `"1"` | identity validation |
| `.lacuna` bundle | `0.7`–`0.9` | `bundle_version` | `1` | identity verification |
| standardized audit profile | `0.8`–`0.9` | `schema_version` | `"1"` | identity validation |

An identity migration is meaningful: the consumer validates the old bytes under the original
contract and constructs the current immutable value without changing recorded evidence. There is no
value-transforming migration in this matrix because none of the three persisted formats changed
through `0.8`. Lacuna does not rewrite an old method result to make it appear as though a newer
method produced it.

## Strict readers

Use the reader belonging to the artifact:

```python
import lacuna as lc

result = lc.AnalysisResult.from_json(result_json)
profile = lc.AuditProfile.from_json(profile_json)
manifest = lc.BundleManifest.from_json(manifest_json)
verification = lc.verify_bundle("study.lacuna")
```

`AnalysisResult.from_json(...)` and `AuditProfile.from_json(...)` reject duplicate keys at any
depth, non-finite constants, unknown or missing fields, unsupported versions, invalid enums, and
invalid nested contracts. They do not import plugins, activate entry points, or execute serialized
content.

`BundleManifest.from_json(...)` validates a standalone manifest only. It cannot establish that the
declared archive members exist or match their hashes. Use `verify_bundle(...)` for a complete local
archive; that path additionally enforces ZIP safety, canonical encoding, membership, bounded sizes,
and every SHA-256 digest. Neither path proves authorship or independent recomputation.

## Release-line evidence corpus

`tests/fixtures/persisted-artifact-corpus-v1.json` records the exact SHA-256 and Git blob identity of
the persisted fixtures retained by stable tags:

- the audit-result fixture is one identical Git blob in every `v0.1.0` through `v0.8.0` tag;
- the bundle-manifest fixture is one identical Git blob in `v0.7.0` and `v0.8.0`;
- the standardized-profile fixture is retained from `v0.8.0`.

The regression gate recomputes those identities, validates every fixture against its published JSON
Schema, reads it through the current public reader, and requires semantic round-trip equality. This
tests actual retained release artifacts rather than creating new payloads that merely claim to be
old.

## Failure behavior

Unsupported versions fail closed. A consumer must not:

- feed an unknown envelope to the nearest-looking parser;
- add missing fields with assumed defaults;
- reinterpret finding states, units, thresholds, or method versions;
- treat a validated standalone manifest as verified archive integrity;
- activate a plugin named by serialized evidence;
- overwrite the source artifact during inspection.

An error should report the artifact kind, observed selector, and supported target. It should not
include arbitrary source data, credentials, or exception dumps.

## Adding a real migration

A future value-transforming migration requires all of the following in one review:

1. publish the new format schema and an explicit source-to-target migration route;
2. retain the old fixture and add the new pre/post fixtures;
3. define field, unit, finding-code, and method-version preservation rules;
4. test duplicate, missing, interrupted-write, unsupported-version, and idempotence behavior;
5. keep the original artifact available and write a new destination atomically;
6. update the compatibility matrix, public API fixture, changelog, docs, bundle/wheel smoke, and
   release verifier;
7. state whether the transformation is lossless and which claims still require recomputation.

Package SemVer does not substitute for this process. Result schema, bundle version, profile schema,
profile meaning, and analytical method versions remain separate identities.
