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

#[cfg(test)]
mod tests {
    use super::{NumericError, checked_mean};

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
}
