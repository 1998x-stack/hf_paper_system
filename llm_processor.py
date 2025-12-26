"""
llm_processor.py - Ollama LLM 处理模块

该模块负责使用Ollama进行论文分类、关键词提取、标签生成和段落评论。
遵循CleanRL设计原则：单一职责、显式依赖、易于测试。
"""

import json
import sys
import asyncio
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiohttp
from loguru import logger

from config import settings, PAPER_CATEGORIES
from models import (
    ClassificationResult,
    KeywordsResult,
    LabelsResult,
    ParagraphComment,
    CommentsResult,
    Ar5ivContent,
)
from utils import (
    save_json,
    load_json,
    safe_json_parse,
    truncate_text,
    format_exception,
)


class OllamaClient:
    """
    Ollama API 客户端
    
    负责与Ollama服务器通信，发送生成请求。
    支持流式和非流式响应。
    """
    
    def __init__(
        self,
        host: str = "http://localhost:11434",
        timeout: int = 120,
    ):
        """
        初始化客户端
        
        Args:
            host: Ollama服务器地址
            timeout: 超时时间（秒）
        """
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.generate_url = f"{self.host}/api/generate"
    
    async def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 10000,
    ) -> Optional[str]:
        """
        生成文本
        
        Args:
            model: 模型名称
            prompt: 用户提示
            system: 系统提示
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            生成的文本或None
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        
        if system:
            payload["system"] = system
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.generate_url,
                    json=payload,
                    timeout=self.timeout
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("response", "")
                    else:
                        text = await response.text()
                        logger.error(f"Ollama错误 HTTP {response.status}: {text[:200]}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error(f"Ollama超时 ({self.timeout}s)")
            return None
        except Exception:
            error_message = format_exception()
            logger.error(f"Ollama请求失败: {error_message}")
            return None
    
    async def check_health(self) -> bool:
        """检查服务是否可用"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.host}/api/tags", timeout=5) as response:
                    return response.status == 200
        except Exception:
            return False


class LLMProcessor:
    """
    LLM处理器
    
    使用Ollama进行论文分析：
    1. 分类 (qwen3:0.6b)
    2. 关键词提取 (qwen3:0.6b)
    3. 标签生成 (qwen3:0.6b)
    4. 段落评论 (qwen3:4b)
    """
    
    def __init__(
        self,
        host: str = None,
        model_small: str = None,
        model_large: str = None,
        concurrency: int = 3,
    ):
        """
        初始化处理器
        
        Args:
            host: Ollama服务器地址
            model_small: 小模型名称
            model_large: 大模型名称
            concurrency: 并发数
        """
        self.host = host or settings.ollama_host
        self.model_small = model_small or settings.ollama_model_small
        self.model_large = model_large or settings.ollama_model_large
        self.concurrency = concurrency
        
        self.client = OllamaClient(self.host, settings.ollama_timeout)
        
        # 统计
        self.stats = {
            "classification": {"success": 0, "failure": 0},
            "keywords": {"success": 0, "failure": 0},
            "labels": {"success": 0, "failure": 0},
            "comments": {"success": 0, "failure": 0},
        }
    
    async def check_service(self) -> bool:
        """检查Ollama服务"""
        healthy = await self.client.check_health()
        if healthy:
            logger.info(f"Ollama服务正常: {self.host}")
        else:
            logger.error(f"Ollama服务不可用: {self.host}")
        return healthy
    
    # ==================== 分类 ====================
    
    def _build_classification_prompt(self, title: str, abstract: str) -> str:
        """构建分类提示"""
        categories_desc = "\n".join([
            f"- {cat_id}: {info['name']} ({info['name_zh']})"
            for cat_id, info in PAPER_CATEGORIES.items()
        ])
        
        return f"""Classify this academic paper into ONE category.

CATEGORIES:
{categories_desc}

PAPER:
Title: {title}
Abstract: {truncate_text(abstract or '', 500)}

Respond with ONLY a JSON object:
{{"category": "category_id", "confidence": 0.0-1.0, "reasoning": "brief reason"}}"""
    
    async def classify_paper(
        self,
        paper_id: str,
        title: str,
        abstract: str,
        force: bool = False
    ) -> Optional[ClassificationResult]:
        """
        对论文进行分类
        
        Args:
            paper_id: 论文ID
            title: 标题
            abstract: 摘要
            force: 是否强制重新分类
            
        Returns:
            ClassificationResult或None
        """
        # 检查缓存
        cache_file = settings.get_llm_output_file("classification", paper_id)
        if cache_file.exists() and not force:
            data = await load_json(cache_file)
            if data:
                return ClassificationResult(**data)
        
        prompt = self._build_classification_prompt(title, abstract)
        system = "You are an academic paper classifier. Respond only with valid JSON. /no_think"
        
        response = await self.client.generate(
            model=self.model_small,
            prompt=prompt,
            system=system,
            temperature=0.2,
        )
        
        if not response:
            self.stats["classification"]["failure"] += 1
            return None
        
        # 解析响应
        parsed = safe_json_parse(response)
        if not parsed:
            logger.warning(f"分类结果解析失败 {paper_id}: {truncate_text(response, 100)}")
            self.stats["classification"]["failure"] += 1
            return None
        
        category = parsed.get("category", "other")
        if category not in PAPER_CATEGORIES:
            category = "other"
        
        cat_info = PAPER_CATEGORIES[category]
        
        result = ClassificationResult(
            paper_id=paper_id,
            category=category,
            category_name=cat_info["name"],
            category_name_zh=cat_info["name_zh"],
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning"),
            raw_response=response,
        )
        
        # 保存结果
        await save_json(result.model_dump(), cache_file)
        self.stats["classification"]["success"] += 1
        
        return result
    
    # ==================== 关键词提取 ====================
    
    def _build_keywords_prompt(self, title: str, abstract: str) -> str:
        """构建关键词提取提示"""
        return f"""Extract key technical terms and concepts from this academic paper.

PAPER:
Title: {title}
Abstract: {truncate_text(abstract or '', 500)}

Respond with ONLY a JSON object:
{{"keywords": ["keyword1", "keyword2", ...], "keywords_zh": ["关键词1", "关键词2", ...]}}

Extract 5-10 specific technical keywords. Include both English and Chinese versions."""
    
    async def extract_keywords(
        self,
        paper_id: str,
        title: str,
        abstract: str,
        force: bool = False
    ) -> Optional[KeywordsResult]:
        """
        提取关键词
        
        Args:
            paper_id: 论文ID
            title: 标题
            abstract: 摘要
            force: 是否强制重新提取
            
        Returns:
            KeywordsResult或None
        """
        cache_file = settings.get_llm_output_file("keywords", paper_id)
        if cache_file.exists() and not force:
            data = await load_json(cache_file)
            if data:
                return KeywordsResult(**data)
        
        prompt = self._build_keywords_prompt(title, abstract)
        system = "You are a keyword extractor for academic papers. Respond only with valid JSON. /no_think"
        
        response = await self.client.generate(
            model=self.model_small,
            prompt=prompt,
            system=system,
            temperature=0.3,
        )
        
        if not response:
            self.stats["keywords"]["failure"] += 1
            return None
        
        parsed = safe_json_parse(response)
        if not parsed:
            self.stats["keywords"]["failure"] += 1
            return None
        
        result = KeywordsResult(
            paper_id=paper_id,
            keywords=parsed.get("keywords", [])[:10],
            keywords_zh=parsed.get("keywords_zh", [])[:10],
            raw_response=response,
        )
        
        await save_json(result.model_dump(), cache_file)
        self.stats["keywords"]["success"] += 1
        
        return result
    
    # ==================== 标签生成 ====================
    
    def _build_labels_prompt(
        self,
        title: str,
        abstract: str,
        keywords: List[str]
    ) -> str:
        """构建标签生成提示"""
        return f"""Generate semantic labels/tags for this academic paper.

PAPER:
Title: {title}
Abstract: {truncate_text(abstract or '', 400)}
Keywords: {', '.join(keywords)}

Generate 3-5 high-level semantic labels that describe:
- Research area
- Methodology
- Application domain
- Contribution type

Respond with ONLY a JSON object:
{{"labels": ["label1", "label2", ...], "labels_zh": ["标签1", "标签2", ...]}}"""
    
    async def extract_labels(
        self,
        paper_id: str,
        title: str,
        abstract: str,
        keywords: List[str],
        force: bool = False
    ) -> Optional[LabelsResult]:
        """
        生成标签
        
        Args:
            paper_id: 论文ID
            title: 标题
            abstract: 摘要
            keywords: 关键词列表
            force: 是否强制重新生成
            
        Returns:
            LabelsResult或None
        """
        cache_file = settings.get_llm_output_file("labels", paper_id)
        if cache_file.exists() and not force:
            data = await load_json(cache_file)
            if data:
                return LabelsResult(**data)
        
        prompt = self._build_labels_prompt(title, abstract, keywords)
        system = "You are a semantic label generator. Respond only with valid JSON. /no_think"
        
        response = await self.client.generate(
            model=self.model_small,
            prompt=prompt,
            system=system,
            temperature=0.3,
        )
        
        if not response:
            self.stats["labels"]["failure"] += 1
            return None
        
        parsed = safe_json_parse(response)
        if not parsed:
            self.stats["labels"]["failure"] += 1
            return None
        
        result = LabelsResult(
            paper_id=paper_id,
            labels=parsed.get("labels", [])[:5],
            labels_zh=parsed.get("labels_zh", [])[:5],
            raw_response=response,
        )
        
        await save_json(result.model_dump(), cache_file)
        self.stats["labels"]["success"] += 1
        
        return result
    
    # ==================== 段落评论 ====================
    
    def _build_comment_prompt(
        self,
        paper_title: str,
        section_title: str,
        paragraph: str,
        paragraph_index: int,
    ) -> str:
        """构建段落评论提示"""
        return f"""As an expert reader, provide reading notes for this paragraph from an academic paper.

PAPER: {paper_title}
SECTION: {section_title}
PARAGRAPH {paragraph_index}:
{truncate_text(paragraph, 800)}

Provide:
1. Key points (2-3 bullet points)
2. Reading notes (1-2 sentences about what readers should focus on)
3. Importance level (low/medium/high)

Respond with ONLY a JSON object:
{{
  "key_points": ["point1", "point2"],
  "reading_notes": "explanation",
  "importance": "medium"
}}"""
    
    async def generate_paragraph_comment(
        self,
        paper_title: str,
        section_title: str,
        paragraph: str,
        paragraph_index: int,
    ) -> Optional[ParagraphComment]:
        """
        生成单个段落的评论
        
        Args:
            paper_title: 论文标题
            section_title: 章节标题
            paragraph: 段落文本
            paragraph_index: 段落索引
            
        Returns:
            ParagraphComment或None
        """
        prompt = self._build_comment_prompt(
            paper_title, section_title, paragraph, paragraph_index
        )
        system = "You are an expert academic paper reader. Provide insightful reading notes. Respond only with valid JSON. /no_think"
        
        response = await self.client.generate(
            model=self.model_large,  # 使用大模型
            prompt=prompt,
            system=system,
            temperature=0.4,
            max_tokens=10000,
        )
        
        if not response:
            return None
        
        parsed = safe_json_parse(response)
        if not parsed:
            return None
        
        return ParagraphComment(
            paragraph_index=paragraph_index,
            paragraph_text=truncate_text(paragraph, 100),
            section_title=section_title,
            key_points=parsed.get("key_points", []),
            reading_notes=parsed.get("reading_notes", ""),
            importance=parsed.get("importance", "medium"),
            raw_response=response,
        )
    
    async def generate_comments(
        self,
        paper_id: str,
        content: Ar5ivContent,
        max_paragraphs: int = 20,
        force: bool = False
    ) -> Optional[CommentsResult]:
        """
        生成论文段落评论
        
        Args:
            paper_id: 论文ID
            content: 论文内容
            max_paragraphs: 最大处理段落数
            force: 是否强制重新生成
            
        Returns:
            CommentsResult或None
        """
        cache_file = settings.get_llm_output_file("comments", paper_id)
        if cache_file.exists() and not force:
            data = await load_json(cache_file)
            if data:
                return CommentsResult(**data)
        
        from scraper_ar5iv import get_all_paragraphs
        
        paragraphs = get_all_paragraphs(content)
        
        # 限制处理数量，优先选择重要段落
        # 筛选较长的段落（通常更重要）
        paragraphs = sorted(paragraphs, key=lambda x: len(x["text"]), reverse=True)
        paragraphs = paragraphs[:max_paragraphs]
        
        comments = []
        semaphore = asyncio.Semaphore(self.concurrency)
        
        async def process_paragraph(idx: int, para: Dict[str, str]):
            async with semaphore:
                comment = await self.generate_paragraph_comment(
                    content.title,
                    para["section_title"],
                    para["text"],
                    idx,
                )
                return comment
        
        tasks = [
            process_paragraph(i, para)
            for i, para in enumerate(paragraphs)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"段落评论生成失败: {result}")
            elif result:
                comments.append(result)
        
        if not comments:
            self.stats["comments"]["failure"] += 1
            return None
        
        # 生成总结
        summary = f"共分析 {len(comments)} 个关键段落，" \
                  f"高重要性: {sum(1 for c in comments if c.importance == 'high')} 个"
        
        result = CommentsResult(
            paper_id=paper_id,
            comments=comments,
            summary=summary,
        )
        
        await save_json(result.model_dump(), cache_file)
        self.stats["comments"]["success"] += 1
        
        return result
    
    # ==================== 批量处理 ====================
    
    async def process_paper(
        self,
        paper_id: str,
        title: str,
        abstract: str,
        content: Optional[Ar5ivContent] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        完整处理单篇论文
        
        Args:
            paper_id: 论文ID
            title: 标题
            abstract: 摘要
            content: 论文内容（用于生成评论）
            force: 是否强制重新处理
            
        Returns:
            处理结果字典
        """
        result = {
            "paper_id": paper_id,
            "classification": None,
            "keywords": None,
            "labels": None,
            "comments": None,
        }
        
        # 1. 分类
        classification = await self.classify_paper(paper_id, title, abstract, force)
        if classification:
            result["classification"] = classification.model_dump()
        
        # 2. 关键词
        keywords = await self.extract_keywords(paper_id, title, abstract, force)
        if keywords:
            result["keywords"] = keywords.model_dump()
        
        # 3. 标签
        keyword_list = keywords.keywords if keywords else []
        labels = await self.extract_labels(paper_id, title, abstract, keyword_list, force)
        if labels:
            result["labels"] = labels.model_dump()
        
        # 4. 评论（如果提供了内容）
        if content:
            comments = await self.generate_comments(paper_id, content, force=force)
            if comments:
                result["comments"] = comments.model_dump()
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.stats


async def main():
    """主函数，用于独立测试"""
    from utils import setup_logging
    
    setup_logging()
    settings.ensure_directories()
    
    logger.info("开始LLM处理器测试")
    
    processor = LLMProcessor()
    
    # 检查服务
    if not await processor.check_service():
        logger.error("Ollama服务不可用，请确保服务已启动")
        return
    
    # 测试分类
    test_title = "Attention Is All You Need"
    test_abstract = """
    The dominant sequence transduction models are based on complex recurrent or
    convolutional neural networks that include an encoder and a decoder. The best
    performing models also connect the encoder and decoder through an attention
    mechanism. We propose a new simple network architecture, the Transformer,
    based solely on attention mechanisms, dispensing with recurrence and convolutions
    entirely.
    """
    
    logger.info("测试分类...")
    classification = await processor.classify_paper(
        "1706.03762", test_title, test_abstract, force=True
    )
    if classification:
        logger.info(f"分类: {classification.category_name} ({classification.confidence:.2f})")
    
    logger.info("测试关键词提取...")
    keywords = await processor.extract_keywords(
        "1706.03762", test_title, test_abstract, force=True
    )
    if keywords:
        logger.info(f"关键词: {keywords.keywords}")
    
    logger.info("测试标签生成...")
    labels = await processor.extract_labels(
        "1706.03762", test_title, test_abstract,
        keywords.keywords if keywords else [], force=True
    )
    if labels:
        logger.info(f"标签: {labels.labels}")
    
    logger.info(f"\n统计: {processor.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())