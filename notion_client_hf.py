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


# ==================== Helper Functions ====================

def rich_text(
    content: str,
    bold: bool = False,
    italic: bool = False,
    color: str = None,
    link: str = None
) -> Dict[str, Any]:
    """
    创建Notion rich_text对象
    
    Args:
        content: 文本内容
        bold: 是否加粗
        italic: 是否斜体
        color: 颜色
        link: 链接URL
        
    Returns:
        Notion rich_text对象
    
    注意: annotations 必须与 text 同级，不能放在 text 内部
    """
    text_obj = {"content": content}
    if link:
        text_obj["link"] = {"url": link}
    
    result = {
        "type": "text",
        "text": text_obj
    }
    
    # 只在需要时添加annotations
    annotations = {}
    if bold:
        annotations["bold"] = True
    if italic:
        annotations["italic"] = True
    if color:
        annotations["color"] = color
    
    if annotations:
        result["annotations"] = annotations
    
    return result


def simple_text(content: str) -> Dict[str, Any]:
    """简单文本，无格式"""
    return {"type": "text", "text": {"content": content}}


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
        
        # 数据库schema缓存
        self._db_schema: Dict[str, Any] = {}
        self._title_property: str = "Name"  # 默认标题属性名
        
        # 统计
        self.created_count = 0
        self.updated_count = 0
        self.error_count = 0
    
    async def check_connection(self) -> bool:
        """检查连接并获取数据库schema"""
        try:
            db_info = await self.client.databases.retrieve(database_id=self.database_id)
            
            # 解析数据库属性
            self._db_schema = {}
            for prop_name, prop_info in db_info.get("properties", {}).items():
                prop_type = prop_info.get("type")
                self._db_schema[prop_name] = prop_type
                
                # 找到title属性
                if prop_type == "title":
                    self._title_property = prop_name
            
            logger.info(f"Notion连接成功: {self.database_id[:8]}...")
            logger.info(f"数据库标题属性: {self._title_property}")
            logger.info(f"可用属性: {list(self._db_schema.keys())}")
            
            # 自动创建缺失属性
            await self._auto_create_missing_properties()
            
            return True
        except Exception:
            error_message = format_exception()
            logger.error(f"Notion连接失败: {error_message}")
            return False
    
    async def _auto_create_missing_properties(self):
        """自动创建缺失的推荐属性"""
        # 定义需要的属性及其配置
        required_properties = {
            "Paper ID": {"rich_text": {}},
            "Authors": {"rich_text": {}},
            "Category": {"select": {"options": [
                {"name": "Language Models", "color": "blue"},
                {"name": "Computer Vision", "color": "green"},
                {"name": "Multimodal", "color": "purple"},
                {"name": "Reinforcement Learning", "color": "orange"},
                {"name": "Generative Models", "color": "pink"},
                {"name": "NLP", "color": "yellow"},
                {"name": "Speech", "color": "red"},
                {"name": "Robotics", "color": "gray"},
                {"name": "Graph Neural Networks", "color": "brown"},
                {"name": "Optimization", "color": "default"},
                {"name": "Other", "color": "default"},
            ]}},
            "Keywords": {"multi_select": {"options": []}},
            "Labels": {"multi_select": {"options": []}},
            "Upvotes": {"number": {"format": "number"}},
            "Organization": {"rich_text": {}},
            "Month": {"rich_text": {}},
            "arXiv URL": {"url": {}},
            "HuggingFace URL": {"url": {}},
        }
        
        # 找出缺失的属性
        missing = {
            name: config 
            for name, config in required_properties.items() 
            if name not in self._db_schema
        }
        
        if not missing:
            logger.info("✅ 数据库schema完整")
            return True
        
        logger.info(f"🔧 自动创建 {len(missing)} 个缺失属性: {list(missing.keys())}")
        
        try:
            # 使用 databases.update API 添加属性
            result = await self.client.databases.update(
                database_id=self.database_id,
                properties=missing
            )
            logger.info(f"✅ 成功创建属性: {list(missing.keys())}")
            
            # 重新获取数据库schema以确保同步
            db_info = await self.client.databases.retrieve(database_id=self.database_id)
            self._db_schema = {}
            for prop_name, prop_info in db_info.get("properties", {}).items():
                prop_type = prop_info.get("type")
                self._db_schema[prop_name] = prop_type
            
            logger.info(f"📋 更新后的属性: {list(self._db_schema.keys())}")
            return True
                
        except Exception as e:
            error_message = format_exception()
            logger.warning(f"⚠️ 自动创建属性失败: {error_message}")
            logger.warning("可能原因: Integration没有数据库编辑权限")
            self._print_manual_setup_guide(missing)
            return False
    
    def _print_manual_setup_guide(self, missing: Dict[str, Any]):
        """打印手动设置指南"""
        type_names = {
            "rich_text": "Text/文本",
            "select": "Select/单选",
            "multi_select": "Multi-select/多选",
            "number": "Number/数字",
            "url": "URL/链接",
        }
        
        lines = ["请在Notion中手动添加以下属性:"]
        for name, config in missing.items():
            prop_type = list(config.keys())[0]
            type_name = type_names.get(prop_type, prop_type)
            lines.append(f"  - {name} ({type_name})")
        
        lines.extend([
            "",
            "操作步骤:",
            "1. 打开您的Notion数据库",
            "2. 点击表头右侧的 '+' 添加新属性", 
            "3. 输入属性名称，选择属性类型",
            "4. 重复以上步骤添加所有属性",
        ])
        
        logger.info("\n".join(lines))
    
    def _check_recommended_properties(self):
        """检查推荐的属性是否存在（已废弃，使用_auto_create_missing_properties）"""
        pass
    
    def _has_property(self, name: str, expected_type: str = None) -> bool:
        """检查属性是否存在且类型匹配"""
        if name not in self._db_schema:
            return False
        if expected_type and self._db_schema[name] != expected_type:
            return False
        return True
    
    # ==================== 数据库操作 ====================
    
    def _build_database_properties(self, paper: FullPaper) -> Dict[str, Any]:
        """构建数据库属性（只使用存在的属性）"""
        properties = {}
        
        # 检查schema是否已加载
        if not self._db_schema:
            logger.warning("⚠️ 数据库schema未加载，只使用标题属性")
        
        # 标题（必须）- 使用检测到的标题属性名
        properties[self._title_property] = {
            "title": [{"text": {"content": truncate_text(paper.title, 100)}}]
        }
        
        # Paper ID
        if self._has_property("Paper ID", "rich_text"):
            properties["Paper ID"] = {
                "rich_text": [{"text": {"content": paper.paper_id}}]
            }
        
        # Authors
        if self._has_property("Authors", "rich_text") and paper.authors:
            properties["Authors"] = {
                "rich_text": [{"text": {"content": ", ".join(paper.authors[:5])}}]
            }
        
        # 分类
        if self._has_property("Category", "select") and paper.classification:
            properties["Category"] = {
                "select": {"name": paper.classification.category_name}
            }
        
        # 关键词
        if self._has_property("Keywords", "multi_select") and paper.keywords and paper.keywords.keywords:
            properties["Keywords"] = {
                "multi_select": [
                    {"name": kw[:100]} for kw in paper.keywords.keywords[:5]
                ]
            }
        
        # 标签
        if self._has_property("Labels", "multi_select") and paper.labels and paper.labels.labels:
            properties["Labels"] = {
                "multi_select": [
                    {"name": label[:100]} for label in paper.labels.labels[:5]
                ]
            }
        
        # HF元数据相关属性
        if paper.hf_metadata:
            # 投票数
            if self._has_property("Upvotes", "number"):
                properties["Upvotes"] = {
                    "number": paper.hf_metadata.metrics.upvotes
                }
            
            # 组织
            if self._has_property("Organization", "rich_text") and paper.hf_metadata.organization:
                properties["Organization"] = {
                    "rich_text": [{"text": {"content": paper.hf_metadata.organization.name}}]
                }
            
            # 月份
            if self._has_property("Month", "rich_text"):
                properties["Month"] = {
                    "rich_text": [{"text": {"content": paper.hf_metadata.month}}]
                }
        
        # 链接
        if self._has_property("arXiv URL", "url"):
            properties["arXiv URL"] = {
                "url": f"https://arxiv.org/abs/{paper.paper_id}"
            }
        if self._has_property("HuggingFace URL", "url"):
            properties["HuggingFace URL"] = {
                "url": f"https://huggingface.co/papers/{paper.paper_id}"
            }
        
        logger.debug(f"📝 使用的属性: {list(properties.keys())}")
        
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
                        {
                            "type": "text",
                            "text": {"content": "👥 作者: "},
                            "annotations": {"bold": True}
                        },
                        {
                            "type": "text",
                            "text": {"content": ", ".join(paper.authors[:10])}
                        }
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
                        {
                            "type": "text",
                            "text": {"content": "🏷️ 分类: "},
                            "annotations": {"bold": True}
                        },
                        {
                            "type": "text",
                            "text": {"content": f"{paper.classification.category_name} ({paper.classification.category_name_zh})"}
                        }
                    ]
                }
            })
        
        if paper.keywords and paper.keywords.keywords:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "🔑 关键词: "},
                            "annotations": {"bold": True}
                        },
                        {
                            "type": "text",
                            "text": {"content": ", ".join(paper.keywords.keywords)}
                        }
                    ]
                }
            })
        
        if paper.labels and paper.labels.labels:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "🏷️ 标签: "},
                            "annotations": {"bold": True}
                        },
                        {
                            "type": "text",
                            "text": {"content": ", ".join(paper.labels.labels)}
                        }
                    ]
                }
            })
        
        # 链接
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": "🔗 链接: "},
                        "annotations": {"bold": True}
                    },
                    {
                        "type": "text",
                        "text": {"content": "arXiv", "link": {"url": f"https://arxiv.org/abs/{paper.paper_id}"}}
                    },
                    {
                        "type": "text",
                        "text": {"content": " | "}
                    },
                    {
                        "type": "text",
                        "text": {"content": "PDF", "link": {"url": f"https://arxiv.org/pdf/{paper.paper_id}.pdf"}}
                    },
                    {
                        "type": "text",
                        "text": {"content": " | "}
                    },
                    {
                        "type": "text",
                        "text": {"content": "ar5iv", "link": {"url": f"https://ar5iv.labs.arxiv.org/html/{paper.paper_id}"}}
                    },
                    {
                        "type": "text",
                        "text": {"content": " | "}
                    },
                    {
                        "type": "text",
                        "text": {"content": "HuggingFace", "link": {"url": f"https://huggingface.co/papers/{paper.paper_id}"}}
                    },
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
                            {"type": "text", "text": {"content": f"{importance_emoji} "}},
                            {"type": "text", "text": {"content": truncate_text(comment.paragraph_text, 80)}}
                        ],
                        "children": [
                            # 要点
                            {
                                "object": "block",
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {
                                    "rich_text": [
                                        {
                                            "type": "text",
                                            "text": {"content": "要点: "},
                                            "annotations": {"bold": True}
                                        },
                                        {
                                            "type": "text",
                                            "text": {"content": " | ".join(comment.key_points)}
                                        }
                                    ]
                                }
                            },
                            # 阅读笔记
                            {
                                "object": "block",
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {
                                    "rich_text": [
                                        {
                                            "type": "text",
                                            "text": {"content": "笔记: "},
                                            "annotations": {"bold": True}
                                        },
                                        {
                                            "type": "text",
                                            "text": {"content": comment.reading_notes}
                                        }
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
                                "rich_text": [{
                                    "type": "text",
                                    "text": {"content": f"Figure {i+1}: {truncate_text(fig.caption, 200)}"},
                                    "annotations": {"italic": True}
                                }]
                            }
                        })
        
        # ========== 页脚 ==========
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"},
                        "annotations": {"italic": True, "color": "gray"}
                    }
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
            # 确保已加载数据库schema
            if not self._db_schema:
                logger.info("📡 首次创建，加载数据库schema...")
                success = await self.check_connection()
                if not success:
                    logger.error("❌ 无法加载数据库schema")
                    return None
            
            logger.info(f"📋 当前可用属性: {list(self._db_schema.keys())}")
            
            properties = self._build_database_properties(paper)
            blocks = self._build_page_content(paper)
            
            logger.info(f"📝 将要使用的属性: {list(properties.keys())}")
            
            # Notion API限制每次最多100个blocks
            blocks = blocks[:100]
            
            response = await self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=blocks
            )
            
            page_id = response["id"]
            self.created_count += 1
            logger.info(f"✅ 创建页面成功: {paper.paper_id} -> {page_id[:8]}...")
            
            return page_id
            
        except Exception:
            error_message = format_exception()
            logger.error(f"❌ 创建页面失败 {paper.paper_id}: {error_message}")
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
            # 如果有Paper ID属性，按Paper ID查找
            if self._has_property("Paper ID", "rich_text"):
                response = await self.client.databases.query(
                    database_id=self.database_id,
                    filter={
                        "property": "Paper ID",
                        "rich_text": {"equals": paper_id}
                    }
                )
            else:
                # 否则按标题查找（可能不准确，但是兜底方案）
                response = await self.client.databases.query(
                    database_id=self.database_id,
                    filter={
                        "property": self._title_property,
                        "title": {"contains": paper_id}
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
        # 确保已加载数据库schema
        if not self._db_schema:
            await self.check_connection()
        
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
    设置数据库schema（自动创建缺失属性）
    
    调用 check_connection 会自动创建缺失属性。
    此函数提供额外的验证。
    
    数据库将包含以下属性:
    - Title (title): 论文标题 (自动存在)
    - Paper ID (rich_text): arXiv ID
    - Authors (rich_text): 作者
    - Category (select): 分类（预设11个类别）
    - Keywords (multi_select): 关键词
    - Labels (multi_select): 标签
    - Upvotes (number): 点赞数
    - Organization (rich_text): 组织
    - Month (rich_text): 月份
    - arXiv URL (url): arXiv链接
    - HuggingFace URL (url): HF链接
    """
    # check_connection 会自动创建缺失属性
    if not await client.check_connection():
        return False
    
    # 验证所有属性都已创建
    required = ["Paper ID", "Authors", "Category", "Keywords", "Labels", 
                "Upvotes", "Organization", "Month", "arXiv URL", "HuggingFace URL"]
    
    missing = [p for p in required if p not in client._db_schema]
    
    if missing:
        logger.warning(f"以下属性未能自动创建: {missing}")
        logger.warning("请手动在Notion中添加这些属性")
        return False
    
    logger.info("✅ 数据库schema设置完成")
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
    
    # 测试连接并设置schema
    if not await client.check_connection():
        return
    
    # 尝试自动创建缺失属性
    await setup_database_schema(client)
    
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