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

# ----------------------
# Configuration & Setup
# ----------------------
requests_cache.install_cache(
    "amazon_cache", backend="sqlite", expire_after=3600,
    allowable_methods=("GET",), allowable_codes=(200,304)
)

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

DOLLAR_RATE = 87.0  # INR per USD
PRICE_SEL = (
    "#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative"
    " > span.aok-offscreen"
)

app = Flask(__name__)

# Global store for results
all_results = []

# ----------------------
# Scraping Helpers
# ----------------------

def get_html(url):
    headers = random.choice(HEADERS_LIST)
    try:
        r = requests.get(url, headers=headers, timeout=(5,15))
        if r.status_code == 200:
            return r.content
    except:
        pass
    return None


def parse_price_usd(s):
    try:
        return float(s.replace("$","").replace(",",""))
    except:
        return None


def parse_price_inr(s):
    try:
        return float(s.replace("₹","").replace(",",""))
    except:
        return None


def parse_weight_lbs(ws):
    if not ws: return 1.0
    m = re.match(r"([\d\.]+)", ws.replace("\u200e",""))
    if not m: return 1.0
    val = float(m.group(1))
    wsl = ws.lower()
    if "ounce" in wsl:
        lbs = val/16
    elif "pound" in wsl:
        lbs = val
    elif any(x in wsl for x in ["kilogram","kilo","kg"]):
        lbs = val*2.20462
    elif "gram" in wsl:
        lbs = (val/1000)*2.20462
    else:
        lbs = 1.0
    return lbs


def psych_price(v):
    x = math.ceil(v)
    candidates = []
    for unit in [10,100,1000]:
        base = (x//unit)*unit
        c = base + (unit-1)
        if c < x: c += unit
        candidates.append(c)
    return min(candidates)


def compute_tiers(usd, wt):
    cost = usd * DOLLAR_RATE
    prod = cost * 1.2
    ship = wt * 5 * DOLLAR_RATE
    dom = wt * 200
    total = prod + ship + dom
    fee = total * 0.05
    gst = (total + fee) * 1.18
    return {
        '5%':  gst*1.05,
        '10%': gst*1.10,
        '15%': gst*1.15,
        '20%': gst*1.20,
        '25%': gst*1.25
    }


def pick_ideal(tiers, inr_price):
    numeric = {k:v for k,v in tiers.items() if v}
    if not numeric:
        return None
    if inr_price:
        valid = {k:v for k,v in numeric.items() if v <= inr_price}
        choice = valid[max(valid, key=lambda k: float(k.strip('%')))] if valid else numeric['5%']
    else:
        choice = numeric['25%']
    return psych_price(choice)

# ----------------------
# Core Scraper
# ----------------------

def scrape_asin(asin):
    time.sleep(random.uniform(5,6))
    # .com
    html_com = get_html(f"https://www.amazon.com/dp/{asin}")
    price_usd = None; wt_str = None; dims = None; dim_wt = 0.0
    if html_com:
        soup = BeautifulSoup(html_com, 'html.parser')
        el = soup.select_one(PRICE_SEL)
        price_usd = parse_price_usd(el.get_text(strip=True).split(' with')[0]) if el else None
        # weight
        for th in soup.find_all('th'):
            if 'item weight' in th.get_text(strip=True).lower():
                td=th.find_next_sibling('td'); wt_str = td.get_text(strip=True) if td else None; break
        # fallback bullets
        if not wt_str:
            db = soup.select_one('#detailBullets_feature_div')
            if db:
                for li in db.find_all('li'):
                    txt=li.get_text(' ', strip=True).lower()
                    if 'item weight' in txt:
                        wt_str = txt.split(':')[1].strip() if ':' in txt else None
                        break
        # dimensions
        for th in soup.find_all('th'):
            if 'dimensions' in th.get_text(strip=True).lower():
                td=th.find_next_sibling('td'); dims=td.get_text(strip=True) if td else None; break
        if not dims and db:
            for li in db.find_all('li'):
                txt=li.get_text(' ', strip=True).lower()
                if 'dimensions' in txt:
                    parts=txt.split(':'); dims=parts[1].strip() if len(parts)>1 else None; break
        # dim weight
        if dims:
            nums = re.findall(r'[\d\.]+', dims)
            if len(nums)>=3:
                l,b,h = map(float, nums[:3]); dim_wt = (l*b*h)/139
    # .in
    html_in = get_html(f"https://www.amazon.in/dp/{asin}")
    price_inr = None
    if html_in:
        soup = BeautifulSoup(html_in, 'html.parser')
        el2 = soup.select_one(PRICE_SEL)
        price_inr = parse_price_inr(el2.get_text(strip=True).split(' with')[0]) if el2 else None

    wt_lbs = parse_weight_lbs(wt_str)
    used_wt = max(wt_lbs, dim_wt)
    tiers = compute_tiers(price_usd or 0, used_wt) if price_usd else {}
    ideal = pick_ideal(tiers, price_inr)
    return {
        'ASIN': asin,
        'Amazon.com Price (USD)': f"${price_usd:.2f}" if price_usd else 'N/A',
        'Amazon.com Weight (lbs)': f"{wt_lbs:.2f}",
        'Dimensions': dims or 'N/A',
        'Dim Weight (lbs)': f"{dim_wt:.2f}",
        **{f"{k} Profit (INR)": f"₹{tiers[k]:.2f}" for k in tiers},
        'Amazon.in Price (INR)': f"₹{price_inr:.2f}" if price_inr else 'N/A',
        'Ideal Price (INR)': f"₹{ideal}" if ideal else 'N/A'
    }

# ----------------------
# Flask Routes & Template
# ----------------------

@app.after_request
def allow_iframe(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    return response

TABLE_HEADERS = [
    'ASIN','Amazon.com Price (USD)','Amazon.com Weight (lbs)',
    'Dimensions','Dim Weight (lbs)',
    '5% Profit (INR)','10% Profit (INR)','15% Profit (INR)',
    '20% Profit (INR)','25% Profit (INR)',
    'Amazon.in Price (INR)','Ideal Price (INR)'
]

TEMPLATE = '''
<!doctype html>
<html>
<head>
  <title>Amazon ASIN Scraper</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 40px; background: #f9f9f9; }
    h1 { text-align: center; color: #333; }
    .container { max-width: 1000px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    form { display: flex; justify-content: center; margin-bottom: 20px; }
    input[name=asin] { padding: 10px; width: 250px; font-size: 1em; border: 1px solid #ccc; border-radius: 4px; }
    button { padding: 10px 16px; margin-left: 8px; font-size: 1em; color: #fff; background: #0073e6; border: none; border-radius: 4px; cursor: pointer; }
    button:hover { background: #005bb5; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
    th, td { border: 1px solid #ddd; padding: 12px; font-size: 0.95em; }
    th { background: #0073e6; color: #fff; position: sticky; top: 0; }
    tr:nth-child(even) { background: #f2f2f2; }
    tr:hover { background: #e6f7ff; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Amazon ASIN Scraper</h1>
    <form method="get">
      <input name="asin" placeholder="Enter ASIN (e.g. B08...)" value="{{ asin }}" />
      <button type="submit">Scrape</button>
    </form>
    <table>
      <thead><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead>
      <tbody>
        {% for row in results %}
          <tr>{% for h in headers %}<td>{{ row[h] }}</td>{% endfor %}</tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</body>
</html>
'''

@app.route('/', methods=['GET'])
def index():
    asin = request.args.get('asin', '').strip()
    if asin:
        new = scrape_asin(asin)
        all_results.append(new)
    return render_template_string(
        TEMPLATE,
        asin=asin,
        results=all_results,
        headers=TABLE_HEADERS
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
