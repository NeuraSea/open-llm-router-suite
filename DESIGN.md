# Design System — Enterprise Router

## Product Context
- **What this is:** 企业内部 LLM 网关控制台，统一承接飞书登录、开发者 CLI 接入、模型凭证池和用量治理
- **Who it's for:** 公司内部开发者（日常使用）+ 管理员（凭证/配额/用量管理）
- **Space/industry:** 企业 AI 基础设施
- **Project type:** 内部 web app / admin dashboard + developer portal

## Aesthetic Direction
- **Direction:** Linear-Sharp + GitHub Blue — 纯白底、无阴影、清晰边框、蓝色 Accent
- **Decoration level:** minimal — 靠间距和排版层次，不靠装饰
- **Mood:** 精准、干净、专业。用户打开感到清爽，信息密度舒适。
- **References:** Linear（纯白、无装饰、sharp edges）、GitHub（蓝色 Accent、结构感强）
- **Core principle:** 不要超越"常见 UI 舒适区"——追求执行质量，而非视觉差异化。

## Typography
- **UI / Body:** Geist — 现代、中性、专业，不像 Inter 那么泛滥
- **Chinese:** Noto Sans SC — 中文渲染补全
- **Data / Mono:** JetBrains Mono — token 数、JTI、时间戳、命令行
- **Loading:** Google Fonts CDN
- **Scale:**
  - xs: 11px · sm: 12px · base: 13px · md: 14px · lg: 16px · xl: 20px · 2xl: 28px

## Color — Light Theme
- **Background:** `#FFFFFF` — 纯白
- **Surface / Card:** `#FFFFFF`
- **Primary text:** `#0A0A0A`
- **Secondary text:** `#737373`
- **Muted text:** `#A3A3A3`
- **Border:** `#E5E5E5`
- **Accent (CTA / active nav):** `#000000` — 纯黑主按钮
- **Accent color (links / badges / status):** `#0969DA` GitHub blue
- **Success:** `#16A34A` · **Warning:** `#D97706` · **Error:** `#DC2626`

## Color — Dark Theme
- **Background:** `#0A0A0A` — 近黑
- **Surface / Card:** `#161616`
- **Primary text:** `#FAFAFA`
- **Secondary text:** `#737373`
- **Muted text:** `#525252`
- **Border:** `#222222`
- **Accent (CTA):** `#FFFFFF` — 深色主题下主按钮用白色
- **Accent color:** `#388BFD` GitHub blue（深色背景更亮一点）

## Spacing
- **Base unit:** 4px
- **Density:** comfortable
- **Content padding:** 24px 水平 / 20px 垂直
- **Card padding:** 16px

## Layout
- **Structure:** 左侧固定侧边栏（280px）+ 右侧内容区，两者跟随主题统一（不做深色/浅色分割）
- **Max width:** 1440px
- **Border radius:** 6px 统一（Linear 风格，sharp but not square）

## Motion
- **Approach:** minimal-functional
- **Duration:** 150ms short / 250ms medium · ease-out for enter, ease-in for exit

## Theme Toggle
- 全白 / 全黑两档，无混合（侧边栏跟随内容区主题）
- 用户选择持久化到 localStorage，初始跟随系统偏好
- 切换按钮位于侧边栏底部

## Anti-Patterns
- 渐变背景（已删除）
- 刻意差异化的"工业风"或"极简主义宣言"
- 极端圆角（>24px）或极端直角（<4px）
- 过度使用等宽字体（只在数据字段用）

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-27 | 初始设计系统建立 | /design-consultation |
| 2026-03-27 | 方向调整：从"冷精密"→"标准精致 SaaS" | 用户明确：对齐 Manus/ChatGPT 质量，不超出常见 UI 舒适区 |
| 2026-03-27 | 全黑/全白主题切换 | 侧边栏跟随主题，不做深色侧边栏+浅色内容的混合 |
| 2026-03-28 | 方向调整：Manus-Warm → Linear-Sharp + GitHub Blue | 用户选择 B 方案：纯白底、GitHub 蓝 accent、6px 圆角 |
