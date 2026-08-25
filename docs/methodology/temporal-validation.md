# Walk-forward validation, purging, and embargo

`lacuna.cv` returns inspectable source-row indices and structured fold evidence. It never shuffles
time. The package contains chronological `WalkForward`, label-aware `PurgedKFold`, and v0.5
`CombinatorialPurgedKFold`; it does not conflate any of them with purged walk-forward validation.

## Walk-forward

```python
split = lc.cv.WalkForward(
    train=60,
    test=20,
    step=20,
    mode="expanding",
).split(data, time="date")
```

Observation-count durations operate on sorted unique time values, not rows. With train (a), test
(b), and step (s), the first test begins at unique-time position (a). `expanding` keeps the first
training time fixed; `rolling` retains at most the most recent (a) unique times.

Calendar durations use positive `D`, `W`, `M`, or `Y` strings and require Polars Date/Datetime values.
Month/year addition clamps the day to the final valid day of the target month. Train, test, and step
must all use the observation-count family or all use the calendar family.

Windows are half-open in time: training precedes the test start and test times satisfy
`test_start <= time < test_end`. The final partial test window is dropped unless
`allow_incomplete=True`. Rows retain their original source indices even though unique times are sorted
to construct windows.

## Label intervals

Purging requires non-null, same-dtype `label_start` and `label_end` values with strict
`label_start < label_end`. Intervals are half-open:

```text
train overlaps test
iff train_start < test_end and train_end > test_start
```

Therefore `[0, 2)` and `[2, 3)` touch but do not overlap.

## Purged K-fold

`PurgedKFold(n_splits=k)` partitions sorted unique observation times into (k) contiguous, as-even-as-
possible test groups. For each fold, every row outside the test-time group is initially a training
candidate. A candidate is purged if its label interval overlaps any test label interval.

```python
purged = lc.cv.PurgedKFold(
    n_splits=5,
    embargo=2,
).split(labels.frame)
```

This is K-fold validation over time blocks, so folds can train on observations chronologically after a
test block. Use `WalkForward` when the research design requires training to be strictly in the past;
v0.1 does not claim `PurgedKFold` is a walk-forward model.

The Python reference merges overlapping test intervals and uses ordered endpoints. The Rust kernel
implements the same interval rule. Property tests assert that every retained train interval is
disjoint from every test interval and that native/reference folds agree.

## Combinatorial purged K-fold

`CombinatorialPurgedKFold(n_groups=N, n_test_groups=k)` partitions unique times into `N`
contiguous, as-even-as-possible groups and holds out all `C(N, k)` combinations. Purging uses the
union of every test label interval in a combination. Embargo is applied separately after every
held-out group, then test periods are removed from the embargo set so test and embargo roles never
overlap.

```python
combinatorial = lc.cv.CombinatorialPurgedKFold(
    n_groups=6,
    n_test_groups=2,
    embargo=2,
    max_combinations=10_000,
).split(labels.frame)
```

Every group has `C(N - 1, k - 1)` test incidences. Ordered group incidence assigns those results to
the same number of complete `CPCVPath` objects. Each path exposes one contributing fold per group
and contains every source row once in chronological group order. This is a reconstruction map for
out-of-sample predictions: the splitter does not fabricate predictions or performance values.

`CombinatorialSplitResult` provides:

- `folds`: every train/test combination with separate purge and embargo indices;
- `paths`: every complete reconstructed test path;
- `groups`: chronological group boundaries and row counts;
- `combinations`: the test-group tuple for each fold;
- `path_table`: each `(path, group, contributing fold)` assignment;
- structured counts for combinations, paths, purged observations, and embargoed observations.

The split count is bounded before enumeration by `max_combinations`. CPCV remains block
cross-validation: training data can be chronologically later than a held-out group. Use a
walk-forward design when strict past-only fitting is the required estimand.

## Embargo

The implemented embargo is a non-negative count of unique observation periods. `PurgedKFold`
applies it immediately after the final test period; `CombinatorialPurgedKFold` applies it after
every held-out group. It is applied after purging and only to candidates still retained. Purged and
embargoed indices are reported separately. Calendar-duration and percentage embargoes are later
methods, not alternative interpretations of the integer parameter.

## Outputs and limitations

Each `Fold` contains `train_indices`, `test_indices`, `purged_indices`, and `embargoed_indices`.
`SplitResult.fold_table` has one row per fold/role with start, end, and count. CPCV additionally
returns explicit group, combination, and path tables. Metadata records the interval closure, source
columns, backend, and materialization evidence.

The splitters do not fit a model, stratify, randomize, or infer label intervals. They also cannot cure
look-ahead already embedded in a feature or universe. Purging protects the train/test label boundary;
it is not a general proof of point-in-time data correctness.
