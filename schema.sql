-- ============================================================
-- 小宇宙播客 AI 助手 —— Supabase 建表脚本
-- 在 Supabase 控制台的 SQL Editor 里整体执行即可
-- ============================================================

-- 1. 启用 pgvector 扩展（向量检索地基）
create extension if not exists vector;

-- 2. 播客处理结果表：历史记录 + 缓存
create table if not exists podcasts (
    episode_id  text primary key,          -- 从小宇宙 URL 提取的唯一 ID
    url         text,
    title       text,
    transcript  text,
    tldr        text,
    mindmap     text,
    quotes      text,
    created_at  timestamptz not null default now()
);

-- 历史列表按时间倒序，建索引加速
create index if not exists podcasts_created_at_idx
    on podcasts (created_at desc);

-- 3. 分块向量表：RAG 地基（本期仅存储，不检索）
--    text-embedding-3-small 向量维度为 1536
create table if not exists chunks (
    id           bigint generated always as identity primary key,
    episode_id   text not null references podcasts (episode_id) on delete cascade,
    chunk_index  int  not null,
    content      text not null,
    embedding    vector(1536),
    created_at   timestamptz not null default now(),
    unique (episode_id, chunk_index)
);

-- 按 episode_id 过滤分块
create index if not exists chunks_episode_idx
    on chunks (episode_id);

-- 将来做相似度检索时用的近似向量索引（cosine 距离）
-- HNSW 无需训练、空表即可建，召回率与稳定性优于 ivfflat：
--   m               每个节点的最大连接数（默认 16）
--   ef_construction 构建时的候选列表大小，越大越准但越慢（默认 64）
create index if not exists chunks_embedding_idx
    on chunks using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);
