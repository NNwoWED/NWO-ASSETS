import unittest
from nwoassets.world_placement import PlacementMap


class PlacementTests(unittest.TestCase):
    def mapper(self):
        return PlacementMap({'blockSize':2,'ownershipRows':[[0,0,1,'a'],[0,2,2,'b'],[1,0,2,'a']],
            'placements':[{'id':'a','translation':[100,200,0]},{'id':'b','translation':[400,500,1]}]})

    def test_positions_floors_and_stable_empty_reference(self):
        p=self.mapper()
        self.assertEqual(p((1,1,12)),(101,201,12))
        self.assertEqual(p((4,0,7)),(404,500,8))
        self.assertEqual(p((7,0,7)),(407,500,8))

    def test_rectangles_preserve_exact_coverage(self):
        p=self.mapper(); rectangles=p.rectangles((1,1,3),(5,3,5))
        want={p((x,y,z)) for x in range(1,6) for y in range(1,4) for z in range(3,6)}
        got=[]
        for lo,hi in rectangles:
            got.extend((x,y,z) for x in range(lo[0],hi[0]+1) for y in range(lo[1],hi[1]+1) for z in range(lo[2],hi[2]+1))
        self.assertEqual(set(got),want)
        self.assertEqual(len(got),len(want))

    def test_contiguous_equal_transforms_merge(self):
        self.assertEqual(self.mapper().rectangles((0,0,7),(3,3,7)),[((100,200,7),(103,203,7))])


if __name__=='__main__':unittest.main()
