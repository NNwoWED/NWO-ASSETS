"""Three-way consolidation explicitly requested for the mob-estrelado branch.

The existing adopt-runtime gate stays strict. This separate operation accepts a
verified client archive and a Git ancestor, refuses overlapping DAT edits, keeps
all canonical records/payloads, remaps appended sprites and extends categories.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import base64

from .atomic import atomic_binary_output
from .binary import BinaryReader
from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import _commit_transaction, _remove_if_exists, _sha256_segment, _transaction_path, verify_sprite_hash_algorithm
from .otfi import parse_otfi
from .pipeline import inspect_client, validate_root
from .roundtrip import append_spr_blocks, scan_dat_record_spans
from .runtime_adopt import _property_map, update_otb_from_runtime
from .sprites import RGBA_SIZE, decode_sprite_for_hash, read_spr_blocks, sprite_hash
from .versioning import create_version, find_rar, require_asset_layout, _run_rar


def git_asset(root: Path, ref: str, path: str) -> bytes | Path:
    """Resolve a Git blob or a verified local LFS object, without a checkout."""
    raw = subprocess.check_output(['git', '-C', str(root), 'show', f'{ref}:{path}'])
    if not raw.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
        return raw
    fields = dict(line.split(' ', 1) for line in raw.decode('ascii').splitlines()[1:])
    digest = fields['oid'].removeprefix('sha256:')
    common = subprocess.check_output(['git','-C',str(root),'rev-parse','--git-common-dir'],text=True).strip()
    common_path = (root / common).resolve()
    obj = common_path/'lfs/objects'/digest[:2]/digest[2:4]/digest
    if not obj.is_file() or obj.stat().st_size != int(fields['size']) or sha256_file(obj).lower() != digest:
        raise FormatError(f'objeto ancestral LFS ausente ou divergente: {path}')
    return obj


def merge_plan(base: dict, canonical: dict, incoming: dict) -> tuple[set, list]:
    selected, conflicts = set(), []
    for key, record in incoming.items():
        if key not in base:
            if key in canonical: conflicts.append(key)
            elif key not in canonical: selected.add(key)
        elif record != base[key]:
            # Equal DAT bytes can still refer to different appended SPR payloads.
            # Do not infer semantic equality for simultaneous branch edits.
            if key not in canonical or canonical[key] != base[key]: conflicts.append(key)
            else: selected.add(key)
    # An incoming removal of an ancestral record must never pass unnoticed.
    conflicts.extend(key for key in base if key not in incoming)
    return selected, sorted(set(conflicts))


def remap_record(data: bytes, span, otfi, mapping: dict[int,int]) -> bytes:
    result = bytearray(data[span.start:span.end])
    reader = BinaryReader(data, source='incoming DAT')
    reader.position = span.properties_end
    groups = reader.u8() if otfi.frame_groups and span.category == 'outfits' else 1
    size, fmt = (4, '<I') if otfi.extended else (2, '<H')
    for _ in range(groups):
        if otfi.frame_groups and span.category == 'outfits': reader.u8()
        width, height = reader.u8(), reader.u8()
        if width > 1 or height > 1: reader.u8()
        dimensions = [width,height] + [reader.u8() for _ in range(5)]
        frames = dimensions[-1]
        if frames > 1 and otfi.frame_durations: reader.skip(6 + frames*8)
        count = 1
        for value in dimensions: count *= value
        for _ in range(count):
            offset = reader.position
            original = reader.u32() if otfi.extended else reader.u16()
            struct.pack_into(fmt,result,offset-span.start,mapping.get(original,original))
    if reader.position != span.end: raise FormatError('remapeamento DAT não terminou no limite do registro')
    return bytes(result)


def consolidate_runtime(root: Path, *, archive: Path, ancestor: str, dry_run: bool=False, deep_spr: bool=True, resolutions: Path | None=None, metadata_dir: Path | None=None) -> dict:
    root, archive = root.resolve(), archive.resolve()
    layout = require_asset_layout(root)
    validation = validate_root(root,deep_spr=True)
    if not validation['passed']: raise FormatError('baseline canônica reprovou antes da consolidação')
    before = inspect_client(root/'assets',deep_spr=deep_spr)
    paths = {k:Path(v) for k,v in before['paths'].items()}
    otfi = parse_otfi(paths['otfi'])
    ancestor_commit = subprocess.check_output(['git','-C',str(root),'rev-parse',ancestor],text=True).strip()
    base_dat = git_asset(root,ancestor_commit,'assets/860/Tibia.dat')
    base_dat = base_dat.read_bytes() if isinstance(base_dat,Path) else base_dat
    base_spr = git_asset(root,ancestor_commit,'assets/860/Tibia.spr')
    if not isinstance(base_spr,Path): raise FormatError('ancestral SPR deve estar em um objeto LFS local verificado')
    archive_hash = sha256_file(archive)
    metadata_changes={};metadata_sources={}
    if metadata_dir:
        for name in ['items.otml','creatures.otml','effects.otml','missiles.otml','things.otml']:
            canonical=root/name;source=metadata_dir/name
            old=canonical.read_bytes();new=source.read_bytes();base=git_asset(root,ancestor_commit,name)
            base=base.read_bytes() if isinstance(base,Path) else base
            metadata_sources[source]=sha256_file(source)
            if new==old or new==base:continue
            if old!=base:raise FormatError(f'conflito de metadados deve ser resolvido explicitamente: {name}')
            metadata_changes[canonical]=new
    rar = find_rar()
    _run_rar(rar,['t','-idq',str(archive)])
    listed = _run_rar(rar,['lb',str(archive)]).decode('utf-8',errors='replace')
    allowed = {'860','860/tibia.dat','860/tibia.spr','860/tibia.otfi','860/.gitattributes'}
    for line in listed.splitlines():
        name=line.strip().replace('\\','/')
        p=PureWindowsPath(name)
        if name and (p.is_absolute() or p.drive or '..' in p.parts or name.lower() not in allowed):
            raise FormatError(f'entrada não autorizada no arquivo: {name}')
    with tempfile.TemporaryDirectory(prefix='.runtime-consolidate-',dir=root/'reports') as tmp:
        extracted=Path(tmp)
        _run_rar(rar,['x','-idq','-y','-o+',str(archive),str(extracted)+os.sep])
        incoming_dir=extracted/'860'
        # Keep input filenames distinct from canonical discovery during the
        # mandatory create-version/final validation scans.
        for suffix in ['dat','spr','otfi']:
            (incoming_dir/f'Tibia.{suffix}').rename(incoming_dir/f'incoming.{suffix}')
        incoming_otfi=parse_otfi(incoming_dir/'incoming.otfi')
        if incoming_otfi != otfi: raise FormatError('OTFI de entrada diverge do perfil canônico')
        incoming_spr=inspect_spr(incoming_dir/'incoming.spr',otfi,deep=deep_spr)
        incoming_dat=inspect_dat(incoming_dir/'incoming.dat',otfi,expected_metadata_reader=before['profile']['metadata_reader'],sprite_count=int(incoming_spr['sprite_count']))
        if incoming_spr.get('errors') or incoming_dat.get('errors'): raise FormatError('DAT/SPR de entrada reprovados')
        base_info=inspect_spr(base_spr,otfi,deep=deep_spr)
        base_count=int(base_info['sprite_count'])
        body_size=base_spr.stat().st_size-int(base_info['table_end'])
        body_hash=_sha256_segment(base_spr,int(base_info['table_end']))
        for label,path,info in [('canônico',paths['spr'],before['spr']),('main',incoming_dir/'incoming.spr',incoming_spr)]:
            if int(info['sprite_count'])<base_count or _sha256_segment(path,int(info['table_end']),body_size)!=body_hash:
                raise FormatError(f'SPR {label} não preserva o payload ancestral; consolidação bloqueada')
            # Payload equality alone cannot prove that old IDs still point to it.
            with base_spr.open('rb') as a,path.open('rb') as b:
                header=8 if otfi.extended else 6
                a.seek(header);b.seek(header)
                old_offsets=struct.unpack(f'<{base_count}I',a.read(base_count*4))
                new_offsets=struct.unpack(f'<{base_count}I',b.read(base_count*4))
                shift=int(info['table_end'])-int(base_info['table_end'])
                if any((old+shift if old else 0)!=new for old,new in zip(old_offsets,new_offsets)):
                    raise FormatError(f'SPR {label} remapeou Sprite IDs ancestrais')
        current=paths['dat'].read_bytes();incoming=(incoming_dir/'incoming.dat').read_bytes()
        if current[:4]!=base_dat[:4] or incoming[:4]!=base_dat[:4]: raise FormatError('assinatura DAT divergente')
        def records(data):return {(s.category,s.thing_id):s for s in scan_dat_record_spans(data,otfi,'consolidação')}
        base_spans,cur_spans,new_spans=records(base_dat),records(current),records(incoming)
        def raw(data,spans):return {key:data[span.start:span.end] for key,span in spans.items()}
        selected,conflicts=merge_plan(raw(base_dat,base_spans),raw(current,cur_spans),raw(incoming,new_spans))
        resolved=[]
        if resolutions:
            decisions=json.loads(resolutions.read_text('utf-8'))['decisions']
            declared={(d['category'],int(d['client_id'])):d for d in decisions}
            if len(declared)!=len(decisions) or set(declared)!=set(conflicts):
                raise FormatError('resoluções devem corresponder exatamente aos conflitos encontrados')
            for key in conflicts:
                d=declared[key];a=cur_spans[key];b=new_spans[key]
                if hashlib.sha256(current[a.start:a.end]).hexdigest()!=d['canonical_record_sha256'] or hashlib.sha256(incoming[b.start:b.end]).hexdigest()!=d['incoming_record_sha256']:
                    raise FormatError(f'registro divergiu da resolução aprovada: {key}')
                if d['keep']=='incoming':selected.add(key)
                elif d['keep']!='canonical':raise FormatError('resolução deve escolher incoming ou canonical')
                resolved.append(d)
            conflicts=[]
        report={'root':str(root),'archive':str(archive),'archive_sha256':archive_hash,'ancestor':ancestor_commit,
            'dry_run':dry_run,'selected_records':[list(k) for k in sorted(selected)],'conflicts':[list(k) for k in conflicts],
            'canonical_records_preserved':len(cur_spans)-len(selected & cur_spans.keys()),'ancestral_payloads_verified':True}
        report['explicit_resolutions']=resolved
        report['metadata_changes']=[str(p.relative_to(root)) for p in metadata_changes]
        if conflicts: return {**report,'passed':False,'errors':['Conflitos DAT devem ser resolvidos explicitamente.']}
        new_count=int(incoming_spr['sprite_count']);cur_count=int(before['spr']['sprite_count'])
        # Retain every appended source payload, including currently unused ones.
        with (incoming_dir/'incoming.spr').open('rb') as stream:
            stream.seek(8 if otfi.extended else 6)
            offsets=struct.unpack(f'<{new_count}I',stream.read(new_count*4))
        source_ids={i for i in range(base_count+1,new_count+1) if offsets[i-1]}
        blocks=read_spr_blocks(incoming_dir/'incoming.spr',source_ids,otfi)
        mapping={sid:cur_count+index for index,sid in enumerate(sorted(source_ids),1)}
        mapping.update({sid:0 for sid in range(base_count+1,new_count+1) if not offsets[sid-1]})
        replacements={key:remap_record(incoming,new_spans[key],otfi,mapping) for key in selected}
        props={};hashes={};animated={}
        for category,cid in selected:
            if category!='items':continue
            if (category,cid) not in cur_spans:raise FormatError('novo Client ID de item exige import-cloned-items, não consolidação')
            old,new=cur_spans[(category,cid)],new_spans[(category,cid)]
            old_props,new_props=_property_map(current,old,'canonical'),_property_map(incoming,new,'main')
            if old_props!=new_props:props[cid]=(old_props,new_props)
            view=new.appearances[0];count=view.width*view.height*view.layers
            refs=set(view.sprite_ids[:count])-{0}
            pixel_blocks=read_spr_blocks(incoming_dir/'incoming.spr',refs,otfi)
            hashes[cid]=sprite_hash([bytes(RGBA_SIZE) if not sid else decode_sprite_for_hash(pixel_blocks[sid],transparency=otfi.transparency) for sid in view.sprite_ids[:count]])
            animated[cid]=any(a.frames>1 for a in new.appearances)
        report.update({'appended_sprites':len(blocks),'property_client_ids':sorted(props),'sprite_id_map':mapping})
        # Exercise all OTB translation gates before any version/commit.
        update_otb_from_runtime(paths['otb'],extracted/'preflight.otb',sprite_hashes=hashes,property_changes=props,animated=animated)
        if dry_run: return {**report,'passed':True,'errors':[]}
        gate=verify_sprite_hash_algorithm(paths['dat'],paths['spr'],paths['otb'],otfi)
        if not gate['passed']:raise FormatError('SpriteHash canônico reprovou antes da versão')
        backup=create_version(root)
        pending={paths[k]:_transaction_path(paths[k],'pending') for k in ['dat','spr','otb']}
        pending.update({p:_transaction_path(p,'pending') for p in metadata_changes})
        if any(p.exists() for p in pending.values()):raise FormatError('há arquivos pendentes anteriores')
        canonical_hashes={p:sha256_file(p) for p in (root/'assets').rglob('*') if p.is_file()}
        canonical_hashes.update({p:sha256_file(p) for p in metadata_changes})
        if metadata_changes:
            snapshot={'version_backup':backup,'files':[{'path':str(p),'sha256':sha256_file(p),'base64':base64.b64encode(p.read_bytes()).decode('ascii')} for p in metadata_changes]}
            snapshot_path=root/'reports'/('metadata-before-'+str(backup['version_id'])+'.json')
            with atomic_binary_output(snapshot_path) as output:output.write(json.dumps(snapshot,indent=2).encode('utf-8'))
            report['metadata_backup']=str(snapshot_path)
        try:
            append_spr_blocks(paths['spr'],pending[paths['spr']],otfi,[blocks[sid] for sid in sorted(blocks)])
            categories=['items','outfits','effects','missiles'];maxima=[]
            with atomic_binary_output(pending[paths['dat']]) as stream:
                for i,cat in enumerate(categories):maxima.append(max(struct.unpack_from('<H',current,4+i*2)[0],struct.unpack_from('<H',incoming,4+i*2)[0]))
                stream.write(current[:4]+struct.pack('<4H',*maxima))
                for cat,maximum in zip(categories,maxima):
                    for cid in range(100 if cat=='items' else 1,maximum+1):
                        key=(cat,cid)
                        if key in replacements:stream.write(replacements[key])
                        elif key in cur_spans:
                            span=cur_spans[key];stream.write(current[span.start:span.end])
                        else:raise FormatError(f'lacuna DAT na consolidação: {key}')
            changes=update_otb_from_runtime(paths['otb'],pending[paths['otb']],sprite_hashes=hashes,property_changes=props,animated=animated)
            for path,payload in metadata_changes.items():
                with atomic_binary_output(pending[path]) as output:output.write(payload)
            written=pending[paths['dat']].read_bytes();written_spans=records(written)
            for key,span in cur_spans.items():
                if key not in selected:
                    new=written_spans[key]
                    if current[span.start:span.end]!=written[new.start:new.end]:raise FormatError(f'registro canônico não alvo mudou: {key}')
            actual_blocks=read_spr_blocks(pending[paths['spr']],set(mapping.values())-{0},otfi)
            if any(actual_blocks[mapping[sid]]!=block for sid,block in blocks.items()):raise FormatError('pixels de entrada não persistiram')
            new_info=inspect_spr(pending[paths['spr']],otfi,deep=True)
            if _sha256_segment(pending[paths['spr']],int(new_info['table_end']),paths['spr'].stat().st_size-int(before['spr']['table_end'])) != _sha256_segment(paths['spr'],int(before['spr']['table_end'])):
                raise FormatError('payloads SPR canônicos não foram preservados')
            if archive_hash!=sha256_file(archive) or any(sha256_file(p)!=digest for p,digest in {**canonical_hashes,**metadata_sources}.items()):raise FormatError('entrada mudou durante a operação')
            final=_commit_transaction(root,pending,deep_spr=True)
        except BaseException:
            _remove_if_exists(list(pending.values()));raise
        for p,digest in canonical_hashes.items():
            if p not in pending and sha256_file(p)!=digest:raise FormatError(f'arquivo fora do lote mudou: {p}')
        return {**report,'version_backup':backup,'otb_changes':changes,'transaction_committed':True,
            'old_sprite_payload_preserved':True,'incoming_pixels_verified':True,'non_target_records_verified':True,
            'output_hashes':{k:sha256_file(paths[k]) for k in ['dat','spr','otb']},'final_validation_passed':final['passed'],
            'passed':final['passed'],'errors':final.get('errors',[])}
