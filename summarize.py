import os
import anthropic

api_key = os.environ.get("CLAUDE_KEY")
if not api_key:
    raise ValueError("请设置环境变量 CLAUDE_KEY")
client = anthropic.Anthropic(api_key=api_key)

with open("transcript.txt", "r", encoding="utf-8") as f:
    transcript = f.read()

print("正在生成总结，请稍等...")

response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=2000,
    messages=[{"role": "user", "content": f"请对以下播客内容生成详细总结，包括：1.核心主题 2.主要观点 3.具体建议。\n\n播客内容：\n{transcript}"}]
)

summary = response.content[0].text
print("\n=== 播客总结 ===")
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
        messages=[{"role": "user", "content": f"基于以下播客内容回答问题，播客没涉及可结合实际补充。\n\n播客内容：\n{transcript}\n\n问题：{question}"}]
    )
    print("\nAI回答：", response.content[0].text)
    print()