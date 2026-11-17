from pathlib import Path
import csv
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
sync=json.loads((ROOT/'reports/sync-runtime-sprites-batch-20261116.json').read_text('utf8'))
assert sync['passed']
reg_path=ROOT/'reports/registration-sprites-batch-20261116.json'
registration=json.loads(reg_path.read_text('utf8'))
destination=(ROOT/'importados/sprites-batch-20261116').resolve()
source_root=(ROOT/'sprites').resolve()
planned=[]
for row in registration:
    source=Path(row['source_path']).resolve()
    assert source.is_relative_to(source_root)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256']
    target=(destination/source.relative_to(source_root)).resolve()
    assert target.is_relative_to(destination) and not target.exists()
    row['archived_source_path']=str(target)
    row['original_png_is_imported_source']=True
    planned.append((source,target))
for name in ['items.csv','outfits.csv']:
    source=(source_root/'lote-novos-20261116'/name).resolve()
    target=(destination/'manifestos'/name).resolve()
    assert source.is_relative_to(source_root) and target.is_relative_to(destination) and not target.exists()
    planned.append((source,target))
for source,target in planned:
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.move(str(source),str(target))
reg_path.write_text(json.dumps(registration,indent=2,ensure_ascii=False),encoding='utf8')
(destination/'registro.json').write_text(json.dumps(registration,indent=2,ensure_ascii=False),encoding='utf8')

indexed={row['source_path']:row for row in registration}
inventory=json.loads((ROOT/'reports/sprites-deduplication-20261116.json').read_text('utf8'))
rows=[]
for entry in inventory:
    original=str(ROOT/entry['path'])
    imported=indexed.get(original)
    if imported:
        item='target_server_id'in imported
        rows.append({'nome':imported['name'],'situacao':'adicionado','categoria':'item'if item else'outfit','server_id':imported.get('target_server_id',''),'client_ou_outfit_id':imported.get('target_client_id',imported.get('outfit_id')),'arquivo':imported['archived_source_path']})
    else:
        for match in entry['canonical_matches']:
            rows.append({'nome':Path(entry['path']).stem,'situacao':'ja existia','categoria':match['category'],'server_id':'|'.join(map(str,match['server_ids'])),'client_ou_outfit_id':match['id'],'arquivo':original})
assert len(rows)==60
with (ROOT/'reports/ids-sprites-batch-20261116.csv').open('w',encoding='utf-8-sig',newline='')as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print('Archived',len(planned),'sources/manifests and recorded',len(rows),'audited PNGs')
