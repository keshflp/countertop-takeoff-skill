"""Manufacturer boundary arithmetic, including corrections to the research table."""

from decimal import Decimal as D
import unittest

from eval import Edge, Rect, ticks
from source_predicates import (MM_PER_TICK, MSI, SILESTONE, adjacent_gap, applicable,
    minimum_ticks, opening_center, original_run_strips, outside_minimum, radius_minimum, seam_clearance)


class SourcePredicateTests(unittest.TestCase):
    def test_metric_minimums_are_ceiled_not_approximate_inch_labels(self):
        self.assertEqual(minimum_ticks(50), 32)
        self.assertEqual(minimum_ticks(100), 63)
        self.assertEqual(minimum_ticks(150), 95)
        self.assertEqual(63 * MM_PER_TICK, D("100.0125"))
        self.assertEqual(95 * MM_PER_TICK, D("150.8125"))
        self.assertLess(62 * MM_PER_TICK, 100)
        self.assertLess(94 * MM_PER_TICK, 150)

    def test_profiles_thickness_and_provenance_are_actual_facts(self):
        for t in (12, 20, 30, "20.0"):
            self.assertTrue(applicable(SILESTONE, "Explicit synthetic product/source selection.", t))
        for profile, note, t in ((None, "Known supplier", 20), ("quartz", "Trade name", 20),
                                 (SILESTONE, " ", 20), (SILESTONE, None, 20),
                                 (SILESTONE, "Confirmed", None), (SILESTONE, "Confirmed", 19),
                                 (SILESTONE, "Confirmed", 20.0625)):
            with self.subTest(profile=profile, note=note, thickness=t):
                self.assertFalse(applicable(profile, note, t))

    def test_radius_profiles_are_not_interchangeable_or_grid_rounded(self):
        self.assertTrue(applicable(MSI, "Explicit Q product basis; scope remains incomplete.", "19"))
        self.assertEqual(radius_minimum(SILESTONE, "sink"), 10)
        self.assertEqual(radius_minimum(SILESTONE, "cooktop"), 10)
        self.assertEqual(radius_minimum(SILESTONE, "other"), 5)
        self.assertEqual(radius_minimum(SILESTONE, "corner"), 10)
        self.assertEqual(radius_minimum(MSI, "sink"), D("9.525"))
        self.assertLess(D("9.525"), radius_minimum(SILESTONE, "sink"))

    def test_correct_sink_rear_and_cooktop_rear_are_distinct(self):
        run = Rect(0, 0, ticks(96), ticks(30))
        opening = Rect(ticks(12), 63, ticks(24), ticks(20))
        for kind, rear in (("sink", 100), ("cooktop", 50)):
            checks = original_run_strips(run, opening, kind, 20)
            self.assertEqual(checks["rear"].minimum, rear)
            self.assertTrue(all(c.passes for c in checks.values()))
        near_rear = Rect(opening.x, 62, opening.w, opening.h)
        self.assertFalse(original_run_strips(run, near_rear, "sink", 20)["rear"].passes)
        self.assertTrue(original_run_strips(run, near_rear, "cooktop", 20)["rear"].passes)

    def test_end_distance_depends_on_exact_thickness_class(self):
        run = Rect(0, 0, ticks(96), ticks(30))
        opening = Rect(80, 80, ticks(24), ticks(18))
        self.assertTrue(original_run_strips(run, opening, "sink", 20)["leftEnd"].passes)
        self.assertTrue(original_run_strips(run, opening, "sink", 30)["leftEnd"].passes)
        self.assertFalse(original_run_strips(run, opening, "sink", 12)["leftEnd"].passes)
        self.assertEqual(outside_minimum(12), 150)
        self.assertEqual(outside_minimum(20), 100)

    def test_adjacent_gap_is_fifty_not_one_hundred_and_not_diagonal(self):
        a = Rect(0, 0, 100, 100)
        self.assertTrue(adjacent_gap(a, Rect(132, 0, 100, 100)).passes)
        self.assertFalse(adjacent_gap(a, Rect(131, 0, 100, 100)).passes)
        self.assertIsNone(adjacent_gap(a, Rect(132, 132, 100, 100)))

    def test_off_center_join_uses_opening_center_not_installation_midpoint(self):
        opening = Rect(ticks(24), ticks(5), ticks(24), ticks(20))
        join = Edge("run", "v", ticks(36), 0, ticks(30))
        self.assertTrue(opening_center(join, opening))
        self.assertTrue(seam_clearance(join, opening, 20, selected=True))
        self.assertFalse(seam_clearance(join, opening, 20))
        self.assertFalse(seam_clearance(Edge("run", "v", ticks(35), 0, ticks(30)), opening, 20, selected=True))
        self.assertFalse(seam_clearance(join, Rect(ticks(35), ticks(5), ticks(24), ticks(20)), 20))

    def test_outside_seam_exact_boundary_and_thickness(self):
        opening = Rect(0, 80, 200, 200)
        for gap, thickness, valid in ((62, 20, False), (63, 20, True), (63, 30, True),
                                       (94, 12, False), (95, 12, True), (80, 12, False), (80, 20, True)):
            with self.subTest(gap=gap, thickness=thickness):
                self.assertEqual(seam_clearance(Edge("run", "v", 200 + gap, 0, 400), opening, thickness), valid)

    def test_remote_sliver_or_inside_join_cannot_repair_original_rail(self):
        run = Rect(0, 0, ticks(120), ticks(30))
        opening = Rect(ticks(24), ticks(5), ticks(24), ticks(23.5))
        for selected in (False, True):
            # Resulting seam geometry is deliberately irrelevant to original strip.
            self.assertFalse(original_run_strips(run, opening, "sink", 20)["front"].passes)


if __name__ == "__main__":
    unittest.main()
