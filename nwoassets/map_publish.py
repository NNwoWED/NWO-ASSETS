"""Canonical map publication for NWO Map Gen, with mandatory asset versioning.

Drafts and conversions are never additional operational maps. This adapter is
the sole binary publication path: validate -> version -> staged rewrite -> audit
-> replace -> deep validation, with automatic rollback from that exact version.
"""
from __future__ import annotations
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
import zipfile

from .map_edit import (rewrite_map, inspect_map, iter_tile_records, rebase_tile, tile_record, append_tile_items,
                       _mapped, _scan, _changes_hash)
from .pipeline import validate_root
from .versioning import create_version

MAX_PUBLISH_CHANGES=1_048_576


def _hash(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def _report(path,value):
    tmp=path.with_suffix('.tmp')
    with tmp.open('x',encoding='utf-8') as out:
        json.dump(value,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
    os.replace(tmp,path)


def _extract(archive,entry,destination):
    with zipfile.ZipFile(archive) as zf:
        if zf.namelist()!=[entry] or zf.testzip() is not None:
            raise ValueError('Backup do mapa inválido.')
        with zf.open(entry) as src,Path(destination).open('xb') as out:
            shutil.copyfileobj(src,out,4*1024*1024);out.flush();os.fsync(out.fileno())


def _journal_settings(root,path,context):
    if path is None:
        if context is not None:raise ValueError('journal_context requer journal_path.')
        return None,None
    argument=Path(path)
    destination=argument.resolve()
    if argument.is_symlink() or destination.suffix.lower()!='.json' or not destination.parent.is_dir():
        raise ValueError('Journal requer arquivo JSON regular em diretório existente.')
    if destination.is_relative_to(root/'assets') or destination.is_relative_to(root/'versions'):
        raise ValueError('Journal não pode substituir assets ou versões imutáveis.')
    context={} if context is None else context
    if not isinstance(context,dict):raise ValueError('journal_context deve ser um objeto JSON.')
    pending=[(context,0)]
    visited=set()
    while pending:
        value,depth=pending.pop()
        if depth>32:raise ValueError('Contexto do journal excede 32 níveis.')
        if isinstance(value,(dict,list)):
            if id(value) in visited:continue
            visited.add(id(value))
            if isinstance(value,dict):
                if any(type(key) is not str for key in value):raise ValueError('Chaves do journal devem ser strings.')
                pending.extend((item,depth+1) for item in value.values())
            else:pending.extend((item,depth+1) for item in value)
        elif value is not None and type(value) not in (str,int,float,bool):
            raise ValueError('Contexto contém valor fora do formato JSON.')
    try:
        data=json.dumps(context,ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (ValueError,TypeError,RecursionError) as exc:
        raise ValueError('Contexto do journal não é JSON válido/finito.') from exc
    if len(data)>1024*1024:raise ValueError('Contexto do journal excede 1 MiB.')
    return destination,json.loads(data)


def _write_journal(path,value):
    """Durable atomic receipt; a failed write never destroys the prior receipt."""
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as output:
            output.write(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8'))
            output.flush();os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def _audit_changes(source,staged,changes,audit,*,cancel=None,progress=None,item_additions=None):
    """Stream exact before/after records, retaining offsets instead of tile data.

    Each old coordinate uses one packed integer key and one offset. No whole-map
    sets, old/new raw-tile dictionaries or item lists survive between callbacks.
    Metadata hashing shares the same two scans instead of two additional passes.
    """
    old_offsets={}
    item_additions={} if item_additions is None else item_additions
    verified_additions=set()
    expected_non_null=sum(raw is not None for raw in changes.values())
    checked=0
    def tick(value,message):
        if cancel and cancel.is_set():raise InterruptedError('Auditoria cancelada; mapa preservado.')
        if progress:progress(value,message)
    with _mapped(source) as original:
        def remember(pos,begin,end,area):
            if pos not in changes:return
            raw=changes[pos]
            before=tile_record(original,begin)
            if pos in item_additions:
                expected=append_tile_items(rebase_tile(before['raw'],*pos),item_additions[pos])
                if raw is None or rebase_tile(raw,*pos)!=expected:
                    raise ValueError(f'Item append changed existing tile data: {pos}.')
                verified_additions.add(pos)
            elif before['protected'] and (raw is None or rebase_tile(before['raw'],*pos)!=rebase_tile(raw,*pos)):
                raise ValueError(f'Tile protegido não pode ser sobrescrito: {pos}.')
            old_offsets[pos[0]|pos[1]<<16|pos[2]<<32]=begin
        source_report=_scan(original,cancel=cancel,on_tile=remember,collect_areas=False,
                            progress=lambda f,*_:tick(f*.45,'Auditando offsets e proteções da origem'))
        source_metadata=source_report['metadataHash']
        if verified_additions!=set(item_additions):
            raise ValueError('Item append requires existing source tiles for every declared position.')
        indexed=len(old_offsets)
        del source_report  # Release its potentially large TILE_AREA inventory now.
        with gzip.open(audit,'wt',encoding='utf-8') as output:
            def write_row(pos,before,after):
                output.write(json.dumps({'x':pos[0],'y':pos[1],'z':pos[2],
                    'before':before['items'] if before else [],'after':after['items'] if after else [],
                    'beforeHash':hashlib.sha256(before['raw']).hexdigest() if before else None,
                    'afterHash':hashlib.sha256(after['raw']).hexdigest() if after else None})+'\n')
            with _mapped(staged) as destination:
                def verify(pos,begin,end,area):
                    nonlocal checked
                    if pos not in changes:return
                    raw=changes[pos]
                    if raw is None:raise ValueError(f'Remoção não persistiu: {pos}.')
                    after=tile_record(destination,begin)
                    if rebase_tile(after['raw'],*pos)!=rebase_tile(raw,*pos):
                        raise ValueError(f'Dados persistidos divergentes: {pos}.')
                    code=pos[0]|pos[1]<<16|pos[2]<<32
                    offset=old_offsets.pop(code,None)
                    before=tile_record(original,offset) if offset is not None else None
                    write_row(pos,before,after)
                    checked+=1
                target_report=_scan(destination,cancel=cancel,on_tile=verify,collect_areas=False,
                                    progress=lambda f,*_:tick(.45+f*.5,'Conferindo destino e gravando auditoria'))
                target_metadata=target_report['metadataHash']
                del target_report
            if checked!=expected_non_null:
                raise ValueError('Um ou mais tiles solicitados não apareceram no mapa gravado.')
            # What remains in the offset table must have been deleted. The count
            # above, unique-coordinate validation and membership checks prove that
            # every requested non-null tile was encountered exactly once.
            for index,(code,offset) in enumerate(old_offsets.items()):
                if index%4096==0:tick(.96,'Auditando remoções persistidas')
                pos=(code&65535,(code>>16)&65535,code>>32)
                if changes[pos] is not None:raise ValueError(f'Tile solicitado não persistiu: {pos}.')
                write_row(pos,tile_record(original,offset),None)
            for index,(pos,raw) in enumerate(changes.items()):
                if index%4096==0:tick(.98,'Finalizando auditoria das coordenadas')
                if raw is None and (pos[0]|pos[1]<<16|pos[2]<<32) not in old_offsets:
                    write_row(pos,None,None)
    return {'sourceMetadataHash':source_metadata,'outputMetadataHash':target_metadata,
            'indexedSourceOffsets':indexed,'verifiedOutputTiles':checked,'rows':len(changes)}


def publish_map(root,source,changes,*,expected_hash,source_hash,cancel=None,progress=None,before_replace=None,
                journal_path=None,journal_context=None,history_source_hash=None,history_baseline_file=None,
                item_additions=None):
    """Publish with an optional durable application recovery receipt.

    Journal schema 1 is prepared before the atomic map swap. ``context`` is an
    opaque JSON snapshot supplied by the app (original/current source hashes,
    workspace, commit); no application files are reconstructed here. At startup,
    a prepared journal is recoverable only if canonical SHA256 equals outputHash
    AND a fresh validate_root(...,deep_spr=True) passes. A committed-receipt write
    failure returns committed=True plus receiptWarning, never a false rollback.

    Supplying both history arguments publishes an incremental batch from the
    current canonical map while retaining the original immutable history base.
    ``sourceHash`` then identifies the batch input; ``historySourceHash`` and
    ``baselineFile`` identify the original timeline. Omitting both preserves the
    legacy full-draft/source-cache contract.

    ``item_additions`` declares exact appended Server IDs for existing ordinary
    or protection-zone tiles. The audit requires every old byte to survive;
    other protected content and undeclared tile edits remain rejected.
    """
    # Explicit additive edits preserve the entire old encoded subtree. They do
    # not grant a general overwrite permission for protected tiles.
    additions={}
    if item_additions is not None:
        for pos,ids in item_additions.items():
            if pos not in changes or changes[pos] is None:
                raise ValueError('Item append must name a non-null changed tile.')
            additions[pos]=tuple(ids)
            append_tile_items(changes[pos],additions[pos])  # Validate IDs/layout without writing.
    source_argument=Path(source)
    root=Path(root).resolve();canonical=root/'assets/world/mapanovo.otbm';source=source_argument.resolve()
    if canonical.is_symlink() or source_argument.is_symlink():raise ValueError('Mapas simbólicos não são permitidos.')
    if source!=canonical and not source.is_relative_to(root/'drafts/history'):
        raise ValueError('Fonte deve ser o mapa canônico ou o cache de histórico validado.')
    checkpoint_mode=history_source_hash is not None or history_baseline_file is not None
    if checkpoint_mode:
        if (not isinstance(history_source_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',history_source_hash)
                or history_baseline_file is None):
            raise ValueError('Checkpoint requer hash histórico SHA256 e arquivo da baseline original.')
        if source!=canonical or source_hash!=expected_hash:
            raise ValueError('Lote incremental deve partir do mapa canônico atual e de seu hash esperado.')
        cache=root/'drafts/history'/(history_source_hash+'.baseline')
        history_argument=Path(history_baseline_file)
        if history_argument.is_symlink() or history_argument.resolve()!=cache:
            raise ValueError('Baseline histórica deve usar o cache original exato dentro de drafts/history.')
    else:
        cache=root/'drafts/history'/(source_hash+'.baseline')
        history_source_hash=source_hash
    if len(changes)>MAX_PUBLISH_CHANGES:
        raise ValueError('Publicação limitada temporariamente a 1.048.576 tiles alterados no lote ativo. '
                         'Reduza as alterações ainda não publicadas; nenhum arquivo foi alterado.')
    journal_path,journal_context=_journal_settings(root,journal_path,journal_context)
    run_id=datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]
    reports=root/'reports';reports.mkdir(exist_ok=True)
    draft=root/'drafts'/('publish-'+run_id);draft.mkdir(parents=True,exist_ok=False)
    staged=draft/'map.tmp';rollback=draft/'rollback.tmp'
    report={'passed':False,'committed':False,'runId':run_id,'sourceHash':source_hash,
            'expectedCanonicalHash':expected_hash,'changes':len(changes),'positions':[],
            'startedAt':datetime.now().astimezone().isoformat()}
    if additions:
        report['itemAdditions']=[{'position':list(pos),'serverIds':list(ids)} for pos,ids in additions.items()]
    if checkpoint_mode:report['historySourceHash']=history_source_hash
    version=None;replaced=False;written_hash=None;journal=None;journal_prepared=False
    def tick(value,message):
        if cancel and cancel.is_set():raise InterruptedError('Gravação cancelada antes da confirmação final.')
        if progress:progress(value,message)
    try:
        tick(.02,'Validando baseline completa (DAT, SPR, OTB e mapa)')
        if _hash(canonical)!=expected_hash or _hash(source)!=source_hash:
            raise ValueError('O mapa mudou desde a abertura do projeto; gravação recusada.')
        if cache.is_symlink():raise ValueError('Cache histórico simbólico não é permitido.')
        if cache.exists():
            if _hash(cache)!=history_source_hash:raise ValueError('Cache de histórico corrompido; não foi substituído.')
        elif history_source_hash!=source_hash or source!=canonical:
            raise ValueError('Cache original de histórico não está disponível.')
        # items.xml deliberately is not in the immutable items.rar inventory,
        # but it is still part of the source contract for this publication.
        xml_hash=_hash(root/'assets/items/items.xml')
        changes_hash=_changes_hash(changes,cancel)
        # Validate ALL new Server IDs against canonical OTB/DAT before versioning.
        from .properties import read_otb_items
        from .roundtrip import scan_dat_record_spans
        from .otfi import parse_otfi
        mapping=read_otb_items(root/'assets/items/items.otb')
        dat=(root/'assets/860/Tibia.dat').read_bytes()
        cids={r.thing_id for r in scan_dat_record_spans(dat,parse_otfi(root/'assets/860/Tibia.otfi'),'map publication') if r.category=='items'}
        for pos,raw in changes.items():
            if raw is None:continue
            for sid in tile_record(raw)['items']:
                if sid not in mapping or mapping[sid]['client_id'] not in cids:
                    raise ValueError(f'SID {sid} sem vínculo OTB/DAT válido em {pos}.')
        del dat,cids,mapping  # Deep validation loads its own asset data next.
        before=validate_root(root,deep_spr=True)
        _report(reports/('map-before-'+run_id+'.json'),before)
        if not before.get('passed') or before.get('errors'):raise ValueError('A validação inicial falhou; nenhuma mudança foi aplicada.')
        tick(.15,'Criando e testando a versão imutável de todos os assets')
        version=create_version(root)
        if not version.get('passed'):raise ValueError('Versionamento obrigatório falhou.')
        report['version']=version
        archive=Path(version['archives']['world']['path'])
        # A readonly cache has no .otbm extension and is not an operational map.
        # It lets the editor compare prior revisions after canonical publication.
        cache.parent.mkdir(parents=True,exist_ok=True)
        if cache.exists():
            if cache.is_symlink() or _hash(cache)!=history_source_hash:raise ValueError('Cache de histórico corrompido; não foi substituído.')
        elif source==canonical and history_source_hash==source_hash:
            temporary_cache=cache.with_suffix('.'+run_id+'.tmp')
            try:
                _extract(archive,canonical.name,temporary_cache)
                if _hash(temporary_cache)!=history_source_hash:raise ValueError('Backup não corresponde à baseline do editor.')
                os.replace(temporary_cache,cache)
            finally:temporary_cache.unlink(missing_ok=True)
        else:raise ValueError('Cache original de histórico não está disponível.')
        tick(.26,'Reescrevendo somente os tiles alterados')
        output=rewrite_map(source,staged,changes,cancel=cancel,
            progress=lambda f,*_:tick(.26+.3*f,'Montando mapa e preservando atributos desconhecidos'))
        written_hash=output['sha256']
        audit=reports/('map-positions-'+run_id+'.jsonl.gz')
        audit_stats=_audit_changes(source,staged,changes,audit,cancel=cancel,
                                 progress=lambda f,message:tick(.56+.10*f,message),item_additions=additions)
        report['positionReport']=str(audit)
        report['audit']=audit_stats
        # Metadata (towns, spawns filenames, unknown nodes) cannot be modified.
        if audit_stats['sourceMetadataHash']!=audit_stats['outputMetadataHash']:
            raise ValueError('Metadados fora da seleção foram alterados.')
        tick(.67,'Conferindo conflitos e preparando troca atômica')
        if _hash(canonical)!=expected_hash:raise ValueError('Outro editor salvou o mapa. Nenhum arquivo foi sobrescrito.')
        if _hash(source)!=source_hash:raise ValueError('A baseline de histórico mudou durante a preparação.')
        if _hash(cache)!=history_source_hash:raise ValueError('A baseline original mudou durante a preparação.')
        if _changes_hash(changes,cancel)!=changes_hash:raise ValueError('O rascunho mudou durante a publicação; nada foi aplicado.')
        # Version inventories use uppercase hex; local hashes use lowercase.
        # Normalize representation while still comparing the complete digest.
        expected_assets={r['path']:r['sha256'].lower() for r in version['sources'] if r['path']!='assets/world/mapanovo.otbm'}
        expected_assets['assets/items/items.xml']=xml_hash
        for name,checksum in expected_assets.items():
            if _hash(root/name)!=checksum:raise ValueError('Os assets mudaram durante a preparação.')
        if before_replace:before_replace(cache)
        tick(.7,'Gravando arquivo canônico e verificando a integridade final')
        if journal_path is not None:
            journal={'schema':1,'kind':'nwo-map-publication','runId':run_id,'stage':'prepared',
                     'canonicalFile':str(canonical),'expectedCanonicalHash':expected_hash,'outputHash':written_hash,
                     'sourceHash':source_hash,'baselineFile':str(cache),'versionId':version['version_id'],
                     'recoveryArchive':str(archive),'positionReport':str(audit),
                     'publicationReport':str(reports/('map-publish-'+run_id+'.json')),
                     'beforeReport':str(reports/('map-before-'+run_id+'.json')),
                     'afterReport':str(reports/('map-after-'+run_id+'.json')),
                     'preparedAt':datetime.now().astimezone().isoformat(),'context':journal_context}
            if checkpoint_mode:journal['historySourceHash']=history_source_hash
            _write_journal(journal_path,journal)
            journal_prepared=True
            report['journalPath']=str(journal_path)
            tick(.71,'Journal preparado; conferindo troca final do mapa')
        # Rebinding may take time and external editors are not governed by our
        # application lock. Recheck after the callback, immediately before swap.
        if _hash(canonical)!=expected_hash:
            raise ValueError('Outro editor salvou o mapa durante a preparação final. Nenhum arquivo foi sobrescrito.')
        if _hash(cache)!=history_source_hash:
            raise ValueError('A baseline original mudou antes da troca final; gravação recusada.')
        for name,checksum in expected_assets.items():
            if _hash(root/name)!=checksum:raise ValueError('Os assets mudaram antes da troca final; gravação recusada.')
        os.replace(staged,canonical);replaced=True
        after=validate_root(root,deep_spr=True)
        _report(reports/('map-after-'+run_id+'.json'),after)
        if not after.get('passed') or after.get('errors'):raise ValueError('Validação final falhou; restaurando versão anterior.')
        tick(.9,'Conferindo hashes finais e concluindo publicação')
        for name,checksum in expected_assets.items():
            if _hash(root/name)!=checksum:raise ValueError('Asset não relacionado mudou durante a gravação.')
        checksum=_hash(canonical)
        if checksum!=written_hash:
            raise ValueError('Outro editor alterou o mapa durante a validação final; essa edição externa será preservada.')
        if _hash(cache)!=history_source_hash:
            raise ValueError('A baseline original mudou durante a validação final.')
        report.update(passed=True,committed=True,sha256=checksum,baselineFile=str(cache),
                      versionId=version['version_id'],rewrite=output,
                      completedAt=datetime.now().astimezone().isoformat())
        _report(reports/('map-publish-'+run_id+'.json'),report)
        result={k:report[k] for k in ('passed','committed','sha256','baselineFile','versionId','positionReport')}
        if additions:result['itemAdditions']=report['itemAdditions']
        if checkpoint_mode:result.update(sourceHash=source_hash,historySourceHash=history_source_hash)
        if journal_path is not None:
            result['journalPath']=str(journal_path)
            committed_journal={**journal,'stage':'committed','committedAt':report['completedAt'],'result':dict(result)}
            try:
                _write_journal(journal_path,committed_journal)
            except Exception as receipt_exc:
                # The prepared record is already durable and records both hashes.
                # Do not roll a verified map back merely because UI bookkeeping
                # ran out of disk space after publication was actually complete.
                result['receiptWarning']='Mapa gravado e validado, mas o recibo final não pôde ser atualizado. '
                result['receiptWarning']+=f'O journal preparado permite recuperação na próxima abertura: {receipt_exc}'
        return result
    except BaseException as exc:
        report.update(passed=False,committed=False,error=str(exc))
        recovery_error=None
        if replaced and version:
            try:
                current_hash=_hash(canonical) if canonical.exists() else None
                if current_hash!=written_hash:
                    report.update(externalConflict=True,restored=False,observedCanonicalHash=current_hash,
                                  recoveryArchive=version['archives']['world']['path'])
                    recovery_error=RuntimeError('Conflito com alteração externa após a gravação: o mapa atual não foi sobrescrito. '
                                                f'Recupere ou compare manualmente com o backup: {version["archives"]["world"]["path"]}')
                else:
                    _extract(Path(version['archives']['world']['path']),canonical.name,rollback)
                    if _hash(rollback)!=expected_hash:raise ValueError('Backup de rollback não confere.')
                    # Extraction itself can be lengthy. Never restore over a save
                    # that arrived while the archive was being checked/extracted.
                    current_hash=_hash(canonical) if canonical.exists() else None
                    if current_hash!=written_hash:
                        report.update(externalConflict=True,restored=False,observedCanonicalHash=current_hash,
                                      recoveryArchive=version['archives']['world']['path'])
                        recovery_error=RuntimeError('O mapa foi alterado externamente durante a recuperação e foi preservado. '
                                                    f'Backup disponível: {version["archives"]["world"]["path"]}')
                    else:
                        os.replace(rollback,canonical)
                        report['restored']=_hash(canonical)==expected_hash
            except BaseException as restore_exc:
                report['restoreError']=str(restore_exc)
                recovery_error=RuntimeError(f'Gravação falhou e restauração exige intervenção: {restore_exc}. Backup: {version["root"]}')
        if journal_prepared:
            try:
                observed=_hash(canonical) if canonical.exists() else None
                failed_journal={**journal,'stage':'rolled-back' if observed==expected_hash else 'external-conflict',
                                'failedAt':datetime.now().astimezone().isoformat(),'error':str(exc),
                                'observedCanonicalHash':observed,'restored':report.get('restored',False),
                                'recoveryRequired':observed!=expected_hash}
                _write_journal(journal_path,failed_journal)
            except Exception as receipt_exc:
                report['receiptWarning']=f'Journal anterior preservado; falha ao registrar encerramento: {receipt_exc}'
        _report(reports/('map-publish-'+run_id+'.json'),report)
        if recovery_error is not None:raise recovery_error from exc
        raise
    finally:
        # Only temporary files explicitly created in this run are removed.
        staged.unlink(missing_ok=True);rollback.unlink(missing_ok=True)
        try:draft.rmdir()
        except OSError:pass
