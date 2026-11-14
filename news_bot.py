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
# [나만의 세이브티커 v4.1 - 한글↔티커 자동 연동 에디션]
# ==========================================

# 1. 매크로 & 거시경제 핵심 키워드
MACRO_KEYWORDS = ["연준 금리", "환율", "유가", "CPI 물가", "미국 증시", "코스피"]

# 2. 국내 주요 기업 감시 (뉴스 + DART 공시 동시 추적)
KR_COMPANIES = ["삼성전자", "SK하이닉스", "현대차", "한화에어로스페이스", "NAVER"]

# 3. 미국 핵심 티커 감시 (Finviz 스냅샷 + Finviz/Yahoo 속보 + 한글 번역)
US_TICKERS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "PLTR"]

# 4. 광고/노이즈 차단 단어
IGNORE_WORDS = ["부고", "인사", "포토", "동정", "모집", "이벤트", "할인", "광고"]

# ==========================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DART_API_KEY = os.environ.get("DART_API_KEY")
HISTORY_FILE = "sent_news.json"
FEED_DATA_FILE = "feed_data.json"
SNAPSHOT_FILE = "snapshots.json"


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


def fetch_finviz_ticker(ticker):
    """Finviz 개별 티커 페이지에서 핵심 펀더멘털 스냅샷과 월가 뉴스 테이블을 동시 추출합니다."""
    url = f"https://finviz.com/quote.ashx?t={ticker}&p=d"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finviz.com/"
    }
    snapshot = {}
    news_list = []

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as res:
            page_html = res.read().decode("utf-8", errors="ignore")

        snap_match = re.search(r'<table[^>]*class="[^"]*snapshot-table2[^"]*"[^>]*>(.*?)</table>', page_html, re.S)
        if snap_match:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', snap_match.group(1), re.S)
            clean_cells = [strip_html_tags(c) for c in cells]
            kv_map = {}
            for i in range(0, len(clean_cells) - 1, 2):
                kv_map[clean_cells[i]] = clean_cells[i + 1]

            price = kv_map.get("Price", "-")
            target = kv_map.get("Target Price", "-")
            fwd_pe = kv_map.get("Forward P/E", "-")
            short_float = kv_map.get("Short Float", "-")
            earnings = kv_map.get("Earnings", "-")
            change = kv_map.get("Change", "-")

            upside_str = ""
            try:
                p_val = float(price.replace(",", ""))
                t_val = float(target.replace(",", ""))
                if p_val > 0:
                    upside = ((t_val - p_val) / p_val) * 100
                    upside_str = f" ({upside:+.1f}%)"
            except Exception:
                pass

            snapshot = {
                "ticker": ticker,
                "price": price,
                "change": change,
                "target": f"{target}{upside_str}",
                "fwd_pe": fwd_pe,
                "short_float": short_float,
                "earnings": earnings
            }

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

    return snapshot, news_list


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


def build_saveticker_html(feed_items, snapshots_map, updated_time):
    """한글 기업명 ↔ 미국 티커 자동 연동 검색이 탑재된 세이브티커 웹 UI"""
    snap_cards_html = ""
    for ticker in US_TICKERS:
        s = snapshots_map.get(ticker)
        if not s:
            continue
        chg = s.get("change", "-")
        chg_color = "#3fb950" if not chg.startswith("-") and chg != "-" else ("#ff7b72" if chg.startswith("-") else "#8b949e")
        snap_cards_html += f"""
        <div class="snap-card" onclick="quickFilter('${{ticker}}')">
            <div class="snap-top">
                <span class="snap-ticker">${{ticker}}</span>
                <span class="snap-price">${{html.escape(s.get('price', '-'))}} <small style="color:${{chg_color}}">${{html.escape(chg)}}</small></span>
            </div>
            <div class="snap-row"><span>목표가</span><b>${{html.escape(s.get('target', '-'))}}</b></div>
            <div class="snap-row"><span>Fwd P/E</span><b>${{html.escape(s.get('fwd_pe', '-'))}}</b></div>
            <div class="snap-row"><span>공매도</span><b>${{html.escape(s.get('short_float', '-'))}}</b></div>
            <div class="snap-row"><span>실적일</span><b>${{html.escape(s.get('earnings', '-'))}}</b></div>
        </div>
        """

    snap_section = f"""
    <div class="snap-section">
        <div class="snap-header">📊 Finviz 핵심 지표 스냅샷 (클릭 시 해당 티커 필터)</div>
        <div class="snap-grid">{snap_cards_html}</div>
    </div>
    """ if snap_cards_html else ""

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
<title>My SaveTicker v4.1 - 한글·티커 자동 연동 금융 피드</title>
<style>
  body {{ background-color: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, "Pretendard", sans-serif; margin: 0; padding: 0; }}
  .header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 20px; position: sticky; top: 0; z-index: 100; }}
  .header-inner {{ max-width: 880px; margin: 0 auto; }}
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
  .container {{ max-width: 880px; margin: 16px auto; padding: 0 16px; }}
  .snap-section {{ margin-bottom: 18px; }}
  .snap-header {{ font-size: 12px; color: #8b949e; margin-bottom: 8px; font-weight: 600; }}
  .snap-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(135px, 1fr)); gap: 8px; }}
  .snap-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 10px 12px; cursor: pointer; transition: border-color 0.2s; }}
  .snap-card:hover {{ border-color: #58a6ff; }}
  .snap-top {{ display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px solid #21262d; padding-bottom: 6px; margin-bottom: 6px; }}
  .snap-ticker {{ font-weight: 800; color: #58a6ff; font-size: 13px; }}
  .snap-price {{ font-weight: 700; font-size: 12px; color: #f0f6fc; }}
  .snap-row {{ display: flex; justify-content: space-between; font-size: 11px; color: #8b949e; margin-top: 3px; }}
  .snap-row b {{ color: #c9d1d9; font-weight: 600; }}
  .live-banner {{ background: rgba(56, 139, 253, 0.12); border: 1px solid rgba(56, 139, 253, 0.4); border-radius: 10px; padding: 12px 16px; margin-bottom: 14px; display: none; justify-content: space-between; align-items: center; font-size: 13px; color: #79c0ff; }}
  .reset-btn {{ background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 4px 10px; border-radius: 8px; cursor: pointer; font-size: 12px; }}
  .news-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; transition: border-color 0.2s; }}
  .news-card:hover {{ border-color: #58a6ff; }}
  .card-top {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
  .badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }}
  .badge.hot {{ background: rgba(248, 81, 73, 0.18); color: #ff7b72; border: 1px solid rgba(248, 81, 73, 0.4); }}
  .badge.live {{ background: rgba(46, 160, 67, 0.2); color: #3fb950; border: 1px solid rgba(46, 160, 67, 0.45); }}
  .badge.normal {{ background: rgba(139, 148, 158, 0.15); color: #8b949e; }}
  .ticker-tag {{ background: rgba(56, 139, 253, 0.15); color: #58a6ff; font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 6px; }}
  .meta {{ font-size: 12px; color: #8b949e; margin-left: auto; }}
  .news-title {{ color: #f0f6fc; text-decoration: none; font-size: 15px; font-weight: 600; line-height: 1.45; display: block; }}
  .news-title:hover {{ color: #58a6ff; text-decoration: underline; }}
  .sub-title {{ color: #8b949e; font-size: 12.5px; margin-top: 5px; line-height: 1.4; }}
</style>
</head>
<body>
  <div class="header">
    <div class="header-inner">
      <div class="title-row">
        <div class="logo" onclick="resetSearch()">⚡ MY SAVETICKER <span style="font-size:12px;color:#8b949e;font-weight:500;">+ Finviz</span></div>
        <div class="updated">자동 업데이트: {updated_time} (KST)</div>
      </div>
      <div class="controls">
        <button class="tab active" onclick="filterCat('ALL', this)">전체 피드</button>
        <button class="tab" onclick="filterCat('DART', this)">🚨 DART 공시</button>
        <button class="tab" onclick="filterCat('MACRO', this)">🌐 매크로·거시</button>
        <button class="tab" onclick="filterCat('KR', this)">🇰🇷 국내기업</button>
        <button class="tab" onclick="filterCat('US', this)">🇺🇸 미국주식(Finviz/번역)</button>
        <div class="search-wrap">
          <input type="text" class="search-box" id="searchInput" onkeydown="if(event.key==='Enter') liveSearch()" onkeyup="localFilter()" placeholder="엔비디아, NVDA, 테슬라 입력 후 Enter...">
          <button class="search-btn" onclick="liveSearch()">실시간 검색</button>
        </div>
      </div>
    </div>
  </div>
  <div class="container">
    {snap_section}
    <div class="live-banner" id="liveBanner">
      <span id="liveStatusText">🔍 실시간 검색 결과</span>
      <button class="reset-btn" onclick="resetSearch()">기본 피드로 돌아가기</button>
    </div>
    <div id="liveResults"></div>
    <div id="feedList">
      {cards_html if cards_html else "<p style='color:#8b949e;text-align:center;'>수집된 뉴스가 없습니다.</p>"}
    </div>
  </div>
<script>
  let currentCat = 'ALL';

  // 한글 기업명(자주 쓰는 표기 및 오타 포함) → 미국 공식 티커 매핑 사전
  const KO_TO_TICKER = {{
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
    '티에스엠씨': 'TSM', '에이에스엠엘': 'ASML', '암': 'ARM', '리비안': 'RIVN', '루시드': 'LCID',
    '나스닥': 'QQQ', '에스앤피': 'SPY', '반도체': 'SOXX'
  }};

  // 검색어 정규화 (예: '앤비디아' -> 공식 한글명 '엔비디아' + 티커 'NVDA' 동시 도출)
  function resolveQueryContext(raw) {{
    const cleaned = raw.replace('$', '').trim();
    const upper = cleaned.toUpperCase();
    const compact = cleaned.replace(/\\s+/g, '');

    if (/^[A-Z0-9.\\-]{{1,8}}$/.test(upper)) {{
      const matchedKo = Object.keys(KO_TO_TICKER).find(k => KO_TO_TICKER[k] === upper) || '';
      return {{ ticker: upper, krKeyword: matchedKo || cleaned }};
    }}

    if (KO_TO_TICKER[compact]) {{
      const tk = KO_TO_TICKER[compact];
      // 흔한 오타('앤비디아')는 표준 검색어('엔비디아')로 보정해 한국 뉴스 검색률도 극대화
      const normalizedKr = (compact === '앤비디아') ? '엔비디아' : cleaned;
      return {{ ticker: tk, krKeyword: normalizedKr }};
    }}

    return {{ ticker: '', krKeyword: cleaned }};
  }}

  // 사전에 없는 기업명을 입력했을 때 야후 파이낸스 심볼 검색으로 티커 자동 추출
  async function autoDetectTicker(queryText) {{
    try {{
      const enName = await translateKoToEn(queryText);
      const searchUrl = `https://query2.finance.yahoo.com/v1/finance/search?q=${{encodeURIComponent(enName)}}&quotesCount=3&newsCount=0`;
      const proxyUrl = `https://api.allorigins.win/get?url=${{encodeURIComponent(searchUrl)}}`;
      const res = await fetch(proxyUrl);
      const wrapper = await res.json();
      const parsed = JSON.parse(wrapper.contents);
      if (parsed && parsed.quotes && parsed.quotes.length > 0) {{
        const equity = parsed.quotes.find(q => q.quoteType === 'EQUITY' || q.quoteType === 'ETF');
        return equity ? equity.symbol : parsed.quotes[0].symbol;
      }}
    }} catch (e) {{}}
    return '';
  }}

  function quickFilter(tickerStr) {{
    resetSearch(false);
    document.getElementById('searchInput').value = tickerStr;
    localFilter();
  }}

  function filterCat(cat, btn) {{
    resetSearch(false);
    currentCat = cat;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    localFilter();
  }}

  function localFilter() {{
    const raw = document.getElementById('searchInput').value.trim();
    if (!raw) {{
      document.querySelectorAll('.saved-card').forEach(card => {{
        card.style.display = (currentCat === 'ALL' || card.dataset.cat === currentCat) ? 'block' : 'none';
      }});
      return;
    }}
    const ctx = resolveQueryContext(raw);
    const q1 = raw.toLowerCase();
    const q2 = ctx.ticker.toLowerCase();
    const q3 = ctx.krKeyword.toLowerCase();

    document.querySelectorAll('.saved-card').forEach(card => {{
      const matchCat = (currentCat === 'ALL' || card.dataset.cat === currentCat);
      const txt = card.dataset.text;
      const matchText = txt.includes(q1) || (q2 && txt.includes(q2)) || (q3 && txt.includes(q3));
      card.style.display = (matchCat && matchText) ? 'block' : 'none';
    }});
  }}

  function resetSearch(clearInput = true) {{
    if (clearInput) document.getElementById('searchInput').value = '';
    document.getElementById('liveBanner').style.display = 'none';
    document.getElementById('liveResults').innerHTML = '';
    document.getElementById('feedList').style.display = 'block';
    localFilter();
  }}

  async function translateEnToKo(enText) {{
    try {{
      const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q=${{encodeURIComponent(enText)}}`;
      const res = await fetch(url);
      const data = await res.json();
      return data[0].map(p => p[0]).join('') || enText;
    }} catch (e) {{
      return enText;
    }}
  }}

  async function translateKoToEn(koText) {{
    try {{
      const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=ko&tl=en&dt=t&q=${{encodeURIComponent(koText)}}`;
      const res = await fetch(url);
      const data = await res.json();
      return data[0].map(p => p[0]).join('') || koText;
    }} catch (e) {{
      return koText;
    }}
  }}

  async function liveSearch() {{
    const rawQuery = document.getElementById('searchInput').value.trim();
    if (!rawQuery) {{
      resetSearch();
      return;
    }}

    const banner = document.getElementById('liveBanner');
    const statusText = document.getElementById('liveStatusText');
    const liveResults = document.getElementById('liveResults');
    const feedList = document.getElementById('feedList');

    banner.style.display = 'flex';
    liveResults.innerHTML = '';
    feedList.style.display = 'none';

    let ctx = resolveQueryContext(rawQuery);
    statusText.textContent = `⏳ '${{rawQuery}}' 종목 매칭 및 실시간 속보 수집 중...`;

    if (!ctx.ticker) {{
      const detected = await autoDetectTicker(rawQuery);
      if (detected) ctx.ticker = detected;
    }}

    const labelStr = ctx.ticker ? `${{ctx.krKeyword}} ($${{ctx.ticker}})` : ctx.krKeyword;
    statusText.textContent = `⏳ ${{labelStr}} 국내·미국 현지 속보 수집 및 한글 번역 중...`;

    const krRss = `https://news.google.com/rss/search?q=${{encodeURIComponent(ctx.krKeyword)}}&hl=ko&gl=KR&ceid=KR:ko`;
    const krApi = `https://api.rss2json.com/v1/api.json?rss_url=${{encodeURIComponent(krRss)}}`;

    let combinedItems = [];

    try {{
      const requests = [fetch(krApi).then(r => r.json()).catch(() => null)];
      if (ctx.ticker) {{
        const usRss = `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${{encodeURIComponent(ctx.ticker)}}&region=US&lang=en-US`;
        const usApi = `https://api.rss2json.com/v1/api.json?rss_url=${{encodeURIComponent(usRss)}}`;
        requests.push(fetch(usApi).then(r => r.json()).catch(() => null));
      }}

      const [krData, usData] = await Promise.all(requests);

      if (usData && usData.status === 'ok' && usData.items) {{
        const topUs = usData.items.slice(0, 7);
        const translatedTitles = await Promise.all(topUs.map(item => translateEnToKo(item.title)));
        topUs.forEach((item, idx) => {{
          combinedItems.push({{
            tag: `$${{ctx.ticker}}`,
            press: 'Yahoo Finance (US)',
            title: translatedTitles[idx],
            subTitle: translatedTitles[idx] !== item.title ? item.title : '',
            link: item.link,
            pubDate: item.pubDate ? item.pubDate.slice(5, 16) : '실시간'
          }});
        }});
      }}

      if (krData && krData.status === 'ok' && krData.items) {{
        krData.items.slice(0, 8).forEach(item => {{
          let title = item.title || '';
          let press = 'Google 뉴스';
          if (title.includes(' - ')) {{
            const parts = title.split(' - ');
            press = parts.pop();
            title = parts.join(' - ');
          }}
          combinedItems.push({{
            tag: ctx.krKeyword,
            press: press,
            title: title,
            subTitle: '',
            link: item.link,
            pubDate: item.pubDate ? item.pubDate.slice(5, 16) : '실시간'
          }});
        }});
      }}

      if (combinedItems.length === 0) {{
        statusText.textContent = `⚠️ '${{labelStr}}'에 대한 최신 뉴스를 찾지 못했습니다.`;
        return;
      }}

      statusText.textContent = `✅ ${{labelStr}} 실시간 통합 검색 결과 (${{combinedItems.length}}건)`;
      liveResults.innerHTML = combinedItems.map(item => `
        <div class="news-card">
          <div class="card-top">
            <span class="badge live">⚡ 실시간조회</span>
            <span class="ticker-tag">${{item.tag}}</span>
            <span class="meta">${{item.press}} · ${{item.pubDate}}</span>
          </div>
          <a href="${{item.link}}" target="_blank" class="news-title">${{item.title}}</a>
          ${{item.subTitle ? `<div class="sub-title">${{item.subTitle}}</div>` : ''}}
        </div>
      `).join('');

    }} catch (err) {{
      statusText.textContent = `⚠️ 검색 중 일시적인 네트워크 오류가 발생했습니다.`;
    }}
  }}
</script>
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page_html)


def main():
    sent_links = set(load_json(HISTORY_FILE, []))
    feed_items = load_json(FEED_DATA_FILE, [])
    snapshots_map = load_json(SNAPSHOT_FILE, {})
    now_str = get_kst_now().strftime("%m/%d %H:%M")
    new_items = []

    collected = []
    collected.extend(fetch_dart())

    for kw in MACRO_KEYWORDS:
        collected.extend(fetch_google_news(kw, "MACRO"))

    for corp in KR_COMPANIES:
        collected.extend(fetch_google_news(corp, "KR"))

    for ticker in US_TICKERS:
        snap, finviz_news = fetch_finviz_ticker(ticker)
        if snap:
            snapshots_map[ticker] = snap
        collected.extend(finviz_news)
        collected.extend(fetch_yahoo_us_news(ticker))
        time.sleep(1.5)

    for item in collected:
        if item["link"] not in sent_links:
            item["time"] = now_str
            new_items.append(item)
            sent_links.add(item["link"])

            snap_note = ""
            if item["category"] == "US":
                raw_t = item["tag"].replace("$", "")
                s = snapshots_map.get(raw_t)
                if s:
                    snap_note = f"\n📊 <code>주가 ${s['price']} | 목표가 ${s['target']} | 공매도 {s['short_float']} | 실적 {s['earnings']}</code>"

            sub_line = f"\n<i>({item['sub_title']})</i>" if item.get("sub_title") else ""
            msg = (
                f"{item['impact']} <b>[{item['tag']}]</b>\n"
                f"{item['title']}{sub_line}{snap_note}\n"
                f"🗞 {item['press']} · <a href='{item['link']}'>원문 보기</a>"
            )
            send_telegram(msg)

    if new_items:
        feed_items = new_items + feed_items
        save_json(HISTORY_FILE, list(sent_links)[-1200:])
        save_json(FEED_DATA_FILE, feed_items[:200])

    if snapshots_map:
        save_json(SNAPSHOT_FILE, snapshots_map)

    build_saveticker_html(feed_items, snapshots_map, now_str)
    print(f"완료: 신규 뉴스 {len(new_items)}건 반영, 스냅샷 {len(snapshots_map)}종목 업데이트")


if __name__ == "__main__":
    main()
