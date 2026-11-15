import struct
import unittest
from nwoassets.map_edit import _node, node_events, tile_record, MapEditError
from nwoassets.map_relocate import relocate_tile, relocate_metadata, item_attribute_spans


def item(sid,attrs=b'',children=b''):
    return _node(b'\x06'+struct.pack('<H',sid)+attrs,children)


class MapRelocateTests(unittest.TestCase):
    def test_house_flags_nested_items_and_text_are_preserved(self):
        text=b'\x08 is text, not a teleport'
        attrs=b'\x04'+struct.pack('<H',222)+b'\x06'+struct.pack('<H',len(text))+text
        destination=b'\x08'+struct.pack('<HHB',500,600,7)
        raw=_node(b'\x0e\x02\x03'+struct.pack('<I',123)+b'\x03'+struct.pack('<I',5),
                  item(1987,attrs,item(1387,destination)))
        calls=[]
        def mapper(pos):calls.append(pos);return pos[0]+1000,pos[1]+2000,pos[2]
        result=relocate_tile(raw,(1022,1023,7),mapper)
        expected=_node(b'\x0e\xfe\xff'+struct.pack('<I',123)+b'\x03'+struct.pack('<I',5),
                      item(1987,attrs,item(1387,b'\x08'+struct.pack('<HHB',1500,2600,7))))
        self.assertEqual(result,expected);self.assertEqual(calls,[(500,600,7)])
        self.assertEqual(tile_record(result)['house'],123)

    def test_null_teleport_remains_script_sentinel(self):
        raw=_node(b'\x05\x00\x00',item(1387,b'\x08'+bytes(5)))
        result=relocate_tile(raw,(256,512,7),lambda _:self.fail('null destination mapped'))
        self.assertEqual(raw,result)

    def test_unrelated_noncanonical_escapes_stay_identical(self):
        raw=b'\xfe\x05\x01\x02\xfe\x06\x64\x00\x04\xfd\x01\x00\xff\xff'
        self.assertEqual(relocate_tile(raw,(9,10,7),lambda p:p),raw[:2]+b'\x09\x0a'+raw[4:])

    def test_attribute_map_does_not_confuse_bytes_with_positions(self):
        key=b'custom';value=b'\x08\xfd\xfe\xff'
        attrs=b'\x80'+struct.pack('<H',1)+struct.pack('<H',len(key))+key+b'\x01'+struct.pack('<I',len(value))+value
        payload=b'\x06\x64\x00'+attrs+b'\x08'+struct.pack('<HHB',1,2,3)
        self.assertEqual([s[0] for s in item_attribute_spans(payload)],[128,8])
        raw=_node(b'\x05\x00\x00',_node(payload))
        changed=relocate_tile(raw,(256,512,7),lambda p:(p[0]+1,p[1]+2,p[2]))
        headers=[p for opening,_,p,_ in node_events(changed,0) if opening]
        self.assertEqual(headers[1],payload[:-5]+struct.pack('<HHB',2,4,3))

    def test_unknown_or_truncated_attributes_stop(self):
        for attrs in (b'\x7f',b'\x08\x00',b'\x06\x08\x00abc',b'\x80\x01\x00'):
            with self.subTest(attrs=attrs),self.assertRaises(MapEditError):
                relocate_tile(_node(b'\x05\x00\x00',item(100,attrs)),(1,1,7),lambda p:p)

    def test_towns_and_waypoints_keep_ids_names(self):
        name='Konoha'.encode();pos=struct.pack('<HHB',100,200,10)
        town=_node(b'\x0c',_node(b'\x0d'+struct.pack('<I',1)+struct.pack('<H',len(name))+name+pos))
        result=relocate_metadata(town,lambda p:(p[0]+900,p[1]+1800,p[2]))
        self.assertEqual(result,town.replace(pos,struct.pack('<HHB',1000,2000,10)))
        wp=_node(b'\x0f',_node(b'\x10'+struct.pack('<H',len(name))+name+pos))
        self.assertEqual(relocate_metadata(wp,lambda p:p),wp)

    def test_invalid_destination_and_unknown_metadata_stop(self):
        raw=_node(b'\x05\x00\x00',item(100,b'\x08'+struct.pack('<HHB',1,2,3)))
        with self.assertRaises(MapEditError):relocate_tile(raw,(1,1,7),lambda p:(-1,2,3))
        with self.assertRaises(MapEditError):relocate_metadata(_node(b'\x19'),lambda p:p)

    def test_nwo_areas_split_rectangles_keep_shaders_colors_and_apng(self):
        region=_node(b'\x14'+struct.pack('<HHBHHB',0,0,7,31,15,7))
        apng=_node(b'\x17'+struct.pack('<H',5)+b'a.png'+struct.pack('<HHBhhHHB',5,6,7,-1,-2,64,64,1))
        color=_node(b'\x18\x10\x20\x30')
        raw=_node(b'\x11',region+apng+color)
        mapper=lambda p:(p[0]+100,p[1]+200,p[2])
        rects=lambda lo,hi:[((100,200,7),(115,215,7)),((216,300,7),(231,315,7))]
        changed=relocate_metadata(raw,mapper,rectangle_mapper=rects)
        headers=[p for opening,_,p,_ in node_events(changed,0) if opening]
        self.assertEqual([p[0] for p in headers],[17,20,20,23,24])
        self.assertEqual(headers[-1],b'\x18\x10\x20\x30')
        self.assertEqual(struct.unpack_from('<HHB',headers[-2],8),(105,206,7))


if __name__=='__main__':unittest.main()
