from backend.schemas import AgentStep, AgentTrace, TravelRequest, new_id


class WorkflowService:
    def build_trace(self, session_id: str, intent: str, has_missing_fields: bool) -> AgentTrace:
        steps = [
            AgentStep(step=1, agent="coordinator_agent", action="receive_message", summary="协调总控接收用户输入并建立工作流上下文", duration_ms=60),
            AgentStep(step=2, agent="intent_agent", action="detect_intent_with_chatbot", summary=f"调用 Chatbot 识别一级意图：{intent}", duration_ms=180),
            AgentStep(step=3, agent="requirement_adapter", action="extract_travel_request", summary="生成 TravelRequest，供后续推荐、路线和行程模块使用", duration_ms=260),
        ]

        if has_missing_fields:
            steps.append(
                AgentStep(step=4, agent="coordinator_agent", action="branch_follow_up", summary="发现关键字段缺失，进入追问分支", duration_ms=80)
            )
        elif intent == "travel_qa":
            steps.append(
                AgentStep(step=4, agent="rag_service", action="query", summary="转交 RAG 问答接口，等待来源证据", status="skipped", duration_ms=0)
            )
        elif intent == "modify_trip":
            steps.extend([
                AgentStep(step=4, agent="coordinator_agent", action="branch_modify_trip", summary="解析修改对象和受影响日期", duration_ms=180),
                AgentStep(step=5, agent="member3_itinerary_api", action="local_replan", summary="预留局部重规划接口调用", status="skipped", duration_ms=0),
            ])
        else:
            steps.extend([
                AgentStep(step=4, agent="coordinator_agent", action="branch_create_trip", summary="进入新建行程工作流分支", duration_ms=100),
                AgentStep(step=5, agent="member2_recommendation_api", action="recommend_places", summary="预留景点、酒店、餐厅推荐接口调用", status="skipped", duration_ms=0),
                AgentStep(step=6, agent="member2_route_api", action="batch_plan_routes", summary="预留批量路线规划接口调用", status="skipped", duration_ms=0),
                AgentStep(step=7, agent="member3_itinerary_api", action="generate_and_validate", summary="预留行程生成、预算和规则校验接口调用", status="skipped", duration_ms=0),
            ])

        return AgentTrace(trace_id=new_id("trace"), session_id=session_id, steps=steps)

    def demo_itinerary_shell(self, requirements: TravelRequest) -> dict:
        return {
            "itinerary_id": new_id("trip"),
            "session_id": requirements.session_id,
            "version": 1,
            "requirements_snapshot": requirements.model_dump(),
            "days": [],
            "total_cost": None,
            "status": "draft",
            "note": "成员一只创建工作流壳，正式行程由成员三接口生成。",
        }
