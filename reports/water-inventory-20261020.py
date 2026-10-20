"""Read-only water triage using NWO-ASSETS parsers and the canonical baseline."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib
import json
import mmap
import re
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nwoassets.properties import read_otb_items, flag_names, dat_flag_names
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import scan_dat_record_spans, dat_item_flags
from nwoassets.map_edit import iter_tile_records

paths={name:ROOT/path for name,path in {
    'dat':'assets/860/Tibia.dat','spr':'assets/860/Tibia.spr',
    'otb':'assets/items/items.otb','xml':'assets/items/items.xml',
    'map':'assets/world/mapanovo.otbm'}.items()}
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
before={name:digest(path) for name,path in paths.items()}
items=read_otb_items(paths['otb'])
data=paths['dat'].read_bytes()
otfi=parse_otfi(ROOT/'assets/860/Tibia.otfi')
spans={s.thing_id:s for s in scan_dat_record_spans(data,otfi,str(paths['dat'])) if s.category=='items'}
flags=dat_item_flags(data,otfi,str(paths['dat']))
names={}
for item in ET.parse(paths['xml']).getroot().iter('item'):
    first=int(item.get('id') or item.get('fromid') or 0)
    last=int(item.get('toid') or first)
    for sid in range(first,last+1): names[sid]=item.get('name','')
movement=(ROOT.parent/'Server-Data-Nwo/data/lib/000-constant.lua').read_bytes().decode('latin1')
movement_ids={int(n) for n in re.search(r'WATER_IDS\s*=\s*\{([^}]+)',movement)[1].replace(',',' ').split()}
by_client=defaultdict(list)
for sid,item in items.items(): by_client[item['client_id']].append(sid)
# Follow exact sprite references as well as names: cloned water borders may
# have no XML name and no custom walkable-water flag.
excluded_surface_seeds={20869,20870,15483,20731}
water_sprite_ids=set()
for sid,item in items.items():
    if sid in excluded_surface_seeds:continue
    cid=item['client_id']
    if cid not in spans:continue
    is_ground=0 in flags.get(cid,()) or item['group']==1
    water_name=any(word in names.get(sid,'').casefold() for word in ('water','agua','água'))
    if (is_ground and water_name) or item['flags']&(1<<27) or sid in movement_ids:
        water_sprite_ids.update(i for i in spans[cid].appearances[0].sprite_ids if i)
candidates={}
for sid,item in items.items():
    cid=item['client_id']
    if cid not in spans:continue
    dat_ground=0 in flags.get(cid,())
    is_ground=dat_ground or item['group']==1
    water_name=any(word in names.get(sid,'').casefold() for word in ('water','agua','água'))
    water_flag=bool(item['flags'] & (1<<27))
    shared_sprites=set(spans[cid].appearances[0].sprite_ids)&water_sprite_ids
    shared_water=bool(is_ground and shared_sprites)
    if not ((is_ground and water_name) or water_flag or sid in movement_ids or shared_water):continue
    span=spans[cid]
    appearance=span.appearances[0]
    candidates[sid]={
      'server_id':sid,'client_id':cid,'name':names.get(sid,''),'dat_ground':dat_ground,'otb_group':item['group'],
      'movement_script':sid in movement_ids,'otb_flags':flag_names(item['flags']),
      'water_sprite_references':len(shared_sprites),'discovered_by_shared_sprites_only':shared_water and not ((is_ground and water_name) or water_flag or sid in movement_ids),
      'dat_flags':dat_flag_names(flags[cid]),'block_solid':bool(item['flags']&1),
      'client_unpassable': 'unpassable' in dat_flag_names(flags[cid]),
      'server_ids_sharing_client':sorted(by_client[cid]),
      'layout':{'width':appearance.width,'height':appearance.height,'layers':appearance.layers,
        'patterns':[appearance.pattern_x,appearance.pattern_y,appearance.pattern_z],
        'frames':appearance.frames,'sprites':len(appearance.sprite_ids)},
      'map_occurrences':0,'samples':[]}
print('WATER_CANDIDATES',len(candidates),flush=True)
tiles=0
with paths['map'].open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as mapping:
    for rec in iter_tile_records(mapping):
        tiles+=1
        for sid in rec['items']:
            if sid in candidates:
                row=candidates[sid];row['map_occurrences']+=1
                if len(row['samples'])<3:
                    row['samples'].append({'x':rec['x'],'y':rec['y'],'z':rec['z'],
                      'stack':rec['items'],'protected':rec['protected']})
        if tiles%500000==0:print('WATER_TILES',tiles,flush=True)
after={name:digest(path) for name,path in paths.items()}
assert before==after,'Canonical files changed during read-only inventory'
rows=sorted(candidates.values(),key=lambda r:(-r['map_occurrences'],r['server_id']))
report={'operation':'read_only_water_inventory','canonical_hashes':before,'canonical_unchanged':True,
        'tiles_scanned':tiles,'movement_ids':sorted(movement_ids),'candidates':rows,
        'active_candidates':sum(r['map_occurrences']>0 for r in rows),
        'notes':['Item names, ground flags, custom water flag and registered movement IDs define candidates.',
                 'No classification is inferred from sprite color alone.',
                 'Shared Client IDs must be checked before appearance replacement.',
                 'No DAT/SPR/OTB/OTBM/XML modification or runtime synchronization occurred.']}
output=ROOT/'reports/water-inventory-20261020.json'
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('WATER_INVENTORY_OK',tiles,report['active_candidates'],output,flush=True)
