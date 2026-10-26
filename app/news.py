# app/news.py
# 뉴스 수집. 네이버 검색 API를 우선 쓰고, 실패하면 구글 뉴스 RSS로 넘어갑니다.
# 검색이 느슨해 무관한 기사가 섞이므로 종목명이 실제로 들어간 기사만 남깁니다.

import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from . import config

KST = timezone(timedelta(hours=9))
TAG_RE = re.compile(r"<[^>]+>")
S = requests.Session()
S.headers.update(config.UA)


def _clean(t):
    return html.unescape(TAG_RE.sub("", t or "")).strip()


def _ago(dt):
    if not dt:
        return ""
    delta = datetime.now(KST) - dt.astimezone(KST)
    h = delta.total_seconds() / 3600
    if h < 1:
        return f"{max(1, int(delta.total_seconds() // 60))}분 전"
    if h < 24:
        return f"{int(h)}시간 전"
    return f"{int(h // 24)}일 전"


def _relevant(name, title, desc, locale="ko"):
    """종목명이 제목이나 본문에 실제로 들어간 기사만 통과."""
    blob = f"{title} {desc}"
    if locale == "en":
        return name.lower() in blob.lower()
    if name in blob:
        return True
    # '삼성전자' → '삼성' 처럼 앞부분만 나오는 경우도 허용 (4자 이상일 때)
    return len(name) >= 4 and name[:3] in blob and any(
        k in blob for k in ("주가", "증권", "코스피", "코스닥", "실적", "공시", "상장")
    )


# ---------------- 네이버 검색 API ----------------

def _naver(query, want, days, strict=True):
    if not (config.NAVER_CLIENT_ID and config.NAVER_CLIENT_SECRET):
        return None
    r = S.get(
        "https://openapi.naver.com/v1/search/news.json",
        params={"query": query, "display": 30, "sort": "date"},
        headers={"X-Naver-Client-Id": config.NAVER_CLIENT_ID,
                 "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"[뉴스] 네이버 API HTTP {r.status_code}: {r.text[:120]}")
        return None
    cutoff = datetime.now(KST) - timedelta(days=days)
    out = []
    for it in r.json().get("items", []):
        title, desc = _clean(it.get("title")), _clean(it.get("description"))
        # strict=False는 시장 전체 이슈용입니다. '코스피' 같은 넓은 검색어는
        # 종목명 필터를 걸면 멀쩡한 기사까지 떨어져 나갑니다.
        if strict and not _relevant(query, title, desc):
            continue
        try:
            pub = datetime.strptime(it.get("pubDate", ""), "%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            pub = None
        if pub and pub < cutoff:
            continue
        link = it.get("originallink") or it.get("link") or ""
        out.append({"t": title, "url": link,
                    "s": urllib.parse.urlparse(link).netloc.replace("www.", ""),
                    "w": _ago(pub), "sum": desc,
                    "ts": pub.timestamp() if pub else 0})
        if len(out) >= want:
            break
    return out


# ---------------- 구글 뉴스 RSS (예비, 미국은 주 출처) ----------------

def _google(query, want, days, locale="ko", strict=True):
    q = urllib.parse.quote(query)
    params = "hl=en-US&gl=US&ceid=US:en" if locale == "en" else "hl=ko&gl=KR&ceid=KR:ko"
    url = f"https://news.google.com/rss/search?q={q}&{params}"
    r = S.get(url, timeout=20)
    if r.status_code != 200:
        return []
    cutoff = datetime.now(KST) - timedelta(days=days)
    out = []
    for it in ET.fromstring(r.content).findall(".//item"):
        title = _clean(it.findtext("title"))
        # 구글은 제목 끝에 ' - 언론사'를 붙입니다.
        src_el = it.find("source")
        src = src_el.text if src_el is not None else ""
        if src and title.endswith(" - " + src):
            title = title[: -(len(src) + 3)]
        if strict and not _relevant(query, title, "", locale=locale):
            continue
        try:
            pub = datetime.strptime(it.findtext("pubDate"), "%a, %d %b %Y %H:%M:%S %Z")
            pub = pub.replace(tzinfo=timezone.utc)
        except Exception:
            pub = None
        if pub and pub < cutoff:
            continue
        # 구글 RSS의 description은 제목·출처를 다시 감싼 링크 뭉치라 요약으로
        # 쓸 게 못 됩니다. 쓸 만한 문장일 때만 남기고 아니면 비웁니다.
        desc = _clean(it.findtext("description"))
        if len(desc) < 20 or desc.startswith(title[:20]):
            desc = ""
        out.append({"t": title, "url": it.findtext("link") or "",
                    "s": src or ("Google News" if locale == "en" else "구글뉴스"),
                    "w": _ago(pub), "sum": desc,
                    "ts": pub.timestamp() if pub else 0})
        if len(out) >= want:
            break
    return out


def fetch_topic(query, want=6, days=2, locale="ko"):
    """시장 전체 이슈용. 종목명 필터 없이 검색 결과를 그대로 쓰고 요약까지 담습니다.
    종목 뉴스(fetch_for)와 달리 '코스피', '환율'처럼 넓은 주제어를 받습니다."""
    if locale == "en":
        try:
            return _google(query, want, days, locale="en", strict=False)
        except Exception as e:
            print(f"[이슈] {query} 구글(EN) 실패: {type(e).__name__}: {e}")
            return []
    try:
        got = _naver(query, want, days, strict=False)
        if got:
            return got
    except Exception as e:
        print(f"[이슈] {query} 네이버 실패: {type(e).__name__}: {e}")
    try:
        return _google(query, want, days, strict=False)
    except Exception as e:
        print(f"[이슈] {query} 구글 실패: {type(e).__name__}: {e}")
        return []


def fetch_for(name, want=3, days=3, locale="ko"):
    """한 종목의 최근 뉴스. locale="en"이면 구글 뉴스(영문)만 씁니다 (네이버는 국내 전용)."""
    if locale == "en":
        try:
            return _google(name, want, days, locale="en")
        except Exception as e:
            print(f"[뉴스] {name} 구글(EN) 실패: {type(e).__name__}: {e}")
            return []
    try:
        got = _naver(name, want, days)
        if got:
            return got
    except Exception as e:
        print(f"[뉴스] {name} 네이버 실패: {type(e).__name__}: {e}")
    try:
        return _google(name, want, days)
    except Exception as e:
        print(f"[뉴스] {name} 구글 실패: {type(e).__name__}: {e}")
        return []


def fetch_market(want=5, days=1, locale="ko"):
    """시장 전체 주요 뉴스."""
    queries = ("S&P 500", "Wall Street", "stock market") if locale == "en" else ("코스피", "코스닥", "증시")
    items, seen = [], set()
    for q in queries:
        try:
            if locale == "en":
                got = _google(q, want, days, locale="en")
            else:
                got = _naver(q, want, days) or _google(q, want, days)
        except Exception:
            got = []
        for a in got:
            key = a["t"][:24]
            if key in seen:
                continue
            seen.add(key)
            a = dict(a, tag=q)
            items.append(a)
        time.sleep(0.2)
        if len(items) >= want:
            break
    return items[:want]
