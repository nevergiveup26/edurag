"""
阿里云 DashScope OCR 客户端
使用 qwen-vl-ocr 模型进行高精度文字识别
fallback 到现有 LLM vision 方案
"""
import os
import re
import json
import base64
from typing import Optional, Dict

from core.logger import get_logger

logger = get_logger("ocr_client")


class DashScopeOCR:
    """DashScope OCR 封装"""

    def __init__(self, api_key: str = None):
        if api_key:
            self.api_key = api_key
        elif os.getenv("DASHSCOPE_API_KEY"):
            self.api_key = os.getenv("DASHSCOPE_API_KEY")
        elif os.getenv("LLM_API_KEY"):
            self.api_key = os.getenv("LLM_API_KEY")
        else:
            from core.config_manager import ConfigManager
            self.api_key = ConfigManager().dashscope_config.get("api_key", "")
        self._available = False
        self._checked = False

    def _ensure_available(self) -> bool:
        """检测 dashscope 是否可用"""
        if self._checked:
            return self._available
        self._checked = True

        if not self.api_key or self.api_key in ("ollama", "not-needed", ""):
            logger.info("[DashScopeOCR] 未配置有效的 DashScope API Key，跳过")
            return False

        try:
            import dashscope
            dashscope.api_key = self.api_key
            self._available = True
            logger.info("[DashScopeOCR] DashScope 初始化成功")
        except ImportError:
            logger.warning("[DashScopeOCR] dashscope 未安装，pip install dashscope")
        except Exception as e:
            logger.warning(f"[DashScopeOCR] 初始化失败: {e}")

        return self._available

    def extract_text(self, image_base64: str, label: str = "图片") -> Dict:
        """
        从 base64 图片中提取文字

        Args:
            image_base64: 图片 base64（可带 data:image/...;base64, 前缀）
            label: 图片标签（题目/作答）

        Returns:
            {"extracted_text": "...", "confidence": "高/中/低", "error": ""}
        """
        if not self._ensure_available():
            return {"extracted_text": "", "error": "DashScope 未配置或不可用", "confidence": "低"}

        # 标准化 base64：确保带 data URI 前缀
        img_url = image_base64
        if not img_url.startswith("data:"):
            # 探测图片格式
            try:
                raw = base64.b64decode(img_url[:100], validate=True)
            except Exception:
                return {"extracted_text": "", "error": "无效的 base64 图片数据", "confidence": "低"}
            img_url = f"data:image/png;base64,{img_url}"

        try:
            import dashscope
            from dashscope import MultiModalConversation

            messages = [{
                "role": "user",
                "content": [
                    {"image": img_url},
                    {"text": f"请提取这张{label}中的所有文字内容。\n\n要求：\n1. 返回图片中出现的全部文字，包括标题、题干、说明、数据、标注等，一个都不要漏\n2. 按照原文的阅读顺序输出（从上到下、从左到右）\n3. 如果是数学公式，保持原样不要修改\n4. 如果某个字实在看不清，标为[?]\n5. 如果完全没有文字，返回空"}
                ]
            }]

            logger.info(f"[DashScopeOCR] 开始调用 qwen-vl-ocr 识别{label}...")
            response = MultiModalConversation.call(
                model="qwen-vl-ocr",
                messages=messages,
            )

            if response.status_code == 200:
                # 记录原始响应用于调试
                try:
                    raw_output_str = str(response.output)
                    logger.info(f"[DashScopeOCR] {label} 原始响应(前2000字): {raw_output_str[:2000]}")
                except Exception as e:
                    logger.debug(f"OCR 响应转字符串失败: {e}")

                content = ""
                try:
                    output = response.output
                    if hasattr(output, 'choices') and output.choices:
                        msg = output.choices[0].message
                        if hasattr(msg, 'content'):
                            for item in msg.content:
                                item_text = ""
                                # 优先使用 ocr_result 结构化结果（含完整文字+位置信息）
                                if isinstance(item, dict):
                                    ocr_result = item.get("ocr_result", {})
                                    if isinstance(ocr_result, dict) and ocr_result.get("processed_text"):
                                        item_text = ocr_result["processed_text"]
                                        logger.info(f"[DashScopeOCR] {label} 从ocr_result.processed_text提取({len(item_text)}字)")
                                    elif item.get("text"):
                                        item_text = item["text"]
                                        logger.info(f"[DashScopeOCR] {label} 从item.text提取({len(item_text)}字)")
                                elif hasattr(item, 'text'):
                                    item_text = item.text
                                if item_text:
                                    content += item_text
                        elif isinstance(msg, dict):
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = "".join(
                                    c.get("text", "") if isinstance(c, dict) else str(c)
                                    for c in content
                                )
                    elif hasattr(output, 'text'):
                        content = output.text
                except Exception as parse_err:
                    logger.warning(f"[DashScopeOCR] 解析响应异常: {parse_err}")
                    content = str(response.output) if response.output else ""

                content = content.strip()
                confidence = "高" if len(content) > 20 else ("中" if len(content) > 5 else "低")

                logger.info(f"[DashScopeOCR] {label}识别成功，{len(content)}字，置信度: {confidence}")
                return {
                    "extracted_text": content,
                    "confidence": confidence,
                    "engine": "dashscope-qwen-vl-ocr",
                }
            else:
                logger.error(f"[DashScopeOCR] API调用失败: {response.status_code} - {response.message}")
                return {
                    "extracted_text": "",
                    "error": f"DashScope API错误: {response.message}",
                    "confidence": "低",
                }

        except ImportError:
            logger.warning("[DashScopeOCR] dashscope 未安装")
            return {"extracted_text": "", "error": "dashscope 未安装", "confidence": "低"}
        except Exception as e:
            logger.error(f"[DashScopeOCR] 调用异常: {e}", exc_info=True)
            return {"extracted_text": "", "error": str(e), "confidence": "低"}


# 全局单例
_ocr_client: Optional[DashScopeOCR] = None


def get_ocr_client() -> DashScopeOCR:
    """获取全局 OCR 客户端"""
    global _ocr_client
    if _ocr_client is None:
        _ocr_client = DashScopeOCR()
    return _ocr_client


def ocr_extract_text(image_base64: str, label: str = "图片") -> str:
    """
    使用 DashScope OCR 提取文字，返回 JSON 字符串

    如果 DashScope 不可用，返回空结果让上层 fallback
    """
    client = get_ocr_client()
    result = client.extract_text(image_base64, label)
    return json.dumps(result, ensure_ascii=False)
