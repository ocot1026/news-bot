import os
import json
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# ==========================================
# [사용자 설정 영역] 원하시는 대로 수정하세요
# ==========================================

# 1. 한국 뉴스 감시 키워드 (기업명, 산업 테마 등)
KR_KEYWORDS = ["삼성전자", "SK하이닉스", "엔비디아", "HPSP", "금리인하", "금리인상"]

# 2. 미국 현지 뉴스 감시 티커 (영문 주식 심볼)
US_TICKERS = ["NVDA"]

# 3. 제외할 노이즈 단어 (제목에 이 단어가 들어가면 알림 안 보냄)
IGNORE_WORDS = ["부고", "인사", "포토", "동정", "모집", "이벤트", "할인"]

# 4. DART 공시 필터 (비워두면 모든 공시 수신 / 특정 공시만 보려면 키워드 입력)
# 예: ["실적", "공급계약", "유상증자", "자기주식", "영업(잠정)실적"]
DART_IMPORTANT_ONLY = []

# ==========================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
DART_API_KEY = os.environ.get("DART_API_KEY")
HISTORY_FILE = "sent_news.json"


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history_set)[-1000:], f, ensure_ascii=False, indent=2)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True  # 미리보기 끄기로 채팅창 깔끔하게 유지
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")


def is_clean_title(title):
    """노이즈 단어가 포함된 기사인지 검사합니다."""
    return not any(word in title for word in IGNORE_WORDS)


def fetch_kr_news(keyword):
    """구글 뉴스(한국) 최신 기사 수집"""
    encoded_kw = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"
    results = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            root = ET.fromstring(res.read())
        for item in root.findall(".//item")[:3]:
            raw_title = item.find("title").text or ""
            link = item.find("link").text or ""
            if not is_clean_title(raw_title):
                continue
            # 제목과 언론사명 분리 (예: "기사제목 - 매일경제")
            if " - " in raw_title:
                title, press = raw_title.rsplit(" - ", 1)
            else:
                title, press = raw_title, "뉴스"
            results.append((f"[{press}] {title}", link))
    except Exception as e:
        print(f"[KR-{keyword}] 오류: {e}")
    return results


def fetch_us_news(ticker):
    """야후 파이낸스 미국 현지 속보 RSS 수집"""
    rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    results = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            root = ET.fromstring(res.read())
        for item in root.findall(".//item")[:2]:
            title = item.find("title").text or ""
            link = item.find("link").text or ""
            results.append((title, link))
    except Exception as e:
        print(f"[US-{ticker}] 오류: {e}")
    return results


def fetch_dart_disclosures():
    """금융감독원 DART 오늘자 실시간 공시 수집 (관심 기업 매칭)"""
    if not DART_API_KEY:
        return []
    today_kst = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y%m%d")
    api_url = (
        f"https://opendart.fss.or.kr/api/list.json?"
        f"crtfc_key={DART_API_KEY}&bgn_de={today_kst}&end_de={today_kst}&page_count=100"
    )
    results = []
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))
        if data.get("status") != "000":
            return []
        for item in data.get("list", []):
            corp_name = item.get("corp_name", "")
            report_nm = item.get("report_nm", "")
            rcept_no = item.get("rcept_no", "")
            # KR_KEYWORDS에 포함된 기업인지 확인
            if any(kw in corp_name for kw in KR_KEYWORDS):
                if DART_IMPORTANT_ONLY and not any(k in report_nm for k in DART_IMPORTANT_ONLY):
                    continue
                dart_link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                results.append((corp_name, report_nm, dart_link))
    except Exception as e:
        print(f"[DART] 수집 오류: {e}")
    return results


def main():
    sent_links = load_history()
    new_count = 0

    # 1. 금융감독원 DART 공시 확인 (최우선 알림)
    for corp_name, report_nm, link in fetch_dart_disclosures():
        if link not in sent_links:
            msg = (
                f"🚨 <b>[DART 공식 공시] {corp_name}</b>\n"
                f"📄 {report_nm}\n"
                f"🔗 <a href='{link}'>공시 원문 바로보기</a>"
            )
            send_telegram(msg)
            sent_links.add(link)
            new_count += 1

    # 2. 국내 키워드 뉴스 확인
    for kw in KR_KEYWORDS:
        for title, link in fetch_kr_news(kw):
            if link not in sent_links:
                msg = (
                    f"🇰🇷 <b>[{kw}]</b>\n"
                    f"{title}\n"
                    f"🔗 <a href='{link}'>기사 읽기</a>"
                )
                send_telegram(msg)
                sent_links.add(link)
                new_count += 1

    # 3. 미국 현지 티커 뉴스 확인
    for ticker in US_TICKERS:
        for title, link in fetch_us_news(ticker):
            if link not in sent_links:
                msg = (
                    f"🇺🇸 <b>[${ticker} 속보]</b>\n"
                    f"{title}\n"
                    f"🔗 <a href='{link}'>Read More</a>"
                )
                send_telegram(msg)
                sent_links.add(link)
                new_count += 1

    if new_count > 0:
        save_history(sent_links)
    print(f"업데이트 완료: 신규 알림 {new_count}건 발송")


if __name__ == "__main__":
    main()
