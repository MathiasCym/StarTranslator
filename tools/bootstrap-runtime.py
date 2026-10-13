"""Build the same portable Windows runtime on a fresh maintainer/Actions computer."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
PYTHON_URL='https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
RCEDIT_SHA='ab53500d556fd824636621bca7dbecd8583ba181891c3e9efdcf16b72a28b0cd'

def download(url,target,expected=None):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and expected and hashlib.sha256(target.read_bytes()).hexdigest()==expected:return
    temporary=target.with_name(target.name+'.tmp')
    try:
        for attempt in range(3):
            try:
                with urlopen(url,timeout=120) as response,temporary.open('wb') as output:shutil.copyfileobj(response,output)
                if expected and hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:raise ValueError('Downloaded component checksum differs: '+target.name)
                temporary.replace(target);return
            except Exception:
                temporary.unlink(missing_ok=True)
                if attempt==2:raise
    finally:temporary.unlink(missing_ok=True)

def bootstrap():
    if sys.platform!='win32':raise SystemExit('Windows x64 is required for the portable installer.')
    runtime=ROOT/'python-runtime'
    if not (runtime/'python.exe').exists():
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'python.zip';download(PYTHON_URL,archive)
            runtime.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as source:
                for member in source.namelist():
                    if not (runtime/member).resolve().is_relative_to(runtime.resolve()):raise ValueError('Invalid archive path')
                pins=json.loads((ROOT/'build/runtime-sources.json').read_text(encoding='utf-8'))['python']['files']
                for name,digest in pins.items():
                    if hashlib.sha256(source.read(name)).hexdigest()!=digest:raise ValueError('Portable Python core checksum differs: '+name)
                source.extractall(runtime)
        (runtime/'python311._pth').write_text('python311.zip\n.\nLib\\site-packages\nimport site\n',encoding='utf-8')
    packages=runtime/'Lib/site-packages';packages.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--target',str(packages),'-r',str(ROOT/'requirements-runtime.txt')],check=True)
    source=next(item for item in json.loads((ROOT/'backend/skills/sources.json').read_text(encoding='utf-8')) if item['name']=='officecli')['binary']
    download(source['browser_download_url'],ROOT/'vendor/officecli/officecli.exe',source['digest'].removeprefix('sha256:'))
    if hashlib.sha256((ROOT/'tools/bin/rcedit-x64.exe').read_bytes()).hexdigest()!=RCEDIT_SHA:raise ValueError('Build tool checksum differs')
    print(json.dumps({'portablePython':'3.11.9','officecliPinned':True,'rceditPinned':True}))

if __name__=='__main__':bootstrap()
