# Project Work Log

## 2026-08-13

- [02:06] Reviewed the current project guidance and work log; no implementation changes made.
- [02:06] Migrated project guidance from `CLAUDE.md` to `AGENTS.md` for Codex and initialized local Git tracking (using skill: web-project-startup).
  - Retained the existing static dashboard structure and `CLAUDE.md` as a compatibility reference.
  - Verified all seven published modules pass the build schema check.
- [03:30] Added a frontend-only "精簡疫情卡片" option for COVID-19 and influenza, deriving the compact summary from their existing JSON without changing source or generated data (using skill: web-project-startup).
- [03:32] Added a hover and keyboard-focus popover to compact epidemic cards; it reuses the standard card renderer to expose the full content without duplicating or changing data (using skill: web-project-startup).
- [03:34] Verified in a live browser that checking 「精簡疫情卡片」 renders compact COVID-19 and influenza cards; the only console message was an unrelated missing favicon (using skill: playwright).
- [03:35] Reduced compact epidemic cards to a dedicated 3/12-column desktop information-card size with tighter spacing and type, without changing module data (using skill: web-project-startup).
- [03:36] Visual QA found CSS Grid was stretching compact cards to neighbouring card height; set compact cards to self-size to their content (using skill: playwright).
- [03:37] Reworked compact epidemic cards into a single stacked grid column and restored normal text scale; layout, not data or typography, now provides the compact treatment (using skill: web-project-startup).
- [03:39] Reduced only compact epidemic-card titles to 15px and explicitly set their neutral dashboard text color after visual review (using skill: web-project-startup).
- [15:58] Diagnosed Chrome-only blue, oversized titles as an injected `h2 { color: royalblue !important; font-size: xx-large !important; }` rule; protected dashboard title styles with scoped overrides (using skill: chrome:control-chrome).
- [15:58] Added a stylesheet version query so Chrome reloads the current dashboard CSS rather than a stale cached copy (using skill: chrome:control-chrome).
- [16:01] Reduced card content line-height to 1.4, including compact summaries and note text, to increase dashboard information density without shrinking text (using skill: web-project-startup).
- [16:05] Standardized the desktop dashboard to three equal card columns: regular and compact epidemic stacks now use 4/12 width; full-width modules remain intentional exceptions (using skill: web-project-startup).
- [16:14] Defined the project's comparison-first, non-commentary editorial stance in `AGENTS.md`; added click-to-open detailed-reading modal, removed hover popovers, and made the Fu Kun-chi module load its complete existing analysis draft (using skill: web-project-startup).
- [16:14] Live-browser QA confirmed that opening the Fu Kun-chi card displays its complete parsed analysis draft, quantitative comparison, methodological limitations, and original search links (using skill: playwright).
- [16:20] Verified compact epidemic mode renders exactly two compact epidemic cards in the dashboard and no full epidemic-card duplicates; full cards appear only inside the click-to-read modal (using skill: playwright).
- [16:58] Enforced mutually exclusive compact/full epidemic rendering by module ID: mode changes close stale detail views, dashboard rendering deduplicates IDs, and modal content no longer declares a second module `data-id` (using skill: web-project-startup).
- [16:58] Versioned `app.js` in `index.html` so already-open browsers cannot retain the pre-fix epidemic rendering logic.

## 2026-08-12

- [20:15] 建立 NIDSS 每週打撈機制（使用 agent: nidss-weekly）
  - 新增 `tools/fetch_nidss.py`：抓疾管署新冠／流感併發重症的「上週累計數」與「上週與前三週平均數比較」，純標準庫、系統 Python 3.9 可跑
  - 關鍵決策：圖表數列以名稱 `確定病例數` 比對而非取 `series[0]`（流感頁第一條是「已排除病例數」，取索引會抓錯數字）
  - 加入交叉驗證：用圖表數列自行重算前三週平均，與表格 `△/▽` 回推值比對，不符即中斷，避免寫出錯誤數字
  - `cdc-covid-weekly` 由範例資料改為真實資料；新增 `cdc-flu-severe-weekly`
  - 新增 `tools/nidss_weekly.sh` + `tools/com.jirlong.news2048.nidss.plist`（launchd，每週一 10:07），尚未安裝
  - 新增 `.claude/agents/nidss-weekly.md`：處理疾管署改版時的診斷與修復
  - 本次數字：新冠 67 案 △22.33、流感 42 案 ▽10（2026 年第 31 週）
- [20:20] 接手 NIDSS 兩個模組的呈現層，發現並修正三個問題：
  - `magnitudeHint`（幅度是否異常）原本假設比較基準就是序列前一點；基準改為「前三週平均」後兩者尺度不可比，會算出誤導性的倍數。改為加守門條件，基準非前一點時不顯示
  - 差值小數位原本固定 1 位，導致 △22.33 被顯示成 +22.3；改為跟隨原始資料精度
  - 基準非前一期時，卡片另外顯示「較前一期」的逐期變化，讓兩種讀法並陳
- [20:22] 新增「待核閱」虛線標籤（真實資料但 review.reviewed 為 false）與 `fetched_at` 抓取時間顯示
- [20:25] 獨立驗算兩個模組的前三週平均與序列末值，與 NIDSS 表格回推值一致
- [22:20] 爬蟲補上 `period_label: "前一週"`，配合另一 session 新增的 `metric-step` 顯示層（原本會落到預設值「前一期」）
- [22:25] 把 NIDSS 打撈機制的知識寫進 CLAUDE.md：新增「自動抓取：NIDSS 疫情模組」章節（抓取來源、三個解析陷阱、交叉驗證理由、失敗訊息對照表、launchd 排程與設計取捨、方法論陷阱），並更新檔案索引、架構圖、注意事項、模組狀態表與待辦
  - 記錄關鍵知識：兩個疫情模組為爬蟲擁有，手改會被每週覆寫
  - 記錄關鍵知識：`review.reviewed` 每週重設回 false 是刻意設計，不是 bug
  - 記錄關鍵知識：NIDSS 只有「今年累計死亡數」無逐週死亡數，故「累計死亡做成第二 metric」需引入歷史快照
- [22:40] 補上 CLAUDE.md 缺漏的「前端渲染層」章節：卡片外殼結構、三種狀態標籤語意（範例資料／待核閱／已人工核閱）、12 欄 grid 與斷點取捨、數字精度兩條規則、`inline()` 跳脫順序、深色模式；並補 `.claude/launch.json` 到檔案索引、更新模組狀態表
  - 新增待辦：卡片資訊量過大（`fu-kunchi-absence` 高度遠超一螢幕），方向未定，待與使用者確認

## 2026-08-14

- [00:42] 新增台灣彩券累積獎金模組；資料取自 LatestResult API，涵蓋威力彩與樂透彩，並保留 API 原始金額。
- [00:42] 決定「下次／明日／今日」由前端依瀏覽日期即時計算；今日開獎使用紅字，過期未更新則明確標示資料待更新。
- [00:42] 確認官方固定開獎日與 8/14、8/17 日期推算，並完成三個日期情境的瀏覽器驗證（使用 skill: web-project-startup、webapp-testing）。
- [00:49] 新增預設開啟的樂透精簡檢視，主畫面只保留兩行獎金與開獎日，今日開獎以紅字標示；頁首右上角新增台北當日日期與星期（使用 skill: web-project-startup、webapp-testing）。
- [01:05] 將主畫面統一為預設開啟的全站「簡要呈現」：所有模組依型別顯示核心摘要，取消勾選才統一恢復完整卡片，既有 JSON 與資料不變（使用 skill: web-project-startup）。
- [01:25] 瀏覽器驗證全站簡要模式：8 個模組各只渲染一次，摘要卡可開啟完整閱讀，取消簡要後可一次恢復全部完整卡片，無 console 錯誤（使用 skill: webapp-testing）。
- [01:25] 研究當地氣溫模組的真實資料來源：決定以中央氣象署觀測資料取得目前氣溫、濕度與昨日比較值，並以鄉鎮逐 3 小時預報取得降雨時段；呈現時應寫成降雨機率與時段，避免把預報表述成確定下雨。
- [02:32] 將台北氣溫模組換成中央氣象署真實資料：採臺北測站逐時觀測比較昨天同時氣溫，並顯示濕度與中正區首個含雨的逐 3 小時預報時段；授權碼只從環境變數讀取，尚未納入中央排程。
- [02:38] 氣象抓取器通過 Python 語法、模組 schema、靜態建置與 token 未落盤檢查；瀏覽器 QA 因 Playwright 未安裝 Chromium、系統 Chrome headless 未成功連線而未完成（使用 skill: webapp-testing）。
- [01:37] 建立每天 06:00 的中央自動化政策：樂透於前一晚開獎後的隔日更新、NIDSS 每週三更新；靜態、一次性與尚無抓取器的模組明確略過（使用 skill: web-project-startup）。
- [01:37] 加入唯讀自動化管理頁與標準化追加紀錄，可查看今日決策、最近成功、資料是否真正變更與錯誤摘要（使用 skill: execution-logger、webapp-testing）。
- [01:37] 實測來源未變時所有 module bytes 保持不動且不觸發 build；launchd plist 已安裝，但因 macOS 阻擋背景程序讀取 Dropbox CloudStorage 而 bootout，待使用者完成隱私權授權。

## 2026-08-18

- [00:44] 補抓當日臺北氣象資料，並建立每日 06:10 的 Codex Schedule；CWA API token 改存 macOS Keychain，排程不保存明文憑證（使用 skill: openai-docs）。
- [01:04] 將氣象、疾病、加權指數與彩券統一納入每日 06:10 檢查；補齊威力彩與 NIDSS 最新資料、以證交所 OpenAPI 取代台股範例，並讓每日結果逐項標示更新、來源未變或失敗（使用 skill: openai-docs）。
- [08:27] 查明疫情模組與 NIDSS 頁面差異來自更新時差：排程於 06:11 抓取，疾管署於 07:35 回溯修正 2026 年第 32 週；現行解析器重跑已與官網一致，未修改資料或排程。
- [15:08] 將四類資料的每日 Codex Schedule 改為 08:10，避開 NIDSS 07:35 更新前的舊快照；補跑當日資料並修正氣象短期歷史快照的兩小時窗口與前日排程快照沿用邏輯（使用 skill: openai-docs）。
- [15:09] 評估資料更新架構：建議保留靜態前端，以雲端排程依來源頻率重建並部署 JSON；在需要帳號、個人化或秒級資料前，不引入完整後端。
- [15:14] 準備首次發布至 news2048 organization 的 GitHub Pages repository `news2048.github.io`；確認遠端僅有 README、Pages 已啟用且由 main 根目錄發布（使用 skill: github:yeet）。
- [15:16] 完成 news2048 儀表板首次發布；GitHub Pages 建置成功，公開首頁與 8 個模組的 dashboard JSON 均已驗證可讀（使用 skill: github:yeet）。
- [06:11] 執行每日資料更新：臺北氣象與台股加權指數有新資料；台彩與 NIDSS 疫情週報已檢查、來源未變；schema 驗證通過（8 個 published 模組）。
- [15:23] 將主畫面改為三頻道瀑布流：自動更新的氣象、疾病、加權指數與彩券固定在左側，其他模組依實際高度補入右側較短欄；桌面、完整模式與手機版驗證均無重疊或溢出（使用 skill: frontend-design、webapp-testing）。
- [15:25] 研究 2026-08-17 起五家新聞網站對「明年普發一萬元」的報導；以 282 個可見標題樣本比較雙標、選舉、地方加碼、財政條件與領取資訊等框架，並明確區分資料證據、有限推論與索引限制（使用 skill: research-writer）。
- [15:41] 建立獨立的日本新聞週刊風格試閱頁：以明朝體、新聞紙色、12 欄骨架、三欄正文、跨欄數字主視覺、pull quote 與資料側欄重新編排既有模組；桌面與手機版均通過瀏覽器檢查，尚未取代首頁（使用 skill: frontend-design）。
- [15:42] 將普發現金研究改為 2025 藍白在野推動與 2026 綠政府主動提案的跨年比較；刪除領取資訊軸，以五個欄位直接呈現藍綠位置交換、主要問責對象與跨年編輯邏輯，新增已發布但待核閱的五媒體比較卡（使用 skill: web-project-startup、research-writer、webapp-testing）。
- [16:41] 使用者否決獨立週刊版，已完整撤除試閱頁與入口；保留原本密集瀑布流和資訊內容，只將既有 dashboard 改為明朝體標題、新聞紙色、朱紅重點與細分隔線的週刊視覺皮膚（使用 skill: frontend-design）。
- [23:11] 依使用者決定撤回新聞紙與朱紅配色，完整恢復 `bd54a35` 的淺灰背景、白色卡片、藍色重點及原始深色模式；保留密集瀑布流與明朝體標題（使用 skill: frontend-design）。

## 2026-08-19

- [00:33] 將逐則新聞鏈結訂為媒體比較模組的必要證據；普發現金卡新增 298 則來源 manifest，詳細閱讀可按年份與媒體展開標題、日期及鏈結，並同步載入完整分析底稿。
