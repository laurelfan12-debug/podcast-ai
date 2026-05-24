import os
from openai import OpenAI

api_key = os.environ.get("OPENAI_KEY")
if not api_key:
    raise ValueError("请设置环境变量 OPENAI_KEY")
client = OpenAI(api_key=api_key)

print("开始转录，请稍等...")
with open("episode_small.mp3", "rb") as f:
    response = client.audio.transcriptions.create(
        model="whisper-1",
        file=f,
        language="zh"
    )

transcript = response.text
print("转录完成，共", len(transcript), "字")

with open("transcript.txt", "w", encoding="utf-8") as f:
    f.write(transcript)

print("已保存到 transcript.txt")