"""Offline, read-only OfficeCLI checks; no model-generated command execution."""
from collections import Counter
import json
import os
import re
from pathlib import Path
import subprocess
import shutil
import tempfile
import logging
import stat
import time
import hashlib
from datetime import datetime, timezone

CHECK_TIMEOUT = 180


def component_candidates():
    # Keep the logical resources path as well as the resolved path (junctions).
    roots = [Path(__file__).absolute().parents[1], Path(__file__).resolve().parents[1]]
    candidates = []
    resources = os.environ.get('STAR_RESOURCE_DIR')
    if resources and Path(resources).is_absolute():
        candidates.append(Path(resources) / 'officecli/officecli.exe')
    for root in roots:
        candidates.extend((root / 'vendor/officecli/officecli.exe', root.parent / 'officecli/officecli.exe'))
    return list(dict.fromkeys(candidates))


def binary_path():
    for path in component_candidates():
        try:
            metadata = path.stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError(f'无法访问文档检查组件（系统错误 {getattr(error, "winerror", None) or error.errno}）：{path}。请确认当前账户有读取权限。') from error
        if stat.S_ISREG(metadata.st_mode):
            return path
    raise ValueError('文档检查组件缺失，请重新安装星译官。检查位置：' + str(component_candidates()[0]))


def expected_component():
    try:
        sources = json.loads((Path(__file__).parent / 'skills/sources.json').read_text(encoding='utf-8'))
        pinned = next(item['binary'] for item in sources if item.get('name') == 'officecli')
        digest = pinned['digest'].removeprefix('sha256:')
        if not isinstance(pinned['size'], int) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('invalid component pin')
        return pinned['size'], digest
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as error:
        raise ValueError('文档检查组件的校验资料不可读取，请修复或重新安装软件。') from error


def component_state():
    """Bounded filesystem evidence; no document text, model settings or execution."""
    result = {'resource_directory': os.environ.get('STAR_RESOURCE_DIR', ''), 'candidates': []}
    for candidate in component_candidates():
        item = {'path': str(candidate)}
        try:
            metadata = candidate.stat()
            item.update(present=True, regular=stat.S_ISREG(metadata.st_mode), size=metadata.st_size,
                        modified_ns=metadata.st_mtime_ns)
        except OSError as error:
            item.update(present=False if isinstance(error, FileNotFoundError) else None,
                        system_error=getattr(error, 'winerror', None) or error.errno)
        result['candidates'].append(item)
    return result


def ensure_component(stage='before_check'):
    try:
        binary = binary_path()
        expected_size, expected_hash = expected_component()
        try:
            metadata = binary.stat()
            if metadata.st_size != expected_size:
                raise ValueError('文档检查组件内容不完整，请修复组件。检查位置：' + str(binary))
            digest = hashlib.sha256()
            with binary.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected_hash:
                raise ValueError('文档检查组件内容与本版本不一致，请修复组件。检查位置：' + str(binary))
        except OSError as error:
            code = getattr(error, 'winerror', None) or error.errno
            raise ValueError(f'无法读取文档检查组件（系统错误 {code}）。检查位置：{binary}') from error
        return binary
    except ValueError as error:
        record_failure({'stage': stage, 'failure': 'component_preflight', 'message': str(error), **component_state()})
        raise


def audit_startup():
    # Missing OfficeCLI must not prevent opening the app or using DOCX/history.
    details = {'stage': 'startup', **component_state()}
    try:
        details.update(verified=True, component=str(ensure_component('startup')))
    except ValueError as error:
        details.update(verified=False, message=str(error))
    record_failure(details)
    return details


def record_failure(details):
    # Never store model prompts or successful document output in diagnostics.
    try:
        from .glossary.store import data_dir
        target = data_dir() / 'logs/officecli.jsonl'
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({'time': datetime.now(timezone.utc).isoformat(), **details}, ensure_ascii=False) + '\n'
        with target.open('w' if target.exists() and target.stat().st_size > 1024 * 1024 else 'a', encoding='utf-8') as stream:
            stream.write(line)
    except OSError:
        logging.getLogger(__name__).exception('Could not write document check diagnostics')


def parse_response(output):
    clean = output.lstrip('\ufeff').strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Some launches prepend a diagnostic line. Accept one complete envelope,
        # never a partial result or a second JSON payload.
        for match in list(re.finditer(r'(?:^|\n)\s*(\{)', clean))[:1]:
            try:
                value, end = json.JSONDecoder().raw_decode(clean, match.start(1))
            except json.JSONDecodeError:
                continue
            if (not clean[end:].strip() and isinstance(value, dict)
                    and isinstance(value.get('success'), bool) and ('data' in value or 'error' in value)):
                return value
        raise


def run_check(argv, cancel=None, **options):
    if cancel is None:
        return subprocess.run(argv, **options)
    from .translation import check_cancel
    check_cancel(cancel)
    timeout = options.pop('timeout')
    options.pop('capture_output')
    deadline = time.monotonic() + timeout
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options) as child:
        try:
            while True:
                check_cancel(cancel)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    stdout, stderr = child.communicate(timeout=min(.3, remaining))
                    check_cancel(cancel)
                    return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            if child.poll() is None:
                child.kill()
            child.communicate()
            raise


def command(*args, cancel=None):
    # The bundled binary is version-pinned and tested with this release.
    # Disable upstream self-updates and skill auto-refresh during document reads.
    env = {**os.environ, 'OFFICECLI_NO_AUTO_RESIDENT': '1', 'OFFICECLI_SKIP_UPDATE': '1'}
    started = time.monotonic()
    details = {'operation': str(args[0]) if args else '', 'timeout_seconds': CHECK_TIMEOUT}
    def fail(message, cause=None):
        details.update(message=message, elapsed_seconds=round(time.monotonic() - started, 2))
        record_failure(details)
        raise ValueError(message) from cause
    try:
        binary = ensure_component()
        details['component'] = str(binary)
        # Checks operate on a private snapshot; do not use the installation
        # directory as the subprocess working directory.
        document = Path(args[1]) if len(args) > 1 else None
        result = run_check([str(binary), *map(str, args), '--json'], cancel=cancel,
            capture_output=True, encoding='utf-8-sig', errors='replace', timeout=CHECK_TIMEOUT, env=env,
            cwd=str(document.absolute().parent) if document else str(binary.parent),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except ValueError as error:
        details['failure'] = 'component'
        fail(str(error), error)
    except subprocess.TimeoutExpired as error:
        details['failure'] = 'timeout'
        fail(f'文档检查超时（{CHECK_TIMEOUT} 秒），尚未生成本文件的输出。可导出错误日志排查。', error)
    except OSError as error:
        code = getattr(error, 'winerror', None) or error.errno
        details.update(failure='launch', system_error=code)
        action = '请确认当前账户有执行权限。' if code in (5, 13) else '请导出错误日志排查。'
        fail(f'文档检查组件无法启动（系统错误 {code}）。{action}', error)
    details.update(returncode=result.returncode, stdout_length=len(result.stdout), stderr=result.stderr[:3000])
    native = result.returncode & 0xffffffff
    startup_errors = {0xc0000135: '系统无法加载组件所需的运行库', 0xc000007b: '系统无法加载此组件的程序格式',
                      0xc0000142: '组件初始化失败', 0xc0000005: '组件运行时异常退出'}
    if native in startup_errors:
        details['failure'] = 'native_exit'
        fail(f'文档检查未完成：{startup_errors[native]}（0x{native:08X}）。可导出错误日志排查。')
    try:
        response = parse_response(result.stdout)
    except json.JSONDecodeError as error:
        details.update(failure='invalid_json', parse_error=str(error))
        fail(f'文档检查组件未返回有效检查结果（退出码 {result.returncode}）。可导出错误日志排查。', error)
    if not isinstance(response, dict):
        details['failure'] = 'invalid_response'
        fail('文档检查组件返回了无效结果。可导出错误日志排查。')
    data = response.get('data')
    if data is not None and not isinstance(data, dict):
        details['failure'] = 'invalid_data'
        fail('文档检查组件返回了无效检查数据。可导出错误日志排查。')
    # validate exits with 1 for schema findings, including legitimate WPS and
    # newer Office extensions. Those findings are a baseline to compare, not an
    # I/O failure. Explicit error responses must still fail.
    if (args and args[0] == 'validate' and result.returncode == 1
            and response.get('success') is False and not response.get('error')
            and isinstance(data, dict) and isinstance(data.get('errors'), list) and data['errors']):
        return data
    if not response.get('success') or result.returncode:
        details['failure'] = 'check_error'
        fail('文档检查失败：' + str(response.get('error') or '请检查文件是否可读取。'))
    return data or {}


def inspect(path, cancel=None):
    # PowerPoint holds its source open for editing. OfficeCLI's .NET reader
    # does not share that access mode, although Python can read the same file.
    # Validate a private, read-only copy rather than competing for the source.
    source = Path(path)
    with tempfile.TemporaryDirectory(prefix='star-office-check-') as directory:
        snapshot = Path(directory) / source.name
        try:
            shutil.copyfile(source, snapshot)
        except OSError as error:
            code = getattr(error, 'winerror', None) or error.errno
            message = f'读取文档检查副本失败（系统错误 {code}）。请确认文件已下载完成，且当前账户有读取权限。'
            record_failure({'failure': 'read_snapshot', 'source': str(source), 'system_error': code, 'message': message})
            raise ValueError(message) from error
        return {'errors': command('validate', snapshot, cancel=cancel).get('errors', []),
                'issues': command('view', snapshot, 'issues', '--type', 'format', '--limit', '5000', cancel=cancel).get('issues', [])}


def compare(before, after):
    signature = lambda item: json.dumps({k: v for k, v in item.items() if k.lower() != 'id'}, sort_keys=True)
    old_errors = Counter(signature(e) for e in before['errors'])
    new_errors = Counter(signature(e) for e in after['errors']) - old_errors
    if new_errors:
        raise ValueError('输出文档出现新的结构问题，未导出，请重新处理。')
    old = {signature(i) for i in before['issues']}
    warnings = []
    for item in after['issues']:
        if signature(item) in old:
            continue
        if 'text overflow' in item.get('message', '').lower():
            location = item.get('path', '')
            slide = re.search(r'/slide\[(\d+)\]', location)
            shape = re.search(r'shape\[@id=(\d+)\]', location)
            warnings.append({'text': '文本框 ' + shape[1] if shape else '',
                             'reason': '该处英文较长，请检查文本是否完整显示。',
                             'slide': int(slide[1]) if slide else None})
    return warnings
