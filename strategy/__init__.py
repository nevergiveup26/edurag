"""
检索策略模块
提供 HyDE、子查询分解、回溯检索三种策略的预处理执行
"""
from strategy.base_strategy import StrategyResult, BaseStrategy

# 策略实现延迟导入，避免循环依赖
_strategies = {}


async def execute_strategy(
    strategy: str,
    query: str,
    retriever,
    llm,
    web_search_fn=None,
) -> StrategyResult:
    """统一入口：根据策略名执行对应预处理"""
    if strategy == "direct":
        return StrategyResult()  # direct 不需要预处理

    # 延迟导入策略实现
    global _strategies
    if not _strategies:
        from strategy.hyde_strategy import HyDEStrategy
        from strategy.sub_query_strategy import SubQueryStrategy
        from strategy.backtrack_strategy import BacktrackStrategy
        _strategies = {
            "hyde": HyDEStrategy(),
            "sub_query": SubQueryStrategy(),
            "backtrack": BacktrackStrategy(),
        }

    impl = _strategies.get(strategy)
    if not impl:
        return StrategyResult()
    return await impl.execute(
        query=query,
        retriever=retriever,
        llm=llm,
        web_search_fn=web_search_fn,
    )