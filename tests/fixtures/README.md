# 测试样例说明

本目录保存旅游资源推荐模块的测试 fixture 数据。

建议测试按以下场景读取样例：

| 文件 | 用途 |
|---|---|
| `candidate_resources.json` | 测试候选资源查询、标签过滤、城市过滤 |
| `recommendation_context_normal.json` | 测试正常新建行程推荐 |
| `recommendation_context_budget_limit.json` | 测试明确预算限制 |
| `recommendation_context_forbidden_place.json` | 测试禁止地点过滤 |
| `recommendation_context_dietary_restriction.json` | 测试饮食禁忌过滤 |
| `recommendation_result_valid.json` | 测试合法推荐输出 |
| `recommendation_result_invalid_city.json` | 测试城市不一致校验 |
| `recommendation_result_forbidden_place.json` | 测试禁止地点校验 |
| `poi_candidates_ambiguous.json` | 测试同名 POI 候选确认 |
| `route_results_sample.json` | 测试路线结果格式 |
| `rag_evidence_sample.json` | 测试推荐依据补充 |
