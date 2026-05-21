from openai import OpenAI

client = OpenAI(api_key="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")

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