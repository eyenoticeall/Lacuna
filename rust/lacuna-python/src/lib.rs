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
}
