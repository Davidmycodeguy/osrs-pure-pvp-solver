"""Keep ``python -m pure_solver.cli`` working as an alias of ``python -m pure_solver``."""

from .parser import main

raise SystemExit(main())
