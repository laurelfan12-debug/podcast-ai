import streamlit as st
import requests
import json
import os
import subprocess
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
    with open("episode.m4a", 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            f.write(chunk)
    subprocess.run([
        "ffmpeg", "-y", "-i", "episode.m4a",
        "-ac", "1", "-ar", "16000", "-b:a", "16k", "episode_small.mp3"
    ], capture_output=True)
    return "episode_small.mp3"

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
    full_text = ""
    for i, seg in enumerate(segments):
        st.write(f"转录第 {i+1}/{len(segments)} 段...")
        with open(f"segments/{seg}", "rb") as f:
            response = client.audio.transcriptions.create(model="whisper-1", file=f, language="zh")
        full_text += response.text + "\n"
    return full_text

def get_summary(transcript):
    client = anthropic.Anthropic(api_key=CLAUDE_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": f"请对以下播客内容生成详细总结，包括：1.核心主题 2.主要观点 3.具体建议。\n\n播客内容：\n{transcript}"}]
    )
    return response.content[0].text

def ask_question(transcript, question):
    client = anthropic.Anthropic(api_key=CLAUDE_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": f"基于以下播客内容回答问题，没涉及可结合实际补充。\n\n播客内容：\n{transcript}\n\n问题：{question}"}]
    )
    return response.content[0].text

# 初始化session state
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "summary" not in st.session_state:
    st.session_state.summary = ""
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

    with st.spinner("生成总结..."):
        summary = get_summary(transcript)
        st.session_state.summary = summary

# 显示总结
if st.session_state.summary:
    st.subheader(f"📋 总结：{st.session_state.title}")
    st.markdown(st.session_state.summary)
    st.divider()

    # 问答
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