import json
import unittest
from pathlib import Path

from pure_solver.errors import DataUnavailableError
from pure_solver.item_verification import VerificationDecision, build_verified_item_documents, promote_observation
from pure_solver.ruleset import load_ruleset
from pure_solver.wiki_items import observe_equipment


class ItemVerificationTests(unittest.TestCase):
    def test_committed_item_snapshot_regenerates_from_sources(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        decisions = json.loads(Path("rulesets/osrs-f2p-v1/item-verification.json").read_text(encoding="utf-8"))
        regenerated = build_verified_item_documents(
            ruleset.source_archive,
            decisions,
            set(ruleset.mechanics.source_revisions),
        )
        committed = json.loads(Path("rulesets/osrs-f2p-v1/items.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(json.dumps(regenerated)), committed)

    def test_item_without_standard_world_scope_cannot_be_promoted(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        decisions = json.loads(Path("rulesets/osrs-f2p-v1/item-verification.json").read_text(encoding="utf-8"))
        decisions["items"][0]["availability_scope"] = "lms"
        with self.assertRaisesRegex(DataUnavailableError, "standard-world scope"):
            build_verified_item_documents(ruleset.source_archive, decisions, set(ruleset.mechanics.source_revisions))

    def test_lms_observation_cannot_be_mislabelled_into_standard_scope(self) -> None:
        ruleset = load_ruleset("rulesets/osrs-f2p-v1")
        decisions = json.loads(Path("rulesets/osrs-f2p-v1/item-verification.json").read_text(encoding="utf-8"))
        rune_scimitar = next(item for item in decisions["items"] if item["item_id"] == 1333)
        record = json.loads((ruleset.source_archive / "rune-scimitar.json").read_text(encoding="utf-8"))
        record["title"] = "Rune scimitar (Last Man Standing)"
        with self.assertRaisesRegex(DataUnavailableError, "explicitly scoped"):
            promote_observation(
                observe_equipment(record),
                VerificationDecision.from_document(rune_scimitar),
                set(ruleset.mechanics.source_revisions),
            )
