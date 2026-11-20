from pathlib import Path
import hashlib,json,os,runpy,shutil,zipfile,subprocess,sys
from nwoassets.runtime_sync import sync_runtime_assets
from nwoassets.versioning import _archive_world
ROOT=Path.cwd();OFFICIAL=ROOT.parent/'Server-Data-Nwo/data/world/mapanovo.otbm';OP=ROOT/'assets/world/mapanovo.otbm'
def checksum(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
original=checksum(OFFICIAL)
assert original==checksum(OP)=='f4729e973198b4e4e96a923c0515a82d0763f0d8fb67ed8375291c0a2ca95c4f'
assets={str(p):checksum(p)for p in [ROOT/'assets/860/Tibia.dat',ROOT/'assets/860/Tibia.spr',ROOT/'assets/items/items.otb',ROOT/'assets/items/items.xml']}
runpy.run_module('reports.update-chiyo-doors-20261120',run_name='__main__')
changed=checksum(OP);assert changed!=original and checksum(OFFICIAL)==original
print('Syncing validated map through official runtime program...',flush=True)
r=sync_runtime_assets(ROOT,expected_server_map_hash=original)
assert r['passed'] and checksum(OFFICIAL)==changed
(ROOT/'reports/sync-runtime-chiyo-doors-20261120.json').write_text(json.dumps(r,indent=2),encoding='utf8')
# The tracked server archive is generated and tested by the same NWO-ASSETS archiver.
archive=OFFICIAL.with_suffix('.zip');pending=archive.with_name('mapanovo.chiyo-pending.zip')
assert not pending.exists()
old_archive_hash=checksum(archive)
backup=ROOT/'reports'/('server-map-zip-before-chiyo-'+old_archive_hash+'.zip')
if not backup.exists():shutil.copyfile(archive,backup)
assert checksum(backup)==old_archive_hash
_archive_world(OFFICIAL,pending)
assert checksum(OFFICIAL)==changed and checksum(archive)==old_archive_hash
os.replace(pending,archive)
with zipfile.ZipFile(archive)as z:
 assert z.namelist()==['mapanovo.otbm'] and z.testzip() is None
 with z.open('mapanovo.otbm')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==changed
assert all(checksum(Path(p))==v for p,v in assets.items())
(ROOT/'reports/chiyo-server-archive-20261120.json').write_text(json.dumps({'passed':True,'archive':str(archive),'archive_sha256':checksum(archive),'previous_archive_backup':str(backup),'map_source_sha256':original,'map_result_sha256':changed,'dat_spr_otb_xml_preserved':True},indent=2),encoding='utf8')
print('Official map, server ZIP and runtime copies validated and synchronized.',flush=True)
subprocess.run([sys.executable,'-m','nwoassets','inspect-map-position','.', '2726','866','8','-o','reports/position-after-chiyo-doors-20261120.json'],check=True)
subprocess.run([sys.executable,'-m','nwoassets','inspect-world','.', '-o','reports/inspect-world-chiyo-doors-20261120.json'],check=True)
subprocess.run([sys.executable,'-m','nwoassets','validate','.', '--deep-spr','-o','reports/validation-final-chiyo-doors-20261120.json'],check=True)
print('Final Chiyo map verification complete.',flush=True)
