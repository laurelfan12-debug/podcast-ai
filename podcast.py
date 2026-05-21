import requests
import json
import os
import subprocess
from bs4 import BeautifulSoup
from openai import OpenAI
import anthropic

OPENAI_KEY = "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"
CLAUDE_KEY = "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"


def get_audio_url(episode_url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    r = requests.get(episode_url, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')
    script = soup.find('script', {'id': '__NEXT_DATA__'})
    data = json.loads(script.string)
    ep = data['props']['pageProps']['episode']
    return ep['enclosure']['url'], ep.get('title', '未知标题')

def download_audio(audio_url, filename="episode.m4a"):
    print("下载音频...")
    r = requests.get(audio_url, stream=True, timeout=60)
    with open(filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            f.write(chunk)
    print(f"下载完成：{filename}")
    return filename

def compress_audio(input_file, output_file="episode_small.mp3"):
    print("压缩音频...")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_file,
        "-ac", "1", "-ar", "16000", "-b:a", "32k", output_file
    ], capture_output=True)
    size = os.path.getsize(output_file) / 1024 / 1024
    print(f"压缩完成：{size:.1f} MB")
    return output_file

def transcribe(audio_file):
    print("转录中，请稍等...")
    client = OpenAI(api_key=OPENAI_KEY)
    
    # 检查文件大小，超过20MB就分段
    file_size = os.path.getsize(audio_file) / 1024 / 1024
    
    if file_size <= 20:
        with open(audio_file, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1", file=f, language="zh"
            )
        print(f"转录完成：{len(response.text)} 字")
        return response.text
    
    # 分段处理
    print(f"文件 {file_size:.1f} MB，自动分段转录...")
    segment_duration = 15 * 60  # 每段15分钟
    segments_dir = "segments"
    os.makedirs(segments_dir, exist_ok=True)
    
    # 用ffmpeg切段
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file,
        "-f", "segment", "-segment_time", str(segment_duration),
        "-c", "copy", f"{segments_dir}/seg%03d.mp3"
    ], capture_output=True)
    
    # 逐段转录并合并
    segments = sorted(os.listdir(segments_dir))
    full_text = ""
    for i, seg in enumerate(segments):
        print(f"转录第 {i+1}/{len(segments)} 段...")
        seg_path = os.path.join(segments_dir, seg)
        with open(seg_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1", file=f, language="zh"
            )
        full_text += response.text + "\n"
    
    print(f"转录完成：{len(full_text)} 字")
    return full_text

def summarize_and_chat(transcript, title):
    client = anthropic.Anthropic(api_key=CLAUDE_KEY)
    print("生成总结...")
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": f"请对以下播客内容生成详细总结，包括：1.核心主题 2.主要观点 3.具体建议。\n\n播客内容：\n{transcript}"}]
    )
    summary = response.content[0].text
    print(f"\n=== 《{title}》总结 ===")
    print(summary)

    with open("summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)
    print("\n总结已保存到 summary.txt")

    print("\n=== 开始问答，输入 q 退出 ===\n")
    while True:
        question = input("你的问题：").strip()
        if question.lower() == "q":
            break
        if not question:
            continue
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            messages=[{"role": "user", "content": f"基于以下播客内容回答问题，没涉及可结合实际补充。\n\n播客内容：\n{transcript}\n\n问题：{question}"}]
        )
        print("\nAI回答：", response.content[0].text)
        print()

# 主流程
url = input("请粘贴小宇宙播客链接：").strip()
print("解析链接...")
audio_url, title = get_audio_url(url)
print(f"标题：{title}")

m4a = download_audio(audio_url)
mp3 = compress_audio(m4a)
transcript = transcribe(mp3)

with open("transcript.txt", "w", encoding="utf-8") as f:
    f.write(transcript)

summarize_and_chat(transcript, title)