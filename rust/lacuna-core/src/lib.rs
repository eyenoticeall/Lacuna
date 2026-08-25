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
                write!(formatter, "interval {index} ends before it starts")
            }
        }
    }
}

impl Error for NumericError {}

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

fn average_ranks(values: &[f64]) -> Vec<f64> {
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|left, right| values[*left].total_cmp(&values[*right]));

    let mut ranks = vec![0.0; values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && values[order[end]].total_cmp(&values[order[start]]).is_eq() {
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
            let mut sampled = Vec::with_capacity(window[1] - window[0]);
            for index in &indices[window[0]..window[1]] {
                let value = values
                    .get(*index)
                    .ok_or(NumericError::IndexOutOfBounds { index: *index })?;
                sampled.push(*value);
            }
            checked_mean(&sampled)
        })
        .collect()
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
        if end < start {
            return Err(NumericError::InvalidInterval { index });
        }
    }
    for (index, (start, end)) in test_starts.iter().zip(test_ends).enumerate() {
        if end < start {
            return Err(NumericError::InvalidInterval { index });
        }
    }

    Ok(train_starts
        .iter()
        .zip(train_ends)
        .map(|(train_start, train_end)| {
            test_starts
                .iter()
                .zip(test_ends)
                .any(|(test_start, test_end)| train_start < test_end && train_end > test_start)
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::{NumericError, bootstrap_means, checked_mean, grouped_rank_ic, interval_purge};

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
    fn grouped_rank_ic_rejects_invalid_offsets() {
        assert_eq!(
            grouped_rank_ic(&[1.0], &[2.0], &[1, 1]),
            Err(NumericError::InvalidOffsets)
        );
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
}
