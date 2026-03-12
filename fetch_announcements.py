"""
ASX Price Sensitive Announcements — Daily Enriched Report
Scrapes Market Index (marketindex.com.au) for today's price sensitive
announcements, then enriches with Yahoo Finance market data.
"""

import requests
import json
import re
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    AEST = ZoneInfo("Australia/Sydney")
except ImportError:
    AEST = timezone(timedelta(hours=10))

TODAY     = date.today()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
REPORT_PATH = Path("report.html")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-AU,en;q=0.9",
}

YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

# ── Fetch from Market Index ─────────────────────────────────────────────────────
MI_ENDPOINTS = [
    # Market Index JSON API (used by their own page)
    "https://www.marketindex.com.au/api/announcements?type=price-sensitive&exchange=ASX",
    "https://www.marketindex.com.au/api/asx/announcements?sensitive=true",
    "https://www.marketindex.com.au/api/announcements?sensitive=1",
    # Their announcements page (HTML fallback)
    "https://www.marketindex.com.au/asx/announcements",
]

def now_str():
    return datetime.now().strftime("%H:%M:%S")

def parse_mi_json(data):
    """Try to extract announcement list from various JSON shapes."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("announcements", "data", "results", "items", "records"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return []

def parse_mi_html(html):
    """
    Extract announcement data from Market Index HTML page.
    They embed JSON in a __NEXT_DATA__ or window.__INITIAL_STATE__ script tag.
    """
    # Try Next.js data island
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            nd = json.loads(match.group(1))
            # Walk the props tree looking for announcements array
            props = nd.get("props", {}).get("pageProps", {})
            for key in ("announcements", "data", "initialData"):
                if key in props and isinstance(props[key], list):
                    print(f"  → Found {len(props[key])} items in Next.js __NEXT_DATA__.props.pageProps.{key}")
                    return props[key]
            # Deeper search
            def find_list(obj, depth=0):
                if depth > 5: return None
                if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
                    if any(k in obj[0] for k in ("ticker","code","asx_code","symbol","headline","header")):
                        return obj
                if isinstance(obj, dict):
                    for v in obj.values():
                        r = find_list(v, depth+1)
                        if r: return r
                return None
            result = find_list(nd)
            if result:
                print(f"  → Found {len(result)} items via deep search of __NEXT_DATA__")
                return result
        except Exception as e:
            print(f"  → __NEXT_DATA__ parse error: {e}")

    # Try window.__INITIAL_STATE__
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.DOTALL)
    if match:
        try:
            state = json.loads(match.group(1))
            for key in ("announcements", "data"):
                if key in state and isinstance(state[key], list):
                    return state[key]
        except:
            pass

    # Try any JSON array in script tags
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        script = m.group(1)
        if '"ticker"' in script or '"asx_code"' in script or '"headline"' in script:
            # Try to extract JSON array
            arr_match = re.search(r'(\[{.*?}\])', script, re.DOTALL)
            if arr_match:
                try:
                    items = json.loads(arr_match.group(1))
                    if isinstance(items, list) and items:
                        return items
                except:
                    pass

    print("  → Could not extract structured data from HTML")
    return []

def normalize_mi(raw):
    """Normalise a Market Index announcement to standard shape."""
    ticker = (raw.get("ticker") or raw.get("code") or raw.get("asx_code")
              or raw.get("symbol") or raw.get("company_code") or "–")
    headline = (raw.get("headline") or raw.get("header") or raw.get("title")
                or raw.get("announcement") or "Announcement")
    released = (raw.get("release_date") or raw.get("released_at") or raw.get("date")
                or raw.get("time") or raw.get("document_release_date") or "")
    pdf_url  = (raw.get("url") or raw.get("pdf_url") or raw.get("link")
                or raw.get("document_url")
                or f"https://www.asx.com.au/markets/company/{ticker}")
    pages    = raw.get("pages") or raw.get("number_of_pages") or ""
    return {
        "ticker":   str(ticker).upper().strip(),
        "headline": str(headline).strip(),
        "released": str(released),
        "pdf_url":  str(pdf_url),
        "pages":    pages,
    }

def fetch_announcements():
    print(f"\n[{now_str()}] Fetching from Market Index...")
    session = requests.Session()

    for endpoint in MI_ENDPOINTS:
        is_html = endpoint.endswith("/announcements") and "api" not in endpoint
        try:
            print(f"  Trying: {endpoint}")
            r = session.get(endpoint, headers=HEADERS, timeout=30)
            print(f"  → HTTP {r.status_code} | Content-Type: {r.headers.get('content-type','?')[:50]}")

            if r.status_code != 200:
                print(f"  → Skipping non-200")
                continue

            content_type = r.headers.get("content-type", "")

            if "json" in content_type:
                try:
                    data = r.json()
                    items = parse_mi_json(data)
                    if items:
                        print(f"  ✓ Got {len(items)} items from JSON endpoint")
                        return [normalize_mi(i) for i in items]
                    else:
                        print(f"  → JSON returned empty list. Keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                except Exception as e:
                    print(f"  → JSON parse error: {e}")

            elif "html" in content_type or is_html:
                items = parse_mi_html(r.text)
                if items:
                    print(f"  ✓ Got {len(items)} items from HTML page")
                    return [normalize_mi(i) for i in items]
                else:
                    # Save HTML snippet for debugging
                    snippet = r.text[:2000]
                    print(f"  → HTML snippet (first 500 chars): {snippet[:500]}")

        except Exception as e:
            print(f"  → Error: {e}")

    print("\n  ⚠ All Market Index endpoints failed.")
    print("  Generating empty report.")
    return []


# ── Yahoo Finance ───────────────────────────────────────────────────────────────
def fetch_yahoo_data(tickers):
    if not tickers:
        return {}
    result = {}
    print(f"\n[{now_str()}] Fetching Yahoo Finance data for {len(tickers)} tickers...")
    for i in range(0, len(tickers), 20):
        batch   = tickers[i:i+20]
        symbols = ",".join(f"{t}.AX" for t in batch)
        params  = {
            "symbols": symbols,
            "fields": "shortName,longName,regularMarketPrice,regularMarketChangePercent,marketCap,sector,industry",
        }
        try:
            r = requests.get(YF_QUOTE_URL, params=params, headers=HEADERS, timeout=20)
            r.raise_for_status()
            for q in r.json().get("quoteResponse", {}).get("result", []):
                t = q.get("symbol", "").replace(".AX", "")
                result[t] = {
                    "name":       q.get("longName") or q.get("shortName") or t,
                    "sector":     q.get("sector") or "Unknown",
                    "industry":   q.get("industry") or "–",
                    "mktcap":     q.get("marketCap"),
                    "price":      q.get("regularMarketPrice"),
                    "change_pct": q.get("regularMarketChangePercent"),
                }
        except Exception as e:
            print(f"  ✗ Yahoo batch failed: {e}")
        time.sleep(0.3)
    print(f"  → Market data for {len(result)}/{len(tickers)} tickers")
    return result


# ── Helpers ─────────────────────────────────────────────────────────────────────
def fmt_mktcap(n):
    if not n: return "–"
    if n >= 1e12: return f"A${n/1e12:.2f}T"
    if n >= 1e9:  return f"A${n/1e9:.2f}B"
    if n >= 1e6:  return f"A${n/1e6:.0f}M"
    return f"A${n:,.0f}"

def mktcap_tier(n):
    if not n: return "micro"
    if n >= 10e9:  return "large"
    if n >= 2e9:   return "mid"
    if n >= 300e6: return "small"
    return "micro"

def fmt_time(s):
    if not s: return "–"
    try:
        dt   = datetime.fromisoformat(s.replace("Z", "+00:00"))
        aest = dt.astimezone(timezone(timedelta(hours=10)))
        return aest.strftime("%-I:%M %p")
    except:
        return s[:16]

def esc(s):
    return (str(s or "")
        .replace("&","&amp;").replace("<","&lt;")
        .replace(">","&gt;").replace('"',"&quot;"))


# ── HTML Report ─────────────────────────────────────────────────────────────────
def build_html(announcements, market_data, generated_at):
    date_str = generated_at.strftime("%A %-d %B %Y")
    time_str = generated_at.strftime("%-I:%M %p AEST")
    total    = len(announcements)
    enriched = sum(1 for a in announcements if a["ticker"] in market_data)

    sector_counts = {}
    for a in announcements:
        s = market_data.get(a["ticker"], {}).get("sector", "Unknown")
        sector_counts[s] = sector_counts.get(s, 0) + 1

    sector_pills = "".join(
        f'<span class="sector-pill">{esc(s)} <strong>{c}</strong></span>'
        for s, c in sorted(sector_counts.items(), key=lambda x: -x[1])
    ) or '<span style="color:#7d8590">No sector data</span>'

    rows_html = ""
    for a in announcements:
        md        = market_data.get(a["ticker"], {})
        name      = md.get("name") or a["ticker"]
        sector    = md.get("sector") or "–"
        industry  = md.get("industry") or "–"
        mc_str    = fmt_mktcap(md.get("mktcap"))
        tier      = mktcap_tier(md.get("mktcap"))
        price     = md.get("price")
        chg       = md.get("change_pct")
        p_str     = f"A${price:.2f}" if price else "–"
        chg_str   = f"{chg:+.2f}%" if chg is not None else ""
        chg_cls   = "pos" if (chg or 0) >= 0 else "neg"
        pages_tag = f'<span class="pages">{a["pages"]}pp</span>' if a["pages"] else ""
        rows_html += f"""
        <tr onclick="window.open('{esc(a['pdf_url'])}','_blank')">
          <td class="td-ticker">{esc(a['ticker'])}</td>
          <td class="td-company">
            <div class="company-name">{esc(name)}</div>
            <div class="company-industry">{esc(industry)}</div>
          </td>
          <td><span class="mktcap {tier}">{mc_str}</span></td>
          <td><span class="sector-badge">{esc(sector)}</span></td>
          <td class="td-price"><div>{p_str}</div><div class="chg {chg_cls}">{chg_str}</div></td>
          <td class="td-headline">
            <a href="{esc(a['pdf_url'])}" target="_blank" onclick="event.stopPropagation()">{esc(a['headline'])}</a>
            {pages_tag}
          </td>
          <td class="td-time">{fmt_time(a['released'])}</td>
        </tr>"""

    if not rows_html:
        rows_html = f'<tr><td colspan="7" class="empty">No price sensitive announcements found for {date_str}.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASX Price Sensitive — {date_str}</title>
<style>
:root{{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#7d8590;
      --accent:#58a6ff;--green:#3fb950;--red:#f85149;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{padding:20px 24px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start}}
h1{{font-size:22px;font-weight:700}}h1 span{{color:var(--accent)}}
.subtitle{{font-size:12px;color:var(--muted);margin-top:4px}}
.stats{{text-align:right;font-size:12px;color:var(--muted)}}
.stat-num{{font-size:22px;font-weight:700;color:var(--accent);display:block}}
.sectors-bar{{padding:10px 24px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.sectors-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}}
.sector-pill{{background:#21262d;border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:12px}}
.sector-pill strong{{color:var(--accent)}}
.controls{{padding:10px 24px;display:flex;gap:10px;align-items:center;border-bottom:1px solid var(--border)}}
input[type=search]{{flex:1;background:#21262d;border:1px solid var(--border);border-radius:6px;color:var(--text);padding:7px 12px;font-size:13px}}
select{{background:#21262d;border:1px solid var(--border);border-radius:6px;color:var(--text);padding:7px 10px;font-size:13px}}
.count{{font-size:12px;color:var(--muted);white-space:nowrap}}
table{{width:100%;border-collapse:collapse}}
th{{background:var(--surface);border-bottom:2px solid var(--border);padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{color:var(--text)}}
td{{padding:10px 12px;border-bottom:1px solid #21262d;vertical-align:top}}
tr{{cursor:pointer;transition:background .15s}}tr:hover{{background:#161b22}}
.td-ticker{{font-weight:700;color:var(--accent);font-size:13px;white-space:nowrap}}
.company-name{{font-weight:500;font-size:13px}}.company-industry{{font-size:11px;color:var(--muted)}}
.mktcap{{border-radius:4px;padding:2px 8px;font-size:12px;font-weight:600;white-space:nowrap}}
.mktcap.large{{background:#f0883e22;color:#f0883e}}.mktcap.mid{{background:#58a6ff22;color:#58a6ff}}
.mktcap.small{{background:#3fb95022;color:#3fb950}}.mktcap.micro{{background:#7d859022;color:#7d8590}}
.sector-badge{{background:#21262d;border-radius:4px;padding:2px 8px;font-size:11px;white-space:nowrap}}
.td-price{{white-space:nowrap;font-size:13px}}.chg.pos{{color:var(--green)}}.chg.neg{{color:var(--red)}}
.td-headline a{{color:var(--text);text-decoration:none;font-size:13px}}.td-headline a:hover{{color:var(--accent)}}
.pages{{margin-left:6px;background:#21262d;border-radius:3px;padding:1px 5px;font-size:11px;color:var(--muted)}}
.td-time{{color:var(--muted);font-size:12px;white-space:nowrap}}
.empty{{text-align:center;padding:40px;color:var(--muted);font-family:monospace}}
footer{{text-align:center;padding:20px;font-size:11px;color:var(--muted);border-top:1px solid var(--border)}}
.hidden{{display:none}}
</style>
</head>
<body>
<header>
  <div>
    <h1><span>ASX</span> Price Sensitive Announcements</h1>
    <div class="subtitle">{date_str} &nbsp;·&nbsp; Enriched with market cap &amp; sector data &nbsp;·&nbsp; Source: Market Index + Yahoo Finance</div>
  </div>
  <div class="stats">
    <span>Generated {time_str}</span><br>
    <span class="stat-num" id="visCount">{total}</span> ANNOUNCEMENTS &nbsp;
    <span class="stat-num">{enriched}</span> ENRICHED &nbsp;
    <span class="stat-num">{len(sector_counts)}</span> SECTORS
  </div>
</header>
<div class="sectors-bar">
  <span class="sectors-label">Sectors</span>
  {sector_pills}
</div>
<div class="controls">
  <input type="search" id="searchBox" placeholder="Search ticker, company, headline..." oninput="filterTable()">
  <select id="sectorFilter" onchange="filterTable()">
    <option value="">All Sectors</option>
    {''.join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in sorted(sector_counts))}
  </select>
  <select id="sortSelect" onchange="sortTable()">
    <option value="time">Time (newest first)</option>
    <option value="mktcap">Market Cap (largest first)</option>
    <option value="ticker">Ticker A–Z</option>
    <option value="chg">Price Change</option>
  </select>
  <span class="count" id="countLabel">{total} announcements</span>
</div>
<table id="mainTable">
<thead>
  <tr>
    <th onclick="colSort('ticker')">Ticker</th>
    <th onclick="colSort('company')">Company</th>
    <th onclick="colSort('mktcap')">Mkt Cap</th>
    <th onclick="colSort('sector')">Sector</th>
    <th onclick="colSort('price')">Price</th>
    <th>Announcement</th>
    <th onclick="colSort('time')">Time</th>
  </tr>
</thead>
<tbody id="tableBody">
{rows_html}
</tbody>
</table>
<footer>Data sourced from Market Index (announcements) and Yahoo Finance (market data). Price sensitive announcements only. Not financial advice. Report generated {time_str} &nbsp;·&nbsp; {date_str}</footer>
<script>
function filterTable(){{
  const q=document.getElementById('searchBox').value.toLowerCase();
  const s=document.getElementById('sectorFilter').value.toLowerCase();
  let vis=0;
  document.querySelectorAll('#tableBody tr').forEach(r=>{{
    const t=r.textContent.toLowerCase();
    const sec=r.querySelector('.sector-badge')?.textContent.toLowerCase()||'';
    const show=t.includes(q)&&(!s||sec.includes(s));
    r.classList.toggle('hidden',!show);
    if(show)vis++;
  }});
  document.getElementById('countLabel').textContent=vis+' announcements';
  document.getElementById('visCount').textContent=vis;
}}
function sortTable(){{}}
function colSort(col){{}}
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(f"ASX Enriched Announcements — {TODAY_STR}")
    print("=" * 60)

    announcements = fetch_announcements()
    tickers = list({a["ticker"] for a in announcements if a["ticker"] != "–"})
    print(f"  → {len(tickers)} unique tickers: {', '.join(sorted(tickers)[:10])}{'...' if len(tickers)>10 else ''}")

    market_data = fetch_yahoo_data(tickers)

    generated_at = datetime.now(AEST)
    print(f"\n[{now_str()}] Building HTML report...")
    html = build_html(announcements, market_data, generated_at)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"  → Report saved to {REPORT_PATH.resolve()}")
    print(f"\n✓ Done — {len(announcements)} announcements, {len(market_data)} enriched")
    print("  Open report.html in your browser to view.")
