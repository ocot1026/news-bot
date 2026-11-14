import os
import json
import html
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# ==========================================
# [나만의 세이브티커 v2.0 설정 영역]
# ==========================================

# 1. 매크로 & 거시경제 핵심 키워드
MACRO_KEYWORDS = ["연준 금리", "환율", "유가", "CPI 물가", "미국 증시", "코스피"]

# 2. 국내 주요 기업 감시 (뉴스 + DART 공시 동시 추적)
KR_COMPANIES = ["삼성전자", "SK하이닉스", "현대차", "한화에어로스페이스", "NAVER"]

# 3. 미국 핵심 티커 감시 (월스트리트 현지 속보)
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
    hot_words = ["속보", "긴급", "급등", "급락", "실적", "어닝", "공급계약", "유상증자", "금리", "인하", "인상", "파월", "트럼프", "SURGE", "PLUNGE", "BREAKING", "EARNINGS"]
    if any(w in title.upper() for w in hot_words):
        return "🔥 주요속보"
    return "📰 일반"


def fetch_google_news(keyword, category):
    encoded_kw = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
    results = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            root = ET.fromstring(res.read())
        for item in root.findall(".//item")[:5]:
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
                "link": link,
                "impact": classify_impact(title)
            })
    except Exception as e:
        print(f"[{keyword}] 수집 오류: {e}")
    return results


def fetch_us_news(ticker):
    rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    results = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            root = ET.fromstring(res.read())
        for item in root.findall(".//item")[:5]:
            title = item.find("title").text or ""
            link = item.find("link").text or ""
            results.append({
                "category": "US",
                "tag": f"${ticker}",
                "press": "Yahoo Finance",
                "title": title,
                "link": link,
                "impact": classify_impact(title)
            })
    except Exception as e:
        print(f"[US-{ticker}] 수집 오류: {e}")
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
                    "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}",
                    "impact": "🚨 공식공시"
                })
    except Exception as e:
        print(f"[DART] 오류: {e}")
    return results


def build_saveticker_html(feed_items, updated_time):
    """실시간 온디맨드 티커/키워드 검색 기능이 탑재된 세이브티커 웹 UI"""
    cards_html = ""
    for item in feed_items[:120]:
        badge_class = "hot" if ("속보" in item["impact"] or "공시" in item["impact"]) else "normal"
        safe_title = html.escape(item["title"])
        safe_tag = html.escape(item["tag"])
        safe_press = html.escape(item["press"])
        safe_time = html.escape(item.get("time", ""))
        safe_link = html.escape(item["link"])

        cards_html += f"""
        <div class="news-card saved-card" data-cat="{item['category']}" data-text="{safe_tag.lower()} {safe_title.lower()}">
            <div class="card-top">
                <span class="badge {badge_class}">{item['impact']}</span>
                <span class="ticker-tag">{safe_tag}</span>
                <span class="meta">{safe_press} · {safe_time}</span>
            </div>
            <a href="{safe_link}" target="_blank" class="news-title">{safe_title}</a>
        </div>
        """

    page_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My SaveTicker - 실시간 금융·기업 속보 피드</title>
<style>
  body {{ background-color: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, "Pretendard", sans-serif; margin: 0; padding: 0; }}
  .header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 20px; position: sticky; top: 0; z-index: 100; }}
  .header-inner {{ max-width: 840px; margin: 0 auto; }}
  .title-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
  .logo {{ font-size: 20px; font-weight: 800; color: #58a6ff; letter-spacing: -0.5px; cursor: pointer; }}
  .updated {{ font-size: 12px; color: #8b949e; }}
  .controls {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .tab {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 12px; border-radius: 16px; font-size: 13px; cursor: pointer; }}
  .tab.active {{ background: #1f6feb; border-color: #388bfd; color: #fff; font-weight: 600; }}
  .search-wrap {{ display: flex; flex: 1; min-width: 220px; gap: 6px; }}
  .search-box {{ flex: 1; background: #0d1117; border: 1px solid #30363d; color: #fff; padding: 7px 14px; border-radius: 16px; font-size: 13px; outline: none; }}
  .search-box:focus {{ border-color: #58a6ff; }}
  .search-btn {{ background: #238636; border: none; color: #fff; padding: 7px 14px; border-radius: 16px; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }}
  .search-btn:hover {{ background: #2ea043; }}
  .container {{ max-width: 840px; margin: 16px auto; padding: 0 16px; }}
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
</style>
</head>
<body>
  <div class="header">
    <div class="header-inner">
      <div class="title-row">
        <div class="logo" onclick="resetSearch()">⚡ MY SAVETICKER</div>
        <div class="updated">자동 업데이트: {updated_time} (KST)</div>
      </div>
      <div class="controls">
        <button class="tab active" onclick="filterCat('ALL', this)">전체 피드</button>
        <button class="tab" onclick="filterCat('DART', this)">🚨 DART 공시</button>
        <button class="tab" onclick="filterCat('MACRO', this)">🌐 매크로·거시</button>
        <button class="tab" onclick="filterCat('KR', this)">🇰🇷 국내기업</button>
        <button class="tab" onclick="filterCat('US', this)">🇺🇸 미국주식</button>
        <div class="search-wrap">
          <input type="text" class="search-box" id="searchInput" onkeydown="if(event.key==='Enter') liveSearch()" onkeyup="localFilter()" placeholder="티커(NVDA) 또는 기업명 입력 후 Enter...">
          <button class="search-btn" onclick="liveSearch()">실시간 검색</button>
        </div>
      </div>
    </div>
  </div>
  <div class="container">
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

  function filterCat(cat, btn) {{
    resetSearch(false);
    currentCat = cat;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    localFilter();
  }}

  function localFilter() {{
    const q = document.getElementById('searchInput').value.toLowerCase().trim();
    document.querySelectorAll('.saved-card').forEach(card => {{
      const matchCat = (currentCat === 'ALL' || card.dataset.cat === currentCat);
      const matchText = card.dataset.text.includes(q);
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
    statusText.textContent = `⏳ '${{rawQuery}}' 실시간 최신 속보를 불러오는 중...`;
    liveResults.innerHTML = '';
    feedList.style.display = 'none';

    const cleanTicker = rawQuery.replace('$', '').toUpperCase();
    const isEnglishTicker = /^[A-Z0-9.\\-]{{1,8}}$/.test(cleanTicker);

    // 1. 구글 뉴스 한국어 실시간 검색 RSS
    const krRss = `https://news.google.com/rss/search?q=${{encodeURIComponent(rawQuery)}}&hl=ko&gl=KR&ceid=KR:ko`;
    const krApi = `https://api.rss2json.com/v1/api.json?rss_url=${{encodeURIComponent(krRss)}}`;

    // 2. 영문 티커일 경우 야후 파이낸스 미국 현지 속보 RSS 동시 조회
    const usRss = `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${{encodeURIComponent(cleanTicker)}}&region=US&lang=en-US`;
    const usApi = `https://api.rss2json.com/v1/api.json?rss_url=${{encodeURIComponent(usRss)}}`;

    let combinedItems = [];

    try {{
      const requests = [fetch(krApi).then(r => r.json()).catch(() => null)];
      if (isEnglishTicker) {{
        requests.push(fetch(usApi).then(r => r.json()).catch(() => null));
      }}

      const [krData, usData] = await Promise.all(requests);

      if (usData && usData.status === 'ok' && usData.items) {{
        usData.items.slice(0, 8).forEach(item => {{
          combinedItems.push({{
            tag: `$${{cleanTicker}}`,
            press: 'Yahoo Finance (US)',
            title: item.title,
            link: item.link,
            pubDate: item.pubDate ? item.pubDate.slice(5, 16) : '실시간'
          }});
        }});
      }}

      if (krData && krData.status === 'ok' && krData.items) {{
        krData.items.slice(0, 10).forEach(item => {{
          let title = item.title || '';
          let press = 'Google 뉴스';
          if (title.includes(' - ')) {{
            const parts = title.split(' - ');
            press = parts.pop();
            title = parts.join(' - ');
          }}
          combinedItems.push({{
            tag: rawQuery,
            press: press,
            title: title,
            link: item.link,
            pubDate: item.pubDate ? item.pubDate.slice(5, 16) : '실시간'
          }});
        }});
      }}

      if (combinedItems.length === 0) {{
        statusText.textContent = `⚠️ '${{rawQuery}}'에 대한 최신 뉴스를 찾지 못했습니다.`;
        return;
      }}

      statusText.textContent = `✅ '${{rawQuery}}' 실시간 검색 결과 (${{combinedItems.length}}건)`;
      liveResults.innerHTML = combinedItems.map(item => `
        <div class="news-card">
          <div class="card-top">
            <span class="badge live">⚡ 실시간조회</span>
            <span class="ticker-tag">${{item.tag}}</span>
            <span class="meta">${{item.press}} · ${{item.pubDate}}</span>
          </div>
          <a href="${{item.link}}" target="_blank" class="news-title">${{item.title}}</a>
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
    now_str = get_kst_now().strftime("%m/%d %H:%M")
    new_items = []

    collected = []
    collected.extend(fetch_dart())
    for kw in MACRO_KEYWORDS:
        collected.extend(fetch_google_news(kw, "MACRO"))
    for corp in KR_COMPANIES:
        collected.extend(fetch_google_news(corp, "KR"))
    for ticker in US_TICKERS:
        collected.extend(fetch_us_news(ticker))

    for item in collected:
        if item["link"] not in sent_links:
            item["time"] = now_str
            new_items.append(item)
            sent_links.add(item["link"])

            msg = (
                f"{item['impact']} <b>[{item['tag']}]</b>\n"
                f"{item['title']}\n"
                f"🗞 {item['press']} · <a href='{item['link']}'>원문 보기</a>"
            )
            send_telegram(msg)

    if new_items:
        feed_items = new_items + feed_items
        save_json(HISTORY_FILE, list(sent_links)[-1000:])
        save_json(FEED_DATA_FILE, feed_items[:200])

    build_saveticker_html(feed_items, now_str)
    print(f"완료: 신규 뉴스 {len(new_items)}건 반영 및 웹피드 업데이트")


if __name__ == "__main__":
    main()
