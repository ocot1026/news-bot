import os
import re
import json
import time
import html
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# ==========================================
# [나만의 세이브티커 v5.0 - 한·미 4대 지수 전광판 에디션]
# ==========================================

# 1. 매크로 & 거시경제 핵심 키워드
MACRO_KEYWORDS = ["연준 금리", "환율", "유가", "CPI 물가", "미국 증시", "코스피"]

# 2. 국내 주요 기업 감시 (뉴스 + DART 공시 동시 추적)
KR_COMPANIES = ["삼성전자", "SK하이닉스", "현대차", "한화에어로스페이스", "NAVER"]

# 3. 미국 핵심 티커 감시 (Finviz/Yahoo 속보 + 한글 번역)
US_TICKERS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "PLTR"]

# 4. 광고/노이즈 차단 단어
IGNORE_WORDS = ["부고", "인사", "포토", "동정", "모집", "이벤트", "할인", "광고"]

# ==========================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DART_API_KEY = os.environ.get("DART_API_KEY")
HISTORY_FILE = "sent_news.json"
FEED_DATA_FILE = "feed_data.json"


def get_kst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


def load_json(filepath, default):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def translate_en_to_ko(text):
    """무료 구글 번역 API를 이용해 영문 뉴스 제목을 자연스러운 한국어로 번역합니다."""
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


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")


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


def fetch_market_indices():
    """코스피, 코스닥, 다우, 나스닥 4대 주요 지수의 최신 시세를 수집합니다."""
    symbols = {
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
        "DOW": "^DJI",
        "NASDAQ": "^IXIC"
    }
    indices = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for key, sym in symbols.items():
        try:
            encoded_sym = urllib.parse.quote(sym)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_sym}?interval=1d&range=5d"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as res:
                data = json.loads(res.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price is not None and prev:
                diff = price - prev
                pct = (diff / prev) * 100
                indices[key] = {
                    "price": f"{price:,.2f}",
                    "diff": f"{diff:+,.2f}",
                    "pct": f"{pct:+.2f}%",
                    "up": diff >= 0
                }
            else:
                indices[key] = {"price": "-", "diff": "0.00", "pct": "0.00%", "up": True}
        except Exception as e:
            print(f"[Index-{key}] 수집 오류: {e}")
            indices[key] = {"price": "-", "diff": "0.00", "pct": "0.00%", "up": True}

    return indices


def fetch_finviz_news_only(ticker):
    """Finviz 개별 티커 페이지에서 월가 속보 뉴스만 깔끔하게 추출합니다."""
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
            if any(k in corp for k in KR_COMPANIES):
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


def render_index_box(box_id, label, sub_label, info):
    cls = "up" if info.get("up", True) else "down"
    arrow = "▲" if info.get("up", True) else "▼"
    price = html.escape(info.get("price", "-"))
    diff = html.escape(info.get("diff", "0.00"))
    pct = html.escape(info.get("pct", "0.00%"))
    return f"""
    <div class="idx-card" id="idx-{box_id}">
        <div class="idx-head">
            <span class="idx-name">{label}</span>
            <span class="idx-sub">{sub_label}</span>
        </div>
        <div class="idx-body">
            <span class="idx-price">{price}</span>
            <span class="idx-chg {cls}">{arrow} {diff} ({pct})</span>
        </div>
    </div>
    """


def build_saveticker_html(feed_items, indices, updated_time):
    """1행(코스피/코스닥) + 2행(다우/나스닥) 실시간 지수 전광판이 적용된 웹 UI"""
    kospi_html = render_index_box("KOSPI", "🇰🇷 코스피", "KOSPI", indices.get("KOSPI", {}))
    kosdaq_html = render_index_box("KOSDAQ", "🇰🇷 코스닥", "KOSDAQ", indices.get("KOSDAQ", {}))
    dow_html = render_index_box("DOW", "🇺🇸 다우존스", "DOW JONES", indices.get("DOW", {}))
    nasdaq_html = render_index_box("NASDAQ", "🇺🇸 나스닥", "NASDAQ", indices.get("NASDAQ", {}))

    cards_html = ""
    for item in feed_items[:150]:
        badge_class = "hot" if ("속보" in item["impact"] or "공시" in item["impact"]) else "normal"
        safe_title = html.escape(item["title"])
        safe_sub = html.escape(item.get("sub_title", ""))
        safe_tag = html.escape(item["tag"])
        safe_press = html.escape(item["press"])
        safe_time = html.escape(item.get("time", ""))
        safe_link = html.escape(item["link"])
        sub_html = f'<div class="sub-title">{safe_sub}</div>' if safe_sub else ""

        cards_html += f"""
        <div class="news-card saved-card" data-cat="{item['category']}" data-text="{safe_tag.lower()} {safe_title.lower()} {safe_sub.lower()}">
            <div class="card-top">
                <span class="badge {badge_class}">{item['impact']}</span>
                <span class="ticker-tag">{safe_tag}</span>
                <span class="meta">{safe_press} · {safe_time}</span>
            </div>
            <a href="{safe_link}" target="_blank" class="news-title">{safe_title}</a>
            {sub_html}
        </div>
        """

    page_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My SaveTicker - 실시간 금융·증시 피드</title>
<style>
  body {{ background-color: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, "Pretendard", sans-serif; margin: 0; padding: 0; }}
  .header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 20px; position: sticky; top: 0; z-index: 100; }}
  .header-inner {{ max-width: 860px; margin: 0 auto; }}
  .title-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
  .logo {{ font-size: 20px; font-weight: 800; color: #58a6ff; letter-spacing: -0.5px; cursor: pointer; }}
  .updated {{ font-size: 12px; color: #8b949e; }}
  .controls {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .tab {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 12px; border-radius: 16px; font-size: 13px; cursor: pointer; }}
  .tab.active {{ background: #1f6feb; border-color: #388bfd; color: #fff; font-weight: 600; }}
  .search-wrap {{ display: flex; flex: 1; min-width: 240px; gap: 6px; }}
  .search-box {{ flex: 1; background: #0d1117; border: 1px solid #30363d; color: #fff; padding: 7px 14px; border-radius: 16px; font-size: 13px; outline: none; }}
  .search-box:focus {{ border-color: #58a6ff; }}
  .search-btn {{ background: #238636; border: none; color: #fff; padding: 7px 14px; border-radius: 16px; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }}
  .search-btn:hover {{ background: #2ea043; }}
  .container {{ max-width: 860px; margin: 16px auto; padding: 0 16px; }}

  /* 2단 지수 전광판 스타일 (1행: 코스피/코스닥, 2행: 다우/나스닥) */
  .market-board {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }}
  .market-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
  .idx-card {{ background: #16
