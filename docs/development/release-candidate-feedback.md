# Release-candidate feedback

Independent use is an acceptance gate for Lacuna `0.1`, not a marketing checkbox. Maintainer tests
can establish internal consistency and platform coverage; they cannot prove that the API fits an
unfamiliar research stack or that the evidence is understandable without project context.

## Acceptance criteria

The `0.1` candidate can graduate only after all of the following are evidenced publicly or in a
maintainer-reviewed private record:

1. At least two people who did not implement the tested path run the tagged candidate.
2. Their tests cover at least two operating-system/architecture combinations.
3. At least one test uses pandas, PyArrow, NumPy, or a Polars lazy input rather than only an eager
   Polars frame.
4. At least one tester independently compares a reported statistic or split with another
   implementation or a hand-checkable fixture.
5. Both testers inspect copy/materialization provenance and the meaning of `UNKNOWN` findings.
6. No open release-blocking correctness, leakage, packaging, or security report remains.

Passing these criteria does not claim statistical correctness for every dataset. It proves that the
candidate survived concrete use outside its implementation environment.

## Tester protocol

### 1. Install an artifact

Download the wheel matching the target platform from the tagged GitHub prerelease and install it in a
new environment. Normal users should not install a Rust toolchain.

```bash
python -m venv .lacuna-rc
.lacuna-rc/bin/python -m pip install ./lacuna-0.1.0rc1-*.whl
.lacuna-rc/bin/lacuna doctor --json
```

On Windows, use `.lacuna-rc\Scripts\python.exe` and `.lacuna-rc\Scripts\lacuna.exe`.

### 2. Verify the artifact

Compare the downloaded file with `SHA256SUMS`. A GitHub attestation can also be checked with:

```bash
gh attestation verify lacuna-0.1.0rc1-*.whl --repo eyenoticeall/Lacuna
```

### 3. Run an independent study

Use a synthetic, public, or non-sensitive private sample. Exercise labels, at least one signal
diagnostic, one temporal-validation path, bootstrap inference, and an audit renderer. Compare one
headline value or fold boundary with an independent calculation.

### 4. Inspect evidence quality

Review:

- execution timing and interval assumptions;
- excluded and censored row counts;
- backend and method versions;
- `adapter_copy`, `materialization_reason`, and `execution_operations`;
- every warning, failure, and `UNKNOWN` finding;
- JSON/Markdown/HTML agreement.

### 5. Submit feedback

Use the repository's
[v0.1 RC feedback form](https://github.com/eyenoticeall/Lacuna/issues/new?template=rc-feedback.yml).
Remove credentials, proprietary data, and sensitive research details. A minimal synthetic reproducer
is preferred for discrepancies.

## Evidence register

Feedback is not counted until it links to a reviewable record and satisfies the protocol above.
The public recruitment and graduation checklist lives in
[GitHub issue #2](https://github.com/eyenoticeall/Lacuna/issues/2).

| Tester record | Platform | Input boundary | Independent comparison | Disposition |
| --- | --- | --- | --- | --- |
| [Tracker #2](https://github.com/eyenoticeall/Lacuna/issues/2) | — | — | — | Awaiting external tests |

The pending row is deliberately explicit. It must not be interpreted as completed independent
validation.
