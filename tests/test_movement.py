import unittest

from pure_solver.errors import VerifiedMechanicMissingError
from pure_solver.movement import MovementProfile, MovementState, Tile, resolve_movement_tick
from pure_solver.ruleset import load_ruleset


class MovementTests(unittest.TestCase):
    def test_ruleset_movement_profile_resolves_walk_run_and_diagonal(self) -> None:
        profile = MovementProfile.from_mechanics(load_ruleset("rulesets/osrs-f2p-v1").mechanics)
        self.assertEqual((profile.walk_tiles_per_tick, profile.run_tiles_per_tick), (1, 2))
        self.assertEqual(
            resolve_movement_tick(MovementState(Tile(0, 0), Tile(2, 2), True), profile, tick=0).tile,
            Tile(2, 2),
        )

    def test_verified_profile_resolves_tiles_and_bind(self) -> None:
        profile = MovementProfile(1, 2, "chebyshev", True, ("fixture",), "verified")
        state = MovementState(Tile(0, 0), Tile(3, 3), running=True)
        moved = resolve_movement_tick(state, profile, tick=0)
        self.assertEqual(moved.tile, Tile(2, 2))
        bound = resolve_movement_tick(MovementState(Tile(0, 0), Tile(3, 3), True, 5), profile, tick=4)
        self.assertEqual(bound.tile, Tile(0, 0))

    def test_unverified_profile_fails_closed(self) -> None:
        with self.assertRaises(VerifiedMechanicMissingError):
            resolve_movement_tick(
                MovementState(Tile(0, 0), Tile(1, 0)),
                MovementProfile(1, 2, "chebyshev", True, (), "unverified"),
                tick=0,
            )
