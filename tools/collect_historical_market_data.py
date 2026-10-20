#!/usr/bin/env python3
"""Collect annual total-return candidates from Yahoo Finance adjusted-close history.

This is a data-screening job, not a final audited production dataset. Adjusted-close
returns are kept separate from raw 1996 year-end closing prices. Missing observations
are left blank and reported; no missing values are invented.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

START = int(datetime(1996, 12, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2022, 1, 15, tzinfo=timezone.utc).timestamp())
YEARS = list(range(1997, 2022))
BASE_YEAR = 1996

ASSETS = [
    {"ticker":"2330.TW","game_name":"晶峰科技","game_code":"233","real_name":"台積電","note":""},
    {"ticker":"1303.TW","game_name":"南岳材料","game_code":"130","real_name":"南亞","note":""},
    {"ticker":"2002.TW","game_name":"鋼岳重工","game_code":"200","real_name":"中鋼","note":""},
    {"ticker":"9911.TW","game_name":"櫻華生活","game_code":"991","real_name":"櫻花","note":""},
    {"ticker":"1216.TW","game_name":"統盛食品","game_code":"121","real_name":"統一","note":""},
    {"ticker":"1604.TW","game_name":"聲華電器","game_code":"160","real_name":"聲寶","note":""},
    {"ticker":"2303.TW","game_name":"聯晶科技","game_code":"230","real_name":"聯電","note":""},
    {"ticker":"1707.TW","game_name":"葡康生技","game_code":"170","real_name":"葡萄王","note":""},
    {"ticker":"2892.TW","game_name":"第一金融","game_code":"289","real_name":"第一金控","note":"第一金控於2003-01-02掛牌；1997-2002前身第一銀行序列需另行核證，不能以2892.TW直接補值。"},
    {"ticker":"2204.TW","game_name":"華馳汽車","game_code":"220","real_name":"中華車","note":""},
    {"ticker":"2501.TW","game_name":"國岳建設","game_code":"250","real_name":"國建","note":""},
    {"ticker":"1210.TW","game_name":"大豐食品","game_code":"121-2","real_name":"大成","note":""},
]

SOURCE_BASE = "https://finance.yahoo.com/quote/{ticker}/history/"
OFFICIAL_PRICE_SOURCE = "https://data.gov.tw/dataset/11548"
OFFICIAL_DIVIDEND_SOURCE = "https://data.gov.tw/en/datasets/31612"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
OUT.mkdir(parents=True, exist_ok=True)


def fetch_json(url: str) -> dict:
    last_error = None
    for attempt in range(4):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TaiwanStockTimeExchangeDataAudit/1.0)",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def get_series(asset: dict) -> dict:
    ticker = asset["ticker"]
    query = urllib.parse.urlencode({
        "period1": START,
        "period2": END,
        "interval": "1d",
        "events": "div,splits",
    })
    api_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{query}"
    result = {
        "ticker": ticker,
        "game_name": asset["game_name"],
        "game_code": asset["game_code"],
        "real_name": asset["real_name"],
        "api_url": api_url,
        "history_url": SOURCE_BASE.format(ticker=ticker),
        "status": "ERROR",
        "error": "",
        "exchange_timezone": "",
        "year_ends": {},
        "base_close": None,
        "base_date": "",
        "note": asset["note"],
    }
    try:
        root = fetch_json(api_url)
        chart = root.get("chart", {})
        if chart.get("error"):
            raise RuntimeError(str(chart["error"]))
        rows = chart.get("result") or []
        if not rows:
            raise RuntimeError("No chart result")
        payload = rows[0]
        meta = payload.get("meta", {})
        tz_name = meta.get("exchangeTimezoneName") or "Asia/Taipei"
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("Asia/Taipei")
        result["exchange_timezone"] = tz_name
        timestamps = payload.get("timestamp") or []
        indicators = payload.get("indicators", {})
        quotes = (indicators.get("quote") or [{}])[0]
        closes = quotes.get("close") or []
        adjrows = (indicators.get("adjclose") or [{}])
        adjusted = (adjrows[0].get("adjclose") if adjrows else None) or []
        year_points: dict[int, dict] = {}
        base_candidates = []
        for i, stamp in enumerate(timestamps):
            dt = datetime.fromtimestamp(stamp, timezone.utc).astimezone(tz)
            close = closes[i] if i < len(closes) else None
            adj = adjusted[i] if i < len(adjusted) else None
            if dt.year == BASE_YEAR and dt.month == 12 and close is not None:
                base_candidates.append((dt, float(close)))
            if dt.year in YEARS and adj is not None:
                prev = year_points.get(dt.year)
                if prev is None or dt > prev["datetime"]:
                    year_points[dt.year] = {
                        "datetime": dt,
                        "adj_close": float(adj),
                        "raw_close": float(close) if close is not None else None,
                    }
            if dt.year == BASE_YEAR and adj is not None:
                prev = year_points.get(BASE_YEAR)
                if prev is None or dt > prev["datetime"]:
                    year_points[BASE_YEAR] = {
                        "datetime": dt,
                        "adj_close": float(adj),
                        "raw_close": float(close) if close is not None else None,
                    }
        if base_candidates:
            dt, close = max(base_candidates, key=lambda item: item[0])
            result["base_date"] = dt.date().isoformat()
            result["base_close"] = close
        for yr, point in year_points.items():
            result["year_ends"][yr] = {
                "date": point["datetime"].date().isoformat(),
                "adj_close": point["adj_close"],
                "raw_close": point["raw_close"],
            }
        if not result["year_ends"]:
            raise RuntimeError("No year-end adjusted-close observations")
        result["status"] = "FETCHED"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


series_results = []
for i, asset in enumerate(ASSETS):
    result = get_series(asset)
    series_results.append(result)
    print(f"[{i+1}/{len(ASSETS)}] {asset['ticker']}: {result['status']} "
          f"({len(result['year_ends'])} annual/year-end points)")
    time.sleep(0.4)

price_rows = []
return_rows = []
missing_counts = {}
for result in series_results:
    points = result["year_ends"]
    base_status = "OK" if result["base_close"] is not None else "MISSING_1996_DECEMBER_CLOSE"
    price_rows.append({
        "real_ticker": result["ticker"],
        "real_name": result["real_name"],
        "game_name": result["game_name"],
        "game_code": result["game_code"],
        "base_year": BASE_YEAR,
        "base_date": result["base_date"],
        "base_close_ntd": result["base_close"] if result["base_close"] is not None else "",
        "status": base_status,
        "source_url": result["history_url"],
        "note": result["note"],
    })
    prev = points.get(BASE_YEAR)
    missing = []
    for year in YEARS:
        current = points.get(year)
        if prev is None:
            status = "MISSING_PRIOR_YEAR_END"
            ret = ""
            prior_date = ""
            prior_adj = ""
        elif current is None:
            status = "MISSING_YEAR_END"
            ret = ""
            prior_date = prev["date"]
            prior_adj = prev["adj_close"]
        else:
            status = "OK"
            ret = current["adj_close"] / prev["adj_close"] - 1
            prior_date = prev["date"]
            prior_adj = prev["adj_close"]
        if status != "OK":
            missing.append(f"{year}:{status}")
        return_rows.append({
            "year": year,
            "real_ticker": result["ticker"],
            "real_name": result["real_name"],
            "game_name": result["game_name"],
            "game_code": result["game_code"],
            "prior_year_end_date": prior_date,
            "prior_year_end_adj_close": prior_adj,
            "year_end_date": current["date"] if current else "",
            "year_end_adj_close": current["adj_close"] if current else "",
            "annual_total_return_decimal": ret,
            "status": status,
            "source_url": result["history_url"],
            "audit_status": "SECONDARY_SOURCE_PENDING_OFFICIAL_CROSSCHECK",
            "note": result["note"],
        })
        if current is not None:
            prev = current
    missing_counts[result["ticker"]] = {
        "fetch_status": result["status"],
        "missing_years": missing,
        "missing_count": len(missing),
        "base_price_status": base_status,
        "fetch_error": result["error"],
        "note": result["note"],
    }


def fetch_twse_december_close(stock_code: str, year: int) -> dict:
    """Fetch the official TWSE daily trading rows for December and retain the last close."""
    month_date = f"{year}12" + "01"
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?" + urllib.parse.urlencode({
        "date": month_date, "stockNo": stock_code, "response": "json"
    })
    row = {
        "year": year, "stock_code": stock_code, "last_trading_date": "",
        "official_december_close_ntd": "", "status": "MISSING",
        "source_url": url, "note": ""
    }
    try:
        payload = fetch_json(url)
        data = payload.get("data") or []
        if not data:
            row["note"] = str(payload.get("stat") or "No daily rows returned")
            return row
        # TWSE date format is ROC year/month/day; close is column 6.
        def iso_date(record):
            parts = str(record[0]).split("/")
            if len(parts) != 3:
                return ""
            return f"{int(parts[0]) + 1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        valid = []
        for record in data:
            if len(record) < 7:
                continue
            date_text = iso_date(record)
            close_text = str(record[6]).replace(",", "").strip()
            if date_text and close_text and close_text not in {"--", "-", "X0.00"}:
                try:
                    valid.append((date_text, float(close_text)))
                except ValueError:
                    continue
        if valid:
            date_text, close_value = max(valid, key=lambda x: x[0])
            row.update({
                "last_trading_date": date_text,
                "official_december_close_ntd": close_value,
                "status": "OK",
                "note": "Official TWSE daily close for last available trading day in December."
            })
        else:
            row["note"] = str(payload.get("stat") or "No usable close value in response")
    except Exception as exc:
        row["status"] = "ERROR"
        row["note"] = f"{type(exc).__name__}: {exc}"
    return row


# Official TWSE monthly daily records are available from 1999-01-05 onward.
# Keep this separate from Yahoo adjusted-close returns: official raw close is not total return.
official_december_rows = []
for asset in ASSETS:
    stock_code = asset["ticker"].split(".")[0]
    for year in range(1999, 2022):
        row = fetch_twse_december_close(stock_code, year)
        row["ticker"] = asset["ticker"]
        row["game_name"] = asset["game_name"]
        official_december_rows.append(row)
        if row["status"] != "OK":
            print(f"[TWSE] {asset['ticker']} {year}: {row['status']} {row['note']}")
        time.sleep(0.12)

def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

write_csv(
    OUT / "twse_official_december_closes_1999_2021.csv",
    official_december_rows,
    ["year","stock_code","ticker","game_name","last_trading_date","official_december_close_ntd","status","source_url","note"],
)
write_csv(
    OUT / "stock_annual_total_return_candidates.csv",
    return_rows,
    ["year","real_ticker","real_name","game_name","game_code","prior_year_end_date",
     "prior_year_end_adj_close","year_end_date","year_end_adj_close",
     "annual_total_return_decimal","status","source_url","audit_status","note"],
)
write_csv(
    OUT / "stock_base_prices_candidates.csv",
    price_rows,
    ["real_ticker","real_name","game_name","game_code","base_year","base_date",
     "base_close_ntd","status","source_url","note"],
)
wide_rows = []
for year in YEARS:
    row = {"year": year}
    for result in series_results:
        item = next((x for x in return_rows if x["year"] == year and x["real_ticker"] == result["ticker"]), None)
        row[result["ticker"]] = item["annual_total_return_decimal"] if item else ""
        row[result["ticker"] + "_status"] = item["status"] if item else "NO_ROW"
    wide_rows.append(row)
wide_fields = ["year"]
for asset in ASSETS:
    wide_fields.extend([asset["ticker"], asset["ticker"] + "_status"])
write_csv(OUT / "stock_annual_total_returns_wide.csv", wide_rows, wide_fields)

audit = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "method": "Calendar-year total-return candidate = Yahoo adjusted close at last available trading observation of year / prior calendar-year-end adjusted close - 1. The adjusted-close time series is secondary source data and is not yet officially cross-checked.",
    "base_price_method": "1996 raw December close is still unavailable from the currently queried free official endpoint; do not substitute annual average price. Official TWSE December last-trading-day closes are collected separately for 1999-2021.",
    "official_december_close_method": "For each stock and each year 1999-2021, query TWSE STOCK_DAY for December and retain the last dated row with a valid raw close. These are price-only closes and are not total-return figures.",
    "primary_sources_for_crosscheck": [
        {"name":"TWSE daily closing prices and monthly average prices dataset","url":OFFICIAL_PRICE_SOURCE},
        {"name":"TWSE listed-company dividend distribution dataset","url":OFFICIAL_DIVIDEND_SOURCE},
    ],
    "adjusted_close_method_source": "https://in.help.yahoo.com/kb/adjusted-close-sln28256.html",
    "years_required": YEARS,
    "assets_required": ASSETS,
    "results": missing_counts,
    "totals": {
        "assets": len(ASSETS),
        "annual_return_rows": len(return_rows),
        "official_december_close_rows": len(official_december_rows),
        "official_december_closes_found": sum(1 for r in official_december_rows if r["status"] == "OK"),
        "official_december_closes_missing_or_error": sum(1 for r in official_december_rows if r["status"] != "OK"),
        "complete_return_rows": sum(1 for r in return_rows if r["status"] == "OK"),
        "missing_return_rows": sum(1 for r in return_rows if r["status"] != "OK"),
        "base_prices_found": sum(1 for r in price_rows if r["status"] == "OK"),
        "base_prices_missing": sum(1 for r in price_rows if r["status"] != "OK"),
    },
}
(OUT / "source_audit_report.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(audit["totals"], ensure_ascii=False))
