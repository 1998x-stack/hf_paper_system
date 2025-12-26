"""
notion_client.py - Notion API 客户端模块

该模块负责与Notion API交互，创建数据库条目和页面。
遵循CleanRL设计原则：单一职责、显式依赖、易于测试。
"""

import sys
import asyncio
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

from notion_client import AsyncClient
from loguru import logger

from config import settings, PAPER_CATEGORIES
from models import (
    FullPaper,
    HFPaper,
    ClassificationResult,
    KeywordsResult,
    LabelsResult,
    CommentsResult,
    ParagraphComment,
)
from utils import format_exception, truncate_text


class NotionPaperClient:
    """
    Notion论文管理客户端
    
    负责：
    1. 创建/更新数据库条目
    2. 创建详细的论文页面
    3. 美观的页面布局
    """
    
    def __init__(
        self,
        token: str = None,
        database_id: str = None,
    ):
        """
        初始化客户端
        
        Args:
            token: Notion API token
            database_id: 数据库ID
        """
        self.token = token or settings.notion_token
        self.database_id = database_id or settings.notion_database_id
        
        if not self.token:
            raise ValueError("Notion token未配置")
        if not self.database_id:
            raise ValueError("Notion database_id未配置")
        
        self.client = AsyncClient(auth=self.token)
        
        # 统计
        self.created_count = 0
        self.updated_count = 0
        self.error_count = 0
    
    async def check_connection(self) -> bool:
        """检查连接"""
        try:
            await self.client.databases.retrieve(database_id=self.database_id)
            logger.info(f"Notion连接成功: {self.database_id[:8]}...")
            return True
        except Exception:
            error_message = format_exception()
            logger.error(f"Notion连接失败: {error_message}")
            return False
    
    # ==================== 数据库操作 ====================
    
    def _build_database_properties(self, paper: FullPaper) -> Dict[str, Any]:
        """构建数据库属性"""
        properties = {
            "Title": {
                "title": [{"text": {"content": truncate_text(paper.title, 100)}}]
            },
            "Paper ID": {
                "rich_text": [{"text": {"content": paper.paper_id}}]
            },
            "Authors": {
                "rich_text": [{"text": {"content": ", ".join(paper.authors[:5])}}]
            },
        }
        
        # 分类
        if paper.classification:
            properties["Category"] = {
                "select": {"name": paper.classification.category_name}
            }
        
        # 关键词
        if paper.keywords and paper.keywords.keywords:
            properties["Keywords"] = {
                "multi_select": [
                    {"name": kw[:100]} for kw in paper.keywords.keywords[:5]
                ]
            }
        
        # 标签
        if paper.labels and paper.labels.labels:
            properties["Labels"] = {
                "multi_select": [
                    {"name": label[:100]} for label in paper.labels.labels[:5]
                ]
            }
        
        # 投票数
        if paper.hf_metadata:
            properties["Upvotes"] = {
                "number": paper.hf_metadata.metrics.upvotes
            }
            
            # 组织
            if paper.hf_metadata.organization:
                properties["Organization"] = {
                    "rich_text": [{"text": {"content": paper.hf_metadata.organization.name}}]
                }
            
            # 月份
            properties["Month"] = {
                "rich_text": [{"text": {"content": paper.hf_metadata.month}}]
            }
        
        # 链接
        properties["arXiv URL"] = {
            "url": f"https://arxiv.org/abs/{paper.paper_id}"
        }
        properties["HuggingFace URL"] = {
            "url": f"https://huggingface.co/papers/{paper.paper_id}"
        }
        
        return properties
    
    def _build_page_content(self, paper: FullPaper) -> List[Dict[str, Any]]:
        """构建页面内容块"""
        blocks = []
        
        # ========== 标题横幅 ==========
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": f"📚 {paper.title}"}}],
                "icon": {"emoji": "📄"},
                "color": "blue_background"
            }
        })
        
        # ========== 元信息表格 ==========
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "📋 论文信息"}}]
            }
        })
        
        # 作者
        if paper.authors:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": "👥 作者: ", "annotations": {"bold": True}}},
                        {"text": {"content": ", ".join(paper.authors[:10])}}
                    ]
                }
            })
        
        # 分类和标签
        if paper.classification:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": "🏷️ 分类: ", "annotations": {"bold": True}}},
                        {"text": {"content": f"{paper.classification.category_name} ({paper.classification.category_name_zh})"}}
                    ]
                }
            })
        
        if paper.keywords and paper.keywords.keywords:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": "🔑 关键词: ", "annotations": {"bold": True}}},
                        {"text": {"content": ", ".join(paper.keywords.keywords)}}
                    ]
                }
            })
        
        if paper.labels and paper.labels.labels:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": "🏷️ 标签: ", "annotations": {"bold": True}}},
                        {"text": {"content": ", ".join(paper.labels.labels)}}
                    ]
                }
            })
        
        # 链接
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"text": {"content": "🔗 链接: ", "annotations": {"bold": True}}},
                    {"text": {"content": "arXiv", "link": {"url": f"https://arxiv.org/abs/{paper.paper_id}"}}},
                    {"text": {"content": " | "}},
                    {"text": {"content": "PDF", "link": {"url": f"https://arxiv.org/pdf/{paper.paper_id}.pdf"}}},
                    {"text": {"content": " | "}},
                    {"text": {"content": "ar5iv", "link": {"url": f"https://ar5iv.labs.arxiv.org/html/{paper.paper_id}"}}},
                    {"text": {"content": " | "}},
                    {"text": {"content": "HuggingFace", "link": {"url": f"https://huggingface.co/papers/{paper.paper_id}"}}},
                ]
            }
        })
        
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        
        # ========== 摘要 ==========
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "📝 摘要"}}]
            }
        })
        
        if paper.abstract:
            # 分段处理长摘要
            abstract_text = paper.abstract
            chunks = [abstract_text[i:i+2000] for i in range(0, len(abstract_text), 2000)]
            for chunk in chunks:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": chunk}}]
                    }
                })
        
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        
        # ========== 阅读笔记 ==========
        if paper.comments and paper.comments.comments:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "📖 阅读笔记"}}]
            }
            })
            
            # 总结
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": paper.comments.summary}}],
                    "icon": {"emoji": "💡"},
                    "color": "yellow_background"
                }
            })
            
            # 按章节组织评论
            current_section = ""
            for comment in paper.comments.comments:
                # 章节标题
                if comment.section_title != current_section:
                    current_section = comment.section_title
                    blocks.append({
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"text": {"content": f"📌 {current_section}"}}]
                        }
                    })
                
                # 重要性图标
                importance_emoji = {
                    "high": "🔴",
                    "medium": "🟡",
                    "low": "🟢"
                }.get(comment.importance, "⚪")
                
                # 段落评论
                blocks.append({
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": [
                            {"text": {"content": f"{importance_emoji} "}},
                            {"text": {"content": truncate_text(comment.paragraph_text, 80)}}
                        ],
                        "children": [
                            # 要点
                            {
                                "object": "block",
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {
                                    "rich_text": [
                                        {"text": {"content": "要点: ", "annotations": {"bold": True}}},
                                        {"text": {"content": " | ".join(comment.key_points)}}
                                    ]
                                }
                            },
                            # 阅读笔记
                            {
                                "object": "block",
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {
                                    "rich_text": [
                                        {"text": {"content": "笔记: ", "annotations": {"bold": True}}},
                                        {"text": {"content": comment.reading_notes}}
                                    ]
                                }
                            }
                        ]
                    }
                })
        
        # ========== 论文结构 ==========
        if paper.content and paper.content.sections:
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "📚 论文结构"}}]
                }
            })
            
            for section in paper.content.sections[:10]:  # 限制章节数
                blocks.append({
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": [{"text": {"content": f"📖 {section.title}"}}],
                        "children": [
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [{"text": {"content": truncate_text(para, 500)}}]
                                }
                            }
                            for para in section.paragraphs[:3]
                        ] if section.paragraphs else []
                    }
                })
        
        # ========== 图表 ==========
        if paper.content and paper.content.figures:
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": f"🖼️ 图表 ({len(paper.content.figures)})"}}]
                }
            })
            
            for i, fig in enumerate(paper.content.figures[:5]):
                if fig.src.startswith("http"):
                    blocks.append({
                        "object": "block",
                        "type": "image",
                        "image": {
                            "type": "external",
                            "external": {"url": fig.src}
                        }
                    })
                    if fig.caption:
                        blocks.append({
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"text": {"content": f"Figure {i+1}: {truncate_text(fig.caption, 200)}", "annotations": {"italic": True}}}]
                            }
                        })
        
        # ========== 页脚 ==========
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"text": {"content": f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "annotations": {"italic": True, "color": "gray"}}}
                ]
            }
        })
        
        return blocks
    
    async def create_page(self, paper: FullPaper) -> Optional[str]:
        """
        创建论文页面
        
        Args:
            paper: 完整论文数据
            
        Returns:
            页面ID或None
        """
        try:
            properties = self._build_database_properties(paper)
            blocks = self._build_page_content(paper)
            
            # Notion API限制每次最多100个blocks
            blocks = blocks[:100]
            
            response = await self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=blocks
            )
            
            page_id = response["id"]
            self.created_count += 1
            logger.info(f"创建页面成功: {paper.paper_id} -> {page_id[:8]}...")
            
            return page_id
            
        except Exception:
            error_message = format_exception()
            logger.error(f"创建页面失败 {paper.paper_id}: {error_message}")
            self.error_count += 1
            return None
    
    async def find_existing_page(self, paper_id: str) -> Optional[str]:
        """
        查找已存在的页面
        
        Args:
            paper_id: 论文ID
            
        Returns:
            页面ID或None
        """
        try:
            response = await self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Paper ID",
                    "rich_text": {"equals": paper_id}
                }
            )
            
            if response["results"]:
                return response["results"][0]["id"]
            return None
            
        except Exception:
            error_message = format_exception()
            logger.debug(f"查找页面失败 {paper_id}: {error_message}")
            return None
    
    async def update_page(self, page_id: str, paper: FullPaper) -> bool:
        """
        更新页面属性
        
        Args:
            page_id: 页面ID
            paper: 论文数据
            
        Returns:
            是否成功
        """
        try:
            properties = self._build_database_properties(paper)
            
            await self.client.pages.update(
                page_id=page_id,
                properties=properties
            )
            
            self.updated_count += 1
            logger.info(f"更新页面成功: {paper.paper_id}")
            return True
            
        except Exception:
            error_message = format_exception()
            logger.error(f"更新页面失败 {paper.paper_id}: {error_message}")
            self.error_count += 1
            return False
    
    async def sync_paper(
        self,
        paper: FullPaper,
        update_existing: bool = False
    ) -> Optional[str]:
        """
        同步论文到Notion
        
        Args:
            paper: 论文数据
            update_existing: 是否更新已存在的页面
            
        Returns:
            页面ID或None
        """
        # 检查是否存在
        existing_id = await self.find_existing_page(paper.paper_id)
        
        if existing_id:
            if update_existing:
                success = await self.update_page(existing_id, paper)
                return existing_id if success else None
            else:
                logger.debug(f"页面已存在，跳过: {paper.paper_id}")
                return existing_id
        else:
            return await self.create_page(paper)
    
    async def sync_papers(
        self,
        papers: List[FullPaper],
        update_existing: bool = False,
        delay: float = 0.5
    ) -> Dict[str, Any]:
        """
        批量同步论文
        
        Args:
            papers: 论文列表
            update_existing: 是否更新已存在的
            delay: 请求间隔
            
        Returns:
            同步结果统计
        """
        logger.info(f"开始同步 {len(papers)} 篇论文到Notion")
        
        results = {"synced": [], "failed": [], "skipped": []}
        
        for i, paper in enumerate(papers):
            logger.info(f"同步进度: {i+1}/{len(papers)}")
            
            try:
                page_id = await self.sync_paper(paper, update_existing)
                
                if page_id:
                    results["synced"].append(paper.paper_id)
                    paper.notion_page_id = page_id
                    paper.notion_synced_at = datetime.now()
                else:
                    results["failed"].append(paper.paper_id)
                    
            except Exception:
                error_message = format_exception()
                logger.error(f"同步失败 {paper.paper_id}: {error_message}")
                results["failed"].append(paper.paper_id)
            
            # 避免速率限制
            await asyncio.sleep(delay)
        
        logger.info(
            f"同步完成: 成功 {len(results['synced'])}, "
            f"失败 {len(results['failed'])}, "
            f"跳过 {len(results['skipped'])}"
        )
        
        return results
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计"""
        return {
            "created": self.created_count,
            "updated": self.updated_count,
            "errors": self.error_count
        }


async def setup_database_schema(client: NotionPaperClient) -> bool:
    """
    设置数据库schema（需要手动在Notion中创建）
    
    数据库应包含以下属性:
    - Title (title): 论文标题
    - Paper ID (rich_text): arXiv ID
    - Authors (rich_text): 作者
    - Category (select): 分类
    - Keywords (multi_select): 关键词
    - Labels (multi_select): 标签
    - Upvotes (number): 点赞数
    - Organization (rich_text): 组织
    - Month (rich_text): 月份
    - arXiv URL (url): arXiv链接
    - HuggingFace URL (url): HF链接
    """
    logger.info("""
请确保Notion数据库包含以下属性:
- Title (title): 论文标题
- Paper ID (rich_text): arXiv ID  
- Authors (rich_text): 作者
- Category (select): 分类
- Keywords (multi_select): 关键词
- Labels (multi_select): 标签
- Upvotes (number): 点赞数
- Organization (rich_text): 组织
- Month (rich_text): 月份
- arXiv URL (url): arXiv链接
- HuggingFace URL (url): HF链接
    """)
    return True


async def main():
    """主函数，用于独立测试"""
    from utils import setup_logging
    
    setup_logging()
    settings.ensure_directories()
    
    logger.info("开始Notion客户端测试")
    
    # 检查配置
    if not settings.notion_token:
        logger.error("请设置 NOTION_TOKEN 环境变量")
        return
    if not settings.notion_database_id:
        logger.error("请设置 NOTION_DATABASE_ID 环境变量")
        return
    
    client = NotionPaperClient()
    
    # 测试连接
    if not await client.check_connection():
        return
    
    # 创建测试论文
    from models import FullPaper, HFPaper, PaperMetrics, ClassificationResult, KeywordsResult
    
    test_paper = FullPaper(
        paper_id="1706.03762",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
        hf_metadata=HFPaper(
            paper_id="1706.03762",
            title="Attention Is All You Need",
            url="https://huggingface.co/papers/1706.03762",
            arxiv_url="https://arxiv.org/abs/1706.03762",
            ar5iv_url="https://ar5iv.labs.arxiv.org/html/1706.03762",
            month="2017-06",
            metrics=PaperMetrics(upvotes=1000, comments=50)
        ),
        classification=ClassificationResult(
            paper_id="1706.03762",
            category="language_models",
            category_name="Language Models",
            category_name_zh="语言模型",
            confidence=0.95,
            raw_response=""
        ),
        keywords=KeywordsResult(
            paper_id="1706.03762",
            keywords=["transformer", "attention", "encoder-decoder", "machine translation"],
            raw_response=""
        )
    )
    
    # 同步测试
    page_id = await client.sync_paper(test_paper)
    if page_id:
        logger.info(f"测试页面创建成功: {page_id}")
    
    logger.info(f"统计: {client.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())