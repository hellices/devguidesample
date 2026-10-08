import unittest
from collections import Counter

from verify import event_identity, event_rank, expected_events


class EventIdentityTest(unittest.TestCase):
    def test_replacement_is_distinct_from_ordinary_update(self):
        expected = expected_events("run", 1)

        self.assertEqual(
            expected,
            Counter(
                {
                    event_identity("run:0000000", "insert", 1): 1,
                    event_identity("run:0000000", "update", 2): 1,
                    event_identity("run:0000000", "update", 3): 1,
                    event_identity("run:0000000", "delete", None): 1,
                }
            ),
        )

        substituted = Counter(
            {
                event_identity("run:0000000", "insert", 1): 1,
                event_identity("run:0000000", "update", 2): 2,
                event_identity("run:0000000", "delete", None): 1,
            }
        )
        self.assertTrue(expected - substituted)
        self.assertTrue(substituted - expected)

    def test_update_versions_have_distinct_order(self):
        self.assertEqual(
            [
                event_rank("insert", 1),
                event_rank("update", 2),
                event_rank("update", 3),
                event_rank("delete", None),
            ],
            [0, 1, 2, 3],
        )


if __name__ == "__main__":
    unittest.main()
