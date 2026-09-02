"""Exception hierarchy for fail-closed behaviour: every error means a result would not be reproducible or valid,
never that a guess was substituted.
"""


class SolverError(RuntimeError):
    """Base class for a failure that makes a result non-reproducible or invalid."""


class DataUnavailableError(SolverError):
    """A required source record or data field was unavailable."""


class VerifiedMechanicMissingError(SolverError):
    """A simulation tried to use a mechanic that has not been verified."""


class MechanicConflictError(SolverError):
    """The data snapshot records unresolved conflicting claims for a mechanic."""


class LegalityError(SolverError):
    """A requested account, item, or loadout is not legal under the ruleset."""


class SearchBudgetExceeded(SolverError):
    """An explicitly supplied search budget was reached before exhaustive search ended."""
