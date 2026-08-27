//! Performance-critical kernels shared by Lacuna's language bindings.
//!
//! The crate begins intentionally small. New kernels belong here only after a
//! reference implementation and benchmark demonstrate that native code is the
//! appropriate execution path.

use std::error::Error;
use std::fmt::{Display, Formatter};

/// Errors returned by numeric kernels.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NumericError {
    /// The input did not contain any observations.
    EmptyInput,
    /// The input contained a NaN or an infinite value.
    NonFiniteValue { index: usize },
    /// Two input arrays that must align have different lengths.
    LengthMismatch,
    /// Group or resample offsets do not describe the complete input.
    InvalidOffsets,
    /// A bootstrap index points outside the values array.
    IndexOutOfBounds { index: usize },
    /// An interval has its end before its start.
    InvalidInterval { index: usize },
    /// Matrix dimensions, partitions, or statistic configuration are invalid.
    InvalidDimensions,
    /// A PBO partition combination is not sorted, unique, or in range.
    InvalidCombination { index: usize },
    /// CPCV buffers, dimensions, or group boundaries are inconsistent.
    InvalidCpcvDimensions,
    /// A CPCV row has an invalid chronological group or period code.
    InvalidCpcvGroup { index: usize },
    /// A CPCV held-out combination is not sorted, unique, or in range.
    InvalidCpcvCombination { index: usize },
    /// A built-in statistic is undefined for at least one strategy.
    UndefinedStatistic,
    /// Finite inputs produced a non-finite intermediate result.
    NonFiniteComputation,
}

impl Display for NumericError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EmptyInput => formatter.write_str("input must contain at least one value"),
            Self::NonFiniteValue { index } => {
                write!(
                    formatter,
                    "input contains a non-finite value at index {index}"
                )
            }
            Self::LengthMismatch => formatter.write_str("aligned inputs must have equal lengths"),
            Self::InvalidOffsets => formatter.write_str(
                "offsets must begin at zero, be non-decreasing, and end at the input length",
            ),
            Self::IndexOutOfBounds { index } => {
                write!(formatter, "bootstrap index {index} is out of bounds")
            }
            Self::InvalidInterval { index } => {
                write!(formatter, "interval {index} must end after it starts")
            }
            Self::InvalidDimensions => formatter.write_str(
                "matrix dimensions and partition configuration must describe a non-empty, evenly partitioned matrix",
            ),
            Self::InvalidCombination { index } => write!(
                formatter,
                "partition combination {index} must contain sorted, unique, in-range group codes",
            ),
            Self::InvalidCpcvDimensions => formatter.write_str(
                "CPCV dimensions and group boundaries must describe a non-empty valid split",
            ),
            Self::InvalidCpcvGroup { index } => write!(
                formatter,
                "CPCV row {index} must contain in-range chronological group and period codes",
            ),
            Self::InvalidCpcvCombination { index } => write!(
                formatter,
                "CPCV combination {index} must contain sorted, unique, in-range group codes",
            ),
            Self::UndefinedStatistic => formatter.write_str(
                "PBO Sharpe statistic is undefined for a constant strategy",
            ),
            Self::NonFiniteComputation => {
                formatter.write_str("finite inputs produced a non-finite statistic")
            }
        }
    }
}

impl Error for NumericError {}

/// Dense values and byte validity for nullable floating-point kernel output.
#[derive(Debug, Clone, PartialEq)]
pub struct NullableF64Buffer {
    /// Floating-point values; invalid positions contain a deterministic zero placeholder.
    pub values: Vec<f64>,
    /// One marks a defined value and zero marks an undefined value.
    pub validity: Vec<u8>,
}

/// Built-in performance statistic supported by the compact PBO kernel.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PboStatistic {
    /// Arithmetic mean performance.
    Mean,
    /// Arithmetic mean divided by sample standard deviation.
    Sharpe,
}

/// Compact per-combination output from the PBO split reducer.
#[derive(Debug, Clone, PartialEq)]
pub struct PboSplitBuffer {
    /// Selected in-sample strategy index for each combination.
    pub selected_strategy: Vec<usize>,
    /// Selected strategy's in-sample performance.
    pub in_sample_performance: Vec<f64>,
    /// Selected strategy's out-of-sample performance.
    pub out_of_sample_performance: Vec<f64>,
    /// Average out-of-sample rank of the selected strategy.
    pub out_of_sample_rank: Vec<f64>,
    /// Logit of the selected strategy's relative rank.
    pub logit: Vec<f64>,
    /// One when multiple strategies shared the maximum in-sample performance.
    pub selection_tie: Vec<u8>,
    /// One when the selected strategy's out-of-sample logit is non-positive.
    pub underperformed_median: Vec<u8>,
}

/// CSR-style role indices and compact CPCV path incidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompactFoldBuffer {
    /// Concatenated source-order training indices.
    pub train_indices: Vec<usize>,
    /// Offsets delimiting one training slice per fold.
    pub train_offsets: Vec<usize>,
    /// Concatenated source-order test indices.
    pub test_indices: Vec<usize>,
    /// Offsets delimiting one test slice per fold.
    pub test_offsets: Vec<usize>,
    /// Concatenated source-order purged indices.
    pub purged_indices: Vec<usize>,
    /// Offsets delimiting one purge slice per fold.
    pub purged_offsets: Vec<usize>,
    /// Concatenated source-order embargoed indices.
    pub embargoed_indices: Vec<usize>,
    /// Offsets delimiting one embargo slice per fold.
    pub embargoed_offsets: Vec<usize>,
    /// Path-major fold numbers, one for each chronological group.
    pub path_fold_by_group: Vec<usize>,
    /// Offsets delimiting one group-incidence slice per path.
    pub path_offsets: Vec<usize>,
}

/// Borrowed, validated-at-use buffers for complete CPCV assembly.
#[derive(Debug, Clone, Copy)]
pub struct CpcvAssemblyInput<'a> {
    /// Chronological group code for each source row.
    pub row_groups: &'a [usize],
    /// Chronological observation-period code for each source row.
    pub row_periods: &'a [usize],
    /// Half-open label interval starts.
    pub starts: &'a [i64],
    /// Half-open label interval ends.
    pub ends: &'a [i64],
    /// Final chronological period code in each group.
    pub group_end_periods: &'a [usize],
    /// Flattened, sorted held-out group combinations.
    pub combination_groups: &'a [usize],
    /// Held-out groups in every combination.
    pub groups_per_combination: usize,
    /// Observation-period embargo after every held-out group.
    pub embargo: usize,
}

/// Compute a checked arithmetic mean using Neumaier compensated summation.
///
/// This small kernel is the initial cross-language smoke test. It establishes
/// error semantics and numerical-care conventions without claiming to be a
/// complete statistical implementation.
///
/// # Errors
///
/// Returns [`NumericError::EmptyInput`] for an empty slice and
/// [`NumericError::NonFiniteValue`] when an observation is NaN or infinite.
pub fn checked_mean(values: &[f64]) -> Result<f64, NumericError> {
    if values.is_empty() {
        return Err(NumericError::EmptyInput);
    }

    let mut sum = 0.0;
    let mut correction = 0.0;

    for (index, value) in values.iter().copied().enumerate() {
        if !value.is_finite() {
            return Err(NumericError::NonFiniteValue { index });
        }

        let candidate = sum + value;
        if sum.abs() >= value.abs() {
            correction += (sum - candidate) + value;
        } else {
            correction += (value - candidate) + sum;
        }
        sum = candidate;
    }

    // Any in-memory slice large enough to lose integer precision here is not
    // addressable on supported targets; the cast is appropriate for a mean.
    #[allow(clippy::cast_precision_loss)]
    let count = values.len() as f64;
    Ok((sum + correction) / count)
}

fn validate_offsets(offsets: &[usize], length: usize) -> Result<(), NumericError> {
    if offsets.len() < 2
        || offsets.first() != Some(&0)
        || offsets.last() != Some(&length)
        || offsets.windows(2).any(|window| window[0] > window[1])
    {
        return Err(NumericError::InvalidOffsets);
    }
    Ok(())
}

// Exact numeric equality defines a rank tie; this intentionally makes -0.0 and +0.0 equal.
#[allow(clippy::float_cmp)]
fn average_ranks(values: &[f64]) -> Vec<f64> {
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|left, right| values[*left].total_cmp(&values[*right]));

    let mut ranks = vec![0.0; values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && values[order[end]] == values[order[start]] {
            end += 1;
        }
        #[allow(clippy::cast_precision_loss)]
        let average = ((start + 1 + end) as f64) / 2.0;
        for index in &order[start..end] {
            ranks[*index] = average;
        }
        start = end;
    }
    ranks
}

fn pearson(left: &[f64], right: &[f64]) -> Option<f64> {
    if left.len() < 2 || left.len() != right.len() {
        return None;
    }
    #[allow(clippy::cast_precision_loss)]
    let count = left.len() as f64;
    let left_mean = left.iter().sum::<f64>() / count;
    let right_mean = right.iter().sum::<f64>() / count;
    let mut covariance = 0.0;
    let mut left_variance = 0.0;
    let mut right_variance = 0.0;
    for (left_value, right_value) in left.iter().zip(right) {
        let left_centered = left_value - left_mean;
        let right_centered = right_value - right_mean;
        covariance += left_centered * right_centered;
        left_variance += left_centered * left_centered;
        right_variance += right_centered * right_centered;
    }
    let denominator = (left_variance * right_variance).sqrt();
    if denominator == 0.0 {
        None
    } else {
        Some((covariance / denominator).clamp(-1.0, 1.0))
    }
}

/// Compute average-rank Spearman correlation for contiguous groups.
///
/// `offsets` contains group boundaries and must start at zero and end at the
/// common input length. Groups with fewer than two observations or zero rank
/// variance return `None`.
///
/// # Errors
///
/// Returns an error for unequal lengths, non-finite values, or invalid offsets.
pub fn grouped_rank_ic(
    signal: &[f64],
    labels: &[f64],
    offsets: &[usize],
) -> Result<Vec<Option<f64>>, NumericError> {
    if signal.len() != labels.len() {
        return Err(NumericError::LengthMismatch);
    }
    validate_offsets(offsets, signal.len())?;
    for (index, value) in signal.iter().chain(labels).copied().enumerate() {
        if !value.is_finite() {
            return Err(NumericError::NonFiniteValue { index });
        }
    }

    Ok(offsets
        .windows(2)
        .map(|window| {
            let signal_ranks = average_ranks(&signal[window[0]..window[1]]);
            let label_ranks = average_ranks(&labels[window[0]..window[1]]);
            pearson(&signal_ranks, &label_ranks)
        })
        .collect())
}

/// Compute grouped rank IC into contiguous values and byte validity buffers.
///
/// This compact carrier avoids constructing nullable Python objects at the
/// language boundary while retaining [`grouped_rank_ic`] as the legible oracle.
///
/// # Errors
///
/// Returns the same checked input errors as [`grouped_rank_ic`].
pub fn grouped_rank_ic_buffer(
    signal: &[f64],
    labels: &[f64],
    offsets: &[usize],
) -> Result<NullableF64Buffer, NumericError> {
    let correlations = grouped_rank_ic(signal, labels, offsets)?;
    let mut values = Vec::with_capacity(correlations.len());
    let mut validity = Vec::with_capacity(correlations.len());
    for correlation in correlations {
        if let Some(value) = correlation {
            values.push(value);
            validity.push(1);
        } else {
            values.push(0.0);
            validity.push(0);
        }
    }
    Ok(NullableF64Buffer { values, validity })
}

/// Reduce pre-generated bootstrap index batches to arithmetic means.
///
/// Random-index generation remains outside this kernel so callers can derive
/// stable per-replicate streams independent of worker scheduling. `offsets`
/// bounds each resample in the flattened `indices` array.
///
/// # Errors
///
/// Returns an error for empty/non-finite values, invalid offsets, empty
/// resamples, or an out-of-bounds index.
pub fn bootstrap_means(
    values: &[f64],
    indices: &[usize],
    offsets: &[usize],
) -> Result<Vec<f64>, NumericError> {
    if values.is_empty() {
        return Err(NumericError::EmptyInput);
    }
    for (index, value) in values.iter().copied().enumerate() {
        if !value.is_finite() {
            return Err(NumericError::NonFiniteValue { index });
        }
    }
    validate_offsets(offsets, indices.len())?;

    offsets
        .windows(2)
        .map(|window| {
            if window[0] == window[1] {
                return Err(NumericError::EmptyInput);
            }
            let mut sum = 0.0;
            let mut correction = 0.0;
            for index in &indices[window[0]..window[1]] {
                let value = values
                    .get(*index)
                    .ok_or(NumericError::IndexOutOfBounds { index: *index })?;
                let candidate = sum + value;
                if sum.abs() >= value.abs() {
                    correction += (sum - candidate) + value;
                } else {
                    correction += (value - candidate) + sum;
                }
                sum = candidate;
            }
            #[allow(clippy::cast_precision_loss)]
            let count = (window[1] - window[0]) as f64;
            Ok((sum + correction) / count)
        })
        .collect()
}

#[derive(Debug, Clone, Copy)]
struct Moments {
    count: usize,
    mean: f64,
    m2: f64,
}

impl Moments {
    fn empty() -> Self {
        Self {
            count: 0,
            mean: 0.0,
            m2: 0.0,
        }
    }

    fn update(&mut self, value: f64) {
        self.count += 1;
        #[allow(clippy::cast_precision_loss)]
        let count = self.count as f64;
        let delta = value - self.mean;
        self.mean += delta / count;
        self.m2 += delta * (value - self.mean);
    }

    fn combine(&mut self, other: Self) {
        if other.count == 0 {
            return;
        }
        if self.count == 0 {
            *self = other;
            return;
        }
        let combined_count = self.count + other.count;
        #[allow(clippy::cast_precision_loss)]
        let left_count = self.count as f64;
        #[allow(clippy::cast_precision_loss)]
        let right_count = other.count as f64;
        #[allow(clippy::cast_precision_loss)]
        let combined_count_float = combined_count as f64;
        let delta = other.mean - self.mean;
        self.mean += delta * (right_count / combined_count_float);
        self.m2 += other.m2 + delta * delta * (left_count * right_count / combined_count_float);
        self.count = combined_count;
    }

    fn performance(self, statistic: PboStatistic) -> Result<f64, NumericError> {
        let result = match statistic {
            PboStatistic::Mean => self.mean,
            PboStatistic::Sharpe => {
                if self.count < 2 || self.m2 <= 0.0 {
                    return Err(NumericError::UndefinedStatistic);
                }
                #[allow(clippy::cast_precision_loss)]
                let denominator = (self.m2 / ((self.count - 1) as f64)).sqrt();
                self.mean / denominator
            }
        };
        if result.is_finite() {
            Ok(result)
        } else {
            Err(NumericError::NonFiniteComputation)
        }
    }
}

// Exact equality defines PBO rank ties and intentionally treats signed zero as tied.
#[allow(clippy::float_cmp)]
fn selected_average_rank(values: &[f64], selected: usize) -> f64 {
    let selected_value = values[selected];
    let less = values
        .iter()
        .filter(|value| **value < selected_value)
        .count();
    let equal = values
        .iter()
        .filter(|value| **value == selected_value)
        .count();
    #[allow(clippy::cast_precision_loss)]
    let rank = less as f64 + (equal + 1) as f64 / 2.0;
    rank
}

// Exact equality preserves the public tie policy; a tolerance would change the estimand.
#[allow(clippy::float_cmp)]
fn selected_maximum(values: &[f64]) -> (usize, bool) {
    let mut selected = 0;
    for index in 1..values.len() {
        if values[index] > values[selected] {
            selected = index;
        }
    }
    let selected_value = values[selected];
    let tie = values
        .iter()
        .filter(|value| **value == selected_value)
        .count()
        > 1;
    (selected, tie)
}

/// Reduce CSCV partition combinations for built-in PBO statistics.
///
/// `values` is a row-major `rows x columns` matrix. `combination_groups`
/// contains flattened, sorted in-sample partition codes; each combination has
/// exactly `groups_per_combination` codes. The complement defines its
/// out-of-sample groups. Policy, combination enumeration, and public result
/// construction remain caller responsibilities.
///
/// # Errors
///
/// Returns checked errors for invalid dimensions, non-finite input, invalid
/// group codes, undefined Sharpe statistics, or non-finite computation.
pub fn pbo_partition_splits(
    values: &[f64],
    rows: usize,
    columns: usize,
    partitions: usize,
    combination_groups: &[usize],
    groups_per_combination: usize,
    statistic: PboStatistic,
) -> Result<PboSplitBuffer, NumericError> {
    if rows == 0
        || columns < 2
        || partitions < 2
        || partitions % 2 != 0
        || rows % partitions != 0
        || groups_per_combination != partitions / 2
        || groups_per_combination == 0
        || combination_groups.is_empty()
        || combination_groups.len() % groups_per_combination != 0
        || rows.checked_mul(columns) != Some(values.len())
    {
        return Err(NumericError::InvalidDimensions);
    }
    for (index, value) in values.iter().copied().enumerate() {
        if !value.is_finite() {
            return Err(NumericError::NonFiniteValue { index });
        }
    }

    let combination_count = combination_groups.len() / groups_per_combination;
    for (combination, groups) in combination_groups
        .chunks_exact(groups_per_combination)
        .enumerate()
    {
        if groups.iter().any(|group| *group >= partitions)
            || groups.windows(2).any(|window| window[0] >= window[1])
        {
            return Err(NumericError::InvalidCombination { index: combination });
        }
    }

    let group_size = rows / partitions;
    let mut partition_moments = vec![Moments::empty(); partitions * columns];
    for group in 0..partitions {
        for row_in_group in 0..group_size {
            let row = group * group_size + row_in_group;
            for column in 0..columns {
                partition_moments[group * columns + column].update(values[row * columns + column]);
            }
        }
    }

    let mut selected_strategy = Vec::with_capacity(combination_count);
    let mut in_sample_performance = Vec::with_capacity(combination_count);
    let mut out_of_sample_performance = Vec::with_capacity(combination_count);
    let mut out_of_sample_rank = Vec::with_capacity(combination_count);
    let mut logits = Vec::with_capacity(combination_count);
    let mut selection_tie = Vec::with_capacity(combination_count);
    let mut underperformed_median = Vec::with_capacity(combination_count);
    let mut included = vec![0_u8; partitions];
    let mut in_sample = vec![0.0; columns];
    let mut out_of_sample = vec![0.0; columns];

    for groups in combination_groups.chunks_exact(groups_per_combination) {
        included.fill(0);
        for group in groups {
            included[*group] = 1;
        }
        for column in 0..columns {
            let mut in_moments = Moments::empty();
            let mut out_moments = Moments::empty();
            for group in 0..partitions {
                let moments = partition_moments[group * columns + column];
                if included[group] != 0 {
                    in_moments.combine(moments);
                } else {
                    out_moments.combine(moments);
                }
            }
            in_sample[column] = in_moments.performance(statistic)?;
            out_of_sample[column] = out_moments.performance(statistic)?;
        }

        let (selected, tied) = selected_maximum(&in_sample);
        let rank = selected_average_rank(&out_of_sample, selected);
        #[allow(clippy::cast_precision_loss)]
        let relative_rank = rank / ((columns + 1) as f64);
        let logit = (relative_rank / (1.0 - relative_rank)).ln();
        if !logit.is_finite() {
            return Err(NumericError::NonFiniteComputation);
        }
        selected_strategy.push(selected);
        in_sample_performance.push(in_sample[selected]);
        out_of_sample_performance.push(out_of_sample[selected]);
        out_of_sample_rank.push(rank);
        logits.push(logit);
        selection_tie.push(u8::from(tied));
        underperformed_median.push(u8::from(logit <= 0.0));
    }

    Ok(PboSplitBuffer {
        selected_strategy,
        in_sample_performance,
        out_of_sample_performance,
        out_of_sample_rank,
        logit: logits,
        selection_tie,
        underperformed_median,
    })
}

fn merged_selected_intervals(starts: &[i64], ends: &[i64], selected: &[usize]) -> Vec<(i64, i64)> {
    let mut intervals: Vec<(i64, i64)> = selected
        .iter()
        .map(|index| (starts[*index], ends[*index]))
        .collect();
    intervals.sort_unstable();
    let mut merged: Vec<(i64, i64)> = Vec::with_capacity(intervals.len());
    for (start, end) in intervals {
        if let Some(last) = merged.last_mut() {
            if start <= last.1 {
                last.1 = last.1.max(end);
                continue;
            }
        }
        merged.push((start, end));
    }
    merged
}

fn interval_overlaps(merged: &[(i64, i64)], start: i64, end: i64) -> bool {
    let candidate = merged.partition_point(|(_, test_end)| *test_end <= start);
    candidate < merged.len() && merged[candidate].0 < end
}

fn validate_cpcv_input(input: &CpcvAssemblyInput<'_>) -> Result<(usize, usize), NumericError> {
    let row_count = input.row_groups.len();
    let group_count = input.group_end_periods.len();
    if row_count == 0
        || input.row_periods.len() != row_count
        || input.starts.len() != row_count
        || input.ends.len() != row_count
        || group_count < 2
        || input.groups_per_combination == 0
        || input.groups_per_combination >= group_count
        || input.combination_groups.is_empty()
        || input.combination_groups.len() % input.groups_per_combination != 0
        || input
            .group_end_periods
            .windows(2)
            .any(|window| window[0] >= window[1])
    {
        return Err(NumericError::InvalidCpcvDimensions);
    }
    for (index, (start, end)) in input.starts.iter().zip(input.ends).enumerate() {
        if end <= start {
            return Err(NumericError::InvalidInterval { index });
        }
    }
    for index in 0..row_count {
        let group = input.row_groups[index];
        if group >= group_count {
            return Err(NumericError::InvalidCpcvGroup { index });
        }
        let lower = if group == 0 {
            0
        } else {
            input.group_end_periods[group - 1].saturating_add(1)
        };
        if input.row_periods[index] < lower
            || input.row_periods[index] > input.group_end_periods[group]
        {
            return Err(NumericError::InvalidCpcvGroup { index });
        }
    }
    for (combination, groups) in input
        .combination_groups
        .chunks_exact(input.groups_per_combination)
        .enumerate()
    {
        if groups.iter().any(|group| *group >= group_count)
            || groups.windows(2).any(|window| window[0] >= window[1])
        {
            return Err(NumericError::InvalidCpcvCombination { index: combination });
        }
    }
    Ok((row_count, group_count))
}

fn cpcv_path_incidence(
    group_count: usize,
    combination_groups: &[usize],
    groups_per_combination: usize,
) -> Result<(Vec<usize>, Vec<usize>), NumericError> {
    let mut group_folds = vec![Vec::new(); group_count];
    for (fold, groups) in combination_groups
        .chunks_exact(groups_per_combination)
        .enumerate()
    {
        for group in groups {
            group_folds[*group].push(fold);
        }
    }
    let path_count = group_folds[0].len();
    if path_count == 0 || group_folds.iter().any(|folds| folds.len() != path_count) {
        return Err(NumericError::InvalidCpcvDimensions);
    }
    let mut path_fold_by_group = Vec::with_capacity(path_count * group_count);
    let mut path_offsets = Vec::with_capacity(path_count + 1);
    path_offsets.push(0);
    for path in 0..path_count {
        for folds in &group_folds {
            path_fold_by_group.push(folds[path]);
        }
        path_offsets.push(path_fold_by_group.len());
    }
    Ok((path_fold_by_group, path_offsets))
}

/// Assemble complete CPCV train/test/purge/embargo index sets and path incidence.
///
/// Row groups and period codes are zero-based chronological codes resolved by
/// the caller. `combination_groups` contains flattened, sorted held-out group
/// codes. All role indices preserve original source-row order.
///
/// # Errors
///
/// Returns checked errors for misaligned buffers, invalid intervals, group or
/// period codes, malformed combinations, or inconsistent group boundaries.
pub fn cpcv_fold_assembly(input: CpcvAssemblyInput<'_>) -> Result<CompactFoldBuffer, NumericError> {
    let (row_count, group_count) = validate_cpcv_input(&input)?;
    let fold_count = input.combination_groups.len() / input.groups_per_combination;
    let mut train_indices = Vec::new();
    let mut test_indices = Vec::new();
    let mut purged_indices = Vec::new();
    let mut embargoed_indices = Vec::new();
    let mut train_offsets = Vec::with_capacity(fold_count + 1);
    let mut test_offsets = Vec::with_capacity(fold_count + 1);
    let mut purged_offsets = Vec::with_capacity(fold_count + 1);
    let mut embargoed_offsets = Vec::with_capacity(fold_count + 1);
    train_offsets.push(0);
    test_offsets.push(0);
    purged_offsets.push(0);
    embargoed_offsets.push(0);
    let mut held_group = vec![0_u8; group_count];
    let mut selected_test_indices = Vec::new();

    for groups in input
        .combination_groups
        .chunks_exact(input.groups_per_combination)
    {
        held_group.fill(0);
        for group in groups {
            held_group[*group] = 1;
        }
        selected_test_indices.clear();
        selected_test_indices.extend(
            input
                .row_groups
                .iter()
                .enumerate()
                .filter_map(|(index, group)| (held_group[*group] == 1).then_some(index)),
        );
        let merged = merged_selected_intervals(input.starts, input.ends, &selected_test_indices);
        let fold_test_start = test_indices.len();
        for index in 0..row_count {
            let group = input.row_groups[index];
            if held_group[group] == 1 {
                test_indices.push(index);
                continue;
            }
            if interval_overlaps(&merged, input.starts[index], input.ends[index]) {
                purged_indices.push(index);
                continue;
            }
            let period = input.row_periods[index];
            let embargoed = input.embargo > 0
                && groups.iter().any(|group| {
                    let final_period = input.group_end_periods[*group];
                    period > final_period && period <= final_period.saturating_add(input.embargo)
                });
            if embargoed {
                embargoed_indices.push(index);
            } else {
                train_indices.push(index);
            }
        }
        debug_assert_eq!(
            test_indices.len() - fold_test_start,
            selected_test_indices.len()
        );
        train_offsets.push(train_indices.len());
        test_offsets.push(test_indices.len());
        purged_offsets.push(purged_indices.len());
        embargoed_offsets.push(embargoed_indices.len());
    }

    let (path_fold_by_group, path_offsets) = cpcv_path_incidence(
        group_count,
        input.combination_groups,
        input.groups_per_combination,
    )?;

    Ok(CompactFoldBuffer {
        train_indices,
        train_offsets,
        test_indices,
        test_offsets,
        purged_indices,
        purged_offsets,
        embargoed_indices,
        embargoed_offsets,
        path_fold_by_group,
        path_offsets,
    })
}

/// Mark each training interval that overlaps at least one test interval.
///
/// Intervals are half-open: `[start, end)`. Touching boundaries do not overlap.
///
/// # Errors
///
/// Returns an error for unequal start/end lengths or an end before its start.
pub fn interval_purge(
    train_starts: &[i64],
    train_ends: &[i64],
    test_starts: &[i64],
    test_ends: &[i64],
) -> Result<Vec<bool>, NumericError> {
    if train_starts.len() != train_ends.len() || test_starts.len() != test_ends.len() {
        return Err(NumericError::LengthMismatch);
    }
    for (index, (start, end)) in train_starts.iter().zip(train_ends).enumerate() {
        if end <= start {
            return Err(NumericError::InvalidInterval { index });
        }
    }
    for (index, (start, end)) in test_starts.iter().zip(test_ends).enumerate() {
        if end <= start {
            return Err(NumericError::InvalidInterval { index });
        }
    }

    let mut test_intervals: Vec<(i64, i64)> = test_starts
        .iter()
        .zip(test_ends)
        .map(|(start, end)| (*start, *end))
        .collect();
    test_intervals.sort_unstable();
    let mut merged: Vec<(i64, i64)> = Vec::with_capacity(test_intervals.len());
    for (start, end) in test_intervals {
        if let Some(last) = merged.last_mut() {
            if start <= last.1 {
                last.1 = last.1.max(end);
                continue;
            }
        }
        merged.push((start, end));
    }

    Ok(train_starts
        .iter()
        .zip(train_ends)
        .map(|(train_start, train_end)| {
            let candidate = merged.partition_point(|(_, end)| *end <= *train_start);
            candidate < merged.len() && merged[candidate].0 < *train_end
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::{
        CpcvAssemblyInput, NumericError, PboStatistic, bootstrap_means, checked_mean,
        cpcv_fold_assembly, grouped_rank_ic, grouped_rank_ic_buffer, interval_purge,
        pbo_partition_splits,
    };

    #[test]
    fn computes_the_mean() {
        let result = checked_mean(&[1.0, 2.0, 6.0]).expect("valid input");
        assert!((result - 3.0).abs() <= f64::EPSILON);
    }

    #[test]
    fn compensates_for_large_magnitude_cancellation() {
        let result = checked_mean(&[1.0e16, 1.0, -1.0e16]).expect("valid input");
        assert!((result - (1.0 / 3.0)).abs() <= f64::EPSILON);
    }

    #[test]
    fn rejects_empty_input() {
        assert_eq!(checked_mean(&[]), Err(NumericError::EmptyInput));
    }

    #[test]
    fn rejects_non_finite_input() {
        assert_eq!(
            checked_mean(&[1.0, f64::NAN]),
            Err(NumericError::NonFiniteValue { index: 1 })
        );
    }

    #[test]
    fn grouped_rank_ic_uses_average_ties() {
        let result = grouped_rank_ic(
            &[1.0, 2.0, 2.0, 4.0, 4.0, 3.0],
            &[1.0, 2.0, 3.0, 4.0, 1.0, 2.0],
            &[0, 4, 6],
        )
        .expect("valid grouped data");
        assert!((result[0].expect("defined group") - 0.948_683_298_050_513_8).abs() < 1e-14);
        assert_eq!(result[1], Some(-1.0));
    }

    #[test]
    fn grouped_rank_ic_marks_constant_groups_undefined() {
        let result = grouped_rank_ic(&[1.0, 1.0], &[1.0, 2.0], &[0, 2]).expect("valid group");
        assert_eq!(result, vec![None]);
    }

    #[test]
    fn grouped_rank_ic_treats_signed_zero_as_a_tie() {
        let result =
            grouped_rank_ic(&[1.0, 2.0, 3.0], &[0.0, -0.0, 1.0], &[0, 3]).expect("valid group");
        assert!((result[0].expect("defined group") - 0.866_025_403_784_438_7).abs() < 1e-14);

        let constant =
            grouped_rank_ic(&[1.0, 2.0], &[0.0, -0.0], &[0, 2]).expect("valid constant group");
        assert_eq!(constant, vec![None]);
    }

    #[test]
    fn grouped_rank_ic_rejects_invalid_offsets() {
        assert_eq!(
            grouped_rank_ic(&[1.0], &[2.0], &[1, 1]),
            Err(NumericError::InvalidOffsets)
        );
    }

    #[test]
    fn grouped_rank_ic_buffer_uses_dense_values_and_byte_validity() {
        let result = grouped_rank_ic_buffer(
            &[1.0, 2.0, 3.0, 1.0, 1.0],
            &[1.0, 2.0, 3.0, 1.0, 2.0],
            &[0, 3, 5],
        )
        .expect("valid grouped data");
        assert_eq!(result.values, vec![1.0, 0.0]);
        assert_eq!(result.validity, vec![1, 0]);
    }

    #[test]
    fn bootstrap_means_reduce_flattened_resamples() {
        let result = bootstrap_means(&[1.0, 2.0, 5.0], &[0, 0, 2, 1, 2, 2], &[0, 3, 6])
            .expect("valid bootstrap indices");
        assert_eq!(result, vec![7.0 / 3.0, 4.0]);
    }

    #[test]
    fn bootstrap_means_reject_out_of_bounds_indices() {
        assert_eq!(
            bootstrap_means(&[1.0], &[1], &[0, 1]),
            Err(NumericError::IndexOutOfBounds { index: 1 })
        );
    }

    fn literal_performance(values: &[f64], columns: usize, rows: &[usize]) -> Vec<f64> {
        (0..columns)
            .map(|column| {
                let selected: Vec<f64> = rows
                    .iter()
                    .map(|row| values[row * columns + column])
                    .collect();
                #[allow(clippy::cast_precision_loss)]
                let count = selected.len() as f64;
                let mean = selected.iter().sum::<f64>() / count;
                let variance = selected
                    .iter()
                    .map(|value| (value - mean).powi(2))
                    .sum::<f64>()
                    / (count - 1.0);
                mean / variance.sqrt()
            })
            .collect()
    }

    #[test]
    #[allow(clippy::cast_precision_loss)]
    fn pbo_partition_splits_match_literal_row_selection() {
        let rows = 24;
        let columns = 5;
        let partitions = 6;
        let group_size = rows / partitions;
        let values: Vec<f64> = (0..rows)
            .flat_map(|row| {
                (0..columns).map(move |column| {
                    ((row * 17 + column * 31) as f64 * 0.071).sin() + (column as f64 * 0.03)
                })
            })
            .collect();
        let combinations = [0, 1, 2, 0, 1, 3, 0, 1, 4, 0, 1, 5];
        let result = pbo_partition_splits(
            &values,
            rows,
            columns,
            partitions,
            &combinations,
            3,
            PboStatistic::Sharpe,
        )
        .expect("valid PBO input");

        for (combination_index, groups) in combinations.chunks_exact(3).enumerate() {
            let mut in_rows = Vec::new();
            let mut out_rows = Vec::new();
            for group in 0..partitions {
                let target = if groups.contains(&group) {
                    &mut in_rows
                } else {
                    &mut out_rows
                };
                target.extend(group * group_size..(group + 1) * group_size);
            }
            let in_performance = literal_performance(&values, columns, &in_rows);
            let out_performance = literal_performance(&values, columns, &out_rows);
            let selected = in_performance
                .iter()
                .enumerate()
                .max_by(|left, right| left.1.total_cmp(right.1))
                .map(|(index, _)| index)
                .expect("strategies exist");
            assert_eq!(result.selected_strategy[combination_index], selected);
            assert!(
                (result.in_sample_performance[combination_index] - in_performance[selected]).abs()
                    < 1e-12
            );
            assert!(
                (result.out_of_sample_performance[combination_index] - out_performance[selected])
                    .abs()
                    < 1e-12
            );
        }
    }

    #[test]
    fn pbo_partition_splits_report_ties_and_mean_ranks() {
        let result = pbo_partition_splits(
            &[1.0, 1.0, 0.0, 2.0, 2.0, 0.0, 3.0, 3.0, 0.0, 4.0, 4.0, 0.0],
            4,
            3,
            2,
            &[0],
            1,
            PboStatistic::Mean,
        )
        .expect("valid tied PBO input");
        assert_eq!(result.selected_strategy, vec![0]);
        assert_eq!(result.selection_tie, vec![1]);
        assert_eq!(result.out_of_sample_rank, vec![2.5]);
        assert_eq!(result.underperformed_median, vec![0]);
    }

    #[test]
    fn pbo_partition_splits_reject_invalid_combinations() {
        assert_eq!(
            pbo_partition_splits(
                &[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
                4,
                2,
                4,
                &[0, 0],
                2,
                PboStatistic::Mean,
            ),
            Err(NumericError::InvalidCombination { index: 0 })
        );
    }

    #[test]
    fn pbo_partition_splits_reject_constant_sharpe() {
        assert_eq!(
            pbo_partition_splits(
                &[1.0, 0.0, 1.0, 1.0, 1.0, 2.0, 1.0, 3.0],
                4,
                2,
                2,
                &[0],
                1,
                PboStatistic::Sharpe,
            ),
            Err(NumericError::UndefinedStatistic)
        );
    }

    #[test]
    fn cpcv_fold_assembly_preserves_roles_and_path_incidence() {
        let combinations = [0, 1, 0, 2, 0, 3, 1, 2, 1, 3, 2, 3];
        let result = cpcv_fold_assembly(CpcvAssemblyInput {
            row_groups: &[0, 0, 1, 1, 2, 2, 3, 3],
            row_periods: &[0, 1, 2, 3, 4, 5, 6, 7],
            starts: &[0, 1, 2, 3, 4, 5, 6, 7],
            ends: &[1, 2, 3, 4, 5, 6, 7, 8],
            group_end_periods: &[1, 3, 5, 7],
            combination_groups: &combinations,
            groups_per_combination: 2,
            embargo: 1,
        })
        .expect("valid CPCV input");

        assert_eq!(
            &result.test_indices[result.test_offsets[0]..result.test_offsets[1]],
            &[0, 1, 2, 3]
        );
        assert_eq!(
            &result.train_indices[result.train_offsets[0]..result.train_offsets[1]],
            &[5, 6, 7]
        );
        assert_eq!(
            &result.purged_indices[result.purged_offsets[0]..result.purged_offsets[1]],
            &[]
        );
        assert_eq!(
            &result.embargoed_indices[result.embargoed_offsets[0]..result.embargoed_offsets[1]],
            &[4]
        );
        assert_eq!(
            result.path_fold_by_group,
            vec![0, 0, 1, 2, 1, 3, 3, 4, 2, 4, 5, 5]
        );
        assert_eq!(result.path_offsets, vec![0, 4, 8, 12]);
    }

    #[test]
    fn cpcv_fold_assembly_purges_half_open_overlaps() {
        let result = cpcv_fold_assembly(CpcvAssemblyInput {
            row_groups: &[0, 0, 1, 1, 2, 2, 3, 3],
            row_periods: &[0, 1, 2, 3, 4, 5, 6, 7],
            starts: &[0, 1, 2, 3, 4, 5, 6, 7],
            ends: &[2, 3, 4, 5, 6, 7, 8, 9],
            group_end_periods: &[1, 3, 5, 7],
            combination_groups: &[0, 1, 0, 2, 0, 3, 1, 2, 1, 3, 2, 3],
            groups_per_combination: 2,
            embargo: 0,
        })
        .expect("valid overlapping CPCV input");
        assert_eq!(
            &result.purged_indices[result.purged_offsets[0]..result.purged_offsets[1]],
            &[4]
        );
        assert_eq!(
            &result.train_indices[result.train_offsets[0]..result.train_offsets[1]],
            &[5, 6, 7]
        );
    }

    #[test]
    fn cpcv_fold_assembly_rejects_invalid_group_codes() {
        assert_eq!(
            cpcv_fold_assembly(CpcvAssemblyInput {
                row_groups: &[0, 2],
                row_periods: &[0, 1],
                starts: &[0, 1],
                ends: &[1, 2],
                group_end_periods: &[0, 1],
                combination_groups: &[0],
                groups_per_combination: 1,
                embargo: 0,
            }),
            Err(NumericError::InvalidCpcvGroup { index: 1 })
        );
    }

    #[test]
    fn interval_purge_uses_half_open_boundaries() {
        let result =
            interval_purge(&[0, 2, 3, 5], &[2, 3, 5, 7], &[2], &[4]).expect("valid intervals");
        assert_eq!(result, vec![false, true, true, false]);
    }

    #[test]
    fn interval_purge_rejects_reversed_intervals() {
        assert_eq!(
            interval_purge(&[2], &[1], &[0], &[1]),
            Err(NumericError::InvalidInterval { index: 0 })
        );
    }

    #[test]
    fn interval_purge_rejects_empty_intervals() {
        assert_eq!(
            interval_purge(&[1], &[1], &[2], &[3]),
            Err(NumericError::InvalidInterval { index: 0 })
        );
    }
}
