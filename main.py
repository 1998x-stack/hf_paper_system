"""
main.py - 主程序入口

该模块是系统的主要入口点，负责协调各组件的工作流程。
遵循CleanRL设计原则：单文件、完整可运行、清晰的执行流程。

Usage:
    python main.py --start-month 2024-01 --end-month 2025-12 --min-votes 50
    python main.py --mode scrape
    python main.py --mode process
    python main.py --mode sync
"""

import sys
import asyncio
import argparse
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from loguru import logger

from config import settings, PAPER_CATEGORIES
from models import (
    HFPaper,
    FullPaper,
    Ar5ivContent,
    ProcessingStats,
)
from utils import (
    setup_logging,
    generate_months,
    save_json,
    load_json,
    save_jsonl,
    load_jsonl,
    format_exception,
    ProgressTracker,
)
from scraper_hf import HFPapersScraper, load_existing_papers
from scraper_ar5iv import Ar5ivExtractor
from llm_processor import LLMProcessor
from notion_client_hf import NotionPaperClient


class PaperPipeline:
    """
    论文处理流水线
    
    整合所有组件，提供完整的数据处理流程：
    1. 爬取HuggingFace论文列表
    2. 提取ar5iv论文内容
    3. LLM分析（分类、关键词、标签、评论）
    4. 同步到Notion
    """
    
    def __init__(
        self,
        start_month: str = None,
        end_month: str = None,
        min_votes: int = None,
        concurrency: int = None,
    ):
        """
        初始化流水线
        
        Args:
            start_month: 起始月份
            end_month: 结束月份
            min_votes: 最小投票数
            concurrency: 并发数
        """
        self.start_month = start_month or settings.start_month
        self.end_month = end_month or settings.end_month
        self.min_votes = min_votes or settings.min_votes
        self.concurrency = concurrency or settings.concurrency
        
        # 组件
        self.hf_scraper = HFPapersScraper(
            min_votes=self.min_votes,
            concurrency=self.concurrency,
        )
        self.ar5iv_extractor = Ar5ivExtractor(
            concurrency=self.concurrency,
        )
        self.llm_processor = LLMProcessor(
            concurrency=self.concurrency,
        )
        self.notion_client: Optional[NotionPaperClient] = None
        
        # 统计
        self.stats = ProcessingStats()
    
    def _init_notion(self) -> bool:
        """初始化Notion客户端"""
        if not settings.notion_token or not settings.notion_database_id:
            logger.warning("Notion配置不完整，跳过Notion同步")
            return False
        
        try:
            self.notion_client = NotionPaperClient()
            return True
        except Exception:
            error_message = format_exception()
            logger.error(f"Notion初始化失败: {error_message}")
            return False
    
    async def step1_scrape_hf(self, force: bool = False) -> List[HFPaper]:
        """
        步骤1: 爬取HuggingFace论文
        
        Args:
            force: 是否强制重新爬取
            
        Returns:
            论文列表
        """
        logger.info("=" * 60)
        logger.info("步骤1: 爬取HuggingFace Papers")
        logger.info("=" * 60)
        
        months = list(generate_months(self.start_month, self.end_month))
        
        if not force:
            # 检查已有数据
            existing = await load_existing_papers(months)
            if existing:
                logger.info(f"发现已有数据: {len(existing)} 篇论文")
                self.stats.total_papers = len(existing)
                return existing
        
        papers = await self.hf_scraper.scrape_range(self.start_month, self.end_month)
        self.stats.total_papers = len(papers)
        
        logger.info(f"爬取完成: {len(papers)} 篇论文 (votes >= {self.min_votes})")
        
        return papers
    
    async def step2_extract_ar5iv(
        self,
        papers: List[HFPaper],
        force: bool = False
    ) -> Dict[str, Ar5ivContent]:
        """
        步骤2: 提取ar5iv内容
        
        Args:
            papers: HF论文列表
            force: 是否强制重新提取
            
        Returns:
            {paper_id: Ar5ivContent} 映射
        """
        logger.info("=" * 60)
        logger.info("步骤2: 提取ar5iv论文内容")
        logger.info("=" * 60)
        
        paper_ids = [p.paper_id for p in papers]
        
        # 检查缓存
        if not force:
            cached = {}
            for pid in paper_ids:
                cache_file = settings.get_ar5iv_file(pid)
                if cache_file.exists():
                    data = await load_json(cache_file)
                    if data:
                        cached[pid] = Ar5ivContent(**data)
            
            if cached:
                logger.info(f"使用缓存: {len(cached)} 篇")
            
            # 只提取未缓存的
            paper_ids = [pid for pid in paper_ids if pid not in cached]
            
            if not paper_ids:
                self.stats.ar5iv_extracted = len(cached)
                return cached
        else:
            cached = {}
        
        logger.info(f"需要提取: {len(paper_ids)} 篇")
        
        contents = await self.ar5iv_extractor.extract_papers(paper_ids, force)
        
        result = {c.paper_id: c for c in contents}
        result.update(cached)
        
        self.stats.ar5iv_extracted = len(result)
        
        logger.info(f"提取完成: {len(result)} 篇成功")
        
        return result
    
    async def step3_llm_process(
        self,
        papers: List[HFPaper],
        contents: Dict[str, Ar5ivContent],
        force: bool = False
    ) -> List[FullPaper]:
        """
        步骤3: LLM处理
        
        Args:
            papers: HF论文列表
            contents: ar5iv内容映射
            force: 是否强制重新处理
            
        Returns:
            完整论文列表
        """
        logger.info("=" * 60)
        logger.info("步骤3: LLM分析（分类、关键词、标签、评论）")
        logger.info("=" * 60)
        
        # 检查LLM服务
        if not await self.llm_processor.check_service():
            logger.warning("Ollama服务不可用，跳过LLM处理")
            # 返回不带LLM结果的论文
            full_papers = []
            for paper in papers:
                content = contents.get(paper.paper_id)
                full = FullPaper(
                    paper_id=paper.paper_id,
                    title=paper.title,
                    authors=content.authors if content else [],
                    abstract=content.abstract if content else None,
                    hf_metadata=paper,
                    content=content,
                )
                full_papers.append(full)
            return full_papers
        
        full_papers = []
        tracker = ProgressTracker(len(papers), "LLM处理")
        
        for paper in papers:
            content = contents.get(paper.paper_id)
            
            # 获取标题和摘要
            title = paper.title
            abstract = content.abstract if content else None
            
            if not abstract:
                logger.warning(f"论文无摘要，跳过LLM处理: {paper.paper_id}")
                full = FullPaper(
                    paper_id=paper.paper_id,
                    title=title,
                    authors=content.authors if content else [],
                    abstract=abstract,
                    hf_metadata=paper,
                    content=content,
                )
                full_papers.append(full)
                tracker.update(error=True)
                continue
            
            try:
                # LLM处理
                result = await self.llm_processor.process_paper(
                    paper.paper_id,
                    title,
                    abstract,
                    content,  # 用于生成评论
                    force=force
                )
                
                # 构建FullPaper
                from models import ClassificationResult, KeywordsResult, LabelsResult, CommentsResult
                
                full = FullPaper(
                    paper_id=paper.paper_id,
                    title=title,
                    authors=content.authors if content else [],
                    abstract=abstract,
                    hf_metadata=paper,
                    content=content,
                    classification=ClassificationResult(**result["classification"]) if result.get("classification") else None,
                    keywords=KeywordsResult(**result["keywords"]) if result.get("keywords") else None,
                    labels=LabelsResult(**result["labels"]) if result.get("labels") else None,
                    comments=CommentsResult(**result["comments"]) if result.get("comments") else None,
                )
                
                # 保存完整论文
                save_path = settings.get_processed_file(paper.paper_id)
                await save_json(full.model_dump(), save_path)
                
                full_papers.append(full)
                tracker.update()
                
            except Exception:
                error_message = format_exception()
                logger.error(f"LLM处理失败 {paper.paper_id}: {error_message}")
                self.stats.errors.append({
                    "paper_id": paper.paper_id,
                    "stage": "llm",
                    "error": error_message
                })
                tracker.update(error=True)
        
        finish_stats = tracker.finish()
        self.stats.classified = finish_stats["completed"] - finish_stats["errors"]
        
        logger.info(f"LLM处理完成: {len(full_papers)} 篇")
        
        return full_papers
    
    async def step4_sync_notion(
        self,
        papers: List[FullPaper],
        update_existing: bool = False
    ) -> Dict[str, Any]:
        """
        步骤4: 同步到Notion
        
        Args:
            papers: 完整论文列表
            update_existing: 是否更新已存在的
            
        Returns:
            同步结果
        """
        logger.info("=" * 60)
        logger.info("步骤4: 同步到Notion")
        logger.info("=" * 60)
        
        if not self.notion_client:
            if not self._init_notion():
                logger.warning("跳过Notion同步")
                return {"skipped": True}
        
        if not await self.notion_client.check_connection():
            logger.error("Notion连接失败")
            return {"error": "connection_failed"}
        
        result = await self.notion_client.sync_papers(papers, update_existing)
        self.stats.notion_synced = len(result.get("synced", []))
        
        return result
    
    async def run_full_pipeline(
        self,
        scrape: bool = True,
        extract: bool = True,
        process: bool = True,
        sync: bool = True,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        运行完整流水线
        
        Args:
            scrape: 是否爬取
            extract: 是否提取
            process: 是否LLM处理
            sync: 是否同步Notion
            force: 是否强制重新处理
            
        Returns:
            执行结果
        """
        start_time = datetime.now()
        
        logger.info("*" * 60)
        logger.info("HuggingFace Papers 处理流水线")
        logger.info(f"日期范围: {self.start_month} 到 {self.end_month}")
        logger.info(f"投票阈值: >= {self.min_votes}")
        logger.info(f"并发数: {self.concurrency}")
        logger.info("*" * 60)
        
        papers = []
        contents = {}
        full_papers = []
        
        try:
            # 步骤1: 爬取
            if scrape:
                papers = await self.step1_scrape_hf(force)
            else:
                # 从文件加载
                months = list(generate_months(self.start_month, self.end_month))
                papers = await load_existing_papers(months)
                self.stats.total_papers = len(papers)
            
            if not papers:
                logger.warning("没有论文需要处理")
                return {"status": "no_papers"}
            
            # 步骤2: 提取
            if extract:
                contents = await self.step2_extract_ar5iv(papers, force)
            
            # 步骤3: LLM处理
            if process:
                full_papers = await self.step3_llm_process(papers, contents, force)
            else:
                # 构建简单的FullPaper
                for paper in papers:
                    content = contents.get(paper.paper_id)
                    full = FullPaper(
                        paper_id=paper.paper_id,
                        title=paper.title,
                        authors=content.authors if content else [],
                        abstract=content.abstract if content else None,
                        hf_metadata=paper,
                        content=content,
                    )
                    full_papers.append(full)
            
            # 步骤4: 同步Notion
            if sync:
                await self.step4_sync_notion(full_papers)
            
        except Exception:
            error_message = format_exception()
            logger.error(f"流水线执行失败: {error_message}")
            return {"status": "error", "error": error_message}
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # 最终统计
        result = {
            "status": "success",
            "duration_seconds": duration,
            "stats": {
                "total_papers": self.stats.total_papers,
                "ar5iv_extracted": self.stats.ar5iv_extracted,
                "classified": self.stats.classified,
                "notion_synced": self.stats.notion_synced,
                "errors": len(self.stats.errors),
            },
            "errors": self.stats.errors[:10],  # 只保留前10个错误
        }
        
        logger.info("*" * 60)
        logger.info("流水线执行完成")
        logger.info(f"总耗时: {duration:.1f} 秒")
        logger.info(f"论文总数: {self.stats.total_papers}")
        logger.info(f"ar5iv提取: {self.stats.ar5iv_extracted}")
        logger.info(f"LLM分类: {self.stats.classified}")
        logger.info(f"Notion同步: {self.stats.notion_synced}")
        logger.info(f"错误数: {len(self.stats.errors)}")
        logger.info("*" * 60)
        
        # 保存执行报告
        report_file = settings.data_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        await save_json(result, report_file)
        logger.info(f"报告已保存: {report_file}")
        
        return result


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="HuggingFace Papers 聚合处理系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整流水线
  python main.py

  # 只爬取
  python main.py --mode scrape

  # 只LLM处理
  python main.py --mode process

  # 只同步Notion
  python main.py --mode sync

  # 指定日期范围
  python main.py --start-month 2024-06 --end-month 2024-12

  # 强制重新处理
  python main.py --force
        """
    )
    
    parser.add_argument(
        "--mode",
        choices=["full", "scrape", "extract", "process", "sync"],
        default="full",
        help="运行模式 (default: full)"
    )
    
    parser.add_argument(
        "--start-month",
        default=settings.start_month,
        help=f"起始月份 YYYY-MM (default: {settings.start_month})"
    )
    
    parser.add_argument(
        "--end-month",
        default=settings.end_month,
        help=f"结束月份 YYYY-MM (default: {settings.end_month})"
    )
    
    parser.add_argument(
        "--min-votes",
        type=int,
        default=settings.min_votes,
        help=f"最小投票数 (default: {settings.min_votes})"
    )
    
    parser.add_argument(
        "--concurrency",
        type=int,
        default=settings.concurrency,
        help=f"并发数 (default: {settings.concurrency})"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新处理已有数据"
    )
    
    parser.add_argument(
        "--update-notion",
        action="store_true",
        help="更新已存在的Notion页面"
    )
    
    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_args()
    
    # 初始化
    setup_logging()
    settings.ensure_directories()
    
    logger.info("HuggingFace Papers 聚合处理系统")
    logger.info(f"模式: {args.mode}")
    logger.info(f"日期范围: {args.start_month} 到 {args.end_month}")
    logger.info(f"投票阈值: >= {args.min_votes}")
    
    # 创建流水线
    pipeline = PaperPipeline(
        start_month=args.start_month,
        end_month=args.end_month,
        min_votes=args.min_votes,
        concurrency=args.concurrency,
    )
    
    # 根据模式运行
    mode_config = {
        "full": {"scrape": True, "extract": True, "process": True, "sync": True},
        "scrape": {"scrape": True, "extract": False, "process": False, "sync": False},
        "extract": {"scrape": False, "extract": True, "process": False, "sync": False},
        "process": {"scrape": False, "extract": True, "process": True, "sync": False},
        "sync": {"scrape": False, "extract": False, "process": True, "sync": True},
    }
    
    config = mode_config[args.mode]
    
    result = await pipeline.run_full_pipeline(
        **config,
        force=args.force
    )
    
    if result.get("status") == "error":
        logger.error(f"执行失败: {result.get('error')}")
        sys.exit(1)
    
    logger.info("执行完成!")


if __name__ == "__main__":
    asyncio.run(main())