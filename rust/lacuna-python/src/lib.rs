//! `PyO3` bridge for Lacuna's native kernels.

#[pyo3::pymodule(gil_used = false)]
mod _native {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    /// Return the version of the compiled extension.
    #[pyfunction]
    fn version() -> &'static str {
        env!("CARGO_PKG_VERSION")
    }

    /// Compute a checked mean while releasing the Python interpreter lock.
    #[pyfunction]
    fn checked_mean(py: Python<'_>, values: Vec<f64>) -> PyResult<f64> {
        py.detach(move || lacuna_core::checked_mean(&values))
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    /// Compute average-rank Spearman IC for contiguous groups.
    #[pyfunction]
    fn grouped_rank_ic(
        py: Python<'_>,
        signal: Vec<f64>,
        labels: Vec<f64>,
        offsets: Vec<usize>,
    ) -> PyResult<Vec<Option<f64>>> {
        py.detach(move || lacuna_core::grouped_rank_ic(&signal, &labels, &offsets))
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    /// Reduce flattened bootstrap index batches to means.
    #[pyfunction]
    fn bootstrap_means(
        py: Python<'_>,
        values: Vec<f64>,
        indices: Vec<usize>,
        offsets: Vec<usize>,
    ) -> PyResult<Vec<f64>> {
        py.detach(move || lacuna_core::bootstrap_means(&values, &indices, &offsets))
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    /// Mark training intervals that overlap any half-open test interval.
    #[pyfunction]
    fn interval_purge(
        py: Python<'_>,
        train_starts: Vec<i64>,
        train_ends: Vec<i64>,
        test_starts: Vec<i64>,
        test_ends: Vec<i64>,
    ) -> PyResult<Vec<bool>> {
        py.detach(move || {
            lacuna_core::interval_purge(&train_starts, &train_ends, &test_starts, &test_ends)
        })
        .map_err(|error| PyValueError::new_err(error.to_string()))
    }
}
