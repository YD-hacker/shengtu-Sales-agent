"""向量记忆系统 - 本地FAISS实现（完全异步版）

功能：
1. 语义检索历史对话
2. 记住用户偏好和关键信息
3. 支持多用户隔离
4. 模型在后台线程加载，绝不阻塞请求
"""
import os
import json
import threading
from loguru import logger
from code import DATA_DIR

_model = None
_index = None
_model_ready = False
_model_loading = False
_model_lock = threading.Lock()
_memories = []
_user_indices = {}  # user_id -> [memory_index, ...] 用于快速用户隔离
_persist_dir = os.path.join(DATA_DIR, "vector_memory")
os.makedirs(_persist_dir, exist_ok=True)

# 加载元数据（轻量操作，不加载模型）
_memories_path = os.path.join(_persist_dir, "memories.json")
try:
    if os.path.exists(_memories_path):
        with open(_memories_path, "r", encoding="utf-8") as f:
            _memories = json.load(f)
        # 重建用户索引
        for idx, m in enumerate(_memories):
            uid = m.get("user_id", "")
            if uid:
                if uid not in _user_indices:
                    _user_indices[uid] = []
                _user_indices[uid].append(idx)
        logger.info(f"向量记忆元数据加载: {len(_memories)}条, {len(_user_indices)}个用户")
except Exception as e:
    logger.debug(f"元数据加载失败: {e}")


def _load_model_background():
    """后台线程加载模型（不阻塞任何请求）"""
    global _model, _index, _model_ready, _model_loading
    if _model_ready or _model_loading:
        return
    with _model_lock:
        if _model_ready or _model_loading:
            return
        _model_loading = True
    try:
        logger.info("后台线程: 开始加载向量模型...")
        from sentence_transformers import SentenceTransformer
        import faiss
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        index_path = os.path.join(_persist_dir, "faiss.index")
        if os.path.exists(index_path):
            _index = faiss.read_index(index_path)
        else:
            _index = faiss.IndexFlatIP(384)
        _model_ready = True
        logger.info(f"后台线程: 向量模型加载完成, 索引大小={_index.ntotal}")
    except Exception as e:
        logger.warning(f"后台线程: 向量模型加载失败: {e}")
    finally:
        _model_loading = False


# 启动后台加载线程（daemon=True，主进程退出时自动结束）
_load_thread = threading.Thread(target=_load_model_background, daemon=True)
_load_thread.start()


def add_memory(user_id, user_msg, assistant_msg, metadata=None):
    """添加记忆（如果模型未就绪则静默跳过）"""
    global _memories, _index, _model, _model_ready, _user_indices
    if not _model_ready:
        return
    try:
        import faiss
        text = "用户：" + user_msg + "\n小范：" + assistant_msg
        embedding = _model.encode([text])[0]
        faiss.normalize_L2(embedding.reshape(1, -1))
        _index.add(embedding.reshape(1, -1))
        memory_idx = len(_memories)
        _memories.append({
            "user_id": user_id,
            "text": text,
            "user_msg": user_msg,
            "assistant_msg": assistant_msg,
            "metadata": metadata or {}
        })
        # 维护用户索引
        if user_id not in _user_indices:
            _user_indices[user_id] = []
        _user_indices[user_id].append(memory_idx)
        # 每100条持久化一次
        if len(_memories) % 100 == 0:
            _save()
    except Exception as e:
        logger.debug(f"添加记忆失败: {e}")


def search(user_id, query, top_k=3):
    """语义检索，用户隔离（如果模型未就绪返回空）"""
    if not _model_ready or _index is None or _index.ntotal == 0:
        return []
    try:
        import faiss
        import numpy as np

        # 先检查用户是否有记忆
        user_memory_indices = _user_indices.get(user_id, [])
        if not user_memory_indices:
            return []

        query_embedding = _model.encode([query])[0]
        faiss.normalize_L2(query_embedding.reshape(1, -1))

        # 用户记忆数量少于top_k时，直接返回该用户所有记忆（按相关性排序）
        if len(user_memory_indices) <= top_k:
            results = []
            for idx in user_memory_indices:
                if idx < len(_memories):
                    memory = _memories[idx]
                    if memory.get("metadata", {}).get("cleared"):
                        continue
                    # 计算相似度
                    if _index.ntotal > idx:
                        score = float(np.dot(query_embedding, _index.reconstruct(idx)))
                    else:
                        score = 0.0
                    results.append({
                        "text": memory["text"],
                        "score": score,
                        "metadata": memory.get("metadata", {})
                    })
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_k]

        # 用户记忆较多时，从全局搜索中过滤（扩大搜索范围）
        search_k = min(top_k * 10, _index.ntotal)
        scores, indices = _index.search(query_embedding.reshape(1, -1), search_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(_memories) and _memories[idx]["user_id"] == user_id:
                results.append({
                    "text": _memories[idx]["text"],
                    "score": float(score),
                    "metadata": _memories[idx].get("metadata", {})
                })
                if len(results) >= top_k:
                    break
        return results
    except Exception as e:
        logger.debug(f"检索记忆失败: {e}")
        return []


def get_user_memories(user_id, limit=10):
    return [m for m in _memories if m["user_id"] == user_id][-limit:]


def clear_user_memories(user_id):
    """清除指定用户的所有向量记忆（用于信息纠正场景）"""
    global _memories, _user_indices
    user_indices = _user_indices.get(user_id, [])
    if not user_indices:
        return 0
    # 标记删除（不能直接删除，因为FAISS索引不支持删除）
    # 将用户的记忆文本清空，后续检索时会跳过
    count = 0
    for idx in user_indices:
        if idx < len(_memories) and _memories[idx]["user_id"] == user_id:
            _memories[idx]["text"] = "[已清除]"
            _memories[idx]["user_msg"] = ""
            _memories[idx]["assistant_msg"] = ""
            _memories[idx]["metadata"] = {"cleared": True}
            count += 1
    # 清除用户索引
    _user_indices.pop(user_id, None)
    logger.info(f"已清除用户{user_id}的{count}条向量记忆")
    return count


def get_stats():
    return {
        "total_memories": len(_memories),
        "index_size": _index.ntotal if _index else 0,
        "model_ready": _model_ready,
        "model_loading": _model_loading,
        "unique_users": len(set(m["user_id"] for m in _memories))
    }


_save_lock = threading.Lock()

def _save():
    """持久化向量索引和元数据（带文件锁，防多worker并发损坏）"""
    with _save_lock:
        try:
            import tempfile
            index_path = os.path.join(_persist_dir, "faiss.index")
            if _index is not None:
                import faiss
                # 原子写入FAISS索引
                tmp_index = index_path + ".tmp"
                faiss.write_index(_index, tmp_index)
                os.replace(tmp_index, index_path)
            # 原子写入元数据
            with tempfile.NamedTemporaryFile(mode='w', dir=_persist_dir, delete=False, encoding='utf-8') as tmp:
                json.dump(_memories, tmp, ensure_ascii=False, indent=2)
                tmp_name = tmp.name
            os.replace(tmp_name, _memories_path)
        except Exception as e:
            logger.debug(f"保存记忆失败: {e}")
