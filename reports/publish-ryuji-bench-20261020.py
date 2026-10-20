"""Publish the requested Ryuji disassembly bench through the official adapter.

One existing floor-only tile, no new IDs or appearance/property changes.
The adapter validates, creates/tests an immutable full version, audits all
non-target bytes, writes a durable journal and validates after atomic replace.
"""
from pathlib import Path
import hashlib
import json
import mmap
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nwoassets.map_edit import append_tile_items, node_events, rebase_tile, tile_record
from nwoassets.map_publish import publish_map
from nwoassets.properties import read_otb_items, flag_names

reports=ROOT/'reports'
def read(name): return json.loads((reports/name).read_text(encoding='utf-8'))
def write(name,value): (reports/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
before=read('position-before-ryuji-bench-20261020.json')
baseline=read('validation-ryuji-before-20261020.json')
review=read('ryuji-forge-review-20261020.json')
assert baseline['passed'] and not baseline['errors'] and not baseline['warnings']
assert before['passed'] and before['found'] and [i['server_id'] for i in before['items']]==[14931]
assert before['position']=={'x':1223,'y':766,'z':6} and not before['house_id']
tile_flags=int(before['tile_flags'],16)
assert tile_flags==1,'Preserve the verified protection-zone tile flag'
mapping=read_otb_items(ROOT/'assets/items/items.otb')
assert mapping[20952]['client_id']==20067
assert [sid for sid,item in mapping.items() if item['client_id']==20067]==[20952]
assert not (mapping[20952]['flags'] & ((1<<5)|(1<<6))),'Station must not be movable/pickupable'
canonical=ROOT/'assets/world/mapanovo.otbm'
with canonical.open('rb') as stream: source_hash=hashlib.file_digest(stream,'sha256').hexdigest()
assert source_hash==review['canonical_hashes']['map'],'Map changed since read-only forge review'
journal=reports/'ryuji-bench-publication-journal-20261020.json'
assert not journal.exists(),'Do not replay an existing publication journal'
position=(1223,766,6)
original=None
with canonical.open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as mapped:
    stack=[];area=None
    for opening,offset,payload,_ in node_events(mapped):
        if opening:
            kind=payload[0]
            if kind==4: area=struct.unpack_from('<HHB',payload,1)
            if kind in (5,14) and stack[-1]==4 and (area[0]+payload[1],area[1]+payload[2],area[2])==position:
                original=tile_record(mapped,offset)
                break
            stack.append(kind)
        elif stack.pop()==4: area=None
assert original and original['items']==[14931] and original['flags']==tile_flags
assert original['protectionReasons']==['flags']
normalized=rebase_tile(original['raw'],*position)
addition=append_tile_items(normalized,[20952])
operation={'card':'https://trello.com/c/3WURTDBh','kind':'map_existing_item_placement',
    'canonical_map':str(canonical),'position':[1223,766,6],
    'before_server_ids':[14931],'after_server_ids':[14931,20952],
    'tile_flags_before':tile_flags,'tile_flags_after':tile_flags,
    'existing_tile_bytes_preserved':True,'declared_item_additions':[20952],
    'item':{'name':'Disassembly station (existing Ninja forge appearance)',
            'server_id':20952,'client_id':20067,'otb_flags':flag_names(mapping[20952]['flags']),
            'exported_png':str(ROOT/'export/ryuji-forge-review-20261020/server-20952_client-20067.png'),
            'layout':'Existing64x64 appearance,8 frames; properties and timing unchanged'},
    'location_basis':'Startup Ryuji at1225,763,6 in121-npcs_on_startup.lua, invoked by customInit; canonical forge interior and clear tile verified.',
    'expected_result':'Existing action20952 opens disassembly/tier menu; room entrance and NPC counter remain reachable.',
    'client_change':False,'server_code_change':False,'database_access':False,
    'sprite_or_properties_change':False,'source_hash':source_hash}
write('ryuji-bench-operation-20261020.json',operation)

last_progress=[-100,None]
def progress(fraction,message):
    percent=int(fraction*100)
    if message!=last_progress[1] or percent>=last_progress[0]+5:
        print(f'RYUJI_PUBLISH {fraction:.0%} {message}',flush=True)
        last_progress[:]=[percent,message]
result=publish_map(ROOT,canonical,{position:addition},
                   expected_hash=source_hash,source_hash=source_hash,progress=progress,
                   journal_path=journal,journal_context=operation,item_additions={position:[20952]})
write('ryuji-bench-publication-result-20261020.json',result)
assert result['passed'] and result['committed'],result
print('RYUJI_PUBLICATION_OK',json.dumps(result,ensure_ascii=True),flush=True)
