import os
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# 감시하고 싶은 기업명이나 키워드 (나중에 여기서 글자만 바꾸시면 됩니다)
KEYWORDS = ["삼성전자", "엔비디아", "SK하이닉스", "미국 증시"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
HISTORY_FILE = "sent_news.json"


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history_set)[-500:], f, ensure_ascii=False, indent=2)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("텔레그램 설정값이 없습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"전송 실패: {e}")


def fetch_google_news(keyword):
    encoded_kw = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=ko&gl=KR&ceid=KR:ko"

    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:3]

        news_list = []
        for item in items:
            title = item.find("title").text
            link = item.find("link").text
            pub_date = item.find("pubDate").text
            news_list.append((title, link, pub_date))
        return news_list
    except Exception as e:
        print(f"[{keyword}] 뉴스 수집 오류: {e}")
        return []


def main():
    sent_links = load_history()
    new_count = 0

    for kw in KEYWORDS:
        articles = fetch_google_news(kw)
        for title, link, pub_date in articles:
            if link not in sent_links:
                msg = f"📰 [{kw} 새 소식]\n\n{title}\n\n🔗 원문 보기:\n{link}"
                send_telegram(msg)
                sent_links.add(link)
                new_count += 1

    if new_count > 0:
        save_history(sent_links)
    print(f"완료: 총 {new_count}건의 새로운 뉴스를 전송했습니다.")


if __name__ == "__main__":
    main()
