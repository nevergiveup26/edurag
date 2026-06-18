"""
评估报告生成
生成包含图表和指标详情的自包含 HTML 报告
"""
import base64
import io
from typing import List, Dict, Optional

from core.logger import get_logger

logger = get_logger("eval_report")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    HAS_MATPLOTLIB = True

    _CN_FONTS = ["Noto Sans SC", "SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei"]
    for _fn in _CN_FONTS:
        try:
            fm.findfont(_fn, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [_fn]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            continue
except ImportError:
    HAS_MATPLOTLIB = False


def _fig_to_b64(fig) -> str:
    """将 matplotlib figure 转为 base64 PNG"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def generate_charts(sample_reports: List[Dict]) -> Dict[str, str]:
    """生成评估图表，返回 {chart_name: base64_png}"""
    if not HAS_MATPLOTLIB or not sample_reports:
        return {}

    charts = {}
    n = len(sample_reports)

    try:
        # 图1: 检索指标柱状图
        fig, ax = plt.subplots(figsize=(8, 5))
        metrics_names = ["Precision", "Recall", "F1", "MRR", "NDCG", "HitRate"]
        values = [
            sum(r.get("precision", 0) for r in sample_reports) / n,
            sum(r.get("recall", 0) for r in sample_reports) / n,
            sum(r.get("f1", 0) for r in sample_reports) / n,
            sum(r.get("mrr", 0) for r in sample_reports) / n,
            sum(r.get("ndcg", 0) for r in sample_reports) / n,
            sum(r.get("hit_rate", 0) for r in sample_reports) / n,
        ]
        colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#E91E63", "#00BCD4"]
        bars = ax.bar(metrics_names, values, color=colors, edgecolor="white")
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                    f"{val:.2%}", ha="center", va="bottom", fontsize=10)
        ax.set_ylim(0, 1.15)
        ax.set_title("Retrieval Metrics", fontsize=14, fontweight="bold")
        ax.set_ylabel("Score")
        fig.tight_layout()
        charts["retrieval"] = _fig_to_b64(fig)
        plt.close(fig)

        # 图2: 生成指标条形图
        top_n = min(20, n)
        display = sample_reports[:top_n]
        queries = [r.get("query", "")[:15] + "..." for r in display]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        bleu_vals = [r.get("bleu_1", 0) for r in display]
        rouge_vals = [r.get("rouge_l", 0) for r in display]
        x = range(len(queries))
        width = 0.35
        ax1.barh([i + width / 2 for i in x], bleu_vals, width, label="BLEU-1", color="#2196F3")
        ax1.barh([i - width / 2 for i in x], rouge_vals, width, label="ROUGE-L", color="#4CAF50")
        ax1.set_yticks(x)
        ax1.set_yticklabels(queries, fontsize=8)
        ax1.set_xlabel("Score")
        ax1.set_title("BLEU-1 & ROUGE-L", fontsize=12, fontweight="bold")
        ax1.set_xlim(0, 1.1)
        ax1.legend(fontsize=8)

        kw_rates = [r.get("keyword_match_rate", 0) for r in display]
        ax2.barh(range(len(queries)), kw_rates, color="#FF9800")
        ax2.set_yticks(range(len(queries)))
        ax2.set_yticklabels(queries, fontsize=8)
        ax2.set_xlabel("Keyword Match Rate")
        ax2.set_title("Keyword Match Rate", fontsize=12, fontweight="bold")
        ax2.set_xlim(0, 1.1)
        fig.tight_layout()
        charts["generation"] = _fig_to_b64(fig)
        plt.close(fig)

    except Exception as e:
        logger.warning(f"Chart generation failed: {e}")

    return charts


def format_report_html(
    metrics: Dict,
    details: List[Dict],
    total_time: float,
    charts: Dict[str, str] = None,
) -> str:
    """
    生成统一 HTML 评估报告

    Args:
        metrics: 汇总指标 dict，包含 retrieval/generation/rag_quality/avg_score
        details: 逐样本详情列表
        total_time: 总耗时（秒）
        charts: 图表 base64 dict

    Returns:
        HTML 字符串
    """
    charts = charts or {}

    def _bar(val, color=None):
        pct = max(0, min(100, int(val * 100)))
        if color is None:
            color = "#4CAF50" if val >= 0.7 else "#FF9800" if val >= 0.4 else "#F44336"
        return (
            f"<div style='display:flex;align-items:center;gap:8px;'>"
            f"<div style='flex:1;background:#e0e0e0;border-radius:3px;height:10px;'>"
            f"<div style='width:{pct}%;background:{color};border-radius:3px;height:10px;'></div>"
            f"</div><span style='min-width:50px;font-weight:bold;color:{color};'>{val:.1%}</span></div>"
        )

    def _card(title, value, color, unit=""):
        return (
            f"<div style='flex:1;min-width:80px;background:{color};border-radius:8px;"
            f"padding:12px;text-align:center;'>"
            f"<div style='font-size:11px;color:#666;'>{title}</div>"
            f"<div style='font-size:24px;font-weight:bold;color:#333;'>{value}{unit}</div></div>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EduRAG 统一评估报告</title>
<style>
* {{margin:0;padding:0;box-sizing:border-box;}}
body {{font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;background:#f5f7fa;color:#333;padding:24px;}}
.container {{max-width:1200px;margin:0 auto;}}
h1 {{font-size:24px;margin-bottom:20px;color:#1a1a2e;}}
h2 {{font-size:18px;margin:24px 0 12px;color:#1a1a2e;border-bottom:2px solid #e0e0e0;padding-bottom:6px;}}
.card {{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,0.06);}}
.metric-row {{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;}}
.chart-img {{max-width:100%;border-radius:8px;margin:8px 0;}}
.sample-detail {{font-size:13px;}}
.sample-detail summary {{cursor:pointer;padding:8px;background:#f0f4f8;border-radius:6px;margin:4px 0;}}
.sample-detail summary:hover {{background:#e0e8f0;}}
.sample-detail table {{width:100%;border-collapse:collapse;margin:8px 0;}}
.sample-detail th, .sample-detail td {{padding:6px 10px;text-align:left;border-bottom:1px solid #eee;font-size:12px;}}
.sample-detail th {{background:#f8f9fa;font-weight:600;}}
</style>
</head>
<body>
<div class="container">
<h1>EduRAG 统一评估报告</h1>
"""

    # 概览卡片
    sample_count = len(details) if details else 0
    avg_score = metrics.get("avg_score", 0)
    html += "<div class='card'><div class='metric-row'>"
    html += _card("样本数", sample_count, "#e3f2fd")
    html += _card("综合平均分", f"{avg_score:.1%}", "#e8f5e9")
    html += _card("总耗时", f"{total_time:.1f}s", "#fff3e0")
    html += "</div></div>"

    # 检索指标
    html += "<h2>检索指标</h2><div class='card'>"
    r = metrics.get("retrieval", {})
    retrieval_items = [
        ("Precision", r.get("precision", 0), "检索结果中相关文档的比例"),
        ("Recall", r.get("recall", 0), "所有相关文档被检索到的比例"),
        ("F1 Score", r.get("f1_score", 0), "Precision 与 Recall 的调和平均"),
        ("MRR", r.get("mrr", 0), "第一个相关文档排名的倒数均值"),
        ("NDCG", r.get("ndcg", 0), "归一化折损累计增益"),
        ("Hit Rate", r.get("hit_rate", 0), "至少命中一个相关文档的概率"),
    ]
    for name, val, desc in retrieval_items:
        html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>{name}</b></span><span style='font-size:12px;color:#999;'>{desc}</span></div>{_bar(val)}</div>"
    if charts.get("retrieval"):
        html += f"<img class='chart-img' src='data:image/png;base64,{charts['retrieval']}' alt='检索指标图表'>"
    html += "</div>"

    # 生成指标
    html += "<h2>生成指标</h2><div class='card'>"
    g = metrics.get("generation", {})
    gen_items = [
        ("BLEU-1", g.get("bleu_1", 0)),
        ("BLEU-2", g.get("bleu_2", 0)),
        ("ROUGE-L", g.get("rouge_l", 0)),
        ("Keyword Match Rate", g.get("keyword_match_rate", 0)),
    ]
    for name, val in gen_items:
        html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>{name}</b></span></div>{_bar(val)}</div>"
    if charts.get("generation"):
        html += f"<img class='chart-img' src='data:image/png;base64,{charts['generation']}' alt='生成指标图表'>"
    html += "</div>"

    # RAG 质量指标
    html += "<h2>RAG 质量指标 (LLM 评判)</h2><div class='card'>"
    q = metrics.get("rag_quality", {})
    rag_items = [
        ("Faithfulness (忠实度)", q.get("faithfulness", 0), "答案是否忠实于上下文，不编造"),
        ("AnswerRelevancy (答案相关性)", q.get("answer_relevancy", 0), "答案是否直接回应问题"),
        ("ContextPrecision (上下文精确率)", q.get("context_precision", 0), "embedding 相似度均值"),
        ("ContextRelevancy (上下文相关性)", q.get("context_relevancy", 0), "embedding 相似度均值"),
    ]
    if q.get("answer_correctness", 0) > 0:
        rag_items.append(("AnswerCorrectness (正确性)", q.get("answer_correctness", 0), "与标准答案的一致性"))
    for name, val, desc in rag_items:
        html += f"<div style='margin:8px 0;'><div style='display:flex;justify-content:space-between;'><span><b>{name}</b></span><span style='font-size:12px;color:#999;'>{desc}</span></div>{_bar(val)}</div>"
    html += "</div>"

    # 样本详情
    if details:
        html += "<h2>样本详情</h2><div class='card sample-detail'>"
        for i, d in enumerate(details):
            query = (d.get("query", "") or "")[:80]
            answer = (d.get("answer", "") or "")[:150]
            html += f"<details><summary>[{i+1}] {query}</summary>"
            html += "<table>"
            html += f"<tr><th>字段</th><th>值</th></tr>"
            html += f"<tr><td>answer</td><td>{answer}</td></tr>"
            for key in ["bleu_1", "bleu_2", "rouge_l", "keyword_match_rate", "faithfulness",
                        "answer_relevancy", "f1", "precision", "recall", "mrr", "execution_time"]:
                if key in d:
                    val = d[key]
                    if isinstance(val, float):
                        val = f"{val:.4f}"
                    html += f"<tr><td>{key}</td><td>{val}</td></tr>"
            html += "</table></details>"
        html += "</div>"

    html += "</div></body></html>"
    return html