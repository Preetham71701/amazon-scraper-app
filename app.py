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

# Enable caching of requests
requests_cache.install_cache("amazon_cache", backend="sqlite", expire_after=3600)

# Rotate User-Agents to reduce detection risk
HEADERS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
]

# CSS selector for both Amazon.com and Amazon.in price
PRICE_SEL = (
    "#corePriceDisplay_desktop_feature_div > div.a-section.a-spacing-none.aok-align-center.aok-relative"
    " > span.aok-offscreen"
)

DOLLAR_RATE = 87.0  # INR per USD
app = Flask(__name__)

# Helper to fetch HTML with rotating headers
def get_html(url):
    headers = {"User-Agent": random.choice(HEADERS)}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.content
    except:
        return None

# Scraping logic for ASINs
def scrape_asins(asins):
    records = []
    for asin in asins:
        time.sleep(random.uniform(1, 5))  # polite delay
        url_com = f"https://www.amazon.com/dp/{asin}"
        url_in = f"https://www.amazon.in/dp/{asin}"

        html_com = get_html(url_com)
        html_in = get_html(url_in)

        # Extract Amazon.com price
        price_usd = None
        if html_com:
            soup = BeautifulSoup(html_com, "html.parser")
            el = soup.select_one(PRICE_SEL)
            if el:
                price_usd = el.get_text(strip=True).split(" with")[0]

        # Extract Amazon.com weight
        weight_lbs = 1.0
        if html_com:
            soup = BeautifulSoup(html_com, "html.parser")
            for th in soup.find_all("th"):
                if "item weight" in th.get_text(strip=True).lower():
                    td = th.find_next_sibling("td")
                    text = td.get_text(strip=True) if td else None
                    if text:
                        m = re.match(r"([\d\.]+)", text.replace("\u200e", ""))
                        if m:
                            val = float(m.group(1))
                            if "ounce" in text.lower():
                                weight_lbs = val / 16
                            else:
                                weight_lbs = val
                    break

        # Extract dimensions & calculate dimensional weight
        dim_weight = 0.0
        dimensions = None
        if html_com:
            soup = BeautifulSoup(html_com, "html.parser")
            for th in soup.find_all("th"):
                if "dimensions" in th.get_text(strip=True).lower():
                    td = th.find_next_sibling("td")
                    dimensions = td.get_text(strip=True) if td else None
                    break
            if dimensions:
                nums = re.findall(r"[\d\.]+", dimensions)
                if len(nums) >= 3:
                    l, b, h = map(float, nums[:3])
                    dim_weight = (l * b * h) / 139

        # Extract Amazon.in price
        price_inr = None
        if html_in:
            soup = BeautifulSoup(html_in, "html.parser")
            el2 = soup.select_one(PRICE_SEL)
            if el2:
                price_inr = el2.get_text(strip=True).split(" with")[0]

        records.append({
            "ASIN": asin,
            "USD Price": price_usd or "N/A",
            "Weight (lbs)": weight_lbs,
            "Dimensions": dimensions or "N/A",
            "Dim Weight (lbs)": round(dim_weight, 2),
            "INR Price": price_inr or "N/A"
        })
    return records

# Allow embedding in iframes
@app.after_request
def allow_iframe(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    return response

# Flask route
@app.route('/', methods=['GET'])
def index():
    asin = request.args.get('asin', '')
    results = []
    if asin:
        results = scrape_asins([asin])
    return render_template_string(
        """
        <!doctype html>
        <html><body>
          <form method="get">
            ASIN: <input name="asin" value="{{ asin }}" />
            <button type="submit">Scrape</button>
          </form>
          {% if results %}
          <table border="1" cellpadding="5" style="border-collapse:collapse">
            <tr>{% for k in results[0].keys() %}<th>{{ k }}</th>{% endfor %}</tr>
            {% for row in results %}
            <tr>{% for v in row.values() %}<td>{{ v }}</td>{% endfor %}</tr>
            {% endfor %}
          </table>
          {% endif %}
        </body></html>
        """, asin=asin, results=results
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
