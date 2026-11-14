import os
import re
import json
import time
import html
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

# ==========================================
# [나만의 세이브티커 v9.1 - 웹 대시보드 전용 에디션 (텔레그램 발송 제거)]
# ==========================================

# 1. 미국 거시경제 공식 발표치 (curr: 이번 발표치, prev: 직전 발표치)
MACRO_OFFICIAL = {
    "FOMC": {
        "display": "3.75~4.00%",
        "curr": 4.00,
        "prev": 4.00,
        "date": "2026.10"
    },
    "CPI": {
        "display": "3.7% (YoY)",
        "curr": 3.7,
        "prev": 3.5,
        "date": "10월 MoM +0.4%"
    },
    "PPI": {
        "display": "6.5% (YoY)",
        "curr": 6.5,
        "prev": 6.8,
        "date": "10월 MoM +0.3%"
    }
}

# 2. 감시 기업 및 티커 설정
KR_COMPANIES = ["삼성전자", "SK하이닉스", "현대차", "한화에어로스페이스", "NAVER", "HPSP"]
US_TICKERS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "PLTR"]
IGNORE_WORDS = ["부고", "인사", "포토", "동정", "모집", "이벤트", "할인", "광고"]

# 3-A. 🇰🇷 국내 증시 전용 9대 섹터
KR_SECTORS_CONFIG = [
    {
        "id": "KR_SEMI",
        "name": "반도체",
        "rss_query": "반도체 OR HBM OR SK하이닉스 OR 삼성전자",
        "search_kw": "반도체",
        "keywords": ["반도체", "HBM", "SK하이닉스", "삼성전자", "HPSP", "파운드리", "메모리", "CXL", "유리기판", "전공정", "후공정", "온디바이스"]
    },
    {
        "id": "KR_SHIP",
        "name": "조선·방산",
        "rss_query": "조선 수주 OR 방산 수출 OR 한화에어로스페이스",
        "search_kw": "한화에어로스페이스",
        "keywords": ["조선", "방산", "한화에어로스페이스", "HD현대", "한화오션", "수주", "LNG선", "K방산", "현대로템", "LIG넥스원", "잠수함", "미사일"]
    },
    {
        "id": "KR_BATT",
        "name": "2차전지",
        "rss_query": "2차전지 OR 배터리 OR 에코프로 OR LG에너지솔루션",
        "search_kw": "2차전지",
        "keywords": ["2차전지", "배터리", "LG에너지솔루션", "에코프로", "양극재", "전고체", "리튬", "ESS", "포스코퓨처엠", "삼성SDI", "음극재"]
    },
    {
        "id": "KR_MOBIL",
        "name": "모빌리티",
        "rss_query": "현대차 OR 기아 OR 자동차 수출",
        "search_kw": "현대차",
        "keywords": ["현대차", "기아", "하이브리드", "전기차", "완성차", "모빌리티", "자율주행", "현대모비스", "부품", "수출"]
    },
    {
        "id": "KR_BIO",
        "name": "바이오·제약",
        "rss_query": "제약 바이오 OR 삼성바이오로직스 OR 셀트리온",
        "search_kw": "바이오",
        "keywords": ["바이오", "제약", "삼성바이오로직스", "셀트리온", "임상", "신약", "기술수출", "알테오젠", "유한양행", "CDMO", "비만치료제"]
    },
    {
        "id": "KR_IT",
        "name": "IT·플랫폼",
        "rss_query": "네이버 OR 카카오 OR 국내 AI 소프트웨어",
        "search_kw": "네이버",
        "keywords": ["네이버", "NAVER", "카카오", "AI", "인공지능", "플랫폼", "클라우드", "소프트웨어", "게임", "크래프톤", "보안"]
    },
    {
        "id": "KR_FIN",
        "name": "금융·밸류업",
        "rss_query": "금융지주 밸류업 OR 은행 증권 배당",
        "search_kw": "금융지주",
        "keywords": ["금융", "은행", "증권", "보험", "밸류업", "배당", "자사주", "KB금융", "신한지주", "메리츠", "지주사", "주주환원"]
    },
    {
        "id": "KR_MAT",
        "name": "소재·철강",
        "rss_query": "포스코 OR 철강 비철금속 OR 석유화학",
        "search_kw": "포스코",
        "keywords": ["철강", "포스코", "POSCO", "고려아연", "비철금속", "화학", "정유", "구리", "알루미늄", "희토류", "소재"]
    },
    {
        "id": "KR_CONS",
        "name": "K뷰티·엔터",
        "rss_query": "K뷰티 화장품 OR 하이브 엔터테인먼트",
        "search_kw": "화장품",
        "keywords": ["화장품", "뷰티", "엔터", "하이브", "K팝", "면세", "음식료", "삼양식품", "아모레퍼시픽", "에이피알", "카지노"]
    }
]

# 3-B. 🇺🇸 해외(미국) 증시 전용 9대 섹터
US_SECTORS_CONFIG = [
    {
        "id": "US_AISEMI",
        "name": "AI·반도체",
        "rss_query": "Nvidia OR AI chip OR semiconductor stock",
        "search_kw": "NVDA",
        "keywords": ["엔비디아", "NVDA", "브로드컴", "AVGO", "AMD", "TSMC", "TSM", "마이크론", "MU", "ASML", "ARM", "AI칩", "반도체", "GPU"]
    },
    {
        "id": "US_BIGTECH",
        "name": "빅테크·클라우드",
        "rss_query": "Microsoft OR Apple OR Palantir OR cloud AI",
        "search_kw": "MSFT",
        "keywords": ["마이크로소프트", "MSFT", "애플", "AAPL", "아마존", "AMZN", "구글", "GOOGL", "메타", "META", "팔란티어", "PLTR", "클라우드", "데이터센터"]
    },
    {
        "id": "US_SPACE",
        "name": "우주·방위산업",
        "rss_query": "SpaceX OR Rocket Lab OR US defense aerospace stock",
        "search_kw": "RKLB",
        "keywords": ["로켓랩", "RKLB", "스페이스X", "보잉", "BA", "록히드마틴", "LMT", "우주", "위성", "방위", "항공", "드론"]
    },
    {
        "id": "US_POWER",
        "name": "원전·전력망",
        "rss_query": "nuclear power AI data center OR Vistra OR Oklo",
        "search_kw": "OKLO",
        "keywords": ["원전", "SMR", "오클로", "OKLO", "비스트라", "VST", "컨스텔레이션", "CEG", "전력망", "변압기", "에너지", "유틸리티"]
    },
    {
        "id": "US_HEALTH",
        "name": "비만·헬스케어",
        "rss_query": "Eli Lilly OR Novo Nordisk OR US biotech FDA",
        "search_kw": "LLY",
        "keywords": ["일라이릴리", "LLY", "노보노디스크", "NVO", "비만치료제", "유나이티드헬스", "UNH", "FDA", "임상", "바이오텍", "헬스케어"]
    },
    {
        "id": "US_ROBOT",
        "name": "로봇·자율주행",
        "rss_query": "Tesla robotaxi OR humanoid robot autonomous",
        "search_kw": "TSLA",
        "keywords": ["테슬라", "TSLA", "로보택시", "자율주행", "휴머노이드", "로봇", "FSD", "웨이모", "리비안", "RIVN", "전기차"]
    },
    {
        "id": "US_FIN",
        "name": "월가 금융",
        "rss_query": "JPMorgan OR Goldman Sachs OR Wall Street bank",
        "search_kw": "JPM",
        "keywords": ["JP모건", "골드만삭스", "모건스탠리", "뱅크오브아메리카", "블랙록", "국채", "금리", "월가", "투자은행", "버크셔"]
    },
    {
        "id": "US_ENERGY",
        "name": "에너지·원자재",
        "rss_query": "Exxon OR Chevron OR crude oil gold market",
        "search_kw": "XOM",
        "keywords": ["엑슨모빌", "셰브론", "유가", "원유", "천연가스", "셰일", "금값", "구리", "광산", "에너지", "정유"]
    },
    {
        "id": "US_CRYPTO",
        "name": "크립토·핀테크",
        "rss_query": "Bitcoin ETF OR Coinbase OR MicroStrategy stock",
        "search_kw": "COIN",
        "keywords": ["비트코인", "코인베이스", "COIN", "마이크로스트래티지", "MSTR", "로빈후드", "HOOD", "이더리움", "ETF", "핀테크", "스테이블코인"]
    }
]

# ==========================================

DART_API_KEY = os.environ.get("DART_API_KEY")
HISTORY_FILE = "sent_news.json"
FEED_DATA_FILE = "feed_data.json"


def get_kst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def translate_en_to_ko(text):
    if not text:
        return text
    try:
        encoded = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
        translated = "".join([part[0] for part in data[0] if part[0]])
        return translated if translated else text
    except Exception:
        return text


def classify_impact(title):
    hot_words = [
        "속보", "긴급", "급등", "급락", "실적", "어닝", "공급계약", "유상증자",
        "금리", "인하", "인상", "파월", "트럼프", "SURGE", "PLUNGE", "BREAKING",
        "EARNINGS", "UPGRADE", "DOWNGRADE", "TARGET", "BUY", "SELL"
    ]
    if any(w in title.upper() for w in hot_words):
        return "🔥 주요속보"
    return "📰 일반"


def strip_html_tags(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_yahoo_quote_and_120d(sym, decimals=2):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        encoded_sym = urllib.parse.quote(sym)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_sym}?interval=1d&range=8mo"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))

        result = data["chart"]["result"][0]
        meta = result["meta"]
        timestamps = result.get("timestamp", [])
        quote = result["indicators"]["quote"][0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])

        candles = []
        for i in range(len(timestamps)):
            if i < len(closes) and closes[i] is not None and opens[i] is not None and highs[i] is not None and lows[i] is not None:
                dt_str = datetime.datetime.utcfromtimestamp(timestamps[i]).strftime("%m/%d")
                candles.append([
                    dt_str,
                    round(float(opens[i]), decimals),
                    round(float(highs[i]), decimals),
                    round(float(lows[i]), decimals),
                    round(float(closes[i]), decimals)
                ])

        candles_120 = candles[-120:]

        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if len(candles_120) >= 2 and (prev is None or prev == price):
            prev = candles_120[-2][4]

        if price is not None and prev:
            diff = price - prev
            pct = (diff / prev) * 100
            fmt = f"{{:,.{decimals}f}}"
            dfmt = f"{{:+,.{decimals}f}}"
            return {
                "price": fmt.format(price),
                "diff": dfmt.format(diff),
                "pct": f"{pct:+.2f}%",
                "up": diff >= 0,
                "candles": candles_120
            }
    except Exception as e:
        print(f"[Quote120-{sym}] 오류: {e}")
    return {"price": "-", "diff": "0.00", "pct": "0.00%", "up": True, "candles": []}


def evaluate_macro_delta(key, cfg, extra_note=""):
    curr = float(cfg["curr"])
    prev = float(cfg["prev"])
    diff = round(curr - prev, 4)

    if abs(diff) < 1e-6:
        status_cls = "freeze"
        status_text = f"동결 ({cfg['date']})" if key == "FOMC" else f"동결 (직전 {prev:.1f}%)"
    elif diff > 0:
        status_cls = "up"
        if key == "FOMC":
            bp = int(round(diff * 100))
            status_text = f"▲ +{diff:.2f}%p (+{bp}bp) 인상"
        else:
            status_text = f"▲ +{diff:.1f}%p 상승 (직전 {prev:.1f}%)"
    else:
        status_cls = "down"
        if key == "FOMC":
            bp = int(round(abs(diff) * 100))
            status_text = f"▼ {diff:.2f}%p (-{bp}bp) 인하"
        else:
            status_text = f"▼ {diff:.1f}%p 하락 (직전 {prev:.1f}%)"

    return {
        "price": cfg["display"],
        "status_text": status_text,
        "status_cls": status_cls,
        "sub_note": extra_note if extra_note else cfg["date"]
    }


def fetch_all_macro_dashboard():
    us10y = fetch_yahoo_quote_and_120d("^TNX", 2)
    ten_y_str = f"미10Y {us10y['price']}%" if us10y["price"] != "-" else "실효 3.88%"

    items_meta = [
        ("KOSPI", "🇰🇷 코스피 (KOSPI)", "^KS11", 2),
        ("KOSDAQ", "🇰🇷 코스닥 (KOSDAQ)", "^KQ11", 2),
        ("DOW", "🇺🇸 다우존스 (DOW)", "^DJI", 2),
        ("NASDAQ", "🇺🇸 나스닥 (NASDAQ)", "^IXIC", 2),
        ("USDKRW", "🇰🇷 원/달러 (USD/KRW)", "KRW=X", 2),
        ("EURUSD", "🇪🇺 유로/달러 (EUR/USD)", "EURUSD=X", 4),
        ("USDJPY", "🇯🇵 달러/엔 (USD/JPY)", "JPY=X", 2),
        ("GBPUSD", "🇬🇧 파운드/달러 (GBP/USD)", "GBPUSD=X", 4),
        ("USDCHF", "🇨🇭 달러/프랑 (USD/CHF)", "CHF=X", 4),
        ("USDCAD", "🇨🇦 달러/캐나다 (USD/CAD)", "CAD=X", 4),
        ("OIL", "🛢 WTI 유가 ($/bbl)", "CL=F", 2),
        ("GOLD", "🥇 국제 금 ($/oz)", "GC=F", 2),
        ("SILVER", "🥈 국제 은 ($/oz)", "SI=F", 2),
    ]

    board = {}
    chart_store = {}

    for key, label, sym, dec in items_meta:
        q = fetch_yahoo_quote_and_120d(sym, dec)
        board[key] = q
        chart_store[key] = {
            "label": label,
            "sym": sym,
            "dec": dec,
            "candles": q.get("candles", [])
        }

    board["FOMC"] = evaluate_macro_delta("FOMC", MACRO_OFFICIAL["FOMC"], ten_y_str)
    board["CPI"] = evaluate_macro_delta("CPI", MACRO_OFFICIAL["CPI"])
    board["PPI"] = evaluate_macro_delta("PPI", MACRO_OFFICIAL["PPI"])

    return board, chart_store


def compute_market_sector_heatmap(sectors_cfg, feed_items, market_scope="KR"):
    sector_stats = []
    stopwords = {
        "오늘", "전망", "특징주", "관련주", "주가", "상승", "하락", "마감", "장중",
        "코스피", "코스닥", "시장", "투자", "분석", "속보", "뉴스", "기업", "한국",
        "미국", "증시", "최대", "신고가", "목표가", "리포트", "STOCK", "MARKET", "NEWS", "WHY", "WHAT"
    }

    for sec in sectors_cfg:
        matched_titles = []
        kw_counter = Counter()

        for item in feed_items[:150]:
            cat = item.get("category", "")
            if market_scope == "KR" and cat == "US":
                continue
            if market_scope == "US" and cat in ("KR", "DART"):
                continue

            full_text = f"{item.get('tag', '')} {item.get('title', '')} {item.get('sub_title', '')}"
            upper_text = full_text.upper()
            hit_kws = [kw for kw in sec["keywords"] if kw.upper() in upper_text]
            if hit_kws:
                matched_titles.append(item.get("title", ""))
                for hk in hit_kws:
                    kw_counter[hk] += 2

        try:
            encoded_q = urllib.parse.quote(sec["rss_query"])
            if market_scope == "KR":
                rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=ko&gl=KR&ceid=KR:ko"
            else:
                rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"

            req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=7) as res:
                root = ET.fromstring(res.read())
            rss_items = root.findall(".//item")[:14]

            for it in rss_items:
                raw_t = (it.find("title").text or "").rsplit(" - ", 1)[0]
                if any(w in raw_t for w in IGNORE_WORDS):
                    continue
                matched_titles.append(raw_t)
                for kw in sec["keywords"]:
                    if kw.upper() in raw_t.upper():
                        kw_counter[kw] += 1
                tokens = re.findall(r"[가-힣A-Za-z0-9]{2,10}", raw_t)
                for tk in tokens:
                    if tk.upper() not in stopwords and not tk.isdigit():
                        kw_counter[tk] += 1
        except Exception as e:
            print(f"[Sector-{sec['id']}] 스캔 지연: {e}")

        unique_titles = list(dict.fromkeys(matched_titles))
        info_count = len(unique_titles)

        sample_list = unique_titles[:2]
        if market_scope == "US" and sample_list:
            sample_list = [translate_en_to_ko(t) for t in sample_list]

        top_kws = []
        for k, cnt in kw_counter.most_common(12):
            if k != sec["name"] and len(top_kws) < 5:
                top_kws.append({"word": k, "count": cnt})
        if not top_kws:
            top_kws = [{"word": sec["keywords"][0], "count": 1}]

        sector_stats.append({
            "id": sec["id"],
            "market": market_scope,
            "name": sec["name"],
            "rss_query": sec["rss_query"],
            "search_kw": sec["search_kw"],
            "keywords": sec["keywords"],
            "count": info_count,
            "top_keywords": top_kws,
            "sample_titles": sample_list
        })

    sector_stats.sort(key=lambda x: x["count"], reverse=True)

    total = len(sector_stats)
    for rank_idx, s in enumerate(sector_stats):
        s["rank"] = rank_idx + 1
        if rank_idx < max(1, total // 3):
            s["level"] = "high"
        elif rank_idx >= total - max(1, total // 3):
            s["level"] = "low"
        else:
            s["level"] = "mid"

    return sector_stats


def fetch_finviz_news_only(ticker):
    url = f"https://finviz.com/quote.ashx?t={ticker}&p=d"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finviz.com/"
    }
    news_list = []
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as res:
            page_html = res.read().decode("utf-8", errors="ignore")

        news_match = re.search(r'<table[^>]*id="news-table"[^>]*>(.*?)</table>', page_html, re.S)
        if news_match:
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', news_match.group(1), re.S)
            for row in rows[:4]:
                link_m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', row, re.S)
                source_m = re.search(r'<span[^>]*>(.*?)</span>', row, re.S)
                if not link_m:
                    continue
                href = html.unescape(link_m.group(1)).strip()
                if href.startswith("/"):
                    href = f"https://finviz.com{href}"
                en_title = strip_html_tags(link_m.group(2))
                source_name = strip_html_tags(source_m.group(1)) if source_m else "Finviz"
                source_name = source_name.strip("()")

                if not en_title:
                    continue
                ko_title = translate_en_to_ko(en_title)
                news_list.append({
                    "category": "US",
                    "tag": f"${ticker}",
                    "press": f"Finviz · {source_name}",
                    "title": ko_title,
                    "sub_title": en_title if ko_title != en_title else "",
                    "link": href,
                    "impact": classify_impact(en_title)
                })
    except Exception as e:
        print(f"[Finviz-{ticker}] 수집 건너뜀: {e}")

    return news_list


def fetch_yahoo_us_news(ticker):
    rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    results = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            root = ET.fromstring(res.read())
        for item in root.findall(".//item")[:3]:
            en_title = item.find("title").text or ""
            link = item.find("link").text or ""
            ko_title = translate_en_to_ko(en_title)
            results.append({
                "category": "US",
                "tag": f"${ticker}",
                "press": "Yahoo Finance",
                "title": ko_title,
                "sub_title": en_title if ko_title != en_title else "",
                "link": link,
                "impact": classify_impact(en_title)
            })
    except Exception as e:
        print(f"[Yahoo-{ticker}] 수집 오류: {e}")
    return results


def fetch_google_news(keyword, category):
    encoded_kw = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
    results = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            root = ET.fromstring(res.read())
        for item in root.findall(".//item")[:4]:
            raw_title = item.find("title").text or ""
            link = item.find("link").text or ""
            if any(w in raw_title for w in IGNORE_WORDS):
                continue
            if " - " in raw_title:
                title, press = raw_title.rsplit(" - ", 1)
            else:
                title, press = raw_title, "언론사"
            results.append({
                "category": category,
                "tag": keyword,
                "press": press,
                "title": title,
                "sub_title": "",
                "link": link,
                "impact": classify_impact(title)
            })
    except Exception as e:
        print(f"[{keyword}] 수집 오류: {e}")
    return results


def fetch_dart():
    if not DART_API_KEY:
        return []
    today_kst = get_kst_now().strftime("%Y%m%d")
    api_url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART_API_KEY}&bgn_de={today_kst}&end_de={today_kst}&page_count=100"
    results = []
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))
        if data.get("status") != "000":
            return []
        for item in data.get("list", []):
            corp = item.get("corp_name", "")
            report = item.get("report_nm", "")
            rcp = item.get("rcept_no", "")
            if any(k.upper() in corp.upper() for k in KR_COMPANIES):
                results.append({
                    "category": "DART",
                    "tag": corp,
                    "press": "금융감독원 DART",
                    "title": f"[공시] {report}",
                    "sub_title": "",
                    "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}",
                    "impact": "🚨 공식공시"
                })
    except Exception as e:
        print(f"[DART] 오류: {e}")
    return results


def render_tile(box_id, label, sub_label, info, compact=False):
    cls = "up" if info.get("up", True) else "down"
    arrow = "▲ " if info.get("up", True) else "▼ "
    price = html.escape(str(info.get("price", "-")))
    diff = html.escape(str(info.get("diff", "")))
    pct = html.escape(str(info.get("pct", "")))
    card_cls = "idx-card chartable compact" if compact else "idx-card chartable"
    return (
        f'<div class="{card_cls}" id="idx-{box_id}" data-chart-key="{box_id}">'
        f'<div class="idx-head"><span class="idx-name">{label}</span><span class="idx-sub">{sub_label} 📈</span></div>'
        f'<div class="idx-body"><span class="idx-price">{price}</span><span class="idx-chg {cls}">{arrow}{diff} ({pct})</span></div>'
        f'</div>'
    )


def render_macro_policy_tile(box_id, label, sub_label, info):
    price = html.escape(str(info.get("price", "-")))
    status_text = html.escape(str(info.get("status_text", "")))
    status_cls = html.escape(str(info.get("status_cls", "freeze")))
    sub_note = html.escape(str(info.get("sub_note", sub_label)))
    return (
        f'<div class="idx-card compact" id="idx-{box_id}">'
        f'<div class="idx-head"><span class="idx-name">{label}</span><span class="idx-sub">{sub_note}</span></div>'
        f'<div class="idx-body"><span class="idx-price">{price}</span><span class="idx-chg {status_cls}">{status_text}</span></div>'
        f'</div>'
    )


def render_sector_strip(sector_stats, scope):
    cells = []
    for idx, sec in enumerate(sector_stats):
        lvl = sec["level"]
        name = html.escape(sec["name"])
        cnt = sec["count"]
        rank = sec["rank"]
        q = html.escape(sec["search_kw"])
        cells.append(
            f'<div class="sec-cell lvl-{lvl}" data-scope="{scope}" data-sec-idx="{idx}" onclick="searchSectorKeyword(\'{q}\')">'
            f'<div class="sec-rank">{rank}위</div>'
            f'<div class="sec-cell-name">{name}</div>'
            f'<div class="sec-cell-cnt">{cnt}건</div>'
            f'</div>'
        )
    return "".join(cells)


def build_saveticker_html(feed_items, board, chart_store, kr_sectors, us_sectors, updated_time):
    row_kr = render_tile("KOSPI", "🇰🇷 코스피", "KOSPI", board.get("KOSPI", {})) + render_tile("KOSDAQ", "🇰🇷 코스닥", "KOSDAQ", board.get("KOSDAQ", {}))
    row_us = render_tile("DOW", "🇺🇸 다우존스", "DOW JONES", board.get("DOW", {})) + render_tile("NASDAQ", "🇺🇸 나스닥", "NASDAQ", board.get("NASDAQ", {}))
    row_fx = (
        render_tile("USDKRW", "🇰🇷 원/달러", "USD/KRW", board.get("USDKRW", {}), compact=True)
        + render_tile("EURUSD", "🇪🇺 유로/달러", "EUR/USD", board.get("EURUSD", {}), compact=True)
        + render_tile("USDJPY", "🇯🇵 달러/엔", "USD/JPY", board.get("USDJPY", {}), compact=True)
        + render_tile("GBPUSD", "🇬🇧 파운드/달러", "GBP/USD", board.get("GBPUSD", {}), compact=True)
        + render_tile("USDCHF", "🇨🇭 달러/프랑", "USD/CHF", board.get("USDCHF", {}), compact=True)
        + render_tile("USDCAD", "🇨🇦 달러/캐나다", "USD/CAD", board.get("USDCAD", {}), compact=True)
    )
    row_cmd = (
        render_tile("OIL", "🛢 WTI 유가", "$/bbl", board.get("OIL", {}), compact=True)
        + render_tile("GOLD", "🥇 국제 금", "$/oz", board.get("GOLD", {}), compact=True)
        + render_tile("SILVER", "🥈 국제 은", "$/oz", board.get("SILVER", {}), compact=True)
    )
    row_macro = (
        render_macro_policy_tile("FOMC", "🏛 FOMC 기준금리", "FED RATE", board.get("FOMC", {}))
        + render_macro_policy_tile("CPI", "📊 미국 CPI", "소비자물가", board.get("CPI", {}))
        + render_macro_policy_tile("PPI", "🏭 미국 PPI", "생산자물가", board.get("PPI", {}))
    )

    kr_sector_strip = render_sector_strip(kr_sectors, "KR")
    us_sector_strip = render_sector_strip(us_sectors, "US")

    card_parts = []
    for item in feed_items[:150]:
        badge_class = "hot" if ("속보" in item["impact"] or "공시" in item["impact"]) else "normal"
        safe_title = html.escape(item["title"])
        safe_sub = html.escape(item.get("sub_title", ""))
        safe_tag = html.escape(item["tag"])
        safe_press = html.escape(item["press"])
        safe_time = html.escape(item.get("time", ""))
        safe_link = html.escape(item["link"])
        sub_html = f'<div class="sub-title">{safe_sub}</div>' if safe_sub else ""
        data_text = f"{safe_tag.lower()} {safe_title.lower()} {safe_sub.lower()}"

        card_parts.append(
            f'<div class="news-card saved-card" data-cat="{item["category"]}" data-text="{data_text}">'
            f'<div class="card-top"><span class="badge {badge_class}">{item["impact"]}</span>'
            f'<span class="ticker-tag">{safe_tag}</span><span class="meta">{safe_press} · {safe_time}</span></div>'
            f'<a href="{safe_link}" target="_blank" class="news-title">{safe_title}</a>{sub_html}</div>'
        )

    cards_html = "\n".join(card_parts) if card_parts else "<p style='color:#8b949e;text-align:center;'>수집된 뉴스가 없습니다.</p>"
    chart_json_str = json.dumps(chart_store, ensure_ascii=False)
    sector_map_json = json.dumps({"KR": kr_sectors, "US": us_sectors}, ensure_ascii=False)

    template = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My SaveTicker - 국내·해외 실시간 섹터 히트맵 & 증시 대시보드</title>
<style>
  body { background-color: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, "Pretendard", sans-serif; margin: 0; padding: 0; }
  .header { background: #161b22; border-bottom: 1px solid #30363d; padding: 14px 20px; position: sticky; top: 0; z-index: 100; }
  .header-inner { max-width: 920px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
  .logo { font-size: 20px; font-weight: 800; color: #58a6ff; letter-spacing: -0.5px; cursor: pointer; }
  .updated { font-size: 12px; color: #8b949e; }
  .container { max-width: 920px; margin: 16px auto; padding: 0 16px; }

  .sec-label { font-size: 11.5px; font-weight: 700; color: #8b949e; margin: 14px 0 6px; letter-spacing: -0.2px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
  @media (max-width: 640px) {
    .grid-3 { grid-template-columns: repeat(2, 1fr); }
  }

  .idx-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 12px 15px; display: flex; flex-direction: column; gap: 6px; transition: border-color 0.2s; }
  .idx-card.chartable { cursor: crosshair; }
  .idx-card.chartable:hover { border-color: #58a6ff; background: #1c222b; }
  .idx-card.compact { padding: 10px 12px; gap: 4px; }
  .idx-head { display: flex; justify-content: space-between; align-items: center; }
  .idx-name { font-size: 13px; font-weight: 700; color: #c9d1d9; }
  .idx-card.compact .idx-name { font-size: 12px; }
  .idx-sub { font-size: 10.5px; color: #8b949e; font-weight: 600; }
  .idx-body { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 4px; }
  .idx-price { font-size: 18px; font-weight: 800; color: #f0f6fc; letter-spacing: -0.3px; }
  .idx-card.compact .idx-price { font-size: 15px; }
  .idx-chg { font-size: 12px; font-weight: 700; }
  .idx-card.compact .idx-chg { font-size: 11px; }
  .idx-chg.up { color: #ff6b6b; }
  .idx-chg.down { color: #4dabf7; }
  .idx-chg.freeze { color: #3fb950; background: rgba(63, 185, 80, 0.14); padding: 2px 7px; border-radius: 6px; border: 1px solid rgba(63, 185, 80, 0.35); }

  .sector-legend { display: flex; gap: 10px; font-size: 11px; font-weight: 600; }
  .leg-dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }
  .sector-strip {
    display: grid;
    grid-template-columns: repeat(9, 1fr);
    border: 1px solid #30363d;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 10px;
    background: #161b22;
  }
  @media (max-width: 740px) {
    .sector-strip { grid-template-columns: repeat(3, 1fr); }
  }
  .sec-cell {
    position: relative;
    padding: 12px 5px 10px;
    text-align: center;
    border-right: 1px solid rgba(255, 255, 255, 0.12);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    cursor: pointer;
    transition: transform 0.15s, filter 0.15s;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 3px;
    min-height: 58px;
  }
  .sec-cell:last-child { border-right: none; }
  .sec-cell:hover { filter: brightness(1.2); z-index: 2; }
  .sec-rank { font-size: 9.5px; font-weight: 800; opacity: 0.75; letter-spacing: -0.2px; }
  .sec-cell.lvl-high {
    background: linear-gradient(180deg, rgba(35, 134, 54, 0.58) 0%, rgba(46, 160, 67, 0.36) 100%);
    color: #aff5b4;
  }
  .sec-cell.lvl-mid {
    background: rgba(48, 54, 61, 0.55);
    color: #c9d1d9;
  }
  .sec-cell.lvl-low {
    background: linear-gradient(180deg, rgba(218, 54, 51, 0.52) 0%, rgba(248, 81, 73, 0.30) 100%);
    color: #ffdcd7;
  }
  .sec-cell-name { font-size: 12px; font-weight: 800; letter-spacing: -0.3px; line-height: 1.2; word-break: keep-all; }
  .sec-cell-cnt { font-size: 10.5px; font-weight: 600; opacity: 0.85; }

  .sector-tooltip {
    position: fixed;
    z-index: 9999;
    width: 310px;
    max-width: calc(100vw - 24px);
    background: #161b22;
    border: 1px solid #3fb950;
    border-radius: 12px;
    padding: 12px 14px;
    box-shadow: 0 14px 36px rgba(0, 0, 0, 0.82);
    pointer-events: none;
    display: none;
  }
  .st-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #21262d; }
  .st-title { font-size: 13.5px; font-weight: 800; color: #f0f6fc; }
  .st-badge { font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px; }
  .st-badge.high { background: rgba(46, 160, 67, 0.25); color: #3fb950; }
  .st-badge.mid { background: rgba(139, 148, 158, 0.2); color: #c9d1d9; }
  .st-badge.low { background: rgba(248, 81, 73, 0.25); color: #ff7b72; }
  .st-sub { font-size: 11px; color: #8b949e; margin-bottom: 6px; font-weight: 600; }
  .st-kw-list { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }
  .st-kw { background: rgba(56, 139, 253, 0.16); border: 1px solid rgba(56, 139, 253, 0.35); color: #79c0ff; font-size: 11.5px; font-weight: 700; padding: 3px 8px; border-radius: 6px; }
  .st-headlines { font-size: 11px; color: #c9d1d9; line-height: 1.45; border-top: 1px solid #21262d; padding-top: 6px; }
  .st-headlines div { margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .chart-tooltip {
    position: fixed;
    z-index: 9999;
    width: 340px;
    max-width: calc(100vw - 24px);
    background: #161b22;
    border: 1px solid #58a6ff;
    border-radius: 12px;
    padding: 12px 14px;
    box-shadow: 0 14px 36px rgba(0, 0, 0, 0.75);
    pointer-events: none;
    display: none;
  }
  .ct-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .ct-title { font-size: 13px; font-weight: 800; color: #f0f6fc; }
  .ct-badge { font-size: 10.5px; color: #8b949e; background: #21262d; padding: 2px 7px; border-radius: 6px; }
  .ct-stats { display: flex; justify-content: space-between; font-size: 11px; color: #8b949e; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #21262d; }
  .ct-stats b { color: #e6edf3; }
  .ct-legend { display: flex; justify-content: space-between; font-size: 10px; color: #8b949e; margin-top: 4px; }

  .search-panel { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 12px; margin: 14px 0; }
  .search-wrap { display: flex; gap: 8px; margin-bottom: 10px; }
  .search-box { flex: 1; background: #0d1117; border: 1px solid #30363d; color: #fff; padding: 9px 14px; border-radius: 10px; font-size: 13.5px; outline: none; }
  .search-box:focus { border-color: #58a6ff; }
  .search-btn { background: #238636; border: none; color: #fff; padding: 9px 16px; border-radius: 10px; font-size: 13px; font-weight: 700; cursor: pointer; white-space: nowrap; }
  .search-btn:hover { background: #2ea043; }
  .tabs-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .tab { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 5px 11px; border-radius: 14px; font-size: 12px; cursor: pointer; }
  .tab.active { background: #1f6feb; border-color: #388bfd; color: #fff; font-weight: 600; }

  .live-banner { background: rgba(56, 139, 253, 0.12); border: 1px solid rgba(56, 139, 253, 0.4); border-radius: 10px; padding: 12px 16px; margin-bottom: 14px; display: none; justify-content: space-between; align-items: center; font-size: 13px; color: #79c0ff; }
  .reset-btn { background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 4px 10px; border-radius: 8px; cursor: pointer; font-size: 12px; }
  .news-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; transition: border-color 0.2s; }
  .news-card:hover { border-color: #58a6ff; }
  .card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
  .badge.hot { background: rgba(248, 81, 73, 0.18); color: #ff7b72; border: 1px solid rgba(248, 81, 73, 0.4); }
  .badge.live { background: rgba(46, 160, 67, 0.2); color: #3fb950; border: 1px solid rgba(46, 160, 67, 0.45); }
  .badge.normal { background: rgba(139, 148, 158, 0.15); color: #8b949e; }
  .ticker-tag { background: rgba(56, 139, 253, 0.15); color: #58a6ff; font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 6px; }
  .meta { font-size: 12px; color: #8b949e; margin-left: auto; }
  .news-title { color: #f0f6fc; text-decoration: none; font-size: 15px; font-weight: 600; line-height: 1.45; display: block; }
  .news-title:hover { color: #58a6ff; text-decoration: underline; }
  .sub-title { color: #8b949e; font-size: 12.5px; margin-top: 5px; line-height: 1.4; }
</style>
</head>
<body>
  <div class="header">
    <div class="header-inner">
      <div class="logo" onclick="resetSearch()">⚡ MY SAVETICKER</div>
      <div class="updated" id="liveClock">업데이트: __UPDATED_TIME__ (KST)</div>
    </div>
  </div>

  <div class="sector-tooltip" id="sectorTooltip"></div>

  <div class="chart-tooltip" id="chartTooltip">
    <div class="ct-header">
      <span class="ct-title" id="ctTitle">KOSPI</span>
      <span class="ct-badge">120일 일봉 · MA20</span>
    </div>
    <div class="ct-stats" id="ctStats"></div>
    <canvas id="ctCanvas" width="312" height="145"></canvas>
    <div class="ct-legend">
      <span id="ctStartDate">-</span>
      <span style="color:#eab308;">--- 20일 이평선</span>
      <span id="ctEndDate">-</span>
    </div>
  </div>

  <div class="container">
    <div class="sec-label" style="margin-top:0;">📈 주요 증시 지수 (마우스를 올리면 120일 일봉 차트 표시)</div>
    <div class="grid-2">__ROW_KR__</div>
    <div class="grid-2">__ROW_US__</div>

    <div class="sec-label">
      <span>🇰🇷 국내 실시간 주도 섹터 (활발한 순 정렬 · 호버 시 상승 키워드)</span>
      <span class="sector-legend">
        <span><i class="leg-dot" style="background:#2ea043;"></i>활발(상위)</span>
        <span><i class="leg-dot" style="background:#484f58;"></i>보통</span>
        <span><i class="leg-dot" style="background:#da3633;"></i>한산(하위)</span>
      </span>
    </div>
    <div class="sector-strip" id="krSectorStrip">__KR_SECTOR_STRIP__</div>

    <div class="sec-label">
      <span>🇺🇸 해외(미국) 실시간 주도 섹터 (활발한 순 정렬 · 호버 시 상승 키워드)</span>
      <span id="sectorSyncStatus" style="font-size:10.5px; color:#58a6ff;">실시간 순위 연동 중</span>
    </div>
    <div class="sector-strip" id="usSectorStrip">__US_SECTOR_STRIP__</div>

    <div class="search-panel">
      <div class="search-wrap">
        <input type="text" class="search-box" id="searchInput" autocapitalize="characters" autocorrect="off" spellcheck="false" onkeydown="if(event.key==='Enter') liveSearch()" onkeyup="localFilter()" placeholder="티커(NVDA) 또는 기업명(삼성전자, NAVER, HPSP) 검색...">
        <button class="search-btn" onclick="liveSearch()">실시간 검색</button>
      </div>
      <div class="tabs-row">
        <button class="tab active" onclick="filterCat('ALL', this)">전체 피드</button>
        <button class="tab" onclick="filterCat('DART', this)">🚨 DART 공시</button>
        <button class="tab" onclick="filterCat('KR', this)">🇰🇷 국내기업</button>
        <button class="tab" onclick="filterCat('US', this)">🇺🇸 미국주식(번역)</button>
      </div>
    </div>

    <div class="sec-label">💱 실시간 환율 (한국 원/달러 & 세계 5대 주요 통화 · 호버 시 120일 차트)</div>
    <div class="grid-3">__ROW_FX__</div>

    <div class="sec-label">⛏️ 원자재 선물 (WTI 유가 · 국제 금 · 국제 은 · 호버 시 120일 차트)</div>
    <div class="grid-3">__ROW_CMD__</div>

    <div class="sec-label">🏛️ 미국 통화정책 & 물가지표 (FOMC · CPI · PPI — 직전 발표치 대비)</div>
    <div class="grid-3">__ROW_MACRO__</div>

    <div class="sec-label" style="margin-top:18px;">📰 기업 속보 & DART 공시 피드</div>
    <div class="live-banner" id="liveBanner">
      <span id="liveStatusText">🔍 실시간 검색 결과</span>
      <button class="reset-btn" onclick="resetSearch()">기본 피드로 돌아가기</button>
    </div>
    <div id="liveResults"></div>
    <div id="feedList">
      __CARDS_HTML__
    </div>
  </div>

<script>
  let currentCat = 'ALL';
  const CHART_DATA = __CHART_JSON__;
  let SECTOR_MAP = __SECTOR_MAP_JSON__;

  function positionFloatingBox(box, e) {
    const pad = 14;
    const w = box.offsetWidth || 320;
    const h = box.offsetHeight || 200;
    let left = e.clientX + 16;
    let top = e.clientY + 16;

    if (left + w + pad > window.innerWidth) {
      left = Math.max(pad, e.clientX - w - 16);
    }
    if (top + h + pad > window.innerHeight) {
      top = Math.max(pad, e.clientY - h - 16);
    }
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
  }

  function renderSectorTooltip(scope, idx) {
    const list = SECTOR_MAP[scope] || [];
    const sec = list[idx];
    if (!sec) return false;
    const tip = document.getElementById('sectorTooltip');

    const marketBadge = scope === 'KR' ? '🇰🇷 국내' : '🇺🇸 해외';
    const levelLabel = sec.level === 'high' ? `🟢 ${sec.rank}위 · 매우 활발` : (sec.level === 'low' ? `🔴 ${sec.rank}위 · 한산` : `⚪ ${sec.rank}위 · 보통`);
    const borderCol = sec.level === 'high' ? '#3fb950' : (sec.level === 'low' ? '#ff7b72' : '#58a6ff');
    tip.style.borderColor = borderCol;

    const kwsHtml = (sec.top_keywords || []).map(k => `<span class="st-kw">🔥 ${k.word} (${k.count})</span>`).join('');
    const newsHtml = (sec.sample_titles || []).map(t => `<div>• ${t}</div>`).join('');

    tip.innerHTML = `
      <div class="st-head">
        <span class="st-title">${marketBadge} ${sec.name}</span>
        <span class="st-badge ${sec.level}">${levelLabel} (${sec.count}건)</span>
      </div>
      <div class="st-sub">📈 실시간 상승 키워드</div>
      <div class="st-kw-list">${kwsHtml}</div>
      ${newsHtml ? `<div class="st-headlines">${newsHtml}</div>` : ''}
    `;
    return true;
  }

  function renderSectorStripDOM(scope) {
    const containerId = scope === 'KR' ? 'krSectorStrip' : 'usSectorStrip';
    const container = document.getElementById(containerId);
    const list = SECTOR_MAP[scope] || [];
    if (!container || list.length === 0) return;

    container.innerHTML = list.map((sec, idx) => `
      <div class="sec-cell lvl-${sec.level}" data-scope="${scope}" data-sec-idx="${idx}" onclick="searchSectorKeyword('${sec.search_kw.replace(/'/g, "\\'")}')">
        <div class="sec-rank">${sec.rank}위</div>
        <div class="sec-cell-name">${sec.name}</div>
        <div class="sec-cell-cnt">${sec.count}건</div>
      </div>
    `).join('');

    bindSectorHoverEvents();
  }

  function bindSectorHoverEvents() {
    const tip = document.getElementById('sectorTooltip');
    document.querySelectorAll('.sec-cell').forEach(cell => {
      const scope = cell.dataset.scope;
      const idx = parseInt(cell.dataset.secIdx, 10);

      cell.onmouseenter = (e) => {
        if (renderSectorTooltip(scope, idx)) {
          tip.style.display = 'block';
          positionFloatingBox(tip, e);
        }
      };
      cell.onmousemove = (e) => {
        if (tip.style.display === 'block') {
          positionFloatingBox(tip, e);
        }
      };
      cell.onmouseleave = () => {
        tip.style.display = 'none';
      };
    });
  }

  async function refreshLiveSectorRankings() {
    const statusEl = document.getElementById('sectorSyncStatus');
    if (statusEl) statusEl.textContent = '🔄 섹터 활동성 재계산 중...';

    const stopwords = new Set(['오늘', '전망', '특징주', '관련주', '주가', '상승', '하락', '마감', '장중', '코스피', '코스닥', '시장', '투자', '분석', '속보', '뉴스', '기업', '한국', '미국', '증시', 'STOCK', 'MARKET', 'NEWS', 'WHY', 'WHAT', 'THE', 'AND', 'FOR']);

    for (const scope of ['KR', 'US']) {
      const list = SECTOR_MAP[scope] || [];
      const updatedList = await Promise.all(list.map(async (sec) => {
        try {
          const rssUrl = scope === 'KR'
            ? `https://news.google.com/rss/search?q=${encodeURIComponent(sec.rss_query)}&hl=ko&gl=KR&ceid=KR:ko`
            : `https://news.google.com/rss/search?q=${encodeURIComponent(sec.rss_query)}&hl=en-US&gl=US&ceid=US:en`;
          const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(rssUrl)}`;
          const res = await fetch(proxyUrl);
          const wrapper = await res.json();
          if (!wrapper || !wrapper.contents) return sec;

          const parser = new DOMParser();
          const xmlDoc = parser.parseFromString(wrapper.contents, "text/xml");
          const nodes = Array.from(xmlDoc.querySelectorAll("item")).slice(0, 15);
          if (nodes.length === 0) return sec;

          const kwMap = {};
          const titles = [];

          nodes.forEach(node => {
            const rawT = (node.querySelector("title")?.textContent || "").split(' - ')[0].trim();
            if (!rawT) return;
            titles.push(rawT);

            (sec.keywords || []).forEach(kw => {
              if (rawT.toUpperCase().includes(kw.toUpperCase())) {
                kwMap[kw] = (kwMap[kw] || 0) + 2;
              }
            });

            const tokens = rawT.match(/[가-힣A-Za-z0-9]{2,10}/g) || [];
            tokens.forEach(tk => {
              if (!stopwords.has(tk.toUpperCase()) && !/^\d+$/.test(tk) && tk !== sec.name) {
                kwMap[tk] = (kwMap[tk] || 0) + 1;
              }
            });
          });

          const sortedKws = Object.entries(kwMap)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([word, count]) => ({ word, count }));

          return {
            ...sec,
            count: titles.length,
            top_keywords: sortedKws.length > 0 ? sortedKws : sec.top_keywords,
            sample_titles: scope === 'KR' ? titles.slice(0, 2) : sec.sample_titles
          };
        } catch (e) {
          return sec;
        }
      }));

      updatedList.sort((a, b) => b.count - a.count);
      const total = updatedList.length;
      updatedList.forEach((item, idx) => {
        item.rank = idx + 1;
        if (idx < Math.max(1, Math.floor(total / 3))) item.level = 'high';
        else if (idx >= total - Math.max(1, Math.floor(total / 3))) item.level = 'low';
        else item.level = 'mid';
      });

      SECTOR_MAP[scope] = updatedList;
      renderSectorStripDOM(scope);
    }

    if (statusEl) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      statusEl.textContent = `⚡ 실시간 순위 반영 (${hh}:${mm})`;
    }
  }

  function searchSectorKeyword(kw) {
    document.getElementById('searchInput').value = kw;
    liveSearch();
  }

  function render120DayCandles(key) {
    const item = CHART_DATA[key];
    if (!item || !item.candles || item.candles.length < 2) return false;

    const candles = item.candles;
    const dec = item.dec || 2;
    const fmt = (n) => n.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });

    let maxH = -Infinity;
    let minL = Infinity;
    candles.forEach(c => {
      if (c[2] > maxH) maxH = c[2];
      if (c[3] < minL) minL = c[3];
    });
    if (maxH === minL) { maxH += 1; minL -= 1; }

    const firstClose = candles[0][4];
    const lastClose = candles[candles.length - 1][4];
    const retPct = ((lastClose - firstClose) / firstClose) * 100;
    const retColor = retPct >= 0 ? '#ff6b6b' : '#4dabf7';

    document.getElementById('ctTitle').textContent = item.label;
    document.getElementById('ctStats').innerHTML = `
      <span>120일 최고 <b style="color:#ff6b6b;">${fmt(maxH)}</b></span>
      <span>최저 <b style="color:#4dabf7;">${fmt(minL)}</b></span>
      <span>기간수익 <b style="color:${retColor};">${retPct >= 0 ? '+' : ''}${retPct.toFixed(2)}%</b></span>
    `;
    document.getElementById('ctStartDate').textContent = candles[0][0];
    document.getElementById('ctEndDate').textContent = candles[candles.length - 1][0];

    const canvas = document.getElementById('ctCanvas');
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    ctx.strokeStyle = '#21262d';
    ctx.lineWidth = 1;
    for (let g = 1; g <= 3; g++) {
      const gy = (H / 4) * g;
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(W, gy);
      ctx.stroke();
    }

    const padTop = 8;
    const padBot = 8;
    const plotH = H - padTop - padBot;
    const toY = (val) => padTop + ((maxH - val) / (maxH - minL)) * plotH;

    const count = candles.length;
    const step = W / count;
    const bodyW = Math.max(1.2, step * 0.62);

    candles.forEach((c, idx) => {
      const [dt, o, h, l, cl] = c;
      const isUp = cl >= o;
      const color = isUp ? '#ff6b6b' : '#4dabf7';
      const cx = idx * step + step / 2;

      const yH = toY(h);
      const yL = toY(l);
      const yO = toY(o);
      const yC = toY(cl);

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx, yH);
      ctx.lineTo(cx, yL);
      ctx.stroke();

      ctx.fillStyle = color;
      const topY = Math.min(yO, yC);
      const barH = Math.max(1.2, Math.abs(yC - yO));
      ctx.fillRect(cx - bodyW / 2, topY, bodyW, barH);
    });

    ctx.strokeStyle = '#eab308';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    let started = false;
    for (let i = 19; i < count; i++) {
      let sum = 0;
      for (let j = 0; j < 20; j++) sum += candles[i - j][4];
      const ma20 = sum / 20;
      const mx = i * step + step / 2;
      const my = toY(ma20);
      if (!started) {
        ctx.moveTo(mx, my);
        started = true;
      } else {
        ctx.lineTo(mx, my);
      }
    }
    ctx.stroke();
    return true;
  }

  function bindChartHoverEvents() {
    const tip = document.getElementById('chartTooltip');
    document.querySelectorAll('.chartable').forEach(card => {
      const key = card.dataset.chartKey;

      card.addEventListener('mouseenter', (e) => {
        if (render120DayCandles(key)) {
          tip.style.display = 'block';
          positionFloatingBox(tip, e);
        }
      });

      card.addEventListener('mousemove', (e) => {
        if (tip.style.display === 'block') {
          positionFloatingBox(tip, e);
        }
      });

      card.addEventListener('mouseleave', () => {
        tip.style.display = 'none';
      });

      card.addEventListener('click', (e) => {
        if (window.innerWidth <= 768 && render120DayCandles(key)) {
          tip.style.display = 'block';
          tip.style.left = `${Math.max(12, (window.innerWidth - 340) / 2)}px`;
          tip.style.top = `${Math.min(window.innerHeight - 240, e.clientY + 14)}px`;
          e.stopPropagation();
        }
      });
    });

    document.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        tip.style.display = 'none';
      }
    });
  }

  async function refreshLiveMarketQuotes() {
    const keys = Object.keys(CHART_DATA);
    for (const key of keys) {
      const item = CHART_DATA[key];
      try {
        const apiUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(item.sym)}?interval=1d&range=8mo`;
        const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(apiUrl)}`;
        const res = await fetch(proxyUrl);
        const wrapper = await res.json();
        const data = JSON.parse(wrapper.contents);
        const result = data.chart.result[0];
        const meta = result.meta;
        const price = meta.regularMarketPrice;
        const prev = meta.chartPreviousClose || meta.previousClose;

        const ts = result.timestamp || [];
        const q = result.indicators.quote[0];
        const freshCandles = [];
        for (let i = 0; i < ts.length; i++) {
          if (q.close[i] != null && q.open[i] != null && q.high[i] != null && q.low[i] != null) {
            const d = new Date(ts[i] * 1000);
            const dtStr = `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
            freshCandles.push([dtStr, q.open[i], q.high[i], q.low[i], q.close[i]]);
          }
        }
        if (freshCandles.length >= 2) {
          CHART_DATA[key].candles = freshCandles.slice(-120);
        }

        if (price !== undefined && prev) {
          const diff = price - prev;
          const pct = (diff / prev) * 100;
          const isUp = diff >= 0;
          const card = document.getElementById(`idx-${key}`);
          if (card) {
            card.querySelector('.idx-price').textContent = price.toLocaleString('en-US', { minimumFractionDigits: item.dec, maximumFractionDigits: item.dec });
            const chgEl = card.querySelector('.idx-chg');
            const sign = isUp ? '+' : '';
            const arrow = isUp ? '▲' : '▼';
            chgEl.textContent = `${arrow} ${sign}${diff.toLocaleString('en-US', { minimumFractionDigits: item.dec, maximumFractionDigits: item.dec })} (${sign}${pct.toFixed(2)}%)`;
            chgEl.className = `idx-chg ${isUp ? 'up' : 'down'}`;
          }
        }
      } catch (e) {}
    }

    try {
      const apiUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent('^TNX')}?interval=1d&range=5d`;
      const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(apiUrl)}`;
      const res = await fetch(proxyUrl);
      const wrapper = await res.json();
      const data = JSON.parse(wrapper.contents);
      const tenY = data.chart.result[0].meta.regularMarketPrice;
      if (tenY !== undefined) {
        const fomcCard = document.getElementById('idx-FOMC');
        if (fomcCard) {
          fomcCard.querySelector('.idx-sub').textContent = `미10Y ${tenY.toFixed(2)}%`;
        }
      }
    } catch (e) {}
  }

  window.addEventListener('DOMContentLoaded', () => {
    bindSectorHoverEvents();
    bindChartHoverEvents();
    refreshLiveMarketQuotes();
    refreshLiveSectorRankings();
    setInterval(refreshLiveMarketQuotes, 60000);
    setInterval(refreshLiveSectorRankings, 90000);
  });

  const KR_ENGLISH_MAP = {
    'NAVER': '네이버 OR NAVER',
    'HPSP': 'HPSP',
    'POSCO': '포스코 OR POSCO',
    'KT': 'KT OR 케이티',
    'LG': 'LG OR 엘지',
    'SK': 'SK OR 에스케이',
    'GS': 'GS',
    'LS': 'LS',
    'CJ': 'CJ',
    'OCI': 'OCI',
    'HYBE': '하이브 OR HYBE',
    'KAKAO': '카카오 OR KAKAO',
    'JYP': 'JYP',
    'SM': '에스엠 OR SM엔터',
    'YG': '와이지엔터테인먼트 OR YG',
    'HMM': 'HMM',
    'HD': 'HD현대'
  };

  const KO_TO_TICKER = {
    '엔비디아': 'NVDA', '앤비디아': 'NVDA', '엔비': 'NVDA',
    '테슬라': 'TSLA', '애플': 'AAPL',
    '마이크로소프트': 'MSFT', '마소': 'MSFT',
    '아마존': 'AMZN', '구글': 'GOOGL', '알파벳': 'GOOGL',
    '메타': 'META', '페이스북': 'META',
    '브로드컴': 'AVGO', '팔란티어': 'PLTR', '일라이릴리': 'LLY',
    '넷플릭스': 'NFLX', '코스트코': 'COST', '월마트': 'WMT',
    '퀄컴': 'QCOM', '인텔': 'INTC', '마이크론': 'MU', '슈퍼마이크로': 'SMCI',
    '오라클': 'ORCL', '세일즈포스': 'CRM', '어도비': 'ADBE', '서비스나우': 'NOW',
    '스노우플레이크': 'SNOW', '크라우드스트라이크': 'CRWD', '팔로알토': 'PANW',
    '아이온큐': 'IONQ', '리게티': 'RGTI', '디웨이브': 'QBTS',
    '로켓랩': 'RKLB', '조비': 'JOBY', '아처': 'ACHR',
    '뉴스케일': 'SMR', '오클로': 'OKLO', '비스트라': 'VST', '컨스텔레이션': 'CEG',
    '코인베이스': 'COIN', '마이크로스트래티지': 'MSTR', '스트래티지': 'MSTR', '로빈후드': 'HOOD',
    '유나이티드헬스': 'UNH', '노보노디스크': 'NVO', '버크셔': 'BRK-B',
    '보잉': 'BA', '록히드마틴': 'LMT', '캐터필러': 'CAT', '디즈니': 'DIS',
    '스타벅스': 'SBUX', '나이키': 'NKE', '쿠팡': 'CPNG', '유니티': 'U', '로블록스': 'RBLX',
    '티에스엠씨': 'TSM', '에이에스엠엘': 'ASML', '암': 'ARM', '리비안': 'RIVN', '루시드': 'LCID'
  };

  function resolveQueryContext(raw) {
    const cleaned = raw.replace('$', '').trim();
    const upper = cleaned.toUpperCase();
    const compact = cleaned.replace(/\s+/g, '');

    if (/^[A-Za-z0-9.\-]{1,10}$/.test(cleaned)) {
      if (KR_ENGLISH_MAP[upper]) {
        return { ticker: '', displayLabel: upper, krSearchQuery: KR_ENGLISH_MAP[upper], isKrEnglish: true };
      }
      const matchedKo = Object.keys(KO_TO_TICKER).find(k => KO_TO_TICKER[k] === upper) || '';
      return { ticker: upper, displayLabel: matchedKo || upper, krSearchQuery: matchedKo || upper, isKrEnglish: false };
    }

    if (KO_TO_TICKER[compact]) {
      const tk = KO_TO_TICKER[compact];
      const normalizedKr = (compact === '앤비디아') ? '엔비디아' : cleaned;
      return { ticker: tk, displayLabel: normalizedKr, krSearchQuery: normalizedKr, isKrEnglish: false };
    }

    return { ticker: '', displayLabel: cleaned, krSearchQuery: cleaned, isKrEnglish: false };
  }

  async function autoDetectTicker(queryText) {
    try {
      const enName = await translateKoToEn(queryText);
      const searchUrl = `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(enName)}&quotesCount=3&newsCount=0`;
      const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(searchUrl)}`;
      const res = await fetch(proxyUrl);
      const wrapper = await res.json();
      const parsed = JSON.parse(wrapper.contents);
      if (parsed && parsed.quotes && parsed.quotes.length > 0) {
        const equity = parsed.quotes.find(q => q.quoteType === 'EQUITY' || q.quoteType === 'ETF');
        return equity ? equity.symbol : parsed.quotes[0].symbol;
      }
    } catch (e) {}
    return '';
  }

  async function fetchRssItemsReliable(rssUrl, limitCount) {
    try {
      const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(rssUrl)}`;
      const res = await fetch(proxyUrl);
      const wrapper = await res.json();
      if (wrapper && wrapper.contents) {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(wrapper.contents, "text/xml");
        const nodes = Array.from(xmlDoc.querySelectorAll("item")).slice(0, limitCount);
        if (nodes.length > 0) {
          return nodes.map(node => ({
            title: (node.querySelector("title")?.textContent || "").trim(),
            link: (node.querySelector("link")?.textContent || "").trim(),
            pubDate: (node.querySelector("pubDate")?.textContent || "").trim()
          }));
        }
      }
    } catch (e) {}

    try {
      const apiUrl = `https://api.rss2json.com/v1/api.json?rss_url=${encodeURIComponent(rssUrl)}`;
      const res = await fetch(apiUrl);
      const data = await res.json();
      if (data && data.status === 'ok' && data.items && data.items.length > 0) {
        return data.items.slice(0, limitCount).map(item => ({
          title: (item.title || "").trim(),
          link: (item.link || "").trim(),
          pubDate: (item.pubDate || "").trim()
        }));
      }
    } catch (e) {}

    return [];
  }

  function filterCat(cat, btn) {
    resetSearch(false);
    currentCat = cat;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    localFilter();
  }

  function localFilter() {
    const raw = document.getElementById('searchInput').value.trim();
    if (!raw) {
      document.querySelectorAll('.saved-card').forEach(card => {
        card.style.display = (currentCat === 'ALL' || card.dataset.cat === currentCat) ? 'block' : 'none';
      });
      return;
    }
    const ctx = resolveQueryContext(raw);
    const q1 = raw.toLowerCase();
    const q2 = ctx.ticker.toLowerCase();
    const q3 = ctx.displayLabel.toLowerCase();

    document.querySelectorAll('.saved-card').forEach(card => {
      const matchCat = (currentCat === 'ALL' || card.dataset.cat === currentCat);
      const txt = card.dataset.text.toLowerCase();
      const matchText = txt.includes(q1) || (q2 && txt.includes(q2)) || (q3 && txt.includes(q3)) || (q1 === 'naver' && txt.includes('네이버'));
      card.style.display = (matchCat && matchText) ? 'block' : 'none';
    });
  }

  function resetSearch(clearInput = true) {
    if (clearInput) document.getElementById('searchInput').value = '';
    document.getElementById('liveBanner').style.display = 'none';
    document.getElementById('liveResults').innerHTML = '';
    document.getElementById('feedList').style.display = 'block';
    localFilter();
  }

  async function translateEnToKo(enText) {
    try {
      const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q=${encodeURIComponent(enText)}`;
      const res = await fetch(url);
      const data = await res.json();
      return data[0].map(p => p[0]).join('') || enText;
    } catch (e) {
      return enText;
    }
  }

  async function translateKoToEn(koText) {
    try {
      const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=ko&tl=en&dt=t&q=${encodeURIComponent(koText)}`;
      const res = await fetch(url);
      const data = await res.json();
      return data[0].map(p => p[0]).join('') || koText;
    } catch (e) {
      return koText;
    }
  }

  async function liveSearch() {
    const rawQuery = document.getElementById('searchInput').value.trim();
    if (!rawQuery) {
      resetSearch();
      return;
    }

    const banner = document.getElementById('liveBanner');
    const statusText = document.getElementById('liveStatusText');
    const liveResults = document.getElementById('liveResults');
    const feedList = document.getElementById('feedList');

    banner.style.display = 'flex';
    liveResults.innerHTML = '';
    feedList.style.display = 'none';

    let ctx = resolveQueryContext(rawQuery);
    statusText.textContent = `⏳ '${ctx.displayLabel}' 종목 매칭 및 실시간 속보 수집 중...`;

    if (!ctx.ticker && !ctx.isKrEnglish) {
      const detected = await autoDetectTicker(rawQuery);
      if (detected) ctx.ticker = detected;
    }

    const labelStr = ctx.ticker ? `${ctx.displayLabel} ($${ctx.ticker})` : ctx.displayLabel;
    statusText.textContent = `⏳ ${labelStr} 실시간 속보 수집 및 정리 중...`;

    const krRss = `https://news.google.com/rss/search?q=${encodeURIComponent(ctx.krSearchQuery)}&hl=ko&gl=KR&ceid=KR:ko`;

    let combinedItems = [];

    try {
      const requests = [fetchRssItemsReliable(krRss, 10)];
      if (ctx.ticker) {
        const usRss = `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${encodeURIComponent(ctx.ticker)}&region=US&lang=en-US`;
        requests.push(fetchRssItemsReliable(usRss, 7));
      }

      const [krItems, usItems] = await Promise.all(requests);

      if (usItems && usItems.length > 0) {
        const translatedTitles = await Promise.all(usItems.map(item => translateEnToKo(item.title)));
        usItems.forEach((item, idx) => {
          combinedItems.push({
            tag: `$${ctx.ticker}`,
            press: 'Yahoo Finance (US)',
            title: translatedTitles[idx],
            subTitle: translatedTitles[idx] !== item.title ? item.title : '',
            link: item.link,
            pubDate: item.pubDate ? item.pubDate.slice(5, 16) : '실시간'
          });
        });
      }

      if (krItems && krItems.length > 0) {
        krItems.forEach(item => {
          let title = item.title || '';
          let press = 'Google 뉴스';
          if (title.includes(' - ')) {
            const parts = title.split(' - ');
            press = parts.pop();
            title = parts.join(' - ');
          }
          combinedItems.push({
            tag: ctx.displayLabel,
            press: press,
            title: title,
            subTitle: '',
            link: item.link,
            pubDate: item.pubDate ? item.pubDate.slice(5, 16) : '실시간'
          });
        });
      }

      if (combinedItems.length === 0) {
        statusText.textContent = `⚠️ '${labelStr}'에 대한 최신 뉴스를 찾지 못했습니다.`;
        return;
      }

      statusText.textContent = `✅ ${labelStr} 실시간 통합 검색 결과 (${combinedItems.length}건)`;
      liveResults.innerHTML = combinedItems.map(item => `
        <div class="news-card">
          <div class="card-top">
            <span class="badge live">⚡ 실시간조회</span>
            <span class="ticker-tag">${item.tag}</span>
            <span class="meta">${item.press} · ${item.pubDate}</span>
          </div>
          <a href="${item.link}" target="_blank" class="news-title">${item.title}</a>
          ${item.subTitle ? `<div class="sub-title">${item.subTitle}</div>` : ''}
        </div>
      `).join('');

    } catch (err) {
      statusText.textContent = `⚠️ 검색 중 일시적인 네트워크 오류가 발생했습니다.`;
    }
  }
</script>
</body>
</html>"""

    page_html = (
        template.replace("__UPDATED_TIME__", updated_time)
        .replace("__ROW_KR__", row_kr)
        .replace("__ROW_US__", row_us)
        .replace("__KR_SECTOR_STRIP__", kr_sector_strip)
        .replace("__US_SECTOR_STRIP__", us_sector_strip)
        .replace("__ROW_FX__", row_fx)
        .replace("__ROW_CMD__", row_cmd)
        .replace("__ROW_MACRO__", row_macro)
        .replace("__CARDS_HTML__", cards_html)
        .replace("__CHART_JSON__", chart_json_str)
        .replace("__SECTOR_MAP_JSON__", sector_map_json)
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page_html)


def main():
    sent_links = set(load_json(HISTORY_FILE, []))
    feed_items = load_json(FEED_DATA_FILE, [])
    now_str = get_kst_now().strftime("%m/%d %H:%M")
    new_items = []

    board, chart_store = fetch_all_macro_dashboard()

    collected = []
    collected.extend(fetch_dart())

    for corp in KR_COMPANIES:
        collected.extend(fetch_google_news(corp, "KR"))

    for ticker in US_TICKERS:
        collected.extend(fetch_finviz_news_only(ticker))
        collected.extend(fetch_yahoo_us_news(ticker))
        time.sleep(1.2)

    for item in collected:
        if item["link"] not in sent_links:
            item["time"] = now_str
            new_items.append(item)
            sent_links.add(item["link"])

    if new_items:
        feed_items = new_items + feed_items
        save_json(HISTORY_FILE, list(sent_links)[-1200:])
        save_json(FEED_DATA_FILE, feed_items[:150])

    kr_sectors = compute_market_sector_heatmap(KR_SECTORS_CONFIG, feed_items, market_scope="KR")
    us_sectors = compute_market_sector_heatmap(US_SECTORS_CONFIG, feed_items, market_scope="US")

    build_saveticker_html(feed_items, board, chart_store, kr_sectors, us_sectors, now_str)
    print(f"완료: 신규 뉴스 {len(new_items)}건 웹 대시보드 업데이트 (텔레그램 발송 비활성화됨)")


if __name__ == "__main__":
    main()
