//! Exact-arithmetic math kernel for the `pure` F2P pure-build solver.
//!
//! Python (`src/pure_solver`) keeps data collection, verification and the CLI
//! wrapper; every stage on the ranking path is implemented here.  Stages 1-4
//! are ports verified byte-for-byte against the Python reference outputs;
//! Stage 5 (`kits`, KO-switch kit expansion) exists only in Rust.

pub mod account_frontier;
pub mod accounts;
pub mod canonical;
pub mod cli;
pub mod combat;
pub mod commands;
pub mod dominance;
pub mod experience;
pub mod formula;
pub mod gear_matrix;
pub mod io;
pub mod items;
pub mod kits;
pub mod matrix_table;
pub mod mechanics;
pub mod prayers;
pub mod ranking;
pub mod rational;
pub mod reduction;
pub mod resolved_screen;
