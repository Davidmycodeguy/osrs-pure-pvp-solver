import io
import json
import unittest
from contextlib import redirect_stdout

from pure_solver.cli import main


class DuelSolveCommandTests(unittest.TestCase):
    def test_solve_emits_a_duel_report_or_an_explicit_verification_block(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "solve",
                    "rulesets/osrs-f2p-v1",
                    "--attack-min",
                    "40",
                    "--attack-max",
                    "40",
                    "--strength-min",
                    "40",
                    "--strength-max",
                    "40",
                    "--ranged-min",
                    "1",
                    "--ranged-max",
                    "1",
                    "--prayer-max",
                    "1",
                    "--hitpoints-min",
                    "40",
                    "--hitpoints-max",
                    "40",
                    "--combat-min",
                    "30",
                    "--combat-max",
                    "40",
                    "--max-candidates",
                    "1",
                    "--max-strategies",
                    "1",
                    "--samples",
                    "1",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertIn("verification", payload)
        self.assertIn(payload["verification"]["status"], {"verified", "blocked"})
        if status == 0:
            self.assertIn("pairwise_matchups", payload)
            self.assertIn("nash", payload)
            self.assertIn("resources", payload)
        else:
            self.assertEqual(status, 2)
            self.assertFalse(payload["verification"]["production_ready"])
            self.assertNotIn("top_overall", payload)

    def test_solve_defaults_to_standard_f2p_training_mode(self) -> None:
        parser_output = io.StringIO()
        with redirect_stdout(parser_output):
            status = main(
                [
                    "solve",
                    "rulesets/osrs-f2p-v1",
                    "--attack-min",
                    "40",
                    "--attack-max",
                    "40",
                    "--strength-min",
                    "60",
                    "--strength-max",
                    "60",
                    "--ranged-min",
                    "1",
                    "--ranged-max",
                    "1",
                    "--prayer-max",
                    "34",
                    "--hitpoints-min",
                    "10",
                    "--hitpoints-max",
                    "10",
                    "--combat-min",
                    "30",
                    "--combat-max",
                    "40",
                    "--max-candidates",
                    "1",
                    "--max-strategies",
                    "1",
                    "--samples",
                    "1",
                ]
            )
        # Under the default f2p_standard_training account mode the requested 60 Strength / 10 Hitpoints scope
        # yields no supported strategies, so the solve fails closed with an explicit verification block
        # instead of silently falling back to independent HP.
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(parser_output.getvalue())["verification"]["status"], "blocked")
