# Result schema compatibility

Lacuna's canonical interchange format is the JSON representation of `AnalysisResult`. The v0.1
contract is schema version `1`, published in the repository as
`schemas/audit-result-v1.schema.json` using JSON Schema Draft 2020-12.

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
