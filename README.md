# 煎蛋 RSS

把 [煎蛋网](https://jandan.net/) 首页的文章（煎蛋正文，不是无聊图/妹子图）转成标准 RSS 2.0。
纯 Python 标准库，零依赖。

**在线订阅地址**（GitHub Pages，每 30 分钟自动更新）：

```
https://sseaan.github.io/jandan-rss/feed.xml
```

预览页：<https://sseaan.github.io/jandan-rss/>

输出内容：标题、原文链接、摘要、**正文全文 HTML（含配图）**、精确发布时间、分类、缩略图。
自动跳过重复文章、缓存正文，重复运行只抓新文章。

## 本地试一下

```bash
cd jandan-rss
python3 jandan_rss.py --serve
```

打开 <http://127.0.0.1:8765/> 预览，订阅地址是：

```
http://127.0.0.1:8765/feed.xml
```

这个地址可以填进任何 RSS 阅读器（NetNewsWire、Reeder、Foliate、Inoreader…）。
缺点是电脑得开着；想 7×24 可用就部署到 GitHub Pages（见下）。

只生成静态文件、不起服务：

```bash
python3 jandan_rss.py --out feed.xml          # 默认抓 2 页 ≈ 70 条
python3 jandan_rss.py --pages 1 --out feed.xml # 只抓首页 35 条
python3 jandan_rss.py --no-fulltext           # 只要摘要，不抓正文（快很多）
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--pages N` | 抓取列表页数，每页约 35 条，默认 2 |
| `--no-fulltext` | 不请求文章页，只用列表页的摘要 |
| `--serve` / `--port` | 启动本地服务 / 指定端口（默认 8765） |
| `--interval` | 服务模式下多久重新抓一次，默认 600 秒 |
| `--cache-age` | 正文缓存有效期，默认 6 小时 |
| `--workers` | 并发数，默认 6，别调太高 |

正文缓存在 `cache/articles.json`，删掉就是全量重抓。

## 部署成公网 RSS（GitHub Pages，免费）

仓库里已经带了 `.github/workflows/rss.yml`：每 30 分钟跑一次，抓取后发布到 Pages。

1. 在 GitHub 建一个仓库（比如 `jandan-rss`），把本目录推上去：

   ```bash
   git init && git add . && git commit -m "jandan rss"
   git branch -M main
   git remote add origin git@github.com:<你的用户名>/jandan-rss.git
   git push -u origin main
   ```

2. 仓库 **Settings → Pages → Build and deployment → Source** 选 **GitHub Actions**。

3. 等第一次 Action 跑完，订阅地址就是：

   ```
   https://<你的用户名>.github.io/jandan-rss/feed.xml
   ```

Actions 里用 `actions/cache` 保留了正文缓存，所以定时任务每次只抓新增的几篇，不会把煎蛋刷爆。
想改频率就改 `cron`（GitHub 的定时任务可能延迟几分钟到十几分钟，正常）。

## 它是怎么工作的

1. 抓 `https://jandan.net/` 和 `/page/2`，解析出文章列表（标题、摘要、缩略图、日期分组）。
2. 并发打开每篇文章，取 `div.post-content` 里的正文、`发布于 2026.10.19 , 11:53` 的精确时间、`meta keywords` 里的分类。
3. 清理正文里的广告/脚本/内联 iframe，图片补全为绝对地址，然后拼成 RSS 2.0（`content:encoded` 放全文，`media:thumbnail`/`enclosure` 放缩略图）。

煎蛋自己的 `/feed` 已经返回 403，所以走的是「列表页 + 文章页」这条路，不依赖官方 feed。
图片来自 `img.wangmoyu.com`，实测不带 Referer 也能正常加载；哪天又被防盗链了，在阅读器里加个 Referer 规则或套一层图片代理即可。

## 注意

- 抓取频率建议 ≥ 30 分钟，别拿它做全站爬虫。
- 内容版权归煎蛋网及原作者所有，这个 feed 只适合自己订阅阅读，别二次分发。
- 煎蛋偶尔会改版；选择器集中在 `parse_listing` / `fetch_article` 两个函数里，改版后改那里就行。
