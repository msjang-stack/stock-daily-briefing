# app/issue_build.py
# 시장 전체의 주요 이슈·뉴스만 따로 모읍니다.
#
# 국내(kr_build)·미국(us_build) 빌드와 마찬가지로 서로를 전혀 모릅니다 — 결과는
# cache/issue_latest/issues.json 한 곳에만 쓰고, 화면에 붙이는 일은 assemble.py가
# 합니다. 뉴스는 장 마감과 무관하게 하루 종일 움직이므로 자기 주기(3시간)로
# 따로 돕니다.

import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from . import config, news

KST = timezone(timedelta(hours=9))

# 시장 전체를 훑는 주제어입니다. 개별 종목 뉴스는 각 시장 탭에 이미 있으므로,
# 여기서는 지수·거시·해외처럼 "오늘 시장이 왜 이렇게 움직였나"에 해당하는 것만 모읍니다.
TOPICS = (
    ("국내 증시", ("코스피", "코스닥")),
    ("환율·금리", ("원달러 환율", "기준금리")),
    ("해외 증시", ("뉴욕증시", "연방준비제도")),
)

PER_TOPIC = 5     # 주제어 하나당 받아올 기사 수
TOTAL = 24        # 화면에 남길 최대 개수
DAYS = 2          # 며칠 이내 기사만


def _key(item):
    """같은 사건을 다룬 기사를 걸러내기 위한 비교 키."""
    return "".join(ch for ch in item.get("t", "")[:22] if ch.isalnum())


def run():
    started = time.time()
    print("[이슈] 시작")

    items, seen_title, seen_url = [], set(), set()
    for tag, queries in TOPICS:
        for q in queries:
            got = news.fetch_topic(q, want=PER_TOPIC, days=DAYS)
            kept = 0
            for a in got:
                k, url = _key(a), a.get("url", "")
                if not a.get("t") or not url or k in seen_title or url in seen_url:
                    continue
                seen_title.add(k)
                seen_url.add(url)
                items.append({
                    "t": a["t"],
                    "sum": a.get("sum", ""),
                    "url": url,
                    "s": a.get("s", ""),
                    "w": a.get("w", ""),
                    "ts": a.get("ts", 0),
                    "tag": tag,
                })
                kept += 1
            print(f"[이슈] {tag} · {q}: {len(got)}건 중 {kept}건")
            time.sleep(0.2)

    items.sort(key=lambda a: a.get("ts", 0), reverse=True)
    items = items[:TOTAL]
    for a in items:
        a.pop("ts", None)  # 정렬에만 쓰고 화면에는 안 내보냅니다

    # 한 건도 못 건졌으면(검색 API 장애, 키 누락 등) 파일을 건드리지 않고 실패로
    # 끝냅니다. 빈 목록으로 덮어쓰면 화면에서 이슈가 통째로 사라지고, builtAt만
    # 새로 찍혀서 워치독도 "정상"으로 보고 넘어갑니다 — 이전 것을 그대로 두는
    # 편이 낫고, 묵으면 워치독이 알아서 다시 띄웁니다.
    if not items:
        print("[이슈] 한 건도 못 받았습니다 — 기존 파일을 그대로 두고 실패로 끝냅니다")
        return 1

    now = datetime.now(KST)
    out_dir = config.ISSUE_CACHE_DIR
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "builtAt": now.strftime("%Y-%m-%d %H:%M"),
        "topics": [t for t, _ in TOPICS],
        "items": items,
    }
    path = os.path.join(out_dir, "issues.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    withsum = sum(1 for a in items if a["sum"])
    kb = os.path.getsize(path) / 1024
    print(f"[이슈] 완료: {len(items)}건 (요약 있는 것 {withsum}건) · "
          f"{kb:,.0f} KB · {time.time() - started:.0f}초 소요")
    return 0
