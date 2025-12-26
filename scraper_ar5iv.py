"""
scraper_ar5iv.py - ar5iv 内容提取模块

该模块负责从ar5iv页面提取论文完整内容。
遵循CleanRL设计原则：单一职责、显式依赖、易于测试。
"""

import re
import sys
import asyncio
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiohttp
from bs4 import BeautifulSoup, Tag
from loguru import logger

from config import settings
from models import (
    Ar5ivContent,
    Section,
    Figure,
    Table,
    Equation,
)
from utils import (
    save_json,
    load_json,
    build_ar5iv_url,
    clean_text,
    truncate_text,
    format_exception,
)


class Ar5ivExtractor:
    """
    ar5iv 内容提取器
    
    负责从ar5iv HTML页面提取论文的完整结构化内容。
    支持提取：标题、作者、摘要、章节、图片、表格、公式、参考文献。
    """
    
    def __init__(
        self,
        concurrency: int = 3,
        request_delay: float = 1.5,
        max_retries: int = 3,
    ):
        """
        初始化提取器
        
        Args:
            concurrency: 并发数
            request_delay: 请求间隔（秒）
            max_retries: 最大重试次数
        """
        self.concurrency = concurrency
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.user_agent = settings.user_agent
        
        # 统计
        self.success_count = 0
        self.failure_count = 0
    
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
            async with session.get(url, headers=headers, timeout=60) as response:
                if response.status == 200:
                    # ar5iv页面可能较大，确保完整读取
                    content = await response.read()
                    try:
                        return content.decode('utf-8')
                    except UnicodeDecodeError:
                        return content.decode('utf-8', errors='replace')
                elif response.status == 404:
                    logger.warning(f"论文不存在: {url}")
                    return None
                elif response.status == 429:
                    wait_time = 120 * (retry_count + 1)
                    logger.warning(f"速率限制，等待 {wait_time} 秒: {url}")
                    await asyncio.sleep(wait_time)
                    if retry_count < self.max_retries:
                        return await self._fetch_page(session, url, retry_count + 1)
                else:
                    logger.warning(f"HTTP {response.status}: {url}")
                    
        except asyncio.TimeoutError:
            logger.warning(f"请求超时: {url}")
            if retry_count < self.max_retries:
                await asyncio.sleep(10 * (retry_count + 1))
                return await self._fetch_page(session, url, retry_count + 1)
                
        except Exception:
            error_message = format_exception()
            logger.error(f"请求失败 {url}: {error_message}")
            
        return None
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取论文标题"""
        title_elem = soup.select_one("h1.ltx_title")
        if title_elem:
            return clean_text(title_elem.get_text())
        
        # 备选方案
        title_elem = soup.select_one("title")
        if title_elem:
            text = title_elem.get_text()
            # 移除常见后缀
            text = re.sub(r"\s*-\s*ar5iv.*$", "", text, flags=re.I)
            return clean_text(text)
        
        return "Unknown Title"
    
    def _extract_authors(self, soup: BeautifulSoup) -> List[str]:
        """提取作者列表"""
        authors = []
        
        # 方法1: ltx_author
        for author in soup.select(".ltx_author"):
            name = clean_text(author.get_text())
            if name and len(name) > 1:
                authors.append(name)
        
        # 方法2: ltx_personname
        if not authors:
            for person in soup.select(".ltx_personname"):
                name = clean_text(person.get_text())
                if name and len(name) > 1:
                    authors.append(name)
        
        return authors
    
    def _extract_affiliations(self, soup: BeautifulSoup) -> List[str]:
        """提取单位列表"""
        affiliations = []
        
        for contact in soup.select(".ltx_contact"):
            text = clean_text(contact.get_text())
            if text and "@" not in text:  # 排除邮箱
                affiliations.append(text)
        
        return affiliations
    
    def _extract_abstract(self, soup: BeautifulSoup) -> Optional[str]:
        """提取摘要"""
        abstract_elem = soup.select_one(".ltx_abstract")
        if abstract_elem:
            # 移除标题
            title = abstract_elem.select_one(".ltx_title")
            if title:
                title.decompose()
            
            # 获取段落文本
            paragraphs = abstract_elem.select(".ltx_p")
            if paragraphs:
                return clean_text(" ".join(p.get_text() for p in paragraphs))
            
            return clean_text(abstract_elem.get_text())
        
        return None
    
    def _extract_sections(self, soup: BeautifulSoup) -> List[Section]:
        """提取章节结构"""
        sections = []
        
        for section in soup.select("section.ltx_section"):
            section_data = self._parse_section(section, level=2)
            if section_data:
                sections.append(section_data)
        
        return sections
    
    def _parse_section(self, elem: Tag, level: int = 2) -> Optional[Section]:
        """
        递归解析章节
        
        Args:
            elem: 章节元素
            level: 当前层级
            
        Returns:
            Section对象或None
        """
        # 提取标题
        title_elem = elem.select_one(f"h{level}.ltx_title, .ltx_title")
        if not title_elem:
            return None
        
        title = clean_text(title_elem.get_text())
        
        # 跳过参考文献和附录标题
        if re.match(r"^(references|bibliography|appendix)", title, re.I):
            return None
        
        # 提取段落
        paragraphs = []
        for para in elem.find_all("p", class_="ltx_p", recursive=False):
            text = clean_text(para.get_text())
            if text and len(text) > 10:
                paragraphs.append(text)
        
        # 如果没有直接段落，查找ltx_para容器
        if not paragraphs:
            for para_container in elem.find_all(class_="ltx_para", recursive=False):
                for para in para_container.find_all("p", class_="ltx_p"):
                    text = clean_text(para.get_text())
                    if text and len(text) > 10:
                        paragraphs.append(text)
        
        # 递归处理子章节
        subsections = []
        for subsection in elem.select("section.ltx_subsection"):
            sub_data = self._parse_section(subsection, level=level+1)
            if sub_data:
                subsections.append(sub_data)
        
        return Section(
            title=title,
            level=level,
            paragraphs=paragraphs,
            subsections=subsections
        )
    
    def _extract_figures(self, soup: BeautifulSoup) -> List[Figure]:
        """提取图片"""
        figures = []
        
        for fig in soup.select("figure.ltx_figure"):
            img = fig.select_one("img")
            if not img:
                continue
            
            src = img.get("src", "")
            # 转换为完整URL
            if src.startswith("/"):
                src = f"https://ar5iv.labs.arxiv.org{src}"
            
            caption_elem = fig.select_one("figcaption.ltx_caption")
            caption = clean_text(caption_elem.get_text()) if caption_elem else None
            
            # 提取标签
            label = None
            id_attr = fig.get("id", "")
            if id_attr.startswith("S"):
                label = id_attr
            
            figures.append(Figure(
                src=src,
                alt=img.get("alt"),
                caption=caption,
                label=label
            ))
        
        return figures
    
    def _extract_tables(self, soup: BeautifulSoup) -> List[Table]:
        """提取表格"""
        tables = []
        
        for table in soup.select("table.ltx_tabular"):
            # 提取标题
            caption = None
            caption_elem = table.find_previous("figcaption") or table.find_previous(class_="ltx_caption")
            if caption_elem:
                caption = clean_text(caption_elem.get_text())
            
            # 提取表头
            headers = []
            thead = table.select_one("thead")
            if thead:
                for th in thead.select("th, td"):
                    headers.append(clean_text(th.get_text()))
            
            # 提取数据行
            rows = []
            tbody = table.select_one("tbody") or table
            for tr in tbody.select("tr"):
                row = [clean_text(td.get_text()) for td in tr.select("td")]
                if row:
                    rows.append(row)
            
            if headers or rows:
                tables.append(Table(
                    caption=caption,
                    headers=headers,
                    rows=rows
                ))
        
        return tables
    
    def _extract_equations(self, soup: BeautifulSoup) -> List[Equation]:
        """提取数学公式"""
        equations = []
        
        for eq in soup.select(".ltx_equation, .ltx_equationgroup"):
            math_elem = eq.select_one("math")
            if math_elem:
                latex = math_elem.get("alttext", "")
                mathml = str(math_elem)
                
                # 提取标签
                label = None
                tag = eq.select_one(".ltx_tag")
                if tag:
                    label = clean_text(tag.get_text())
                
                equations.append(Equation(
                    latex=latex,
                    mathml=mathml[:1000] if len(mathml) > 1000 else mathml,  # 限制长度
                    label=label
                ))
        
        return equations
    
    def _extract_references(self, soup: BeautifulSoup) -> List[str]:
        """提取参考文献"""
        references = []
        
        for ref in soup.select(".ltx_bibitem"):
            text = clean_text(ref.get_text())
            if text:
                # 移除编号
                text = re.sub(r"^\[\d+\]\s*", "", text)
                references.append(text)
        
        return references
    
    def _extract_full_text(self, sections: List[Section]) -> str:
        """
        从章节提取完整文本
        
        Args:
            sections: 章节列表
            
        Returns:
            完整文本
        """
        texts = []
        
        def extract_section_text(section: Section, depth: int = 0):
            prefix = "#" * (section.level) + " "
            texts.append(prefix + section.title)
            texts.append("")
            
            for para in section.paragraphs:
                texts.append(para)
                texts.append("")
            
            for sub in section.subsections:
                extract_section_text(sub, depth + 1)
        
        for section in sections:
            extract_section_text(section)
        
        return "\n".join(texts)
    
    def parse_html(self, html: str, paper_id: str) -> Optional[Ar5ivContent]:
        """
        解析HTML提取论文内容
        
        Args:
            html: 页面HTML
            paper_id: 论文ID
            
        Returns:
            Ar5ivContent对象或None
        """
        try:
            soup = BeautifulSoup(html, "lxml")
            
            title = self._extract_title(soup)
            authors = self._extract_authors(soup)
            affiliations = self._extract_affiliations(soup)
            abstract = self._extract_abstract(soup)
            sections = self._extract_sections(soup)
            figures = self._extract_figures(soup)
            tables = self._extract_tables(soup)
            equations = self._extract_equations(soup)
            references = self._extract_references(soup)
            full_text = self._extract_full_text(sections)
            
            return Ar5ivContent(
                paper_id=paper_id,
                title=title,
                authors=authors,
                affiliations=affiliations,
                abstract=abstract,
                sections=sections,
                figures=figures,
                tables=tables,
                equations=equations,
                references=references,
                full_text=full_text,
            )
            
        except Exception:
            error_message = format_exception()
            logger.error(f"解析HTML失败 {paper_id}: {error_message}")
            return None
    
    async def extract_paper(
        self,
        session: aiohttp.ClientSession,
        paper_id: str,
        force: bool = False
    ) -> Optional[Ar5ivContent]:
        """
        提取单篇论文内容
        
        Args:
            session: aiohttp会话
            paper_id: 论文ID
            force: 是否强制重新提取
            
        Returns:
            Ar5ivContent对象或None
        """
        # 检查缓存
        cache_file = settings.get_ar5iv_file(paper_id)
        if cache_file.exists() and not force:
            logger.debug(f"使用缓存: {paper_id}")
            data = await load_json(cache_file)
            if data:
                return Ar5ivContent(**data)
        
        url = build_ar5iv_url(paper_id)
        logger.info(f"提取论文: {paper_id}")
        
        html = await self._fetch_page(session, url)
        if not html:
            self.failure_count += 1
            return None
        
        content = self.parse_html(html, paper_id)
        if content:
            # 保存到缓存
            await save_json(content.model_dump(), cache_file)
            self.success_count += 1
        else:
            self.failure_count += 1
        
        # 添加延迟
        await asyncio.sleep(self.request_delay)
        
        return content
    
    async def extract_papers(
        self,
        paper_ids: List[str],
        force: bool = False
    ) -> List[Ar5ivContent]:
        """
        批量提取论文内容
        
        Args:
            paper_ids: 论文ID列表
            force: 是否强制重新提取
            
        Returns:
            Ar5ivContent列表
        """
        logger.info(f"开始批量提取 {len(paper_ids)} 篇论文")
        
        results = []
        
        async with aiohttp.ClientSession() as session:
            semaphore = asyncio.Semaphore(self.concurrency)
            
            async def bounded_extract(paper_id: str):
                async with semaphore:
                    content = await self.extract_paper(session, paper_id, force)
                    return content
            
            tasks = [bounded_extract(pid) for pid in paper_ids]
            extracted = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(extracted):
                if isinstance(result, Exception):
                    logger.error(f"提取 {paper_ids[i]} 失败: {result}")
                elif result:
                    results.append(result)
        
        logger.info(
            f"提取完成: 成功 {self.success_count}, 失败 {self.failure_count}"
        )
        
        return results
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            "success": self.success_count,
            "failure": self.failure_count,
            "total": self.success_count + self.failure_count
        }


def get_all_paragraphs(content: Ar5ivContent) -> List[Dict[str, str]]:
    """
    获取论文所有段落（用于生成评论）
    
    Args:
        content: 论文内容
        
    Returns:
        段落列表，包含章节信息
    """
    paragraphs = []
    
    def process_section(section: Section):
        for para in section.paragraphs:
            paragraphs.append({
                "section_title": section.title,
                "text": para,
            })
        
        for sub in section.subsections:
            process_section(sub)
    
    for section in content.sections:
        process_section(section)
    
    return paragraphs


async def main():
    """主函数，用于独立测试"""
    from utils import setup_logging
    
    setup_logging()
    settings.ensure_directories()
    
    logger.info("开始ar5iv提取测试")
    
    extractor = Ar5ivExtractor(
        concurrency=2,
        request_delay=2.0,
    )
    
    # 测试论文ID
    test_ids = ["2312.02139", "2401.02385"]
    
    contents = await extractor.extract_papers(test_ids)
    
    for content in contents:
        logger.info(f"\n{'='*50}")
        logger.info(f"标题: {content.title}")
        logger.info(f"作者: {', '.join(content.authors[:3])}...")
        logger.info(f"摘要: {truncate_text(content.abstract or '', 200)}")
        logger.info(f"章节: {len(content.sections)}")
        logger.info(f"图片: {len(content.figures)}")
        logger.info(f"表格: {len(content.tables)}")
        logger.info(f"公式: {len(content.equations)}")
        logger.info(f"参考文献: {len(content.references)}")
    
    logger.info(f"\n统计: {extractor.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())