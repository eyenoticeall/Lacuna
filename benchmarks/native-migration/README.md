# Native migration evidence

This directory contains reviewed `lacuna.native-migration-benchmark` version 1 artifacts tied to
exact source commits. Local artifacts are development evidence only. Admission and release closure
still require reproduction on the pinned Linux nightly runner and by the non-publishing release
preflight for the release commit.

Artifacts are immutable once reviewed. A later run is added as a new file rather than replacing an
older result. The checked-in `r01-nightly-e54b757.json` and `r08-nightly-e54b757.json` artifacts are
the authoritative pinned-Linux admission reproductions for the shipped v0.14 kernels. The exact-SHA
release preflight repeats them as a publication gate.
