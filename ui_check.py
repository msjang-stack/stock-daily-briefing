#!/usr/bin/env python3
# ui_check.py
# 배포된 페이지가 '지금의' 화면 코드(app/template.html)를 쓰고 있는지 확인합니다.
#
# 왜 필요한가: 페이지는 만들어질 때 그 시점의 template.html을 통째로 박아서
# 완성됩니다(app/kr_build.py). 그래서 데이터는 최신인데 화면만 옛것인 상태가
# 생길 수 있고, 이때 기존 배포 확인(날짜·생성 시각 대조)은 전부 통과합니다 —
# 2026-10-26 '주요 이슈' 탭이 실제로 이렇게 통과하면서 안 보였습니다.
#
# 지금은 assemble.py가 조립할 때마다 다시 감싸주므로 어긋날 일이 없어야 하지만,
# "없어야 한다"를 믿지 않고 결과물을 직접 확인합니다. watchdog이 이걸 보고
# 어긋나 있으면 redeploy.yml을 띄워 알아서 바로잡습니다.

import os
import re
import sys
import urllib.request

TEMPLATE_PATH = os.path.join("app", "template.html")

# 데이터는 한 줄짜리 compact JSON이라(json.dumps separators) 이 줄은 정확히
# 이 접두사로 시작해서 이 접미사로 끝납니다 — 그 다음 줄부터가 화면 코드입니다.
DATA_PREFIX = "<script>window.__DATA__ = "
DATA_SUFFIX = ";</script>"
TAIL_RE = re.compile(r"\n</body>\s*</html>\s*\Z")


def page_template(html):
    """페이지에서 화면 코드 부분만 떼어냅니다. 구조를 못 알아보면 None —
    '다르다'와 '모르겠다'를 구분해야 합니다(아래 is_current 참고)."""
    lines = html.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(DATA_PREFIX) and line.endswith(DATA_SUFFIX):
            rest = "\n".join(lines[i + 1:])
            break
    else:
        return None
    tail = TAIL_RE.search(rest)
    return rest[:tail.start()] if tail else None


def local_template(path=TEMPLATE_PATH):
    with open(path, encoding="utf-8") as f:
        return f.read()


def is_current(html, tpl):
    """True 최신 / False 옛 화면 / None 판단 불가.

    판단 불가를 False로 뭉개면 안 됩니다 — 페이지 구조를 못 읽은 것뿐인데
    배포를 계속 다시 걸어대는 쪽이 더 나쁩니다."""
    live = page_template(html)
    if live is None:
        return None
    return live == tpl


def describe(html, tpl):
    """어긋났을 때 사람이 읽을 한 줄. 템플릿은 수십 KB라 전문 대신 어디서부터
    달라지는지만 알려줍니다."""
    live = page_template(html)
    if live is None:
        return "페이지 구조를 못 알아봤습니다"
    for n, (a, b) in enumerate(zip(live.split("\n"), tpl.split("\n")), 1):
        if a != b:
            return (f"{n}번째 줄부터 다릅니다 · 라이브 {len(live):,}자 / "
                    f"지금 코드 {len(tpl):,}자\n  라이브: {a.strip()[:100]}\n"
                    f"  지금:   {b.strip()[:100]}")
    return f"길이만 다릅니다 · 라이브 {len(live):,}자 / 지금 코드 {len(tpl):,}자"


def main(sites):
    tpl = local_template()
    verdicts = []
    for base in sites:
        try:
            req = urllib.request.Request(
                f"{base}/", headers={"User-Agent": "stock-daily-briefing-ui-check"})
            with urllib.request.urlopen(req, timeout=60) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"[화면] {base}/ 조회 실패: {type(e).__name__}")
            continue
        ok = is_current(html, tpl)
        verdicts.append(ok)
        if ok is True:
            print(f"[화면] {base}/ 는 지금 화면 코드를 쓰고 있습니다")
        elif ok is False:
            print(f"[화면] {base}/ 가 옛 화면 코드입니다 — {describe(html, tpl)}")
        else:
            print(f"[화면] {base}/ 는 구조를 못 알아봐 판단을 보류합니다")
    if False in verdicts:
        return 1
    if not any(v is True for v in verdicts):
        print("[화면] 확인하지 못했습니다 (조회 실패 또는 구조 변경) — 실패로 보지 않습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or [
        "https://stock-daily-briefing.pages.dev",
        "https://msjang-stack.github.io/stock-daily-briefing",
    ]))
