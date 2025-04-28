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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
]

# CSS selector for price
PRICE_SEL = (
    "#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative"
    " > span.aok-offscreen"
)

DOLLAR_RATE = 87.0  # INR per USD
app = Flask(__name__)

# Polite fetcher with rotating headers
def get_html(url):
    headers = {"User-Agent": random.choice(HEADERS)}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.content
    except:
        return None

# Compute profit tiers given USD price & weight (lbs)
def compute_tiers(usd, weight_lbs):
    inr_cost = usd * DOLLAR_RATE
    prod = inr_cost * 1.2
    ship = weight_lbs * 5 * DOLLAR_RATE
    dom = weight_lbs * 200
    total = prod + ship + dom
    fee = total * 0.05
    cost_gst = (total + fee) * 1.18
    return {
        '5%': cost_gst * 1.05,
        '10%': cost_gst * 1.10,
        '15%': cost_gst * 1.15,
        '20%': cost_gst * 1.20,
        '25%': cost_gst * 1.25
    }

# Pick ideal price tier based on INR price
def pick_ideal(tiers, inr_price):
    numeric = {k: v for k, v in tiers.items() if v is not None}
    if not numeric:
        return None
    if inr_price is not None and inr_price != 'N/A':
        valid = {k: v for k, v in numeric.items() if v <= inr_price}
        if valid:
            choice = valid[max(valid, key=lambda k: float(k.strip('%')))]
        else:
            choice = numeric['5%']
    else:
        choice = numeric['25%']
    x = math.ceil(choice)
    # psych price
    candidates = []
    for unit in (10, 100, 1000):
        base = (x // unit) * unit
        c = base + (unit - 1)
        if c < x:
            c += unit
        candidates.append(c)
    return min(candidates)

# Main scraping
def scrape_asins(asins):
    records = []
    for asin in asins:
        time.sleep(random.uniform(5, 6))  # polite delay (5–6s to avoid detection)
        url_com = f"https://www.amazon.com/dp/{asin}"
        url_in = f"https://www.amazon.in/dp/{asin}"

        html_com = get_html(url_com)
        html_in = get_html(url_in)

        # USD price
        usd_price = None
        if html_com:
            soup = BeautifulSoup(html_com, 'html.parser')
            el = soup.select_one(PRICE_SEL)
            if el:
                try:
                    usd_price = float(el.get_text().strip().replace('$','').split(' ')[0])
                except:
                    pass

        # Weight
        weight_lbs = 1.0
        dims = None
        dim_weight = 0.0
        if html_com:
            soup = BeautifulSoup(html_com, 'html.parser')
            db = None
            # weight
            for th in soup.find_all('th'):
                txt = th.get_text(strip=True).lower()
                if 'item weight' in txt:
                    td = th.find_next_sibling('td')
                    w = td.get_text(strip=True) if td else ''
                    m = re.match(r'([\d\.]+)', w.replace('\u200e',''))
                    if m:
                        val = float(m.group(1))
                        if 'ounce' in w.lower(): weight_lbs = val/16
                        else: weight_lbs = val
                    break
            # dimensions
            for th in soup.find_all('th'):
                txt = th.get_text(strip=True).lower()
                if 'dimensions' in txt:
                    td = th.find_next_sibling('td')
                    dims = td.get_text(strip=True) if td else None
                    break
            db = soup.select_one('#detailBullets_feature_div')
            if not dims and db:
                for li in db.find_all('li'):
                    txt = li.get_text(' ', strip=True).lower()
                    if 'dimensions' in txt:
                        parts = txt.split(':')
                        if len(parts)>1: dims = parts[1].strip()
                        break
            # dim weight
            if dims:
                nums = re.findall(r'[\d\.]+', dims)
                if len(nums)>=3:
                    l,b,h = map(float, nums[:3])
                    dim_weight = (l*b*h)/139

        # INR price
        inr_price = None
        if html_in:
            soup = BeautifulSoup(html_in, 'html.parser')
            el2 = soup.select_one(PRICE_SEL)
            if el2:
                try:
                    inr_price = float(el2.get_text().strip().replace('₹','').split(' ')[0])
                except:
                    pass

        used_weight = max(weight_lbs, dim_weight)
        tiers = compute_tiers(usd_price, used_weight) if usd_price else {k: None for k in ['5%','10%','15%','20%','25%']}
        ideal = pick_ideal(tiers, inr_price)

        record = {
            'ASIN': asin,
            'USD Price': f"${usd_price:.2f}" if usd_price else 'N/A',
            'Weight (lbs)': f"{weight_lbs:.2f}",
            'Dimensions': dims or 'N/A',
            'Dim Weight (lbs)': f"{dim_weight:.2f}",
            '5% Profit (INR)': f"₹{tiers['5%']:.2f}" if tiers['5%'] else 'N/A',
            '10% Profit (INR)': f"₹{tiers['10%']:.2f}" if tiers['10%'] else 'N/A',
            '15% Profit (INR)': f"₹{tiers['15%']:.2f}" if tiers['15%'] else 'N/A',
            '20% Profit (INR)': f"₹{tiers['20%']:.2f}" if tiers['20%'] else 'N/A',
            '25% Profit (INR)': f"₹{tiers['25%']:.2f}" if tiers['25%'] else 'N/A',
            'INR Price': f"₹{inr_price:.2f}" if inr_price else 'N/A',
            'Ideal Price (INR)': f"₹{ideal}" if ideal else 'N/A'
        }
        records.append(record)
    return records

# Allow embedding
@app.after_request
def allow_iframe(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    return response

# Flask route with styled template
def index():
    asin = request.args.get('asin','')
    results = scrape_asins([asin]) if asin else []
    return render_template_string("""
<!doctype html>
<html>
<head>
  <title>Amazon ASIN Scraper</title>
  <style>
    body { font-family: Arial, sans-serif; margin:20px; }
    form { margin-bottom:20px; }
    input[name=asin] { padding:8px; width:200px; font-size:1em; }
    button { padding:8px 12px; font-size:1em; }
    table { width:100%; border-collapse:collapse; margin-top:10px; }
    th, td { padding:10px; border:1px solid #ccc; text-align:left; }
    th { background:#f4f4f4; }
    tr:nth-child(even) { background:#fafafa; }
  </style>
</head>
<body>
  <h1>Amazon ASIN Scraper</h1>
  <form method="get">
    <label>ASIN: <input name="asin" value="{{asin}}" placeholder="e.g. B08K2GW2ZF"></label>
    <button type="submit">Scrape</button>
  </form>
  {% if results %}
    <table>
      <tr>{% for h in results[0].keys() %}<th>{{h}}</th>{% endfor %}</tr>
      {% for row in results %}
      <tr>{% for v in row.values() %}<td>{{v}}</td>{% endfor %}</tr>
      {% endfor %}
    </table>
  {% endif %}
</body>
</html>
""", asin=asin, results=results)

app.add_url_rule('/','index',index)

if __name__=='__main__':
    port = int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0',port=port)
