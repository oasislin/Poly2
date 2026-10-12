import requests
import json

def test_markets_resolution():
    slug = "highest-temperature-in-shanghai-on-july-14-2026"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    
    r = requests.get(url)
    if r.status_code == 200:
        event = r.json()[0]
        markets = event.get("markets", [])
        for m in markets:
            print(f"Market ID: {m.get('id')}")
            print(f"Question: {m.get('question')}")
            print(f"Closed: {m.get('closed')}")
            print(f"Outcome Prices: {m.get('outcomePrices')}")
            print(f"CLOB Tokens: {m.get('clobTokenIds')}")
            print("-" * 50)
    else:
        print(f"Error {r.status_code}: {r.text}")

if __name__ == "__main__":
    test_markets_resolution()
