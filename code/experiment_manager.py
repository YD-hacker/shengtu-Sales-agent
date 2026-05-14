"""A/B测试框架

实验配置、流量分配、效果评估、自动胜出判定。
支持话术实验、流程实验、策略实验。
"""
import os
import yaml
import hashlib
from loguru import logger
from code import CONFIG_DIR


# ---- 实验配置 ----
EXPERIMENT_FILE = os.path.join(CONFIG_DIR, "experiments.yaml")
_experiments = {}
_last_load_time = 0


def _load_experiments():
    """加载实验配置"""
    global _experiments, _last_load_time
    try:
        if not os.path.exists(EXPERIMENT_FILE):
            _experiments = {}
            return
        mtime = os.path.getmtime(EXPERIMENT_FILE)
        if mtime == _last_load_time:
            return
        _last_load_time = mtime
        with open(EXPERIMENT_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _experiments = data.get("experiments", {})
        logger.info(f"加载实验配置: {len(_experiments)}个实验")
    except Exception as e:
        logger.error(f"加载实验配置失败: {e}")


def _ensure_loaded():
    if not _experiments:
        _load_experiments()


# ---- 流量分配 ----

def assign_variant(user_id: str, experiment_name: str) -> str:
    """基于用户ID哈希分配实验变体，保证同一用户始终在同一组"""
    _ensure_loaded()
    exp = _experiments.get(experiment_name)
    if not exp or exp.get("status") != "running":
        return "control"

    variants = exp.get("variants", {})
    if not variants:
        return "control"

    # 用用户ID+实验名做哈希，保证一致性
    hash_input = f"{user_id}:{experiment_name}"
    hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 100

    cumulative = 0
    for variant_name, variant_config in variants.items():
        cumulative += variant_config.get("weight", 50)
        if hash_val < cumulative:
            return variant_name

    return "control"


def get_variant_content(experiment_name: str, variant: str) -> dict:
    """获取实验变体的内容"""
    _ensure_loaded()
    exp = _experiments.get(experiment_name, {})
    variants = exp.get("variants", {})
    return variants.get(variant, variants.get("control", {}))


# ---- 实验查询 ----

def get_active_experiments() -> list:
    """获取所有运行中的实验"""
    _ensure_loaded()
    active = []
    for name, config in _experiments.items():
        if config.get("status") == "running":
            active.append({"name": name, **config})
    return active


def get_experiment_for_stage(stage: str, intent: str = "") -> dict:
    """查找当前阶段/意图是否有生效的实验"""
    _ensure_loaded()
    for name, config in _experiments.items():
        if config.get("status") != "running":
            continue
        if config.get("stage") == stage:
            if not config.get("trigger") or config.get("trigger") == intent:
                return {"name": name, **config}
    return None


def get_experiment_template(user_id: str, stage: str, intent: str = "") -> str:
    """获取实验话术模板（如果有生效的实验）"""
    exp = get_experiment_for_stage(stage, intent)
    if not exp:
        return ""

    variant = assign_variant(user_id, exp["name"])
    content = get_variant_content(exp["name"], variant)

    template = content.get("template", "")
    if template:
        logger.info(f"实验命中: {exp['name']} variant={variant}")
    return template


# ---- 效果记录 ----

def record_exposure(user_id: str, experiment_name: str, variant: str):
    """记录实验曝光"""
    from code.conversation_analytics import log_experiment_exposure
    log_experiment_exposure(user_id, experiment_name, variant)


def record_conversion(user_id: str, experiment_name: str, variant: str, metric: str):
    """记录实验转化"""
    from code.conversation_analytics import record_event
    record_event(user_id, "experiment_conversion", {
        "experiment": experiment_name,
        "variant": variant,
        "metric": metric,
    })


# ---- 效果评估 ----

def evaluate_experiment(experiment_name: str, date_str: str = None) -> dict:
    """评估实验效果"""
    import json
    from code.time_utils import get_beijing_time
    from code import DATA_DIR

    if date_str is None:
        date_str = get_beijing_time().strftime("%Y-%m-%d")

    event_file = os.path.join(DATA_DIR, "analytics", f"events_{date_str}.jsonl")
    if not os.path.exists(event_file):
        return {"error": f"No data for {date_str}"}

    # 统计各变体的曝光和转化
    variant_stats = {}

    with open(event_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line.strip())
                data = event.get("data", {})

                if event["event_type"] == "experiment_exposure" and data.get("experiment") == experiment_name:
                    variant = data.get("variant", "unknown")
                    if variant not in variant_stats:
                        variant_stats[variant] = {"exposures": 0, "conversions": {}}
                    variant_stats[variant]["exposures"] += 1

                if event["event_type"] == "experiment_conversion" and data.get("experiment") == experiment_name:
                    variant = data.get("variant", "unknown")
                    metric = data.get("metric", "unknown")
                    if variant not in variant_stats:
                        variant_stats[variant] = {"exposures": 0, "conversions": {}}
                    variant_stats[variant]["conversions"][metric] = \
                        variant_stats[variant]["conversions"].get(metric, 0) + 1

            except (json.JSONDecodeError, KeyError):
                continue

    # 计算转化率
    for variant, stats in variant_stats.items():
        for metric, count in stats["conversions"].items():
            if stats["exposures"] > 0:
                stats["conversions"][f"{metric}_rate"] = round(count / stats["exposures"] * 100, 1)

    return {
        "experiment": experiment_name,
        "date": date_str,
        "variants": variant_stats,
    }


def get_winning_variant(experiment_name: str, metric: str, min_samples: int = 50) -> str:
    """判断实验是否有胜出变体"""
    result = evaluate_experiment(experiment_name)
    variants = result.get("variants", {})

    best_variant = None
    best_rate = -1

    for variant, stats in variants.items():
        if stats["exposures"] < min_samples:
            continue  # 样本量不足
        rate = stats["conversions"].get(f"{metric}_rate", 0)
        if rate > best_rate:
            best_rate = rate
            best_variant = variant

    return best_variant
