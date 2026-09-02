import json
import unittest
from pathlib import Path

from pure_solver.wiki_consumables import observe_consumable
from pure_solver.wiki_items import observe_equipment


class WikiItemObservationTests(unittest.TestCase):
    def test_rune_scimitar_is_parsed_but_not_promoted(self) -> None:
        record = json.loads(Path("research/authoritative/rune-scimitar.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.item_id, 1333)
        self.assertEqual(observed.requirements, {"attack": 40})
        self.assertEqual(observed.bonuses["attack_slash"], 45)
        self.assertEqual(observed.bonuses["melee_strength"], 44)
        self.assertEqual(observed.attack_speed, 4)
        self.assertTrue(observed.free_to_play)
        self.assertEqual(observed.status, "observed")
        self.assertIn("special_mechanics", observed.verification_gaps)

    def test_maple_shortbow_requirement_uses_alternate_wiki_wording(self) -> None:
        record = json.loads(Path("research/authoritative/maple-shortbow.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.requirements, {"ranged": 30})
        self.assertEqual(observed.attack_speed, 4)
        self.assertEqual(observed.attack_range, 7)

    def test_scp_template_requirement_wording_is_parsed(self) -> None:
        record = json.loads(Path("research/authoritative/adamant-scimitar.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.requirements, {"attack": 30})

    def test_numeric_skill_requirement_wording_is_parsed(self) -> None:
        record = json.loads(Path("research/authoritative/adamant-battleaxe.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.requirements, {"attack": 30})

    def test_can_be_equipped_wording_is_parsed(self) -> None:
        record = json.loads(Path("research/authoritative/bronze-mace.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.requirements, {"attack": 1})

    def test_requires_level_in_skill_wording_is_parsed(self) -> None:
        record = json.loads(Path("research/authoritative/mithril-warhammer.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.requirements, {"strength": 20})

    def test_multiversion_arrow_selects_default_unpoisoned_variant(self) -> None:
        record = json.loads(Path("research/authoritative/adamant-arrow.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.item_id, 890)
        self.assertEqual(observed.name, "Adamant arrow")
        self.assertTrue(observed.free_to_play)
        self.assertEqual(observed.bonuses["ranged_strength"], 31)

    def test_lms_or_deadman_observation_is_explicitly_out_of_scope(self) -> None:
        record = json.loads(Path("research/authoritative/rune-scimitar.json").read_text(encoding="utf-8"))
        record["title"] = "Rune scimitar (Last Man Standing)"
        observed = observe_equipment(record)
        self.assertEqual(observed.environment_scope, "lms_or_deadman")

    def test_food_observations_preserve_whole_and_bite_states(self) -> None:
        swordfish = observe_consumable(
            json.loads(Path("research/authoritative/swordfish.json").read_text(encoding="utf-8"))
        )
        pizza = observe_consumable(
            json.loads(Path("research/authoritative/anchovy-pizza.json").read_text(encoding="utf-8"))
        )
        self.assertEqual(swordfish.healing_by_state, {"whole": 14})
        self.assertEqual(pizza.healing_by_state, {"full": 9, "half": 9})
        self.assertIn("eat_delay_ticks", pizza.verification_gaps)

    def test_observes_fixed_healing_wording_variants(self) -> None:
        pumpkin = observe_consumable(
            json.loads(Path("research/authoritative/pumpkin.json").read_text(encoding="utf-8"))
        )
        egg = observe_consumable(json.loads(Path("research/authoritative/easter-egg.json").read_text(encoding="utf-8")))
        self.assertEqual(pumpkin.healing_by_state, {"whole": 14})
        self.assertEqual(egg.healing_by_state, {"whole": 14})

    def test_worn_at_level_requirement_is_parsed(self) -> None:
        record = json.loads(Path("research/authoritative/green-dhide-chaps.json").read_text(encoding="utf-8"))
        self.assertEqual(observe_equipment(record).requirements, {"ranged": 40})

    def test_defence_requirement_wordings_from_armour_pages(self) -> None:
        expectations = {
            "rune-platebody.json": {"defence": 40},  # "It requires 40 Defence and completion of the quest ..."
            "steel-full-helm.json": {"defence": 5},  # "Wearing this helmet requires at least 5 Defence"
            "studded-body.json": {"ranged": 20, "defence": 20},  # "requires 20 Ranged and Defence to equip"
            "green-dhide-body.json": {"ranged": 40, "defence": 40},  # "have level 40 Ranged and Defence"
            "hardleather-body.json": {"ranged": 1, "defence": 10},  # "players with 1 Ranged and 10 Defence"
            "adamant-plateskirt.json": {"defence": 30},  # "At least 30 Defence is required to wear it"
            "rune-kiteshield.json": {"defence": 40},  # "requires 40 Defence to wield"
            "leather-cowl.json": {},  # no requirement sentence at all
            "monks-robe-top.json": {},  # "Prayer level of 31 to enter" is the monastery, not the robe
            "mithril-warhammer.json": {
                "strength": 20
            },  # "Unlike other mithril weapons, it requires level 20 in Strength"
            "green-dhide-vambraces.json": {"ranged": 40},  # "-64 Magic attack bonus" is a stat, not a requirement
        }
        for source_file, expected in expectations.items():
            record = json.loads(Path("research/authoritative", source_file).read_text(encoding="utf-8"))
            self.assertEqual(dict(observe_equipment(record).requirements), expected, source_file)

    def test_staff_attack_range_uses_the_wiki_staff_convention(self) -> None:
        record = json.loads(Path("research/authoritative/staff-of-air.json").read_text(encoding="utf-8"))
        observed = observe_equipment(record)
        self.assertEqual(observed.attack_range, 1)
        self.assertEqual(observed.attack_speed, 5)
        self.assertEqual(observed.slot, "weapon")

    def test_full_f2p_equipment_observation_snapshot_is_explicit(self) -> None:
        snapshot = json.loads(Path("research/observations/f2p-equipment.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["observation_count"], 1091)
        self.assertEqual(snapshot["failure_count"], 25)
        self.assertEqual(len(snapshot["observation_snapshot_id"]), 64)
        self.assertTrue(all(item["observation"]["status"] == "observed" for item in snapshot["observations"]))
