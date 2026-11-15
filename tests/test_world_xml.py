from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from nwoassets.errors import FormatError
from nwoassets.world_xml import relocate_world_xml


class WorldXmlTests(unittest.TestCase):
    def setUp(self):
        # Keep task-created files within the NWO NEW workspace.
        self.temporary = tempfile.TemporaryDirectory(prefix='world-xml-', dir=Path(__file__).parent)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / 'source.xml'
        self.destination = self.directory / 'new.xml'

    def tearDown(self):
        self.temporary.cleanup()

    def run_xml(self, text, mapper=lambda p: (p[0] + 100, p[1] + 200, p[2]), **kwargs):
        self.source.write_text(text, encoding='utf-8')
        before = self.source.read_bytes()
        audit = relocate_world_xml(self.source, self.destination, mapper, **kwargs)
        self.assertEqual(before, self.source.read_bytes())
        self.assertTrue(audit['sourceUnmodified'])
        return ET.parse(self.destination).getroot(), audit

    def test_spawn_offsets_and_absolute_child_floor(self):
        root, audit = self.run_xml('<spawns><spawn centerx="10" centery="20" centerz="7" radius="5"><monster id="a" name="Lobo" x="-2" y="3" z="8" spawntime="60"/></spawn></spawns>', lambda p:(p[0]+100,p[1]+200,p[2]-1))
        spawn, entity = root[0], root[0][0]
        self.assertEqual((spawn.get('centerx'),spawn.get('centery'),spawn.get('centerz')),('110','220','6'))
        self.assertEqual((entity.get('x'),entity.get('y'),entity.get('z')),('-2','3','7'))
        self.assertEqual(entity.get('spawntime'),'60')
        self.assertEqual(audit['counts']['after']['entities'],1)

    def test_split_translation_runs_preserve_entity_order_and_storage(self):
        text = '<spawns><spawn id="g" centerx="10" centery="20" centerz="7" radius="2"><npc id="a" x="0" y="0" z="7" storageId="91005" storageValue="1"/><!--between--><monster id="b" x="1" y="0" z="7"/><npc id="c" x="0" y="1" z="7"/></spawn></spawns>'
        def mapper(p):return (p[0]+(500 if p[0]==11 else 100),p[1]+200,p[2])
        root,audit = self.run_xml(text,mapper)
        self.assertEqual(len(root),3)
        self.assertEqual([n.get('id') for s in root for n in s],['a','b','c'])
        self.assertEqual([s.get('radius') for s in root],['2']*3)
        self.assertEqual([s.get('centerx') for s in root],['110','510','110'])
        self.assertEqual(root[0][0].get('storageId'),'91005')
        self.assertEqual(audit['spawnGroupsAdded'],2)
        self.assertEqual(audit['counts']['after']['comments'],1)

    def test_empty_spawn_and_missing_child_coordinates(self):
        root,_ = self.run_xml('<spawns><spawn centerx="0" centery="0" centerz="0" radius="0"/><spawn centerx="12" centery="13" centerz="7" radius="1"><monster name="A"/></spawn></spawns>')
        self.assertEqual(root[0].get('centerx'),'100')
        self.assertEqual(root[1][0].attrib,{'name':'A'})

    def test_house_unset_sentinel_does_not_swallow_legitimate_zero_axis(self):
        calls=[]
        def mapper(p):calls.append(p);return(p[0]+100,p[1]+100,p[2])
        root,audit=self.run_xml('<houses><house houseid="7" townid="3" name="Não renomear" entryx="0" entryy="0" entryz="0"/><house houseid="8" townid="3" entryx="0" entryy="5" entryz="0"/></houses>',mapper)
        self.assertEqual(calls,[(0,5,0)])
        self.assertEqual(root[0].get('entryx'),'0')
        self.assertEqual(root[1].get('entryx'),'100')
        self.assertEqual(root[0].get('houseid'),'7')
        self.assertEqual(root[0].get('townid'),'3')
        self.assertEqual(audit['preservedUnsetHouseEntries'],1)

    def test_routes_map_zero_and_keep_indexes_and_text(self):
        root,_=self.run_xml('<routes><route id="4" name="Árvore" color="#00ff00" visible="false">Nota<waypoint index="9" x="0" y="0" z="0"/>Fim<waypoint index="2" x="10" y="20" z="8"/></route></routes>')
        self.assertEqual([p.get('index') for p in root[0]],['9','2'])
        self.assertEqual(root[0][0].get('x'),'100')
        self.assertEqual(root[0].text,'Nota')
        self.assertEqual(root[0][0].tail,'Fim')

    def test_regions_split_inside_even_when_corners_share_translation(self):
        text='<areapalette version="2"><area id="1"><sub id="9"><region fromX="0" fromY="2" fromZ="7" toX="4" toY="3" toZ="7" custom="keep"/></sub></area></areapalette>'
        def mapper(p):return(p[0]+(100 if p[0]==2 else 10),p[1],p[2])
        root,audit=self.run_xml(text,mapper)
        regions=root.findall('.//region')
        self.assertEqual(len(regions),3)
        covered=set()
        for region in regions:
            self.assertEqual(region.get('custom'),'keep')
            for y in range(int(region.get('fromY')),int(region.get('toY'))+1):
                for x in range(int(region.get('fromX')),int(region.get('toX'))+1):covered.add((x,y,7))
        self.assertEqual(covered,{mapper((x,y,7)) for x in range(5) for y in [2,3]})
        self.assertEqual(audit['counts']['after']['regionCellsInclusive'],10)

    def test_explicit_rectangle_mapper_and_apng_offsets_sound_metadata(self):
        text='<areapalette><area id="1"><sub id="8" shader="forest"><region fromX="1" fromY="1" fromZ="7" toX="2" toY="1" toZ="7" label="R"/><sound file="forest.ogg" channel="2" volume="35"/><apng file="Árvore.png" x="0" y="0" z="0" offsetX="-12" offsetY="40" width="128" height="256" onTop="0"/><soundsrc id="5" x="8" y="9" z="7" file="water.ogg" radius="12"/></sub></area></areapalette>'
        rect=lambda lo,hi:[((10,20,7),(10,20,7)),((30,40,7),(30,40,7))]
        root,audit=self.run_xml(text,rectangle_mapper=rect)
        apng=root.find('.//apng');sound=root.find('.//sound');src=root.find('.//soundsrc')
        self.assertEqual((apng.get('x'),apng.get('offsetX'),apng.get('offsetY')),('100','-12','40'))
        self.assertEqual(sound.attrib,{'file':'forest.ogg','channel':'2','volume':'35'})
        self.assertEqual(src.get('x'),'108')
        self.assertEqual(audit['regionsAdded'],1)

    def test_preserves_comments_and_processing_instructions_outside_root(self):
        text='<?xml version="1.0"?><!--before--><?audit keep?><houses><!--inside--><house houseid="1" entryx="1" entryy="2" entryz="7"/></houses><!--after-->'
        _,audit=self.run_xml(text)
        result=self.destination.read_text(encoding='utf-8')
        for token in ['<!--before-->','<?audit keep?>','<!--inside-->','<!--after-->']:self.assertEqual(result.count(token),1)
        self.assertLess(result.index('<!--before-->'),result.index('<houses>'))
        self.assertGreater(result.index('<!--after-->'),result.index('</houses>'))
        self.assertEqual(audit['counts']['after']['comments'],3)

    def test_unknown_nonspatial_metadata_is_preserved(self):
        root,_=self.run_xml('<routes><metadata author="alguém">Texto &amp; texto</metadata><route id="1"><waypoint x="1" y="2" z="3"/></route></routes>')
        self.assertEqual(root.find('metadata').text,'Texto & texto')

    def test_unknown_coordinate_schemas_fail_without_output(self):
        texts=[
            '<routes><portal x="1" y="2" z="3"/></routes>',
            '<routes><route><waypoint x="1" y="2"/></route></routes>',
            '<routes><route><waypoint x="1" y="2" z="3" targetX="5"/></route></routes>',
            '<houses><location>1,2,3</location></houses>',
            '<spawns><spawn centerpos="1,2,3" radius="1"/></spawns>',
            '<unknown/>',
        ]
        for text in texts:
            with self.subTest(text=text):
                self.source.write_text(text,encoding='utf-8')
                with self.assertRaises(FormatError):relocate_world_xml(self.source,self.destination,lambda p:p)
                self.assertFalse(self.destination.exists())

    def test_invalid_mapper_bounds_types_and_failures_leave_no_output(self):
        self.source.write_text('<routes><route><waypoint x="1" y="2" z="3"/></route></routes>',encoding='utf-8')
        for value in [(-1,2,3),(65536,2,3),(1,2,16),(1.0,2,3),(True,2,3),None,(1,2)]:
            with self.subTest(value=value):
                with self.assertRaises(FormatError):relocate_world_xml(self.source,self.destination,lambda p:value)
                self.assertFalse(self.destination.exists())
        def failure(p):raise RuntimeError('no owner')
        with self.assertRaisesRegex(RuntimeError,'no owner'):relocate_world_xml(self.source,self.destination,failure)
        self.assertFalse(self.destination.exists())

    def test_rectangle_mapper_cannot_drop_duplicate_or_invert_cells(self):
        text='<areapalette><area><sub><region fromX="1" fromY="1" fromZ="7" toX="2" toY="1" toZ="7"/></sub></area></areapalette>'
        self.source.write_text(text,encoding='utf-8')
        bad=[[],[((1,1,7),(1,1,7))],[((1,1,7),(1,1,7)),((1,1,7),(1,1,7))],[((2,1,7),(1,1,7))]]
        for rects in bad:
            with self.subTest(rects=rects):
                with self.assertRaises(FormatError):relocate_world_xml(self.source,self.destination,lambda p:p,rectangle_mapper=lambda lo,hi:rects)
                self.assertFalse(self.destination.exists())

    def test_destination_must_be_new_and_source_cannot_be_overwritten(self):
        self.source.write_text('<houses/>',encoding='utf-8')
        self.destination.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):relocate_world_xml(self.source,self.destination,lambda p:p)
        self.assertEqual(self.destination.read_bytes(),b'keep me')
        with self.assertRaises(FileExistsError):relocate_world_xml(self.source,self.source,lambda p:p)
        self.assertEqual(self.source.read_text(encoding='utf-8'),'<houses/>')

    def test_doctype_is_explicitly_rejected(self):
        self.source.write_text('<!DOCTYPE houses [<!ENTITY value "text">]><houses/>',encoding='utf-8')
        with self.assertRaisesRegex(FormatError,'DOCTYPE'):relocate_world_xml(self.source,self.destination,lambda p:p)
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
