import os
import time
import random
import re
import math
import requests
import requests_cache
import pandas as pd
from flask import Flask, request, render_template_string
from bs4 import BeautifulSoup

# Configure caching
requests_cache.install_cache("amazon_cache", backend="sqlite", expire_after=3600)

# Rotate User-Agents
HEADERS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4)...",
    "Mozilla/5.0 (X11; Linux x86_64)...",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)...",
]

DOLLAR_RATE = 87.0

app = Flask(__name__)

def get_html(url):
    headers = {"User-Agent": random.choice(HEADERS)}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.content
    except:
        return None

# Amazon ASIN Scraper: Direct HTTP Fetch with Caching & Best-Practice Tips (Colab-Ready)

# 1. Install required libraries
!pip install -q requests beautifulsoup4 pandas requests_cache

# 2. Imports
import time, random, re, math
import requests
import requests_cache
import pandas as pd
from bs4 import BeautifulSoup
from IPython.display import display

# 3. Configure cache (avoid repeated fetches)
requests_cache.install_cache(
    "amazon_cache",
    backend="sqlite",
    expire_after=3600,             # cache pages for 1 hour
    allowable_methods=("GET",),
    allowable_codes=(200,304),
)

# 4. Headers pool for rotation
HEADERS_LIST = [
    {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.google.com/"
    }
    for ua, lang in [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36", "en-US,en;q=0.9"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15", "en-US,en;q=0.9"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36", "en-US,en;q=0.9"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", "en-US,en;q=0.9"),
    ]
]

# 5. Fixed dollar rate
DOLLAR_RATE = 87.0  # INR per USD

# 6. Helper to fetch HTML via direct GET with header rotation
def get_html(url):
    headers = random.choice(HEADERS_LIST)
    try:
        resp = requests.get(url, headers=headers, timeout=(5,15))
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None

# 7. Parse helpers
def parse_price_usd(s):
    return float(s.replace("$", "").replace(",", "")) if s and s.startswith("$") else None

def parse_price_inr(s):
    return float(s.replace("₹", "").replace(",", "")) if s and s.startswith("₹") else None

def parse_weight_lbs(ws):
    # Return weight in pounds; if missing, default to 1
    if not ws:
        return 1.0
    m = re.match(r"([\d\.]+)", ws.replace("\u200e", ""))
    if not m:
        return 1.0
    val = float(m.group(1))
    wsl = ws.lower()
    if "ounce" in wsl:
        lbs = val / 16
    elif "pound" in wsl:
        lbs = val
    elif any(x in wsl for x in ["kilogram", "kilo", "kg"]):
        lbs = val * 2.20462
    elif "gram" in wsl:
        lbs = (val / 1000) * 2.20462
    else:
        return 1.0
    return lbs  # no rounding


def psych_price(v):
    x = math.ceil(v)
    candidates = []
    for unit in [10, 100, 1000]:
        base = (x // unit) * unit
        c = base + (unit - 1)
        if c < x:
            c += unit
        candidates.append(c)
    return min(candidates)

# 8. Main scraping & calculation
def scrape_asins(asins):
    # Print header once
    header = [
        "ASIN", "Amazon.com Price (USD)", "Amazon.com Weight (lbs)",
        "Dimensions", "Dim Weight (lbs)",
        "5% Profit Price (INR)", "10% Profit Price (INR)",
        "15% Profit Price (INR)", "20% Profit Price (INR)", "25% Profit Price (INR)",
        "Amazon.in Price (INR)", "Ideal Price (INR)"
    ]
    print("\t".join(header))

    records = []
    for asin in asins:
        time.sleep(random.uniform(1, 5))  # polite delay
        url_com = f"https://www.amazon.com/dp/{asin}"
        url_in = f"https://www.amazon.in/dp/{asin}"

        html_com = get_html(url_com)
        html_in = get_html(url_in)

        # Amazon.com price
        pc = None
        if html_com:
            soup = BeautifulSoup(html_com, "html.parser")
            core = soup.select_one(
                "#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative"
            )
            if core:
                sp = core.select_one("span.aok-offscreen")
                pc = sp.get_text(strip=True).split(" with")[0] if sp else None

        # Amazon.com weight
        wt_str = None
        db = None
        if html_com:
            soup = BeautifulSoup(html_com, "html.parser")
            for th in soup.find_all("th"):
                if "item weight" in th.get_text(strip=True).lower():
                    td = th.find_next_sibling("td")
                    wt_str = td.get_text(strip=True) if td else None
                    break
            if not wt_str:
                db = soup.select_one("#detailBullets_feature_div")
                if db:
                    for li in db.find_all("li"):
                        txt = li.get_text(" ", strip=True).lower()
                        if "item weight" in txt:
                            parts = txt.split(":")
                            wt_str = parts[1].strip() if len(parts) > 1 else None
                            break
        weight_lbs = parse_weight_lbs(wt_str)

        # Amazon.com dimensions
        dim_str = None
        if html_com:
            soup = BeautifulSoup(html_com, "html.parser")
            for th in soup.find_all("th"):
                if "dimensions" in th.get_text(strip=True).lower():
                    td = th.find_next_sibling("td")
                    dim_str = td.get_text(strip=True) if td else None
                    break
            if not dim_str and db:
                for li in db.find_all("li"):
                    txt = li.get_text(" ", strip=True).lower()
                    if "dimensions" in txt:
                        parts = txt.split(":")
                        dim_str = parts[1].strip() if len(parts) > 1 else None
                        break
        # calculate dimensional weight
        dim_weight = 0.0
        if dim_str:
            nums = re.findall(r"[\d\.]+", dim_str)
            if len(nums) >= 3:
                l, b, h = map(float, nums[:3])
                dim_weight = round((l * b * h) / 139, 2)

        # Amazon.in price
        pi = None
        if html_in:
            soup = BeautifulSoup(html_in, "html.parser")
            core = soup.select_one(
                "#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative"
            )
            if core:
                sp = core.select_one("span.aok-offscreen")
                pi = sp.get_text(strip=True).split(" with")[0] if sp else None

        disp_com = pc or "Price not available"
        disp_in = pi or "Price not available"
        usd = parse_price_usd(pc)
        inr = parse_price_inr(pi)
        used_weight = max(weight_lbs, dim_weight)

        # profit tiers & ideal
        p5 = p10 = p15 = p20 = p25 = ideal = None
        if usd and used_weight:
            cost_inr = usd * DOLLAR_RATE
            prod = cost_inr * 1.2
            ship = used_weight * 5 * DOLLAR_RATE
            dom = used_weight * 200
            total = prod + ship + dom
            fee = total * 0.05
            gstcost = (total + fee) * 1.18

            p5 = gstcost * 1.05
            p10 = gstcost * 1.10
            p15 = gstcost * 1.15
            p20 = gstcost * 1.20
            p25 = gstcost * 1.25

            if inr:
                for tier in (p25, p20, p15, p10, p5):
                    if inr >= tier:
                        raw = tier
                        break
                else:
                    raw = p5
            else:
                raw = p25

            ideal = psych_price(raw)

        # Print row immediately
        row = [
            asin, disp_com, f"{weight_lbs}", dim_str or "N/A", f"{dim_weight}",
            f"{round(p5,2) if p5 else ''}", f"{round(p10,2) if p10 else ''}",
            f"{round(p15,2) if p15 else ''}", f"{round(p20,2) if p20 else ''}", f"{round(p25,2) if p25 else ''}",
            disp_in, f"{ideal if ideal else ''}"
        ]
        print("\t".join(row))
        records.append({
            "ASIN": asin,
            "Amazon.com Price (USD)": disp_com,
            "Amazon.com Weight (lbs)": weight_lbs,
            "Dimensions": dim_str or "N/A",
            "Dim Weight (lbs)": dim_weight,
            "5% Profit Price (INR)": round(p5,2) if p5 else None,
            "10% Profit Price (INR)": round(p10,2) if p10 else None,
            "15% Profit Price (INR)": round(p15,2) if p15 else None,
            "20% Profit Price (INR)": round(p20,2) if p20 else None,
            "25% Profit Price (INR)": round(p25,2) if p25 else None,
            "Amazon.in Price (INR)": disp_in,
            "Ideal Price (INR)": ideal
        })

    # Save all at end
    df = pd.DataFrame(records)
    df.to_csv("asin_full_data_with_profit.csv", index=False)
    print("✅ Saved to asin_full_data_with_profit.csv")

# 9. Input ASINs
asins_input = input("Enter ASINs separated by commas: ")
asins = [a.strip() for a in asins_input.split(",") if a.strip()]

# 10. Run
scrape_asins(asins)


@app.route("/", methods=["GET"])
def index():
    asin = request.args.get("asin", "").strip()
    results = []
    if asin:
        results = scrape_asins([asin]).to_dict(orient="records")
    # simple HTML template that shows the input box + table
    return render_template_string("""
    <!doctype html>
    <html>
      <head><title>ASIN Scraper</title></head>
      <body>
        <form method="get">
          ASIN: <input name="asin" value="{{ request.args.asin or '' }}">
          <button type="submit">Scrape</button>
        </form>
        {% if results %}
          <table border="1" cellpadding="5" style="border-collapse:collapse">
            <tr>
              {% for h in results[0].keys() %}<th>{{ h }}</th>{% endfor %}
            </tr>
            {% for row in results %}
              <tr>
                {% for v in row.values() %}<td>{{ v }}</td>{% endfor %}
              </tr>
            {% endfor %}
          </table>
        {% endif %}
      </body>
    </html>
    """, results=results)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
 
