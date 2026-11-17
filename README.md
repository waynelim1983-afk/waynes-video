# AI 影片生成產線

多平台 AI 影片生成，具備自動備援：依序嘗試 Google Flow（Veo 3）、Kling AI、OiiOii（Seedance）、HuggingFace Wan2.1，第一個成功就停止。

*Multi-backend AI video generation with automatic fallback — tries each service in order and stops at the first success.*

這是我自動經營 YouTube 頻道時用的影片生成核心。各 AI 影片平台的免費額度有限，也常常逾時或拒絕生成，所以設計成「一個不行就換下一個」，產線不會因為單一平台出問題而停擺。

---

## 運作方式

```
python main_smartcat.py --prompt "你的 prompt"

  1. 檢查 Veo 3 配額（只顯示，不會擋住備援）
  2. 依序嘗試各平台：
       Veo 3（Google Flow）→ Kling AI → OiiOii → HuggingFace Wan2.1
  3. 第一個成功就停止，影片存到 output/clips/
  4. 結果寫進 logs/daily.log
```

---

## 支援的平台

| 順序 | 平台 | 額度 | 浮水印 |
|---|---|---|---|
| 1 | **Veo 3**（Google Flow） | 每月 1000 點 | 無 |
| 2 | **Kling AI**（klingai.com） | 每天約 66 點 | 有 |
| 3 | **OiiOii**（Seedance 2.0 Pro） | STAR 代幣 | 無 |
| 4 | **HuggingFace Wan2.1** | 完全免費 | 無（排隊約 8–12 分鐘） |

Gemini（`gemini_browser.py`）和 Grok（`grok_browser.py`）可以選用來強化 prompt：在 `main_smartcat.py` 設定 `USE_GEMINI_PROMPT = True`，就會改用 Gemini 生成 prompt。

---

## 專案結構

```
waynes-video/
│
├── main_smartcat.py        # 入口：負責調度備援鏈
│
├── # ── AI 影片生成平台
├── veo3_browser.py         # Google Flow / Veo 3（主要）
├── kling_browser.py        # Kling AI
├── oiioii_browser.py       # OiiOii / Seedance 2.0 Pro
├── huggingface_wan2.py     # HuggingFace Wan2.1（免費）
├── gemini_browser.py       # Gemini：生成 prompt／影片
├── grok_browser.py         # Grok：生成 prompt／影片
│
├── # ── Prompt 與檢查
├── prompts_smartcat.py     # Prompt 範本
├── prompt_validator.py     # Prompt 檢查工具
├── affiliate_products.py   # 選品（內建虛構示範產品，可改讀 config/products.json）
│
├── # ── 工具
├── quota_tracker.py        # Veo 3 每月配額追蹤
├── recovery.py             # 從 Flow 或 output/ 找回還沒處理的影片
│
├── config/
│   ├── flow_config.example.json   # Google Flow 設定範本
│   └── credentials/               # 瀏覽器登入狀態（絕對不要提交）
│
├── output/                 # 生成的影片（自動建立，不提交）
├── logs/                   # 執行紀錄（不提交）
└── assets/bgm/             # 背景音樂（不提交）
```

---

## 快速開始

### 需求

- Python 3.10 以上
- Google Chrome（透過 Playwright 做瀏覽器自動化）
- 你要使用的平台帳號（Google Flow／Kling AI／HuggingFace）

### 安裝

```bash
git clone https://github.com/waynelim1983-afk/waynes-video.git
cd waynes-video
pip install playwright gradio_client httpx
playwright install chromium
```

### 設定

複製 Flow 設定範本，填入你的專案 ID：

```bash
cp config/flow_config.example.json config/flow_config.json
# 編輯 flow_config.json，把 YOUR_PROJECT_ID_HERE 換掉
```

選品預設使用內建的虛構示範產品。要換成自己的選品，建立 `config/products.json`（格式見 `affiliate_products.py` 開頭說明，這個檔案已加進 `.gitignore`）。

第一次執行時，各平台模組會開啟 Chrome 請你登入。登入狀態存在 `config/credentials/`（只留在本機，絕對不要提交這個資料夾）。

### 執行

```bash
# 生成一支影片（依序走備援鏈）
python main_smartcat.py --prompt "A cat chasing a laser dot, cinematic slow motion"

# 依序生成 3 支（約 36 分鐘）
python main_smartcat.py --prompt "..." --count 3

# 透過 HuggingFace 同時生成 3 支（約 12 分鐘）
python main_smartcat.py --prompt "..." --count 3 --parallel

# 找回還沒處理的影片（加 --scan-only 只報告不動作，加 --no-flow 跳過 Google Flow）
python main_smartcat.py --recover
```

---

## 平行模式

`--parallel` 會同時送出 N 個 HuggingFace Wan2.1 任務，跳過 Veo 3、Kling、OiiOii。適合 Veo 3 配額用完，或需要快速大量生成時使用。

| 模式 | 3 支影片 | 節省時間 |
|---|---|---|
| 依序 | 約 36 分鐘 | — |
| 平行 | 約 12 分鐘 | 約 66% |

---

## Veo 3 配額

`quota_tracker.py` 在本機記錄 Google Flow 的用量：

```bash
python quota_tracker.py
# Veo3 配額 | 本期已用: 0pts | 剩餘: 1940pts (97 支影片) | 下次重置: 2026-07-09
```

上限 1940 點是 Flow 每月 1000 點加上 940 點 AI 備用點數，實際剩餘以 Google Flow 畫面為準。配額每月 9 號重置。產線不會因為配額卡住，一定會往下改用免費平台。

---

## 注意事項

- `config/credentials/` 存的是瀏覽器登入狀態，**絕對不要提交**（已加進 `.gitignore`）
- 每個平台模組都接受 `--prompt` 和 `--output` 參數，可以單獨執行來測試
- Wan2.x 模型對中文 prompt 的反應明顯比較好；要讓 HuggingFace 效果最好，可以在 `_build_job` 裡把中文版本傳給 `hf_prompt`

---

## 授權

MIT
