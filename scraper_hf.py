"""
scraper_hf.py - HuggingFace Papers 爬虫模块 (带代理支持)

整合代理管理器，支持:
- 自动代理切换和故障转移
- 智能重试机制
- 请求频率控制
- 完善的错误处理

HTML结构参考 (2024-12):
- article.relative: 论文卡片容器
- a[href^="/papers/"]: 论文链接，包含paper_id
- h3 > a.line-clamp-3: 论文标题
- label > div.leading-none: 投票数
"""

import re
import sys
import asyncio
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from functools import wraps

import aiohttp
from bs4 import BeautifulSoup
from loguru import logger

# 本地模块
from proxy_manager import ProxyManager, create_proxy_manager

# 尝试导入配置（如果存在）
try:
    from config import settings
except ImportError:
    settings = None

# 尝试导入模型定义（如果存在）
try:
    from models import HFPaper, PaperMetrics, Organization, ScrapingStats
except ImportError:
    # 内联定义基本模型
    from dataclasses import dataclass, field
    from typing import Optional
    
    @dataclass
    class PaperMetrics:
        upvotes: int = 0
        comments: int = 0
        github_stars: Optional[int] = None
    
    @dataclass
    class Organization:
        name: str
        logo: Optional[str] = None
        url: Optional[str] = None
    
    @dataclass
    class HFPaper:
        paper_id: str
        title: str
        url: str
        arxiv_url: str
        ar5iv_url: str
        month: str
        thumbnail: Optional[str] = None
        submitter: Optional[str] = None
        organization: Optional[Organization] = None
        metrics: PaperMetrics = field(default_factory=PaperMetrics)
        has_video: bool = False
        
        def model_dump(self) -> dict:
            """转换为字典"""
            return {
                'paper_id': self.paper_id,
                'title': self.title,
                'url': self.url,
                'arxiv_url': self.arxiv_url,
                'ar5iv_url': self.ar5iv_url,
                'month': self.month,
                'thumbnail': self.thumbnail,
                'submitter': self.submitter,
                'organization': {
                    'name': self.organization.name,
                    'logo': self.organization.logo,
                    'url': self.organization.url,
                } if self.organization else None,
                'metrics': {
                    'upvotes': self.metrics.upvotes,
                    'comments': self.metrics.comments,
                    'github_stars': self.metrics.github_stars,
                },
                'has_video': self.has_video,
            }
    
    @dataclass
    class ScrapingStats:
        month: str
        start_time: datetime = field(default_factory=datetime.now)
        end_time: Optional[datetime] = None
        total_papers: int = 0
        filtered_papers: int = 0
        
        @property
        def duration_seconds(self) -> float:
            if self.end_time:
                return (self.end_time - self.start_time).total_seconds()
            return 0


# ============================================
# 工具函数
# ============================================

def build_hf_monthly_url(month: str) -> str:
    """构建HuggingFace月度论文URL"""
    return f"https://huggingface.co/papers?date={month}"


def build_arxiv_url(paper_id: str) -> str:
    """构建arXiv URL"""
    return f"https://arxiv.org/abs/{paper_id}"


def build_ar5iv_url(paper_id: str) -> str:
    """构建ar5iv URL (HTML版arXiv)"""
    return f"https://ar5iv.org/abs/{paper_id}"


def generate_months(start: str, end: str):
    """生成月份范围"""
    from datetime import datetime
    
    start_date = datetime.strptime(start, "%Y-%m")
    end_date = datetime.strptime(end, "%Y-%m")
    
    current = start_date
    while current <= end_date:
        yield current.strftime("%Y-%m")
        # 移动到下个月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)


def format_exception() -> str:
    """格式化异常信息"""
    return traceback.format_exc().strip().split('\n')[-1]


async def save_jsonl(data: List[dict], filepath: str):
    """保存为JSONL格式"""
    import json
    from pathlib import Path
    
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


async def load_jsonl(filepath: str) -> List[dict]:
    """加载JSONL文件"""
    import json
    from pathlib import Path
    
    if not Path(filepath).exists():
        return []
    
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


# ============================================
# 重试装饰器
# ============================================

def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (aiohttp.ClientError, asyncio.TimeoutError),
    on_retry: Optional[Callable] = None,
):
    """
    异步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        # 指数退避
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        
                        logger.warning(
                            f"重试 {attempt + 1}/{max_retries}: {e.__class__.__name__} - "
                            f"等待 {delay:.1f}s"
                        )
                        
                        if on_retry:
                            on_retry(attempt, e)
                        
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"重试次数已用尽: {e}")
            
            raise last_exception
        
        return wrapper
    return decorator


# ============================================
# HuggingFace 爬虫
# ============================================

class HFPapersScraper:
    """
    HuggingFace Papers 爬虫 (带代理支持)
    
    Features:
    - 自动代理管理和故障转移
    - 智能重试机制
    - 异步并发控制
    - 完善的HTML解析
    """
    
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    
    def __init__(
        self,
        proxy_manager: Optional[ProxyManager] = None,
        min_votes: int = 50,
        concurrency: int = 3,
        request_delay: float = 1.0,
        max_retries: int = 3,
        user_agent: str = None,
    ):
        """
        初始化爬虫
        
        Args:
            proxy_manager: 代理管理器（可选）
            min_votes: 最小投票数阈值
            concurrency: 并发数
            request_delay: 请求间隔（秒）
            max_retries: 最大重试次数
            user_agent: 用户代理字符串
        """
        self.proxy_manager = proxy_manager
        self.min_votes = min_votes
        self.concurrency = concurrency
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        
        # 统计信息
        self.stats: Dict[str, ScrapingStats] = {}
        
        # 会话（延迟创建）
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建aiohttp会话"""
        if self._session is None or self._session.closed:
            if self.proxy_manager:
                self._session = self.proxy_manager.create_session(timeout=30)
            else:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                )
        return self._session
    
    async def close(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    
    async def _fetch_page(
        self,
        url: str,
        retry_count: int = 0
    ) -> Optional[str]:
        """
        获取页面HTML（带重试）
        
        Args:
            url: 页面URL
            retry_count: 当前重试次数
            
        Returns:
            HTML内容或None
        """
        session = await self._get_session()
        headers = self._get_headers()
        
        # 获取代理参数
        request_kwargs = {}
        if self.proxy_manager:
            request_kwargs = self.proxy_manager.get_request_kwargs()
        
        try:
            async with session.get(
                url, 
                headers=headers, 
                **request_kwargs
            ) as response:
                
                if response.status == 200:
                    # 正确处理编码
                    content = await response.read()
                    try:
                        html = content.decode('utf-8')
                    except UnicodeDecodeError:
                        html = content.decode('utf-8', errors='replace')
                    
                    # 报告成功
                    if self.proxy_manager:
                        self.proxy_manager.report_success()
                    
                    return html
                
                elif response.status == 429:
                    # 速率限制
                    wait_time = min(60 * (retry_count + 1), 300)
                    logger.warning(f"⚠️ 速率限制 (429)，等待 {wait_time}s: {url}")
                    
                    # 尝试切换代理
                    if self.proxy_manager:
                        self.proxy_manager.report_failure()
                    
                    await asyncio.sleep(wait_time)
                    
                    if retry_count < self.max_retries:
                        return await self._fetch_page(url, retry_count + 1)
                
                elif response.status == 403:
                    logger.error(f"❌ 访问被拒绝 (403): {url}")
                    if self.proxy_manager:
                        self.proxy_manager.report_failure()
                
                else:
                    logger.warning(f"⚠️ HTTP {response.status}: {url}")
                    
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ 请求超时: {url}")
            if self.proxy_manager:
                self.proxy_manager.report_failure()
            
            if retry_count < self.max_retries:
                await asyncio.sleep(5 * (retry_count + 1))
                return await self._fetch_page(url, retry_count + 1)
                
        except aiohttp.ClientError as e:
            logger.error(f"❌ 请求失败: {e}")
            if self.proxy_manager:
                self.proxy_manager.report_failure()
            
            if retry_count < self.max_retries:
                await asyncio.sleep(5 * (retry_count + 1))
                return await self._fetch_page(url, retry_count + 1)
        
        except Exception as e:
            logger.error(f"❌ 未知错误: {format_exception()}")
            
        return None
    
    def _parse_papers(self, html: str, month: str) -> List[HFPaper]:
        """
        解析HTML提取论文列表
        
        基于实际HTML结构：
        - article.relative: 论文卡片容器
        - h3 > a[href^="/papers/"]: 标题链接
        - label > div.leading-none: 投票数
        """
        soup = BeautifulSoup(html, "html.parser")
        papers = []
        seen_ids = set()
        
        # 方法1: 查找所有article容器
        articles = soup.find_all("article", class_=re.compile(r"relative"))
        
        if articles:
            for article in articles:
                paper = self._parse_article_card(article, month, seen_ids)
                if paper:
                    papers.append(paper)
        
        # 方法2: 回退到查找h3内的标题链接
        if not papers:
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
        """从article卡片解析论文信息"""
        try:
            h3 = article.find("h3")
            if not h3:
                return None
            
            title_link = h3.find("a", href=re.compile(r"^/papers/\d{4}\.\d{4,5}"))
            if not title_link:
                return None
            
            paper_id = title_link["href"].split("/")[-1]
            
            if paper_id in seen_ids:
                return None
            seen_ids.add(paper_id)
            
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
            logger.debug(f"解析article卡片失败: {format_exception()}")
            return None
    
    def _parse_from_title_link(
        self,
        link,
        month: str,
        seen_ids: set
    ) -> Optional[HFPaper]:
        """从标题链接解析论文（回退方法）"""
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
            
            return HFPaper(
                paper_id=paper_id,
                title=title,
                url=f"https://huggingface.co/papers/{paper_id}",
                arxiv_url=build_arxiv_url(paper_id),
                ar5iv_url=build_ar5iv_url(paper_id),
                thumbnail=self._extract_thumbnail(container),
                submitter=self._extract_submitter(container),
                organization=self._extract_organization(container, link),
                metrics=PaperMetrics(
                    upvotes=self._extract_upvotes(container, paper_id), 
                    comments=self._extract_comments(container, paper_id),
                    github_stars=self._extract_github_stars(container)
                ),
                has_video=self._check_has_video(container),
                month=month,
            )
            
        except Exception:
            logger.debug(f"解析标题链接失败: {format_exception()}")
            return None
    
    def _find_paper_container(self, link) -> Optional[Any]:
        """查找论文卡片容器"""
        container = link.parent
        max_depth = 10
        depth = 0
        
        while container and container.name != "body" and depth < max_depth:
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
        # 方法1: 查找包含"Submitted by"的div
        divs = container.find_all("div", string=re.compile(r"Submitted by", re.I))
        for div in divs:
            full_text = div.get_text(separator=" ", strip=True)
            match = re.search(r"Submitted by\s+(.+)", full_text, re.I)
            if match:
                return match.group(1).strip()
        
        # 方法2: 查找文本节点
        submitter_text = container.find(string=re.compile(r"Submitted by", re.I))
        if submitter_text:
            parent = submitter_text.parent
            if parent:
                texts = []
                for child in parent.children:
                    if isinstance(child, str):
                        text = child.strip()
                        if text and "Submitted by" not in text:
                            texts.append(text)
                
                if texts:
                    return texts[-1]
                
                full_text = parent.get_text(separator=" ", strip=True)
                match = re.search(r"Submitted by\s+(.+)", full_text, re.I)
                if match:
                    return match.group(1).strip()
        
        return None
    
    def _extract_upvotes(self, container, paper_id: str) -> int:
        """提取点赞数"""
        # 方法1: 查找label内的div.leading-none
        label = container.find("label", class_=re.compile(r"rounded-xl|cursor-pointer"))
        if label:
            vote_div = label.find("div", class_=re.compile(r"leading-none"))
            if vote_div:
                text = vote_div.get_text(strip=True)
                if text.isdigit():
                    return int(text)
                match = re.match(r"([\d.]+)k?", text, re.I)
                if match:
                    num = float(match.group(1))
                    if "k" in text.lower():
                        num *= 1000
                    return int(num)
        
        # 方法2: 查找包含投票图标的容器
        vote_containers = container.find_all("label")
        for vc in vote_containers:
            svg = vc.find("svg")
            if svg:
                path = svg.find("path", d=re.compile(r"M5\.19|triangle", re.I))
                if path or (svg.get("viewBox") == "0 0 12 12"):
                    text = vc.get_text(strip=True)
                    numbers = re.findall(r"\d+", text)
                    if numbers:
                        return int(numbers[-1])
        
        # 方法3: 回退到查找登录链接
        login_link = container.find("a", href=re.compile(rf"/login.*next.*{re.escape(paper_id)}"))
        if login_link:
            text = login_link.get_text(strip=True)
            if text.isdigit():
                return int(text)
        
        return 0
    
    def _extract_organization(self, container, paper_link) -> Optional[Organization]:
        """提取组织信息"""
        org_links = container.find_all("a", class_=re.compile(r"bg-blue|border-blue"))
        for org_link in org_links:
            href = org_link.get("href", "")
            if "/papers/" in href or "#" in href or href.startswith("http"):
                continue
            if not re.match(r"^/[\w-]+$", href):
                continue
            
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
        
        return None
    
    def _extract_comments(self, container, paper_id: str) -> int:
        """提取评论数"""
        comment_link = container.find("a", href=re.compile(rf"/papers/{re.escape(paper_id)}#community"))
        if comment_link:
            text = comment_link.get_text(strip=True)
            match = re.search(r"(\d+)", text)
            if match:
                return int(match.group(1))
        return 0
    
    def _extract_github_stars(self, container) -> Optional[int]:
        """提取GitHub星标数"""
        links = container.find_all("a", class_=re.compile(r"items-center"))
        for link in links:
            svg = link.find("svg")
            if not svg:
                continue
            
            viewbox = svg.get("viewBox", "")
            if "256 250" not in viewbox:
                path = svg.find("path", d=re.compile(r"M128\.001|github", re.I))
                if not path:
                    continue
            
            text = link.get_text(strip=True)
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
    
    async def scrape_month(self, month: str) -> List[HFPaper]:
        """
        爬取单个月份的论文
        
        Args:
            month: 月份 YYYY-MM
            
        Returns:
            过滤后的论文列表
        """
        url = build_hf_monthly_url(month)
        logger.info(f"📄 开始爬取 {month}: {url}")
        
        stats = ScrapingStats(month=month)
        
        html = await self._fetch_page(url)
        if not html:
            logger.error(f"❌ 无法获取页面: {url}")
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
            f"✅ 完成 {month}: 发现 {stats.total_papers} 篇, "
            f"过滤后 {stats.filtered_papers} 篇 (>= {self.min_votes} votes)"
        )
        
        # 添加延迟
        await asyncio.sleep(self.request_delay)
        
        return filtered
    
    async def scrape_range(
        self,
        start_month: str,
        end_month: str,
        save_dir: str = "./data/hf_papers"
    ) -> List[HFPaper]:
        """
        爬取月份范围内的论文
        
        Args:
            start_month: 起始月份 YYYY-MM
            end_month: 结束月份 YYYY-MM
            save_dir: 保存目录
            
        Returns:
            所有论文列表
        """
        months = list(generate_months(start_month, end_month))
        logger.info(f"📅 准备爬取 {len(months)} 个月份: {months[0]} 到 {months[-1]}")
        
        all_papers = []
        semaphore = asyncio.Semaphore(self.concurrency)
        
        async def bounded_scrape(month: str) -> List[HFPaper]:
            async with semaphore:
                papers = await self.scrape_month(month)
                
                # 保存到文件
                if papers and save_dir:
                    from pathlib import Path
                    filepath = Path(save_dir) / f"{month}.jsonl"
                    await save_jsonl([p.model_dump() for p in papers], str(filepath))
                
                return papers
        
        try:
            tasks = [bounded_scrape(month) for month in months]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"❌ 爬取 {months[i]} 失败: {result}")
                else:
                    all_papers.extend(result)
        
        finally:
            await self.close()
        
        logger.info(f"🎉 爬取完成: 共 {len(all_papers)} 篇论文")
        
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
            "proxy_enabled": self.proxy_manager is not None,
            "per_month_stats": {
                month: {
                    "total": s.total_papers,
                    "filtered": s.filtered_papers,
                    "duration": s.duration_seconds
                }
                for month, s in self.stats.items()
            }
        }


# ============================================
# 便捷函数
# ============================================

async def create_scraper_with_proxy(
    proxy_config: str = None,
    min_votes: int = 50,
    test_proxy: bool = True,
) -> HFPapersScraper:
    """
    创建带代理的爬虫实例
    
    Args:
        proxy_config: 代理配置文件路径或订阅URL
        min_votes: 最小投票数
        test_proxy: 是否测试代理
    """
    proxy_manager = None
    
    if proxy_config:
        logger.info(f"🔧 初始化代理: {proxy_config[:50]}...")
        proxy_manager = await create_proxy_manager(
            proxy_config,
            test_nodes=test_proxy,
            check_local=True,
        )
    
    return HFPapersScraper(
        proxy_manager=proxy_manager,
        min_votes=min_votes,
    )


# ============================================
# 主函数
# ============================================

async def main():
    """主函数"""
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description="HuggingFace Papers Scraper")
    parser.add_argument("--start", default="2025-01", help="起始月份 (YYYY-MM)")
    parser.add_argument("--end", default="2025-01", help="结束月份 (YYYY-MM)")
    parser.add_argument("--min-votes", type=int, default=50, help="最小投票数")
    parser.add_argument("--proxy", help="代理配置文件或订阅URL")
    parser.add_argument("--output", default="./data/hf_papers", help="输出目录")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    log_level = "DEBUG" if args.debug else "INFO"
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level=log_level
    )
    
    print("=" * 60)
    print("🚀 HuggingFace Papers Scraper")
    print("=" * 60)
    
    # 创建爬虫
    proxy_manager = None
    
    if args.proxy:
        from proxy_manager import create_proxy_manager
        proxy_manager = await create_proxy_manager(
            args.proxy,
            test_nodes=True,
            check_local=True,
        )
        
        # 显示代理状态
        status = proxy_manager.get_status()
        print(f"\n📊 代理状态:")
        print(f"  可用节点: {status['available_nodes']}/{status['total_nodes']}")
        print(f"  当前代理: {status['proxy_url']}")
    
    scraper = HFPapersScraper(
        proxy_manager=proxy_manager,
        min_votes=args.min_votes,
        concurrency=args.concurrency,
    )
    
    # 开始爬取
    print(f"\n📅 爬取范围: {args.start} ~ {args.end}")
    print(f"📊 投票阈值: >= {args.min_votes}")
    print(f"📁 输出目录: {args.output}")
    print()
    
    papers = await scraper.scrape_range(
        args.start,
        args.end,
        save_dir=args.output
    )
    
    # 显示统计
    stats = scraper.get_stats_summary()
    print(f"\n📊 统计信息:")
    print(f"  爬取月份: {stats['months_scraped']}")
    print(f"  发现论文: {stats['total_papers_found']}")
    print(f"  过滤后: {stats['papers_after_filter']}")
    print(f"  总耗时: {stats['total_duration_seconds']:.1f}s")
    
    # 显示Top 10
    if papers:
        print(f"\n🏆 Top 10 论文:")
        papers.sort(key=lambda p: p.metrics.upvotes, reverse=True)
        for i, paper in enumerate(papers[:10], 1):
            print(f"  {i}. [{paper.metrics.upvotes:4d}] {paper.title[:60]}...")


if __name__ == "__main__":
    asyncio.run(main())