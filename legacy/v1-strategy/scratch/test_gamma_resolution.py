import requests
import json

def test_gamma_resolution():
    slug = "highest-temperature-in-shanghai-on-july-14-2026"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    
    r = requests.get(url)
    if r.status_code == 200:
        events = r.json()
        print(json.dumps(events, indent=2, ensure_ascii=False))
    else:
        print(f"Error {r.status_code}: {r.text}")

if __name__ == "__main__":
    test_gamma_resolution()
