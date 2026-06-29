# Raw Internet Research Notes: AI Travel Itinerary Tool Market in China

**Date:** 2026-06-28
**Focus:** Competitors, Market Trends, Target Users, Commercialization, Technical & Compliance Risks

---

## 1. Competitors (竞品信息)
*   **圆周旅迹 (Pi Travel):**
    *   *Type:* Independent utility App/Mini-program.
    *   *Features:* Copy-paste URL from Xiaohongshu/WeChat to generate itinerary, route optimization, real-time collaboration with friends, map-based adjustment.
    *   *Style:* Clean, minimalist, ad-free.
    *   *Business Model:* Tool-centric, mostly free to accumulate user base.
*   **携程问道 (Ctrip Genie) / 同程“程心AI” / 飞猪“问一问”:**
    *   *Type:* In-app OTA AI assistants.
    *   *Features:* Flight/hotel booking integration, official curated lists (口碑榜/特价榜), natural language travel search and booking.
    *   *Business Model:* Conversion of recommendations into direct transactions (OTA commission/sales).
*   **Generic LLMs (豆包, 元宝, ChatGPT, DeepSeek):**
    *   *Type:* Multi-purpose LLM bots.
    *   *Features:* Chatbot-style planning, lacks real-time map API, booking link, or offline store verification.

---

## 2. Market Size & Trends (市场规模与趋势)
*   **Global/National AI Travel Market:** Expected global AI travel market size of $18.39 billion by 2035 with a CAGR of 21%+. Domestic intelligent travel is growing rapidly.
*   **Xiaohongshu (小红书) Ecosystem:**
    *   Monthly travel search volume: 1.6 billion.
    *   Monthly active users interested in travel: 100M+.
    *   Keywords: "Citywalk", "反向旅游" (reverse travel), "松弛感" (relaxation), "听劝" (listening to advice).
*   **Youth consumption trends:** "Copying homework" (抄作业), "spontaneous travel" (说走就走), "lazy packets" (懒人包) are highly popular.

---

## 3. Target User Analysis (目标用户分析)
*   **Demographics:** Young people aged 20-35.
*   **Pain points:** Decision fatigue (planning takes 30+ days traditionally), information fragmentation and untrustworthiness ("照骗" or sponsored posts), rigid itineraries, difficulty in real-time adjustment.
*   **AI Acceptance:** ~90% awareness, ~80% penetration. Used as planners, budget helpers. Trust is still limited due to "AI hallucination" (e.g., closed shops, outdated prices).
*   **Willingness to Pay:** Highly rational. Will pay for time saved, direct booking discounts, high personalization, and API-integrated premium features. Hate subscription usage caps and privacy leaks.

---

## 4. Commercialization (商业化)
*   **Monetization models:**
    *   Premium Subscription / Pay-per-use (Credits).
    *   OTA Affiliate links (commission on hotel/ticket bookings).
    *   Referrals to local custom tour agencies (B2B2C).
    *   Contextual ads.
*   **Pricing strategy:** 9-19 RMB/month or 49-99 RMB/year for subscriptions; 1-2 RMB per complex plan.
*   **Cold-start strategy:** Open-source developer credibility, interactive social media campaign (e.g. "听劝 AI travel plan" on Xiaohongshu), closed beta invites.

---

## 5. Technical & Compliance Risks (技术与合规风险)
*   **AutoNavi (高德) API Limits:**
    *   Personal developer: ~5,000 requests/day, restricted to test/study.
    *   Commercial enterprise: Required commercial license (starting ~50,000 RMB/year) and per-use tiered pricing (e.g., 30 RMB/10,000 requests for routing).
*   **AIGC Content Censorship:** State regulations require content filtering. Need WeChat's content security APIs or custom moderation filters to check user inputs and DeepSeek outputs.
*   **Publishing Obstacles:**
    *   Need an enterprise entity (personal accounts can't publish AIGC mini-programs).
    *   Must select "深度合成" (Deep Synthesis) category.
    *   Requires "互联网信息服务算法备案" (Algorithm Registration) and "安全评估" (Security Assessment) under CAC regulations.
