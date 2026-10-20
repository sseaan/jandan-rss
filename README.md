# 煎蛋 RSS

把[煎蛋网](https://jandan.net/)首页文章重新拼成一份可用的 RSS 2.0：标题、原文链接、正文全文（带图）、精确到分钟的发布时间、分类。

煎蛋官方 `/feed` 已经 403 很久了，RSSHub 的 `/jandan` 路由也是拿 `i.jandan.net/feed/` 二次加工，源站一抽风就跟着挂，公共实例还常被限流。所以这里直接抓首页列表，再逐篇取正文自己生成 feed。

- **一份产物，两处托管**：GitHub Actions 每 12 小时生成一次 `public/`，GitHub Pages 和 EdgeOne 用同一份静态文件，内容完全一致。
- **零依赖**：只用 Python 标准库，不需要 `pip install`。
- **带缓存**：正文缓存到 `cache/articles.json`，重复运行只抓新增文章。

## 目录

- [在线地址](#在线地址)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [部署：GitHub Pages](#部署github-pages)
- [部署：EdgeOne Makers](#部署edgeone-makers)
- [CI 流程](#ci-流程)
- [配置项](#配置项)
- [实现说明](#实现说明)
- [已知限制](#已知限制)
- [免责声明](#免责声明)

## 在线地址

| 方案 | 订阅地址 | 更新方式 |
| --- | --- | --- |
| GitHub Pages | `https://sseaan.github.io/jandan-rss/feed.xml` | GitHub Actions 每 12 小时 |
| EdgeOne Makers | `https://<你的域名>/feed.xml` | GitHub Actions 每 12 小时直传 |

`github.io` 在国内时通时不通；EdgeOne Makers 有国内节点，但项目默认域名在国内访问需要预览参数，长期订阅需要绑一个已备案域名（详见[已知限制](#已知限制)）。

## 目录结构

```
jandan-rss/
├── .github/workflows/rss.yml    # CI：12 小时抓取 → 生成 public/ → Pages + EdgeOne
├── jandan_rss.py                # 抓取、生成 feed、本地预览服务（CLI 入口）
├── index.html                   # 落地页，CI 复制进 public/
├── edgeone.json                 # EdgeOne 静态配置：/feed 重写、feed 缓存头
├── cache/articles.json          # 正文缓存（不入库，删掉即全量重抓）
└── public/                      # CI 产物（不入库）
```

## 快速开始

需要 Python 3.8+，无第三方依赖。

```bash
git clone https://github.com/sseaan/jandan-rss.git
cd jandan-rss
```

**生成静态文件**

```bash
python3 jandan_rss.py --out public/feed.xml --pages 2   # 默认抓 2 页，约 70 条，带全文
python3 jandan_rss.py --pages 1 --out feed.xml          # 只抓首页
python3 jandan_rss.py --no-fulltext                     # 不抓正文，只输出摘要，快很多
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

仓库已内置 [.github/workflows/rss.yml](.github/workflows/rss.yml)，推送到 `main` 后自动完成：

1. `actions/cache` 恢复 `cache/` 目录（正文缓存）；
2. 运行 `jandan_rss.py --out public/feed.xml --pages 2`；
3. 复制 `index.html` 和 `edgeone.json` 到 `public/`；
4. 校验 feed 至少 20 条；
5. `actions/upload-pages-artifact` + `actions/deploy-pages` 发布。

首次使用请在仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。

## 部署：EdgeOne Makers

EdgeOne 这边是**纯静态直传**：CI 不跑云函数，也不让 EdgeOne 构建，直接把 `public/` 上传。因此：

- 项目必须是 **Upload（直传）类型**；GitHub 集成类型的项目不能用 CLI 更新，会报 `Provider 'Github'`。
- 如果已有同名 GitHub 集成项目，先在控制台删除，再让 CI 创建同名 Upload 项目。
- 删除旧项目后默认域名会变；要保留订阅地址，请在控制台给新项目绑定自定义域名。

### 一次性配置

1. 控制台 → Makers → 删除旧的 `jandan-rss` 项目（如果它是 GitHub 集成类型）。
2. 控制台 → **API Token** → 新建，复制 token。
3. GitHub 仓库 → **Settings → Secrets and variables → Actions** → 新建 secret：`EDGEONE_API_TOKEN`。
4. 推送 `main`，workflow 会自动创建/更新 `jandan-rss` 项目并上传 `public/`。

### 手动部署（可选）

本地已经登录 EdgeOne CLI 时：

```bash
edgeone login
edgeone makers deploy ./public -n jandan-rss
```

`-n` 表示项目名：不存在就创建，存在且是 Upload 类型就更新。

### 订阅地址

部署完控制台会给项目域名，后面拼 `/feed.xml` 或 `/feed` 都能用：

- `/feed.xml`：静态文件本身；
- `/feed`：由 [edgeone.json](edgeone.json) 重写到 `/feed.xml`，兼容旧订阅。

默认域名在国内访问需要预览参数（`?eo_token=...`），过期即 401；境外网络直接访问项目域名不受影响。要在国内长期订阅，请在控制台「域名管理」绑定一个已备案域名。

## CI 流程

```
schedule（每 12 小时，北京时间 09:00 / 21:00）
  └─ build
       ├─ actions/cache 恢复 cache/
       ├─ jandan_rss.py → public/feed.xml（约 70 条全文）
       ├─ 复制 index.html、edgeone.json
       ├─ 校验 XML 可解析且条数 ≥ 20
       ├─ upload-artifact
       ├─ deploy-pages
       └─ deploy-edgeone（TencentEdgeOne/edgeone-pages-action@v1）
```

`push` 到 `main` 也会触发一次，方便改完配置立即验证。GitHub 的 cron 本身会有几分钟到十几分钟的延迟，不要指望准点。

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
| `--self-url URL` | 无 | 写入 `atom:link rel="self"`；CI 不传，因为同一份 feed 有两个域名 |
| `--quiet` | 关 | 不打印生成摘要 |

静态版没有 `limit` / `fulltext` / `refresh` 查询参数，也没有请求时刷新；更新只由 CI 触发。

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
- 只保留一套解析器（Python）。CI 生成静态文件后，Pages 和 EdgeOne 都只是托管，不再各自抓取。
- `<ttl>` 是 720 分钟，和 12 小时更新节奏一致。
- 煎蛋若改版，只需改 `parse_listing` / `fetch_article` 两处。

## 开发

本仓库的提交使用 YubiKey OpenPGP 签名。仓库配置了 `commit.gpgsign=true`，提交时按提示触摸 YubiKey 即可。

## 已知限制

- **12 小时更新 + Actions 延迟**：最新一篇最多可能晚 12 小时以上；一次运行失败会变成 24 小时空窗。建议加一条失败/漏跑告警（例如 healthchecks.io），并在 EdgeOne 保留上一次成功部署以便回滚。
- **GitHub Actions 的 cron 会延迟**，几分钟到十几分钟不等；仓库连续 60 天没有提交，定时任务会被自动暂停，去 Actions 页面点一次 *Run workflow* 即可恢复。
- **EdgeOne 预览链接**：项目默认域名和部署域名从中国大陆访问需要预览参数，过期即 401。这不是代码问题，境外网络直接访问不受影响；要在国内长期订阅，需绑定已备案域名。
- **EdgeOne 项目类型**：直传只能更新 Upload 类型项目。删除旧项目后默认域名会变；如果订阅地址不能变，请提前绑定自定义域名，或改用新的项目名并同步修改 workflow。
- **静态版没有查询参数**：`?limit=`、`?fulltext=0`、`?refresh=1` 都不再支持；需要不同条数就改 workflow 里的 `--pages`。
- **图片**：煎蛋的图以前在 `moyu.im`，有 Referer 校验会导致阅读器裂图；现在换成 `img.wangmoyu.com`，实测不带 Referer 也能加载。若哪天又加校验，可在阅读器补一条 Referer 规则，或套一层图片代理。
- 官方 `/feed` 返回 403，带浏览器 UA 也一样，因此完全没有走官方源。

## 免责声明

内容版权归煎蛋网及原作者所有。本项目仅用于个人订阅阅读，请勿二次分发或用于搭建站点。
