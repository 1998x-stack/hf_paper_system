"""
scraper_hf.py - HuggingFace Papers 爬虫模块

该模块负责从HuggingFace Papers页面爬取论文列表。
遵循CleanRL设计原则：单一职责、显式依赖、易于测试。
"""

import re
import sys
import asyncio
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiohttp
from bs4 import BeautifulSoup
from loguru import logger

from config import settings
from models import HFPaper, PaperMetrics, Organization, ScrapingStats
from utils import (
    generate_months,
    save_jsonl,
    load_jsonl,
    build_hf_monthly_url,
    build_arxiv_url,
    build_ar5iv_url,
    format_exception,
    gather_with_concurrency,
)


class HFPapersScraper:
    """
    HuggingFace Papers 爬虫
    
    负责从HuggingFace月度论文页面爬取论文列表。
    支持异步并发、自动重试、进度追踪。
    """
    
    def __init__(
        self,
        min_votes: int = 50,
        concurrency: int = 3,
        request_delay: float = 1.0,
        max_retries: int = 3,
    ):
        """
        初始化爬虫
        
        Args:
            min_votes: 最小投票数阈值
            concurrency: 并发数
            request_delay: 请求间隔（秒）
            max_retries: 最大重试次数
        """
        self.min_votes = min_votes
        self.concurrency = concurrency
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.user_agent = settings.user_agent
        
        # 统计信息
        self.stats: Dict[str, ScrapingStats] = {}
    
    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        url: str,
        retry_count: int = 0
    ) -> Optional[str]:
        """
        获取页面HTML
        
        Args:
            session: aiohttp会话
            url: 页面URL
            retry_count: 当前重试次数
            
        Returns:
            HTML内容或None
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        try:
            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status == 200:
                    # 确保正确处理编码
                    content = await response.read()
                    # 尝试UTF-8解码
                    try:
                        return content.decode('utf-8')
                    except UnicodeDecodeError:
                        return content.decode('utf-8', errors='replace')
                elif response.status == 429:
                    # 速率限制，等待后重试
                    wait_time = 60 * (retry_count + 1)
                    logger.warning(f"速率限制，等待 {wait_time} 秒: {url}")
                    await asyncio.sleep(wait_time)
                    if retry_count < self.max_retries:
                        return await self._fetch_page(session, url, retry_count + 1)
                else:
                    logger.warning(f"HTTP {response.status}: {url}")
                    
        except asyncio.TimeoutError:
            logger.warning(f"请求超时: {url}")
            if retry_count < self.max_retries:
                await asyncio.sleep(5 * (retry_count + 1))
                return await self._fetch_page(session, url, retry_count + 1)
                
        except Exception:
            error_message = format_exception()
            logger.error(f"请求失败 {url}: {error_message}")
            
        return None
    
    def _parse_papers(self, html: str, month: str) -> List[HFPaper]:
        """
        解析HTML提取论文列表
        
        Args:
            html: 页面HTML
            month: 所属月份
            
        Returns:
            论文列表
        """
        soup = BeautifulSoup(html, "html.parser")
        papers = []
        seen_ids = set()  # 去重
        
        # 查找所有论文链接
        paper_links = soup.find_all("a", href=re.compile(r"^/papers/\d{4}\.\d{4,5}$"))
        
        for link in paper_links:
            try:
                paper_id = link["href"].split("/")[-1]
                
                # 跳过重复
                if paper_id in seen_ids:
                    continue
                seen_ids.add(paper_id)
                
                # 获取标题
                title = link.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                
                # 向上查找论文卡片容器
                container = self._find_paper_container(link)
                if not container:
                    continue
                
                # 提取各项信息
                thumbnail = self._extract_thumbnail(container)
                submitter = self._extract_submitter(container)
                upvotes = self._extract_upvotes(container, paper_id)
                organization = self._extract_organization(container, link)
                comments = self._extract_comments(container, paper_id)
                has_video = self._check_has_video(container)
                
                # 创建论文对象
                paper = HFPaper(
                    paper_id=paper_id,
                    title=title,
                    url=f"https://huggingface.co/papers/{paper_id}",
                    arxiv_url=build_arxiv_url(paper_id),
                    ar5iv_url=build_ar5iv_url(paper_id),
                    thumbnail=thumbnail,
                    submitter=submitter,
                    organization=organization,
                    metrics=PaperMetrics(upvotes=upvotes, comments=comments),
                    has_video=has_video,
                    month=month,
                )
                
                papers.append(paper)
                
            except Exception:
                error_message = format_exception()
                logger.debug(f"解析论文失败: {error_message}")
                continue
        
        return papers
    
    def _find_paper_container(self, link) -> Optional[Any]:
        """查找论文卡片容器"""
        container = link.parent
        max_depth = 10
        depth = 0
        
        while container and container.name != "body" and depth < max_depth:
            # 检查是否包含完整信息
            if container.find("img", src=re.compile(r"cdn-thumbnails|cdn-uploads")):
                return container
            container = container.parent
            depth += 1
        
        return link.parent
    
    def _extract_thumbnail(self, container) -> Optional[str]:
        """提取缩略图URL"""
        img = container.find("img", src=re.compile(r"cdn-thumbnails"))
        return img["src"] if img else None
    
    def _extract_submitter(self, container) -> Optional[str]:
        """提取提交者"""
        submitter_text = container.find(string=re.compile(r"Submitted by", re.I))
        if submitter_text:
            # 查找后续的用户名
            next_elem = submitter_text.find_next()
            if next_elem:
                # 可能是img或直接是文本
                if next_elem.name == "img":
                    text_after = next_elem.find_next(string=True)
                    if text_after:
                        return text_after.strip()
                else:
                    return next_elem.get_text(strip=True)
        return None
    
    def _extract_upvotes(self, container, paper_id: str) -> int:
        """提取点赞数"""
        # 方法1: 查找登录链接中的数字
        login_link = container.find("a", href=re.compile(rf"/login.*next.*{paper_id}"))
        if login_link:
            text = login_link.get_text(strip=True)
            if text.isdigit():
                return int(text)
        
        # 方法2: 查找SVG图标旁边的数字
        svg_icons = container.find_all("svg")
        for svg in svg_icons:
            parent = svg.parent
            if parent:
                text = parent.get_text(strip=True)
                # 提取数字
                match = re.search(r"(\d+)", text)
                if match:
                    num = int(match.group(1))
                    if num > 0:
                        return num
        
        return 0
    
    def _extract_organization(self, container, paper_link) -> Optional[Organization]:
        """提取组织信息"""
        # 查找组织链接（非论文链接）
        org_links = container.find_all("a", href=re.compile(r"^/[a-zA-Z0-9_-]+$"))
        
        for org_link in org_links:
            if org_link == paper_link:
                continue
            if "/papers/" in org_link.get("href", ""):
                continue
            
            name = org_link.get_text(strip=True)
            if name and len(name) > 1:
                org_img = org_link.find("img")
                return Organization(
                    name=name,
                    logo=org_img["src"] if org_img else None,
                    url=f"https://huggingface.co{org_link['href']}"
                )
        
        return None
    
    def _extract_comments(self, container, paper_id: str) -> int:
        """提取评论数"""
        comment_link = container.find("a", href=re.compile(rf"/papers/{paper_id}#community"))
        if comment_link:
            text = comment_link.get_text(strip=True)
            match = re.search(r"(\d+)", text)
            if match:
                return int(match.group(1))
        return 0
    
    def _check_has_video(self, container) -> bool:
        """检查是否有视频"""
        if container.find("video"):
            return True
        if container.find("a", href=re.compile(r"\.(mp4|qt|webm)$", re.I)):
            return True
        return False
    
    async def scrape_month(
        self,
        session: aiohttp.ClientSession,
        month: str
    ) -> List[HFPaper]:
        """
        爬取单个月份的论文
        
        Args:
            session: aiohttp会话
            month: 月份 YYYY-MM
            
        Returns:
            过滤后的论文列表
        """
        url = build_hf_monthly_url(month)
        logger.info(f"开始爬取 {month}: {url}")
        
        stats = ScrapingStats(month=month)
        
        html = await self._fetch_page(session, url)
        if not html:
            logger.error(f"无法获取页面: {url}")
            stats.end_time = datetime.now()
            self.stats[month] = stats
            return []
        
        # 解析论文
        papers = self._parse_papers(html, month)
        stats.total_papers = len(papers)
        
        # 过滤低投票论文
        filtered = [p for p in papers if p.metrics.upvotes >= self.min_votes]
        stats.filtered_papers = len(filtered)
        stats.end_time = datetime.now()
        
        self.stats[month] = stats
        
        logger.info(
            f"完成 {month}: 发现 {stats.total_papers} 篇, "
            f"过滤后 {stats.filtered_papers} 篇 (>= {self.min_votes} votes)"
        )
        
        # 保存到文件
        filepath = settings.get_hf_papers_file(month)
        await save_jsonl([p.model_dump() for p in filtered], filepath)
        
        # 添加延迟
        await asyncio.sleep(self.request_delay)
        
        return filtered
    
    async def scrape_range(
        self,
        start_month: str,
        end_month: str
    ) -> List[HFPaper]:
        """
        爬取月份范围内的论文
        
        Args:
            start_month: 起始月份 YYYY-MM
            end_month: 结束月份 YYYY-MM
            
        Returns:
            所有论文列表
        """
        months = list(generate_months(start_month, end_month))
        logger.info(f"准备爬取 {len(months)} 个月份: {months[0]} 到 {months[-1]}")
        
        all_papers = []
        
        async with aiohttp.ClientSession() as session:
            # 使用信号量控制并发
            semaphore = asyncio.Semaphore(self.concurrency)
            
            async def bounded_scrape(month: str):
                async with semaphore:
                    papers = await self.scrape_month(session, month)
                    return papers
            
            tasks = [bounded_scrape(month) for month in months]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"爬取 {months[i]} 失败: {result}")
                else:
                    all_papers.extend(result)
        
        logger.info(f"爬取完成: 共 {len(all_papers)} 篇论文")
        
        return all_papers
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """获取统计摘要"""
        total_papers = sum(s.total_papers for s in self.stats.values())
        filtered_papers = sum(s.filtered_papers for s in self.stats.values())
        total_duration = sum(s.duration_seconds for s in self.stats.values())
        
        return {
            "months_scraped": len(self.stats),
            "total_papers_found": total_papers,
            "papers_after_filter": filtered_papers,
            "filter_threshold": self.min_votes,
            "total_duration_seconds": total_duration,
            "per_month_stats": {
                month: {
                    "total": s.total_papers,
                    "filtered": s.filtered_papers,
                    "duration": s.duration_seconds
                }
                for month, s in self.stats.items()
            }
        }


async def load_existing_papers(months: List[str]) -> List[HFPaper]:
    """
    加载已存在的论文数据
    
    Args:
        months: 月份列表
        
    Returns:
        论文列表
    """
    all_papers = []
    
    for month in months:
        filepath = settings.get_hf_papers_file(month)
        if filepath.exists():
            data = await load_jsonl(filepath)
            papers = [HFPaper(**item) for item in data]
            all_papers.extend(papers)
            logger.info(f"加载 {month}: {len(papers)} 篇论文")
    
    return all_papers


async def main():
    """主函数，用于独立测试"""
    from utils import setup_logging
    
    setup_logging()
    settings.ensure_directories()
    
    logger.info("开始HuggingFace Papers爬取测试")
    
    scraper = HFPapersScraper(
        min_votes=settings.min_votes,
        concurrency=settings.concurrency,
        request_delay=settings.request_delay,
    )
    
    # 只爬取最近一个月用于测试
    papers = await scraper.scrape_range("2025-12", "2025-12")
    
    logger.info(f"爬取完成: {len(papers)} 篇论文")
    
    # 显示统计
    stats = scraper.get_stats_summary()
    logger.info(f"统计信息: {stats}")
    
    # 显示前5篇
    for paper in papers[:5]:
        logger.info(f"  - {paper.title} ({paper.metrics.upvotes} votes)")


if __name__ == "__main__":
    asyncio.run(main())