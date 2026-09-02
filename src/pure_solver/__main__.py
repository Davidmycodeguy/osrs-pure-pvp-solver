"""Entry point for ``python -m pure_solver``; delegates to :func:`pure_solver.cli.main`."""

from .cli import main

raise SystemExit(main())
