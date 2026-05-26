import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from openai import OpenAI
import anthropic

OPENAI_KEY = st.secrets["OPENAI_KEY"]
CLAUDE_KEY = st.secrets["CLAUDE_KEY"]
st.title("🎙️ 小宇宙播客 AI 助手")

def get_audio_url(episode_url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    r = requests.get(episode_url, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')
    script = soup.find('script', {'id': '__NEXT_DATA__'})
    data = json.loads(script.string)
    ep = data['props']['pageProps']['episode']
    return ep['enclosure']['url'], ep.get('title', '未知标题')

def download_and_compress(audio_url):
    r = requests.get(audio_url, stream=True, timeout=120)
    total = int(r.headers.get('content-length', 0))
    downloaded = 0
    bar = st.progress(0, text="下载音频中...")
    with open("episode.m4a", 'wb') as f:
        for chunk in r.iter_content(chunk_size=512 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                bar.progress(min(downloaded / total, 1.0),
                             text=f"下载中 {downloaded // 1024 // 1024} / {total // 1024 // 1024} MB")
    bar.progress(1.0, text="压缩音频中...")
    subprocess.run([
        "ffmpeg", "-y", "-i", "episode.m4a",
        "-ac", "1", "-ar", "16000", "-b:a", "16k", "episode_small.mp3"
    ], capture_output=True)
    bar.empty()
    return "episode_small.mp3"

def _transcribe_segment(seg_path, client):
    with open(seg_path, "rb") as f:
        return client.audio.transcriptions.create(model="whisper-1", file=f, language="zh").text

def transcribe(audio_file):
    client = OpenAI(api_key=OPENAI_KEY)
    file_size = os.path.getsize(audio_file) / 1024 / 1024
    if file_size <= 20:
        with open(audio_file, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f, language="zh")
        return response.text

    segment_duration = 15 * 60
    os.makedirs("segments", exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file,
        "-f", "segment", "-segment_time", str(segment_duration),
        "-c", "copy", "segments/seg%03d.mp3"
    ], capture_output=True)
    segments = sorted(os.listdir("segments"))
    n = len(segments)

    progress = st.progress(0, text=f"并行转录 {n} 个片段...")
    results = {}
    with ThreadPoolExecutor(max_workers=min(n, 5)) as executor:
        future_to_idx = {
            executor.submit(_transcribe_segment, f"segments/{seg}", client): i
            for i, seg in enumerate(segments)
        }
        completed = 0
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            results[i] = future.result()
            completed += 1
            progress.progress(completed / n, text=f"已完成 {completed}/{n} 段")
    progress.empty()
    return "\n".join(results[i] for i in range(n))

MAX_TRANSCRIPT_CHARS = 80000

def _claude_client():
    return anthropic.Anthropic(api_key=CLAUDE_KEY)

def stream_summary(transcript):
    text = transcript[:MAX_TRANSCRIPT_CHARS]
    with _claude_client().messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"播客内容：\n{text}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": """请对以上播客内容生成思维导图格式的总结。
要求：使用 Markdown 标题层级来表示思维导图结构：
- 用一个 # 标题作为中心主题（播客核心话题，尽量简短）
- 用 ## 标题作为主要分支（如：核心观点、主要话题、具体建议、关键结论等）
- 用 ### 标题和 - 列表作为细节内容
只输出 Markdown 内容，不要添加任何解释或说明文字。"""},
        ]}]
    ) as stream:
        yield from stream.text_stream

def get_quotes(transcript):
    text = transcript[:MAX_TRANSCRIPT_CHARS]
    response = _claude_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"播客内容：\n{text}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": """请从以上播客文字稿中，挑选 5 条最有价值的观点或金句，要求：
1. 完整保留说话人的原始表达，逐字引用，不改写、不润色
2. 每条控制在 1-3 句话以内
3. 按价值从高到低排列
4. 直接以如下格式输出，不要额外说明：

> 原文1

> 原文2

> 原文3

> 原文4

> 原文5"""},
        ]}]
    )
    return response.content[0].text

def ask_question(transcript, question):
    text = transcript[:MAX_TRANSCRIPT_CHARS]
    response = _claude_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"播客内容：\n{text}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"基于以上播客内容回答问题，没涉及可结合实际补充。\n\n问题：{question}"},
        ]}]
    )
    return response.content[0].text

def render_markmap(markdown_text):
    # Prevent </script> inside the template tag from breaking HTML parsing
    safe_md = markdown_text.replace("</script>", "<\\/script>")
    html = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ margin: 0; padding: 0; background: transparent; }}
    svg.markmap {{ width: 100%; height: 500px; }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.17"></script>
</head>
<body>
  <div class="markmap">
    <script type="text/template">
{safe_md}
    </script>
  </div>
</body>
</html>"""
    components.html(html, height=520, scrolling=False)

# 初始化 session state
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "summary" not in st.session_state:
    st.session_state.summary = ""
if "quotes" not in st.session_state:
    st.session_state.quotes = ""
if "messages" not in st.session_state:
    st.session_state.messages = []
if "title" not in st.session_state:
    st.session_state.title = ""

# 输入链接
url = st.text_input("粘贴小宇宙播客链接：")

if st.button("开始处理") and url:
    with st.spinner("解析链接..."):
        audio_url, title = get_audio_url(url)
        st.session_state.title = title
        st.write(f"**标题：** {title}")

    with st.spinner("下载并压缩音频..."):
        audio_file = download_and_compress(audio_url)

    with st.spinner("转录中，请稍等..."):
        transcript = transcribe(audio_file)
        st.session_state.transcript = transcript
        st.write(f"转录完成：{len(transcript)} 字")

    # 金句在后台线程并行获取
    quotes_result = [None]
    def _fetch_quotes():
        quotes_result[0] = get_quotes(transcript)
    quotes_thread = threading.Thread(target=_fetch_quotes)
    quotes_thread.start()

    # 思维导图流式输出，边生成边显示
    st.write("**生成思维导图中...**")
    summary_box = st.empty()
    summary = ""
    for chunk in stream_summary(transcript):
        summary += chunk
        summary_box.markdown(summary)
    st.session_state.summary = summary
    summary_box.empty()

    # 等待金句完成
    with st.spinner("提取金句中..."):
        quotes_thread.join()
    st.session_state.quotes = quotes_result[0]

# 显示思维导图
if st.session_state.summary:
    st.subheader(f"🗺️ 思维导图：{st.session_state.title}")
    render_markmap(st.session_state.summary)
    st.divider()

# 显示原话摘录
if st.session_state.quotes:
    st.subheader("✏️ 精华原话摘录")
    st.markdown(st.session_state.quotes)
    st.divider()

# 问答
if st.session_state.summary:
    st.subheader("💬 问答")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    question = st.chat_input("根据播客内容提问...")
    if question and st.session_state.transcript:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                answer = ask_question(st.session_state.transcript, question)
            st.write(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
