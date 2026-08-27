//! `PyO3` bridge for Lacuna's native kernels.

#[pyo3::pymodule(gil_used = false)]
mod _native {
    use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1, PyReadonlyArray2, PyUntypedArrayMethods};
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    type NullableFloatOutput<'py> = (Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<u8>>);
    type PboOutput<'py> = (
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<f64>>,
        Bound<'py, PyArray1<f64>>,
        Bound<'py, PyArray1<f64>>,
        Bound<'py, PyArray1<f64>>,
        Bound<'py, PyArray1<u8>>,
        Bound<'py, PyArray1<u8>>,
    );

    fn copy_f64(array: &PyReadonlyArray1<'_, f64>, name: &str) -> PyResult<Vec<f64>> {
        let values = array.as_slice().map_err(|error| {
            PyValueError::new_err(format!(
                "{name} must be a one-dimensional, aligned, C-contiguous float64 array: {error}"
            ))
        })?;
        Ok(values.to_vec())
    }

    fn copy_i64(array: &PyReadonlyArray1<'_, i64>, name: &str) -> PyResult<Vec<i64>> {
        let values = array.as_slice().map_err(|error| {
            PyValueError::new_err(format!(
                "{name} must be a one-dimensional, aligned, C-contiguous int64 array: {error}"
            ))
        })?;
        Ok(values.to_vec())
    }

    fn copy_f64_matrix(array: &PyReadonlyArray2<'_, f64>, name: &str) -> PyResult<Vec<f64>> {
        let values = array.as_slice().map_err(|error| {
            PyValueError::new_err(format!(
                "{name} must be a two-dimensional, aligned, C-contiguous float64 array: {error}"
            ))
        })?;
        Ok(values.to_vec())
    }

    fn copy_i64_matrix(array: &PyReadonlyArray2<'_, i64>, name: &str) -> PyResult<Vec<i64>> {
        let values = array.as_slice().map_err(|error| {
            PyValueError::new_err(format!(
                "{name} must be a two-dimensional, aligned, C-contiguous int64 array: {error}"
            ))
        })?;
        Ok(values.to_vec())
    }

    fn checked_usize(values: &[i64], name: &str) -> PyResult<Vec<usize>> {
        values
            .iter()
            .copied()
            .enumerate()
            .map(|(index, value)| {
                usize::try_from(value).map_err(|_| {
                    PyValueError::new_err(format!(
                        "{name}[{index}] must be a non-negative integer representable as usize"
                    ))
                })
            })
            .collect()
    }

    /// Return the version of the compiled extension.
    #[pyfunction]
    fn version() -> String {
        let cargo_version = env!("CARGO_PKG_VERSION");
        if let Some((release, candidate)) = cargo_version.split_once("-rc.") {
            return format!("{release}rc{candidate}");
        }
        cargo_version.to_owned()
    }

    /// Compute a checked mean while releasing the Python interpreter lock.
    #[pyfunction]
    fn checked_mean(py: Python<'_>, values: Vec<f64>) -> PyResult<f64> {
        py.detach(move || lacuna_core::checked_mean(&values))
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    /// Compute average-rank Spearman IC for contiguous groups.
    #[pyfunction]
    // PyO3 extracts Python arguments into these owned guard values.
    #[allow(clippy::needless_pass_by_value)]
    fn grouped_rank_ic<'py>(
        py: Python<'py>,
        signal: PyReadonlyArray1<'py, f64>,
        labels: PyReadonlyArray1<'py, f64>,
        offsets: PyReadonlyArray1<'py, i64>,
    ) -> PyResult<NullableFloatOutput<'py>> {
        // Take Rust-owned snapshots before releasing the interpreter lock. A
        // borrowed NumPy buffer can otherwise be mutated by a Python alias.
        let signal = copy_f64(&signal, "signal")?;
        let labels = copy_f64(&labels, "labels")?;
        let raw_offsets = copy_i64(&offsets, "offsets")?;
        let offsets = checked_usize(&raw_offsets, "offsets")?;
        let result = py
            .detach(move || lacuna_core::grouped_rank_ic_buffer(&signal, &labels, &offsets))
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok((
            result.values.into_pyarray(py),
            result.validity.into_pyarray(py),
        ))
    }

    /// Reduce flattened bootstrap index batches to means.
    #[pyfunction]
    // PyO3 extracts Python arguments into these owned guard values.
    #[allow(clippy::needless_pass_by_value)]
    fn bootstrap_means<'py>(
        py: Python<'py>,
        values: PyReadonlyArray1<'py, f64>,
        indices: PyReadonlyArray1<'py, i64>,
        offsets: PyReadonlyArray1<'py, i64>,
    ) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let values = copy_f64(&values, "values")?;
        let raw_indices = copy_i64(&indices, "indices")?;
        let raw_offsets = copy_i64(&offsets, "offsets")?;
        let indices = checked_usize(&raw_indices, "indices")?;
        let offsets = checked_usize(&raw_offsets, "offsets")?;
        let result = py
            .detach(move || lacuna_core::bootstrap_means(&values, &indices, &offsets))
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(result.into_pyarray(py))
    }

    /// Reduce built-in PBO statistics for checked partition combinations.
    #[pyfunction]
    // PyO3 extracts Python arguments into these owned guard values.
    #[allow(clippy::needless_pass_by_value)]
    fn pbo_partition_splits<'py>(
        py: Python<'py>,
        matrix: PyReadonlyArray2<'py, f64>,
        combination_groups: PyReadonlyArray2<'py, i64>,
        partitions: usize,
        statistic: &str,
    ) -> PyResult<PboOutput<'py>> {
        let matrix_shape = matrix.shape();
        let rows = matrix_shape[0];
        let columns = matrix_shape[1];
        let combination_shape = combination_groups.shape();
        let groups_per_combination = combination_shape[1];
        let values = copy_f64_matrix(&matrix, "matrix")?;
        let raw_groups = copy_i64_matrix(&combination_groups, "combination_groups")?;
        let groups = checked_usize(&raw_groups, "combination_groups")?;
        let statistic = match statistic {
            "mean" => lacuna_core::PboStatistic::Mean,
            "sharpe" => lacuna_core::PboStatistic::Sharpe,
            _ => {
                return Err(PyValueError::new_err(
                    "statistic must be 'mean' or 'sharpe'",
                ));
            }
        };
        let result = py
            .detach(move || {
                lacuna_core::pbo_partition_splits(
                    &values,
                    rows,
                    columns,
                    partitions,
                    &groups,
                    groups_per_combination,
                    statistic,
                )
            })
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        let selected_strategy = result
            .selected_strategy
            .into_iter()
            .map(i64::try_from)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| PyValueError::new_err("selected strategy index exceeds int64"))?;
        Ok((
            selected_strategy.into_pyarray(py),
            result.in_sample_performance.into_pyarray(py),
            result.out_of_sample_performance.into_pyarray(py),
            result.out_of_sample_rank.into_pyarray(py),
            result.logit.into_pyarray(py),
            result.selection_tie.into_pyarray(py),
            result.underperformed_median.into_pyarray(py),
        ))
    }

    /// Mark training intervals that overlap any half-open test interval.
    #[pyfunction]
    // PyO3 extracts Python arguments into these owned guard values.
    #[allow(clippy::needless_pass_by_value)]
    fn interval_purge<'py>(
        py: Python<'py>,
        train_starts: PyReadonlyArray1<'py, i64>,
        train_ends: PyReadonlyArray1<'py, i64>,
        test_starts: PyReadonlyArray1<'py, i64>,
        test_ends: PyReadonlyArray1<'py, i64>,
    ) -> PyResult<Bound<'py, PyArray1<u8>>> {
        let train_starts = copy_i64(&train_starts, "train_starts")?;
        let train_ends = copy_i64(&train_ends, "train_ends")?;
        let test_starts = copy_i64(&test_starts, "test_starts")?;
        let test_ends = copy_i64(&test_ends, "test_ends")?;
        let result = py
            .detach(move || {
                lacuna_core::interval_purge(&train_starts, &train_ends, &test_starts, &test_ends)
            })
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(result
            .into_iter()
            .map(u8::from)
            .collect::<Vec<_>>()
            .into_pyarray(py))
    }
}
