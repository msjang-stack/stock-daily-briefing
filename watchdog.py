#!/usr/bin/env python3
# watchdog.py
# 배포된 사이트가 실제로 오늘 것으로 갱신됐는지 스스로 확인하고, 아니면 빌드를
# 다시 걸어줍니다. 사람이 매번 사이트를 열어보고 "안 됐네" 하고 다시 돌릴 필요가
# 없게 하는 것이 목적입니다.
#
# 왜 필요한가: 이 저장소에서 GitHub 예약 실행(schedule)이 제때 뜨질 않습니다.
# 실측(2026-08-24~09-09)으로 국내 빌드는 목표 시각보다 0.7~11.9시간, 미국 빌드는
# 0.3~7.9시간 늦게 시작됐습니다. 빌드 자체는 멀쩡히 성공하는데 몇 시간 뒤에야
# 도는 탓에, 저녁에 열어보면 아직 어제 데이터가 떠 있습니다.
#
# 그래서 "예약대로 돌았겠지"를 믿지 않고 결과물을 직접 확인합니다. 그리고 다시
# 띄울 때는 workflow_dispatch를 씁니다 — 예약과 달리 dispatch는 지연 없이 바로
# 실행됩니다. 워치독 자신의 예약도 늦게 뜰 수 있으므로 30분 간격으로 촘촘히
# 걸어두고, 그중 가장 먼저 도착한 실행이 복구를 맡습니다.

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 두 배포처 중 먼저 응답하는 쪽을 봅니다. 어느 쪽이든 최신이면 배포는 성공한 것.
SITES = [
    "https://stock-daily-briefing.pages.dev",
    "https://msjang-stack.github.io/stock-daily-briefing",
]

# 빌드가 끝나고 배포까지 도달하는 데 걸리는 시간을 감안한 유예. 이 시각이 지나도
# 오늘 것이 안 보이면 문제로 봅니다.
KR_DUE_AFTER = (17, 10)   # 국내 목표 16:40 KST + 유예
US_DUE_AFTER = (7, 30)    # 미국 목표 07:00 KST + 유예

# 방금 띄운 빌드가 끝나기도 전에 또 띄우지 않도록 하는 최소 간격.
REDISPATCH_GRACE_MIN = 45


def _get(url, token=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "stock-daily-briefing-watchdog"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_live_dates():
    """배포된 사이트에서 국내·미국 각각의 '데이터 생성 시각'(builtAt)을 읽어옵니다.
    한 배포처가 죽어 있어도 다른 쪽이 살아 있으면 그걸로 판단합니다.

    국내 builtAt은 index.html 안 window.__DATA__의 맨 마지막 항목이라, 앞부분만
    잘라 읽으면 절대 못 찾습니다(종목·차트 데이터가 그 앞에 수백 KB 깔림).
    페이지 전체를 받아서 찾습니다. 템플릿 쪽 자바스크립트에도 builtAt이라는
    말은 나오지만 "builtAt":"날짜 꼴은 데이터에만 있어 섞이지 않습니다."""
    kr = us = None
    for base in SITES:
        if kr is None:
            try:
                m = re.search(r'"builtAt":"(\d{4}-\d{2}-\d{2}) ', _get(f"{base}/", timeout=60))
                if m:
                    kr = m.group(1)
                else:
                    print(f"[점검] {base}/ 는 열렸는데 builtAt을 못 찾았습니다 — 페이지 구조가 바뀌었는지 확인 필요")
            except Exception as e:
                print(f"[점검] {base}/ 국내 페이지 조회 실패: {type(e).__name__}")
        if us is None:
            try:
                us = json.loads(_get(f"{base}/us.json")).get("builtAt", " ").split(" ")[0] or None
            except Exception as e:
                print(f"[점검] {base}/us.json 조회 실패: {type(e).__name__}")
        if kr and us:
            break
    return kr, us


def is_due(market, now):
    """지금이 '오늘치가 이미 올라와 있어야 하는' 시각인지.
    국내는 평일 장 마감 뒤, 미국은 (한국시간) 월~토 아침 미국 장 마감 뒤입니다."""
    hh, mm = KR_DUE_AFTER if market == "kr" else US_DUE_AFTER
    if now < now.replace(hour=hh, minute=mm, second=0, microsecond=0):
        return False
    # 국내: 월~금 / 미국: 월~토(금요일 미국 장 마감분이 토요일 아침에 들어옴)
    return now.weekday() <= (4 if market == "kr" else 5)


def needs_rebuild(market, built_date, now):
    """오늘 것이 아직 안 올라왔으면 True. built_date가 없으면(페이지가 깨졌거나
    조회 실패) 함부로 다시 띄우지 않고 그대로 둡니다 — 일시적 네트워크 문제로
    빌드를 계속 걸어대는 쪽이 더 나쁩니다."""
    if not is_due(market, now) or built_date is None:
        return False
    return built_date != now.strftime("%Y-%m-%d")


def recently_ran(repo, workflow, token, now_utc):
    """이미 돌고 있거나 방금 돈 빌드가 있으면 또 띄우지 않습니다."""
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?per_page=3"
    try:
        runs = json.loads(_get(url, token)).get("workflow_runs", [])
    except Exception as e:
        print(f"[점검] {workflow} 최근 실행 조회 실패({type(e).__name__}) — 중복 방지를 위해 이번엔 넘어갑니다")
        return True
    for run in runs:
        if run.get("status") in ("queued", "in_progress"):
            print(f"[점검] {workflow} 가 이미 실행 중 — 기다립니다")
            return True
        created = datetime.strptime(run["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now_utc - created < timedelta(minutes=REDISPATCH_GRACE_MIN):
            print(f"[점검] {workflow} 가 {int((now_utc - created).total_seconds() // 60)}분 전에 실행됨 — 기다립니다")
            return True
    return False


def dispatch(repo, workflow, token):
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    req = urllib.request.Request(url, data=json.dumps({"ref": "main"}).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    urllib.request.urlopen(req, timeout=20).read()
    print(f"[복구] {workflow} 를 지금 바로 실행시켰습니다 (예약이 늦어 직접 띄움)")


def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "msjang-stack/stock-daily-briefing")
    token = os.environ.get("GH_TOKEN")
    now = datetime.now(KST)
    now_utc = datetime.now(timezone.utc)

    kr_built, us_built = fetch_live_dates()
    today = now.strftime("%Y-%m-%d")
    print(f"[점검] 지금 {now:%Y-%m-%d %H:%M} KST · 사이트에 올라온 데이터 생성일 "
          f"— 국내 {kr_built or '읽기 실패'} / 미국 {us_built or '읽기 실패'} (오늘 {today})")

    for market, built, workflow in (("kr", kr_built, "daily.yml"), ("us", us_built, "us-morning.yml")):
        name = "국내" if market == "kr" else "미국"
        if not needs_rebuild(market, built, now):
            print(f"[점검] {name} 정상")
            continue
        print(f"[점검] {name} 갱신 안 됨 (마지막 생성 {built}, 오늘 것이 있어야 하는 시각)")
        if not token:
            print(f"[복구] 토큰이 없어 {workflow} 를 띄우지 못했습니다")
            continue
        if recently_ran(repo, workflow, token, now_utc):
            continue
        dispatch(repo, workflow, token)


if __name__ == "__main__":
    # 워치독이 빨간 줄로 뜨는 것 자체는 목적이 아닙니다. 조회 실패 같은 일시적
    # 문제로 알림을 울리지 않도록, 예기치 못한 예외만 실패로 남깁니다.
    sys.exit(main() or 0)
