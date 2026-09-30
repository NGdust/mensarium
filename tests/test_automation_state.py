import unittest

from mensarium.contracts.automations import merge_state


class AutomationStateTests(unittest.TestCase):
    def test_state_merges_drops_nulls_and_stays_small(self):
        state = merge_state({"price": 194990, "seen": "a1"}, {"price": 189990, "seen": None, "checked": "2026-09-30"})
        self.assertEqual(state, {"price": 189990, "checked": "2026-09-30"})
        with self.assertRaises(ValueError):
            merge_state(state, {"blob": "x" * 4000})
