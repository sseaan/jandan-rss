# 煎蛋 RSS

把[煎蛋网](https://jandan.net/)首页文章重新拼成一份可用的 RSS 2.0：标题、原文链接、正文全文（带图）、精确到分钟的发布时间、分类。

煎蛋官方 `/feed` 已经 403 很久了，RSSHub 的 `/jandan` 路由也是拿 `i.jandan.net/feed/` 二次加工，源站一抽风就跟着挂，公共实例还常被限流。所以这里直接抓首页列表，再逐篇取正文自己生成 feed。

- **不用改订阅地址**：两条部署路线产出的内容完全一致，只有更新方式不同。
- **只用标准库 / 零依赖**：Python 版无需 `pip install`，EdgeOne 版只依赖平台自带的 Blob。
- **带缓存**：只抓新增文章，不会每轮都去打煎蛋。

## 目录

- [在线地址](#在线地址)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [部署：GitHub Pages](#部署github-pages)
- [部署：EdgeOne Makers](#部署edgeone-makers)
- [配置项](#配置项)
- [实现说明](#实现说明)
- [已知限制](#已知限制)
- [免责声明](#免责声明)

## 在线地址

| 方案 | 订阅地址 | 更新方式 |
| --- | --- | --- |
| GitHub Pages | `https://sseaan.github.io/jandan-rss/feed.xml` | GitHub Actions 每 30 分钟 |
| EdgeOne Makers | `https://<你的域名>/feed.xml` | 请求触发，缓存 15 分钟 |

`github.io` 在国内时通时不通；EdgeOne Makers 有国内节点但项目默认域名在国内必须带预览参数（详见[已知限制](#已知限制)），长期订阅需要绑一个已备案域名。

## 目录结构

```
jandan-rss/
├── .github/workflows/rss.yml    # CI：定时抓取 → 构建 → 发布 GitHub Pages
├── jandan_rss.py                # Python 版：抓取、生成 feed、本地预览服务（CLI 入口）
├── site/
│   └── index.html               # GitHub Pages 的落地页
├── edgeone/                     # EdgeOne Makers 版（Node 云函数）
│   ├── cloud-functions/feed.js  # 抓取 + 生成 RSS，路由 /feed
│   ├── middleware.js            # 把 /feed.xml 重写到 /feed
│   ├── index.html               # EdgeOne 落地页（含复制订阅地址、强制刷新）
│   ├── package.json             # 依赖：@edgeone/pages-blob
│   └── .env / .edgeone/         # 本地 CLI 凭据与项目元数据（不入库）
├── cache/articles.json          # 正文缓存（不入库，删掉即全量重抓）
└── feed.xml                     # 生成产物（不入库，CI 里输出到 public/）
```

## 快速开始

需要 Python 3.8+，无第三方依赖。

```bash
git clone https://github.com/sseaan/jandan-rss.git
cd jandan-rss
```

**生成静态文件**

```bash
python3 jandan_rss.py --out feed.xml          # 默认抓 2 页列表，带全文
python3 jandan_rss.py --pages 1 --out feed.xml # 只抓首页
python3 jandan_rss.py --no-fulltext            # 不抓正文，只输出摘要，快很多
```

**本地起服务预览**

```bash
python3 jandan_rss.py --serve                  # http://127.0.0.1:8765
```

- 预览页：`http://127.0.0.1:8765/`
- 订阅地址：`http://127.0.0.1:8765/feed.xml`
- 健康检查：`http://127.0.0.1:8765/healthz`

服务模式下内存里缓存构建结果，默认 10 分钟刷新一次（`--interval` 可调）。电脑关机即失效，适合临时看。

## 部署：GitHub Pages

仓库已内置 [`.github/workflows/rss.yml`](.github/workflows/rss.yml)，推送到 `main` 后自动完成以下流程：

1. `actions/cache` 恢复 `cache/` 目录（正文缓存）
2. 运行 `jandan_rss.py --out public/feed.xml --pages 2 --self-url <Pages 地址>`
3. 把 `site/index.html` 复制为 `public/index.html`
4. `actions/upload-pages-artifact` + `actions/deploy-pages` 发布

首次使用请在仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。

调整抓取量改 workflow 里的 `--pages`：`1` 只要首页约 35 条，`3` 再往前多翻一页。GitHub 的 cron 本身会有几分钟到十几分钟的延迟，不要指望准点。

## 部署：EdgeOne Makers

代码在 [`edgeone/`](edgeone/)，是一个 Node 云函数，用 Blob 存生成的 XML 和元信息。

```bash
cd edgeone
npm i -g edgeone@latest          # 只需一次
edgeone login --site china       # 会打开浏览器登录腾讯云
edgeone makers deploy -n jandan-rss
```

首次部署会自动生成 `edgeone.json`，之后在该目录直接 `edgeone makers deploy` 即可。本地调试用 `edgeone makers dev`，跑在 `127.0.0.1:8088`。

因为要用 Blob 存缓存，这条路线必须登录后部署，无法免登录发布。Blob 的 namespace 是首次调用时自动创建的，不用去控制台配置。

**订阅地址**：部署完 CLI 会打印一个带 `?eo_token=...&eo_time=...` 的预览地址，后面拼上 `/feed.xml`（或 `/feed`）即可；`middleware.js` 会把这个路径重写到 `feed.js`。

## 配置项

### Python CLI

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--out PATH` | `feed.xml` | 输出文件路径 |
| `--pages N` | `2` | 抓取列表页数，每页约 35 条 |
| `--no-fulltext` | 关 | 不抓正文，仅输出摘要 |
| `--serve` | 关 | 启动本地 HTTP 服务 |
| `--port PORT` | `8765` | 本地服务端口 |
| `--interval SEC` | `600` | 服务模式下的重建间隔 |
| `--cache-age SEC` | `21600` | 正文缓存有效期（6 小时） |
| `--workers N` | `6` | 并发抓取线程数 |
| `--self-url URL` | 无 | 写入 `atom:link rel="self"` 的公网地址 |
| `--quiet` | 关 | 不打印生成摘要 |

### EdgeOne 查询参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `limit` | `25` | 条数，范围 5–40 |
| `fulltext` | 开 | 传 `0` 只输出摘要，不抓正文 |
| `refresh` | 关 | 传 `1` 强制刷新（距上次构建至少 60 秒，防止被反复触发） |

响应头里带 `X-Feed-Cache`（`HIT` / `MISS` / `STALE`）、`X-Feed-Items`、`X-Feed-Built`，方便排查缓存状态。

## 实现说明

```
列表页（/、/page/2…）
  ├─ post-title      → 标题、原文链接
  ├─ post-excerpt    → 摘要
  ├─ post-thumb      → 缩略图
  ├─ date-row        → 日期分组（只有日期，无时间）
  └─ nick            → 煎蛋式吐槽，作为 blockquote 附在正文后
        │
        ▼  并发抓取（默认 6 并发）
文章页
  ├─ <!-- google_ad_section_start -->
  │                  → 正文 HTML，清理 script/style/iframe/广告，图片补全域名
  ├─ 发布于 2026.10.19 , 11:53
  │                  → 精确发布时间（Asia/Shanghai）
  └─ meta[name=keywords]
                     → 分类
        │
        ▼
RSS 2.0：content:encoded 放全文，media:thumbnail 放缩略图
```

要点：

- 列表页只有日期没有时间，所以**发布时间必须去文章页取**；取不到时退回列表页日期（当日 12:00）。
- 单篇抓取失败不会让整个 feed 挂掉，只退回摘要。
- Python 版正文缓存到 `cache/articles.json`，按 URL 记录 `content` / `categories` / `pubDate` / `fetched_at`，重复运行只抓新文章。
- EdgeOne 版把 XML 和 `{builtAt, count}` 元信息一起写进 Blob，**懒刷新**：缓存过期后由第一个来访的请求顺手重建，其余请求继续读旧缓存，不会一起卡住；重建失败时返回上一次的缓存（`STALE`）。
- 煎蛋若改版，只需改两个函数：Python 的 `parse_listing` / `fetch_article`，EdgeOne 的 `parseListing` / `parseArticle`。

## 已知限制

- **GitHub Actions 的 cron 会延迟**，几分钟到十几分钟不等；仓库连续 60 天没有提交，定时任务会被自动暂停，去 Actions 页面点一次 *Run workflow* 即可恢复。
- **EdgeOne 预览链接只有 3 小时**：Makers 的项目域名和部署域名从中国大陆访问必须带预览参数（`?eo_token=...`），过期即 401。这不是代码问题，境外网络直接访问项目域名不受影响；要在国内长期订阅，需在控制台「域名管理」绑定一个已备案域名。
- **图片**：煎蛋的图以前在 `moyu.im`，有 Referer 校验会导致阅读器裂图；现在换成 `img.wangmoyu.com`，实测不带 Referer 也能加载。若哪天又加校验，可在阅读器补一条 Referer 规则，或套一层图片代理。
- **两套部署抓到的内容偶尔差几分钟**：Actions 跑在海外，EdgeOne 跑在国内，属正常现象。
- 官方 `/feed` 返回 403，带浏览器 UA 也一样，因此完全没有走官方源。

## 免责声明

内容版权归煎蛋网及原作者所有。本项目仅用于个人订阅阅读，请勿二次分发或用于搭建站点。
