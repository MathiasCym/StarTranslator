"""Read-only full-page OfficeCLI previews, isolated from the app and model workflow."""
import html as escaping
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from lxml import html
from flask import Response
from . import comparison, officecli_bridge
from .glossary import store

SLOTS=threading.BoundedSemaphore(2)
LOCK=threading.RLock()
RENDER_LOCKS={}
MAX_HTML=64*1024*1024
PREVIEW_FORMAT='pages-4'
CSP="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
FRAME_SCRIPT=r'''
(()=>{
const channel='star-page-preview',token=new URLSearchParams(location.search).get('preview_token');let pages=[],zoom='fit',muteUntil=0,ready=false,timer,currentPage=0;
function send(data){parent.postMessage({channel,token,...data},'*')}
function list(){return [...document.querySelectorAll('.slide-container,.page-wrapper')].filter(p=>p.querySelector('.slide,.page'))}
function scale(){
 pages=list();
 currentPage=Math.max(0,Math.min(pages.length-1,currentPage));
 pages.forEach((w,i)=>{w.hidden=i!==currentPage});
 pages.forEach(w=>{if(w.hidden)return;const p=w.querySelector('.slide,.page'),width=p.offsetWidth,height=p.scrollHeight;
  const factor=zoom==='fit'?Math.min(1,Math.max(.05,(document.documentElement.clientWidth-24)/width)):Number(zoom)||1;
  p.style.transformOrigin='top left';p.style.transform='scale('+factor+')';
  w.style.width=width*factor+'px';w.style.height=height*factor+'px';w.style.minHeight='0';
 });
 if(pages.length){send({type:'ready',total:pages.length});ready=true;position()}
}
function position(){
 if(!ready)return;
 const p=pages[currentPage],fraction=Math.max(0,Math.min(1,(scrollY-p.offsetTop)/Math.max(1,p.offsetHeight)));
 send({type:'position',page:currentPage+1,fraction,command:Date.now()<muteUntil})
}
addEventListener('message',e=>{
 if(e.source!==parent||e.data?.channel!==channel||e.data.token!==token)return;
 const d=e.data;
 if(d.type==='zoom'){zoom=['fit','1','1.25','1.5','2'].includes(d.value)?d.value:'fit';muteUntil=Date.now()+350;scale()}
 if(d.type==='goto'&&pages.length){const i=Math.max(0,Math.min(pages.length-1,Math.round(Number(d.page)||1)-1));
  muteUntil=Date.now()+500;currentPage=i;scale();scrollTo(scrollX,pages[i].offsetTop+Math.max(0,Math.min(1,Number(d.fraction)||0))*pages[i].offsetHeight);position()}
});
addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(position,70)},{passive:true});
addEventListener('resize',()=>setTimeout(scale,180));
addEventListener('load',async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode().catch(()=>{})));setTimeout(scale,350);setTimeout(scale,1100)});
new MutationObserver(()=>{clearTimeout(timer);timer=setTimeout(scale,180)}).observe(document.body,{childList:true,subtree:true});
})();
'''
FRAME_CSS='''
html{height:auto!important;overflow:auto!important;background:#071422!important;scroll-behavior:auto!important}
body{display:block!important;height:auto!important;min-height:100vh;overflow:visible!important;padding:12px!important;background:#071422!important;margin:0!important}
.sidebar,.page-counter,.file-title,.slide-label,.slide-notes,.nav-bar,.toolbar,.zoom-controls{display:none!important}
.main{display:block!important;overflow:visible!important;padding:0!important;height:auto!important}
.slide-container,.page-wrapper{display:block!important;position:relative!important;margin:0 auto 18px!important;flex:none!important;overflow:hidden!important;transition:none!important}
.slide-wrapper{display:block!important;width:100%!important;height:100%!important}
.slide,.page{margin:0!important;transition:none!important;flex:none!important;transform-origin:top left!important}
a{pointer-events:none!important;color:inherit!important;text-decoration:inherit!important}
[hidden]{display:none!important}
'''


def prepare(raw,kind):
    dom=html.fromstring(raw)
    # Inline renderer scripts from the pinned compiler run only in an opaque,
    # network-free sandbox. PPT uses our page sizing; Word keeps its pagination.
    for node in list(dom.xpath('//script')):
        if kind=='.pptx' or node.get('src') or node.get('type') in ('module','importmap'): node.drop_tree()
    for node in list(dom.xpath('//iframe|//object|//embed|//form|//base|//link|//meta[@http-equiv]')): node.drop_tree()
    for node in dom.iter():
        for name in list(node.attrib):
            if name.lower().startswith('on') or name.lower() in ('href','srcdoc','action','formaction','srcset'):
                del node.attrib[name]
        if node.get('src') and not node.get('src','').lower().startswith('data:image/'):
            del node.attrib['src']
    head=dom.find('head');body=dom.find('body')
    if head is None or body is None: raise ValueError('文档组件未生成完整页面。')
    style=html.Element('style');style.text=FRAME_CSS;head.append(style)
    script=html.Element('script');script.text=FRAME_SCRIPT;body.append(script)
    return '<!doctype html>\n'+html.tostring(dom,encoding='unicode',method='html')


def text_preview(source):
    """A labelled reading view for formats without the Office page renderer."""
    from .extract import extract
    segments = [s for s in extract(str(source)) if s.editable]
    if not segments: raise ValueError('没有可预览的正文。')
    pages = {}
    for index,segment in enumerate(segments):
        pages.setdefault(segment.slide if segment.slide is not None else index//40+1, []).append(segment)
    content = []
    for number,values in pages.items():
        paragraphs = ''.join('<p>'+escaping.escape(s.text)+'</p>' for s in values)
        content.append(f'<div class="page-wrapper"><div class="page"><small>正文阅读预览 · {number}（不还原原文件版式、图像及代码）</small>{paragraphs}</div></div>')
    raw = '<html><head><meta charset="utf-8"><style>.page{box-sizing:border-box;width:900px;background:white;color:#182737;padding:36px;min-height:600px;font:18px/1.6 Arial,sans-serif}p{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#657584}</style></head><body>'+''.join(content)+'</body></html>'
    return prepare(raw,'.pptx')


def preview(comparison_id,side):
    if side not in ('source','output'): raise ValueError('页面预览不存在。')
    value=comparison.read(comparison_id)
    # The shared semaphore bounds renderer subprocesses independently of model work.
    if not SLOTS.acquire(timeout=30): raise ValueError('页面预览正在准备，请稍后重试。')
    try:
        with LOCK: render_lock=RENDER_LOCKS.setdefault((comparison_id,side),threading.Lock())
        with render_lock:
            source=comparison.source_for_preview(value) if side=='source' else Path(value['output_path'])
            if not source.is_file(): raise ValueError('处理后的文件已移动或删除，无法显示完整页面。文字对照仍可查看。')
            digest=store.fingerprint(source);folder=comparison.folder()/comparison_id;folder.mkdir(parents=True,exist_ok=True)
            cached=folder/(side+'.html');stamp=folder/(side+'.sha256')
            cache_key=PREVIEW_FORMAT+'\n'+digest
            if cached.is_file() and stamp.is_file() and stamp.read_text()==cache_key: return cached.read_text(encoding='utf-8')
            if source.suffix.lower() not in {'.docx','.pptx'}:
                prepared = text_preview(source)
                if store.fingerprint(source) != digest: raise ValueError('文件在读取期间发生变化，请重试预览。')
                cached.write_text(prepared,encoding='utf-8');stamp.write_text(cache_key)
                return prepared
            with tempfile.TemporaryDirectory(prefix='star-page-preview-') as tmp:
                snapshot=Path(tmp)/('document'+source.suffix.lower());output=Path(tmp)/'preview.html'
                shutil.copyfile(source,snapshot)
                if store.fingerprint(snapshot)!=digest: raise ValueError('文件在读取期间发生变化，请重试预览。')
                binary=officecli_bridge.ensure_component('before_preview')
                try:
                    result=subprocess.run([str(binary),'view',str(snapshot),'html','--out',str(output)],
                        cwd=tmp,capture_output=True,encoding='utf-8',errors='replace',timeout=120,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                        env={**os.environ,'OFFICECLI_NO_AUTO_RESIDENT':'1','OFFICECLI_SKIP_UPDATE':'1'})
                except subprocess.TimeoutExpired as e: raise ValueError('完整页面预览准备超时。文字对照仍可使用，请稍后重试。') from e
                if result.returncode or not output.is_file(): raise ValueError('文档组件未能生成完整页面，请导出诊断日志。')
                if output.stat().st_size>MAX_HTML: raise ValueError('页面预览内容较大，请先通过文档软件查看。文字对照仍可使用。')
                prepared=prepare(output.read_text(encoding='utf-8-sig'),source.suffix.lower())
            # Replacements and external edits produce a new fingerprint on the next view.
            cached.write_text(prepared,encoding='utf-8');stamp.write_text(cache_key)
            return prepared
    finally: SLOTS.release()


def response(comparison_id,side,shared=False):
    try: content=preview(comparison_id,side)
    except Exception as error:
        logging.getLogger(__name__).exception('Could not prepare read-only page comparison')
        message=str(error) if isinstance(error,ValueError) else '页面预览未完成，请导出诊断日志。'
        if shared and ('检查位置' in message or not isinstance(error,ValueError)):
            message='页面预览未完成，请在共享电脑校验文档组件或导出诊断日志。'
        import json
        payload=json.dumps({'channel':'star-page-preview','type':'error','message':message},ensure_ascii=True).replace('<','\\u003c')
        content='<html><head><meta charset="utf-8"></head><body style="background:#071422;color:#abc2d5;font:16px sans-serif;padding:20px">'+escaping.escape(message)+'<script>parent.postMessage({...'+payload+',token:new URLSearchParams(location.search).get("preview_token")},"*")</script></body></html>'
    result=Response(content,mimetype='text/html')
    result.headers['Content-Security-Policy']=CSP+("; frame-ancestors 'self'" if shared else '')
    result.headers['Cache-Control']='no-store';result.headers['X-Content-Type-Options']='nosniff'
    return result
