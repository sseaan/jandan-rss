#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把煎蛋网首页文章转成 RSS 2.0。

用法:
    python3 jandan_rss.py --out feed.xml          # 生成静态 feed.xml
    python3 jandan_rss.py --serve                 # 本地起服务, http://127.0.0.1:8765/feed.xml
    python3 jandan_rss.py --serve --port 9000
    python3 jandan_rss.py --pages 1 --no-fulltext  # 只取首页, 不带全文

设计:
    * 只用标准库, 无需 pip install
    * 列表页 -> 文章页, 抓取标题/摘要/正文/精确发布时间/分类
    * 文章内容缓存到 cache/articles.json, 重复运行只抓新文章
"""

import argparse
import html
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

BASE = "https://jandan.net"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "cache", "articles.json")
DEFAULT_OUT = os.path.join(HERE, "feed.xml")

# ---------------------------------------------------------------- 网络

def http_get(url, timeout=30, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": BASE + "/",
            })
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, "replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            if isinstance(exc, HTTPError) and exc.code in (403, 404):
                break
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("GET %s failed: %s" % (url, last))

# ---------------------------------------------------------------- HTML 工具

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")
BLANK_RE = re.compile(r"\n{3,}")


def strip_tags(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</p>", "\n", fragment, flags=re.I)
    text = TAG_RE.sub("", fragment)
    text = html.unescape(text).replace("\xa0", " ")
    text = WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return BLANK_RE.sub("\n\n", text).strip()


def attr(tag, name):
    m = re.search(r'%s="([^"]*)"' % re.escape(name), tag, re.I)
    return html.unescape(m.group(1)) if m else ""


def absolute_url(src):
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    return urljoin(BASE + "/", src)


def parse_cn_date(text, today=None):
    """'10月19日' / '2025年12月31日' -> date"""
    today = today or datetime.now(TZ)
    m = re.search(r"(?:(\d{4})年)?\s*(\d{1,2})月(\d{1,2})日", text)
    if not m:
        return None
    year = int(m.group(1)) if m.group(1) else today.year
    month, day = int(m.group(2)), int(m.group(3))
    try:
        d = datetime(year, month, day, tzinfo=TZ)
    except ValueError:
        return None
    # 没有年份且日期比今天晚很多 => 其实是去年(跨年那几天)
    if not m.group(1) and d - today > timedelta(days=2):
        d = d.replace(year=year - 1)
    return d

# ---------------------------------------------------------------- 列表页

ITEM_SPLIT = re.compile(
    r'<div class="post-item row">(.*?)(?=<div class="post-item row">|<div class="row date-row">|<!-- 广告信息 -->)',
    re.S,
)
DATE_ROW = re.compile(r'<div class="row date-row">.*?<div class="col-12">\s*(.*?)\s*</div>', re.S)


def parse_listing(page_html, today=None):
    marks = [(m.start(), "date", m.group(1)) for m in DATE_ROW.finditer(page_html)]
    marks += [(m.start(), "post", m.group(1)) for m in ITEM_SPLIT.finditer(page_html)]
    marks.sort(key=lambda x: x[0])

    posts, current_date = [], today or datetime.now(TZ)
    for _, kind, chunk in marks:
        if kind == "date":
            parsed = parse_cn_date(strip_tags(chunk), current_date)
            if parsed:
                current_date = parsed
            continue

        tm = re.search(r'<h2 class="post-title"><a href="([^"]+)"[^>]*>(.*?)</a></h2>', chunk, re.S)
        if not tm:
            continue
        url = absolute_url(tm.group(1))
        title = strip_tags(tm.group(2))
        if not title:
            continue

        em = re.search(r'<div class="post-excerpt">(.*?)</div>', chunk, re.S)
        excerpt = strip_tags(em.group(1)) if em else ""

        thumb_m = re.search(r'<div class="post-thumb[^"]*">\s*<img[^>]*>', chunk, re.S)
        thumb = absolute_url(attr(thumb_m.group(0), "src")) if thumb_m else ""

        cm = re.search(r'<div class="post-comment-count[^"]*">\s*(\d+)', chunk)
        comments = int(cm.group(1)) if cm else 0

        nick = re.search(r'<span class="nick">(.*?)</span>\s*(.*?)\s*</div>', chunk, re.S)
        tucao = ""
        if nick:
            who = strip_tags(nick.group(1)).rstrip(":：")
            what = strip_tags(nick.group(2))
            if what:
                tucao = "%s: %s" % (who, what)

        posts.append({
            "url": url,
            "title": title,
            "excerpt": excerpt,
            "thumb": thumb,
            "comments": comments,
            "tucao": tucao,
            "list_date": current_date.replace(hour=12, minute=0, second=0, microsecond=0),
        })
    return posts


def fetch_listing(pages):
    seen, posts = set(), []
    for page in range(1, pages + 1):
        url = BASE + "/" if page == 1 else "%s/page/%d" % (BASE, page)
        try:
            page_html = http_get(url)
        except Exception as exc:  # 后面几页失败不影响整体
            print("[warn] 列表页失败 %s: %s" % (url, exc), file=sys.stderr)
            break
        batch = parse_listing(page_html)
        fresh = [p for p in batch if p["url"] not in seen]
        for p in fresh:
            seen.add(p["url"])
        posts.extend(fresh)
        if not fresh:
            break
        time.sleep(0.3)
    return posts

# ---------------------------------------------------------------- 文章页

CONTENT_RE = re.compile(
    r"<!-- google_ad_section_start -->(.*?)<!-- google_ad_section_end -->", re.S
)
PUB_RE = re.compile(
    r"发布于\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\s*,\s*(\d{1,2}):(\d{2})"
)
CAT_RE = re.compile(r'<meta name="keywords" content="([^"]*)"')


def clean_content(fragment):
    fragment = re.sub(r"<script.*?</script>", "", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<style.*?</style>", "", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<ins\b.*?</ins>", "", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<iframe.*?</iframe>", "", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<div[^>]*class=\"[^\"]*(?:adsbygoogle|wechat-hide)[^\"]*\"[^>]*>.*?</div>",
                      "", fragment, flags=re.S | re.I)

    def fix_img(m):
        tag = m.group(0)
        src = attr(tag, "src") or attr(tag, "data-src") or attr(tag, "data-original")
        src = absolute_url(src)
        if not src:
            return ""
        width = attr(tag, "width")
        style = ' style="max-width:100%;height:auto"' if not width else ' style="max-width:100%"'
        return '<img src="%s"%s loading="lazy" />' % (html.escape(src, quote=True), style)

    fragment = re.sub(r"<img\b[^>]*>", fix_img, fragment, flags=re.I)
    fragment = re.sub(r"<a\b([^>]*)>", lambda m: "<a%s>" % m.group(1), fragment, flags=re.I)
    return fragment.strip()


def fetch_article(url):
    page = http_get(url)
    content_m = CONTENT_RE.search(page)
    content = clean_content(content_m.group(1)) if content_m else ""

    pub = None
    pm = PUB_RE.search(page)
    if pm:
        pub = datetime(int(pm.group(1)), int(pm.group(2)), int(pm.group(3)),
                       int(pm.group(4)), int(pm.group(5)), tzinfo=TZ)

    cm = CAT_RE.search(page)
    cats = [c.strip() for c in (cm.group(1).split(",") if cm else []) if c.strip()]

    return {"content": content, "pubDate": pub, "categories": cats}

# ---------------------------------------------------------------- 缓存

_cache_lock = threading.Lock()


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE_FILE)


def cache_fresh(entry, max_age):
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, ValueError):
        return False
    return datetime.now(timezone.utc) - fetched < timedelta(seconds=max_age)

# ---------------------------------------------------------------- 汇总

def collect(pages=2, fulltext=True, max_age=6 * 3600, workers=6):
    cache = load_cache()
    posts = fetch_listing(pages)

    if fulltext:
        todo = [p for p in posts
                if not (p["url"] in cache and cache_fresh(cache[p["url"]], max_age))]

        def work(post):
            try:
                return post["url"], fetch_article(post["url"])
            except Exception as exc:
                print("[warn] 正文失败 %s: %s" % (post["url"], exc), file=sys.stderr)
                return post["url"], None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, p) for p in todo]
            for fut in as_completed(futures):
                url, data = fut.result()
                if not data:
                    continue
                with _cache_lock:
                    cache[url] = {
                        "content": data["content"],
                        "categories": data["categories"],
                        "pubDate": data["pubDate"].isoformat() if data["pubDate"] else None,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
        save_cache(cache)

    items = []
    for post in posts:
        entry = cache.get(post["url"], {})
        pub = post["list_date"]
        if entry.get("pubDate"):
            try:
                pub = datetime.fromisoformat(entry["pubDate"])
            except ValueError:
                pass
        content = entry.get("content") or ""
        if not content:
            body = html.escape(post["excerpt"] or post["title"])
            content = "<p>%s</p>" % body
            if post["thumb"]:
                content = ('<p><img src="%s" style="max-width:100%%" /></p>' % post["thumb"]) + content
        if post["tucao"]:
            content += "\n<blockquote><p>%s</p></blockquote>" % html.escape(post["tucao"])

        items.append({
            "title": post["title"],
            "link": post["url"],
            "guid": post["url"],
            "pubDate": pub,
            "description": post["excerpt"] or strip_tags(content)[:200],
            "content": content,
            "categories": entry.get("categories") or [],
            "thumb": post["thumb"],
            "comments": post["comments"],
        })
    return items

# ---------------------------------------------------------------- RSS

def rfc822(dt):
    return format_datetime(dt.astimezone(TZ))


def build_rss(items, title="煎蛋 - 首页文章", link=BASE + "/", desc=None, self_url=None):
    desc = desc or "煎蛋网首页文章全文输出（非官方 RSS，内容版权归煎蛋及原作者所有）"
    now = rfc822(datetime.now(TZ))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:media="http://search.yahoo.com/mrss/"'
        ' xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        "    <title>%s</title>" % html.escape(title),
        "    <link>%s</link>" % html.escape(link),
    ]
    if self_url:
        out.append(
            "    <atom:link href=\"%s\" rel=\"self\" type=\"application/rss+xml\" />"
            % html.escape(self_url)
        )
    out += [
        "    <description>%s</description>" % html.escape(desc),
        "    <language>zh-CN</language>",
        "    <lastBuildDate>%s</lastBuildDate>" % now,
        "    <generator>jandan-rss</generator>",
        "    <ttl>720</ttl>",
    ]
    for it in items:
        out.append("    <item>")
        out.append("      <title>%s</title>" % html.escape(it["title"]))
        out.append("      <link>%s</link>" % html.escape(it["link"]))
        out.append('      <guid isPermaLink="true">%s</guid>' % html.escape(it["guid"]))
        out.append("      <pubDate>%s</pubDate>" % rfc822(it["pubDate"]))
        out.append("      <dc:creator>煎蛋</dc:creator>")
        for cat in it["categories"]:
            out.append("      <category>%s</category>" % html.escape(cat))
        out.append("      <description>%s</description>" % html.escape(it["description"]))
        out.append("      <content:encoded><![CDATA[%s]]></content:encoded>"
                   % it["content"].replace("]]>", "]]&gt;"))
        if it["thumb"]:
            out.append('      <media:thumbnail url="%s" />' % html.escape(it["thumb"]))
        out.append("    </item>")
    out += ["  </channel>", "</rss>", ""]
    return "\n".join(out)


def write_rss(path, xml):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(xml)
    os.replace(tmp, path)


def generate(out=DEFAULT_OUT, pages=2, fulltext=True, max_age=6 * 3600, workers=6,
             self_url=None):
    items = collect(pages=pages, fulltext=fulltext, max_age=max_age, workers=workers)
    xml = build_rss(items, self_url=self_url)
    write_rss(out, xml)
    return items, xml

# ---------------------------------------------------------------- 本地服务

INDEX_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>煎蛋 RSS</title>
<style>
 body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;max-width:760px;margin:40px auto;padding:0 18px;color:#222}
 h1{font-size:22px} .meta{color:#666;font-size:14px} a{color:#0b62d0;text-decoration:none}
 li{margin:12px 0} code{background:#f3f3f3;padding:2px 6px;border-radius:4px}
</style></head><body>
<h1>煎蛋 - 首页文章 RSS</h1>
<p class="meta">订阅地址：<code>%(feed_url)s</code><br>更新时间：%(updated)s　共 %(count)d 条</p>
<ul>%(items)s</ul>
</body></html>
"""


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=300")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/feed.xml", "/rss", "/rss.xml", "/"):
                items, xml, err = state.get()
                if path == "/":
                    host = self.headers.get("Host") or "127.0.0.1:%d" % state.port
                    lis = "".join(
                        '<li><a href="%s">%s</a><div class="meta">%s</div></li>'
                        % (html.escape(i["link"]), html.escape(i["title"]),
                           i["pubDate"].strftime("%Y-%m-%d %H:%M"))
                        for i in items
                    )
                    body = INDEX_HTML % {
                        "feed_url": "http://%s/feed.xml" % host,
                        "updated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
                        "count": len(items),
                        "items": lis,
                    }
                    return self._send(200, body, "text/html; charset=utf-8")
                return self._send(200, xml, "application/rss+xml; charset=utf-8")
            if path == "/healthz":
                return self._send(200, "ok", "text/plain; charset=utf-8")
            return self._send(404, "not found", "text/plain; charset=utf-8")

    return Handler


class FeedState:
    def __init__(self, args):
        self.args = args
        self.items = []
        self.xml = None
        self.built_at = 0
        self.lock = threading.Lock()
        self.port = args.port

    def get(self):
        with self.lock:
            age = time.time() - self.built_at
            if self.xml is None or age > self.args.interval:
                try:
                    items, xml = generate(self.args.out, self.args.pages,
                                          not self.args.no_fulltext,
                                          self.args.cache_age, self.args.workers,
                                          self_url="http://127.0.0.1:%d/feed.xml" % self.port)
                    self.items, self.xml, self.built_at = items, xml, time.time()
                except Exception as exc:
                    print("[warn] 刷新失败: %s" % exc, file=sys.stderr)
                    if self.xml is None:
                        self.xml = build_rss([])
            return self.items, self.xml, None


def serve(args):
    state = FeedState(args)
    try:
        state.get()
    except Exception as exc:
        print("[warn] 首次抓取失败: %s" % exc, file=sys.stderr)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state))
    print("煎蛋 RSS 已启动:")
    print("  http://127.0.0.1:%d/feed.xml  <- 订阅这个地址" % args.port)
    print("  http://127.0.0.1:%d/           <- 预览" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")

# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="煎蛋网首页文章 -> RSS")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出的 feed 文件路径")
    ap.add_argument("--pages", type=int, default=2, help="抓取列表页数，每页约 35 条（默认 2）")
    ap.add_argument("--no-fulltext", action="store_true", help="不抓文章正文，仅摘要")
    ap.add_argument("--serve", action="store_true", help="启动本地 HTTP 服务")
    ap.add_argument("--port", type=int, default=8765, help="服务端口（默认 8765）")
    ap.add_argument("--interval", type=int, default=600, help="服务模式下的刷新间隔秒数")
    ap.add_argument("--cache-age", type=int, default=6 * 3600, help="正文缓存有效期秒数")
    ap.add_argument("--workers", type=int, default=6, help="并发抓取线程数")
    ap.add_argument("--self-url", default=None, help="feed 自身的公网地址（写入 atom:link）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.serve:
        serve(args)
        return 0

    t0 = time.time()
    items, xml = generate(args.out, args.pages, not args.no_fulltext,
                          args.cache_age, args.workers, self_url=args.self_url)
    if not args.quiet:
        newest = items[0]["pubDate"].strftime("%Y-%m-%d %H:%M") if items else "-"
        print("已生成 %s：%d 条，最新 %s，耗时 %.1fs"
              % (args.out, len(items), newest, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
