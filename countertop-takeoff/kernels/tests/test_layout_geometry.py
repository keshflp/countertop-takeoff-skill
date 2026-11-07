# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Hand-checkable geometry cases, independent of the optimizer and its cells."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layout_geometry import (
    FabricationPolygon,
    InvalidPolygon,
    Rect,
    connected,
    packing_fits,
    reentrant_vertices,
    solid_cells,
    split_polygon,
    stone_segments,
    tiles,
)

L = ((0, 0), (6, 0), (6, 2), (2, 2), (2, 5), (0, 5))


class GeometryTests(unittest.TestCase):
    def test_corner_splits_tile_without_becoming_collision_cells(self):
        whole = FabricationPolygon(L)
        self.assertEqual(reentrant_vertices(whole), ((2, 2),))
        for axis in (0, 1):
            pieces = split_polygon(whole, axis, 2)
            self.assertEqual(len(pieces), 2)
            self.assertTrue(tiles(whole, pieces))
        u = FabricationPolygon(((0, 0), (8, 0), (8, 6), (6, 6), (6, 2), (2, 2), (2, 6), (0, 6)))
        pieces = split_polygon(u, 1, 4)
        self.assertEqual(len(pieces), 3)
        self.assertTrue(tiles(u, pieces))

    def test_opening_voids_clip_join_segments_and_check_solid_connectivity(self):
        whole = FabricationPolygon(((0, 0), (100, 0), (100, 40), (0, 40)))
        cut = Rect(20, 10, 30, 20)
        self.assertTrue(connected(solid_cells(whole, [cut])))
        self.assertEqual(stone_segments(whole, Rect(35, 0, 0, 40), [cut]),
                         (Rect(35, 0, 0, 10), Rect(35, 30, 0, 10)))
        for piece in split_polygon(whole, 0, 35):
            self.assertTrue(connected(solid_cells(piece, [cut])))
        self.assertFalse(connected(solid_cells(whole, [Rect(20, 0, 30, 40)])))
        self.assertFalse(connected([Rect(0, 0, 2, 2), Rect(2, 2, 2, 2)]))

    def test_whole_l_is_one_piece_despite_touching_collision_cells(self):
        whole = FabricationPolygon(L)
        self.assertEqual(whole.area, 18)
        self.assertEqual(whole.collision_cells, (Rect(0, 0, 6, 2), Rect(0, 2, 2, 3)))
        self.assertTrue(tiles(whole, [whole]))
        # No clearance is required at the computational boundary inside one L.
        self.assertTrue(packing_fits([whole], Rect(0, 0, 6, 5), kerf=4))
        separate_pieces = [FabricationPolygon(cell.points) for cell in whole.collision_cells]
        self.assertTrue(tiles(whole, separate_pieces))
        self.assertFalse(packing_fits(separate_pieces, Rect(0, 0, 6, 5), kerf=1))

    def test_all_quarter_turns_preserve_handedness_and_normalize_origin(self):
        whole = FabricationPolygon(tuple((x + 10, y + 20) for x, y in L))
        expected = [L,
                    ((5, 0), (5, 6), (3, 6), (3, 2), (0, 2), (0, 0)),
                    ((6, 5), (0, 5), (0, 3), (4, 3), (4, 0), (6, 0)),
                    ((0, 6), (0, 0), (2, 0), (2, 4), (5, 4), (5, 6))]
        for turns, outline in enumerate(expected):
            with self.subTest(turns=turns):
                placed = whole.placed(7, 11, turns)
                self.assertEqual(placed.outline, tuple((x + 7, y + 11) for x, y in outline))
                width, height = (5, 6) if turns % 2 else (6, 5)
                self.assertEqual(placed.bounds, Rect(7, 11, width, height))
                self.assertEqual(placed.area, 18)
                self.assertEqual(sum(c.area for c in placed.collision_cells), 18)
        restored = whole
        for _ in range(4):
            restored = restored.placed(0, 0, 1)
        self.assertEqual(restored.outline, L)
        self.assertEqual(whole.outline[0], (10, 20))

    def test_concavity_can_hold_another_piece_without_bbox_separation(self):
        whole = FabricationPolygon(L)
        inset = FabricationPolygon(((3, 3), (5, 3), (5, 4), (3, 4)))
        usable = Rect(0, 0, 6, 5)
        self.assertTrue(packing_fits([whole, inset], usable, kerf=1))
        self.assertFalse(packing_fits([whole, inset], usable, kerf=2))
        touching = FabricationPolygon(((2, 2), (4, 2), (4, 4), (2, 4)))
        self.assertTrue(packing_fits([whole, touching], usable, kerf=0))
        self.assertFalse(packing_fits([whole, touching], usable, kerf=1))
        overlapping = touching.placed(1, 1)
        self.assertFalse(packing_fits([whole, overlapping], usable, kerf=0))
        self.assertFalse(packing_fits([whole, whole], usable, kerf=0))

    def test_rigid_placement_must_fit_the_usable_slab(self):
        whole = FabricationPolygon(L)
        usable = Rect(3, 7, 5, 6)
        self.assertTrue(packing_fits([whole.placed(3, 7, 1)], usable, kerf=1))
        self.assertFalse(packing_fits([whole.placed(3, 7)], usable, kerf=1))
        self.assertFalse(packing_fits([whole.placed(2, 7, 1)], usable, kerf=1))
        self.assertFalse(packing_fits([whole.placed(3, 8, 1)], usable, kerf=1))

    def test_tiling_rejects_equal_area_overlap_holes_and_protrusions(self):
        whole = FabricationPolygon(((0, 0), (6, 0), (6, 4), (0, 4)))
        good = [FabricationPolygon(((0, 0), (2, 0), (2, 4), (0, 4))),
                FabricationPolygon(((2, 0), (6, 0), (6, 4), (2, 4)))]
        self.assertTrue(tiles(whole, good))
        overlap_and_hole = [good[0].placed(2, 0), good[1]]
        self.assertEqual(sum(p.area for p in overlap_and_hole), whole.area)
        self.assertFalse(tiles(whole, overlap_and_hole))
        protrusion = [good[0].placed(-2, 0), good[1]]
        self.assertEqual(sum(p.area for p in protrusion), whole.area)
        self.assertFalse(tiles(whole, protrusion))
        self.assertFalse(tiles(whole, good[:1]))
        self.assertFalse(tiles(whole, []))

    def test_u_and_outline_winding_preserve_the_whole_shape(self):
        outline = ((0, 0), (8, 0), (8, 6), (6, 6), (6, 2), (2, 2), (2, 6), (0, 6))
        whole = FabricationPolygon(outline)
        self.assertEqual(whole.area, 32)
        self.assertEqual(sum(c.area for c in whole.collision_cells), 32)
        reversed_ring = FabricationPolygon(tuple(reversed(outline)))
        self.assertEqual(reversed_ring.collision_cells, whole.collision_cells)
        self.assertTrue(tiles(whole, [reversed_ring]))
        self.assertEqual(FabricationPolygon(outline + outline[:1]), whole)

    def test_collinear_vertices_do_not_change_collision_or_kerf(self):
        whole = FabricationPolygon(L)
        extra_vertex = FabricationPolygon(L[:-1] + ((0, 5), (0, 3)))
        self.assertNotEqual(extra_vertex.collision_cells, whole.collision_cells)
        self.assertTrue(tiles(whole, [extra_vertex]))
        inset = FabricationPolygon(((3, 3), (5, 3), (5, 4), (3, 4)))
        for kerf in (0, 1, 2):
            self.assertEqual(packing_fits([whole, inset], Rect(0, 0, 6, 5), kerf),
                             packing_fits([extra_vertex, inset], Rect(0, 0, 6, 5), kerf))

    def test_integer_geometry_stays_exact_beyond_float_precision(self):
        origin = 2 ** 60
        whole = FabricationPolygon(L).placed(origin, origin)
        self.assertEqual(whole.area, 18)
        self.assertEqual(sum(c.area for c in whole.collision_cells), 18)
        self.assertTrue(tiles(whole, [whole]))
        self.assertEqual(whole.placed(0, 0).outline, L)

    def test_malformed_self_intersecting_and_disconnected_rings_are_rejected(self):
        cases = [(), ((0, 0), (2, 0), (0, 2)),  # Too few vertices.
                 ((0, 0), (3, 1), (3, 3), (0, 3)),  # Diagonal edge.
                 ((0, 0), (3, 0), (3, 0), (3, 3), (0, 3)),  # Zero edge.
                 ((0, 0), (4, 0), (2, 0), (2, 3), (0, 3)),  # Backtracking.
                 ((0, 0), (6, 0), (6, 6), (2, 6), (2, -2), (4, -2), (4, 4), (0, 4)),
                 # Two islands joined only by a retraced, zero-width bridge.
                 ((0, 0), (2, 0), (2, 2), (0, 2), (0, 0), (4, 0),
                  (6, 0), (6, 2), (4, 2), (4, 0), (0, 0)),
                 # Two regions touching at just one point.
                 ((0, 0), (2, 0), (2, 2), (4, 2), (4, 4), (2, 4), (2, 2), (0, 2)),
                 (L, L), ((False, 0), (6, 0), (6, 2), (0, 2)),
                 ((0.5, 0), (6, 0), (6, 2), (0, 2)), ((0,), (6, 0), (6, 2), (0, 2))]
        for outline in cases:
            with self.subTest(outline=outline), self.assertRaises(InvalidPolygon):
                FabricationPolygon(outline)

    def test_placement_and_kerf_require_exact_supported_values(self):
        whole = FabricationPolygon(L)
        for turns in (-1, 4, 0.5, True):
            with self.subTest(turns=turns), self.assertRaises(ValueError):
                whole.placed(0, 0, turns)
        with self.assertRaises(ValueError):
            whole.placed(0.5, 0)
        for kerf in (-1, 0.5, True):
            with self.subTest(kerf=kerf), self.assertRaises(ValueError):
                packing_fits([whole], Rect(0, 0, 6, 5), kerf)


if __name__ == "__main__":
    unittest.main()
