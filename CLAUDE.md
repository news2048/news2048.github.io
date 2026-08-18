# news2048

以「變化量」為核心的**靜態**新聞儀表板。不做即時報導，只回答：今天跟昨天（或這週跟上週）比，哪些數字動了、動了多少、幅度算不算大。

## 專案概述

- **完全靜態**：沒有後端、沒有資料庫、沒有執行期查詢。所有資料在 build 時就固定下來。
- **模組化**：每張卡片是一個獨立模組，資料放在 `modules/<id>/module.json`。
- **人工掛載**：議題型模組（媒體比較）由人工檢視內容後才改成 `published`。
- **新增模組不需寫任何 JS/CSS**，只要放一個符合 schema 的 JSON。

## 開發指令

```bash
python3 tools/build.py                          # 合併模組 → data/dashboard.json
python3 tools/build.py --check                  # 只驗證 schema，不寫檔
python3 tools/new_module.py <type> <id> "<標題>" # 產生模組骨架（預設 status=draft）
python3 -m http.server 8000                     # 本機預覽 http://localhost:8000

python3 tools/fetch_nidss.py                    # 抓 NIDSS 疫情數字 + 自動重新建置
python3 tools/fetch_nidss.py --dry-run          # 只抓取並印出，不寫檔（先確認來源正常）
python3 tools/fetch_nidss.py --no-build         # 寫模組但不跑 build.py
bash tools/nidss_weekly.sh                      # 模擬 launchd 排程跑一次（含寫 log）
```

> 直接用瀏覽器開 `index.html`（file://）會失敗，因為 `fetch()` 讀不到本機 JSON。一定要起 HTTP server。

## 主要檔案索引

| 路徑 | 用途 |
|------|------|
| `index.html` | 頁面外殼：標頭、篩選列、grid 容器 |
| `assets/js/app.js` | **核心**。renderer 註冊表、配色語意查表、卡片外殼、篩選邏輯 |
| `assets/css/dashboard.css` | 版面與配色變數（`--up-red` / `--down-green` / `--hot` / `--cold`…） |
| `tools/build.py` | 收集 + 驗證 + 排序模組，輸出 `data/dashboard.json` |
| `tools/new_module.py` | 依型別產生模組骨架 |
| `tools/fetch_nidss.py` | **NIDSS 疫情爬蟲**。抓取 + 解析 + 交叉驗證 + 直接覆寫兩個疫情模組 |
| `tools/nidss_weekly.sh` | launchd 進入點：固定專案路徑、指定 Python、把輸出附加到 log |
| `tools/com.jirlong.news2048.nidss.plist` | launchd 排程定義（每週一 10:07）。檔案在 repo 裡，安裝要另外 copy 到 `~/Library/LaunchAgents/` |
| `.claude/agents/nidss-weekly.md` | `nidss-weekly` 子代理：跑每週打撈，NIDSS 改版時負責診斷修復 |
| `modules/<id>/module.json` | **唯一要編輯的資料來源**（但疫情兩個模組由爬蟲擁有，見下） |
| `data/dashboard.json` | 建置產物，不要手改 |
| `analysis/*.md` | 議題模組的完整分析底稿。卡片只放濃縮版，方法論與逐篇清單放這裡 |
| `.claude/launch.json` | 本機預覽伺服器定義（`python3 -m http.server 8000`），給 Claude Code 的 preview 用 |
| `LOG.md` | 工作日誌，**只用附加**，最新紀錄在檔尾 |
| `~/Library/Logs/news2048-nidss.log` | 排程執行紀錄（不在 repo 內）。排程沒更新時第一個要看的地方 |

## 架構

```
launchd（每週一 10:07）
   └─> tools/nidss_weekly.sh ──> tools/fetch_nidss.py ──┐
                                  （抓 NIDSS + 交叉驗證）│ 覆寫
                                                        ▼
modules/*/module.json ──[tools/build.py]──> data/dashboard.json ──[fetch]──> app.js
       ▲                                                                      │
       └── 人工編輯（議題型模組）             module.type ─┬─> renderers.delta
                                                         ├─> renderers.compare
                                                         ├─> renderers.list
                                                         └─> renderers.note
```

資料進入模組有兩條路，**不要混用**：人工編輯的議題型模組，和爬蟲擁有的自動模組。

### 模組 schema（共通欄位）

| 欄位 | 必填 | 說明 |
|------|:--:|------|
| `id` | ✓ | 必須與資料夾名稱相同（build 會檢查） |
| `title` | ✓ | 卡片標題 |
| `type` | ✓ | `delta` / `compare` / `list` / `note` |
| `updated` | ✓ | `YYYY-MM-DD` |
| `status` | | `published`（預設）/ `draft` / `archived`，只有 published 會進 build |
| `subtitle` | | 標題旁的小字 |
| `tags` | | 篩選列的標籤來源 |
| `size` | | `s`=4欄 / `m`=6欄 / `l`=12欄（12 欄 grid） |
| `pinned` / `order` | | 排序：置頂 → order 小 → 日期新 |
| `sample` | | `true` 時顯示「範例資料」紅色標籤 |
| `review` | | `{reviewed, by, at}`。`reviewed:true` → 綠色「已人工核閱」；真實資料但未核閱 → 虛線「待核閱」 |
| `fetched_at` | | 爬蟲寫入的抓取時間，顯示在卡片頁尾（與 `updated` 分開：一個是資料期別，一個是抓取時點） |
| `source` | | `{name, url}`，顯示在卡片頁尾 |
| `note` | | 方法論註記／資料陷阱提醒 |
| `data` | ✓ | 型別專屬內容，見下 |

### type: `delta`（指標對比）

```json
"data": {
  "unit": "°C",
  "scheme": "thermal",          // market-tw | market-us | thermal | semantic | plain
  "polarity": "neutral",        // semantic 專用：higher-is-bad | higher-is-good
  "metrics": [{
    "label": "日最高溫",
    "current": 35.2, "previous": 32.6,
    "current_label": "今天", "previous_label": "昨天",
    "mode": "absolute",         // absolute=主顯絕對差 | percent=主顯百分比
    "period_label": "前一週",    // 選填；「較○○」那行的字樣，預設「前一期」
    "series": [31.4, 32.0, ...] // 選填；提供則畫 sparkline 並計算「幅度是否異常」
  }]
}
```

**比較基準與 `series` 的關係（重要）**

前端會檢查 `previous` 是不是等於 `series[n-2]`：

- **相等**（例如「昨天」）→ 顯示「幅度是近期平均波動的 N 倍」。
- **不相等**（例如「前三週平均」）→ 不顯示該提示，因為 `series` 的逐期落差是「一期對一期」的尺度，拿來跟「對移動平均的偏離」比是不同量綱；改為另外補一行「較前一期 X ▲ +Y（+Z%）」，讓兩種讀法並陳。

這個區別在趨勢期特別重要：移動平均會落後趨勢，所以上升期用「對前三週平均」會系統性放大變化（例：新冠第 31 週對前三週平均 +50.0%，但對前一週只有 +15.5%）。兩個數字都對，但適合放進標題的通常是後者。

**配色語意由模組宣告，前端不預設任何文化慣例**：

| scheme | 上升 | 下降 | 用途 |
|--------|------|------|------|
| `market-tw` | 紅 | 綠 | 台股（紅漲綠跌） |
| `market-us` | 綠 | 紅 | 美股 |
| `thermal` | 暖橘 | 冷藍 | 氣溫 |
| `semantic` | 依 `polarity` | 依 `polarity` | 疫情、失業率等有好壞之分的指標 |
| `plain` | 灰 | 灰 | 中性 |

`series` 還會用來算「今天的變化 ÷ 近期平均逐日變化」。比值 ≥1.5 或 ≤0.5 時，卡片會多一行提示（例如「幅度是近期平均波動的 3.6 倍」）——這是回答「漲多了還是跌多了」的第二層資訊。

### type: `compare`（媒體對照表）

`data.axes` 定義比較維度（列），`data.subjects` 是各家媒體（欄），`subjects[].fields[axis.key]` 填內容。`tone` 可填 `neutral` / `supportive` / `critical` / `mixed`，顯示為色塊。`takeaway` 是你的結論。

### type: `list`（並列清單）

`data.columns[]`，每欄一個媒體，`items[].text` + `items[].meta`（分類標籤）。適合 YouTube 選題比較。

### type: `note`（自由文字）

`data.body[]` 每個元素一段。支援 `**粗體**`、`` `code` ``、`[文字](網址)`。

## 前端渲染層（`app.js` / `dashboard.css`）

**新增模組不需要碰這兩個檔案。** 只有在新增 renderer 型別、或改動卡片外殼／配色語意時才要動。

### 卡片外殼

所有型別共用同一個外殼，由 `card(mod)` 組出，renderer 只負責 `card-body` 裡面的內容：

```
card-head   標題 + subtitle ┐
            狀態標籤 + tags + updated 日期
card-body   ← renderers[mod.type](mod.data) 的回傳值
card-foot   note（左） | fetched_at + source（右）
```

### 三種狀態標籤（人工掛載工作流的核心）

卡片右上角的標籤是「這張卡能不能信」的唯一視覺訊號，由 `sample` 與 `review.reviewed` 兩個欄位決定：

| 標籤 | 條件 | 意思 |
|------|------|------|
| 紅色實線「範例資料」 | `sample: true` | 內容是佔位或編造的，**不可對外** |
| 虛線「待核閱」 | `sample` 非 true 且 `review.reviewed: false` | 真實資料，但還沒有人親眼看過 |
| 綠色「已人工核閱」 | `review.reviewed: true` | 有人看過並背書，`title` 屬性會顯示核閱者與日期 |

篩選列的「隱藏範例資料」勾選框過濾的是 `sample`，用途是避免把示範內容誤當真實資料發布。三種狀態互斥，沒有第四種——真實但未核閱的東西一定會被標出來，這是刻意的。

### 版面

12 欄 grid，`grid-auto-flow: row dense`（讓小卡回填空洞）。`size` 對應：`s`=4 欄、`m`=6 欄、`l`=12 欄。

斷點只有兩個：≤1000px 時 `s`/`m` 都變 6 欄；≤640px 時全部滿版。刻意不做更細的斷點——卡片內容高度差異大，多做斷點只會讓 dense 排列更難預測。

### 數字格式的兩條規則

1. **小數位跟著原始資料精度走**（`decimalsOf()`），不寫死。`△22.33` 會顯示成 `+22.33` 而不是 `+22.3`。
2. **逐期變化（`metric-step`）的精度另外算**，取 `current` 與 `series[n-2]` 的精度，不被基準值（如 `44.67` 這種移動平均）的小數位污染，否則整數的案例數會變成 `+9.00`。

### 安全性

`inline()` **先跳脫 HTML，再套用** `**粗體**` / `` `code` `` / `[文字](網址)` 標記。順序不能反——反過來就等於開放 HTML 注入。因此 `module.json` 裡可以安心放任何抓來的文字（媒體標題、網友留言）。除此之外所有文字都走 `textContent`，只有 `inline()` 的產物用 `innerHTML`。

### 深色模式

`prefers-color-scheme` 只覆寫 `:root` 的顏色變數，不改任何版面規則。新增顏色時務必在兩個區塊都定義，否則深色模式會拿到淺色值。

## 自動抓取：NIDSS 疫情模組

`cdc-covid-weekly` 與 `cdc-flu-severe-weekly` 兩個模組是**機器擁有的**。

> ⚠️ **不要手改這兩個 `module.json`。** `tools/fetch_nidss.py` 每次執行都會整檔覆寫，手動編輯會在下次排程時無聲消失。要改呈現方式就改爬蟲的 `build_module()`，要改語意就改 `app.js`。

### 抓什麼

| 模組 | 疾病 | 來源頁 |
|------|------|--------|
| `cdc-covid-weekly` | 新冠併發重症 | `https://nidss.cdc.gov.tw/nndss/Disease?id=19SC` |
| `cdc-flu-severe-weekly` | 流感併發重症 | `https://nidss.cdc.gov.tw/nndss/disease?id=487a` |

兩個數字都在頁面下方「**統計表-依發病日**」那張表：

- `2026年31週 (上週累計數)` → `current`
- `上週與前三週平均數比較 (病例數)` → `△`／`▽` 差值，用來**回推** `previous`（前三週平均 = current − delta）

呈現成模組的 `subtitle`：`上週病例共 67 案，相較於前三週平均數 △22.33`

疾管署用三角形而非正負號：**`△` 是比前三週平均多，`▽` 是少**。`parse_delta()` 只認 `△▲▽▼`，遇到沒有方向符號的非零值會直接中斷，不會猜。

### 三個解析陷阱（踩過，別再踩）

1. **絕對不要用 `series[0]` 取圖表數列。** COVID 頁只有一條「確定病例數」，但流感頁有三條，順序是「已排除病例數」→「檢驗中病例數」→「確定病例數」。照索引取值，流感第 31 週會拿到 15（錯）而不是 42（對）。腳本以常數 `SERIES_NAME = "確定病例數"` 按名稱比對。

2. **sparkline 的 `series` 刻意收在「上週」，不含本週。** 本週還沒過完（例：第 32 週當時只有 13 案），畫進趨勢線會出現假的斷崖，讀者會誤判成疫情驟降。切片長度是 `SPARK_WEEKS = 12`。

3. **圖表 JSON 要用括號配對取出，不要用正規表達式硬切。** 頁面以 `hcJson.push({...})` 內嵌 Highcharts 設定，`data` 陣列裡有上百個逗號，正規表達式會切在錯誤的位置。

### 交叉驗證：為什麼寧可中斷也不寫錯

`△22.33` 本身無法驗證，但同一頁的圖表另外提供每週數列。腳本因此用**兩個獨立來源互相見證**：

- 圖表第 31 週的值必須等於表格的「上週累計數」
- 用圖表第 28–30 週自行重算平均（`(32+44+58)/3 = 44.67`），必須與 `△` 回推值相差 ≤0.05

這支腳本會無人監督地每週覆寫儀表板，**靜靜寫入錯誤數字比明顯壞掉危險得多**——壞掉你會發現，錯誤數字不會。所以任何一項驗證不過就丟 `ScrapeError` 中斷該來源，不寫檔。兩個來源獨立處理，一個壞掉另一個仍會更新。

### 失敗訊息對照

| 錯誤訊息 | 意思 | 怎麼修 |
|---|---|---|
| `找不到『統計表-依發病日』區塊` | 版面大改 | `curl -s "<url>" > /tmp/nidss.html` 找新的表格標題，改 `parse_table()` 的定位字串 |
| `圖表找不到『確定病例數』數列` | 疾管署改了數列名稱 | 訊息會列出現有名稱，挑對的改 `SERIES_NAME`。**不要改成取索引** |
| `表格上週數 X 與圖表 Y 的 Z 不一致` | 欄位語意變了，或抓到別張表 | 讀原始 HTML 確認「上週累計數」還是不是同一件事 |
| `前三週平均對不上` | 表格 `△` 與圖表數列不同步 | 可能是回溯校正未同步，也可能語意變了。**不要放寬容忍值**，先判斷是哪一種 |
| `缺少 △/▽ 方向` | 碰到「持平」或改用 `+/-` | 看清楚實際字元再擴充 `parse_delta()` |

### 排程

`tools/com.jirlong.news2048.nidss.plist` 在 repo 裡，但**安裝是一次性的手動動作**：

```bash
cp tools/com.jirlong.news2048.nidss.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jirlong.news2048.nidss.plist
launchctl kickstart -p gui/$(id -u)/com.jirlong.news2048.nidss   # 立刻試跑
launchctl bootout   gui/$(id -u)/com.jirlong.news2048.nidss      # 移除
```

幾個刻意的選擇：

- **時間是 10:07 不是 10:00。** 整點是所有排程的塞車時段，錯開幾分鐘對這個任務毫無影響。改星期就改 plist 的 `Weekday`（1 = 週一）。
- **用 `/usr/bin/python3`（系統內建，3.9.6）而非 conda／homebrew。** 腳本只用標準庫且已在 3.9 驗證通過，這樣排程不會因為 conda 環境變動或 PATH 差異而壞掉。
- **需要 shell 包裝層**，因為 launchd 不繼承 shell 環境、沒有工作目錄概念，而專案路徑含空白（`CloudStorage/Dropbox`）。
- **Mac 睡眠時 launchd 會在喚醒後補跑**——寧可晚幾小時，也不要整週漏掉。
- 專案在 Dropbox CloudStorage 下。若設為「僅線上」而檔案未下載，排程當下可能讀不到腳本，建議把資料夾設為「永遠保留在此裝置」。

### 方法論陷阱（要寫進卡片 `note`）

- **週一抓到的是最「生」的數字。** NIDSS 依發病日統計且會回溯校正，週一時「上週」才剛在前一天結束，是被低估最嚴重的時刻。改成週二或週三數字會穩定得多。
- **流感的「檢驗中病例數」會讓方向翻盤。** 2026 第 31 週已確診 42 例、但另有 **24 例檢驗中**，相對比例很高。驗完若多數陽性，42 會被上修到超過前三週平均 52，`▽10`（下降）就變成上升。做流感的判讀一定要看這條數列。
- **NIDSS 只給「今年累計死亡數」，沒有逐週死亡數。** 所以「把累計死亡做成第二個 metric」不能直接做——需要自己保存每週快照再做差分，等於要引入歷史狀態檔。這是那項待辦真正的成本。

### `review.reviewed` 每週會被重設回 `false`——這是刻意的

爬蟲每次覆寫都寫入 `review: {reviewed: false}`，卡片因此顯示虛線「待核閱」。**這不是 bug，不要「修」掉它。** 每週是一批新數字，上週的人工核閱不能背書這週的內容；讓它自動退回未核閱狀態，才能逼出「有人真的看過這週數字」這件事。

代價是核閱變成每週一次的動作。若哪天覺得太煩，正確做法是讓 `build_module()` 把核閱狀態連同**當時的資料期別**一起記下（例如 `reviewed_week: 31`），期別一變就自動失效——而不是單純沿用舊的 `true`。

## 新聞網站檢索備忘（做 compare / list 模組時會用到）

2026-08-12 實測結果。這幾個端點的行為差異直接決定「報導量」數字能不能比。

| 媒體 | 可用端點 | 分頁 | 總數顯示 |
|------|---------|:----:|---------|
| 自由時報 | `https://search.ltn.com.tw/list?keyword=<詞>&sort=date&type=all&start_time=YYYYMMDD&end_time=YYYYMMDD&page=N` | ✅ 20 筆/頁，`page=N` 正常運作 | ✅ 「約有 N 項結果」準確 |
| 聯合報 | `https://udn.com/search/word/2/<詞>`、`https://udn.com/search/tagging/2/<詞>` | ❌ **只回傳 20 筆**，`?page=2` 回同一頁、`/api/more?type=searchword` 第 2 頁即回空 | ⚠️ meta 的「共找到 N 篇」是全站累計，非查詢區間 |
| 中央社 | `https://www.cna.com.tw/search/hysearchws.aspx?q=<詞>&pageidx=1` | 單頁約 100 筆，依相關度＋日期混排 | ❌ 不顯示總數 |

實務要點：

- **自由時報是唯一能精確清點的。** 有日期區間參數，`page` 分頁可窮舉，總數可信。
- **聯合報只能取下限。** 搜尋頁與標籤頁各 20 筆、內容不完全重疊，去重後可得 20–25 筆。要精確得走聯合知識庫（`udndata.com`，付費）。報告裡務必寫成「≥N」。
- **中央社不需分頁**，單次請求就涵蓋數月，直接依日期篩選即可。但它是通訊社，**稿件會被他報轉載**（本次聯合報至少 1 篇標題與中央社一字不差），用篇數比較會系統性低估其影響力——這點要寫進模組 `note`。
- `cna2018api/api/WNewsSearch` 回空，不要試。`udn.com/api/more?type=searchword` 也回空。
- **全文檢索命中 ≠ 該事件報導。** 本次自由時報 80 筆命中裡有 11 筆是其他議題（慈濟疫苗案、葉霸案等），要逐筆分類後才能報數字。分母分子都要在模組 `note` 裡交代。

## 新增模組的流程

> 這是**人工模組**的流程。自動抓取的模組（如 NIDSS 疫情）不走這條路，見「自動抓取」章節。

1. `python3 tools/new_module.py compare fu-kunchi-absence "傅崐萁缺席院會"`
2. 編輯 `modules/fu-kunchi-absence/module.json`
3. 人工檢視內容無誤 → `status` 改 `published`、`review.reviewed` 改 `true`、移除 `sample`
4. `python3 tools/build.py`
5. commit + push（`data/dashboard.json` 要一起 commit，它是靜態產物）

## 注意事項

- **`data/dashboard.json` 必須 commit 進版控**，因為靜態站沒有 build server。
- 新增 renderer 型別要同時改 `app.js` 的 `renderers` 物件和 `build.py` 的 `VALID_TYPES`。
- `inline()` 會先跳脫 HTML 再套用標記，所以 JSON 內容可以安心放使用者輸入的文字。
- 疾管署資料有回溯校正，最近一週通常被低估；這類方法論陷阱請寫在模組的 `note` 欄位。
- **`cdc-covid-weekly`／`cdc-flu-severe-weekly` 由爬蟲整檔覆寫，手改會消失。** 要動就動 `tools/fetch_nidss.py`。
- 改 `app.js` 的 delta renderer 時，記得爬蟲產出的 `previous` 是**移動平均**而非前一點，`period_label`／`metric-step`／`magnitudeHint` 那條分支就是為它們而寫的。改動前先跑一次 `python3 tools/fetch_nidss.py --dry-run` 確認欄位還對得上。
- 部署到 GitHub Pages 時整個 repo 直接當 root 即可，沒有 build step。

## 目前模組狀態

| 模組 | 型別 | 資料 | 核閱 | 備註 |
|------|------|------|------|------|
| `cdc-covid-weekly` | delta | ✅ 真實（NIDSS） | ⬜ 待核閱 | 🤖 **爬蟲擁有，勿手改**。比較基準未定，見待辦 |
| `cdc-flu-severe-weekly` | delta | ✅ 真實（NIDSS） | ⬜ 待核閱 | 🤖 同上。判讀時務必看「檢驗中病例數」 |
| `fu-kunchi-absence` | compare | ✅ 真實（2026-08-12 實查） | ⬜ 待核閱 | 底稿見 `analysis/2026-08-12-fu-kunchi-agenda-setting.md` |
| `weather-taipei` | delta | ❌ 假資料 | — | |
| `twse-index` | delta | ❌ 假資料 | — | |
| `yt-topics-daily` | list | ❌ 假資料 | — | |
| `editor-note` | note | — | ✅ 已核閱 | 平台自我說明，內容不隨資料變動 |

四種 renderer 型別目前都有實際模組在用：`delta`×3、`compare`×1、`list`×1、`note`×1。`build.py` 會擋掉 `status` 非 `published` 的模組，目前沒有 draft。

## Pending Tasks (待辦事項)

> 此區塊記錄未完成的任務，Claude 啟動時自動載入。

- [ ] **安裝 launchd 排程**：`tools/com.jirlong.news2048.nidss.plist` 已寫好但**尚未安裝**，目前疫情數字仍靠手動執行。安裝指令見「自動抓取」章節。
- [ ] **決定排程日**：現設每週一 10:07，但週一的「上週」數字被回溯校正低估最嚴重。要不要改成週二／週三（改 plist 的 `Weekday`）？
- [ ] **卡片資訊量過大**（使用者 8/12 提出，細節未談完）：`fu-kunchi-absence` 每個 `fields` 都是完整段落，5 個 axes × 3 家媒體塞在一張 `l` 卡裡，高度遠超一個螢幕，已經不像「儀表板卡片」。可能方向：卡片只留 `volume` + `takeaway`，其餘收進展開區或整段移到 `analysis/`；或替 `compare` 加上「摘要／完整」兩段式渲染。**先跟使用者確認要往哪個方向做。**
- [ ] **決定疫情模組的比較基準**：目前主打「對前三週平均」（+50.0%），但「對前一週」是 +15.5%。要哪個當主要數字？
- [ ] 疫情模組核閱後把 `review.reviewed` 改 `true`——但這是**每週要做一次**的動作，不是一次性的（見下方說明）
- [ ] `fu-kunchi-absence` 核閱後把 `review.reviewed` 改 `true`
- [ ] `weather-taipei`、`twse-index` 仍是假資料，待換成真實來源
- [ ] 填入各台 YouTube 選題模組的真實影片標題
- [ ] 考慮把疫情模組的 `series` 從 12 週拉長到 52 週（流感有明顯季節性，短序列看不出來）
- [ ] 考慮把「累計死亡」做成第二個 metric（目前只寫在 `note` 裡）
- [ ] 決定部署方式（GitHub Pages / Netlify / 其他）
- [ ] 考慮把「報導量」本身做成 `delta` 模組（今天 vs 昨天各報對某議題的稿量），但只有自由時報能精確清點，聯合報缺分頁——先確認可行性
- [ ] 若要把 compare 模組做成常態產出，需寫爬蟲＋編碼流程；目前是人工逐筆分類，無法規模化

---
*Last updated: 2026-08-12*

### 最近一次工作紀錄（2026-08-12）

完成 `fu-kunchi-absence` 模組：以「傅崐萁五度缺席總預算協商、韓國瑜當眾動怒」（8/11 事發）為單一事件，清點三報 8/11–8/12 兩日報導量與框架。

結果：自由時報 69 篇、聯合報 ≥22 篇、中央社 8 篇。核心發現是**量差來自產能結構而非新聞判斷**——自由時報把每個名嘴／綠委發言拆成獨立稿件（評論擴散制），聯合報把每位藍營首長回應拆成獨立稿件（反應輪替制），中央社一個行動者只給一篇（配額制）。框架則給出三個不相容的責任歸屬：自由「一人癱瘓國會、318 萬人社福落空」／聯合「黨內摩擦、始作俑者是行政院」／中央社「各方說了什麼」。

最乾淨的證據是吳思瑤同一段發言的三個標題：中央社與聯合報一字不差（聯合直接用中央社供稿），自由時報加入評價性動詞「打臉」。
