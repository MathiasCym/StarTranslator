"""Flask 后端：给 Electron 前端提供检验/替换能力。

启动时绑定 127.0.0.1 随机端口，把端口写到 stdout 供 Electron 主进程读取。
"""
import argparse
import json
import os
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from backend.extract import extract, SUPPORTED
from backend.glossary import Glossary, DEFAULT_PATH
from backend.glossary.loader import _load_any
from backend.glossary import writer as glossary_writer
from backend.llm.client import LLMClient, LLMUnavailable
from backend.model_connection import connection_probe
from backend.matcher import check_segments
from backend.replacer import apply_replacements

app = Flask(__name__)
from backend.features_api import api as features_api
app.register_blueprint(features_api)

# 进程内状态：一份文档一次检验，够用且简单
STATE = {
    "segments": [],
    "findings": [],
    "files": [],
    "glossary": None,
    "stats": {},
}
LOCK = threading.Lock()


def _get_glossary(imports: list[str] | None = None) -> Glossary:
    from backend.glossary.store import load_glossary
    return load_glossary(imports)


@app.get("/api/health")
def health():
    client = LLMClient()
    connection = connection_probe.get(client)
    return jsonify({
        "status": "ok",
        "llm_available": connection["state"] == "connected",
        "model_status": connection,
        "glossary_path": DEFAULT_PATH,
    })


@app.get("/api/glossary/stats")
def glossary_stats():
    g = _get_glossary()
    confirmed = sum(1 for e in g.entries if e.priority == 1)
    return jsonify({
        "total": len(g.entries),
        "confirmed": confirmed,
        "auto": len(g.entries) - confirmed,
        "entries": [e.to_dict() for e in g.entries],
    })


@app.get("/api/default-output-dir")
def default_output_dir():
    """默认导出目录：用户「文档」下的 星译官 导出。"""
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return jsonify({"dir": os.path.join(docs, "星译官 导出")})


@app.post("/api/glossary/reload")
def glossary_reload():
    """重新载入术语库。

    逐表容错：某张共享表还没同步下来 / 路径失效时，只跳过它并回报，
    不让整次刷新失败——否则用户会以为整个词库都没了。
    """
    data = request.get_json(silent=True) or {}
    imports = data.get("imports") or []

    usable, skipped = [], []
    for path in imports:
        if not path or not os.path.exists(path):
            skipped.append({"path": path, "error": "文件不存在（可能尚未同步）"})
            continue
        try:
            _load_any(path)
        except Exception as e:
            skipped.append({"path": path, "error": str(e)})
            continue
        usable.append(path)

    with LOCK:
        STATE["glossary"] = Glossary.load_with_imports(DEFAULT_PATH, usable)
    return jsonify({
        "total": len(STATE["glossary"].entries),
        "loaded": usable,
        "skipped": skipped,
    })


@app.post("/api/check")
def check():
    """对一批文件做检验。

    请求: {"paths": [...], "use_llm": true, "glossary_imports": [...]}

    判决由 LLM 负责，因此模型不可用时**直接报错、不产出报告**。
    实测已证明：失去模型后规则层单干，在人工校对过的语料上会报出
    35 条假阳性、真错误 0 条。宁可不出结果，也不给用户一堆假错误。
    """
    data = request.get_json(force=True) or {}
    paths = data.get("paths") or []
    use_llm = bool(data.get("use_llm", True))
    imports = data.get("glossary_imports") or []

    if not paths:
        return jsonify({"error": "未提供文件"}), 400

    all_segments, files, errors = [], [], []
    glossary = _get_glossary(imports)

    for path in paths:
        if not os.path.exists(path):
            errors.append({"path": path, "error": "文件不存在"})
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED:
            errors.append({"path": path, "error": f"不支持的格式 {ext}"})
            continue
        try:
            segs = extract(path)
        except Exception as e:
            errors.append({"path": path, "error": f"解析失败：{e}"})
            continue
        all_segments.extend(segs)
        files.append({
            "path": path,
            "name": os.path.basename(path),
            "segments": len(segs),
            "editable": sum(1 for s in segs if s.editable),
        })

    if not all_segments:
        return jsonify({"error": "没有可检验的内容",
                        "details": [e["error"] for e in errors]}), 400

    try:
        findings, stats = check_segments(all_segments, glossary, use_llm=use_llm)
    except LLMUnavailable as e:
        return jsonify({
            "error": "模型不可用，无法检验",
            "hint": str(e),
            "details": str(e),
        }), 503

    with LOCK:
        STATE["segments"] = all_segments
        STATE["findings"] = findings
        STATE["files"] = files
        STATE["stats"] = stats

    # segment id -> 文件/位置信息，供前端展示
    seg_meta = {
        s.id: {"file": s.file, "slide": s.slide, "source": s.source}
        for s in all_segments
    }

    return jsonify({
        "stats": stats,
        "files": files,
        "errors": errors,
        "findings": [
            {**f.to_dict(), "seg": seg_meta.get(f.segment_id, {})}
            for f in findings
        ],
        "segments": [
            {"id": s.id, "file": s.file, "slide": s.slide, "para": s.para,
             "source": s.source, "editable": s.editable,
             "not_editable_reason": s.not_editable_reason,
             "needs_merge": s.needs_merge, "text": s.text}
            for s in all_segments
        ],
    })


@app.post("/api/apply")
def apply():
    """执行替换。

    请求: {"path": "...", "selected": {segment_id: [[old,new], ...]},
           "output_dir": "..."（可选，为空则输出到原文件旁）}
    """
    data = request.get_json(force=True) or {}
    path = data.get("path")
    selected_raw = data.get("selected") or {}
    output_dir = data.get("output_dir") or None

    with LOCK:
        segments = [s for s in STATE["segments"] if s.file == os.path.basename(path or "")]
    if not segments:
        return jsonify({"error": "请先对该文件执行检验"}), 400

    selected = {
        sid: [tuple(p) for p in pairs]
        for sid, pairs in selected_raw.items()
    }

    try:
        out_path, ok, fail = apply_replacements(path, segments, selected, output_dir)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"替换失败：{e}"}), 500

    return jsonify({
        "output": out_path,
        "output_name": os.path.basename(out_path),
        "applied": [{"segment_id": s, "old": o, "new": n} for s, o, n in ok],
        "applied_count": len(ok),
        "failed": [{"segment_id": s, "reason": r} for s, r in fail],
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    from werkzeug.serving import make_server, WSGIRequestHandler

    class RequestHandler(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            # 每秒探测无需刷屏，其余接口保留正常请求日志。
            if self.path != "/api/health":
                super().log_request(code, size)

    # 端口 0 = 让系统分配，随后打印真实端口给 Electron
    server = make_server("127.0.0.1", args.port, app, threaded=True, request_handler=RequestHandler)
    from backend.officecli_bridge import audit_startup
    audit_startup()
    print(f"PORT={server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
