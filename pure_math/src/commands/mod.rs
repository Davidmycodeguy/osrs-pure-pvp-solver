//! Subcommand entry points for the `pure_math` binary.  Each module parses its
//! flags from [`crate::cli::Args`], runs the matching library stage and writes
//! that stage's output files.  `account_frontier`, `gear_matrix`, `screen` and
//! `rank` are named after the `pure_solver` CLI stages they mirror; `kits`
//! (Stage 5) and `shortlist` exist only here.

pub mod account_frontier;
pub mod gear_matrix;
pub mod kits;
pub mod rank;
pub mod screen;
pub mod shortlist;
