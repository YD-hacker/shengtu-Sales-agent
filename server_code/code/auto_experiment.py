"""自动A/B测试模块

功能：
1. 自动生成话术变体
2. 创建实验配置
3. 评估实验效果
"""
import json
import os
from loguru import logger
from code import CONFIG_DIR
from code.model_router import stream_llm
from code.experiment_manager import get_active_experiments, record_exposure


EXPERIMENTS_FILE = os.path.join(CONFIG_DIR, "experiments.yaml")


async def generate_variant(template, intent, state=None):
    """让LLM生成话术变体"""
    state = state or {}
    profile_desc = ""
    if state:
        parts = []
        for k, label in [("education", "学历"), ("age", "年龄"), ("city", "城市")]:
            if state.get(k):
                parts.append(f"{label}:{state[k]}")
        profile_desc = "用户画像：" + "、".join(parts) if parts else ""

    prompt = f"""你是话术优化专家。原话术：
"{template}"

意图：{intent}
{profile_desc}

请生成一个风格不同但效果可能更好的变体话术。
要求：
1. 核心信息不变（费用、条件等关键数据不能改）
2. 表达方式不同（换个说法、换个切入角度）
3. 可能更有说服力或更自然
4. 控制在100字以内
5. 不要出现"培训""学费""保证""一定"等词
6. 口语化，像微信聊天

直接输出新话术："""

    variant = ""
    try:
        async for token in stream_llm(prompt, 0.8, "main"):
            if token:
                variant += token
    except Exception as e:
        logger.warning(f"生成话术变体失败: {e}")
        return ""

    variant = variant.strip()
    if not variant:
        return ""

    # 合规检查：变体必须通过硬检查（使用正确的阶段参数）
    from code.compliance_checker import hard_check
    stage = _get_stage_for_intent(intent)
    is_obj = intent.startswith("objection_")
    is_safe, safe_text = hard_check(variant, stage, is_objection=is_obj)
    if not is_safe:
        logger.warning(f"话术变体合规检查未通过，已拦截: {variant[:50]}...")
        return ""

    return variant


async def auto_create_experiments(kb_scripts):
    """自动创建实验"""
    import yaml

    # 选择要实验的话术
    experiment_targets = {
        "objection_consider": kb_scripts.get("objection_consider", [""])[0],
        "objection_price": kb_scripts.get("objection_price", [""])[0],
        "objection_learn": kb_scripts.get("objection_learn", [""])[0],
        "icebreak_normal": kb_scripts.get("icebreak_normal", [""])[0],
    }

    experiments = {}
    for intent, template in experiment_targets.items():
        if not template:
            continue

        variant = await generate_variant(template, intent)
        if not variant:
            continue

        # 二次合规检查（双重保险）
        from code.compliance_checker import hard_check
        is_safe, safe_variant = hard_check(variant, _get_stage_for_intent(intent), is_objection=intent.startswith("objection_"))
        if not is_safe:
            logger.warning(f"实验变体合规拦截: {intent} -> {variant[:50]}...")
            continue
        variant = safe_variant

        experiments[f"{intent}_variant"] = {
            "stage": _get_stage_for_intent(intent),
            "trigger": intent,
            "status": "running",
            "created_at": __import__("datetime").datetime.now().isoformat(),
            "variants": {
                "control": {"weight": 50, "template": template},
                "variant": {"weight": 50, "template": variant}
            },
            "stats": {
                "control": {"exposures": 0, "conversions": 0},
                "variant": {"exposures": 0, "conversions": 0}
            }
        }
        logger.info(f"创建实验: {intent}, 变体: {variant[:50]}...")

    # 保存实验配置
    if experiments:
        _save_experiments(experiments)

    return experiments


def _get_stage_for_intent(intent):
    """根据意图获取对应阶段"""
    stage_map = {
        "objection_consider": "qualify",
        "objection_price": "show_fee",
        "objection_learn": "qualify",
        "icebreak_normal": "icebreak",
    }
    return stage_map.get(intent, "icebreak")


def _save_experiments(experiments):
    """保存实验配置"""
    try:
        import yaml
        # 读取现有实验
        existing = {}
        if os.path.exists(EXPERIMENTS_FILE):
            with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}

        # 合并
        if "experiments" not in existing:
            existing["experiments"] = {}
        existing["experiments"].update(experiments)

        with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"保存了{len(experiments)}个实验")
    except Exception as e:
        logger.error(f"保存实验配置失败: {e}")


def get_experiment_variant(experiment_name, user_id):
    """获取用户应该看到的变体"""
    try:
        import yaml
        if not os.path.exists(EXPERIMENTS_FILE):
            return None

        with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        exp = config.get("experiments", {}).get(experiment_name)
        if not exp or exp.get("status") != "running":
            return None

        # 简单的A/B分配：基于user_id hash
        variant = "variant" if hash(user_id) % 2 == 0 else "control"

        # 记录曝光
        record_exposure(user_id, experiment_name, variant)

        return exp["variants"][variant]["template"]
    except Exception as e:
        logger.debug(f"获取实验变体失败: {e}")
        return None


def evaluate_all_experiments():
    """评估所有实验效果"""
    try:
        import yaml
        if not os.path.exists(EXPERIMENTS_FILE):
            return {}

        with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        results = {}
        for name, exp in config.get("experiments", {}).items():
            control = exp.get("stats", {}).get("control", {})
            variant = exp.get("stats", {}).get("variant", {})

            control_rate = (control.get("conversions", 0) /
                          max(control.get("exposures", 1), 1)) * 100
            variant_rate = (variant.get("conversions", 0) /
                          max(variant.get("exposures", 1), 1)) * 100

            winner = None
            if control.get("exposures", 0) >= 20 and variant.get("exposures", 0) >= 20:
                if variant_rate > control_rate * 1.1:
                    winner = "variant"
                elif control_rate > variant_rate * 1.1:
                    winner = "control"

            results[name] = {
                "status": exp.get("status", "unknown"),
                "control_rate": round(control_rate, 1),
                "variant_rate": round(variant_rate, 1),
                "winner": winner,
                "control_exposures": control.get("exposures", 0),
                "variant_exposures": variant.get("exposures", 0)
            }

        return results
    except Exception as e:
        logger.error(f"评估实验失败: {e}")
        return {}
