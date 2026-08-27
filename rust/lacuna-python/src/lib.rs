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
    type CpcvOutput<'py> = (
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
        Bound<'py, PyArray1<i64>>,
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

    fn copy_usize(array: &PyReadonlyArray1<'_, i64>, name: &str) -> PyResult<Vec<usize>> {
        let values = array.as_slice().map_err(|error| {
            PyValueError::new_err(format!(
                "{name} must be a one-dimensional, aligned, C-contiguous int64 array: {error}"
            ))
        })?;
        checked_usize(values, name)
    }

    fn copy_usize_matrix(array: &PyReadonlyArray2<'_, i64>, name: &str) -> PyResult<Vec<usize>> {
        let values = array.as_slice().map_err(|error| {
            PyValueError::new_err(format!(
                "{name} must be a two-dimensional, aligned, C-contiguous int64 array: {error}"
            ))
        })?;
        checked_usize(values, name)
    }

    fn checked_i64(values: Vec<usize>, name: &str) -> PyResult<Vec<i64>> {
        values
            .into_iter()
            .enumerate()
            .map(|(index, value)| {
                i64::try_from(value).map_err(|_| {
                    PyValueError::new_err(format!(
                        "{name}[{index}] exceeds the maximum representable int64 value"
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
        let offsets = copy_usize(&offsets, "offsets")?;
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
        let indices = copy_usize(&indices, "indices")?;
        let offsets = copy_usize(&offsets, "offsets")?;
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
        let groups = copy_usize_matrix(&combination_groups, "combination_groups")?;
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

    /// Assemble complete CPCV roles and path incidence into compact CSR buffers.
    #[pyfunction]
    // The private binding mirrors one coarse-grained kernel contract.
    #[allow(clippy::needless_pass_by_value, clippy::too_many_arguments)]
    fn cpcv_fold_assembly<'py>(
        py: Python<'py>,
        row_groups: PyReadonlyArray1<'py, i64>,
        row_periods: PyReadonlyArray1<'py, i64>,
        starts: PyReadonlyArray1<'py, i64>,
        ends: PyReadonlyArray1<'py, i64>,
        group_end_periods: PyReadonlyArray1<'py, i64>,
        combination_groups: PyReadonlyArray2<'py, i64>,
        embargo: usize,
    ) -> PyResult<CpcvOutput<'py>> {
        let combination_shape = combination_groups.shape();
        let groups_per_combination = combination_shape[1];
        // Snapshot every borrowed array before detaching. The Rust core never
        // observes a Python-owned buffer while another thread can mutate it.
        let row_groups = copy_usize(&row_groups, "row_groups")?;
        let row_periods = copy_usize(&row_periods, "row_periods")?;
        let starts = copy_i64(&starts, "starts")?;
        let ends = copy_i64(&ends, "ends")?;
        let group_end_periods = copy_usize(&group_end_periods, "group_end_periods")?;
        let combination_groups = copy_usize_matrix(&combination_groups, "combination_groups")?;
        let result = py
            .detach(move || {
                lacuna_core::cpcv_fold_assembly(lacuna_core::CpcvAssemblyInput {
                    row_groups: &row_groups,
                    row_periods: &row_periods,
                    starts: &starts,
                    ends: &ends,
                    group_end_periods: &group_end_periods,
                    combination_groups: &combination_groups,
                    groups_per_combination,
                    embargo,
                })
            })
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok((
            checked_i64(result.train_indices, "train_indices")?.into_pyarray(py),
            checked_i64(result.train_offsets, "train_offsets")?.into_pyarray(py),
            checked_i64(result.test_indices, "test_indices")?.into_pyarray(py),
            checked_i64(result.test_offsets, "test_offsets")?.into_pyarray(py),
            checked_i64(result.purged_indices, "purged_indices")?.into_pyarray(py),
            checked_i64(result.purged_offsets, "purged_offsets")?.into_pyarray(py),
            checked_i64(result.embargoed_indices, "embargoed_indices")?.into_pyarray(py),
            checked_i64(result.embargoed_offsets, "embargoed_offsets")?.into_pyarray(py),
            checked_i64(result.path_fold_by_group, "path_fold_by_group")?.into_pyarray(py),
            checked_i64(result.path_offsets, "path_offsets")?.into_pyarray(py),
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
