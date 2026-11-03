import struct
import unittest
from nwoassets.runtime_consolidate import merge_plan, remap_record
from nwoassets.roundtrip import scan_dat_record_spans
from test_roundtrip import OTFI, empty_appearance


class RuntimeConsolidateTests(unittest.TestCase):
    def test_three_way_preserves_feature_items_and_imports_main_effects(self):
        base={('items',100):b'base',('effects',1):b'old'}
        canonical={**base,('items',101):b'quest'}
        incoming={**base,('items',100):b'visual',('effects',2):b'new effect'}
        selected,conflicts=merge_plan(base,canonical,incoming)
        self.assertEqual(conflicts,[])
        self.assertEqual(selected,{('items',100),('effects',2)})
        self.assertNotIn(('items',101),selected)

    def test_overlapping_ids_and_simultaneous_edits_are_blocked(self):
        key=('items',100)
        for base,canonical,incoming in [
            ({key:b'base'},{key:b'a'},{key:b'b'}),
            ({key:b'base'},{key:b'a'},{key:b'a'}),
            ({},{key:b'a'},{key:b'a'}),
            ({key:b'base'},{key:b'base'},{}),
        ]:
            with self.subTest(base=base,canonical=canonical,incoming=incoming):
                self.assertEqual(merge_plan(base,canonical,incoming)[1],[key])

    def test_remap_keeps_animation_properties_groups_and_zero_sprites(self):
        plain=empty_appearance()
        timing=b'\x01'+struct.pack('<i',-1)+b'\x00'+struct.pack('<4I',80,90,100,110)
        animated=b'\x01\x01\x01\x01\x01\x01\x02'+timing+struct.pack('<2I',7,0)
        outfit=b'\xff\x02\x00'+animated+b'\x01'+plain
        item=b'\x10\xff'+plain
        data=struct.pack('<I4H',1,100,1,1,1)+item+outfit+b'\xff'+animated+b'\xff'+plain
        spans=scan_dat_record_spans(data,OTFI,'fixture')
        for span in spans:
            mapped=remap_record(data,span,OTFI,{7:1007})
            record=data[span.start:span.end]
            if span.category in ['outfits','effects']:
                expected=record.replace(struct.pack('<2I',7,0),struct.pack('<2I',1007,0))
                self.assertEqual(mapped,expected)
            else:self.assertEqual(mapped,record)


if __name__=='__main__':unittest.main()
