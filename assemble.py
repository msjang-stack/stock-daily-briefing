# assemble.py
# 국내(cache/kr_latest/)와 미국(cache/us_latest/)은 서로를 모르고 각자 자기
# 자리에만 결과물을 씁니다. 이 파일이 유일하게 둘을 알고, 최신 것들을 모아
# dist/로 합칩니다. 한쪽이 아직 없거나 실패했으면 있는 것만 나갑니다.
#
#   python assemble.py            → dist/ 로 합치기만 (미국 갱신 뒤: us-morning.yml)
#   python assemble.py --archive  → 합친 뒤 오늘자로 정식 보관까지 (국내 빌드 뒤: daily.yml)

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

from app import config

KST = timezone(timedelta(hours=9))
WEEKDAY = config.WEEKDAY
# _ensure_us_archived가 국내 기록 없이 임시로 폴더를 만들 때 남기는 표시.
# 이 표시가 있으면 그 폴더의 국내 페이지는 그 날짜의 진짜 데이터가 아니라
# 만들 당시 우연히 떠 있던 다른 날짜의 페이지입니다 — _archive()가 실제
# 국내 데이터를 받으면 날짜가 안 맞아도 반드시 덮어쓰도록 이 표시를 봅니다.
PLACEHOLDER_MARKER = ".kr_placeholder"


def _copy_kr():
    src = config.KR_CACHE_DIR
    if not os.path.isdir(src):
        print("[조립] 국내 데이터 없음 (아직 안 만들어졌거나 실패) — 건너뜁니다")
        return
    for name in os.listdir(src):
        if name == "meta.json":
            continue
        s, d = os.path.join(src, name), os.path.join(config.OUT_DIR, name)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
    print("[조립] 국내 데이터 반영")


def _copy_us():
    src = config.US_CACHE_DIR
    if not os.path.isdir(src) or not os.path.exists(os.path.join(src, "us.json")):
        print("[조립] 미국 데이터 없음 (아직 안 만들어졌거나 실패) — 건너뜁니다")
        return
    shutil.copy2(os.path.join(src, "us.json"), os.path.join(config.OUT_DIR, "us.json"))
    dst_us_dir = os.path.join(config.OUT_DIR, "us")
    if os.path.exists(dst_us_dir):
        shutil.rmtree(dst_us_dir)
    shutil.copytree(os.path.join(src, "us"), dst_us_dir)
    print("[조립] 미국 데이터 반영")


def _archive():
    """오늘자 dist/ 전체(국내+미국)를 국내 거래일 기준으로 보관합니다. 국내 빌드가
    남긴 meta.json의 거래일을 씁니다 — '그날'의 기본 정의는 국내 장 기준입니다.
    (미국 쪽 날짜가 어긋나 있을 때의 보완은 _ensure_us_archived가 따로 맡습니다.)

    종목별 개별 차트 파일(charts/, us/)은 지난 날짜 기록에는 담지 않습니다 —
    Cloudflare Pages는 한 번의 배포에 최대 20,000개 파일까지만 허용하는데,
    하루치가 종목별 차트 파일만으로도 1,700개 안팎이라 30일을 그대로 쌓으면
    가볍게 그 한도를 넘겨 배포 자체가 실패합니다(2026-08-21 실제 발생, "Pages
    only supports up to 20,000 files"). index.html·us.json에 이미 그날 주요
    종목 차트가 내장되어 있고, 없는 종목은 검색 시 조용히 "차트 없음"으로
    빠지게 되어 있어(app/template.html fetchSeries) 지난 날짜에서 개별 차트
    파일이 빠져도 화면이 깨지지는 않습니다."""
    meta_path = os.path.join(config.KR_CACHE_DIR, "meta.json")
    if not os.path.exists(meta_path):
        print("[아카이브] 국내 데이터가 없어 건너뜁니다")
        return
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    date_iso = meta["dateISO"]
    dt = datetime.fromisoformat(meta["dt"])

    now = datetime.now(KST)
    # 평일이라도 국내만 쉬면 dt가 today보다 과거로 남습니다. 그럴 때 이미 확정된
    # 과거 아카이브를 (그새 새로 갱신됐을 수 있는) 미국 데이터로 덮어쓰지 않도록 막습니다.
    fresh = dt.date() == now.date()
    if not fresh:
        print(f"[아카이브] 국내 장이 오늘({now:%Y-%m-%d}) 쉬어 마지막 거래일({date_iso}) 기준으로 판단합니다")

    archive_root = os.path.join(config.CACHE_DIR, "archive")
    os.makedirs(archive_root, exist_ok=True)

    today_dir = os.path.join(archive_root, date_iso)
    # _ensure_us_archived가 국내 기록이 아직 없어 임시로 만들어 둔 자리표시자일
    # 수 있습니다 — 그 안엔 그 날짜의 진짜 국내 페이지가 아니라 그 시점에
    # 우연히 떠 있던 다른 날짜의 국내 페이지가 담겨 있습니다(예: 배포 실패로
    # 그날 국내 빌드의 결과가 아예 캐시에 저장되지 못한 경우). 진짜 국내
    # 데이터가 나중에라도 들어오면, 날짜가 안 맞아도 반드시 덮어써야 합니다.
    placeholder = os.path.exists(os.path.join(today_dir, PLACEHOLDER_MARKER))
    if fresh or placeholder or not os.path.exists(today_dir):
        if os.path.exists(today_dir):
            shutil.rmtree(today_dir)
        shutil.copytree(config.OUT_DIR, today_dir, ignore=shutil.ignore_patterns("archive", "charts", "us"))
        note = " (자리표시자를 진짜 국내 데이터로 교체)" if placeholder and not fresh else ""
        print(f"[아카이브] {date_iso}(국내 기준) 저장{note}")
    else:
        print(f"[아카이브] {date_iso}는 이미 확정된 기록이라 건드리지 않습니다")


def _ensure_us_archived():
    """
    지금 cache/us_latest가 가진 날짜(미국 거래일)가 아카이브 어딘가에 반드시
    남아 있게 합니다.

    문제 상황: 국내 아카이브(_archive)는 국내 거래일 기준으로만 기록을 남기는데,
    미국 쪽 날짜가 국내와 어긋나 있는 채로(예: 주말 사이 미국만 새 거래일이
    생겼거나, 국내 아카이브가 아직 그 날짜를 처리하기 전) 다음 미국 갱신이 오면
    그 사이에 있던 미국 거래일 데이터가 어디에도 기록되지 못하고 다음 값으로
    덮어써져 통째로 사라집니다. (2026-07-31 미국 데이터가 실제로 이렇게
    사라진 적 있음 — 재발 방지용.)

    그래서 매번 조립할 때마다, 미국 날짜로 된 아카이브 폴더가 없으면 지금 시점의
    dist/ 전체(가장 최근 국내 페이지 + 이번 미국 데이터)를 그대로 새 기록으로
    만들어 둡니다. 이미 있으면(보통 국내 아카이브가 같은 날 이미 만들어 둔 경우)
    미국 부분만 최신으로 맞춥니다.
    """
    us_json_path = os.path.join(config.US_CACHE_DIR, "us.json")
    if not os.path.exists(us_json_path):
        return
    with open(us_json_path, encoding="utf-8") as f:
        us_date = json.load(f).get("dateISO")
    if not us_date:
        return

    archive_root = os.path.join(config.CACHE_DIR, "archive")
    os.makedirs(archive_root, exist_ok=True)
    target_dir = os.path.join(archive_root, us_date)

    # charts/, us/(종목별 개별 차트)는 _archive()와 같은 이유로 지난 날짜
    # 기록에는 담지 않습니다 — Cloudflare Pages 20,000개 파일 한도 참고.
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
        for name in os.listdir(config.OUT_DIR):
            if name in ("archive", "charts", "us"):
                continue
            s, d = os.path.join(config.OUT_DIR, name), os.path.join(target_dir, name)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            elif os.path.exists(s):
                shutil.copy2(s, d)
        with open(os.path.join(target_dir, PLACEHOLDER_MARKER), "w") as f:
            f.write("")
        print(f"[아카이브] {us_date}(미국 기준) 새로 기록 "
              f"— 국내 쪽에 이 날짜 기록이 아직 없어 지금 국내 페이지를 함께 담음 "
              f"(진짜 국내 데이터가 나중에 들어오면 자동으로 교체됨)")
    else:
        shutil.copy2(us_json_path, os.path.join(target_dir, "us.json"))


def _strip_legacy_chart_dirs():
    """이 수정 이전에 이미 만들어진 지난 날짜 기록에는 종목별 차트 폴더가
    그대로 남아 있어, 코드만 고쳐서는 이미 쌓인 파일 수가 줄지 않습니다.
    다음 조립 때 한 번 정리해서 실제로 20,000개 한도 아래로 내려가게 합니다."""
    archive_root = os.path.join(config.CACHE_DIR, "archive")
    if not os.path.isdir(archive_root):
        return
    removed = 0
    for name in os.listdir(archive_root):
        day_dir = os.path.join(archive_root, name)
        if not os.path.isdir(day_dir):
            continue
        for sub in ("charts", "us"):
            p = os.path.join(day_dir, sub)
            if os.path.isdir(p):
                shutil.rmtree(p)
                removed += 1
    if removed:
        print(f"[아카이브] 지난 기록에 남아 있던 종목별 차트 폴더 {removed}개 정리")


def _prune_and_manifest():
    """보관기간 지난 날짜를 지우고 date-picker용 manifest.json을 다시 만듭니다.
    아카이브가 바뀔 수 있는 모든 경로(_archive, _ensure_us_archived) 뒤에
    공통으로 부릅니다."""
    archive_root = os.path.join(config.CACHE_DIR, "archive")
    os.makedirs(archive_root, exist_ok=True)

    def _dates():
        return sorted(n for n in os.listdir(archive_root) if os.path.isdir(os.path.join(archive_root, n)))

    parsed = []
    for n in _dates():
        try:
            parsed.append(datetime.strptime(n, "%Y-%m-%d"))
        except ValueError:
            continue
    latest_dt = max(parsed) if parsed else datetime.now(KST).replace(tzinfo=None)
    cutoff = latest_dt - timedelta(days=config.ARCHIVE_DAYS)

    for name in _dates():
        try:
            d = datetime.strptime(name, "%Y-%m-%d")
        except ValueError:
            continue
        if d < cutoff:
            shutil.rmtree(os.path.join(archive_root, name))
            print(f"[아카이브] {name} 삭제 (보관기간 {config.ARCHIVE_DAYS}일 초과)")

    dates = sorted(_dates(), reverse=True)
    manifest = []
    for d in dates:
        dt_d = datetime.strptime(d, "%Y-%m-%d")
        manifest.append({
            "iso": d,
            "label": f"{dt_d.month}월 {dt_d.day}일 ({WEEKDAY[dt_d.weekday()][0]})",
        })
    with open(os.path.join(archive_root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f"[아카이브] 보관 중 {len(dates)}일치")


def _rebuild_dist_archive():
    """date-picker 목록(archive/)을 캐시 전체의 최신 상태로 맞춥니다.
    미국만 갱신한 조립(--archive 없이)에서도 날짜 목록은 그대로 보여야 합니다."""
    archive_root = os.path.join(config.CACHE_DIR, "archive")
    dist_archive = os.path.join(config.OUT_DIR, "archive")
    if os.path.exists(dist_archive):
        shutil.rmtree(dist_archive)
    if os.path.isdir(archive_root):
        shutil.copytree(archive_root, dist_archive, ignore=shutil.ignore_patterns(PLACEHOLDER_MARKER))


def run(archive: bool):
    os.makedirs(config.OUT_DIR, exist_ok=True)
    _copy_kr()
    _copy_us()
    if archive:
        _archive()
    _ensure_us_archived()
    _strip_legacy_chart_dirs()
    _prune_and_manifest()
    _rebuild_dist_archive()
    print(f"[조립] 완료 → {config.OUT_DIR}/")


if __name__ == "__main__":
    run(archive="--archive" in sys.argv)
