# 煎蛋 RSS

煎蛋的官方 RSS 早就不能用了，`jandan.net/feed` 现在直接 403；RSSHub 倒是有个 `/jandan` 路由，但它也是拿 `i.jandan.net/feed/` 再加工，源站一抽风就跟着挂，公共实例还经常限流。所以干脆自己抓首页，重新拼一个 feed。

现在有两条部署路线，内容是一样的：标题、原文链接、正文全文（带图）、精确到分钟的发布时间、分类。区别只在更新方式和国内的访问速度。

**GitHub Pages**，每 30 分钟自动更新一次：

```
https://sseaan.github.io/jandan-rss/feed.xml
```

**EdgeOne Makers**，按需刷新，适合手里有已备案域名、想让国内访问更稳的情况。代码在 `edgeone/`，怎么部署见下面。

## GitHub Pages 这套

仓库里带了 `.github/workflows/rss.yml`，每 30 分钟跑一次 `jandan_rss.py`，把生成的 `feed.xml` 发布到 Pages。

默认抓 2 页列表，大概 70 条，够阅读器补历史。Actions 里用 `actions/cache` 缓存了正文，所以定时任务每次只抓新增的那几篇，不会反复去打煎蛋。

改抓取量就改 workflow 里的 `--pages`：`1` 是只要首页 35 条，`3` 是往前多翻一页。注意 GitHub 的 cron 本来就会延迟几分钟到十几分钟，别指望它准点。

还有个坑：仓库连续 60 天没有提交，GitHub 会自动暂停定时任务，去 Actions 页面点一次 "Run workflow" 就恢复了。

## EdgeOne Makers 这套

`github.io` 在国内时好时坏，阅读器拉不到更新挺烦的。EdgeOne Makers 有免费额度、国内节点，拿来跑这种小抓取正合适，所以补了一份。

代码在 [`edgeone/`](edgeone/)，是一个 Node 云函数（`cloud-functions/feed.js`），用 Blob 存生成的 XML。部署：

```bash
cd edgeone
npm i -g edgeone@latest          # 只装一次
edgeone login --site china       # 会打开浏览器登录腾讯云
edgeone makers deploy -n jandan-rss
```

第一次部署会自动生成 `edgeone.json`，之后在这个目录里直接 `edgeone makers deploy` 就行。本地想先看看效果可以 `edgeone makers dev`，跑在 `127.0.0.1:8088`。

因为用到了 Blob 存缓存，这个方案必须登录后部署，没法走免登录发布。这套已经在我自己的账号上跑起来了，25 条、正文和配图都正常。

部署完 CLI 会打一个带 `?eo_token=...&eo_time=...` 的预览地址，后面拼上 `/feed.xml` 就是订阅地址。`middleware.js` 把这个路径转到 `/feed`，直接订 `/feed` 也行。

这里有个平台限制得说清楚：Makers 的项目域名和部署域名，从中国大陆访问必须带预览链接，而预览链接只有 3 小时，过期就是 401。这不是代码的问题，境外网络直接访问项目域名不受影响。想在国内长期订阅，只能去控制台「域名管理」绑一个已经备案的域名，之后 `https://你的域名/feed.xml` 就稳定了。

它没有定时器，所以是懒刷新：生成的 XML 在 Blob 里缓存 15 分钟，过期之后第一个来拉取的请求顺手重新抓一遍，一般两三秒；这期间别的请求还是拿旧缓存，不会一起卡住。想立刻刷新就访问 `/feed?refresh=1`。

能调的东西不多，都是 query 参数：`limit` 控制条数，默认 25，范围 5–40；`fulltext=0` 只输出摘要，不抓正文，快很多。

Blob 的 namespace 是第一次调用时自动建的，不用去控制台配。

## 本地跑

不想部署，本机跑一下也行：

```bash
python3 jandan_rss.py --serve
```

然后订阅 `http://127.0.0.1:8765/feed.xml`，页面上能直接预览。电脑关了就没了，适合临时看看。

只想生成一个静态文件：

```bash
python3 jandan_rss.py --out feed.xml
python3 jandan_rss.py --pages 1 --out feed.xml    # 只要首页
python3 jandan_rss.py --no-fulltext                # 不抓正文，快很多
```

正文缓存在 `cache/articles.json`，删掉就是全量重抓。

## 抓取逻辑

首页和 `/page/2` 拿文章列表，标题、摘要、缩略图、日期分组都在列表里；然后并发打开每篇文章，从 `div.post-content` 取正文，从「发布于 2026.10.19 , 11:53」这行取精确时间，从 `meta keywords` 取分类；最后拼成 RSS 2.0，正文塞 `content:encoded`，缩略图塞 `media:thumbnail`。

列表页只有日期没有具体时间，所以时间必须去文章页拿。单篇抓失败就退回摘要，不会让整个 feed 挂掉。

煎蛋要是改版，改两个函数就行：Python 版的 `parse_listing` / `fetch_article`，EdgeOne 版的 `parseListing` / `parseArticle`。

## 踩过的坑

官方 `/feed` 返回 403，带浏览器 UA 也一样，所以完全没走官方源。

图片以前在 `moyu.im`，有 Referer 校验，RSS 阅读器里全是裂图；现在换成了 `img.wangmoyu.com`，实测不带 Referer 也能加载。哪天又加校验，在阅读器里补一条 Referer 规则，或者套一层图片代理。

GitHub Actions 跑在海外，EdgeOne 跑在国内，两边抓到的内容偶尔会有几分钟差异，正常。

## 版权

内容都是煎蛋和原作者的，这个 feed 只适合自己订阅阅读，别拿去二次分发或者做站。
