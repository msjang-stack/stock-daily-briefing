# app/kr_build.py
# 국내(코스피·코스닥) 수집 → 계산 → cache/kr_latest/ 생성. 미국 시장은 전혀 모릅니다.
# 실제 배포본(dist/)으로 합치고 날짜별로 보관하는 건 assemble.py가 합니다.
#   python -c "from app import kr_build; kr_build.run()"

import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import config, dart, indicators, naver, news, picks

KST = timezone(timedelta(hours=9))
WEEKDAY = config.WEEKDAY


def eok(v):
    if not v:
        return "-"
    e = v / 1e8
    if e >= 10000:
        return f"{e / 10000:.1f}조"
    return f"{e:,.0f}억"


def build_universe(snap):
    """동전주·저유동성·우선주를 걸러 화면에 올릴 후보를 만듭니다.
    어느 조건에서 얼마나 빠지는지 남겨, 필터가 과하면 바로 알 수 있게 합니다."""
    kinds = {}
    for s in snap:
        kinds[s.get("kind") or "(없음)"] = kinds.get(s.get("kind") or "(없음)", 0) + 1
    print("[유니버스] 종류 분포: " + ", ".join(f"{k} {v:,}" for k, v in sorted(kinds.items())))

    out = []
    drop = {"값없음": 0, "ETF·ETN": 0, "우선주": 0, "스팩": 0,
            "저가": 0, "저유동성": 0, "소형주": 0}
    for s in snap:
        if not s.get("p") or not s.get("c"):
            drop["값없음"] += 1; continue
        # 레버리지 ETF는 등락률 상위를 독차지해 정작 종목이 안 보입니다.
        if s.get("kind") and s["kind"] != "stock":
            drop["ETF·ETN"] += 1; continue
        if not s["c"].endswith("0"):
            drop["우선주"] += 1; continue
        if "스팩" in (s.get("n") or ""):
            drop["스팩"] += 1; continue
        if s["p"] < config.MIN_PRICE:
            drop["저가"] += 1; continue
        if (s.get("val") or 0) < config.MIN_VALUE:
            drop["저유동성"] += 1; continue
        if s.get("cap") and s["cap"] < config.MIN_MARKET_CAP:
            drop["소형주"] += 1; continue
        out.append(s)
    print("[유니버스] 제외 내역: " + ", ".join(f"{k} {v:,}" for k, v in drop.items() if v))
    if snap:
        sample = snap[0]
        print(f"[유니버스] 표본: {sample.get('n')} 가격={sample.get('p')} "
              f"거래량={sample.get('vol')} 거래대금={sample.get('val')} 시총={sample.get('cap')}")
    return out


def run():
    started = time.time()
    now = datetime.now(KST)
    print(f"[국내 시작] {now:%Y-%m-%d %H:%M} KST")

    # ---------- 1. 전 종목 스냅샷 ----------
    snap = naver.fetch_snapshot()
    if not snap:
        print("[오류] 시세를 전혀 받지 못했습니다.")
        return 1
    print(f"[스냅샷] 총 {len(snap):,}종목")

    universe = build_universe(snap)
    print(f"[유니버스] 필터 통과 {len(universe):,}종목")

    by_value = sorted(universe, key=lambda x: -(x.get("val") or 0))
    by_gain = sorted(universe, key=lambda x: -(x.get("pct") or -999))

    # ---------- 2. 차트용 일별 시세 ----------
    targets, seen = [], set()
    for s in by_value[: config.CHART_LIMIT]:
        if s["c"] not in seen:
            seen.add(s["c"]); targets.append(s)
    for s in by_gain[: config.TOP_N * 4]:
        if s["c"] not in seen:
            seen.add(s["c"]); targets.append(s)

    charts, metrics = {}, {}
    print(f"[시세] {len(targets):,}종목 일별 시세 수집 시작")
    fail = 0
    for i, s in enumerate(targets):
        try:
            d = naver.fetch_daily(s["c"])
            if d:
                charts[s["c"]] = {"d": d["d"], "c": d["c"], "v": d["v"]}
                m = indicators.compute(d)
                if m:
                    metrics[s["c"]] = m
            else:
                fail += 1
        except Exception:
            fail += 1
        if (i + 1) % 100 == 0:
            print(f"  ... {i + 1}/{len(targets)} (실패 {fail})")
        time.sleep(0.12)
    print(f"[시세] 완료: 차트 {len(charts):,}개, 지표 {len(metrics):,}개, 실패 {fail}")

    # ---------- 3. 지수 ----------
    # 시장 거래대금은 지수 API가 주는 필드가 불확실해, 상장 종목 거래대금의 합으로 냅니다.
    market_value = {}
    for s in snap:
        if s.get("val"):
            market_value[s["mkt"]] = market_value.get(s["mkt"], 0) + s["val"]

    try:
        investors = naver.fetch_index_investors()
    except Exception as e:
        print(f"[수급] 조회 실패: {type(e).__name__}: {e}")
        investors = {}
    print(f"[수급] {len(investors)}개 시장 확보")

    indices = []
    for name in ("KOSPI", "KOSDAQ"):
        try:
            ix = naver.fetch_index(name)
        except Exception as e:
            print(f"[지수] {name} 실패: {type(e).__name__}: {e}")
            ix = None
        if not ix:
            continue
        ix["series"] = naver.fetch_index_series(name)
        ix.pop("value", None)
        ix["value"] = eok(market_value.get(name))
        ix["flow"] = investors.get(name)
        indices.append(ix)
    print(f"[지수] {len(indices)}개 수집")

    # ---------- 4. 등락 종목 수 ----------
    up = sum(1 for s in snap if (s.get("pct") or 0) > 0)
    down = sum(1 for s in snap if (s.get("pct") or 0) < 0)
    flat = len(snap) - up - down

    lines = []
    for ix in indices:
        verb = "올라" if (ix["pct"] or 0) > 0 else ("내려" if (ix["pct"] or 0) < 0 else "보합으로")
        lines.append(
            f"{ix['name']}는 {abs(ix['pct'] or 0):.2f}% {verb} "
            f"{ix['val']:,.2f}로 마감했습니다. 거래대금은 {ix['value']}원입니다."
        )
    if lines:
        lines.append(f"전체 {len(snap):,}종목 중 {up:,}종목이 오르고 {down:,}종목이 내렸습니다.")

    # ---------- 5. 목록 ----------
    def row(s):
        m = metrics.get(s["c"]) or {}
        note = ""
        if m.get("val_ratio") and m["val_ratio"] >= 2:
            note = f"거래대금 평소의 {m['val_ratio']:.1f}배"
        elif m.get("new_high"):
            note = "60일 최고가 경신"
        elif m.get("ret20") is not None:
            note = f"20일 수익률 {m['ret20']:+.1f}%"
        return {"n": s["n"], "c": s["c"], "mkt": s["mkt"], "p": s["p"],
                "pct": s["pct"], "val": round((s.get("val") or 0) / 1e8),
                "note": note}

    stocks = [row(s) for s in universe]

    # 거래가 얇은 종목은 조건을 쉽게 충족하지만 실제로 사고팔기 어렵습니다.
    watch_pool = [s for s in by_value if (s.get("val") or 0) >= config.MIN_WATCH_VALUE]
    print(f"[주목] 후보 {len(watch_pool):,}종목 "
          f"(거래대금 {config.MIN_WATCH_VALUE / 1e8:,.0f}억원 이상)")
    watch = picks.pick(watch_pool, metrics)
    for w in watch:
        w["val"] = round((w.get("val") or 0) / 1e8)
    print(f"[주목] {len(watch)}종목 선정: " + ", ".join(w["n"] for w in watch))

    # ---------- 6. 뉴스 ----------
    news_targets, seen = [], set()
    for s in [dict(w) for w in watch] + by_value[: config.TOP_N] + by_gain[: config.TOP_N]:
        if s["c"] not in seen and len(news_targets) < config.NEWS_STOCKS:
            seen.add(s["c"]); news_targets.append(s)

    stock_news = {}
    for s in news_targets:
        arts = news.fetch_for(s["n"])
        if arts:
            stock_news[s["c"]] = arts
        time.sleep(0.15)
    print(f"[뉴스] 종목 뉴스 {len(stock_news)}건 / 조회 {len(news_targets)}종목")

    market_news = news.fetch_market()
    print(f"[뉴스] 시장 뉴스 {len(market_news)}건")

    # ---------- 7. 기업 개요 ----------
    info_codes = [s["c"] for s in news_targets]
    try:
        info_raw = dart.enrich(info_codes)
    except Exception as e:
        # 회사 개요는 부가 정보입니다. 실패해도 페이지는 나와야 합니다.
        print(f"[기업정보] 건너뜀 ({type(e).__name__}: {e})")
        info_raw = {}
    info = {}
    for code, d in info_raw.items():
        if not d:
            continue
        parts = []
        if d.get("industry"):
            parts.append(d["industry"])
        if d.get("est"):
            parts.append(f"{d['est']}년 설립")
        if d.get("ceo"):
            parts.append(f"대표 {d['ceo']}")
        if parts:
            info[code] = " · ".join(parts)
    print(f"[기업정보] {len(info)}건")

    # ---------- 8. 출력 ----------
    trade_day = None
    for c in charts.values():
        if c["d"]:
            trade_day = max(trade_day or "", c["d"][-1])
    if trade_day:
        dt = datetime.strptime(trade_day, "%Y%m%d")
    else:
        dt = now.replace(tzinfo=None)
    date_iso = dt.strftime("%Y-%m-%d")

    # 차트는 종목별 파일로 나눕니다. 첫 화면에 바로 보이는 종목만 페이지에 담고,
    # 검색으로 찾아 들어가는 종목은 누를 때 그 종목 파일 하나만 받아옵니다.
    visible = set()
    for s in watch:
        visible.add(s["c"])
    for group in (by_value, by_gain):
        for s in group[: config.TOP_N * 2]:
            visible.add(s["c"])

    out_dir = config.KR_CACHE_DIR
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    chart_dir = os.path.join(out_dir, "charts")
    os.makedirs(chart_dir, exist_ok=True)
    for code, c in charts.items():
        with open(os.path.join(chart_dir, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, separators=(",", ":"))
    inline = {c: v for c, v in charts.items() if c in visible}
    print(f"[차트] 개별 파일 {len(charts):,}개 저장, 페이지 내장 {len(inline)}개")

    data = {
        "chartDir": "charts/",
        "dateISO": date_iso,
        "dateLabel": f"{dt.year}년 {dt.month}월 {dt.day}일",
        "weekday": WEEKDAY[dt.weekday()],
        "closeNote": "15:30 종가 기준",
        "indices": indices,
        "briefing": {"lines": lines, "breadth": {"up": up, "flat": flat, "down": down}},
        "news": market_news,
        "stocks": stocks,
        "watch": watch,
        "info": info,
        "stockNews": stock_news,
        "charts": inline,
        "builtAt": now.strftime("%Y-%m-%d %H:%M"),
    }

    with open("app/template.html", encoding="utf-8") as f:
        tpl = f.read()

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    page = (
        "<!doctype html>\n<html lang=\"ko\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "</head>\n<body>\n"
        f"<script>window.__DATA__ = {payload};</script>\n"
        + tpl +
        "\n</body>\n</html>\n"
    )
    out = os.path.join(out_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)

    # 토스 미니앱용: 페이지에 인라인하는 것과 같은 데이터를 kr.json으로도 내보냅니다.
    # assemble.py의 _copy_kr()이 meta.json 외 모든 파일을 dist/로 옮기므로 별도
    # 조립 변경은 필요 없습니다.
    with open(os.path.join(out_dir, "kr.json"), "w", encoding="utf-8") as f:
        f.write(payload)

    # assemble.py가 아카이브 여부(그날 국내 장이 실제로 열렸는지)를 판단할 때 씁니다.
    # 국내 빌드는 여기서 끝 — 미국이나 아카이브는 전혀 몰라도 됩니다.
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"dateISO": date_iso, "dt": dt.isoformat()}, f)

    kb = os.path.getsize(out) / 1024
    print(f"[완료] {out} ({kb:,.0f} KB) · {time.time() - started:.0f}초 소요")

    print_summary(data, by_value, by_gain)
    return 0


def print_summary(data, by_value, by_gain):
    """만들어진 페이지에 실제로 무엇이 담겼는지 로그로 남깁니다."""
    line = "─" * 58
    print("\n" + line)
    print(f"  {data['dateLabel']} ({data['weekday']}) 마감 시황 — 생성 내용")
    print(line)

    for ix in data["indices"]:
        arrow = "▲" if (ix["pct"] or 0) > 0 else ("▼" if (ix["pct"] or 0) < 0 else "―")
        print(f"  {ix['name']:5s} {ix['val']:>10,.2f}  {arrow} {ix['pct']:+.2f}%   거래대금 {ix['value']}원")

    br = data["briefing"]["breadth"]
    print(f"  상승 {br['up']:,} · 보합 {br['flat']:,} · 하락 {br['down']:,}")

    print("\n  [내일 주목할 종목]")
    if not data["watch"]:
        print("    조건을 충족한 종목이 없습니다.")
    for i, w in enumerate(data["watch"], 1):
        print(f"    {i}. {w['n']} ({w['c']}, {w['mkt']})  {w['p']:,}원 {w['pct']:+.2f}%")
        for label, detail in w["checks"]:
            print(f"       · {label}" + (f" — {detail}" if detail else ""))

    for market in ("KOSPI", "KOSDAQ"):
        for title, rows in (("거래대금 상위", by_value), ("등락률 상위", by_gain)):
            picked = [s for s in rows if s["mkt"] == market][:5]
            if not picked:
                continue
            print(f"\n  [{market} {title}]")
            for i, s in enumerate(picked, 1):
                val = (s.get("val") or 0) / 1e8
                print(f"    {i}. {s['n']:<14s} {s['p']:>9,}원 {s['pct']:>+7.2f}%  거래대금 {val:>7,.0f}억")

    print("\n  [주요 뉴스]")
    for n in data["news"]:
        print(f"    · {n['t']}  ({n['s']}, {n['w']})")

    named = [c for c in data["stockNews"] if data["stockNews"][c]]
    print(f"\n  종목 뉴스 {len(named)}종목 · 회사 개요 {len(data['info'])}건 "
          f"· 차트 {len(data['charts'])}개 내장")
    print(line + "\n")
