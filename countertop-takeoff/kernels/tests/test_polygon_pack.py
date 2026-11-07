import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layout_geometry import FabricationPolygon, Rect, packing_fits
from polygon_pack import Packing, Pose, pack


class PolygonPackingTests(unittest.TestCase):
    def test_interlocking_ls_are_rigid_pieces_with_external_kerf(self):
        polygon = FabricationPolygon(((0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)))
        for kerf, usable in ((0, Rect(0, 0, 8, 6)), (1, Rect(0, 0, 9, 7))):
            result = pack((polygon, polygon), usable, kerf, True)
            self.assertEqual(result.slab_count, 1)
            placed = [polygon.placed(p.x, p.y, p.turns) for p in result.poses]
            self.assertTrue(packing_fits(placed, usable, kerf))
            self.assertTrue(any(p.turns in (2, 3) for p in result.poses))
        result = pack((polygon, polygon), Rect(0, 0, 8, 6), 0, False)
        self.assertEqual(result.slab_count, 2)
        self.assertEqual({p.turns for p in result.poses}, {0})

    def test_exact_packer_can_improve_a_valid_seed(self):
        pieces = (FabricationPolygon(Rect(0, 0, 4, 6).points),) * 2
        seed = Packing((Pose(0, 0, 0, 0), Pose(1, 0, 0, 0)), 2, False)
        with patch("polygon_pack.greedy", return_value=seed):
            result = pack(pieces, Rect(0, 0, 10, 6), 1, False, budget=0.2)
        self.assertEqual(result.slab_count, 1)
        self.assertTrue(result.proven)
        self.assertTrue(packing_fits([p.placed(s.x, s.y, s.turns) for p, s in zip(pieces, result.poses)], Rect(0, 0, 10, 6), 1))


if __name__ == "__main__":
    unittest.main()
