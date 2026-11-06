"""Hand geometry witnesses independent of the optimizer's decomposition/rotations."""

import unittest

from eval import Edge, Rect, ticks
import polygon_oracle as polygon


def poly(raw):
    return polygon.simple(raw)


L = [[0, 0], [72, 0], [72, 24], [24, 24], [24, 60], [0, 60]]


class PolygonTests(unittest.TestCase):
    def test_whole_l_is_one_connected_piece_without_internal_seams(self):
        p = poly(L)
        polygon.connected(p)
        polygon.tile(p, [p])
        self.assertEqual(sum(r.area for r in polygon.cells(p)), 2592 * 256)
        self.assertEqual(polygon.boundaries("counter", [p]), [])
        self.assertEqual(polygon.reentrant(p), [(24 * 16, 24 * 16)])

    def test_exact_tiling_rejects_holes_overlap_and_bbox_replacement(self):
        p = poly(L)
        top = poly([[0, 0], [72, 0], [72, 24], [0, 24]])
        leg = poly([[0, 24], [24, 24], [24, 60], [0, 60]])
        polygon.tile(p, [top, leg])
        for bad in ([top], [top, leg, leg], [poly([[0, 0], [72, 0], [72, 60], [0, 60]])]):
            with self.subTest(pieces=bad), self.assertRaises(ValueError):
                polygon.tile(p, bad)
        self.assertEqual(polygon.boundaries("counter", [top, leg]), [Edge("counter", "h", 384, 0, 384)])

    def test_clockwise_quarter_turns_have_distinct_hand_checked_concavities(self):
        expected = [L,
            [[60, 0], [60, 72], [36, 72], [36, 24], [0, 24], [0, 0]],
            [[72, 60], [0, 60], [0, 36], [48, 36], [48, 0], [72, 0]],
            [[0, 72], [0, 0], [24, 0], [24, 48], [60, 48], [60, 72]]]
        for q in range(4):
            with self.subTest(q=q):
                self.assertEqual(polygon.turn(poly(L), q), [tuple(ticks(v) for v in p) for p in expected[q]])
        for invalid in (-1, 4, True, 1.5):
            with self.assertRaises(ValueError):
                polygon.turn(poly(L), invalid)

    def test_turn_normalizes_before_usable_origin_translation(self):
        shifted = [[x + 10, y + 20] for x, y in L]
        for q in range(4):
            self.assertEqual(polygon.turn(poly(shifted), q), polygon.turn(poly(L), q))

    def test_concavity_can_nest_with_kerf_but_not_a_tick_short(self):
        p = poly(L)
        other = poly([[24.25, 24.25], [54.25, 24.25], [54.25, 54.25], [24.25, 54.25]])
        polygon.no_collision(p, other, ticks(.25))
        with self.assertRaises(ValueError):
            polygon.no_collision(p, [(x - 1, y) for x, y in other], ticks(.25))
        with self.assertRaises(ValueError):
            polygon.no_collision(p, poly(L), 0)

    def test_opening_holes_are_reserved_stock_not_nesting_space(self):
        gross = poly([[0, 0], [96, 0], [96, 30], [0, 30]])
        in_hole = poly([[30, 10], [40, 10], [40, 20], [30, 20]])
        polygon.connected(gross, [Rect(24 * 16, 7 * 16, 24 * 16, 16 * 16)])
        with self.assertRaises(ValueError):
            polygon.no_collision(gross, in_hole, 0)

    def test_opening_must_not_disconnect_solid_even_when_gross_is_connected(self):
        p = poly([[0, 0], [72, 0], [72, 30], [0, 30]])
        polygon.connected(p, [Rect(12 * 16, 5 * 16, 24 * 16, 20 * 16)])
        with self.assertRaises(ValueError):
            polygon.connected(p, [Rect(0, 10 * 16, 72 * 16, 10 * 16)])
        with self.assertRaises(ValueError):
            polygon.connected(p, [Rect(0, 0, 72 * 16, 30 * 16)])

    def test_one_logical_join_has_two_stone_segments_and_no_void_bridge(self):
        edge = Edge("run", "v", 36 * 16, 0, 30 * 16)
        hole = Rect(24 * 16, 5 * 16, 24 * 16, 20 * 16)
        self.assertEqual(polygon.stone_segments(edge, [hole]), [
            Edge("run", "v", 576, 0, 80), Edge("run", "v", 576, 400, 480)])
        self.assertEqual(polygon.stone_segments(Edge("run", "v", 0, 0, 480), [hole]),
                         [Edge("run", "v", 0, 0, 480)])

    def test_simple_polygon_rejects_self_touching_boundaries(self):
        with self.assertRaises(ValueError):
            poly([[0, 0], [8, 0], [8, 8], [4, 8], [4, -4], [0, -4]])


if __name__ == "__main__":
    unittest.main()
