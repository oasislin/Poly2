import requests
import json
import re

url = "https://gamma-api.polymarket.com/events?closed=true&tag_id=84&order=end_date&ascending=false&limit=30"
response = requests.get(url)
if response.status_code == 200:
    events = response.json()
    for e in events:
        title = e.get("title", "")
        slug = e.get("slug", "")
        event_date = e.get("eventDate", "N/A")
        end_date = e.get("endDate", "N/A")
        print(f"Title: {title}\nSlug: {slug}\nEventDate: {event_date}\nEndDate: {end_date}\n" + "-"*40)
else:
    print(f"Error: {response.status_code}")
