import unittest

from toy import Counter


class CounterTests(unittest.TestCase):
    def test_cumulative_acceptance(self):
        counter = Counter(5)
        self.assertTrue(counter.add(2))
        self.assertTrue(counter.add(3))
        self.assertEqual(counter.total, 5)

    def test_overflow_leaves_total_unchanged(self):
        counter = Counter(5)
        self.assertTrue(counter.add(4))
        self.assertFalse(counter.add(2))
        self.assertEqual(counter.total, 4)

    def test_rejects_negative_arguments(self):
        with self.assertRaises(ValueError):
            Counter(-1)
        with self.assertRaises(ValueError):
            Counter(5).add(-1)
