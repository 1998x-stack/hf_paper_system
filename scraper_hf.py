"""
scraper_hf.py - HuggingFace Papers 爬虫模块

该模块负责从HuggingFace Papers页面爬取论文列表。
遵循CleanRL设计原则：单一职责、显式依赖、易于测试。

HTML结构参考 (2024-12):
- article.relative: 论文卡片容器
- a[href^="/papers/"]: 论文链接，包含paper_id
- h3 > a.line-clamp-3: 论文标题
- label > div.leading-none: 投票数
- a.bg-blue-50: 组织徽章
- a[href*="#community"]: 评论链接
- svg[viewBox="0 0 256 250"]: GitHub图标
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
        
        基于实际HTML结构：
        - article.relative: 论文卡片容器
        - h3 > a[href^="/papers/"]: 标题链接
        - label > div.leading-none: 投票数
        
        Args:
            html: 页面HTML
            month: 所属月份
            
        Returns:
            论文列表
        """
        soup = BeautifulSoup(html, "html.parser")
        papers = []
        seen_ids = set()  # 去重
        
        # 方法1: 查找所有article容器（首选方法）
        articles = soup.find_all("article", class_=re.compile(r"relative"))
        
        if articles:
            for article in articles:
                paper = self._parse_article_card(article, month, seen_ids)
                if paper:
                    papers.append(paper)
        
        # 方法2: 如果没找到article，回退到查找h3内的标题链接
        if not papers:
            # 查找h3内的论文链接（标题链接）
            h3_tags = soup.find_all("h3")
            for h3 in h3_tags:
                link = h3.find("a", href=re.compile(r"^/papers/\d{4}\.\d{4,5}"))
                if not link:
                    continue
                    
                paper = self._parse_from_title_link(link, month, seen_ids)
                if paper:
                    papers.append(paper)
        
        return papers
    
    def _parse_article_card(
        self, 
        article, 
        month: str, 
        seen_ids: set
    ) -> Optional[HFPaper]:
        """
        从article卡片解析论文信息
        
        Args:
            article: article元素
            month: 月份
            seen_ids: 已见ID集合
            
        Returns:
            HFPaper或None
        """
        try:
            # 查找h3内的标题链接
            h3 = article.find("h3")
            if not h3:
                return None
                
            title_link = h3.find("a", href=re.compile(r"^/papers/\d{4}\.\d{4,5}"))
            if not title_link:
                return None
            
            paper_id = title_link["href"].split("/")[-1]
            
            # 跳过重复
            if paper_id in seen_ids:
                return None
            seen_ids.add(paper_id)
            
            # 获取标题
            title = title_link.get_text(strip=True)
            if not title or len(title) < 5:
                return None
            
            # 提取各项信息
            thumbnail = self._extract_thumbnail(article)
            submitter = self._extract_submitter(article)
            upvotes = self._extract_upvotes(article, paper_id)
            organization = self._extract_organization(article, title_link)
            comments = self._extract_comments(article, paper_id)
            github_stars = self._extract_github_stars(article)
            has_video = self._check_has_video(article)
            
            return HFPaper(
                paper_id=paper_id,
                title=title,
                url=f"https://huggingface.co/papers/{paper_id}",
                arxiv_url=build_arxiv_url(paper_id),
                ar5iv_url=build_ar5iv_url(paper_id),
                thumbnail=thumbnail,
                submitter=submitter,
                organization=organization,
                metrics=PaperMetrics(
                    upvotes=upvotes, 
                    comments=comments,
                    github_stars=github_stars
                ),
                has_video=has_video,
                month=month,
            )
            
        except Exception:
            error_message = format_exception()
            logger.debug(f"解析article卡片失败: {error_message}")
            return None
    
    def _parse_from_title_link(
        self,
        link,
        month: str,
        seen_ids: set
    ) -> Optional[HFPaper]:
        """
        从标题链接解析论文（回退方法）
        """
        try:
            paper_id = link["href"].split("/")[-1]
            
            if paper_id in seen_ids:
                return None
            seen_ids.add(paper_id)
            
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                return None
            
            container = self._find_paper_container(link)
            if not container:
                return None
            
            thumbnail = self._extract_thumbnail(container)
            submitter = self._extract_submitter(container)
            upvotes = self._extract_upvotes(container, paper_id)
            organization = self._extract_organization(container, link)
            comments = self._extract_comments(container, paper_id)
            github_stars = self._extract_github_stars(container)
            has_video = self._check_has_video(container)
            
            return HFPaper(
                paper_id=paper_id,
                title=title,
                url=f"https://huggingface.co/papers/{paper_id}",
                arxiv_url=build_arxiv_url(paper_id),
                ar5iv_url=build_ar5iv_url(paper_id),
                thumbnail=thumbnail,
                submitter=submitter,
                organization=organization,
                metrics=PaperMetrics(
                    upvotes=upvotes, 
                    comments=comments,
                    github_stars=github_stars
                ),
                has_video=has_video,
                month=month,
            )
            
        except Exception:
            error_message = format_exception()
            logger.debug(f"解析标题链接失败: {error_message}")
            return None
    
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
        """
        提取提交者
        
        HTML结构:
        <div class="...">
            Submitted by
            <div class="...">
                <img ...>
            </div>
            zbhpku  <!-- 用户名在这里 -->
        </div>
        """
        # 方法1: 查找包含"Submitted by"的div，然后获取最后的文本
        divs = container.find_all("div", string=re.compile(r"Submitted by", re.I))
        for div in divs:
            # 获取该div的完整文本
            full_text = div.get_text(separator=" ", strip=True)
            # 提取 "Submitted by" 之后的部分
            match = re.search(r"Submitted by\s+(.+)", full_text, re.I)
            if match:
                return match.group(1).strip()
        
        # 方法2: 查找文本节点
        submitter_text = container.find(string=re.compile(r"Submitted by", re.I))
        if submitter_text:
            parent = submitter_text.parent
            if parent:
                # 获取父元素的所有直接子文本和元素
                texts = []
                for child in parent.children:
                    if isinstance(child, str):
                        text = child.strip()
                        if text and "Submitted by" not in text:
                            texts.append(text)
                
                if texts:
                    return texts[-1]  # 用户名通常是最后一个文本
                    
                # 如果没找到，尝试获取整体文本
                full_text = parent.get_text(separator=" ", strip=True)
                match = re.search(r"Submitted by\s+(.+)", full_text, re.I)
                if match:
                    return match.group(1).strip()
        
        return None
    
    def _extract_upvotes(self, container, paper_id: str) -> int:
        """
        提取点赞数
        
        HTML结构: 
        <label class="...">
            <input type="checkbox" class="peer hidden">
            <svg>...</svg>
            <div class="leading-none">183</div>
        </label>
        """
        # 方法1: 查找label内的div.leading-none（最准确）
        label = container.find("label", class_=re.compile(r"rounded-xl|cursor-pointer"))
        if label:
            vote_div = label.find("div", class_=re.compile(r"leading-none"))
            if vote_div:
                text = vote_div.get_text(strip=True)
                if text.isdigit():
                    return int(text)
                # 处理 "1.5k" 格式
                match = re.match(r"([\d.]+)k?", text, re.I)
                if match:
                    num = float(match.group(1))
                    if "k" in text.lower():
                        num *= 1000
                    return int(num)
        
        # 方法2: 查找包含投票图标(三角形SVG)的容器
        vote_containers = container.find_all("label")
        for vc in vote_containers:
            svg = vc.find("svg")
            if svg:
                # 检查是否是投票图标（包含三角形path）
                path = svg.find("path", d=re.compile(r"M5\.19|triangle", re.I))
                if path or (svg.get("viewBox") == "0 0 12 12"):
                    # 获取同级或子级的数字
                    text = vc.get_text(strip=True)
                    # 提取纯数字
                    numbers = re.findall(r"\d+", text)
                    if numbers:
                        return int(numbers[-1])  # 取最后一个数字
        
        # 方法3: 回退到查找登录链接
        login_link = container.find("a", href=re.compile(rf"/login.*next.*{re.escape(paper_id)}"))
        if login_link:
            text = login_link.get_text(strip=True)
            if text.isdigit():
                return int(text)
        
        return 0
    
    def _extract_organization(self, container, paper_link) -> Optional[Organization]:
        """
        提取组织信息
        
        HTML结构:
        <a href="/PekingUniversity" class="...bg-blue-50...">
            <img src="..." alt="PekingUniversity" class="size-3.5 rounded">
            <span class="...font-medium">Peking University</span>
        </a>
        """
        # 方法1: 查找带有蓝色背景的组织徽章链接
        org_links = container.find_all("a", class_=re.compile(r"bg-blue|border-blue"))
        for org_link in org_links:
            href = org_link.get("href", "")
            # 排除论文链接和特殊链接
            if "/papers/" in href or "#" in href or href.startswith("http"):
                continue
            if not re.match(r"^/[\w-]+$", href):
                continue
            
            # 获取组织名称（优先从span获取）
            span = org_link.find("span")
            if span:
                name = span.get_text(strip=True)
            else:
                name = org_link.get_text(strip=True)
            
            if name and len(name) > 1:
                org_img = org_link.find("img")
                return Organization(
                    name=name,
                    logo=org_img.get("src") if org_img else None,
                    url=f"https://huggingface.co{href}"
                )
        
        # 方法2: 回退到查找任何组织链接
        all_links = container.find_all("a", href=re.compile(r"^/[a-zA-Z0-9_-]+$"))
        for link in all_links:
            if link == paper_link:
                continue
            href = link.get("href", "")
            if "/papers/" in href:
                continue
            
            # 检查是否包含图片（组织标识）
            if link.find("img"):
                name = link.get_text(strip=True)
                if name and len(name) > 1 and name.lower() not in ["login", "sign up"]:
                    org_img = link.find("img")
                    return Organization(
                        name=name,
                        logo=org_img.get("src") if org_img else None,
                        url=f"https://huggingface.co{href}"
                    )
        
        return None
    
    def _extract_comments(self, container, paper_id: str) -> int:
        """
        提取评论数
        
        HTML结构:
        <a href="/papers/2512.16676#community" class="...">
            <svg>...</svg>
            4
        </a>
        """
        comment_link = container.find("a", href=re.compile(rf"/papers/{re.escape(paper_id)}#community"))
        if comment_link:
            text = comment_link.get_text(strip=True)
            match = re.search(r"(\d+)", text)
            if match:
                return int(match.group(1))
        return 0
    
    def _extract_github_stars(self, container) -> Optional[int]:
        """
        提取GitHub星标数
        
        HTML结构:
        <a href="/papers/xxx" class="...">
            <svg viewBox="0 0 256 250">  <!-- GitHub icon -->
                <path d="M128.001 0C57.317...">  <!-- GitHub logo path -->
            </svg>
            <span>1.81k</span>
        </a>
        """
        # 查找包含GitHub图标的链接
        links = container.find_all("a", class_=re.compile(r"items-center"))
        for link in links:
            svg = link.find("svg")
            if not svg:
                continue
                
            # 检查是否是GitHub图标（通过viewBox或path特征）
            viewbox = svg.get("viewBox", "")
            if "256 250" not in viewbox:
                # 尝试查找GitHub特征路径
                path = svg.find("path", d=re.compile(r"M128\.001|github", re.I))
                if not path:
                    continue
            
            # 提取数字
            text = link.get_text(strip=True)
            # 处理 "1.81k" 格式
            match = re.match(r"([\d.]+)\s*k?", text, re.I)
            if match:
                num = float(match.group(1))
                if "k" in text.lower():
                    num *= 1000
                return int(num)
        
        return None
    
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