"""LLM回复质量人工评估框架 - UP-211

评估维度：
  合规性（是否触发违禁词）
  相关性（是否回答用户问题）
  推进性（是否推动销售漏斗）
  自然度（是否像真人而非模板）
  共情度（是否感知并回应用户情绪）

使用方法：
  from code.eval_framework import Evaluator
  evaluator = Evaluator()
  scores = evaluator.evaluate(reply, context)
"""
import json
import os
from datetime import datetime
from loguru import logger
from code import DATA_DIR

EVAL_DIR = os.path.join(DATA_DIR, "evaluations")
os.makedirs(EVAL_DIR, exist_ok=True)

# 评分维度及权重
EVAL_DIMENSIONS = {
    "compliance": {"weight": 0.30, "label": "合规性", "desc": "回复是否遵守合规红线，无违禁词"},
    "relevance":  {"weight": 0.25, "label": "相关性", "desc": "回复是否切题回答用户问题"},
    "progression": {"weight": 0.20, "label": "推进性", "desc": "回复是否推动销售漏斗前进"},
    "naturalness": {"weight": 0.15, "label": "自然度", "desc": "回复是否像真人而非模板"},
    "empathy":    {"weight": 0.10, "label": "共情度", "desc": "感知并回应用户情绪的能力"},
}

# 评分锚点描述（1-5分）
RUBRIC_ANCHORS = {
    5: "优秀 - 完全达到标准，超出预期",
    4: "良好 - 达到标准，有小瑕疵",
    3: "合格 - 基本达标，可接受",
    2: "较差 - 存在明显问题",
    1: "很差 - 严重不符合标准",
}


class EvaluationRecord:
    """单次评估记录"""
    def __init__(self, reply: str, context: dict, scores: dict, total: float, reviewer: str = ""):
        self.timestamp = datetime.now().isoformat()
        self.reply = reply
        self.context = context
        self.scores = scores
        self.total = total
        self.reviewer = reviewer

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "reply": self.reply,
            "context": self.context,
            "scores": self.scores,
            "total": self.total,
            "reviewer": self.reviewer,
        }


class Evaluator:
    """LLM回复质量评估器"""

    def __init__(self, reviewer: str = ""):
        self.reviewer = reviewer

    def auto_evaluate(self, reply: str, context: dict) -> dict:
        """自动评估（基于规则，非LLM）

        context应包含:
          - user_msg: 用户消息
          - intent: 意图
          - current_node: 当前阶段
          - expected_next_node: 预期下一阶段
          - state: 用户状态
        """
        scores = {}
        user_msg = context.get("user_msg", "")

        # 1. 合规性评分（自动检查违禁词）
        forbidden_words = ["培训", "学费", "上课", "招生", "老师", "机构", "保证就业", "包就业"]
        found = [w for w in forbidden_words if w in reply]
        if not found:
            scores["compliance"] = 5
        elif len(found) == 1:
            scores["compliance"] = 3
        else:
            scores["compliance"] = 1

        # 2. 相关性评分（基于关键词重叠）
        user_keywords = set(user_msg) - set("的了吗呢吧啊呀呢哦一二三四五六七八九十")
        reply_keywords = set(reply)
        overlap = len(user_keywords & reply_keywords)
        if len(user_msg) < 10:
            scores["relevance"] = 4
        elif overlap > 5:
            scores["relevance"] = 5
        elif overlap > 1:
            scores["relevance"] = 3
        else:
            scores["relevance"] = 2

        # 3. 推进性评分
        progression_keywords = ["校区", "周末", "过来", "试听", "了解", "情况", "学历", "年龄", "联系"]
        prog_count = sum(1 for w in progression_keywords if w in reply)
        if prog_count >= 3:
            scores["progression"] = 5
        elif prog_count >= 1:
            scores["progression"] = 3
        else:
            scores["progression"] = 2

        # 4. 自然度评分（启发式：模板标记少=更自然）
        template_markers = ["好的", "嗯嗯", "是这样的", "也就是说", "我可以告诉你"]
        marker_count = sum(1 for m in template_markers if m in reply)
        if marker_count == 0:
            scores["naturalness"] = 5
        elif marker_count <= 2:
            scores["naturalness"] = 4
        else:
            scores["naturalness"] = 2

        # 5. 共情度评分
        empathy_keywords = ["理解", "明白", "懂", "不容易", "正常", "理解你", "没关系", "加油"]
        emp_count = sum(1 for w in empathy_keywords if w in reply)
        if emp_count >= 2:
            scores["empathy"] = 5
        elif emp_count >= 1:
            scores["empathy"] = 4
        else:
            scores["empathy"] = 3

        # 计算加权总分
        total = sum(
            scores.get(dim, 3) * info["weight"]
            for dim, info in EVAL_DIMENSIONS.items()
        )

        return {
            "dimensions": {
                dim: {"score": scores.get(dim, 3), "label": info["label"], "desc": info["desc"]}
                for dim, info in EVAL_DIMENSIONS.items()
            },
            "total": round(total, 2),
            "grade": self._grade(total),
        }

    def _grade(self, total: float) -> str:
        if total >= 4.5:
            return "A+"
        elif total >= 4.0:
            return "A"
        elif total >= 3.5:
            return "B+"
        elif total >= 3.0:
            return "B"
        elif total >= 2.0:
            return "C"
        else:
            return "D"

    def evaluate_and_save(self, reply: str, context: dict, user_id: str = "") -> dict:
        """评估并保存记录"""
        result = self.auto_evaluate(reply, context)
        record = EvaluationRecord(
            reply=reply, context=context,
            scores=result["dimensions"], total=result["total"],
            reviewer=self.reviewer
        )
        self._save_record(record, user_id)
        return result

    def _save_record(self, record: EvaluationRecord, user_id: str):
        """保存评估记录到文件"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = os.path.join(EVAL_DIR, f"eval_{date_str}.jsonl")
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"保存评估记录失败: {e}")

    def get_stats(self, date_str: str = None) -> dict:
        """获取某日评估统计"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = os.path.join(EVAL_DIR, f"eval_{date_str}.jsonl")
        if not os.path.exists(file_path):
            return {"error": f"No evaluations for {date_str}"}

        total_count = 0
        total_score = 0.0
        dim_scores = {dim: [] for dim in EVAL_DIMENSIONS}

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    total_count += 1
                    total_score += record.get("total", 0)
                    for dim in EVAL_DIMENSIONS:
                        dim_data = record.get("scores", {}).get(dim, {})
                        dim_scores[dim].append(dim_data.get("score", 0))
                except (json.JSONDecodeError, KeyError):
                    continue

        if total_count == 0:
            return {"error": "No valid records"}

        return {
            "date": date_str,
            "total_evaluations": total_count,
            "average_total": round(total_score / total_count, 2),
            "dimension_averages": {
                dim: round(sum(scores) / len(scores), 2) if scores else 0
                for dim, scores in dim_scores.items()
            },
        }


# 模块级便捷函数
_default_evaluator = Evaluator()


def quick_evaluate(reply: str, user_msg: str, stage: str = "icebreak", intent: str = "normal") -> dict:
    """快捷评估函数"""
    context = {
        "user_msg": user_msg,
        "current_node": stage,
        "intent": intent,
    }
    return _default_evaluator.auto_evaluate(reply, context)
