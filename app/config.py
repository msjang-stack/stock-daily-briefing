# app/config.py
import os


def _int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID") or None
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET") or None
DART_API_KEY = os.environ.get("DART_API_KEY") or None

# 차트를 준비할 종목 수 (거래대금 상위 기준). 나머지는 검색·목록에만 나옵니다.
CHART_LIMIT = _int("CHART_LIMIT", 800)
# 차트에 담을 거래일 수
CHART_DAYS = _int("CHART_DAYS", 60)
# 화면에 보여줄 목록 길이
TOP_N = _int("TOP_N", 10)
# 내일 주목할 종목 수
WATCH_N = _int("WATCH_N", 4)
# 뉴스를 조회할 종목 수 (주목 종목 + 주요 종목 상위)
NEWS_STOCKS = _int("NEWS_STOCKS", 24)

OUT_DIR = os.environ.get("OUT_DIR", "dist")
CACHE_DIR = os.environ.get("CACHE_DIR", "cache")

# 국내·미국 빌드는 서로를 몰라도 되도록 각자 자기 결과물을 여기 자기 자리에만
# 씁니다. assemble.py가 이 둘을 모아 OUT_DIR로 합칩니다.
KR_CACHE_DIR = os.path.join(CACHE_DIR, "kr_latest")
US_CACHE_DIR = os.path.join(CACHE_DIR, "us_latest")
ISSUE_CACHE_DIR = os.path.join(CACHE_DIR, "issue_latest")

# 유니버스 필터
MIN_PRICE = _int("MIN_PRICE", 1000)
MIN_VALUE = _int("MIN_VALUE", 1_000_000_000)        # 당일 거래대금 하한(원)
MIN_MARKET_CAP = _int("MIN_MARKET_CAP", 50_000_000_000)
# '내일 주목할 종목'의 거래대금 하한. 너무 얇은 종목은 신호가 나와도 사고팔기 어렵습니다.
MIN_WATCH_VALUE = _int("MIN_WATCH_VALUE", 30_000_000_000)   # 300억원

# 날짜별 페이지를 며칠치 보관할지. dist/archive/{날짜}/ 로 쌓이며 Actions 캐시에 보관됩니다.
ARCHIVE_DAYS = _int("ARCHIVE_DAYS", 30)

WEEKDAY = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# 미국 시장 유니버스(S&P500)에서 차트를 준비할 종목 수. 배치 시세가 막혀 있어
# 종목마다 개별 호출하므로 코스피·코스닥만큼 크게 잡지는 않습니다.
US_CHART_LIMIT = _int("US_CHART_LIMIT", 503)
US_WATCH_VALUE = _int("US_WATCH_VALUE", 20_000_000)  # 내일 주목할 종목의 당일 거래대금 하한(달러)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/",
}
