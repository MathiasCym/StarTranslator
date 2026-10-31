"""Repeat the ordinary app workflow in isolated data; no document-specific repairs.

Explicit --allow-model is required because selected files reach the configured
model. Outputs, progress and evidence remain under --evidence. Never use the
live application profile as the evidence directory.
"""
import argparse
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',action='append',required=True,help='Input document; repeat for a format matrix')
    parser.add_argument('--evidence',required=True,help='Dedicated private QA directory')
    parser.add_argument('--allow-model',action='store_true',help='Allow the selected documents to reach the configured model')
    parser.add_argument('--expected-host',help='Optional exact model host restriction')
    parser.add_argument('--company-model',action='store_true',help='Use the built-in company connection for explicitly authorized materials; do not change the live configuration')
    parser.add_argument('--resume',action='store_true',help='Reuse this QA profile after a separate fresh acceptance')
    parser.add_argument('--forbid-requests',action='store_true',help='With --resume, fail any attempted model request to prove complete checkpoint reuse')
    parser.add_argument('--apply-suggestions',action='store_true',help='Apply suggestions to test copies before the final save')
    parser.add_argument('--workers',type=int,choices=(1,3),default=3)
    parser.add_argument('--direction',choices=('zh-en','en-zh'),default='zh-en')
    args=parser.parse_args()
    if not args.allow_model and not (args.resume and args.forbid_requests):parser.error('--allow-model is required; this command uses the configured model')
    if args.forbid_requests and not args.resume:parser.error('--forbid-requests requires --resume')
    from backend import workflow
    from backend.glossary import store
    from backend.llm.client import LLMClient,DEFAULT_BASE_URL,DEFAULT_MODEL
    from backend.translation_audit import saved_residuals
    current_profile=Path(os.environ['APPDATA'])/'StarTranslator'
    original_profile=Path(os.environ.get('NOVATERM_DATA_DIR') or (current_profile if current_profile.exists() else Path(os.environ['APPDATA'])/'novaterm-checker')).resolve()
    os.environ['NOVATERM_DATA_DIR']=str(original_profile)
    client=LLMClient(provider='intranet',base_url=DEFAULT_BASE_URL,model=DEFAULT_MODEL) if args.company_model else LLMClient()
    from backend.llm import client as transport
    from backend.llm.client import LLMUnavailable
    if args.expected_host and urlsplit(client.base_url).hostname!=args.expected_host:parser.error('Configured model host differs from --expected-host')
    requests={'sent':0,'blocked':0};original_open=transport._urlopen
    def guarded(request,timeout):
        if args.expected_host and urlsplit(request.full_url).hostname!=args.expected_host:
            requests['blocked']+=1;raise ValueError('Unexpected model destination')
        if args.forbid_requests:
            requests['blocked']+=1;raise LLMUnavailable('验收禁止模型请求；当前断点尚不能完全复用。')
        requests['sent']+=1
        return original_open(request,timeout)
    transport._urlopen=guarded
    settings=original_profile/'lexicon-settings.json'
    lexicon=Path(json.loads(settings.read_text('utf-8')).get('path') or original_profile/'lexicon.json') if settings.exists() else original_profile/'lexicon.json'
    entries=store.read(lexicon)['entries'] if lexicon.exists() else store.seed_entries()
    root=Path(args.evidence).resolve();profile=root/'profile'
    if root==original_profile or root.is_relative_to(original_profile) or original_profile.is_relative_to(root):
        parser.error('Evidence must be separate from the live application profile')
    checkpoint=profile/'task-checkpoints.sqlite3'
    if checkpoint.exists() and not args.resume:parser.error('Fresh acceptance requires a new evidence directory; use --resume separately')
    if args.resume and not checkpoint.exists():parser.error('No checkpoints exist in this evidence directory')
    profile.mkdir(parents=True,exist_ok=True)
    store.atomic_json(profile/'lexicon.json',entries)
    os.environ['NOVATERM_DATA_DIR']=str(profile)
    run_id=uuid.uuid4().hex
    source_paths=list(dict.fromkeys(str(Path(p).resolve()) for p in args.source))
    fingerprints={p:store.fingerprint(p) for p in source_paths}
    job=dict(id=run_id,kind='translate_review',status='running',cancel=threading.Event())
    finished=threading.Event();started=time.monotonic()
    def watch():
        while not finished.wait(2):
            store.atomic_json(root/'progress.json',{k:job.get(k) for k in ('status','phase','done','total','detail')})
    watcher=threading.Thread(target=watch,daemon=True);watcher.start()
    try:
        workflow.run(job,dict(kind='translate_review',paths=source_paths,references=[],pairs={},
            direction=args.direction,combined_output='final',output_dir=str(root/'output'),workers=args.workers,_client=client))
        value=job.get('result') or {};report=value.get('report') or {};records=[]
        store.atomic_json(root/f'{run_id}-result-private.json',value)
        for output in value.get('outputs',[]):
            edits=[dict(index=i,text=f['suggested']) for i,f in enumerate(report.get('findings',[]))
                if f.get('file_path')==output['path'] and f.get('editable') and f.get('suggested') and not f.get('applied')]
            job.update(status='running',phase='export',detail='正在保存并复查校对结果')
            def export_progress(phase,done,total,message):
                job.update(phase='output_check' if phase=='render' else phase,done=done,total=total,detail=message)
            saved=workflow.apply_report(dict(report_id=job['id'],path=output['path'],save_unchanged=True,
                edits=edits if args.apply_suggestions else []),client=client,progress=export_progress)
            store.atomic_json(root/f'{run_id}-{len(records)}-saved-private.json',saved)
            residuals=saved_residuals(saved['output']) if args.direction=='zh-en' else []
            audit=saved.get('output_audit')
            unchanged=store.fingerprint(output['source'])==fingerprints[output['source']]
            passed=bool(output['translation_complete'] and not residuals and unchanged and
                not saved.get('failed') and not saved.get('untranslated') and (audit is None or audit['status']=='complete') and
                (output.get('image_review') is None or output['image_review']['status']=='complete') and
                report.get('stats',{}).get('review_processing_status',report.get('stats',{}).get('model_status'))=='complete')
            if not args.resume and output.get('resumed_segments'):passed=False
            records.append(dict(source=output['source'],output=saved['output'],passed=passed,
                translated=output['translated'],resumed_segments=output['resumed_segments'],
                remaining_chinese=len(residuals) if args.direction=='zh-en' else None,untranslated=saved.get('untranslated',0),
                direction=args.direction,source_unchanged=unchanged,applied=saved['applied_count'],
                image_review=output.get('image_review'),output_audit=audit))
        summary=dict(passed=bool(records) and len(records)==len(source_paths) and all(r['passed'] for r in records) and not requests['blocked'],
            mode='resume' if args.resume else 'fresh',direction=args.direction,records=records,errors=value.get('errors',[]),
            model_requests=requests,seconds=round(time.monotonic()-started,2))
        store.atomic_json(root/f'{run_id}-summary-private.json',summary)
        store.atomic_json(root/'latest-summary-private.json',summary)
        job.update(status='complete' if summary['passed'] else 'partial',phase='complete' if summary['passed'] else 'partial',
            done=len(records),total=len(source_paths),detail='自动验收通过' if summary['passed'] else '自动验收未全部通过，查看机器结果及已保留文件')
        finished.set();watcher.join(4)
        store.atomic_json(root/'progress.json',{k:job.get(k) for k in ('status','phase','done','total','detail')})
        print(json.dumps(dict(passed=summary['passed'],mode=summary['mode'],files=len(records),
            model_requests=requests,seconds=summary['seconds'],evidence=str(root)),ensure_ascii=False))
        return 0 if summary['passed'] else 1
    finally:
        finished.set();watcher.join(4)


if __name__=='__main__':raise SystemExit(main())
