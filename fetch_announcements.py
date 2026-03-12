"""
ASX Price Sensitive Announcements — Daily Enriched Report
=========================================================
Fetches today's price sensitive announcements from ASX,
enriches each with market cap and sector via Yahoo Finance,
and outputs a self-contained HTML report saved as report.html.

Run manually:  python fetch_announcements.py
Scheduled via: GitHub Actions (.github/workflows/daily.yml)
"""

import requests
import json
import os
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
AEST = ZoneInfo("Australia/Sydney")
TODAY = date.today()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
REPORT_PATH = Path("report.html")

# ASX announcement feed — undocumented but stable public endpoint
# Returns JSON list of recent announcements filterable by market_sensitive
ASX_ANNOUNCEMENTS_URL = (
    "https://www.asx.com.au/asx/1/announcements"
    "?market_sensitive=true&count=100&timeframe=0D"
)

# Yahoo Finance batch quote endpoint (no API key needed)
YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "https://www.asx.com.au/",
}

# ── Fetch ASX announcements ───────────────────────────────────────────────────
def fetch_asx_announcements():
    print(f"[{datetime.now(AEST).strftime('%H:%M:%S')}] Fetching ASX announcements...")
    try:
        r = requests.get(ASX_ANNOUNCEMENTS_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        items = data.get("data", [])
        print(f"  → {len(items)} announcements fetched")
        return items
    except Exception as e:
        print(f"  ✗ ASX fetch failed: {e}")
        # Fallback: try alternative endpoint format
        try:
            alt_url = "https://www.asx.com.au/asx/1/announcements?market_sensitive=true&count=100"
            r = requests.get(alt_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            items = data.get("data", [])
            print(f"  → (fallback) {len(items)} announcements fetched")
            return items
        except Exception as e2:
            print(f"  ✗ Fallback also failed: {e2}")
            return []


# ── Fetch Yahoo Finance market data ──────────────────────────────────────────
def fetch_yahoo_data(tickers: list[str]) -> dict:
    """
    Returns dict of ticker → {name, sector, industry, mktcap, price, change_pct}
    Batches requests in groups of 20 to avoid URL length limits.
    """
    result = {}
    if not tickers:
        return result

    batch_size = 20
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        symbols = ",".join(f"{t}.AX" for t in batch)
        params = {
            "symbols": symbols,
            "fields": "shortName,longName,regularMarketPrice,regularMarketChangePercent,marketCap,trailingPE,sector,industry",
        }
        try:
            r = requests.get(
                YF_QUOTE_URL,
                params=params,
                headers={**HEADERS, "Accept": "application/json"},
                timeout=15,
            )
            r.raise_for_status()
            quotes = r.json().get("quoteResponse", {}).get("result", [])
            for q in quotes:
                ticker = q.get("symbol", "").replace(".AX", "")
                result[ticker] = {
                    "name": q.get("longName") or q.get("shortName") or ticker,
                    "sector": q.get("sector") or "Unknown",
                    "industry": q.get("industry") or "–",
                    "mktcap": q.get("marketCap"),
                    "price": q.get("regularMarketPrice"),
                    "change_pct": q.get("regularMarketChangePercent"),
                    "pe": q.get("trailingPE"),
                }
        except Exception as e:
            print(f"  ✗ Yahoo Finance batch {i//batch_size+1} failed: {e}")

    print(f"  → Market data fetched for {len(result)}/{len(tickers)} tickers")
    return result


# ── Format helpers ────────────────────────────────────────────────────────────
def fmt_mktcap(n):
    if not n:
        return "–"
    if n >= 1e12:
        return f"A${n/1e12:.2f}T"
    if n >= 1e9:
        return f"A${n/1e9:.2f}B"
    if n >= 1e6:
        return f"A${n/1e6:.0f}M"
    return f"A${n:,.0f}"


def mktcap_tier(n):
    if not n:
        return "micro"
    if n >= 10e9:
        return "large"
    if n >= 2e9:
        return "mid"
    if n >= 300e6:
        return "small"
    return "micro"


def fmt_time(s):
    if not s:
        return "–"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(AEST).strftime("%-I:%M %p")
    except Exception:
        return s[:16]


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── Build HTML report ─────────────────────────────────────────────────────────
def build_html(announcements: list, market_data: dict, generated_at: datetime) -> str:
    date_str = generated_at.strftime("%A %-d %B %Y")
    time_str = generated_at.strftime("%-I:%M %p AEST")
    total = len(announcements)
    enriched = sum(1 for a in announcements if a["ticker"] in market_data)

    # Build sector summary
    sector_counts = {}
    for a in announcements:
        md = market_data.get(a["ticker"], {})
        sector = md.get("sector", "Unknown")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    sector_pills = "".join(
        f'<span class="sector-pill">{esc(s)} <strong>{c}</strong></span>'
        for s, c in sorted(sector_counts.items(), key=lambda x: -x[1])
    )

    # Build rows
    rows_html = ""
    for a in announcements:
        ticker = a.get("ticker") or a.get("code", "–")
        headline = a.get("header") or a.get("title") or "Announcement"
        rel_time = fmt_time(a.get("document_release_date") or a.get("date"))
        pages = a.get("number_of_pages", "")
        pdf_url = a.get("url") or f"https://www.asx.com.au/markets/company/{ticker}"

        md = market_data.get(ticker, {})
        name = md.get("name") or ticker
        sector = md.get("sector") or "–"
        industry = md.get("industry") or "–"
        mktcap_str = fmt_mktcap(md.get("mktcap"))
        tier = mktcap_tier(md.get("mktcap"))
        price = md.get("price")
        chg = md.get("change_pct")
        price_str = f"A${price:.2f}" if price else "–"
        chg_str = f"{chg:+.2f}%" if chg is not None else ""
        chg_cls = "pos" if (chg or 0) >= 0 else "neg"

        rows_html += f"""
        <tr onclick="window.open('{esc(pdf_url)}','_blank')">
          <td class="td-ticker">{esc(ticker)}</td>
          <td class="td-company">
            <div class="company-name">{esc(name)}</div>
            <div class="company-industry">{esc(industry)}</div>
          </td>
          <td><span class="mktcap {tier}">{mktcap_str}</span></td>
          <td><span class="sector-badge">{esc(sector)}</span></td>
          <td class="td-price">
            <div>{price_str}</div>
            <div class="chg {chg_cls}">{chg_str}</div>
          </td>
          <td class="td-headline">
            <a href="{esc(pdf_url)}" target="_blank" onclick="event.stopPropagation()">{esc(headline)}</a>
            {f'<span class="pages">{pages}pp</span>' if pages else ''}
          </td>
          <td class="td-time">{rel_time}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="7" class="empty">No price sensitive announcements found for today.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ASX Price Sensitive Announcements — {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0a0e1a;--surface:#111827;--surface2:#1a2235;--border:#1e2d45;
  --blue:#3b82f6;--green:#10b981;--red:#ef4444;--amber:#f59e0b;--cyan:#06b6d4;--purple:#8b5cf6;
  --text:#e2e8f0;--dim:#64748b;--mid:#94a3b8;
  --mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif;
}}
body{{font-family:var(--sans);background:var(--bg);color:var(--text);min-height:100vh;padding:0 0 60px}}
header{{background:var(--surface);border-bottom:1px solid var(--border);padding:20px 40px;display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap}}
.header-left h1{{font-size:22px;font-weight:600;letter-spacing:-.3px}}
.header-left h1 span{{color:var(--blue)}}
.header-left .subtitle{{font-family:var(--mono);font-size:12px;color:var(--dim);margin-top:4px}}
.header-right{{text-align:right}}
.gen-time{{font-family:var(--mono);font-size:11px;color:var(--dim)}}
.stats{{display:flex;gap:24px;margin-top:8px;flex-wrap:wrap}}
.stat{{text-align:right}}
.stat-val{{font-family:var(--mono);font-size:18px;font-weight:500}}
.stat-val.blue{{color:var(--cyan)}} .stat-val.green{{color:var(--green)}} .stat-val.amber{{color:var(--amber)}}
.stat-label{{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}}

.sector-row{{padding:14px 40px;background:var(--surface2);border-bottom:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.sector-row-label{{font-family:var(--mono);font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px;margin-right:4px}}
.sector-pill{{background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.25);color:#a78bfa;font-size:11px;font-family:var(--mono);padding:3px 10px;border-radius:3px}}
.sector-pill strong{{color:var(--text)}}

.controls{{padding:14px 40px;border-bottom:1px solid var(--border);display:flex;gap:10px;align-items:center;flex-wrap:wrap;background:var(--surface)}}
.search{{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-family:var(--sans);font-size:13px;color:var(--text);outline:none;flex:1;min-width:200px;transition:border-color .15s}}
.search:focus{{border-color:var(--blue)}}
.search::placeholder{{color:var(--dim)}}
select{{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-family:var(--mono);font-size:12px;color:var(--text);outline:none;cursor:pointer}}
select:focus{{border-color:var(--blue)}}
.count-label{{font-family:var(--mono);font-size:11px;color:var(--dim);margin-left:auto}}

.table-wrap{{overflow-x:auto;padding:0 40px}}
table{{width:100%;border-collapse:collapse;margin-top:0;min-width:800px}}
thead tr{{background:var(--surface);border-bottom:2px solid var(--border)}}
th{{font-family:var(--mono);font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.8px;color:var(--dim);padding:12px 12px;text-align:left;white-space:nowrap;cursor:pointer;user-select:none}}
th:hover{{color:var(--blue)}}
tbody tr{{border-bottom:1px solid rgba(30,45,69,.5);transition:background .1s;cursor:pointer}}
tbody tr:hover{{background:rgba(59,130,246,.05)}}
td{{padding:12px 12px;vertical-align:middle}}
.td-ticker{{font-family:var(--mono);font-weight:500;color:var(--cyan);font-size:14px;white-space:nowrap}}
.td-company{{max-width:200px}}
.company-name{{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.company-industry{{font-size:11px;color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.mktcap{{font-family:var(--mono);font-size:12px;white-space:nowrap}}
.mktcap.large{{color:var(--green)}} .mktcap.mid{{color:var(--amber)}} .mktcap.small{{color:var(--mid)}} .mktcap.micro{{color:var(--dim)}}
.sector-badge{{background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.2);color:#a78bfa;font-size:10px;font-family:var(--mono);padding:3px 8px;border-radius:3px;white-space:nowrap;display:inline-block}}
.td-price{{font-family:var(--mono);font-size:12px;white-space:nowrap;text-align:right}}
.chg.pos{{color:var(--green);font-size:11px}} .chg.neg{{color:var(--red);font-size:11px}}
.td-headline a{{color:var(--text);text-decoration:none;font-size:13px;line-height:1.4}}
.td-headline a:hover{{color:var(--blue)}}
.pages{{background:rgba(100,116,139,.1);color:var(--dim);font-size:10px;font-family:var(--mono);padding:2px 6px;border-radius:3px;margin-left:8px}}
.td-time{{font-family:var(--mono);font-size:11px;color:var(--dim);white-space:nowrap}}
.empty{{text-align:center;padding:60px;color:var(--dim);font-family:var(--mono);font-size:13px}}
footer{{text-align:center;padding:30px;font-family:var(--mono);font-size:11px;color:var(--dim);border-top:1px solid var(--border);margin-top:40px}}
@media(max-width:768px){{header,.sector-row,.controls,.table-wrap{{padding-left:16px;padding-right:16px}}}}
</style>
</head>
<body>
<header>
  <div class="header-left">
    <h1><span>ASX</span> Price Sensitive Announcements</h1>
    <div class="subtitle">{date_str} · Enriched with market cap &amp; sector data</div>
  </div>
  <div class="header-right">
    <div class="gen-time">Generated {time_str}</div>
    <div class="stats">
      <div class="stat"><div class="stat-val blue">{total}</div><div class="stat-label">Announcements</div></div>
      <div class="stat"><div class="stat-val green">{enriched}</div><div class="stat-label">Enriched</div></div>
      <div class="stat"><div class="stat-val amber">{len(sector_counts)}</div><div class="stat-label">Sectors</div></div>
    </div>
  </div>
</header>

<div class="sector-row">
  <span class="sector-row-label">Sectors</span>
  {sector_pills or '<span style="color:var(--dim);font-size:12px">No sector data available</span>'}
</div>

<div class="controls">
  <input class="search" id="search" placeholder="Search ticker, company, headline…" oninput="filterTable()">
  <select id="sector-filter" onchange="filterTable()">
    <option value="">All Sectors</option>
    {"".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in sorted(sector_counts.keys()))}
  </select>
  <select id="sort-select" onchange="sortTable()">
    <option value="time-desc">Time (newest first)</option>
    <option value="mktcap-desc">Market Cap (largest first)</option>
    <option value="ticker-asc">Ticker (A–Z)</option>
    <option value="sector-asc">Sector (A–Z)</option>
  </select>
  <span class="count-label" id="count-label">{total} announcements</span>
</div>

<div class="table-wrap">
  <table id="ann-table">
    <thead>
      <tr>
        <th>Ticker</th>
        <th>Company</th>
        <th>Mkt Cap</th>
        <th>Sector</th>
        <th style="text-align:right">Price</th>
        <th>Announcement</th>
        <th>Time</th>
      </tr>
    </thead>
    <tbody id="table-body">
      {rows_html}
    </tbody>
  </table>
</div>

<footer>
  Data sourced from ASX.com.au (announcements) and Yahoo Finance (market data). 
  Price sensitive announcements only. Not financial advice.
  Report generated {time_str} · {date_str}
</footer>

<script>
// Store original rows for filtering/sorting
const allRows = Array.from(document.querySelectorAll('#table-body tr'));
const rowData = allRows.map(r => ({{
  el: r,
  ticker: r.querySelector('.td-ticker')?.textContent || '',
  company: r.querySelector('.company-name')?.textContent || '',
  headline: r.querySelector('.td-headline a')?.textContent || '',
  sector: r.querySelector('.sector-badge')?.textContent || '',
  mktcap: parseFloat(r.getAttribute('data-mktcap') || '0'),
  time: r.getAttribute('data-time') || '',
}}));

function filterTable() {{
  const q = document.getElementById('search').value.toLowerCase();
  const sec = document.getElementById('sector-filter').value.toLowerCase();
  let visible = 0;
  rowData.forEach(d => {{
    const match = (!q || (d.ticker+d.company+d.headline).toLowerCase().includes(q))
                && (!sec || d.sector.toLowerCase().includes(sec));
    d.el.style.display = match ? '' : 'none';
    if(match) visible++;
  }});
  document.getElementById('count-label').textContent = visible + ' announcements';
}}

function sortTable() {{
  const [col, dir] = document.getElementById('sort-select').value.split('-');
  const tbody = document.getElementById('table-body');
  const rows = [...rowData].sort((a,b) => {{
    let av = a[col]||'', bv = b[col]||'';
    if(col==='mktcap'){{ av=parseFloat(av)||0; bv=parseFloat(bv)||0; }}
    if(av<bv) return dir==='asc'?-1:1;
    if(av>bv) return dir==='asc'?1:-1;
    return 0;
  }});
  rows.forEach(r => tbody.appendChild(r.el));
}}
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f"ASX Enriched Announcements — {TODAY_STR}")
    print(f"{'='*60}\n")

    generated_at = datetime.now(AEST)

    # 1. Fetch announcements
    announcements = fetch_asx_announcements()

    # 2. Extract unique tickers
    tickers = list({
        a.get("ticker") or a.get("code", "")
        for a in announcements
        if a.get("ticker") or a.get("code")
    })
    print(f"  → {len(tickers)} unique tickers: {', '.join(sorted(tickers)[:20])}{'...' if len(tickers)>20 else ''}")

    # 3. Fetch market data
    print(f"\n[{datetime.now(AEST).strftime('%H:%M:%S')}] Fetching Yahoo Finance data...")
    market_data = fetch_yahoo_data(tickers)

    # 4. Build report
    print(f"\n[{datetime.now(AEST).strftime('%H:%M:%S')}] Building HTML report...")
    html = build_html(announcements, market_data, generated_at)

    # 5. Save
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"  → Report saved to {REPORT_PATH.resolve()}")
    print(f"\n✓ Done — {len(announcements)} announcements, {len(market_data)} enriched")
    print(f"  Open report.html in your browser to view.\n")


if __name__ == "__main__":
    main()
