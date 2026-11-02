"""로또 당첨번호 주간 빌드.

smok95.github.io/lotto (동행복권 공개 데이터 미러, 매주 토요일 추첨 직후 갱신)에서
최신/전체 회차를 받아 앱이 쓰는 정적 JSON 두 개를 만든다.

출력 (dist/lotto/ 아래, 기존 stock-daily-briefing dist에 얹는 방식):
  - latest.json : 최신 회차 + 최근 20회차
  - stats.json  : 전체/최근100회 번호별 출현 횟수

stock-daily-briefing 인프라에 붙일 때는 다른 빌드와 마찬가지로
assemble 단계 전에 실행해 dist/lotto/를 채우면 된다.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = 'https://smok95.github.io/lotto/results'
KST = timezone(timedelta(hours=9))


def fetch(path: str):
    req = urllib.request.Request(f'{BASE}/{path}', headers={'User-Agent': 'lotto-hub-build'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def shrink(d: dict) -> dict:
    return {
        'draw_no': d['draw_no'],
        'numbers': d['numbers'],
        'bonus_no': d['bonus_no'],
        'date': d['date'][:10],
    }


def main() -> None:
    all_draws = fetch('all.json')
    all_draws.sort(key=lambda d: d['draw_no'])
    latest = all_draws[-1]
    updated = datetime.now(KST).strftime('%Y-%m-%d %H:%M')

    latest_out = {
        'updated': updated,
        'latest': {
            **shrink(latest),
            'firstPrize': latest['divisions'][0].get('prize', 0),
            'firstWinners': latest['divisions'][0].get('winners', 0),
            'totalSales': latest.get('total_sales_amount', 0),
            'auto': latest.get('winners_combination', {}).get('auto', 0),
            'manual': latest.get('winners_combination', {}).get('manual', 0),
        },
        'recent': [shrink(d) for d in reversed(all_draws[-20:])],
    }

    freq = {str(n): 0 for n in range(1, 46)}
    for d in all_draws:
        for n in d['numbers']:
            freq[str(n)] += 1
    freq100 = {str(n): 0 for n in range(1, 46)}
    for d in all_draws[-100:]:
        for n in d['numbers']:
            freq100[str(n)] += 1

    stats_out = {
        'updated': updated,
        'drawCount': len(all_draws),
        'lastDrawNo': latest['draw_no'],
        'freqAll': freq,
        'freqRecent100': freq100,
    }

    outdir = os.path.join('dist', 'lotto')
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump(latest_out, f, ensure_ascii=False)
    with open(os.path.join(outdir, 'stats.json'), 'w', encoding='utf-8') as f:
        json.dump(stats_out, f, ensure_ascii=False)
    print(f"draw {latest['draw_no']} ({latest['date'][:10]}), {len(all_draws)} draws -> {outdir}")


if __name__ == '__main__':
    main()
