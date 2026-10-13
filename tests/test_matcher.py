# -*- coding: utf-8 -*-
"""判决层回归测试。

守护的是本次重构的核心命题：**判决权归 LLM，脚本只做召回。**

三组断言：
  1. false_positives —— 实测确认的假阳性，一条都不能报
  2. true_positives  —— 实测确认的真错误，必须报出
  3. clean_segments  —— 完全正确的文本，零误报

用法：
    python tests/test_matcher.py            # 全部跑
    python tests/test_matcher.py --only fp  # 只跑假阳性组（快）

注意：LLM 判决非确定，同一输入两次可能略有差异。因此对
true_positives 允许漏报 1 条，但 false_positives 与 clean_segments
的零容忍是硬要求——误报比漏报代价高得多（用户会因此放弃使用工具）。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from backend.glossary import Glossary                      # noqa: E402
from backend.llm.client import LLMClient, LLMUnavailable   # noqa: E402
from backend.matcher.judge import judge_text               # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def test_false_positives(glossary, client):
    """假阳性组：一条都不能报。"""
    data = load("false_positives.json")["cases"]
    print(f"\n=== 假阳性组（{len(data)} 条，要求 0 误报）===")
    bad = []
    for i, case in enumerate(data, 1):
        hits = judge_text(case["context"], glossary, client)
        # 只要报出的问题里涉及这条假阳性词，就算失败
        target = _norm(case["found"])
        offenders = [h for h in hits if target in _norm(h.get("found", ""))
                     or _norm(h.get("found", "")) in target]
        if offenders:
            bad.append((case, offenders))
            print(f"  {RED}✗{RESET} [{i}] {case['found']!r} 被误报:")
            for o in offenders:
                print(f"        -> {o.get('suggested')!r}  ({o.get('reason', '')[:60]})")
        else:
            print(f"  {GREEN}✓{RESET} [{i}] {case['found']!r} 正确放过")
    return len(data), bad


def test_true_positives(glossary, client, allow_miss=1):
    """真错误组：必须报出（允许漏 1 条，因 LLM 非确定）。"""
    data = load("true_positives.json")["cases"]
    print(f"\n=== 真错误组（{len(data)} 条，允许漏 {allow_miss} 条）===")
    missed = []
    for i, case in enumerate(data, 1):
        hits = judge_text(case["segment_text"], glossary, client)
        target = _norm(case["must_find"])
        found_it = any(target in _norm(h.get("found", "")) or
                       _norm(h.get("found", "")) in target
                       for h in hits)
        if found_it:
            kinds = {h.get("kind") for h in hits}
            print(f"  {GREEN}✓{RESET} [{i}] {case['must_find']!r} 已报出 (kind={kinds})")
        else:
            missed.append(case)
            print(f"  {RED}✗{RESET} [{i}] {case['must_find']!r} 漏报  ({case['kind']})")
    return len(data), missed, allow_miss


def test_clean(glossary, client):
    """正确文本组：零误报。"""
    segs = load("clean_segments.json")["segments"]
    print(f"\n=== 正确文本组（{len(segs)} 句，要求 0 误报）===")
    bad = []
    for i, text in enumerate(segs, 1):
        hits = judge_text(text, glossary, client)
        if hits:
            bad.append((text, hits))
            print(f"  {RED}✗{RESET} [{i}] 误报: {[h.get('found') for h in hits]}")
        else:
            print(f"  {GREEN}✓{RESET} [{i}] 正确不报")
    return len(segs), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["fp", "tp", "clean"], default=None)
    args = ap.parse_args()

    client = LLMClient()
    if not client.health():
        print(f"{RED}模型不可用，无法测试。{client.last_error}{RESET}")
        return 2

    glossary = Glossary.load()
    print(f"术语库 {len(glossary.entries)} 条，模型已就绪。")

    failures = []

    if args.only in (None, "fp"):
        total, bad = test_false_positives(glossary, client)
        if bad:
            failures.append(f"假阳性组：{len(bad)}/{total} 条被误报")

    if args.only in (None, "tp"):
        total, missed, allow = test_true_positives(glossary, client)
        if len(missed) > allow:
            failures.append(f"真错误组：漏报 {len(missed)}/{total} 条（允许 {allow}）")

    if args.only in (None, "clean"):
        total, bad = test_clean(glossary, client)
        if bad:
            failures.append(f"正确文本组：{len(bad)}/{total} 句被误报")

    print("\n" + "=" * 50)
    if failures:
        print(f"{RED}失败{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}全部通过{RESET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LLMUnavailable as e:
        print(f"{RED}模型不可用：{e}{RESET}")
        sys.exit(2)
