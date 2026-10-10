# V0.4 線上房間版設定指南

這是跨手機連線版的後端資料庫基礎。正式遊戲頁面仍需接上這個後端並測試後，才算完成線上版。

## 建立資料庫
1. 開啟 https://supabase.com/dashboard 並登入。
2. 建立新專案，名稱可用 best-or-first-game。
3. 專案建立後，進入 SQL Editor。
4. 開啟儲存庫中的 supabase/schema.sql，複製全部內容貼入 SQL Editor，按 Run。
5. 確認顯示成功；若出錯，請先把錯誤訊息傳回來。

## 取得前端連線資料
在 Project Settings → API 中，複製 Project URL 以及 publishable key（舊介面可能叫 anon public key）。只提供這兩項即可供前端設定。
**絕對不要分享 service_role、secret key 或資料庫密碼。**

## 遊戲規劃
- 3–10 人、6 碼房間碼、房主控制回合。
- 分區 3 分鐘；秘密選擇 3–5 人 3 分鐘、6–10 人 5 分鐘。
- 各區分開計分，區內至少 3 人且非平手時，少數選擇者各 +1。
- 每位玩家輪流當莊家，回合數等於玩家數。
- 這份 SQL 是後端基礎；前端即時同步、秘密選擇隱藏、斷線重連和完整測試仍待整合。
