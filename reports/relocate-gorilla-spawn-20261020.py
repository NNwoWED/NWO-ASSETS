"""Relocate one invalid Gorila spawn; preserve unrelated XML bytes and binaries."""
from pathlib import Path
import hashlib,json,os,sys,uuid
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'reports'
def sha(data):return hashlib.sha256(data).hexdigest()
def write(name,data):(REPORTS/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
fixture=json.loads((REPORTS/'gorilla-native-fixture-20261020.json').read_text(encoding='utf-8'))
baseline=json.loads((REPORTS/'validation-gorilla-spawn-before-20261020.json').read_text(encoding='utf-8'))
assert baseline['passed'] and not baseline['errors'] and not baseline['warnings']
assert sha((ROOT/'assets/world/mapanovo.otbm').read_bytes())==fixture['canonical_map_hash']
source=next(t for t in fixture['tiles'] if t['position']=={'x':1226,'y':1202,'z':6})
target=next(t for t in fixture['tiles'] if t['position']=={'x':1228,'y':1202,'z':6})
assert source['serverIds']==[] and target['serverIds']==[15037] and target['clientIds']==[14152]
assert target['tileFlags']==0
old_header=b'<spawn centerx="1226" centery="1202" centerz="6" radius="1">'
new_header=b'<spawn centerx="1228" centery="1202" centerz="6" radius="1">'
paths={'canonical':ROOT/'assets/world/mapanovo-spawn.xml',
       'runtime':ROOT.parent/'Server-Data-Nwo/data/world/mapanovo-spawn.xml'}
prepared={};details=[]
for kind,path in paths.items():
    before=path.read_bytes();assert before.count(old_header)==1 and new_header not in before
    tree=ET.fromstring(before)
    selected=[s for s in tree if s.get('centerx')=='1226' and s.get('centery')=='1202' and s.get('centerz')=='6']
    assert len(selected)==1 and len(selected[0])==1
    monster=selected[0][0]
    assert monster.tag=='monster' and monster.attrib=={'name':'Gorila','x':'0','y':'0','z':'6','spawntime':'60','direction':'2'}
    for spawn in tree:
        center=tuple(map(int,spawn.get('centerpos').split(','))) if spawn.get('centerpos') else tuple(int(spawn.get(k,'0')) for k in ['centerx','centery','centerz'])
        for child in spawn:
            actual=(center[0]+int(child.get('x','0')),center[1]+int(child.get('y','0')),int(child.get('z',str(center[2]))))
            assert actual!=(1228,1202,6),'Destination already has a registered creature'
    after=before.replace(old_header,new_header,1)
    parsed=ET.fromstring(after)
    assert len(parsed)==len(tree) and after.replace(new_header,old_header,1)==before
    prepared[kind]=(path,before,after)
    details.append({'kind':kind,'path':str(path),'before_sha256':sha(before),'after_sha256':sha(after),
                    'spawn_count':len(tree),'only_centerx_changed':True,'backup':str(REPORTS/f'gorilla-spawn-before-20261020-{kind}.xml')})
report={'operation':'relocate_single_gorilla_spawn','passed':True,'committed':False,
        'old_position':[1226,1202,6],'new_position':[1228,1202,6],
        'reason':'Forced spawn accepted an existing tile with no ground; destination is an empty walkable wooden floor.',
        'ground_server_id':15037,'ground_client_id':14152,'files':details,
        'canonical_map_hash':fixture['canonical_map_hash'],'otbm_dat_spr_otb_unchanged':True,
        'monster_attributes_respawn_radius_count_unchanged':True,'database_access':False}
write('gorilla-spawn-relocation-20261020.json',report)
if '--commit' not in sys.argv:
    print('GORILLA_SPAWN_DRY_RUN_OK',json.dumps(details));sys.exit(0)
pending={};published=[]
try:
    for kind,(path,before,after) in prepared.items():
        backup=REPORTS/f'gorilla-spawn-before-20261020-{kind}.xml'
        with backup.open('xb') as out:out.write(before)
        assert sha(backup.read_bytes())==sha(before)
        temp=REPORTS/(f'.gorilla-{kind}-'+uuid.uuid4().hex+'.tmp')
        with temp.open('xb') as out:out.write(after);out.flush();os.fsync(out.fileno())
        assert ET.fromstring(temp.read_bytes()).tag=='spawns'
        pending[kind]=temp
    for kind,(path,before,after) in prepared.items():
        assert path.read_bytes()==before,'Concurrent XML change; refusing replacement'
    for kind,(path,before,after) in prepared.items():
        assert path.read_bytes()==before,'Concurrent XML change; refusing replacement'
        os.replace(pending[kind],path);published.append(kind)
    for path,before,after in prepared.values():assert path.read_bytes()==after
    assert sha((ROOT/'assets/world/mapanovo.otbm').read_bytes())==fixture['canonical_map_hash']
    report['committed']=True;write('gorilla-spawn-relocation-20261020.json',report)
except BaseException as error:
    report.update(passed=False,committed=False,error=str(error))
    for kind in reversed(published):
        path,before,after=prepared[kind]
        if path.read_bytes()!=after:
            report['external_conflict']=str(path);continue
        restore=REPORTS/(f'.gorilla-restore-{kind}-'+uuid.uuid4().hex+'.tmp')
        restore.write_bytes(before);os.replace(restore,path)
    write('gorilla-spawn-relocation-20261020.json',report)
    raise
finally:
    for path in pending.values():path.unlink(missing_ok=True)
print('GORILLA_SPAWN_COMMITTED_OK',json.dumps(report))
