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
# [나만의 세이브티커 v6.3 - FOMC · CPI · PPI 직전발표치 대조 색상 판별 에디션]
# ==========================================

# 1. 미국 거시경제 공식 발표치 (curr: 이번 발표치, prev: 직전 발표치 -> 변동폭 및 색상 자동 계산)
MACRO_OFFICIAL = {
    "FOMC": {
        "display": "3.75~4.00%",  # 화면 표시 금리 구간
        "curr": 4.00,              # 이번 FOMC 상단 금리 (%)
        "prev": 4.00,              # 직전 FOMC 상단 금리 (%) -> 같으면 자동으로 초록색 '동결' 표시
        "date": "2026.10"
    },
    "CPI": {
        "display": "3.7% (YoY)",   # 화면 표시 물가 수치
        "curr": 3.7,               # 이번 CPI 전년비 (%)
        "prev": 3.5,               # 직전 CPI 전년비 (%) -> 높으면 빨간색 상승, 낮으면 파란색 하락
        "date": "10월 MoM +0.4%"
    },
    "PPI": {
        "display": "6.5% (YoY)",   # 화면 표시 생산자물가 수치
        "curr": 6.5,               # 이번 PPI 전년비 (%)
        "prev": 6.8,               # 직전 PPI 전년비 (%) -> 낮으면 파란색 하락, 높으면 빨간색 상승
        "date": "10월 MoM +0.3%"
    }
}

# 2. 감시 기업 및 티커 설정
KR_COMPANIES = ["삼성전자", "SK하이닉스", "현대차", "한화에어로스페이스", "NAVER", "HPSP"]
US_TICKERS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "PLTR"]
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


def fetch_yahoo_quote(sym, decimals=2):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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
            fmt = f"{{:,.{decimals}f}}"
            dfmt = f"{{:+,.{decimals}f}}"
            return {
                "price": fmt.format(price),
                "diff": dfmt.format(diff),
                "pct": f"{pct:+.2f}%",
                "up": diff >= 0
            }
    except Exception as e:
        print(f"[Quote-{sym}] 오류: {e}")
    return {"price": "-", "diff": "0.00", "pct": "0.00%", "up": True}


def evaluate_macro_delta(key, cfg, extra_note=""):
    """직전 발표치(prev)와 현재 발표치(curr)를 비교해 동결(초록)/상승(빨강)/하락(파랑) 상태를 반환합니다."""
    curr = float(cfg["curr"])
    prev = float(cfg["prev"])
    diff = round(curr - prev, 4)

    if abs(diff) < 1e-6:
        status_cls = "freeze"
        if key == "FOMC":
            status_text = f"동결 ({cfg['date']})"
        else:
            status_text = f"동결 (직전 {prev:.1f}%)"
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
    us10y = fetch_yahoo_quote("^TNX", 2)
    ten_y_str = f"미10Y {us10y['price']}%" if us10y["price"] != "-" else "실효 3.88%"

    board = {
        "KOSPI": fetch_yahoo_quote("^KS11", 2),
        "KOSDAQ": fetch_yahoo_quote("^KQ11", 2),
        "DOW": fetch_yahoo_quote("^DJI", 2),
        "NASDAQ": fetch_yahoo_quote("^IXIC", 2),
        "USDKRW": fetch_yahoo_quote("KRW=X", 2),
        "EURUSD": fetch_yahoo_quote("EURUSD=X", 4),
        "USDJPY": fetch_yahoo_quote("JPY=X", 2),
        "GBPUSD": fetch_yahoo_quote("GBPUSD=X", 4),
        "USDCHF": fetch_yahoo_quote("CHF=X", 4),
        "USDCAD": fetch_yahoo_quote("CAD=X", 4),
        "OIL": fetch_yahoo_quote("CL=F", 2),
        "GOLD": fetch_yahoo_quote("GC=F", 2),
        "SILVER": fetch_yahoo_quote("SI=F", 2),
        "FOMC": evaluate_macro_delta("FOMC", MACRO_OFFICIAL["FOMC"], ten_y_str),
        "CPI": evaluate_macro_delta("CPI", MACRO_OFFICIAL["CPI"]),
        "PPI": evaluate_macro_delta("PPI", MACRO_OFFICIAL["PPI"])
    }
    return board


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
    card_cls = "idx-card compact" if compact else "idx-card"
    return (
        f'<div class="{card_cls}" id="idx-{box_id}">'
        f'<div class="idx-head"><span class="idx-name">{label}</span><span class="idx-sub">{sub_label}</span></div>'
        f'<div class="idx-body"><span class="idx-price">{price}</span><span class="idx-chg {cls}">{arrow}{diff} ({pct})</span></div>'
        f'</div>'
    )


def render_macro_policy_tile(box_id, label, sub_label, info):
    """FOMC/CPI/PPI 전용 타일: 동결=초록(freeze), 상승=빨강(up), 하락=파랑(down)"""
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


def build_saveticker_html(feed_items, board, updated_time):
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

    template = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My SaveTicker - 실시간 증시·매크로 대시보드</title>
<style>
  body { background-color: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, "Pretendard", sans-serif; margin: 0; padding: 0; }
  .header { background: #161b22; border-bottom: 1px solid #30363d; padding: 14px 20px; position: sticky; top: 0; z-index: 100; }
  .header-inner { max-width: 880px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
  .logo { font-size: 20px; font-weight: 800; color: #58a6ff; letter-spacing: -0.5px; cursor: pointer; }
  .updated { font-size: 12px; color: #8b949e; }
  .container { max-width: 880px; margin: 16px auto; padding: 0 16px; }

  .sec-label { font-size: 11.5px; font-weight: 700; color: #8b949e; margin: 12px 0 6px; letter-spacing: -0.2px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
  @media (max-width: 640px) {
    .grid-3 { grid-template-columns: repeat(2, 1fr); }
  }

  .idx-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 12px 15px; display: flex; flex-direction: column; gap: 6px; }
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

  <div class="container">
    <div class="grid-2">__ROW_KR__</div>
    <div class="grid-2">__ROW_US__</div>

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

    <div class="sec-label">💱 실시간 환율 (한국 원/달러 & 세계 5대 주요 통화)</div>
    <div class="grid-3">__ROW_FX__</div>

    <div class="sec-label">⛏️ 원자재 선물 (WTI 유가 · 국제 금 · 국제 은)</div>
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

  async function refreshLiveMarketQuotes() {
    const targets = [
      { id: 'KOSPI', sym: '^KS11', dec: 2 },
      { id: 'KOSDAQ', sym: '^KQ11', dec: 2 },
      { id: 'DOW', sym: '^DJI', dec: 2 },
      { id: 'NASDAQ', sym: '^IXIC', dec: 2 },
      { id: 'USDKRW', sym: 'KRW=X', dec: 2 },
      { id: 'EURUSD', sym: 'EURUSD=X', dec: 4 },
      { id: 'USDJPY', sym: 'JPY=X', dec: 2 },
      { id: 'GBPUSD', sym: 'GBPUSD=X', dec: 4 },
      { id: 'USDCHF', sym: 'CHF=X', dec: 4 },
      { id: 'USDCAD', sym: 'CAD=X', dec: 4 },
      { id: 'OIL', sym: 'CL=F', dec: 2 },
      { id: 'GOLD', sym: 'GC=F', dec: 2 },
      { id: 'SILVER', sym: 'SI=F', dec: 2 }
    ];

    for (const t of targets) {
      try {
        const apiUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(t.sym)}?interval=1d&range=5d`;
        const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(apiUrl)}`;
        const res = await fetch(proxyUrl);
        const wrapper = await res.json();
        const data = JSON.parse(wrapper.contents);
        const meta = data.chart.result[0].meta;
        const price = meta.regularMarketPrice;
        const prev = meta.chartPreviousClose || meta.previousClose;

        if (price !== undefined && prev) {
          const diff = price - prev;
          const pct = (diff / prev) * 100;
          const isUp = diff >= 0;
          const card = document.getElementById(`idx-${t.id}`);
          if (card) {
            card.querySelector('.idx-price').textContent = price.toLocaleString('en-US', { minimumFractionDigits: t.dec, maximumFractionDigits: t.dec });
            const chgEl = card.querySelector('.idx-chg');
            const sign = isUp ? '+' : '';
            const arrow = isUp ? '▲' : '▼';
            chgEl.textContent = `${arrow} ${sign}${diff.toLocaleString('en-US', { minimumFractionDigits: t.dec, maximumFractionDigits: t.dec })} (${sign}${pct.toFixed(2)}%)`;
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
    refreshLiveMarketQuotes();
    setInterval(refreshLiveMarketQuotes, 60000);
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
        .replace("__ROW_FX__", row_fx)
        .replace("__ROW_CMD__", row_cmd)
        .replace("__ROW_MACRO__", row_macro)
        .replace("__CARDS_HTML__", cards_html)
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page_html)


def main():
    sent_links = set(load_json(HISTORY_FILE, []))
    feed_items = load_json(FEED_DATA_FILE, [])
    now_str = get_kst_now().strftime("%m/%d %H:%M")
    new_items = []

    board = fetch_all_macro_dashboard()

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

            sub_line = f"\n<i>({item['sub_title']})</i>" if item.get("sub_title") else ""
            msg = (
                f"{item['impact']} <b>[{item['tag']}]</b>\n"
                f"{item['title']}{sub_line}\n"
                f"🗞 {item['press']} · <a href='{item['link']}'>원문 보기</a>"
            )
            send_telegram(msg)

    if new_items:
        feed_items = new_items + feed_items
        save_json(HISTORY_FILE, list(sent_links)[-1200:])
        save_json(FEED_DATA_FILE, feed_items[:150])

    build_saveticker_html(feed_items, board, now_str)
    print(f"완료: 신규 기업뉴스 {len(new_items)}건 및 글로벌 매크로 대시보드 업데이트")


if __name__ == "__main__":
    main()
