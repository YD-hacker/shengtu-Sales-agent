"""Skill注册中心 - UP-201

版本1：dict+dataclass，不过度设计。
提供Skill的注册、发现、元信息查询和执行调度。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, Any, Optional, List
from loguru import logger


@dataclass
class SkillMeta:
    """Skill元信息"""
    name: str
    description: str = ""
    version: str = "1.0"
    category: str = "general"  # sales/general/external_api/flow_control
    applicable_stages: List[str] = field(default_factory=list)  # 适用阶段
    required_permission: str = ""  # 所需权限
    timeout_seconds: int = 30  # 执行超时
    max_retries: int = 0  # 最大重试次数
    is_async: bool = False  # 是否异步执行
    parameters_schema: Dict[str, Any] = field(default_factory=dict)  # 参数schema

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "version": self.version, "category": self.category,
            "applicable_stages": self.applicable_stages,
            "required_permission": self.required_permission,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "is_async": self.is_async,
            "parameters_schema": self.parameters_schema,
        }


class SkillRegistry:
    """Skill注册中心 - 全局单例"""

    def __init__(self):
        self._skills: Dict[str, SkillMeta] = {}
        self._handlers: Dict[str, Callable] = {}  # name -> handler function

    def register(self, meta: SkillMeta, handler: Callable):
        """注册一个Skill"""
        if meta.name in self._skills:
            logger.warning(f"Skill已存在，覆盖注册: {meta.name}")
        self._skills[meta.name] = meta
        self._handlers[meta.name] = handler
        logger.info(f"Skill注册: {meta.name} v{meta.version} [{meta.category}]")

    def unregister(self, name: str):
        """注销Skill"""
        self._skills.pop(name, None)
        self._handlers.pop(name, None)
        logger.info(f"Skill注销: {name}")

    def get_meta(self, name: str) -> Optional[SkillMeta]:
        """获取Skill元信息"""
        return self._skills.get(name)

    def get_handler(self, name: str) -> Optional[Callable]:
        """获取Skill处理函数"""
        return self._handlers.get(name)

    def list_skills(self, category: str = None, stage: str = None) -> List[SkillMeta]:
        """列出所有Skill（支持按类别/阶段筛选）"""
        result = list(self._skills.values())
        if category:
            result = [s for s in result if s.category == category]
        if stage:
            result = [s for s in result if not s.applicable_stages or stage in s.applicable_stages]
        return result

    def list_skill_names(self) -> List[str]:
        """列出所有Skill名称"""
        return list(self._skills.keys())

    def get_skills_for_stage(self, stage: str) -> List[SkillMeta]:
        """获取某阶段可用的Skill"""
        return [s for s in self._skills.values()
                if not s.applicable_stages or stage in s.applicable_stages]

    def to_prompt_desc(self, stage: str = None) -> str:
        """生成供LLM使用的Skill描述文本"""
        skills = self.get_skills_for_stage(stage) if stage else list(self._skills.values())
        if not skills:
            return "（无可用工具）"
        lines = []
        for s in skills:
            params = ""
            if s.parameters_schema:
                required = s.parameters_schema.get("required", [])
                properties = s.parameters_schema.get("properties", {})
                param_parts = []
                for pname, pinfo in properties.items():
                    req_mark = "*" if pname in required else ""
                    param_parts.append(f"{pname}{req_mark}: {pinfo.get('description', '')}")
                params = "(" + ", ".join(param_parts) + ")"
            lines.append(f"- {s.name}{params}: {s.description}")
        return "\n".join(lines)

    def is_registered(self, name: str) -> bool:
        """检查Skill是否已注册"""
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# 全局单例
skill_registry = SkillRegistry()


# ========== 内置Skill注册 ==========

def register_builtin_skills():
    """注册所有内置销售Skill（UP-202: 将现有10个隐式Skill显式注册）"""
    from code.tools import execute_tool

    # ---- 销售流程Skill ----
    skill_registry.register(
        SkillMeta(name="query_user_info", description="查询用户已收集的信息",
                  category="sales", applicable_stages=["qualify", "match_campus", "show_fee", "invite"],
                  timeout_seconds=5),
        lambda params, ctx: execute_tool("query_user_info", params, ctx.get("user_id"))
    )

    skill_registry.register(
        SkillMeta(name="check_qualification", description="检查用户保障班资格",
                  category="sales", applicable_stages=["qualify"],
                  timeout_seconds=5,
                  parameters_schema={
                      "type": "object",
                      "properties": {
                          "education": {"type": "string", "description": "学历"},
                          "age": {"type": "string", "description": "年龄"},
                          "major": {"type": "string", "description": "专业"},
                          "graduated_year": {"type": "string", "description": "毕业年份"},
                          "direction": {"type": "string", "description": "学习方向"}
                      },
                      "required": ["education", "age"]
                  }),
        lambda params, ctx: execute_tool("check_qualification", params, ctx.get("user_id"))
    )

    skill_registry.register(
        SkillMeta(name="match_campus", description="匹配最近校区",
                  category="sales", applicable_stages=["qualify", "match_campus"],
                  timeout_seconds=5),
        lambda params, ctx: execute_tool("match_campus", params, ctx.get("user_id"))
    )

    skill_registry.register(
        SkillMeta(name="get_case", description="获取匹配的学员成功案例",
                  category="sales", applicable_stages=["qualify", "match_campus", "show_fee"],
                  timeout_seconds=10),
        lambda params, ctx: execute_tool("get_case", params, ctx.get("user_id"))
    )

    skill_registry.register(
        SkillMeta(name="get_lead_info", description="获取用户线索评分和等级",
                  category="sales", applicable_stages=["qualify", "match_campus", "show_fee", "invite"],
                  timeout_seconds=5),
        lambda params, ctx: execute_tool("get_lead_info", params, ctx.get("user_id"))
    )

    # ---- 合规Skill（UP-204） ----
    def handle_compliance_check(params, ctx):
        from code.compliance_checker import hard_check
        text = params.get("text", "")
        state_node = params.get("state", ctx.get("current_node", "icebreak"))
        is_objection = params.get("is_objection", False)
        ok, safe_text = hard_check(text, state_node, is_objection=is_objection)
        return {"passed": ok, "safe_text": safe_text}

    skill_registry.register(
        SkillMeta(name="compliance_check", description="合规检查文本是否包含违禁词",
                  category="sales", applicable_stages=["show_fee", "invite", "report_info"],
                  timeout_seconds=3,
                  parameters_schema={
                      "type": "object",
                      "properties": {
                          "text": {"type": "string", "description": "待检查文本"},
                          "state": {"type": "string", "description": "当前阶段"},
                          "is_objection": {"type": "boolean", "description": "是否为异议处理"}
                      },
                      "required": ["text"]
                  }),
        handle_compliance_check
    )

    # ---- RAG问答Skill（UP-205） ----
    def handle_rag_query(params, ctx):
        from code.memory_vector import search as vm_search
        query = params.get("query", "")
        user_id = ctx.get("user_id", "")
        top_k = params.get("top_k", 5)
        results = vm_search(user_id, query, top_k) if vm_search else []
        return {"results": results, "count": len(results)}

    skill_registry.register(
        SkillMeta(name="rag_query", description="基于向量记忆的知识问答",
                  category="general", applicable_stages=[],
                  timeout_seconds=10,
                  parameters_schema={
                      "type": "object",
                      "properties": {
                          "query": {"type": "string", "description": "查询问题"},
                          "top_k": {"type": "integer", "description": "返回结果数"}
                      },
                      "required": ["query"]
                  }),
        handle_rag_query
    )

    # ---- 异议处理Skill（UP-206） ----
    def handle_objection(params, ctx):
        from code.objection_handler import generate_objection_response
        import asyncio
        intent = params.get("intent", "")
        user_msg = params.get("user_msg", "")
        state = ctx.get("state", {})
        history = ctx.get("history", [])
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(generate_objection_response(intent, user_msg, state, history))

    skill_registry.register(
        SkillMeta(name="handle_objection", description="动态生成异议回应",
                  category="sales", applicable_stages=["qualify", "match_campus", "show_fee", "invite"],
                  timeout_seconds=20, is_async=True,
                  parameters_schema={
                      "type": "object",
                      "properties": {
                          "intent": {"type": "string", "description": "异议类型"},
                          "user_msg": {"type": "string", "description": "用户消息"}
                      },
                      "required": ["intent", "user_msg"]
                  }),
        handle_objection
    )

    # ---- 挽回Skill（UP-207） ----
    def handle_recovery(params, ctx):
        from code.recovery_engine import should_attempt_recovery, schedule_recovery
        user_id = ctx.get("user_id", "")
        state = ctx.get("state", {})
        history = ctx.get("history", [])
        intent = params.get("intent", "reject")
        recovery_info = should_attempt_recovery(state, intent, history)
        if recovery_info.get("should_recover"):
            schedule_recovery(user_id, recovery_info["reason"], state)
            return {"scheduled": True, "reason": recovery_info["reason"]}
        return {"scheduled": False, "reason": recovery_info.get("reason", "")}

    skill_registry.register(
        SkillMeta(name="schedule_recovery", description="调度对话挽回任务",
                  category="sales", applicable_stages=["invite", "show_fee", "report_info"],
                  timeout_seconds=10),
        handle_recovery
    )

    # ---- 画像Skill ----
    def handle_profile(params, ctx):
        from code.user_profiler import build_deep_profile, get_personalized_strategy
        state = ctx.get("state", {})
        history = ctx.get("history", [])
        profile = build_deep_profile(state, history)
        strategies = get_personalized_strategy(profile)
        return {"profile": profile, "strategies": strategies}

    skill_registry.register(
        SkillMeta(name="build_profile", description="构建深度用户画像",
                  category="sales", applicable_stages=["qualify", "match_campus"],
                  timeout_seconds=10),
        handle_profile
    )

    # UP-204: 合规自检Skill
    from code.skill_compliance import execute as handle_compliance, get_skill_meta as meta_compliance
    skill_registry.register(meta_compliance(), handle_compliance)

    # UP-205: RAG问答Skill
    from code.skill_rag import execute as handle_rag, get_skill_meta as meta_rag
    skill_registry.register(meta_rag(), handle_rag)

    # UP-206: 异议处理Skill
    from code.skill_objection import execute as handle_objection, get_skill_meta as meta_objection
    skill_registry.register(meta_objection(), handle_objection)

    # UP-207: 挽回Skill
    from code.skill_recovery import execute as handle_recovery, get_skill_meta as meta_recovery
    skill_registry.register(meta_recovery(), handle_recovery)

    logger.info(f"内置Skill注册完成，共{len(skill_registry)}个")


# ========== Skill执行容器（UP-203） ==========

def execute_skill(name: str, params: dict = None, context: dict = None) -> dict:
    """统一Skill执行容器 - 含参数校验/超时/异常捕获"""
    if context is None:
        context = {}
    if params is None:
        params = {}

    meta = skill_registry.get_meta(name)
    if not meta:
        return {"error": f"未知Skill: {name}", "success": False}

    handler = skill_registry.get_handler(name)
    if not handler:
        return {"error": f"Skill无处理函数: {name}", "success": False}

    # 参数校验
    if meta.parameters_schema:
        required = meta.parameters_schema.get("required", [])
        for req_param in required:
            if req_param not in params:
                return {"error": f"缺少必需参数: {req_param}", "success": False}

    # 带超时执行
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(handler, params, context)
            try:
                result = future.result(timeout=meta.timeout_seconds)
            except concurrent.futures.TimeoutError:
                logger.warning(f"Skill执行超时: {name} (>{meta.timeout_seconds}s)")
                return {"error": f"Skill执行超时（>{meta.timeout_seconds}秒）", "success": False}
        if isinstance(result, dict):
            result["success"] = True
            return result
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Skill执行异常 {name}: {e}")
        return {"error": str(e), "success": False}


# 模块加载时自动注册内置Skill
try:
    register_builtin_skills()
except Exception as e:
    logger.warning(f"内置Skill自动注册失败（可能在导入阶段）: {e}")
