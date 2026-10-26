# run_issues.py — 시장 이슈만 모읍니다. 국내·미국 빌드는 전혀 몰라도 됩니다.
#   python run_issues.py   →   cache/issue_latest/ 생성 (dist/로 합치려면 assemble.py 실행)
import sys
import traceback

from app import issue_build

if __name__ == "__main__":
    try:
        sys.exit(issue_build.run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
