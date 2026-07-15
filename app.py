import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import os
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from openai import OpenAI
import anthropic

import db

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

def download_and_compress(audio_url, episode_id):
    # 临时文件名带 episode_id，避免并发处理互相覆盖
    src = f"episode_{episode_id}.m4a"
    dst = f"episode_{episode_id}_small.mp3"
    r = requests.get(audio_url, stream=True, timeout=120)
    total = int(r.headers.get('content-length', 0))
    downloaded = 0
    bar = st.progress(0, text="下载音频中...")
    with open(src, 'wb') as f:
        for chunk in r.iter_content(chunk_size=512 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                bar.progress(min(downloaded / total, 1.0),
                             text=f"下载中 {downloaded // 1024 // 1024} / {total // 1024 // 1024} MB")
    bar.progress(1.0, text="压缩音频中...")
    subprocess.run([
        "ffmpeg", "-y", "-i", src,
        "-ac", "1", "-ar", "16000", "-b:a", "16k", dst
    ], capture_output=True)
    bar.empty()
    return src, dst

def _transcribe_segment(seg_path, client):
    with open(seg_path, "rb") as f:
        return client.audio.transcriptions.create(model="whisper-1", file=f, language="zh").text

def transcribe(audio_file, episode_id):
    client = OpenAI(api_key=OPENAI_KEY)
    file_size = os.path.getsize(audio_file) / 1024 / 1024
    if file_size <= 20:
        with open(audio_file, "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f, language="zh")
        return response.text

    segment_duration = 15 * 60
    seg_dir = f"segments_{episode_id}"
    os.makedirs(seg_dir, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_file,
        "-f", "segment", "-segment_time", str(segment_duration),
        "-c", "copy", f"{seg_dir}/seg%03d.mp3"
    ], capture_output=True)
    segments = sorted(os.listdir(seg_dir))
    n = len(segments)

    progress = st.progress(0, text=f"并行转录 {n} 个片段...")
    results = {}
    with ThreadPoolExecutor(max_workers=min(n, 5)) as executor:
        future_to_idx = {
            executor.submit(_transcribe_segment, f"{seg_dir}/{seg}", client): i
            for i, seg in enumerate(segments)
        }
        completed = 0
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            results[i] = future.result()
            completed += 1
            progress.progress(completed / n, text=f"已完成 {completed}/{n} 段")
    progress.empty()
    # 清理分段临时目录
    for seg in segments:
        try:
            os.remove(f"{seg_dir}/{seg}")
        except OSError:
            pass
    try:
        os.rmdir(seg_dir)
    except OSError:
        pass
    return "\n".join(results[i] for i in range(n))

MAX_TRANSCRIPT_CHARS = 80000

def _claude_client():
    return anthropic.Anthropic(api_key=CLAUDE_KEY)

def get_tldr(transcript):
    text = transcript[:MAX_TRANSCRIPT_CHARS]
    response = _claude_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"播客内容：\n{text}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": """请用三句话概括这期播客，每句一行，分别是：
1. 谁聊了什么
2. 核心观点
3. 适合谁听
直接输出三句话，不要序号、不要额外说明。"""},
        ]}]
    )
    return response.content[0].text

def stream_summary(transcript):
    text = transcript[:MAX_TRANSCRIPT_CHARS]
    with _claude_client().messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"播客内容：\n{text}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": """请对以上播客内容生成一个极简的两层思维导图，用 Markdown 标题层级表示：
- 用一个 # 标题作为中心主题，一句话概括整期播客
- 用 3 到 5 个 ## 标题作为分支，每个分支是「话题 + 一句话结论」，每支控制在 15 字以内
严格要求：只能有 # 和 ## 两层，禁止使用 ### 更深层级，禁止使用 - 列表或任何细节展开，整体总字数控制在 100 字以内。
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
for key, default in {
    "transcript": "", "tldr": "", "summary": "", "quotes": "",
    "messages": [], "title": "", "episode_id": "", "url": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

def load_record(rec):
    """把一条 podcasts 记录载入 session state。"""
    st.session_state.episode_id = rec.get("episode_id", "")
    st.session_state.url = rec.get("url", "")
    st.session_state.title = rec.get("title", "")
    st.session_state.transcript = rec.get("transcript", "")
    st.session_state.tldr = rec.get("tldr", "")
    st.session_state.summary = rec.get("mindmap", "")
    st.session_state.quotes = rec.get("quotes", "")
    st.session_state.messages = []

# 侧边栏：历史播客列表
with st.sidebar:
    st.header("📚 历史播客")
    history = db.list_podcasts()
    if not history:
        st.caption("暂无历史记录")
    for rec in history:
        label = rec.get("title") or rec.get("episode_id")
        if st.button(label, key=f"hist_{rec['episode_id']}", use_container_width=True):
            full = db.get_podcast(rec["episode_id"])
            if full:
                load_record(full)
                st.rerun()

# 输入链接
url = st.text_input("粘贴小宇宙播客链接：")

if st.button("开始处理") and url:
    episode_id = db.extract_episode_id(url)

    # 先查缓存，命中直接展示，不重新下载转录
    cached = db.get_podcast(episode_id)
    if cached:
        st.success("已命中历史缓存，直接读取结果 ✅")
        load_record(cached)
    else:
        with st.spinner("解析链接..."):
            audio_url, title = get_audio_url(url)
            st.session_state.title = title
            st.session_state.episode_id = episode_id
            st.session_state.url = url
            st.write(f"**标题：** {title}")

        src_file = dst_file = None
        try:
            with st.spinner("下载并压缩音频..."):
                src_file, dst_file = download_and_compress(audio_url, episode_id)

            with st.spinner("转录中，请稍等..."):
                transcript = transcribe(dst_file, episode_id)
                st.session_state.transcript = transcript
                st.write(f"转录完成：{len(transcript)} 字")
        finally:
            # 处理完删除临时音频文件
            for f in (src_file, dst_file):
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass

        transcript = st.session_state.transcript

        # TL;DR 与金句在后台线程并行获取
        tldr_result = [None]
        quotes_result = [None]
        def _fetch_tldr():
            tldr_result[0] = get_tldr(transcript)
        def _fetch_quotes():
            quotes_result[0] = get_quotes(transcript)
        tldr_thread = threading.Thread(target=_fetch_tldr)
        quotes_thread = threading.Thread(target=_fetch_quotes)
        tldr_thread.start()
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

        with st.spinner("生成概要与金句中..."):
            tldr_thread.join()
            quotes_thread.join()
        st.session_state.tldr = tldr_result[0] or ""
        st.session_state.quotes = quotes_result[0] or ""

        # 存入 Supabase：历史记录 + 向量分块（RAG 地基）
        with st.spinner("保存到云端..."):
            db.save_podcast(
                episode_id, url, st.session_state.title, transcript,
                st.session_state.tldr, st.session_state.summary, st.session_state.quotes,
            )
            db.save_chunks(episode_id, transcript, OPENAI_KEY)

# ===== 展示顺序：TL;DR → 思维导图 → 金句 → 问答 =====

# TL;DR
if st.session_state.tldr:
    st.subheader(f"⚡ TL;DR：{st.session_state.title}")
    st.info(st.session_state.tldr)
    st.divider()

# 思维导图
if st.session_state.summary:
    st.subheader("🗺️ 思维导图")
    render_markmap(st.session_state.summary)
    st.divider()

# 原话摘录
if st.session_state.quotes:
    st.subheader("✏️ 精华原话摘录")
    st.markdown(st.session_state.quotes)
    st.divider()

# 问答
if st.session_state.transcript:
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
