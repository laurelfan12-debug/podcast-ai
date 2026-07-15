"""Supabase 数据层：历史记录、缓存、以及为 RAG 预留的向量分块存储。"""
import re
import streamlit as st
from openai import OpenAI

try:
    from supabase import create_client, Client
except ImportError:  # 本地未安装 supabase 时降级，不阻断其它功能
    create_client = None
    Client = None

EMBED_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 500      # 每块约 500 字
CHUNK_OVERLAP = 50    # 相邻块重叠 50 字


def extract_episode_id(url: str) -> str:
    """从小宇宙链接中提取唯一 episode_id。

    形如 https://www.xiaoyuzhoufm.com/episode/6634a1b2c3d4e5f6a7b8c9d0
    """
    m = re.search(r"/episode/([0-9a-zA-Z]+)", url)
    if m:
        return m.group(1)
    # 兜底：取最后一段非空路径
    tail = url.rstrip("/").split("/")[-1].split("?")[0]
    return tail


@st.cache_resource
def get_supabase():
    """返回 Supabase 客户端；未配置或未安装时返回 None（功能降级）。"""
    if create_client is None:
        return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        return None
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


# ---------- podcasts 表 ----------

def get_podcast(episode_id: str):
    """按 episode_id 查缓存，命中返回记录 dict，否则 None。"""
    sb = get_supabase()
    if sb is None:
        return None
    try:
        res = sb.table("podcasts").select("*").eq("episode_id", episode_id).limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        st.warning(f"读取历史缓存失败：{e}")
        return None


def save_podcast(episode_id, url, title, transcript, tldr, mindmap, quotes):
    """写入/更新一期播客的处理结果。"""
    sb = get_supabase()
    if sb is None:
        return
    try:
        sb.table("podcasts").upsert({
            "episode_id": episode_id,
            "url": url,
            "title": title,
            "transcript": transcript,
            "tldr": tldr,
            "mindmap": mindmap,
            "quotes": quotes,
        }, on_conflict="episode_id").execute()
    except Exception as e:
        st.warning(f"保存历史记录失败：{e}")


def list_podcasts(limit: int = 50):
    """历史播客列表，按时间倒序。"""
    sb = get_supabase()
    if sb is None:
        return []
    try:
        res = (sb.table("podcasts")
               .select("episode_id, title, created_at")
               .order("created_at", desc=True)
               .limit(limit)
               .execute())
        return res.data or []
    except Exception as e:
        st.warning(f"读取历史列表失败：{e}")
        return []


# ---------- chunks 表（RAG 地基） ----------

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """把长文按 size 字切块，相邻块重叠 overlap 字。"""
    text = (text or "").strip()
    if not text:
        return []
    step = max(size - overlap, 1)
    chunks = []
    for start in range(0, len(text), step):
        piece = text[start:start + size]
        if piece.strip():
            chunks.append(piece)
        if start + size >= len(text):
            break
    return chunks


def embed_texts(texts, openai_key):
    """用 OpenAI text-embedding-3-small 批量生成向量。"""
    if not texts:
        return []
    client = OpenAI(api_key=openai_key)
    res = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in res.data]


def save_chunks(episode_id, transcript, openai_key):
    """本期播客转录切块 + 向量化后存入 chunks 表（仅存储，不检索）。"""
    sb = get_supabase()
    if sb is None:
        return
    try:
        pieces = chunk_text(transcript)
        if not pieces:
            return
        embeddings = embed_texts(pieces, openai_key)
        rows = [{
            "episode_id": episode_id,
            "chunk_index": i,
            "content": pieces[i],
            "embedding": embeddings[i],
        } for i in range(len(pieces))]
        # 先清理旧分块，避免重复
        sb.table("chunks").delete().eq("episode_id", episode_id).execute()
        sb.table("chunks").insert(rows).execute()
    except Exception as e:
        st.warning(f"保存向量分块失败（不影响本期结果）：{e}")
