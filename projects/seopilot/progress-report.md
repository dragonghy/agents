# SEOPilot + SEOPilot Lite 项目完整进展报告

> 报告日期：2026-03-21
> 报告人：product-mia（产品经理）
> 项目发起人：founder-noah

---

## 一、SEOPilot — Shopify AI SEO App

### 1. 项目定义

**做什么**：一个 Shopify 原生 App，用 AI 自动扫描店铺 SEO 问题并一键修复。

**解决什么问题**：Shopify 小商家知道 SEO 重要，但不懂怎么做。现有竞品（Plug in SEO、Booster SEO）只给扫描报告，商家看到红色警告却不会改。SEOPilot 的核心差异是 **AI 驱动的自动修复**——扫描发现问题后，AI 自动生成修复文案，商家一键应用。

**目标用户**：
- 主要：Shopify 小商家（月收入 $1K-$50K），不懂 SEO，付费意愿 $19-49/月
- 次要：代运营/自由职业者，管理多店铺，付费意愿 $49-99/月

### 2. 功能清单

**已实现功能（M1-M4，全部验收通过）：**

| Milestone | 功能 | Ticket | 状态 |
|-----------|------|--------|------|
| M1 | Shopify App 骨架 + Prisma DB + OAuth + 基础 UI（Polaris） | #258 | ✅ 验收通过 |
| M2 | SEO 扫描引擎 — GraphQL 数据获取 + 6 项规则引擎 + 评分 + Dashboard | #260 | ✅ 验收通过 |
| M3 | AI 自动修复引擎 — OpenAI 集成 + 一键修复 + 批量 Alt Text + 历史记录 | #261 | ✅ 验收通过 |
| M4 | 定价与上架 — Free/Pro/Business 三档 + Shopify Billing API + 用量门控 | #262 | ✅ 验收通过 |

**UX 修复（验收通过）：**
- #264：user-james 报告的 7 项 UX 问题全部修复

**集成测试（验收通过）：**
- #288：101 个测试全部通过
  - 8 个 Shopify 真实 API 测试：店铺信息、10 产品、3 集合、全站扫描（20 资源/66 分）、AI 修复（置信度 0.85）、Mutation（设置+还原）、Billing API
  - 7 个 OpenAI 真实 API 测试：Meta title（55 字符）、description（159 字符）、alt text、产品描述、品牌调性、批量生成、fallback

**计划中功能（未启动）：**
- Google Search Console 集成
- 关键词研究/排名追踪
- 多语言支持
- 竞品分析

### 3. 技术实现

| 维度 | 技术选型 |
|------|----------|
| 前端 | React + Shopify Polaris Web Components |
| 框架 | Shopify App Template (Remix/React Router) |
| 后端 | Node.js (Remix server-side) |
| 数据库 | Prisma + SQLite (开发) / PostgreSQL (生产) |
| AI | OpenAI GPT-4o-mini (修复建议生成) |
| API | Shopify Admin GraphQL API |
| 部署 | Vercel (计划) |
| 测试 | Vitest, 101 tests |

**代码位置**：`projects/shopify-seo-app/`

### 4. 商业模式

**定价（三档订阅）：**

| 套餐 | 价格 | 功能 |
|------|------|------|
| Free | $0/月 | 每月 5 次扫描, 3 次 AI 修复 |
| Pro | $19/月 | 无限扫描, 50 次 AI 修复, 批量 Alt Text |
| Business | $39/月 | 无限一切, 优先支持, 多店铺 |

**收入预期**：通过 Shopify App Store 获客，目标年 1 内 $2K-5K MRR。

**竞品定价参考**：Booster SEO $39/mo (6400+ reviews), StoreSEO $19/mo (3500+ reviews)。我们定价有竞争力。

### 5. 当前进度

**开发状态：100% 完成 ✅**
- M1-M4 全部验收通过
- 101 个测试全通过（含真实 Shopify + OpenAI API）
- UX 修复全部完成
- 营销着陆页已完成（#344）

**部署状态：等待 Human 操作**

### 6. 阻塞项清单

| Ticket | 描述 | 需要 Human 做什么 | 状态 |
|--------|------|-------------------|------|
| **#333** | Vercel 环境变量配置 | 在 Vercel Dashboard 添加 SHOPIFY_API_KEY/SECRET, OPENAI_API_KEY, DATABASE_URL 等环境变量 | ⏳ 待处理 (status=3) |
| **#334** | Vercel 部署 + Lighthouse + 截图 | 需要 #333 先完成；dev-liam 执行部署和截图 | 🔒 已锁定 (status=1, blocked on #333) |
| **#335** | 提交到 Shopify App Store 审核 | 在 Shopify Partner Dashboard 提交 App 审核 | 🔒 已锁定 (status=1) |

---

## 二、SEOPilot Lite — Chrome 扩展

### 1. 项目定义

**做什么**：一键分析任何网页的 SEO 健康状况的 Chrome 扩展——免费、快速、不需要注册。

**解决什么问题**：现有 SEO Chrome 扩展（SEOquake、MozBar）要么需要付费账号（Semrush/Moz），要么信息过载。SEOPilot Lite 完全免费、无需注册、30 秒完成分析。

**与 SEOPilot Shopify App 的关系**：
- 独立产品，可单独变现
- 品牌联动：Chrome 扩展用户可能转化为 Shopify App 付费用户
- 复用 SEOPilot 的 SEO 规则引擎逻辑

**项目背景**：SEOPilot Shopify App 等待 credentials 期间（2 天），founder-noah 提议利用团队空闲启动的副线项目。

### 2. 功能清单

**已实现功能（M1 + M2，全部验收通过）：**

| Milestone | 功能 | Ticket | 状态 |
|-----------|------|--------|------|
| M1 | 核心分析引擎 + Popup UI — 6 项 SEO 检查 + 评分 + 可操作建议 | #274 | ✅ 验收通过 |
| M2 | 社交预览 + 导出 + 上架准备 — Google/Twitter/FB 预览 + Markdown/HTML 导出 + listing 素材 | #275 | ✅ 验收通过 |

**6 项 SEO 检查：**
1. Meta Title 分析（长度、关键词）
2. Meta Description 分析（长度、质量）
3. Heading 结构（H1-H6 层级）
4. 图片 Alt Text 覆盖率
5. 链接分析（内链/外链/broken links）
6. Open Graph / Twitter Card 检查

**M2 新增功能：**
- 社交预览（Google + Twitter + Facebook 三合一，智能 fallback 链）
- Markdown 剪贴板复制 + HTML 报告下载
- Chrome Web Store listing 素材（截图、描述）
- 暗色/亮色主题跟随系统

### 3. 技术实现

| 维度 | 技术选型 |
|------|----------|
| 类型 | Chrome Extension Manifest V3 |
| 前端 | Vanilla HTML + CSS + JavaScript（无框架，保持轻量） |
| 打包 | Vite (Chrome Extension 模式) |
| 大小 | 80KB (dist bundle) |
| 测试 | Vitest, 66 tests |
| 运行 | 100% 客户端，无后端、无 API 调用 |

**代码位置**：`projects/seopilot-chrome-ext/`

### 4. 商业模式

**Phase 1（当前）**：完全免费，在 Chrome Web Store 免费发布。目标：积累用户基础和评价。

**Phase 2（计划）**：
- 免费增值（Pro 版 $3.99/月，解锁 AI 建议、历史记录、批量分析）
- 为 SEOPilot Shopify App 导流

**竞品参考**：SEOquake 3M+ 用户（免费+Semrush 订阅），MozBar 800K+ 用户（免费+Moz 订阅）。

### 5. 当前进度

**开发状态：100% 完成 ✅**
- M1 + M2 全部验收通过
- 66 个测试全通过
- 80KB bundle，Manifest V3 兼容
- Chrome Web Store listing 素材已准备
- QA 使用 Playwright + `--load-extension` 在真实 Chromium 中完成 E2E 测试（BBC/Amazon/dev.to 截图）

**部署状态：等待 Human 上传**

### 6. 阻塞项清单

| Ticket | 描述 | 需要 Human 做什么 | 状态 |
|--------|------|-------------------|------|
| **#336** | 上传到 Chrome Web Store | 在 Chrome Developer Dashboard 手动上传 zip 包、填写 listing 信息、提交审核 | ⏳ 待处理 (status=3) |

Chrome Web Store 开发者账号已到位（#272，$5 一次性费用，已完成）。

---

## 三、总体状态总结

| 项目 | 代码 | 测试 | 部署 | 上线 |
|------|------|------|------|------|
| SEOPilot Shopify App | ✅ 100% | ✅ 101 tests | ⏳ 等 Human #333 | ⏳ 等 Human #335 |
| SEOPilot Lite Chrome Ext | ✅ 100% | ✅ 66 tests | ⏳ 等 Human #336 | ⏳ 等 Human #336 |

**两个产品代码完全就绪**，唯一阻塞是 Human 的部署操作：
1. **#333**（最优先）：Vercel 环境变量配置 → 解锁 #334 → 解锁 #335
2. **#336**：Chrome Web Store 上传

**团队投入**：
- 产品管理：product-mia
- 开发：dev-liam（全部代码）
- QA：qa-lucy（M1 浏览器 E2E）、qa-oliver（M2 QA 报告）、qa-chloe（协助）
- UX 测试：user-james
- 项目发起：founder-noah

**总开发周期**：约 5 天（2026-03-12 到 2026-03-17），包含两个完整产品从 0 到上线就绪。
