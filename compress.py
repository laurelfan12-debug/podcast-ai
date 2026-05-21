from pydub import AudioSegment
import os

print("正在压缩音频...")
audio = AudioSegment.from_file("episode.m4a")
audio = audio.set_channels(1).set_frame_rate(16000)
audio.export("episode_small.mp3", format="mp3", bitrate="32k")

size = os.path.getsize("episode_small.mp3") / 1024 / 1024
print(f"压缩完成，文件大小：{size:.1f} MB")