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
        return val/16
    if "pound" in wsl:
        return val
    if any(x in wsl for x in ["kilogram","kilo","kg"]):
        return val*2.20462
    if "gram" in wsl:
        return (val/1000)*2.20462
    return 1.0

def psych_price(v):
    x = math.ceil(v)
    cands = []
    for u in [10,100,1000]:
        base = (x//u)*u
        c = base + (u-1)
        if c < x: c += u
        cands.append(c)
    return min(cands)

def compute_tiers(usd, wt):
    cost = usd * DOLLAR_RATE
    prod = cost * 1.2
    ship = wt * 5 * DOLLAR_RATE
    dom = wt * 200
    total = prod + ship + dom
    fee = total * 0.05
    gst = (total + fee)*1.18
    return {
        '5%':  gst*1.05,
        '10%': gst*1.10,
        '15%': gst*1.15,
        '20%': gst*1.20,
        '25%': gst*1.25
    }

def pick_ideal(tiers, inr_price):
    nums = {k:v for k,v in tiers.items() if v}
    if not nums: return None
    if inr_price:
        valid = {k:v for k,v in nums.items() if v <= inr_price}
        choice = valid[max(valid, key=lambda k: float(k.strip('%')))] if valid else nums['5%']
    else:
        choice = nums['25%']
    return psych_price(choice)

# ----------------------
# Core Scraper
# ----------------------

def scrape_asin(asin):
    time.sleep(random.uniform(5,6))
    html_com = get_html(f"https://www.amazon.com/dp/{asin}")
    price_usd = None; wt_str = None; dims = None; dim_wt = 0.0
    if html_com:
        soup = BeautifulSoup(html_com, 'html.parser')
        el = soup.select_one(PRICE_SEL)
        text = el.get_text(strip=True) if el else None
        if not text:
            alt = soup.select_one("#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative")
            text = alt.get_text(strip=True) if alt else None
        if text:
            price_usd = parse_price_usd(text.split(' with')[0])
        for th in soup.find_all('th'):
            if 'item weight' in th.get_text(strip=True).lower():
                td = th.find_next_sibling('td'); wt_str = td.get_text(strip=True) if td else None; break
        if not wt_str:
            db = soup.select_one('#detailBullets_feature_div')
            if db:
                for li in db.find_all('li'):
                    tmp = li.get_text(' ',strip=True).lower()
                    if 'item weight' in tmp:
                        wt_str = tmp.split(':')[1].strip() if ':' in tmp else None; break
        for th in soup.find_all('th'):
            if 'dimensions' in th.get_text(strip=True).lower():
                td = th.find_next_sibling('td'); dims = td.get_text(strip=True) if td else None; break
        if not dims and db:
            for li in db.find_all('li'):
                tmp = li.get_text(' ',strip=True).lower()
                if 'dimensions' in tmp:
                    dims = tmp.split(':')[1].strip() if ':' in tmp else None; break
        if dims:
            nums = re.findall(r'[\d\.]+', dims)
            if len(nums)>=3:
                l,b,h = map(float, nums[:3]); dim_wt = (l*b*h)/139
    html_in = get_html(f"https://www.amazon.in/dp/{asin}")
    price_inr = None
    if html_in:
        soup = BeautifulSoup(html_in, 'html.parser')
        el2 = soup.select_one(PRICE_SEL)
        text2 = el2.get_text(strip=True) if el2 else None
        if not text2:
            alt2 = soup.select_one("#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative")
            text2 = alt2.get_text(strip=True) if alt2 else None
        if text2:
            price_inr = parse_price_inr(text2.split(' with')[0])
    wt_lbs = parse_weight_lbs(wt_str)
    used_wt = max(wt_lbs, dim_wt)
    tiers = compute_tiers(price_usd or 0, used_wt) if price_usd else {}
    ideal = pick_ideal(tiers, price_inr)
    return {
        'ASIN':asin,
        'Amazon.com Price (USD)':f"${price_usd:.2f}" if price_usd else 'N/A',
        'Amazon.com Weight (lbs)':f"{wt_lbs:.2f}" ,
        'Dimensions':dims or 'N/A',
        'Dim Weight (lbs)':f"{dim_wt:.2f}",
        **{f"{k} Profit (INR)":f"₹{tiers[k]:.2f}" for k in tiers},
        'Amazon.in Price (INR)':f"₹{price_inr:.2f}" if price_inr else 'N/A',
        'Ideal Price (INR)':f"₹{ideal}" if ideal else 'N/A'
    }

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
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f0f2f5; }
    .container { max-width: 1000px; margin: 40px auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    h1 { text-align: center; color: #333; }
    form { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin: 20px 0; }
    input[name=asin] { padding: 10px; font-size: 16px; border-radius: 4px; border: 1px solid #ccc; width: 260px; }
    button { padding: 10px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
    button:hover { background: #0056b3; }
    .loader { display: none; margin: 10px auto; border: 6px solid #f3f3f3; border-top: 6px solid #0073e6; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; }
    @keyframes spin { 100% { transform: rotate(360deg); } }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    thead { background: #007bff; color: white; }
    th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
    tr:nth-child(even) { background: #f9f9f9; }

    @media screen and (max-width: 768px) {
      table, thead, tbody, th, td, tr { display: block; }
      thead { display: none; }
      tr { margin-bottom: 15px; background: #fff; border: 1px solid #ccc; border-radius: 6px; padding: 10px; }
      td {
        position: relative;
        padding-left: 50%;
        border: none;
        border-bottom: 1px solid #eee;
        white-space: normal;
        word-break: break-word;
      }
      td::before {
        content: attr(data-label);
        position: absolute;
        left: 10px;
        top: 10px;
        width: 45%;
        padding-right: 10px;
        font-weight: bold;
        white-space: normal;
        word-break: break-word;
        overflow-wrap: break-word;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Amazon ASIN Scraper</h1>
    <form method="get" onsubmit="showLoader()">
      <input name="asin" placeholder="Enter ASIN (e.g. B08...)" value="{{ asin }}" />
      <button type="submit">Scrape</button>
      <button type="button" onclick="window.location.href='/?clear=1'">Clear</button>
    </form>
    <div class="loader" id="loader"></div>
    <table>
      <thead><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead>
      <tbody>
        {% for row in results %}
        <tr>{% for h in headers %}<td data-label="{{ h }}">{{ row[h] }}</td>{% endfor %}</tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <script>
    function showLoader() {
      document.getElementById('loader').style.display = 'block';
    }
  </script>
</body>
</html>
'''

@app.route('/', methods=['GET'])
def index():
    global all_results
    asin = request.args.get('asin', '').strip()
    if 'clear' in request.args:
        all_results = []
    elif asin:
        all_results.append(scrape_asin(asin))
    return render_template_string(TEMPLATE, asin=asin, results=all_results, headers=TABLE_HEADERS)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
