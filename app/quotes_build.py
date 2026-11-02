# app/quotes_build.py
# 국제 시세(금·은·WTI·브렌트·원/달러·원/엔)를 모아 cache/quotes_latest/quotes.json
# 을 만듭니다. 국내·미국·이슈 빌드는 전혀 몰라도 됩니다.
#
# 출처는 야후 파이낸스 v8/finance/chart(인증 불필요) — 미국 빌드(app/yahoo.py)가
# 이미 쓰는 엔드포인트라 새 의존이 없습니다. 모두 선물·환율의 "직전 거래일 종가"
# 성격의 값이며, 토스 정책상 조언·전망은 넣지 않고 기계적 사실(등락, 연속 상승,
# 기간 최고/최저)만 덧붙입니다.
#
#   python run_quotes.py   →   cache/quotes_latest/quotes.json 생성

import json
import os
from datetime import datetime, timedelta, timezone

from . import config
from .yahoo import fetch_daily

KST = timezone(timedelta(hours=9))

QUOTES_CACHE_DIR = os.path.join(config.CACHE_DIR, "quotes_latest")

# (id, 표시 이름, 야후 심볼, 단위 라벨, 소수점 자릿수, 가격 배율)
# 원/엔은 관례상 100엔당 원화로 표시하므로 JPYKRW=X(엔당 원화)에 100을 곱합니다.
ITEMS = [
    ("gold",   "국제 금",      "GC=F",     "달러/온스", 2, 1),
    ("silver", "국제 은",      "SI=F",     "달러/온스", 2, 1),
    ("wti",    "WTI 원유",     "CL=F",     "달러/배럴", 2, 1),
    ("brent",  "브렌트유",     "BZ=F",     "달러/배럴", 2, 1),
    ("usdkrw", "원/달러 환율", "KRW=X",    "원",        1, 1),
    ("jpykrw", "원/엔 환율",   "JPYKRW=X", "원 (100엔당)", 2, 100),
]

SPARK_DAYS = 40  # 스파크라인에 담을 거래일 수


def _notes(closes):
    """종가 열에서 기계적 사실만 뽑습니다. 조언·전망은 넣지 않습니다."""
    notes = []
    # 연속 상승/하락 일수
    run = 0
    sign = 0
    for i in range(len(closes) - 1, 0, -1):
        diff = closes[i] - closes[i - 1]
        s = 1 if diff > 0 else (-1 if diff < 0 else 0)
        if s == 0:
            break
        if sign == 0:
            sign = s
            run = 1
        elif s == sign:
            run += 1
        else:
            break
    if run >= 2:
        notes.append(f"{run}일 연속 {'상승' if sign > 0 else '하락'}")
    window = closes[-SPARK_DAYS:]
    if len(window) >= 5:
        last = closes[-1]
        if last == max(window):
            notes.append(f"최근 {len(window)}일 중 최고")
        elif last == min(window):
            notes.append(f"최근 {len(window)}일 중 최저")
    return notes


def _fmt_date(yyyymmdd):
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def run():
    now = datetime.now(KST)
    items = []
    failed = []
    for qid, name, symbol, unit, decimals, mult in ITEMS:
        series = fetch_daily(symbol, days=SPARK_DAYS)
        if not series or len(series["c"]) < 2:
            print(f"[시세] {name}({symbol}) 실패 — 항목에서 뺍니다")
            failed.append(name)
            continue
        closes = [round(c * mult, decimals) for c in series["c"]]
        price, prev = closes[-1], closes[-2]
        chg = round(price - prev, decimals)
        pct = round((price / prev - 1) * 100, 2) if prev else 0.0
        items.append({
            "id": qid,
            "name": name,
            "unit": unit,
            "decimals": decimals,
            "price": price,
            "chg": chg,
            "pct": pct,
            "date": _fmt_date(series["d"][-1]),
            "dates": series["d"],
            "series": closes,
            "notes": _notes(closes),
        })
        print(f"[시세] {name}: {price} ({chg:+}, {pct:+.2f}%) 기준일 {series['d'][-1]}")

    if not items:
        print("[시세] 전 항목 실패 — 캐시를 덮어쓰지 않고 종료합니다")
        return 1

    data = {
        "builtAt": f"{now.month}월 {now.day}일 {now.hour:02d}:{now.minute:02d}",
        "closeNote": "직전 거래일 종가 기준",
        "items": items,
    }
    os.makedirs(QUOTES_CACHE_DIR, exist_ok=True)
    path = os.path.join(QUOTES_CACHE_DIR, "quotes.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[시세] {len(items)}개 항목 → {path}" + (f" (실패 {len(failed)}: {', '.join(failed)})" if failed else ""))
    return 0
