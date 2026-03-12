"""
ASX Price Sensitive Announcements — Daily Enriched Report
Uses the Markit Digital API that powers the official ASX announcements page.
Returns ALL ASX companies (not just ASX 200), with sector/industry built-in.
Enriches with Yahoo Finance for live price + market cap.
"""

import requests, time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    AEST = ZoneInfo("Australia/Sydney")
except ImportError:
    AEST = timezone(timedelta(hours=10))

TODAY       = date.today()
TODAY_STR   = TODAY.strftime("%Y-%m-%d")
REPORT_PATH = Path("report.html")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Accept-Language": "en-AU,en;q=0.9",
    "Origin": "https://www.asx.com.au",
    "Referer": "https://www.asx.com.au/",
}

# The real API powering asx.com.au/markets/trade-our-cash-market/announcements
MARKIT_BASE = "https://asx.api.markitdigital.com/asx-research/1.0/markets/announcements"
YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

ITEMS_PER_PAGE = 100  # max per request


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def fetch_all_price_sensitive():
    """
    Fetches today's price sensitive announcements using priceSensitiveOnly=true.
    The API returns announcements sorted newest-first across ALL time, so we
    page through until we hit items from yesterday (stopping early).
    summaryCounts.priceSensitive tells us how many to expect today.
    """
    print(f"\n[{now_str()}] Fetching price-sensitive announcements for {TODAY_STR}...")
    all_ps_items = []
    page         = 0
    expected_today = None

    while True:
        params = {
            "priceSensitiveOnly":  "true",
            "page":                page,
            "itemsPerPage":        ITEMS_PER_PAGE,
            "summaryCountsDate":   TODAY_STR,
        }
        try:
            r = requests.get(MARKIT_BASE, params=params, headers=HEADERS, timeout=30)
            print(f"  Page {page}: HTTP {r.status_code}")

            if r.status_code != 200:
                print(f"  → Non-200. Body: {r.text[:400]}")
                break

            data = r.json()
            top  = data.get("data", {})
            items = top.get("items", [])

            if page == 0:
                summary = top.get("summaryCounts", {})
                expected_today = summary.get("priceSensitive", 0)
                total_ever = top.get("count", "?")
                print(f"  → API: {total_ever} total ever, {expected_today} price sensitive TODAY")

            if not items:
                print(f"  → Empty page, done.")
                break

            # Items are newest-first; stop when we hit yesterday's announcements
            hit_old = False
            for item in items:
                item_date = item.get("date", "")[:10]  # "2026-03-12"
                if item_date == TODAY_STR:
                    all_ps_items.append(item)
                else:
                    print(f"  → Hit item from {item_date}, stopping pagination.")
                    hit_old = True
                    break

            today_on_page = sum(1 for i in items if i.get("date","")[:10] == TODAY_STR)
            print(f"  → Page {page}: {len(items)} items, {today_on_page} from today (running total: {len(all_ps_items)})")

            if hit_old:
                break
            if len(items) < ITEMS_PER_PAGE:
                print(f"  → Last page reached.")
                break
            if expected_today and len(all_ps_items) >= expected_today:
                print(f"  → Collected all {expected_today} expected announcements.")
                break

            page += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"  → Error on page {page}: {e}")
            break

    print(f"  ✓ {len(all_ps_items)} price sensitive announcements for {TODAY_STR} (expected {expected_today})")
    return all_ps_items


def parse_item(raw):
    """Normalise a Markit API item to a flat dict."""
    company_info = (raw.get("companyInfo") or [{}])[0]
    ticker   = raw.get("symbol") or "–"
    name     = company_info.get("displayName") or ticker
    sector   = company_info.get("sector") or "–"
    industry = company_info.get("industry") or "–"
    doc_key  = raw.get("documentKey","")
    pdf_url  = (
        raw.get("url")
        or (f"https://www.asx.com.au/asx/statistics/displayAnnouncement.do?display=pdf&idsId={doc_key}" if doc_key else "")
        or f"https://www.asx.com.au/markets/company/{ticker}"
    )
    return {
        "ticker":   ticker.upper().strip(),
        "name":     name,
        "sector":   sector,
        "industry": industry,
        "headline": raw.get("headline","Announcement"),
        "released": raw.get("date",""),
        "pdf_url":  pdf_url,
        "pages":    raw.get("fileSize",""),
    }


def fetch_yahoo_data(tickers):
    """Fetch live price + market cap from Yahoo Finance."""
    if not tickers:
        return {}
    result = {}
    print(f"\n[{now_str()}] Fetching Yahoo Finance data for {len(tickers)} tickers...")
    for i in range(0, len(tickers), 20):
        batch   = tickers[i:i+20]
        symbols = ",".join(f"{t}.AX" for t in batch)
        try:
            r = requests.get(YF_QUOTE_URL,
                params={"symbols": symbols,
                        "fields": "shortName,longName,regularMarketPrice,regularMarketChangePercent,marketCap"},
                headers=HEADERS, timeout=20)
            r.raise_for_status()
            for q in r.json().get("quoteResponse", {}).get("result", []):
                t = q.get("symbol","").replace(".AX","")
                result[t] = {
                    "mktcap":     q.get("marketCap"),
                    "price":      q.get("regularMarketPrice"),
                    "change_pct": q.get("regularMarketChangePercent"),
                }
        except Exception as e:
            print(f"  ✗ Yahoo batch {i//20+1} failed: {e}")
        time.sleep(0.3)
    print(f"  → Price data for {len(result)}/{len(tickers)} tickers")
    return result


# ── Formatting helpers ──────────────────────────────────────────────────────────
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
        dt   = datetime.fromisoformat(s.replace("Z","+00:00"))
        aest = dt.astimezone(timezone(timedelta(hours=10)))
        return aest.strftime("%-I:%M %p")
    except:
        return s[:16]

def esc(s):
    return (str(s or "")
        .replace("&","&amp;").replace("<","&lt;")
        .replace(">","&gt;").replace('"',"&quot;"))


# ── HTML builder ────────────────────────────────────────────────────────────────
def build_html(announcements, yahoo_data, generated_at):
    date_str = generated_at.strftime("%A %-d %B %Y")
    time_str = generated_at.strftime("%-I:%M %p AEST")
    total    = len(announcements)
    enriched = sum(1 for a in announcements if a["ticker"] in yahoo_data)

    sector_counts = {}
    for a in announcements:
        s = a.get("sector","Unknown") or "Unknown"
        sector_counts[s] = sector_counts.get(s,0) + 1

    sector_pills = "".join(
        f'<span class="sector-pill">{esc(s)} <strong>{c}</strong></span>'
        for s,c in sorted(sector_counts.items(), key=lambda x: -x[1])
    ) or '<span style="color:#7d8590">No announcements today</span>'

    rows_html = ""
    for a in sorted(announcements, key=lambda x: x.get("released",""), reverse=True):
        ticker = a["ticker"]
        yf     = yahoo_data.get(ticker, {})
        mc_str = fmt_mktcap(yf.get("mktcap"))
        tier   = mktcap_tier(yf.get("mktcap"))
        price  = yf.get("price")
        chg    = yf.get("change_pct")
        p_str  = f"A${price:.2f}" if price else "–"
        c_str  = f"{chg:+.2f}%" if chg is not None else ""
        c_cls  = "pos" if (chg or 0) >= 0 else "neg"
        sz     = a.get("pages","")

        rows_html += f"""
        <tr onclick="window.open('{esc(a['pdf_url'])}','_blank')">
          <td class="td-ticker">{esc(ticker)}</td>
          <td class="td-company">
            <div class="company-name">{esc(a['name'])}</div>
            <div class="company-industry">{esc(a['industry'])}</div>
          </td>
          <td><span class="mktcap {tier}">{mc_str}</span></td>
          <td><span class="sector-badge">{esc(a['sector'])}</span></td>
          <td class="td-price"><div>{p_str}</div><div class="chg {c_cls}">{c_str}</div></td>
          <td class="td-headline">
            <a href="{esc(a['pdf_url'])}" target="_blank" onclick="event.stopPropagation()">{esc(a['headline'])}</a>
            {f'<span class="pages">{esc(sz)}</span>' if sz else ""}
          </td>
          <td class="td-time">{fmt_time(a['released'])}</td>
        </tr>"""

    if not rows_html:
        rows_html = f'<tr><td colspan="7" class="empty">No price sensitive announcements found for {date_str}.<br><small>Run after 10am AEST on a trading day.</small></td></tr>'

    sector_options = "".join(
        f'<option value="{esc(s)}">{esc(s)}</option>'
        for s in sorted(sector_counts)
    )

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
header{{padding:20px 24px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px}}
h1{{font-size:22px;font-weight:700}}h1 span{{color:var(--accent)}}
.subtitle{{font-size:12px;color:var(--muted);margin-top:4px}}
.stats{{text-align:right;font-size:12px;color:var(--muted)}}
.stat-row{{display:flex;gap:20px;justify-content:flex-end;margin-top:4px}}
.stat-block{{text-align:center}}.stat-num{{font-size:20px;font-weight:700;color:var(--accent);display:block}}
.sectors-bar{{padding:10px 24px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.sectors-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;white-space:nowrap;margin-right:4px}}
.sector-pill{{background:#21262d;border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:12px;cursor:pointer}}
.sector-pill:hover{{border-color:var(--accent)}}.sector-pill strong{{color:var(--accent)}}
.controls{{padding:10px 24px;display:flex;gap:10px;align-items:center;border-bottom:1px solid var(--border);flex-wrap:wrap}}
input[type=search]{{flex:1;min-width:200px;background:#21262d;border:1px solid var(--border);border-radius:6px;color:var(--text);padding:7px 12px;font-size:13px;outline:none}}
input[type=search]:focus{{border-color:var(--accent)}}
select{{background:#21262d;border:1px solid var(--border);border-radius:6px;color:var(--text);padding:7px 10px;font-size:13px;outline:none}}
.count{{font-size:12px;color:var(--muted);white-space:nowrap}}
table{{width:100%;border-collapse:collapse}}
th{{background:var(--surface);border-bottom:2px solid var(--border);padding:10px 12px;text-align:left;
    font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);white-space:nowrap}}
td{{padding:10px 12px;border-bottom:1px solid #21262d;vertical-align:top}}
tr:hover td{{background:#161b22}}tr{{cursor:pointer}}
.td-ticker{{font-weight:700;color:var(--accent);font-size:13px;white-space:nowrap}}
.company-name{{font-weight:500;font-size:13px}}.company-industry{{font-size:11px;color:var(--muted)}}
.mktcap{{border-radius:4px;padding:2px 8px;font-size:12px;font-weight:600;white-space:nowrap;display:inline-block}}
.mktcap.large{{background:#f0883e22;color:#f0883e}}.mktcap.mid{{background:#58a6ff22;color:#58a6ff}}
.mktcap.small{{background:#3fb95022;color:#3fb950}}.mktcap.micro{{background:#7d859022;color:#7d8590}}
.sector-badge{{background:#21262d;border-radius:4px;padding:2px 8px;font-size:11px;white-space:nowrap;display:inline-block}}
.td-price{{white-space:nowrap;font-size:13px;min-width:70px}}
.chg.pos{{color:var(--green)}}.chg.neg{{color:var(--red)}}
.td-headline a{{color:var(--text);text-decoration:none;font-size:13px;line-height:1.4}}
.td-headline a:hover{{color:var(--accent);text-decoration:underline}}
.pages{{margin-left:6px;background:#21262d;border-radius:3px;padding:1px 5px;font-size:11px;color:var(--muted)}}
.td-time{{color:var(--muted);font-size:12px;white-space:nowrap}}
.empty{{text-align:center;padding:60px 20px;color:var(--muted);font-family:monospace;line-height:2}}
footer{{text-align:center;padding:20px;font-size:11px;color:var(--muted);border-top:1px solid var(--border);margin-top:20px}}
.hidden{{display:none!important}}
</style>
</head>
<body>
<header>
  <div>
    <h1><span>ASX</span> Price Sensitive Announcements</h1>
    <div class="subtitle">{date_str} &nbsp;·&nbsp; All ASX companies &nbsp;·&nbsp; Enriched with price &amp; market cap</div>
  </div>
  <div class="stats">
    <span>Generated {time_str}</span>
    <div class="stat-row">
      <div class="stat-block"><span class="stat-num" id="visCount">{total}</span>ANNOUNCEMENTS</div>
      <div class="stat-block"><span class="stat-num">{enriched}</span>WITH PRICE</div>
      <div class="stat-block"><span class="stat-num">{len(sector_counts)}</span>SECTORS</div>
    </div>
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
    {sector_options}
  </select>
  <span class="count" id="countLabel">{total} announcements</span>
</div>
<table>
<thead>
  <tr>
    <th>Ticker</th><th>Company</th><th>Mkt Cap</th>
    <th>Sector</th><th>Price</th><th>Announcement</th><th>Time AEST</th>
  </tr>
</thead>
<tbody id="tableBody">
{rows_html}
</tbody>
</table>
<footer>
  Data: ASX / Markit Digital (announcements + sector) · Yahoo Finance (price &amp; market cap) ·
  All ASX listed companies · Price sensitive only · Not financial advice · {time_str} · {date_str}
</footer>
<script>
function filterTable(){{
  const q  = document.getElementById('searchBox').value.toLowerCase();
  const sf = document.getElementById('sectorFilter').value.toLowerCase();
  let vis  = 0;
  document.querySelectorAll('#tableBody tr').forEach(r => {{
    const txt = r.textContent.toLowerCase();
    const sec = (r.querySelector('.sector-badge')||{{}}).textContent?.toLowerCase()||'';
    const show = txt.includes(q) && (!sf || sec.includes(sf));
    r.classList.toggle('hidden', !show);
    if (show) vis++;
  }});
  document.getElementById('countLabel').textContent = vis + ' announcements';
  document.getElementById('visCount').textContent   = vis;
}}
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(f"ASX Enriched Announcements — {TODAY_STR}")
    print("=" * 60)

    raw_items    = fetch_all_price_sensitive()
    announcements = [parse_item(r) for r in raw_items]

    tickers      = list({a["ticker"] for a in announcements if a["ticker"] != "–"})
    yahoo_data   = fetch_yahoo_data(tickers)
    generated_at = datetime.now(AEST)

    print(f"\n[{now_str()}] Building HTML report...")
    html = build_html(announcements, yahoo_data, generated_at)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"  → Report saved to {REPORT_PATH.resolve()}")
    print(f"\n✓ Done — {len(announcements)} announcements, {len(yahoo_data)} with price data")
    print("  Open report.html in your browser to view.")
