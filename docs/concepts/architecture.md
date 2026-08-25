# Architecture

Lacuna is a hybrid library with three execution paths behind one typed Python API:

1. Polars for high-level columnar and lazy dataframe operations.
2. NumPy and SciPy for mature numerical and statistical routines.
3. Rust for measured, quant-specific hot paths where coarse calls amortize the language boundary.

Arrow-compatible memory is the contract between user data and these execution paths. A dataframe brand is not part of Lacuna's domain model; semantic schemas such as signal, price, label, and trade frames validate ordinary columnar data.

The native workspace starts with two crates: `lacuna-core` contains language-independent kernels and `lacuna-python` contains only the PyO3 bridge. Crates should split further only when compile time or ownership boundaries justify it.
