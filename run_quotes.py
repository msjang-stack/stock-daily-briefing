# run_quotes.py — 국제 시세만 수집합니다. 국내·미국·이슈 빌드는 전혀 몰라도 됩니다.
#   python run_quotes.py   →   cache/quotes_latest/ 생성 (dist/로 합치려면 assemble.py 실행)
import sys
import traceback

from app import quotes_build

if __name__ == "__main__":
    try:
        sys.exit(quotes_build.run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
