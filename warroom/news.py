"""新聞抓取：GDELT 為主（退避重試），Google News RSS 備援。中文 query 一律 URL 編碼。"""
import json, time, re, urllib.request, urllib.parse

UA = {"User-Agent": "advisor-war-room/1.0 (personal research)"}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def from_gdelt(query, limit=6):
    q = urllib.parse.quote(query)
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&maxrecords={limit}&format=json&sort=datedesc"
    for attempt in range(3):
        try:
            d = json.loads(_get(url))
            return [{"title": a.get("title", "").strip(), "url": a.get("url", ""),
                     "date": a.get("seendate", ""), "src": a.get("domain", "")}
                    for a in d.get("articles", [])]
        except Exception:
            time.sleep((attempt + 1) * 2)
    return None


def from_google_rss(query, limit=6):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-TW"
    try:
        txt = _get(url).decode("utf-8", "replace")
        items = re.findall(r"<item>(.*?)</item>", txt, re.S)[:limit]
        out = []
        for it in items:
            t = re.search(r"<title>(.*?)</title>", it, re.S)
            l = re.search(r"<link>(.*?)</link>", it, re.S)
            p = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            out.append({"title": (t.group(1) if t else "").strip(),
                        "url": l.group(1) if l else "", "date": p.group(1) if p else "", "src": "Google News"})
        return out
    except Exception:
        return None


def fetch_news(query_zh, query_en=None, limit=6):
    """台股：Google News RSS(中文名) 相關度最高，優先；失敗才退 GDELT(英文名)。"""
    arts = from_google_rss(query_zh, limit) if query_zh else None
    if not arts:
        arts = from_gdelt(query_en or query_zh, limit)
    return arts or []


if __name__ == "__main__":
    import sys
    zh = sys.argv[1] if len(sys.argv) > 1 else "台積電"
    en = sys.argv[2] if len(sys.argv) > 2 else "TSMC"
    for a in fetch_news(zh, en, 5):
        print(f"- {a['title'][:60]}  ({a['src']})")
