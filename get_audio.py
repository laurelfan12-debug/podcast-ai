import requests
import json
from bs4 import BeautifulSoup

def get_audio_url(episode_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    r = requests.get(episode_url, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')
    script = soup.find('script', {'id': '__NEXT_DATA__'})
    data = json.loads(script.string)
    ep = data['props']['pageProps']['episode']
    return {
        "title": ep.get('title'),
        "duration_sec": ep.get('duration'),
        "audio_url": ep['enclosure']['url'],
    }

result = get_audio_url("https://www.xiaoyuzhoufm.com/episode/69e5d0661d989496e70ccc2e")
for k, v in result.items():
    print(f"{k}: {v}")