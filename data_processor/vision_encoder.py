"""
视觉编码器 — 多模态Embedding

功能：
1. CLIP模型编码图片为向量（用于相似度检索）— 可选，需 pip install transformers torch
2. 视觉语言模型(VLM)生成图片描述 — 走云端 LLM（推荐）
3. 图片描述文本向量化 — 走云端 DashScope embedding
4. 图文匹配检索

云端模式下 CLIP 不可用时：
- encode_image / encode_text 返回 None（上游已有 fallback）
- describe_image 走云端 VLM

使用方式：
    encoder = VisionEncoder()
    embedding = encoder.encode_image(img_path)  # 图片→向量（需本地CLIP）
    desc = encoder.describe_image(img_path, llm_client=llm)  # 图片→文字描述（云端VLM）
"""
import os
import base64
from typing import List, Optional, Tuple
from pathlib import Path

from core.logger import get_logger

logger = get_logger("vision_encoder")

# 支持的CLIP模型
AVAILABLE_VISION_MODELS = {
    "clip-vit-base-patch32": {
        "name": "openai/clip-vit-base-patch32",
        "dim": 512,
        "description": "OpenAI CLIP ViT-B/32 — 通用图文匹配",
    },
    "clip-vit-large-patch14": {
        "name": "openai/clip-vit-large-patch14",
        "dim": 768,
        "description": "OpenAI CLIP ViT-L/14 — 高精度图文匹配",
    },
    "bge-visualized": {
        "name": "BAAI/BGE-Visualized",
        "dim": 768,
        "description": "BAAI中文图文embedding模型",
    },
    "sentence-clip-vit": {
        "name": "sentence-transformers/clip-ViT-B-32",
        "dim": 512,
        "description": "sentence-transformers CLIP封装",
    },
}


class VisionEncoder:
    """
    视觉编码器

    双模式：
    1. CLIP模式：图片和文本编码到同一向量空间，支持跨模态检索
    2. VLM描述模式：用视觉语言模型生成图片描述文本
    """

    def __init__(self, model_name: str = None, device: str = None):
        self.model_name = model_name or "clip-vit-base-patch32"
        self._model = None
        self._processor = None
        self._device = device or ("cuda" if self._check_cuda() else "cpu")
        self._available = False
        self._dim = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def dim(self) -> int:
        return self._dim or 512

    def _check_cuda(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def _load_clip(self):
        """加载CLIP模型"""
        if self._model is not None:
            return

        model_info = AVAILABLE_VISION_MODELS.get(self.model_name, AVAILABLE_VISION_MODELS["clip-vit-base-patch32"])
        model_id = model_info["name"]
        self._dim = model_info["dim"]

        try:
            from transformers import CLIPModel, CLIPProcessor
            import torch

            self._model = CLIPModel.from_pretrained(model_id)
            self._processor = CLIPProcessor.from_pretrained(model_id)
            self._model.to(self._device)
            self._model.eval()
            self._available = True
            logger.info(f"CLIP模型已加载: {model_id} (dim={self._dim})")
        except ImportError:
            logger.warning("transformers未安装，视觉编码不可用 (pip install transformers torch)")
        except Exception as e:
            logger.warning(f"CLIP模型加载失败: {e}")

    # ======================== 图片编码 ========================

    def encode_image(self, image_path: str = None, image_base64: str = None) -> Optional[List[float]]:
        """
        将图片编码为向量

        Args:
            image_path: 图片文件路径
            image_base64: 图片base64编码

        Returns:
            图片向量 (list of float)
        """
        self._load_clip()
        if not self._available:
            logger.warning("CLIP模型未加载，返回None")
            return None

        try:
            from PIL import Image
            import io
            import torch

            if image_path and os.path.exists(image_path):
                image = Image.open(image_path).convert("RGB")
            elif image_base64:
                image_bytes = base64.b64decode(image_base64)
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            else:
                logger.error("未提供图片路径或base64数据")
                return None

            inputs = self._processor(images=image, return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                embedding = self._model.get_image_features(**inputs)

            embedding = embedding / embedding.norm(dim=-1, keepdim=True)
            return embedding.cpu().numpy().flatten().tolist()
        except Exception as e:
            logger.error(f"图片编码失败: {e}")
            return None

    def encode_images(self, images: List[dict]) -> List[List[float]]:
        """
        批量编码图片

        Args:
            images: [{"image_path": "..."}, ...] 或 [{"image_base64": "..."}, ...]

        Returns:
            向量列表
        """
        embeddings = []
        for img in images:
            emb = self.encode_image(
                image_path=img.get("image_path"),
                image_base64=img.get("image_base64"),
            )
            if emb:
                embeddings.append(emb)
        return embeddings

    # ======================== 文本编码（CLIP文本塔） ========================

    def encode_text(self, text: str) -> Optional[List[float]]:
        """
        用CLIP文本塔编码文本（与图片在同一向量空间）
        用于图文跨模态检索
        """
        self._load_clip()
        if not self._available:
            return None

        try:
            import torch
            inputs = self._processor(text=text, return_tensors="pt", padding=True, truncation=True, max_length=77)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                embedding = self._model.get_text_features(**inputs)

            embedding = embedding / embedding.norm(dim=-1, keepdim=True)
            return embedding.cpu().numpy().flatten().tolist()
        except Exception as e:
            logger.error(f"文本编码失败: {e}")
            return None

    # ======================== 图片→文本描述 ========================

    def describe_image(self, image_path: str = None, image_base64: str = None,
                       llm_client=None) -> Optional[str]:
        """
        生成图片的文字描述（需要VLM或LLM API）

        优先级：
        1. 如果提供了llm_client且有vision能力 → 调用VLM
        2. 否则生成模板化描述

        Args:
            image_path: 图片路径
            image_base64: 图片base64
            llm_client: LLM客户端（需支持vision/图片输入）

        Returns:
            图片的文字描述
        """
        if llm_client and hasattr(llm_client, 'generate_with_image'):
            return llm_client.generate_with_image(
                prompt="请详细描述这张图片的内容，包括图中的对象、场景、文字、数据等关键信息。",
                image_path=image_path,
                image_base64=image_base64,
            )

        # Fallback：返回模板化描述
        source = image_path or "base64_image"
        return f"[图片描述 - {Path(source).name if image_path else '内嵌图片'}]: 这是一张教育类文档中的配图。"

    def describe_images_batch(self, images: List[dict], llm_client=None) -> List[str]:
        """批量描述图片"""
        descriptions = []
        for img in images:
            desc = self.describe_image(
                image_path=img.get("image_path"),
                image_base64=img.get("image_base64"),
                llm_client=llm_client,
            )
            descriptions.append(desc or "")
        return descriptions

    # ======================== 图文相似度计算 ========================

    def image_text_similarity(self, text: str, image_embedding: List[float]) -> float:
        """
        计算文本与图片的CLIP相似度（跨模态匹配）

        Args:
            text: 查询文本
            image_embedding: 图片向量

        Returns:
            余弦相似度 (0~1)
        """
        text_emb = self.encode_text(text)
        if not text_emb or not image_embedding:
            return 0.0

        import numpy as np
        t = np.array(text_emb)
        i = np.array(image_embedding)
        cos_sim = np.dot(t, i) / (np.linalg.norm(t) * np.linalg.norm(i) + 1e-8)
        return float(max(0, min(cos_sim, 1)))

    # ======================== 工具方法 ========================

    @classmethod
    def list_models(cls) -> List[dict]:
        return [
            {"key": k, "name": v["name"], "dim": v["dim"], "desc": v["description"]}
            for k, v in AVAILABLE_VISION_MODELS.items()
        ]

    def get_model_info(self) -> dict:
        return {
            "model_name": self.model_name,
            "available": self._available,
            "dim": self.dim,
            "device": self._device,
        }