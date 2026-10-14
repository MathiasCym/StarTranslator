"""Background jobs, progress, source identity and safe export of reviewed changes."""
import os
import threading
import uuid
import tempfile
import logging
import shutil
from pathlib import Path
from .extract import extract
from .extract.office import open_office
from .glossary import store
from .matcher import check_segments
from .references import ReferenceIndex
from .translation import translate_file, Cancelled, check_cancel, output_path, OUTPUT_LOCK
from .replacer.run_utils import replace_spans
from .matcher.retriever import _form_pattern
from .models import RunInfo
from .replacer.pptx_package import save_office
from .replacer.pptx_layout import fit_document, capture_layout
from .replacer.text_runs import text_runs
from . import officecli_bridge
from .document_input import validate_document_input
from . import history
from . import task_queue
from .llm.client import LLMClient

JOBS = {}
REPORTS = {}
LOCK = threading.Lock()


def snapshot(job):
    return {k:v for k,v in job.items() if k != 'cancel' and not k.startswith('_')}


def start(data):
    if data.get('kind') not in ('check','translate','translate_review'):
        raise ValueError('任务类型不正确')
    if data.get('combined_output', 'both') not in ('both', 'final'):
        raise ValueError('输出方式不正确')
    if type(data.get('workers',3)) is not int or data.get('workers',3) not in (1,3): raise ValueError('处理速度设置不正确')
    paths = data.get('paths')
    if not isinstance(paths,list) or not paths or len(paths)>100 or any(not isinstance(p,str) for p in paths):
        raise ValueError('请选择 1–100 个文档')
    for path in paths + (data.get('references') or []) + (data.get('glossary_imports') or []):
        validate_document_input(path)
    data = dict(data)
    if data['kind'] != 'check' or data.get('use_llm', True):
        data['_client'] = LLMClient()  # freeze this task's connection before enqueueing
    with LOCK:
        if task_queue.MAINTENANCE:
            raise ValueError('正在校验安装文件，请稍后开始任务。')
        if sum(j['status'] in ('queued','running') for j in JOBS.values()) >= task_queue.MAX_ACTIVE:
            raise ValueError('待处理任务已满，请等待部分任务完成。')
        job = {'id':uuid.uuid4().hex,'kind':data['kind'],'status':'queued','done':0,'total':0,
               'message':'正在排队等待处理','phase':'preparing','percent':0,'result':None,'error':'','cancel':threading.Event(),
               '_history_data':{key:data[key] for key in ('kind','paths','output_dir') if key in data}}
        JOBS[job['id']] = job
        for key in list(JOBS):
            if len(JOBS) <= task_queue.MAX_RETAINED: break
            if JOBS[key]['status'] not in ('queued','running'):
                JOBS.pop(key); REPORTS.pop(key, None)
    try: history.begin(job['id'],data,'queued')
    except Exception: logging.getLogger(__name__).exception('Could not create queued task history')
    def scheduled():
        with LOCK:
            cancelled = job['cancel'].is_set()
            job['status'] = 'running'
        if cancelled:
            try: history.finish({**job,'status':'cancelled'},data)
            except Exception: logging.getLogger(__name__).exception('Could not save cancelled queued task')
            with LOCK:
                job.update(status='cancelled', phase='cancelled', message='已取消排队任务')
            return
        run(job, data)
    with LOCK:
        job['_future'] = task_queue.POOL.submit(scheduled)
    return snapshot(job)


def cancel(job_id):
    """Remove queued work immediately; active work exits through its usual cleanup."""
    with LOCK:
        job = JOBS.get(job_id)
        if job is None: raise ValueError('任务不存在')
        if job['status'] not in ('queued','running'): return snapshot(job)
        job['cancel'].set()
        pending = job.get('_future')
        removed = job['status'] == 'queued' and pending is not None and pending.cancel()
        if removed and not job.get('_cancel_finishing'):
            job['_cancel_finishing'] = True
        else:
            job['message'] = '正在结束任务…'
            return snapshot(job)
    try: history.finish({**job,'status':'cancelled'},job['_history_data'])
    except Exception: logging.getLogger(__name__).exception('Could not save cancelled queued task')
    with LOCK:
        job.update(status='cancelled', phase='cancelled', message='已取消排队任务')
        return snapshot(job)


def error_message(error):
    return str(error).strip() or f'任务遇到未提供说明的错误（{type(error).__name__}）。可导出错误日志排查。'


def run(job,data):
    reviews = []
    outcome = 'failed'
    job.setdefault('kind', data['kind'])
    if data.get('_client') is not None: data['_client'].cancel = job['cancel']
    def progress(done,total,message,phase='check',percent=None):
        with LOCK:
            job.update(done=done,total=total,message=message,phase=phase)
            job['percent'] = max(job.get('percent', 0), percent if percent is not None else 100*done/total if total else 0)
    try: history.begin(job['id'], data)
    except Exception: logging.getLogger(__name__).exception('Could not create local task history')
    try:
        glossary = store.load_glossary(data.get('glossary_imports'))
        references = ReferenceIndex(data.get('references',[]),glossary,data.get('pairs'))
        paths = list(dict.fromkeys(os.path.abspath(p) for p in data['paths']))
        if data['kind'] in ('translate','translate_review'):
            outputs, errors = [], []
            job['result'] = {'outputs':outputs,'errors':errors,'completed_paths':[]}
            for index,path in enumerate(paths):
                check_cancel(job['cancel'])
                job.update(file_index=index+1,file_total=len(paths))
                combined = data['kind'] == 'translate_review'
                fraction = .45 if combined else 1
                progress(0,0,f'翻译 {index+1}/{len(paths)}：{Path(path).name}','translate',100*index/len(paths))
                try:
                    final_only = combined and data.get('combined_output') == 'final'
                    folder = store.data_dir() / 'translation-drafts' / job['id'] if final_only else data.get('output_dir')
                    result = translate_file(path,glossary,references,folder,client=data.get('_client'),cancel=job['cancel'],workers=data.get('workers',3),
                        progress=lambda n,t:progress(n,t,f'翻译 {index+1}/{len(paths)}：{Path(path).name}',
                            'translate',100*(index+fraction*n/max(1,t))/len(paths)))
                    result.update(staged=final_only, output_mode=data.get('combined_output', 'both'),
                                  target_dir=str(Path(data.get('output_dir') or Path(path).parent).absolute()))
                    outputs.append(result)
                    if combined:
                        progress(0,0,f'校对 {index+1}/{len(paths)}：{Path(result["path"]).name}', 'check',100*(index+.45)/len(paths))
                        review = auto_review(result, glossary, references, job['cancel'],
                            lambda n,t,*message:progress(n,t,f'校对 {index+1}/{len(paths)}：{Path(path).name}',
                                'check',100*(index+.45+.45*n/max(1,t))/len(paths)),
                            on_finding=lambda items: job.setdefault('partial_findings', []).extend(items),
                            client=data.get('_client'), workers=data.get('workers',3),on_export=lambda:progress(0,0,f'保存校对结果 {index+1}/{len(paths)}：{Path(path).name}',
                                'export',100*(index+.9)/len(paths)))
                        reviews.append(review)
                        if result['review_status'] == 'complete' and not job['cancel'].is_set():
                            job['result']['completed_paths'].append(path)
                    else:
                        job['result']['completed_paths'].append(path)
                    check_cancel(job['cancel'])
                    progress(1,1,f'已完成 {index+1}/{len(paths)} 个文件','export',100*(index+1)/len(paths))
                except Cancelled:
                    raise
                except Exception as error:
                    logging.getLogger(__name__).exception('Translation failed: %s', Path(path).name)
                    if data['kind'] == 'translate_review' and outputs and outputs[-1].get('source') == path:
                        outputs[-1].update(auto_reviewed=True, review_status='incomplete', status='needs_review')
                        outputs[-1]['needs_review'] = max(1, outputs[-1].get('needs_review', 0))
                        outputs[-1]['warnings'].append({'reason': '自动校对未完成，已保留译文：' + error_message(error), 'text': ''})
                    errors.append({'path':path,'error':error_message(error)})
            job['message'] = ('翻译并校对完成' if data['kind']=='translate_review' else '翻译完成') if not errors else '部分文件未完成'
        else:
            all_segments, files, errors, hashes = [], [], [], {}
            for path in paths:
                check_cancel(job['cancel'])
                try:
                    validate_document_input(path)
                    before = store.fingerprint(path)
                    segments = extract(path)
                    if store.fingerprint(path) != before:
                        raise ValueError('读取期间文件发生变化，请重试')
                    all_segments.extend(segments)
                    hashes[path] = before
                    files.append({'path':path,'name':Path(path).name,'segments':len(segments)})
                except Exception as error:
                    logging.getLogger(__name__).exception('Document read failed: %s', Path(path).name)
                    errors.append({'path':path,'error':error_message(error)})
            if not all_segments:
                raise ValueError('没有可检验的内容。'+'；'.join(e['error'] for e in errors))
            # 发现项随复核进度即时挂到 job 上，前端可在进度条下方陆续展示。
            # 这些同时是任务因故中断时仍可用的部分结果。
            partial = []
            def on_finding(items):
                with LOCK:
                    partial.extend(items)
                    job['partial_findings'] = partial
            findings, stats = check_segments(all_segments,glossary,bool(data.get('use_llm',True)),
                client=data.get('_client'),references=references,progress=progress,cancel=job['cancel'],on_finding=on_finding,workers=data.get('workers',3))
            result = {'report_id':job['id'],'files':files,'errors':errors,'stats':stats,
                      'findings':[f.to_dict() for f in findings],
                      'segments':[s.to_dict() for s in all_segments], 'completed_paths':stats['completed_files']}
            with LOCK:
                REPORTS[job['id']] = {'segments':all_segments,'hashes':hashes,'findings':findings}
                job['result'] = result
                job.pop('partial_findings',None)
            job['message'] = '校对完成' if stats['model_status'] in ('complete','not_requested') else '规则检查已完成，模型复核未完成'
        outcome = ('cancelled' if job['cancel'].is_set() else 'failed'
                   if data['kind'] in ('translate', 'translate_review') and not outputs and errors else 'complete')
    except Cancelled as error:
        outcome = 'cancelled'
        job.update(message=str(error))
    except Exception as error:
        logging.getLogger(__name__).exception('Task failed: %s', job['id'])
        with LOCK:
            partial = job.get('partial_findings') or []
        job.update(error=error_message(error),message='任务未完成')
        if partial and data['kind'] == 'check':
            # 任务中断前已陆续发现问题，保留下来供前端展示。
            job['result'] = {'report_id':job['id'],'files':[],'errors':[],
                             'stats':{'findings':len(partial)},'findings':partial,'segments':[]}
            job['message'] = f'任务未完成，已保留中断前发现的 {len(partial)} 项'
    finally:
        if data['kind'] == 'translate_review' and job.get('result'):
            publish_combined_report(job, reviews, outcome)
        try: history.finish({**job,'status':outcome}, data)
        except Exception:
            logging.getLogger(__name__).exception('Could not save local task history')
        # A final status is observable only after the report and outputs exist.
        with LOCK:
            job.update(status=outcome,phase=outcome)
            if outcome=='complete': job['percent'] = 100


def auto_review(result, glossary, references, cancel, progress, on_finding=None, on_export=None, client=None, workers=3):
    """Produce suggestions; applying any review change requires a user action."""
    check_cancel(cancel)
    translated_path = result['path']
    before = store.fingerprint(translated_path)
    segments = extract(translated_path)
    if store.fingerprint(translated_path) != before:
        raise ValueError('读取期间译文文件发生变化，请重试')
    refs = ReferenceIndex(list(dict.fromkeys([result['source'], *references.by_path])) if references else [result['source']], glossary, {translated_path: result['source']})
    findings, stats = check_segments(segments, glossary, True, client=client, references=refs, cancel=cancel, progress=progress, on_finding=on_finding,workers=workers)
    result.update(auto_reviewed=True, review_status=stats['model_status'], corrected=0, translation_path=translated_path)
    result['review_exported'] = False
    if on_export and not cancel.is_set(): on_export()
    result['warnings'] += [{'reason': warning, 'text': ''} for warning in stats['warnings']]
    result['needs_review'] = len(result['review_items']) + (1 if stats['model_status'] != 'complete' else 0)
    result['status'] = 'needs_review' if result['needs_review'] else 'complete'
    # Continue manual edits against the final English output, never the Chinese source.
    final = result['path']
    for segment in segments: segment.file_path = final; segment.file = Path(final).name
    for finding in findings: finding.file_path = final; finding.file = Path(final).name
    return {'local': {'segments':segments,'hashes':{final:store.fingerprint(final)},'findings':findings},
            'stats':stats,'output':result}


def publish_combined_report(job, reviews, outcome):
    result = job['result']
    local = {'segments':[],'hashes':{},'findings':[], 'output_options':{}}
    stats = {key:sum(r['stats'].get(key,0) for r in reviews) for key in
             ('segments','rule_hits','consistency_hits','llm_hits','judged','errors','unreviewed','truncated','unsupported')}
    errors = result.get('errors',[]) + [{'path':r['output']['source'],'error':r['output']['review_error']}
        for r in reviews if r['output'].get('review_error')]
    if job.get('error'): errors.append({'error':job['error']})
    states = [r['stats']['model_status'] for r in reviews]
    stats['model_status'] = 'cancelled' if outcome=='cancelled' else (
        'unavailable' if not reviews or all(s=='unavailable' for s in states) else 'partial' if errors or any(s!='complete' for s in states) else 'complete')
    stats['warnings'] = [warning for r in reviews for warning in r['stats']['warnings']]
    files = []
    for review in reviews:
        block, output = review['local'], review['output']
        local['segments'].extend(block['segments']); local['findings'].extend(block['findings']); local['hashes'].update(block['hashes'])
    for output in result.get('outputs',[]):
        local['hashes'].setdefault(output['path'],store.fingerprint(output['path']))
        local['output_options'][output['path']] = {'mode':output.get('output_mode','both'),
            'comparison_id':output.get('comparison_id'),
            'source':output['source'], 'target_dir':output['target_dir'], 'staged':output.get('staged',False)}
    checked = {r['output']['path']:len(r['local']['segments']) for r in reviews}
    files = [{'path':o['path'],'name':Path(o['path']).name,'source':o['source'],'segments':checked.get(o['path'],0),'review_available':o['path'] in checked}
             for o in result.get('outputs',[])]
    stats['findings'] = len(local['findings'])
    public = {'kind':'translate_review','report_id':job['id'],'files':files,'errors':errors,'stats':stats,
        'output_mode':next((o.get('output_mode') for o in result.get('outputs',[])), 'both'),
        'findings':[f.to_dict() for f in local['findings']], 'segments':[s.to_dict() for s in local['segments']]}
    with LOCK:
        REPORTS[job['id']] = local
        result.update(report=public,stats=stats)
    job.pop('partial_findings',None)
    if outcome=='complete' and (errors or stats['model_status']!='complete'):
        job['message'] = '翻译并校对已结束，部分内容未完成'


def apply_report(data):
    with LOCK:
        if task_queue.MAINTENANCE: raise ValueError('正在校验安装文件，请稍后保存。')
        report = REPORTS.get(data.get('report_id'))
        if report:
            export_lock = report.setdefault('export_lock', threading.Lock())
    if not report:
        raise ValueError('报告已过期，请重新校对。')
    with LOCK:
        if task_queue.MAINTENANCE: raise ValueError('正在校验安装文件，请稍后保存。')
        task_queue.ACTIVE_EXPORTS += 1
    try:
        with export_lock, OUTPUT_LOCK:
            result = _apply_report(data, report)
            option = report.get('output_options',{}).get(data['path'],{})
            source = option.get('source',data['path'])
            try: history.exported(data['report_id'], source, result['output'], result['applied_count'], result['failed'], result['overwritten'],option.get('comparison_id'))
            except Exception: logging.getLogger(__name__).exception('Could not save export history')
            return result
    finally:
        with LOCK: task_queue.ACTIVE_EXPORTS -= 1


def _apply_report(data, report):
    overwrite = data.get('overwrite') is True
    path = os.path.abspath(data.get('path') or '')
    if overwrite and Path(path).suffix.lower() == '.pdf':
        raise ValueError('PDF 的处理结果保存为 Word，不能覆盖原 PDF。请使用另存。')
    option = report.get('output_options',{}).get(path,{})
    final_only = option.get('mode') == 'final'
    managed_output = bool(option)
    if path not in report['hashes'] or store.fingerprint(path)!=report['hashes'][path]:
        raise ValueError('原文件与检验时不一致，请重新校对后再导出。')
    input_path = report.get('working_paths', {}).get(path, path)
    input_hash = report.get('working_hashes', {}).get(path, report['hashes'][path])
    if store.fingerprint(input_path) != input_hash:
        raise ValueError('上次输出文件已被修改，请重新校对后继续替换。')
    edits = {}
    for item in data.get('edits', []):
        if not isinstance(item, dict) or type(item.get('index')) is not int or not isinstance(item.get('text'), str) or not item['text'].strip() or len(item['text']) > 12000:
            raise ValueError('请填写有效的替换文本。')
        index = item['index']
        if index < 0 or index >= len(report['findings']): raise ValueError('建议不存在。')
        finding = report['findings'][index]
        if finding.file_path != path or not finding.editable or finding.applied: raise ValueError('该项建议不可替换。')
        if any(ord(c) < 32 and c not in '\n\t\r' for c in item['text']): raise ValueError('替换文本含有无效字符。')
        edits[index] = item['text'].strip()
    selected = data.get('selected',{})
    if not isinstance(selected, dict): raise ValueError('替换选项格式不正确。')
    if edits:
        selected = {}
        for index, text in edits.items():
            finding = report['findings'][index]
            selected.setdefault(finding.segment_id, []).append([finding.found_text, text])
    segments = {s.id:s for s in report['segments'] if s.file_path==path}
    from .document_context import DocumentContext
    page_context = DocumentContext(list(segments.values()))
    document, paragraphs, _ = open_office(input_path)
    para_map = {loc:para for loc,para,*_ in paragraphs}
    done, failed, changed_locators, applied_indices = [], [], [], set()
    is_pptx = Path(path).suffix.lower() == '.pptx'
    original_layout = capture_layout(document,[s.locator for s in segments.values()]) if is_pptx else None
    baseline = officecli_bridge.inspect(input_path) if is_pptx else None
    for segment_id,pairs in selected.items():
        segment = segments.get(segment_id)
        if not segment or not segment.editable:
            failed.append({'segment_id':segment_id,'reason':'段落不存在或不可自动改写'})
            continue
        paragraph = para_map.get(segment.locator)
        spans = []
        for old,new in pairs:
            if not old or not isinstance(new,str) or not new:
                continue
            choice = next(((i, f) for i, f in enumerate(report['findings']) if f.file_path==path and f.segment_id==segment_id and f.found_text==old and edits.get(i, f.suggested)==new),None)
            if choice is None:
                raise ValueError('替换内容不属于当前报告，请重新校对。')
            finding_index, finding = choice
            if finding.applied:
                raise ValueError('这项改正已应用到原文件，无需重复覆盖。')
            if (finding.method == 'llm' and new == finding.suggested and not finding.numeric_addition_verified
                    and page_context.duplicates_neighbor_number(segment, old, new)):
                failed.append({'segment_id':segment_id,'index':finding_index,
                               'reason':'这条建议会重复补入相邻文字已有的数字，已跳过；请结合上下文修改建议。'})
                continue
            import re
            pattern = _form_pattern(old) if finding.method in ('rule', 'consistency') else re.compile(re.escape(old),re.I)
            matches = list(pattern.finditer(segment.text))
            if any(match.start()<b and match.end()>a for match in matches for a,b,_ in spans):
                failed.append({'segment_id':segment_id,'index':finding_index,'reason':'替换范围重叠，请分别选择改正项'})
                continue
            if matches:
                spans.extend((match.start(),match.end(),new) for match in matches)
                applied_indices.add(finding_index)
        if paragraph is None or paragraph.text != segment.text:
            failed.append({'segment_id':segment_id,'reason':'段落定位或内容发生变化'})
            continue
        replace_spans(text_runs(paragraph),spans)
        if spans:
            changed_locators.append(segment.locator)
        done.extend({'segment_id':segment_id,'old':segment.text[a:b],'new':n} for a,b,n in spans)
    if not done and not (data.get('save_unchanged') is True and (option or not report['findings'])):
        raise ValueError(failed[0]['reason'] if failed else '没有可应用的替换，未生成输出文件。')
    if store.fingerprint(path)!=report['hashes'][path]:
        raise ValueError('导出前原文件已变化，请重新校对。')
    if store.fingerprint(input_path) != input_hash:
        raise ValueError('上次输出文件已被修改，请重新校对后继续替换。')
    layout_adjustments, fitting_warnings = fit_document(document,changed_locators,original_layout) if is_pptx else ([],[])
    if not overwrite or managed_output:
        out = Path(option['output']) if managed_output and option.get('output') else output_path(
            option.get('source',path) if final_only else path,
            option.get('target_dir') if managed_output else data.get('output_dir'),'English_checked' if final_only else 'checked',
            extension=Path(input_path).suffix if final_only else None)
        existing_hash = store.fingerprint(out) if out.exists() else None
        if existing_hash and store.fingerprint(out) != input_hash:
            raise ValueError('上次输出文件已被修改，请重新校对后继续替换。')
        fd, temporary = tempfile.mkstemp(prefix='.star-review-',suffix=out.suffix,dir=out.parent)
        os.close(fd)
        try:
            if done or Path(input_path).suffix.lower() == '.pdf': save_office(input_path,document,temporary,changed_locators)
            else: shutil.copyfile(input_path,temporary)
            layout_warnings = fitting_warnings + (officecli_bridge.compare(baseline,officecli_bridge.inspect(temporary)) if is_pptx else [])
            if store.fingerprint(path) != report['hashes'][path]:
                raise ValueError('导出时原文件已变化，请重新校对。')
            if store.fingerprint(input_path) != input_hash:
                raise ValueError('上次输出文件已被修改，请重新校对后继续替换。')
            if existing_hash and store.fingerprint(out) != existing_hash:
                raise ValueError('上次输出文件已被修改，请重新校对后继续替换。')
            if not existing_hash and out.exists():
                raise ValueError('输出位置已有新文件，请重试。')
            os.replace(temporary,out)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        output = str(out)
        overwrite = bool(existing_hash)
        if managed_output: option['output'] = output
    # Finish the new document first, then atomically replace the original.
    # The temporary file is removed; no backup is retained.
    else:
        source = Path(path)
        fd, temporary = tempfile.mkstemp(prefix='.star-review-', suffix=source.suffix, dir=source.parent)
        os.close(fd)
        try:
            save_office(input_path,document,temporary,changed_locators)
            layout_warnings = fitting_warnings + (officecli_bridge.compare(baseline,officecli_bridge.inspect(temporary)) if is_pptx else [])
            def guard_original():
                if store.fingerprint(path) != report['hashes'][path]:
                    raise ValueError('覆盖前原文件已变化，请重新校对。')
                if store.fingerprint(input_path) != input_hash:
                    raise ValueError('上次输出文件已被修改，请重新校对后继续替换。')
            from .atomic_file import replace_checked
            replace_checked(temporary,path,guard_original)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        output = path
    # Keep the remaining reviewed choices usable against the updated document.
    # This only updates the report snapshot; it does not run a new check/model.
    report['hashes'][path] = store.fingerprint(path)
    report.setdefault('working_paths', {})[path] = output
    report.setdefault('working_hashes', {})[path] = store.fingerprint(output)
    if option.get('comparison_id'):
        try:
            from . import comparison
            comparison.update(option['comparison_id'], output)
        except Exception:
            logging.getLogger(__name__).exception('Could not refresh text comparison')
    changed = {item['segment_id'] for item in done}
    for segment_id in changed:
        segment = segments[segment_id]
        paragraph = para_map[segment.locator]
        segment.text = paragraph.text
        segment.runs = [RunInfo(run.text, index) for index, run in enumerate(text_runs(paragraph))]
    updates = []
    for index, finding in enumerate(report['findings']):
        if finding.file_path != path:
            continue
        if finding.segment_id in changed:
            finding.context = page_context.report_context(segments[finding.segment_id])
            if index in applied_indices:
                finding.applied = True
                finding.suggested = edits.get(index, finding.suggested)
                finding.editable = False
                finding.not_editable_reason = '已替换并保存。'
            elif not finding.applied:
                import re
                pattern = _form_pattern(finding.found_text) if finding.method == 'rule' else re.compile(re.escape(finding.found_text), re.I)
                if not pattern.search(segments[finding.segment_id].text):
                    finding.editable = False
                    finding.not_editable_reason = '原文已被本次改正更新。'
        updates.append({'index':index,'finding':finding.to_dict()})
    return {'output':output,'report_path':path,'applied_count':len(done),'failed':failed,'overwritten':overwrite,'finding_updates':updates,
            'layout_warnings':layout_warnings,'layout_adjustments':layout_adjustments,'layout_checked':is_pptx}
