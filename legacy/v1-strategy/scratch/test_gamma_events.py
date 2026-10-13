import requests

gamma_url = "https://gamma-api.polymarket.com"

# 测试 /events 接口的 end_date_min
p = {
    "closed": "true",
    "tag_id": "84",
    "limit": "100",
    "end_date_min": "2026-06-15T00:00:00Z"
}

try:
    response = requests.get(f"{gamma_url}/events", params=p, timeout=10)
    print("Status Code:", response.status_code)
    if response.status_code == 200:
        events = response.json()
        print(f"Total events returned: {len(events)}")
        for e in events:
            print("---")
            print("ID:", e.get("id"))
            print("Title:", e.get("title"))
            print("Slug:", e.get("slug"))
            print("Event Date:", e.get("eventDate"))
            print("End Date:", e.get("endDate"))
except Exception as e:
    print("Error:", e)
