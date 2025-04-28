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

# Amazon ASIN Scraper as a Flask app
# Caching setup (1h)
requests_cache.install_cache(
    "amazon_cache",
    backend="sqlite",
    expire_after=3600,
    allowable_methods=("GET",),
    allowable_codes=(200,304),
)

# 4. Headers pool for rotation (same as Colab)
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

# fixed rate
DOLLAR_RATE = 87.0  # INR per USD
app = Flask(__name__)

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
    if not ws: return 1
    m = re.match(r"([\d\.]+)", ws.replace("\u200e", ""))
    if not m: return 1
    val = float(m.group(1))
    wsl = ws.lower()
    if "ounce" in wsl: lbs = val/16
    elif "pound" in wsl: lbs = val
    elif any(x in wsl for x in ["kilogram","kilo","kg"]): lbs = val*2.20462
    elif "gram" in wsl: lbs = (val/1000)*2.20462
    else: return 1
    return max(round(lbs),1)

def psych_price(v):
    x = math.ceil(v)
    candidates = []
    for unit in [10,100,1000]:
        base=(x//unit)*unit; c=base+(unit-1)
        if c<x: c+=unit
        candidates.append(c)
    return min(candidates)

# compute tiers same as Colab
def compute_tiers(usd, weight_lbs):
    inr_cost = usd * DOLLAR_RATE
    prod     = inr_cost * 1.2
    ship     = weight_lbs * 5 * DOLLAR_RATE
    dom      = weight_lbs * 200
    total    = prod + ship + dom
    fee      = total * 0.05
    cost_gst = (total + fee) * 1.18
    return {
        '5%':  cost_gst * 1.05,
        '10%': cost_gst * 1.10,
        '15%': cost_gst * 1.15,
        '20%': cost_gst * 1.20,
        '25%': cost_gst * 1.25,
    }

# pick ideal same as Colab
def pick_ideal(tiers, inr_price):
    numeric = {k:v for k,v in tiers.items() if v is not None}
    if not numeric: return None
    if inr_price:
        valid = {k:v for k,v in numeric.items() if v <= inr_price}
        choice = valid[max(valid, key=lambda k: float(k.strip('%')))] if valid else numeric['5%']
    else:
        choice = numeric['25%']
    return psych_price(choice)

# scraping logic
def scrape_asins(asins):
    results = []
    for asin in [a.strip() for a in asins if a.strip()]:
        time.sleep(random.uniform(5,6))  # polite delay
        url_com = f"https://www.amazon.com/dp/{asin}"
        url_in  = f"https://www.amazon.in/dp/{asin}"

        html_com = get_html(url_com)
        html_in  = get_html(url_in)

        # Amazon.com price
        pc=None
        if html_com:
            soup=BeautifulSoup(html_com,'html.parser')
            core=soup.select_one("#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative")
            pc=core.select_one("span.aok-offscreen").get_text(strip=True).split(" with")[0] if core and core.select_one("span.aok-offscreen") else None

        # weight
        wt_str=None; db=None
        if html_com:
            soup=BeautifulSoup(html_com,'html.parser')
            for th in soup.find_all('th'):
                if 'item weight' in th.get_text(strip=True).lower():
                    td=th.find_next_sibling('td'); wt_str=td.get_text(strip=True) if td else None; break
            if not wt_str:
                db=soup.select_one('#detailBullets_feature_div')
                if db:
                    for li in db.find_all('li'):
                        txt=li.get_text(' ',strip=True).lower()
                        if 'item weight' in txt:
                            parts=txt.split(':'); wt_str=parts[1].strip() if len(parts)>1 else None; break
        weight_lbs=parse_weight_lbs(wt_str)

        # dimensions
        dim_str=None
        if html_com:
            soup=BeautifulSoup(html_com,'html.parser')
            for th in soup.find_all('th'):
                if 'dimensions' in th.get_text(strip=True).lower():
                    td=th.find_next_sibling('td'); dim_str=td.get_text(strip=True) if td else None; break
            if not dim_str and db:
                for li in db.find_all('li'):
                    txt=li.get_text(' ',strip=True).lower()
                    if 'dimensions' in txt:
                        parts=txt.split(':'); dim_str=parts[1].strip() if len(parts)>1 else None; break
        dim_weight=0
        if dim_str:
            nums=re.findall(r'[\d\.]+',dim_str)
            if len(nums)>=3:
                l,b,h=map(float,nums[:3]); dim_weight=(l*b*h)/139
        dim_weight=round(dim_weight,2)

        # Amazon.in price
        pi=None
        if html_in:
            soup=BeautifulSoup(html_in,'html.parser')
            core=soup.select_one("#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative")
            pi=core.select_one("span.aok-offscreen").get_text(strip=True).split(" with")[0] if core and core.select_one("span.aok-offscreen") else None

        # compute tiers
        usd=parse_price_usd(pc)
        inr=parse_price_inr(pi)
        used_wt=max(weight_lbs,dim_weight)
        tiers=compute_tiers(usd,used_wt) if usd else {k:None for k in ['5%','10%','15%','20%','25%']}
        ideal=pick_ideal(tiers,inr)

        results.append({
            'ASIN':asin,
            'Amazon.com Price (USD)':pc or 'N/A',
            'Amazon.com Weight (lbs)':weight_lbs,
            'Dimensions':dim_str or 'N/A',
            'Dim Weight (lbs)':dim_weight,
            **{f"{k} Profit (INR)":(f"₹{tiers[k]:.2f}" if tiers[k] else 'N/A') for k in tiers},
            'Amazon.in Price (INR)':pi or 'N/A',
            'Ideal Price (INR)':f"₹{ideal}" if ideal else 'N/A'
        })
    return results

# allow iframe
@app.after_request
 def allow_iframe(response):
    response.headers['X-Frame-Options']='ALLOWALL'
    return response

# route
@app.route('/',methods=['GET'])
def index():
    asin=request.args.get('asin','').strip()
    data=scrape_asins([asin]) if asin else []
    return render_template_string("""
<!doctype html>
<html><head><title>ASIN Scraper</title>
<style>
  body{font-family:Arial,sans-serif;margin:20px}
  form{margin-bottom:20px}
  input,button{padding:8px;font-size:1em}
  table{width:100%;border-collapse:collapse}
  th,td{border:1px solid #ccc;padding:8px;text-align:left}
  th{background:#f4f4f4}
  tr:nth-child(even){background:#fafafa}
</style></head><body>
  <h1>Amazon ASIN Scraper</h1>
  <form method="get">ASIN:<input name="asin" value="{{asin}}" placeholder="B08..."/> <button>Scrape</button></form>
  {% if data %}
    <table>
      <tr>{% for h in data[0].keys() %}<th>{{h}}</th>{% endfor %}</tr>
      {% for row in data %}
      <tr>{% for v in row.values() %}<td>{{v}}</td>{% endfor %}</tr>
      {% endfor %}
    </table>
  {% endif %}
</body></html>
""",asin=asin,data=data)

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
