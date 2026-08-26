# Result schema compatibility

Lacuna's canonical interchange format is the JSON representation of `AnalysisResult`. The v0.1
contract is schema version `1`, published in the repository as
`schemas/audit-result-v1.schema.json` using JSON Schema Draft 2020-12.
The identical wheel resource is available through
`lacuna.schemas.audit_result_v1_text()`; a test prevents the packaged and language-independent copies
from drifting.

## Envelope

Every result contains exactly these top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Compatibility selector; v0.1 emits the string `"1"` |
| `metadata` | Method identity/version, parameters, seed, fingerprint, and UTC creation time |
| `metrics` | Compact named scalar or nested JSON evidence |
| `findings` | Structured state, severity, category, message, and evidence records |
| `tables` | Compact JSON-compatible evidence tables |
| `warnings` | Method limitations that do not fit a finding rule |

Values are canonical JSON values. NaN and positive/negative infinity are rejected during result
construction, not serialized as non-standard tokens. Datetimes are timezone-aware and serialized in
UTC with a `Z` suffix. Mappings are key-sorted during JSON serialization.

## Version behavior

`schema_version` governs the JSON envelope, while `metadata.method_version` governs an analytical
procedure and audit metadata contains the separate score/rule versions. A method threshold change
does not automatically require a result-envelope version, and adding an incompatible envelope field
does not silently change a statistical method.

A consumer should:

1. parse JSON with non-finite values disabled where the parser supports it;
2. read `schema_version` before interpreting other fields;
3. select the matching published schema;
4. reject unsupported major versions;
5. retain unknown method identifiers as data only if the application can display them without
   interpreting their meaning.

`AnalysisResult.from_json(...)` implements the strict supported v1 reader. It rejects duplicate
object keys at any depth, non-finite JSON constants, unsupported schema versions, unknown or missing
envelope/finding fields, invalid enum values, and non-UTC timestamps. `from_dict(...)` applies the
same structural and semantic checks after JSON decoding. Neither reader loads plugins or executes
serialized content.

The same v1 envelope and representative fixture were retained byte-for-byte by every stable
`v0.1.0` through `v0.8.0` tag. The `0.9` compatibility gate treats those release lines as identity
migrations: validate under schema v1 and preserve the recorded method evidence unchanged. See
[Persisted-artifact compatibility](persisted-artifacts.md) for the public matrix and tagged corpus.

## Validation example

`jsonschema` is a development dependency, not a Lacuna runtime dependency:

```python
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

schema = json.loads(Path("schemas/audit-result-v1.schema.json").read_text())
payload = json.loads(Path("lacuna-audit.json").read_text())
Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
```

The committed `tests/fixtures/audit-result-v1.json` and `audit-report-v1.md` fixtures catch accidental
serialization and presentation changes. Intentional compatibility changes update the schema,
fixtures, changelog, and migration guidance together.

## Bundle manifest schema

The result schema and bundle schema have independent version selectors. `schema_version="1"`
describes an `AnalysisResult`; `bundle_version=1` describes the surrounding `.lacuna` archive and
artifact manifest. Bundle v1 is published at
`schemas/lacuna-bundle-manifest-v1.schema.json` and installed as
`lacuna.schemas.bundle_manifest_v1_text()`.

A new bundle layout does not silently change the meaning of an embedded result, and a future result
schema does not automatically require another ZIP layout. Consumers validate both boundaries and
reject either unsupported version. See the
[reproducibility-bundle reference](reproducibility-bundle.md) for artifact and trust semantics.

## Standardized audit profile schema

The standardized-audit profile definition has a third independent schema selector. Profile schema
v1 publishes the profile ID/version, scope, explicit absence of a score model, coverage-rule
version, and the capability/method/disposition matrix at
`schemas/standard-audit-profile-v1.schema.json`. The identical installed resource is available from
`lacuna.schemas.standard_audit_profile_v1_text()`.

Profile schema version governs the portable definition shape; `profile_version` governs its
applicability meaning. `AuditProfile.from_dict(...)` and `from_json(...)` are the strict,
non-executing profile-v1 readers. The generated audit remains an ordinary `AnalysisResult`
schema-v1 object.
