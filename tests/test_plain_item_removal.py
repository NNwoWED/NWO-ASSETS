import struct
import unittest
from pathlib import Path
import tempfile
from nwoassets.map_edit import build_tile, tile_record, remove_plain_tile_items, MapEditError, _node
from nwoassets.map_publish import _audit_changes


class PlainRemovalTest(unittest.TestCase):
    def test_only_declared_door_removed_with_flags_and_ground_unchanged(self):
        raw=build_tile(2726,866,8,[9146,1209,15272],flags=0x10)
        result=remove_plain_tile_items(raw,[1209])
        self.assertEqual(result,build_tile(2726,866,8,[9146,15272],flags=0x10))
        self.assertEqual(tile_record(result)['flags'],0x10)

    def test_missing_item_or_too_many_occurrences_are_rejected(self):
        raw=build_tile(2726,866,8,[9146,1209])
        for ids in ([1210],[1209,1209],[]):
            with self.subTest(ids=ids),self.assertRaises(MapEditError):
                remove_plain_tile_items(raw,ids)

    def test_attributed_door_and_nested_content_are_not_removed(self):
        door=_node(b'\x06'+struct.pack('<H',1209)+b'\x04\x01\x00')
        raw=_node(b'\x05\x01\x01',door)
        with self.assertRaises(MapEditError):remove_plain_tile_items(raw,[1209])
        nested=_node(b'\x06'+struct.pack('<H',1209),_node(b'\x06'+struct.pack('<H',1963)))
        with self.assertRaises(MapEditError):remove_plain_tile_items(_node(b'\x05\x01\x01',nested),[1209])

    def test_publication_audit_accepts_only_exact_declared_removal(self):
        def world(tile):
            area=_node(b'\x04'+struct.pack('<HHB',2560,768,8),tile)
            return bytes(4)+_node(b'\x00'+struct.pack('<IHHII',2,3000,3000,3,20),_node(b'\x02',area))
        before=build_tile(2726,866,8,[9146,1209],flags=0x10)
        after=remove_plain_tile_items(before,[1209])
        pos=(2726,866,8)
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);a=folder/'a';b=folder/'b';audit=folder/'audit.gz'
            a.write_bytes(world(before));b.write_bytes(world(after))
            result=_audit_changes(a,b,{pos:after},audit,item_removals={pos:[1209]})
            self.assertEqual(result['sourceMetadataHash'],result['outputMetadataHash'])
            with self.assertRaises(ValueError):_audit_changes(a,b,{pos:after},audit)
            changed_flags=build_tile(*pos,[9146],flags=0x20)
            b.write_bytes(world(changed_flags))
            with self.assertRaises(ValueError):
                _audit_changes(a,b,{pos:changed_flags},audit,item_removals={pos:[1209]})


if __name__=='__main__':unittest.main()
