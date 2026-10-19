import { getStore } from "@edgeone/pages-blob";

// 抓煎蛋首页 -> RSS。逻辑和仓库根目录的 jandan_rss.py 保持一致，只是换成了
// EdgeOne 的 Node 云函数：拿 Blob 当缓存，读的时候顺手刷新。

const BASE = "https://jandan.net";
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

const STORE_NAME = "jandan-rss";
const CACHE_KEY = "feed.xml";
const META_KEY = "meta.json";
const TTL = 15 * 60 * 1000; // 15 分钟内直接用缓存

const FEED_TITLE = "煎蛋 - 首页文章";

// ---------------------------------------------------------------- 工具

function decodeEntities(str) {
  const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  return str.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (whole, ent) => {
    if (ent[0] === "#") {
      const code =
        ent[1].toLowerCase() === "x"
          ? parseInt(ent.slice(2), 16)
          : parseInt(ent.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : whole;
    }
    const hit = named[ent.toLowerCase()];
    return hit === undefined ? whole : hit;
  });
}

function stripTags(fragment) {
  const withBreaks = fragment
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n");
  const text = decodeEntities(withBreaks.replace(/<[^>]+>/g, ""));
  return text
    .replace(/\u00a0/g, " ")
    .split("\n")
    .map((line) => line.trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function escapeXml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function absoluteUrl(src) {
  if (!src) return "";
  if (src.startsWith("//")) return "https:" + src;
  return new URL(src, BASE + "/").toString();
}

function attr(tag, name) {
  const m = tag.match(new RegExp("(?:\\s|^)" + name + '="([^"]*)"', "i"));
  return m ? decodeEntities(m[1]) : "";
}

function cnDate(text, today) {
  const m = text.match(/(?:(\d{4})年)?\s*(\d{1,2})月(\d{1,2})日/);
  if (!m) return null;
  const year = m[1] ? Number(m[1]) : today.getUTCFullYear();
  const month = Number(m[2]);
  const day = Number(m[3]);
  // 12:00 +08:00
  let d = new Date(Date.UTC(year, month - 1, day, 4, 0, 0));
  if (!m[1] && d.getTime() - today.getTime() > 2 * 86400000) {
    d = new Date(Date.UTC(year - 1, month - 1, day, 4, 0, 0));
  }
  return Number.isNaN(d.getTime()) ? null : d;
}

async function fetchText(url, timeoutMs = 10000) {
  let lastError;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(url, {
        headers: {
          "User-Agent": UA,
          Accept: "text/html,application/xhtml+xml,*/*;q=0.8",
          "Accept-Language": "zh-CN,zh;q=0.9",
          Referer: BASE + "/",
        },
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.text();
    } catch (err) {
      lastError = err;
      if (attempt === 0) await new Promise((r) => setTimeout(r, 800));
    }
  }
  throw lastError;
}

async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let cursor = 0;
  const worker = async () => {
    while (true) {
      const i = cursor++;
      if (i >= items.length) return;
      out[i] = await fn(items[i], i);
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, worker)
  );
  return out;
}

// ---------------------------------------------------------------- 解析列表页

function parseListing(html) {
  const marks = [];
  const dateRe =
    /<div class="row date-row">[\s\S]*?<div class="col-12">\s*([\s\S]*?)\s*<\/div>/g;
  for (const m of html.matchAll(dateRe)) {
    marks.push({ at: m.index, kind: "date", text: stripTags(m[1]) });
  }
  const postRe =
    /<div class="post-item row">([\s\S]*?)(?=<div class="post-item row">|<div class="row date-row">|<!-- 广告信息 -->)/g;
  for (const m of html.matchAll(postRe)) {
    marks.push({ at: m.index, kind: "post", chunk: m[1] });
  }
  marks.sort((a, b) => a.at - b.at);

  const posts = [];
  let day = new Date();
  for (const mark of marks) {
    if (mark.kind === "date") {
      day = cnDate(mark.text, new Date()) || day;
      continue;
    }
    const chunk = mark.chunk;
    const titleMatch = chunk.match(
      /<h2 class="post-title"><a href="([^"]+)"[^>]*>([\s\S]*?)<\/a><\/h2>/
    );
    if (!titleMatch) continue;
    const title = stripTags(titleMatch[2]);
    if (!title) continue;

    const excerptMatch = chunk.match(
      /<div class="post-excerpt">([\s\S]*?)<\/div>/
    );
    const thumbMatch = chunk.match(
      /<div class="post-thumb[^"]*">\s*<img[^>]*>/
    );
    const nickMatch = chunk.match(
      /<span class="nick">([\s\S]*?)<\/span>\s*([\s\S]*?)\s*<\/div>/
    );

    posts.push({
      url: absoluteUrl(titleMatch[1]),
      title,
      excerpt: excerptMatch ? stripTags(excerptMatch[1]) : "",
      thumb: thumbMatch ? absoluteUrl(attr(thumbMatch[0], "src")) : "",
      tucao: nickMatch
        ? `${stripTags(nickMatch[1]).replace(/[:：]\s*$/, "")}: ${stripTags(
            nickMatch[2]
          )}`
        : "",
      listDate: new Date(
        Date.UTC(
          day.getUTCFullYear(),
          day.getUTCMonth(),
          day.getUTCDate(),
          4
        )
      ),
    });
  }
  return posts;
}

// ---------------------------------------------------------------- 解析文章页

function cleanContent(fragment) {
  let html = fragment
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<ins\b[\s\S]*?<\/ins>/gi, "")
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, "")
    .replace(
      /<div[^>]*class="[^"]*(?:adsbygoogle|wechat-hide)[^"]*"[^>]*>[\s\S]*?<\/div>/gi,
      ""
    );

  html = html.replace(/<img\b[^>]*>/gi, (tag) => {
    const src = absoluteUrl(
      attr(tag, "src") || attr(tag, "data-src") || attr(tag, "data-original")
    );
    if (!src) return "";
    return `<img src="${escapeXml(
      src
    )}" style="max-width:100%;height:auto" loading="lazy" />`;
  });
  return html.trim();
}

async function parseArticle(url) {
  const page = await fetchText(url);
  const contentMatch = page.match(
    /<!-- google_ad_section_start -->([\s\S]*?)<!-- google_ad_section_end -->/
  );
  const catsMatch = page.match(/<meta name="keywords" content="([^"]*)"/);
  const pubMatch = page.match(
    /发布于\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\s*,\s*(\d{1,2}):(\d{2})/
  );

  let pubDate = null;
  if (pubMatch) {
    pubDate = new Date(
      Date.UTC(
        Number(pubMatch[1]),
        Number(pubMatch[2]) - 1,
        Number(pubMatch[3]),
        Number(pubMatch[4]) - 8,
        Number(pubMatch[5])
      )
    );
  }

  return {
    content: contentMatch ? cleanContent(contentMatch[1]) : "",
    pubDate,
    categories: catsMatch
      ? catsMatch[1]
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean)
      : [],
  };
}

// ---------------------------------------------------------------- RSS

function rfc822(date) {
  return date.toUTCString().replace("GMT", "+0000");
}

function buildRss(items, selfUrl) {
  const built = rfc822(new Date());
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"' +
      ' xmlns:dc="http://purl.org/dc/elements/1.1/"' +
      ' xmlns:media="http://search.yahoo.com/mrss/"' +
      ' xmlns:atom="http://www.w3.org/2005/Atom">',
    "  <channel>",
    `    <title>${escapeXml(FEED_TITLE)}</title>`,
    `    <link>${BASE}/</link>`,
  ];
  if (selfUrl) {
    lines.push(
      `    <atom:link href="${escapeXml(
        selfUrl
      )}" rel="self" type="application/rss+xml" />`
    );
  }
  lines.push(
    "    <description>煎蛋网首页文章全文输出（非官方 RSS，内容版权归煎蛋及原作者所有）</description>",
    "    <language>zh-CN</language>",
    `    <lastBuildDate>${built}</lastBuildDate>`,
    "    <generator>jandan-rss (EdgeOne Makers)</generator>",
    "    <ttl>30</ttl>"
  );

  for (const item of items) {
    lines.push("    <item>");
    lines.push(`      <title>${escapeXml(item.title)}</title>`);
    lines.push(`      <link>${escapeXml(item.url)}</link>`);
    lines.push(
      `      <guid isPermaLink="true">${escapeXml(item.url)}</guid>`
    );
    lines.push(`      <pubDate>${rfc822(item.pubDate)}</pubDate>`);
    lines.push("      <dc:creator>煎蛋</dc:creator>");
    for (const cat of item.categories) {
      lines.push(`      <category>${escapeXml(cat)}</category>`);
    }
    lines.push(
      `      <description>${escapeXml(item.excerpt || item.title)}</description>`
    );
    lines.push(
      `      <content:encoded><![CDATA[${item.content.replaceAll(
        "]]>",
        "]]&gt;"
      )}]]></content:encoded>`
    );
    if (item.thumb) {
      lines.push(`      <media:thumbnail url="${escapeXml(item.thumb)}" />`);
    }
    lines.push("    </item>");
  }
  lines.push("  </channel>", "</rss>", "");
  return lines.join("\n");
}

// ---------------------------------------------------------------- 抓取 + 组装

export async function buildFeed({ limit = 25, fulltext = true, selfUrl = "" } = {}) {
  const home = await fetchText(BASE + "/");
  const posts = parseListing(home).slice(0, limit);
  if (!posts.length) throw new Error("首页没有解析出文章，可能改版了");

  if (fulltext) {
    await mapLimit(posts, 6, async (post) => {
      try {
        const article = await parseArticle(post.url);
        if (article.content) post.content = article.content;
        if (article.pubDate) post.pubDate = article.pubDate;
        post.categories = article.categories;
      } catch {
        // 单篇失败就退回摘要，不影响整个 feed
      }
    });
  }

  const items = posts.map((post) => ({
    title: post.title,
    url: post.url,
    pubDate: post.pubDate || post.listDate,
    excerpt: post.excerpt,
    content:
      post.content ||
      `<p>${escapeXml(post.excerpt || post.title)}</p>` +
        (post.thumb
          ? `<p><img src="${escapeXml(
              post.thumb
            )}" style="max-width:100%" /></p>`
          : ""),
    categories: post.categories || [],
    thumb: post.thumb,
  }));

  if (items.some((i) => i.pubDate)) {
    items.sort((a, b) => b.pubDate - a.pubDate);
  }
  return { xml: buildRss(items, selfUrl), count: items.length };
}

// ---------------------------------------------------------------- HTTP

function rssResponse(xml, { cache = "MISS", builtAt = 0, count = 0 } = {}) {
  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, max-age=300",
      "Access-Control-Allow-Origin": "*",
      "X-Feed-Cache": cache,
      "X-Feed-Items": String(count),
      "X-Feed-Built": String(builtAt),
    },
  });
}

async function openStore() {
  try {
    return getStore({ name: STORE_NAME, consistency: "strong" });
  } catch {
    return null; // 没配 Blob 也能跑，只是每次都现抓
  }
}

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const limit = Math.min(
    40,
    Math.max(5, Number(url.searchParams.get("limit")) || 25)
  );
  const fulltext = url.searchParams.get("fulltext") !== "0";
  const force = url.searchParams.get("refresh") === "1";
  const selfUrl = `${url.origin}${url.pathname}`;

  const store = await openStore();
  let cached = null;
  let meta = null;
  if (store) {
    try {
      cached = await store.get(CACHE_KEY);
      meta = await store.get(META_KEY, { type: "json" });
    } catch {
      // 读缓存失败就当作没有
    }
  }

  const fresh = meta && Date.now() - Number(meta.builtAt || 0) < TTL;
  if (cached && fresh && !force) {
    return rssResponse(cached, {
      cache: "HIT",
      builtAt: meta.builtAt,
      count: meta.count,
    });
  }

  try {
    const { xml, count } = await buildFeed({ limit, fulltext, selfUrl });
    const builtAt = Date.now();
    if (store) {
      try {
        await store.set(CACHE_KEY, xml);
        await store.setJSON(META_KEY, { builtAt, count });
      } catch {
        // 写缓存失败不影响返回
      }
    }
    return rssResponse(xml, { cache: "MISS", builtAt, count });
  } catch (err) {
    if (cached) {
      return rssResponse(cached, {
        cache: "STALE",
        builtAt: meta?.builtAt || 0,
        count: meta?.count || 0,
      });
    }
    return new Response(`生成失败：${err.message}`, {
      status: 502,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}
