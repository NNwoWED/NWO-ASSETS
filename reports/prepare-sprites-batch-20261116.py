from pathlib import Path
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import scan_dat_record_spans
from nwoassets.properties import read_otb_items

audit=json.loads((ROOT/'reports/sprites-deduplication-20261116.json').read_text('utf8'))
work=ROOT/'sprites/lote-novos-20261116'
work.mkdir(exist_ok=True)
otfi=parse_otfi(ROOT/'assets/860/Tibia.otfi')
spans=scan_dat_record_spans((ROOT/'assets/860/Tibia.dat').read_bytes(),otfi,'canonical')
outfits={s.thing_id:s for s in spans if s.category=='outfits'}
items=read_otb_items(ROOT/'assets/items/items.otb')
assert items[5881]['client_id']==5881
assert max(items)==27502 and max(s.thing_id for s in spans if s.category=='items')==26617
rows=[];registration=[]
for entry in audit:
    path=ROOT/entry['path']
    if path.parent.name!='ITENS SOLICITAMOS PELO JUNIOR':continue
    assert not entry['canonical_matches']
    index=len(rows)+1
    row={'sequence':index,'source_server_id':5881,'target_server_id':27502+index,'target_client_id':26617+index,'source_path':str(path),'frame_width':32,'frame_height':32,'frames':1,'frame_duration_ms':'','animation_async':0}
    rows.append(row)
    registration.append(dict(row,operation='import-cloned-items',name=path.stem,purpose='material de loot para cadastro posterior',properties='DAT/OTB e peso herdados da referencia 5881, material empilhavel, movel e carregavel',sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
assert len(rows)==10
with (work/'items.csv').open('w',encoding='utf8',newline='')as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

files=['abelha-Sheet.png','abelha_boss-Sheet.png','basilisk_boss-Sheet.png','minerador_boss1-Sheet.png','mob_mulher_para_hunt_de_abelha-Sheet.png','mob_para_hunt_de_abelha-Sheet.png','samurai_iwa_final-Sheet.png']
outfit_rows=[]
for index,name in enumerate(files):
    outfit_id=1539+index
    assert not any(sid for app in outfits[outfit_id].appearances for sid in app.sprite_ids)
    source=ROOT/'sprites'/name
    image=Image.open(source)
    reference=631 if image.width==384 else 2127
    assert image.size==((384,1536)if reference==631 else(256,1024))
    row={'sequence':index+1,'operation':'reserved','outfit_id':outfit_id,'reference_outfit_id':reference,'source_path':str(source),'frame_duration_ms':100}
    outfit_rows.append(row)
    registration.append(dict(row,name=source.stem,purpose='outfit disponivel para uso posterior, conforme confirmacao do usuario',sheet_dimensions=image.size,layout='4 direcoes, 2 grupos de 8 frames, uma camada',properties='alvo DAT vazio, layout da referencia e 100 ms por frame',sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
with (work/'outfits.csv').open('w',encoding='utf8',newline='')as f:
    writer=csv.DictWriter(f,fieldnames=list(outfit_rows[0]));writer.writeheader();writer.writerows(outfit_rows)
(ROOT/'reports/registration-sprites-batch-20261116.json').write_text(json.dumps(registration,indent=2,ensure_ascii=False),encoding='utf8')
print('Prepared',len(rows),'items and',len(outfit_rows),'outfits')
