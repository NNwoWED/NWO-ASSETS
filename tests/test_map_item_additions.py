"""Lossless explicit item additions retain the default protected-tile guard."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import gzip
import hashlib
import json
import struct
import tempfile
import unittest
import zipfile

from nwoassets.map_edit import (MapEditError, _node, append_tile_items, build_tile,
                                iter_tile_records, rebase_tile, rewrite_map)
from nwoassets.map_publish import _audit_changes, publish_map

POS=(1223,766,6)

def original_tile():
    # Unaligned area, inline ground, and protection-zone flag. Rebuilding the
    # ground as an ordinary child node would violate the append-only contract.
    return _node(bytes((5,123,66,3))+struct.pack('<I',1)+bytes((9,))+struct.pack('<H',14931))

def world(tile):
    area=_node(bytes((4,))+struct.pack('<HHB',1100,700,6),tile)
    root=_node(bytes((0,))+struct.pack('<IHHII',2,256,256,3,20),_node(bytes((2,)),area))
    return bytes(4)+root

class MapItemAdditionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source.map'
        self.staged=self.root/'staged.map'
        self.audit=self.root/'audit.jsonl.gz'
        self.old=original_tile()
        self.source.write_bytes(world(self.old))

    def draft(self,raw):
        changes={POS:None if raw is None else rebase_tile(raw,*POS)}
        rewrite_map(self.source,self.staged,changes)
        return changes

    def test_preserves_inline_ground_flags_and_bytes_in_unaligned_area(self):
        new=append_tile_items(self.old,[20952])
        self.assertEqual(new[:len(self.old)-1],self.old[:-1])
        changes=self.draft(new)
        result=_audit_changes(self.source,self.staged,changes,self.audit,item_additions={POS:(20952,)})
        tile=next(iter_tile_records(self.staged))
        self.assertEqual(tile['items'],[14931,20952])
        self.assertEqual(tile['flags'],1)
        self.assertEqual(result['verifiedOutputTiles'],1)
        self.assertEqual(result['sourceMetadataHash'],result['outputMetadataHash'])
        with gzip.open(self.audit,'rt',encoding='utf-8') as stream: row=json.loads(stream.read())
        self.assertEqual(row['before'],[14931]);self.assertEqual(row['after'],[14931,20952])

    def test_default_guard_still_rejects_protected_tile_edits(self):
        changes=self.draft(append_tile_items(self.old,[20952]))
        with self.assertRaisesRegex(ValueError,'protegido'):
            _audit_changes(self.source,self.staged,changes,self.audit)

    def test_declared_append_cannot_replace_ground_drop_pz_or_add_undeclared_items(self):
        for items,flags in [([14930,20952],1),([14931,20952],0),([14931,20952,20953],1)]:
            with self.subTest(items=items,flags=flags):
                self.staged.unlink(missing_ok=True)
                changes=self.draft(build_tile(*POS,items,flags=flags))
                with self.assertRaisesRegex(ValueError,'existing tile data'):
                    _audit_changes(self.source,self.staged,changes,self.audit,item_additions={POS:(20952,)})

    def test_declared_append_cannot_delete_a_tile(self):
        changes=self.draft(None)
        with self.assertRaisesRegex(ValueError,'existing tile data'):
            _audit_changes(self.source,self.staged,changes,self.audit,item_additions={POS:(20952,)})

    def test_declared_append_requires_existing_position(self):
        missing=(1224,766,6)
        changes={missing:build_tile(*missing,[14931,20952],flags=1)}
        rewrite_map(self.source,self.staged,changes)
        with self.assertRaisesRegex(ValueError,'existing source tiles'):
            _audit_changes(self.source,self.staged,changes,self.audit,item_additions={missing:(20952,)})

    def test_other_protected_content_and_invalid_ids_remain_rejected(self):
        house=_node(bytes((14,0,0))+struct.pack('<I',42))
        item_attributes=_node(bytes((5,0,0)),_node(bytes((6,))+struct.pack('<H',14931)+bytes((4,1,0))))
        nested=_node(bytes((5,0,0)),_node(bytes((6,))+struct.pack('<H',14931),_node(bytes((6,1,0)))))
        for raw in [house,item_attributes,nested,build_tile(0,0,6,[14931],flags=2)]:
            with self.subTest(raw=raw),self.assertRaises(MapEditError): append_tile_items(raw,[20952])
        for ids in [[],[0],[65536],[True],['20952']]:
            with self.subTest(ids=ids),self.assertRaises(MapEditError): append_tile_items(self.old,ids)

    def run_publication(self,fail_final=False,tamper_asset=False):
        canonical=self.root/'assets/world/mapanovo.otbm'
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(self.source.read_bytes())
        for name in ['860/Tibia.dat','860/Tibia.spr','860/Tibia.otfi','items/items.otb','items/items.xml']:
            path=self.root/'assets'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        expected=hashlib.sha256(canonical.read_bytes()).hexdigest()
        def version(_):
            directory=self.root/'versions/unit-version';directory.mkdir(parents=True)
            archive=directory/'world.zip'
            with zipfile.ZipFile(archive,'w') as out: out.write(canonical,canonical.name)
            sources=[{'path':str(path.relative_to(self.root)).replace('\\','/'),
                      'sha256':hashlib.sha256(path.read_bytes()).hexdigest().upper()}
                     for path in (self.root/'assets').rglob('*') if path.is_file()]
            if tamper_asset:(self.root/'assets/860/Tibia.dat').write_bytes(b'external-change')
            return {'passed':True,'version_id':'unit-version','root':str(directory),
                    'sources':sources, 'archives':{'world':{'path':str(archive)}}}
        changes={POS:rebase_tile(append_tile_items(self.old,[20952]),*POS)}
        validation=[{'passed':True,'errors':[]},{'passed':not fail_final,'errors':['fixture failure'] if fail_final else []}]
        with patch('nwoassets.map_publish.validate_root',side_effect=validation), \
             patch('nwoassets.map_publish.create_version',side_effect=version) as backup, \
             patch('nwoassets.properties.read_otb_items',return_value={14931:{'client_id':14046},20952:{'client_id':20067}}), \
             patch('nwoassets.roundtrip.scan_dat_record_spans',return_value=[SimpleNamespace(thing_id=n,category='items') for n in [14046,20067]]), \
             patch('nwoassets.otfi.parse_otfi',return_value=object()):
            if fail_final or tamper_asset:
                with self.assertRaisesRegex(ValueError,'assets mudaram' if tamper_asset else 'final falhou'):
                    publish_map(self.root,canonical,changes,expected_hash=expected,source_hash=expected,item_additions={POS:[20952]})
                self.assertEqual(canonical.read_bytes(),self.source.read_bytes())
            else:
                journal=self.root/'journal.json'
                result=publish_map(self.root,canonical,changes,expected_hash=expected,source_hash=expected,
                                   item_additions={POS:[20952]},journal_path=journal)
                self.assertTrue(result['committed'])
                self.assertEqual(result['itemAdditions'],[{'position':list(POS),'serverIds':[20952]}])
                self.assertEqual(next(iter_tile_records(canonical))['flags'],1)
                receipt=json.loads(journal.read_text(encoding='utf-8'))
                self.assertEqual(receipt['stage'],'committed')
                self.assertEqual(receipt['result']['itemAdditions'],result['itemAdditions'])
            backup.assert_called_once()
            self.assertTrue((self.root/'versions/unit-version/world.zip').exists())

    def test_real_publication_codec_audit_and_journal(self): self.run_publication()
    def test_failed_final_validation_restores_original_map(self): self.run_publication(fail_final=True)
    def test_real_asset_mutation_still_blocks_publication(self): self.run_publication(tamper_asset=True)

    def test_bad_append_contract_fails_before_versioning(self):
        with patch('nwoassets.map_publish.create_version') as backup:
            with self.assertRaisesRegex(ValueError,'non-null'):
                publish_map(self.root,self.source,{POS:None},expected_hash='',source_hash='',item_additions={POS:[20952]})
            backup.assert_not_called()

if __name__=='__main__': unittest.main()
