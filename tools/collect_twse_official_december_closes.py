#!/usr/bin/env python3
"""Collect official TWSE December daily closing prices for candidate year-end prices.

This is a price-only source cross-check. It is NOT a total-return series; cash dividends,
stock dividends, splits, mergers and ticker changes must be separately reconciled before
the figures are used as total returns in the game.
"""
from __future__ import annotations
import csv, json, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

YEARS = range(1996, 2022)
ASSETS = [
    ("2330","晶峰科技","233","台積電"),
    ("1303","南岳材料","130","南亞"),
    ("2002","鋼岳重工","200","中鋼"),
    ("9911","櫻華生活","991","櫻花"),
    ("1216","統盛食品","121","統一"),
    ("1604","聲華電器","160","聲寶"),
    ("2303","聯晶科技","230","聯電"),
    ("1707","葡康生技","170","葡萄王"),
    ("2892","第一金融","289","第一金控"),
    ("2204","華馳汽車","220","中華車"),
    ("2501","國岳建設","250","國建"),
    ("1210","大豐食品","121-2","大成"),
]
OUT = Path("data/stock-candidates")
OUT.mkdir(parents=True, exist_ok=True)

def get_month(code: str, year: int) -> dict:
    params = urllib.parse.urlencode({"date": f"{year}1201", "stockNo": code, "response": "json"})
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?" + params
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; TaiwanStockTimeExchangeAudit/1.0)",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.twse.com.tw/",
    })
    last = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                data = json.loads(res.read().decode("utf-8"))
            if data.get("stat") not in ("OK", "查詢成功"):
                return {"status":"NO_DATA", "url":url, "error":str(data.get("stat","unknown"))}
            rows = data.get("data") or []
            parsed = []
            for row in rows:
                # TWSE dates are typically ROC year/month/day, e.g. 85/12/31
                dateparts = row[0].split("/")
                if len(dateparts) != 3:
                    continue
                y = int(dateparts[0]) + 1911
                m, d = int(dateparts[1]), int(dateparts[2])
                close_text = str(row[6]).replace(",", "").strip()
                try:
                    close = float(close_text)
                except ValueError:
                    continue
                parsed.append((f"{y:04d}-{m:02d}-{d:02d}", close))
            dec = [x for x in parsed if x[0].startswith(f"{year}-12-")]
            if not dec:
                return {"status":"NO_DECEMBER_CLOSE", "url":url, "error":""}
            date, close = max(dec)
            return {"status":"OK", "url":url, "date":date, "close":close, "error":""}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 * (attempt + 1))
    return {"status":"ERROR", "url":url, "error":last}

rows = []
for code, game_name, game_code, real_name in ASSETS:
    for year in YEARS:
        r = get_month(code, year)
        rows.append({
            "year":year, "real_ticker":code, "real_name":real_name,
            "game_name":game_name, "game_code":game_code,
            "december_last_trading_date":r.get("date",""),
            "raw_close_ntd":r.get("close",""), "status":r["status"],
            "source_url":r["url"], "error":r.get("error",""),
            "audit_status":"OFFICIAL_PRICE_ONLY_NOT_TOTAL_RETURN",
        })
        print(f'{code} {year}: {r["status"]} {r.get("date","")} {r.get("close","")}')
        time.sleep(0.12)

path = OUT / "twse_official_december_closes.csv"
with path.open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
    writer.writeheader(); writer.writerows(rows)
summary = {
 "generated_at_utc":datetime.now(timezone.utc).isoformat(),
 "method":"For each asset/year, query the official TWSE monthly daily-quote endpoint for December and select the last December trading day's raw close.",
 "warning":"Price-only values are not total returns. Do not use these as total-return inputs until dividends, stock dividends, splits, mergers and ticker changes are reconciled.",
 "assets":len(ASSETS),"years":len(list(YEARS)),"rows":len(rows),
 "found":sum(r["status"]=="OK" for r in rows),
 "missing_or_error":sum(r["status"]!="OK" for r in rows),
 "by_status":{s:sum(r["status"]==s for r in rows) for s in sorted(set(r["status"] for r in rows))},
}
(OUT/"twse_official_price_audit.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print("SUMMARY",json.dumps(summary,ensure_ascii=False))
