"""RAG问答Skill - UP-205

基于FAQ知识库 + 向量记忆检索的问答Skill。
当用户提出具体问题时，检索最匹配的FAQ并生成回答。
"""
import json
import os
from loguru import logger
from code import DATA_DIR

# FAQ知识库路径
FAQ_FILE = os.path.join(DATA_DIR, "faq_knowledge.json")

# 内存缓存
_faq_cache = None
_faq_cache_mtime = 0


def _load_faq():
    """加载FAQ知识库（带文件修改时间缓存）"""
    global _faq_cache, _faq_cache_mtime
    try:
        mtime = os.path.getmtime(FAQ_FILE)
        if _faq_cache is not None and mtime == _faq_cache_mtime:
            return _faq_cache

        with open(FAQ_FILE, encoding="utf-8") as f:
            _faq_cache = json.load(f)
        _faq_cache_mtime = mtime
        logger.info(f"FAQ知识库加载: {len(_faq_cache)} 条")
        return _faq_cache
    except Exception as e:
        logger.warning(f"FAQ加载失败: {e}")
        return []


def search_faq(query: str, top_k: int = 3) -> list:
    """
    简单关键词匹配搜索FAQ
    后续可升级为向量检索
    """
    faq_list = _load_faq()
    if not faq_list:
        return []

    scored = []
    query_lower = query.lower()

    for item in faq_list:
        score = 0
        question = item.get("question", "")
        category = item.get("category", "")
        answer = item.get("answer", "")

        # 问题匹配
        q_chars = set(query_lower)
        q_match = sum(1 for c in q_chars if c in question)
        score += q_match * 2

        # 类别匹配
        if any(kw in query_lower for kw in category.split()):
            score += 10

        # 关键词直接命中
        for kw in query_lower.replace("？", "").replace("?", "").split():
            if len(kw) >= 2 and kw in question:
                score += 15

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def search_faq_semantic(query: str, state: dict = None, top_k: int = 3) -> list:
    """
    语义搜索FAQ（使用向量记忆）
    优先使用向量检索，降级为关键词匹配
    """
    try:
        from code.memory_vector import search_faq as vector_faq_search
        results = vector_faq_search(query, top_k)
        if results:
            logger.info(f"向量FAQ检索命中: {len(results)}条")
            return results
    except Exception as e:
        logger.debug(f"向量FAQ检索失败，降级关键词: {e}")

    return search_faq(query, top_k)


def format_faq_answer(item: dict) -> str:
    """将FAQ条目格式化为回答文本"""
    answer = item.get("answer", "")
    question = item.get("question", "")
    # 如果answer已经足够完整，直接返回
    if len(answer) >= 30:
        return answer
    return f"关于「{question}」：{answer}"


def execute(params: dict, context: dict = None) -> dict:
    """
    RAG问答Skill入口

    params:
        query: str — 用户问题
        state: dict — 用户状态（可选，用于个性化）
        top_k: int — 返回结果数（可选，默认3）
        use_semantic: bool — 是否使用语义搜索（可选，默认True）

    returns:
        dict: {
            "found": bool,
            "answers": list[dict],  # 匹配的FAQ条目
            "best_answer": str,     # 最佳回答文本
            "search_method": str,   # 搜索方法
        }
    """
    query = params.get("query", "")
    state = params.get("state")
    top_k = params.get("top_k", 3)
    use_semantic = params.get("use_semantic", True)

    if not query.strip():
        return {"found": False, "answers": [], "best_answer": "", "search_method": "empty"}

    # 搜索
    if use_semantic:
        results = search_faq_semantic(query, state, top_k)
        method = "semantic" if len(results) > 0 else "keyword"
    else:
        results = search_faq(query, top_k)
        method = "keyword"

    if not results:
        logger.info(f"FAQ未匹配: {query[:50]}")
        return {
            "found": False,
            "answers": [],
            "best_answer": "",
            "search_method": method,
        }

    best = results[0]
    logger.info(f"FAQ匹配: {query[:30]} -> {best.get('category', '')}/{best.get('id', '')}")

    return {
        "found": True,
        "answers": results,
        "best_answer": format_faq_answer(best),
        "best_category": best.get("category", ""),
        "best_id": best.get("id", ""),
        "search_method": method,
    }


def get_skill_meta():
    """返回Skill元信息"""
    from code.skill_registry import SkillMeta
    return SkillMeta(
        name="faq_rag",
        description="FAQ知识库问答：检索FAQ知识库，返回精准回答。支持关键词和语义两种检索模式",
        version="1.0",
        category="general",
        applicable_stages=[
            "icebreak", "qualify", "match_campus", "show_fee",
            "invite", "report_info",
            "pre_assessment", "pre_training",
        ],
        timeout_seconds=8,
        max_retries=1,
    )
