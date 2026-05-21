import requests

audio_url = "https://media.xyzcdn.net/65539db173f6183e975cfccc/ll6WHuXqSYcpTJc4S5tvDHH9Y1P0.m4a"
output_file = "episode.m4a"

print("开始下载...")
r = requests.get(audio_url, stream=True, timeout=60)
total = int(r.headers.get('content-length', 0))
downloaded = 0

with open(output_file, 'wb') as f:
    for chunk in r.iter_content(chunk_size=1024*1024):
        f.write(chunk)
        downloaded += len(chunk)
        mb = downloaded / 1024 / 1024
        print(f"\r已下载 {mb:.1f} MB", end='', flush=True)

print(f"\n下载完成，文件：{output_file}")