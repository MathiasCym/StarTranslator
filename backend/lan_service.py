"""Optional LAN gateway. Only upload/job/result APIs are exposed, never desktop APIs."""
import ipaddress
import json
import logging
import os
import secrets
import shutil
import socket
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, send_file
from werkzeug.serving import make_server, WSGIRequestHandler
from . import workflow, task_queue, comparison
from .glossary import store
from .document_input import validate_document_input

SERVICE_LOCK = threading.RLock()
SERVER = None
SESSIONS = {}
COOKIE = 'star_lan_session'
ROOT = Path(__file__).resolve().parents[1] / 'renderer' / 'shared'
MAX_FILE = 150 * 1024 * 1024
MAX_STORAGE = 2 * 1024 * 1024 * 1024


def addresses():
    values = {'127.0.0.1'}
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if ipaddress.ip_address(address).is_private: values.add(address)
    except OSError: pass
    return sorted(values, key=lambda x:x == '127.0.0.1')


def status():
    with SERVICE_LOCK:
        return {'enabled':SERVER is not None, 'port':SERVER.server_port if SERVER else None,
            'addresses':[f'http://{a}:{SERVER.server_port}' for a in addresses()] if SERVER else [],
            'sessions':len(SESSIONS), 'parallel_tasks':2, 'parallel_requests':4}


def configure(enabled, port=8765):
    global SERVER
    with SERVICE_LOCK:
        if not enabled:
            if SERVER:
                old, SERVER = SERVER, None
                # Existing work continues; service resumes with the same sessions.
                old.shutdown(); old.server_close()
            return status()
        if task_queue.MAINTENANCE: raise ValueError('正在校验安装文件，请稍后开启共享。')
        if SERVER: return status()
        if type(port) is not int or not 1024 <= port <= 65535: raise ValueError('端口应为 1024–65535')
        try:
            class Quiet(WSGIRequestHandler):
                def log_request(self, code='-', size='-'): pass
            server = make_server('0.0.0.0',port,create_app(),threaded=True,request_handler=Quiet)
        except OSError as error: raise ValueError('共享服务未能启动，请更换端口或检查网络设置。') from error
        SERVER = server
        threading.Thread(target=server.serve_forever, name='star-lan',daemon=True).start()
        return status()


def base_dir():
    return store.data_dir() / 'shared-service'


def persist(session):
    store.atomic_json(base_dir() / session['id'] / 'session.json', session)


def session_for_request(create=False):
    token = request.cookies.get(COOKIE, '')
    if len(token) == 64 and all(c in '0123456789abcdef' for c in token):
        session = SESSIONS.get(token)
        if session is None:
            file = base_dir() / token / 'session.json'
            if file.is_file():
                session = json.loads(file.read_text(encoding='utf-8')); SESSIONS[token] = session
        if session: return session
    if not create: raise ValueError('请刷新页面后重试。')
    token = secrets.token_hex(32)
    session = {'id':token, 'csrf':secrets.token_hex(32), 'jobs':[], 'created':time.time()}
    with SERVICE_LOCK:
        if len(SESSIONS) >= 200: raise ValueError('当前使用人数较多，请稍后重试。')
        SESSIONS[token] = session
        persist(session)
    return session


def owned_job(job_id):
    session = session_for_request()
    if job_id not in session['jobs']: raise ValueError('任务不存在。')
    with workflow.LOCK:
        job = workflow.JOBS.get(job_id)
    if not job:
        from . import history
        row=history.record(job_id)
        state='interrupted' if row['status'] in ('running','queued') else row['status']
        job={'id':job_id,'kind':row['kind'],'status':state,'phase':state,'percent':100 if state=='complete' else 0,
             'message':'共享服务已重启，本机记录和断点保留。','archived':True,
             'resume_pending':row.get('can_resume',state in ('interrupted','partial','failed','cancelled')),
             'restore_report':row.get('awaiting_confirmation',False),
             'result':{'outputs':row.get('outputs',[]),'errors':row.get('errors',[])},'error':''}
    return job


def report_of(job):
    result = job.get('result') or {}
    return result.get('report') or (result if result.get('report_id') else {})


def download_files(job):
    result = job.get('result') or {}
    files = [o['path'] for o in result.get('outputs',[]) if not o.get('staged')]
    local = workflow.REPORTS.get(job['id']) or {}
    files += list(local.get('working_paths',{}).values())
    return list(dict.fromkeys(path for path in files if Path(path).is_file()))


def clean(value):
    # File system identifiers remain private to the host. Models/keys are never in job data.
    if isinstance(value, dict):
        return {k:(Path(v).name if k in ('path','source','file_path','output_path','report_path') and isinstance(v,str) else clean(v))
                for k,v in value.items() if not k.startswith('_') and k not in ('target_dir','output_dir','translation_path','output_hash')}
    if isinstance(value,list): return [clean(v) for v in value]
    return value


def public(job):
    value = clean(workflow.snapshot(job))
    working = (workflow.REPORTS.get(job['id']) or {}).get('working_paths',{})
    for raw,output in zip((job.get('result') or {}).get('outputs',[]),(value.get('result') or {}).get('outputs',[])):
        saved=working.get(raw.get('path'))
        output['draft']=job.get('kind')=='translate_review' and not raw.get('review_exported')
        if saved and Path(saved).is_file(): output.update(path=Path(saved).name,staged=False,draft=False)
    raw_report = report_of(job)
    report = report_of(value)
    paths = [f['path'] for f in raw_report.get('files',[])]
    outputs=(job.get('result') or {}).get('outputs',[])
    for raw,file in zip(raw_report.get('files',[]),report.get('files',[])):
        file['comparison_index']=next((i for i,o in enumerate(outputs) if o.get('path')==raw['path'] and o.get('comparison_id')),None)
    for original, finding in zip(raw_report.get('findings',[]), report.get('findings',[])):
        finding['file_index'] = paths.index(original['file_path']) if original.get('file_path') in paths else -1
    # A saved browser session can revisit any of its retained tasks and reports.
    value['downloads'] = [{'index':i, 'name':Path(p).name} for i,p in enumerate(download_files(job))]
    resumable=job.get('can_resume')
    if type(resumable) is not bool:
        result={**(job.get('result') or {}),'stats':raw_report.get('stats') or (job.get('result') or {}).get('stats',{})}
        resumable=job.get('resume_pending') or job['status']=='interrupted' or workflow.can_resume_processing({**job,'result':result},job['status'])
    value['can_resume'] = job['status'] not in ('queued','running') and bool(resumable)
    value['can_restore_report'] = bool(job.get('archived') and job.get('restore_report'))
    return value


def save_upload(file, folder):
    name = (file.filename or '').replace('\\','/').split('/')[-1]
    if not name or len(name) > 180 or any(c in name for c in '<>:"|?*') or name.startswith('~$'):
        raise ValueError('请选择正式文档，不能使用临时锁定文件。')
    from .formats import SUPPORTED, archive_check
    if Path(name).suffix.lower() not in SUPPORTED: raise ValueError('不支持此文档格式。')
    path = folder / uuid.uuid4().hex / name
    path.parent.mkdir(parents=True,exist_ok=True)
    size = 0
    with path.open('xb') as target:
        while chunk := file.stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE: raise ValueError('单个文档不能超过 150 MB。')
            target.write(chunk)
    validate_document_input(str(path))
    if path.suffix.lower() in {'.docx','.pptx','.xlsx','.epub'}:
        try:
            with zipfile.ZipFile(path) as archive: archive_check(archive)
        except zipfile.BadZipFile as error:
            raise ValueError('文档不完整，请确认能够正常打开后再上传。') from error
    return str(path)


def create_app(testing=False):
    app = Flask('star-shared',static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=300 * 1024 * 1024, TESTING=testing)

    @app.before_request
    def guard():
        try:
            host = urlsplit('http://' + request.host).hostname
            if host not in addresses() and host != 'localhost': return jsonify(error='共享地址无效'),400
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'): return jsonify(error='请从共享页面操作'),403
            if request.method not in ('GET','HEAD'):
                session = session_for_request()
                if not secrets.compare_digest(request.headers.get('X-Star-CSRF',''),session['csrf']):
                    return jsonify(error='请刷新共享页面后重试'),403
        except ValueError as error: return jsonify(error=str(error)),400

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if 'Content-Security-Policy' not in response.headers:
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(Exception)
    def failure(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException): return jsonify(error='请求未完成，请检查文件大小或刷新页面。'),error.code
        if not isinstance(error,ValueError): logging.getLogger(__name__).exception('LAN request failed')
        return jsonify(error=str(error) if isinstance(error,ValueError) else '共享操作未完成，请在共享电脑导出诊断日志。'),400

    @app.get('/')
    def index(): return send_file(ROOT / 'index.html')

    @app.get('/assets/<name>')
    def asset(name):
        if name not in ('app-icon.png','normal.png','happy.png','sad.png'): return '',404
        return send_file(ROOT.parent / 'assets' / name)

    @app.get('/shared.js')
    def script(): return send_file(ROOT / 'shared.js')

    @app.get('/translation-options.js')
    def translation_options_script(): return send_file(ROOT / 'translation-options.js')

    @app.get('/shared.css')
    def style(): return send_file(ROOT / 'shared.css')

    @app.get('/text-translation.<extension>')
    def text_widget(extension):
        if extension not in ('css', 'js'): return '', 404
        return send_file(ROOT / ('text-translation.' + extension))

    @app.post('/shared/text/jobs')
    def start_text():
        session = session_for_request()
        data = request.get_json(force=True) or {}
        if data.get('retry_of') and data['retry_of'] not in session.get('text_jobs', []):
            raise ValueError('任务不存在。')
        # No remote model configuration or local paths accepted.
        job = workflow.start({key: data[key] for key in ('text', 'direction', 'retry_of') if key in data} | {'kind': 'text'})
        with SERVICE_LOCK:
            session.setdefault('text_jobs', []).append(job['id'])
            session['text_jobs'] = session['text_jobs'][-task_queue.MAX_RETAINED:]
            persist(session)
        return jsonify(job)

    def owned_text(job_id):
        if job_id not in session_for_request().get('text_jobs', []): raise ValueError('任务不存在。')
        with workflow.LOCK:
            job = workflow.JOBS.get(job_id)
            if not job or job.get('kind') != 'text': raise ValueError('文本任务已清理，请重新输入。')
            return workflow.snapshot(job)

    @app.get('/shared/text/jobs/<job_id>')
    def text_status(job_id): return jsonify(owned_text(job_id))

    @app.post('/shared/text/jobs/<job_id>/cancel')
    def cancel_text(job_id):
        owned_text(job_id)
        workflow.cancel(job_id)
        return jsonify(ok=True)

    @app.get('/form-controls.css')
    def form_controls_style(): return send_file(ROOT / 'form-controls.css')

    @app.get('/progress.css')
    def progress_style(): return send_file(ROOT / 'progress.css')

    @app.get('/report.css')
    def report_style(): return send_file(ROOT / 'report.css')

    @app.get('/comparison-view.<extension>')
    def comparison_widget(extension):
        if extension not in ('css','js'): return '',404
        return send_file(ROOT/('comparison-view.'+extension))

    @app.get('/shared/session')
    def init():
        session = session_for_request(True)
        response = jsonify(csrf=session['csrf'], parallel_tasks=2, parallel_requests=4,
            jobs=session['jobs'], maximum_file_mb=150)
        response.set_cookie(COOKIE,session['id'],httponly=True,samesite='Strict',max_age=30*86400)
        return response

    @app.get('/shared/jobs')
    def jobs():
        session = session_for_request()
        values=[]
        for ident in reversed(session['jobs']):
            try:values.append(public(owned_job(ident)))
            except ValueError:continue
        return jsonify(jobs=values)

    @app.post('/shared/jobs')
    def start():
        session = session_for_request()
        data = json.loads(request.form.get('options','{}'))
        if data.get('kind') not in ('translate','check','translate_review'): raise ValueError('请选择任务类型')
        # Only allow explicit options; host paths/model settings cannot be supplied remotely.
        files, refs = request.files.getlist('files'),request.files.getlist('references')
        if not 1 <= len(files) <= 30 or len(refs)>30: raise ValueError('每次请选择 1–30 份材料。')
        with SERVICE_LOCK:
            root = base_dir()
            used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) if root.exists() else 0
            if used + (request.content_length or 0) > MAX_STORAGE: raise ValueError('共享空间已满，请联系共享电脑的使用者清理历史文件。')
            folder = root / session['id'] / uuid.uuid4().hex
            try:
                paths = [save_upload(f,folder/'input') for f in files]
                references = [save_upload(f,folder/'reference') for f in refs]
                job = workflow.start({'kind':data['kind'], 'paths':paths, 'references':references,
                    'output_dir':str(folder/'output'), 'use_llm':data.get('use_llm',True) is True,
                    'workers':data.get('workers',3),'translation_mode':data.get('translation_mode','faithful'),'direction':data.get('direction','zh-en'),
                    'combined_output':data.get('combined_output','both')})
                session['jobs'].append(job['id'])
                session.setdefault('folders',{})[job['id']] = str(folder)
                try: persist(session)
                except OSError: logging.getLogger(__name__).exception('Could not persist shared session; accepted work is retained')
                return jsonify(public(workflow.JOBS[job['id']]))
            except Exception:
                # This resolved UUID folder is the only directory created by this request.
                if folder.is_relative_to(root) and folder.exists(): shutil.rmtree(folder)
                raise

    @app.get('/shared/jobs/<job_id>')
    def job(job_id): return jsonify(public(owned_job(job_id)))

    @app.post('/shared/jobs/<job_id>/cancel')
    def cancel(job_id):
        owned_job(job_id)
        workflow.cancel(job_id)
        return jsonify(ok=True)

    @app.post('/shared/jobs/<job_id>/resume')
    def resume(job_id):
        from . import history
        session=session_for_request();job=owned_job(job_id)
        if job['status'] in ('queued','running'):raise ValueError('该任务仍在处理中。')
        with SERVICE_LOCK:
            root=(base_dir()/session['id']).resolve()
            folder=Path(session.get('folders',{}).get(job_id,'')).resolve()
            if folder==root or not folder.is_relative_to(root) or not folder.is_dir():
                raise ValueError('原任务材料已清理，请重新上传。')
            data=history.resume_options(job_id)
            for path in [*data.get('paths',[]),*data.get('references',[]),*data.get('glossary_imports',[])]:
                if not Path(path).resolve().is_relative_to(folder):raise ValueError('无法确认原任务材料的位置。')
            data['output_dir']=str(folder/'output')
            restored=workflow.start(data)
            session['jobs'].append(restored['id']);session['folders'][restored['id']]=str(folder);persist(session)
            return jsonify(public(workflow.JOBS[restored['id']]))

    @app.post('/shared/jobs/<job_id>/apply')
    def apply(job_id):
        job = owned_job(job_id)
        if task_queue.MAINTENANCE: raise ValueError('共享电脑正在校验安装文件，请稍后保存。')
        data = request.get_json(force=True) or {}
        files = report_of(job).get('files',[])
        index = data.get('file_index')
        if type(index) is not int or not 0 <= index < len(files): raise ValueError('文档不存在。')
        path = files[index]['path']
        folder = Path(path).parents[2] / 'output' if '/input/' in path.replace('\\','/') else Path(path).parent
        result = workflow.apply_report({'report_id':job_id,'path':path,'edits':data.get('edits',[]),
            'save_unchanged':data.get('save_unchanged') is True,'output_dir':str(folder)})
        report = report_of(job)
        for update in result['finding_updates']: report['findings'][update['index']] = update['finding']
        return jsonify(public(job))

    @app.post('/shared/jobs/<job_id>/exports')
    def start_export(job_id):
        from . import report_exports
        job=owned_job(job_id);data=request.get_json(force=True) or {}
        files=report_of(job).get('files',[]);index=data.get('file_index')
        if type(index) is not int or not 0<=index<len(files):raise ValueError('文档不存在。')
        path=files[index]['path']
        folder=Path(path).parents[2]/'output' if '/input/' in path.replace('\\','/') else Path(path).parent
        task=report_exports.start({'report_id':job_id,'path':path,'edits':data.get('edits',[]),
            'save_unchanged':data.get('save_unchanged') is True,'output_dir':str(folder)})
        return jsonify({k:task[k] for k in ('id','status','phase','done','total','message','error')})

    @app.get('/shared/jobs/<job_id>/exports/<export_id>')
    def export_status(job_id,export_id):
        from . import report_exports
        job=owned_job(job_id);task=report_exports.read(export_id,job_id)
        if task['status']=='complete':
            report=report_of(job)
            for update in task['result']['finding_updates']:report['findings'][update['index']]=update['finding']
        return jsonify({k:task[k] for k in ('id','status','phase','done','total','message','error')})

    @app.get('/shared/jobs/<job_id>/download/<int:index>')
    def download(job_id,index):
        files = download_files(owned_job(job_id))
        if index >= len(files): raise ValueError('输出文件不存在。')
        return send_file(files[index],as_attachment=True,download_name=Path(files[index]).name)

    @app.get('/shared/jobs/<job_id>/comparison/<int:index>')
    def compare(job_id,index):
        outputs = (owned_job(job_id).get('result') or {}).get('outputs',[])
        if index >= len(outputs) or not outputs[index].get('comparison_id'): raise ValueError('对照尚未生成。')
        return jsonify(clean(comparison.read(outputs[index]['comparison_id'])))

    @app.get('/shared/jobs/<job_id>/comparison/<int:index>/preview/<side>')
    def compare_preview(job_id,index,side):
        outputs=(owned_job(job_id).get('result') or {}).get('outputs',[])
        if index>=len(outputs) or not outputs[index].get('comparison_id'): raise ValueError('对照尚未生成。')
        from .document_preview import response
        return response(outputs[index]['comparison_id'],side,shared=True)

    @app.get('/shared/jobs/<job_id>/diagnostics')
    def diagnostics(job_id):
        job = owned_job(job_id)
        data = {'task_id':job_id,'kind':job['kind'],'status':job['status'],
            'message':job['message'],'error':job.get('error',''),
            'errors':clean((job.get('result') or {}).get('errors',[])),
            'stats':(job.get('result') or {}).get('stats',{}),
            'note':'仅包含本次任务的状态和错误信息，不包含文档正文或模型密钥。'}
        import io
        return send_file(io.BytesIO(json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')),
            as_attachment=True,download_name='StarTranslator-task-'+job_id[:8]+'.json',mimetype='application/json')

    @app.post('/shared/jobs/<job_id>/cleanup')
    def cleanup(job_id):
        job = owned_job(job_id); session = session_for_request()
        with workflow.LOCK:
            if task_queue.ACTIVE_EXPORTS or task_queue.MAINTENANCE or job['status'] in ('queued','running'):
                raise ValueError('任务或保存尚未结束，请稍后清理。')
            local = workflow.REPORTS.get(job_id)
            export_lock = local.setdefault('export_lock',threading.Lock()) if local else threading.Lock()
        with export_lock, SERVICE_LOCK:
            path = Path(session.get('folders',{}).get(job_id,''))
            root = (base_dir()/session['id']).resolve()
            if not path.is_absolute() or not path.resolve().is_relative_to(root) or path.resolve() == root:
                raise ValueError('无法确认任务文件位置，未删除。')
            aliases=[ident for ident,location in session.get('folders',{}).items()
                     if ident!=job_id and Path(location).resolve()==path.resolve()]
            if not aliases:
                from .checkpoints import forget_under
                forget_under(path)
                if path.exists(): shutil.rmtree(path)
            for output in (job.get('result') or {}).get('outputs',[]):
                if output.get('comparison_id'):
                    target = comparison.folder()/(output['comparison_id']+'.json')
                    if target.is_file(): comparison.remove(output['comparison_id'])
            with workflow.LOCK:
                workflow.JOBS.pop(job_id,None);workflow.REPORTS.pop(job_id,None)
            session['jobs'].remove(job_id);session['folders'].pop(job_id,None);persist(session)
        return jsonify(ok=True)

    return app
