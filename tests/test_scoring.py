import unittest

from app import outcome, score_points


class ScoringTests(unittest.TestCase):
    def test_exact_score_awards_ten_points(self):
        self.assertEqual(score_points((2, 1), (2, 1)), 10)

    def test_correct_winner_and_goal_difference_award_points(self):
        self.assertEqual(score_points((3, 1), (2, 0)), 4)

    def test_draw_outcome_is_supported(self):
        self.assertEqual(outcome(1, 1), 0)
        self.assertEqual(score_points((0, 0), (2, 2)), 4)

    def test_wrong_outcome_can_still_match_both_goal_counts(self):
        self.assertEqual(score_points((2, 1), (1, 2)), 0)


if __name__ == "__main__":
    unittest.main()
