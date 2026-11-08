from __future__ import annotations

import unittest

from procedural_scenarios.emitter import (
    CORE_CUSTOM_MAPS_LOCALES,
    quest_localization_core_deltas,
    quest_localization_rows,
    quest_main_desc_sid,
    quest_main_name_sid,
    quest_objective_name_sid,
)


class QuestLocalizationTests(unittest.TestCase):
    def test_quest_labels_become_lockit_rows_for_all_core_locales(self) -> None:
        map_sid = "proc_objective_chain_1_abcdef12"
        events = (
            {
                "schema": "olden.procedural.mechanical_event.v1",
                "eventId": f"{map_sid}_objective_event_00",
                "repeat": False,
                "title": "Objective 1",
                "objectiveLabel": "Complete objective 1",
                "triggers": [{"kind": "visit", "entitySid": "objective_00"}],
                "actions": [
                    {
                        "kind": "objective_progress",
                        "objectiveSid": f"{map_sid}_objective_00",
                    },
                    {"kind": "victory"},
                ],
            },
        )
        rows = quest_localization_rows(events, map_sid, title="Probe Map")
        by_sid = {row["sid"]: row["text"] for row in rows}
        self.assertEqual("Probe Map", by_sid[quest_main_name_sid(map_sid)])
        self.assertEqual(
            "Complete the scenario objectives.",
            by_sid[quest_main_desc_sid(map_sid)],
        )
        self.assertEqual(
            "Complete objective 1",
            by_sid[quest_objective_name_sid(f"{map_sid}_objective_00")],
        )
        operations = quest_localization_core_deltas(map_sid, rows)
        self.assertEqual(len(CORE_CUSTOM_MAPS_LOCALES) * 2, len(operations))
        locales_tokens = {
            row["member"].split("/")[1]
            for row in operations
            if row["path"] == ["tokens"]
        }
        locales_array = {
            row["member"].split("/")[1]
            for row in operations
            if row["path"] == ["array"]
        }
        self.assertEqual(set(CORE_CUSTOM_MAPS_LOCALES), locales_tokens)
        self.assertEqual(set(CORE_CUSTOM_MAPS_LOCALES), locales_array)
        for row in operations:
            self.assertEqual("upsert_array", row["operation"])
            self.assertTrue(row["member"].endswith("/texts/customMaps.json"))
            self.assertEqual("sid", row["key"])
            self.assertEqual(list(rows), row["rows"])


if __name__ == "__main__":
    unittest.main()
