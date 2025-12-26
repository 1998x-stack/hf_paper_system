"""
models.py - 数据模型模块

该模块定义所有数据结构，使用Pydantic进行类型验证。
遵循CleanRL设计原则：显式类型、清晰结构、易于序列化。
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


# ==================== HuggingFace Papers 模型 ====================

class PaperMetrics(BaseModel):
    """论文指标"""
    upvotes: int = Field(default=0, description="点赞数")
    comments: int = Field(default=0, description="评论数")
    downloads: Optional[int] = Field(default=None, description="下载数")
    github_stars: Optional[int] = Field(default=None, description="GitHub星标数")


class Organization(BaseModel):
    """组织信息"""
    name: str = Field(description="组织名称")
    logo: Optional[str] = Field(default=None, description="Logo URL")
    url: Optional[str] = Field(default=None, description="组织页面URL")


class HFPaper(BaseModel):
    """HuggingFace论文基本信息"""
    paper_id: str = Field(description="arXiv ID, e.g., 2512.02556")
    title: str = Field(description="论文标题")
    url: str = Field(description="HuggingFace论文页面URL")
    arxiv_url: str = Field(description="arXiv页面URL")
    ar5iv_url: str = Field(description="ar5iv HTML页面URL")
    thumbnail: Optional[str] = Field(default=None, description="缩略图URL")
    submitter: Optional[str] = Field(default=None, description="提交者")
    organization: Optional[Organization] = Field(default=None, description="组织信息")
    metrics: PaperMetrics = Field(default_factory=PaperMetrics, description="指标")
    has_video: bool = Field(default=False, description="是否有视频")
    month: str = Field(description="所属月份 YYYY-MM")
    scraped_at: datetime = Field(default_factory=datetime.now, description="抓取时间")
    
    @property
    def safe_id(self) -> str:
        """文件系统安全的ID"""
        return self.paper_id.replace(".", "_")


# ==================== ar5iv 内容模型 ====================

class Figure(BaseModel):
    """论文图片"""
    src: str = Field(description="图片URL")
    alt: Optional[str] = Field(default=None, description="替代文本")
    caption: Optional[str] = Field(default=None, description="图片说明")
    label: Optional[str] = Field(default=None, description="图片标签 e.g., fig:1")


class Table(BaseModel):
    """论文表格"""
    caption: Optional[str] = Field(default=None, description="表格说明")
    headers: List[str] = Field(default_factory=list, description="表头")
    rows: List[List[str]] = Field(default_factory=list, description="数据行")
    label: Optional[str] = Field(default=None, description="表格标签")


class Equation(BaseModel):
    """数学公式"""
    latex: Optional[str] = Field(default=None, description="LaTeX源码")
    mathml: Optional[str] = Field(default=None, description="MathML")
    label: Optional[str] = Field(default=None, description="公式标签")


class Section(BaseModel):
    """论文章节"""
    title: str = Field(description="章节标题")
    level: int = Field(default=2, description="标题级别 2=h2, 3=h3...")
    paragraphs: List[str] = Field(default_factory=list, description="段落列表")
    subsections: List["Section"] = Field(default_factory=list, description="子章节")


class Ar5ivContent(BaseModel):
    """ar5iv论文完整内容"""
    paper_id: str = Field(description="arXiv ID")
    title: str = Field(description="论文标题")
    authors: List[str] = Field(default_factory=list, description="作者列表")
    affiliations: List[str] = Field(default_factory=list, description="单位列表")
    abstract: Optional[str] = Field(default=None, description="摘要")
    sections: List[Section] = Field(default_factory=list, description="章节列表")
    figures: List[Figure] = Field(default_factory=list, description="图片列表")
    tables: List[Table] = Field(default_factory=list, description="表格列表")
    equations: List[Equation] = Field(default_factory=list, description="公式列表")
    references: List[str] = Field(default_factory=list, description="参考文献")
    full_text: Optional[str] = Field(default=None, description="完整文本")
    extracted_at: datetime = Field(default_factory=datetime.now, description="提取时间")


# ==================== LLM 处理结果模型 ====================

class ClassificationResult(BaseModel):
    """分类结果"""
    paper_id: str = Field(description="论文ID")
    category: str = Field(description="分类标识")
    category_name: str = Field(description="分类名称")
    category_name_zh: str = Field(description="分类中文名")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度")
    reasoning: Optional[str] = Field(default=None, description="分类理由")
    raw_response: str = Field(default="", description="LLM原始响应")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")


class KeywordsResult(BaseModel):
    """关键词提取结果"""
    paper_id: str = Field(description="论文ID")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    keywords_zh: List[str] = Field(default_factory=list, description="中文关键词")
    raw_response: str = Field(default="", description="LLM原始响应")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")


class LabelsResult(BaseModel):
    """标签提取结果"""
    paper_id: str = Field(description="论文ID")
    labels: List[str] = Field(default_factory=list, description="标签列表")
    labels_zh: List[str] = Field(default_factory=list, description="中文标签")
    raw_response: str = Field(default="", description="LLM原始响应")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")


class ParagraphComment(BaseModel):
    """段落评论"""
    paragraph_index: int = Field(description="段落索引")
    paragraph_text: str = Field(description="段落原文（前100字）")
    section_title: str = Field(default="", description="所属章节标题")
    key_points: List[str] = Field(default_factory=list, description="要点列表")
    reading_notes: str = Field(default="", description="阅读笔记")
    importance: str = Field(default="medium", description="重要程度: low/medium/high")
    raw_response: str = Field(default="", description="LLM原始响应")


class CommentsResult(BaseModel):
    """论文评论结果"""
    paper_id: str = Field(description="论文ID")
    comments: List[ParagraphComment] = Field(default_factory=list, description="段落评论列表")
    summary: str = Field(default="", description="全文总结")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")


# ==================== 完整论文模型 ====================

class FullPaper(BaseModel):
    """完整论文数据（整合所有来源）"""
    # 基本信息
    paper_id: str = Field(description="arXiv ID")
    title: str = Field(description="论文标题")
    authors: List[str] = Field(default_factory=list, description="作者列表")
    abstract: Optional[str] = Field(default=None, description="摘要")
    
    # HuggingFace元数据
    hf_metadata: Optional[HFPaper] = Field(default=None, description="HF元数据")
    
    # ar5iv内容
    content: Optional[Ar5ivContent] = Field(default=None, description="完整内容")
    
    # LLM处理结果
    classification: Optional[ClassificationResult] = Field(default=None, description="分类")
    keywords: Optional[KeywordsResult] = Field(default=None, description="关键词")
    labels: Optional[LabelsResult] = Field(default=None, description="标签")
    comments: Optional[CommentsResult] = Field(default=None, description="评论")
    
    # Notion同步信息
    notion_page_id: Optional[str] = Field(default=None, description="Notion页面ID")
    notion_synced_at: Optional[datetime] = Field(default=None, description="同步时间")
    
    # 元信息
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


# ==================== Notion 相关模型 ====================

class NotionDatabaseEntry(BaseModel):
    """Notion数据库条目"""
    paper_id: str = Field(description="论文ID")
    title: str = Field(description="标题")
    authors: str = Field(description="作者（逗号分隔）")
    category: str = Field(description="分类")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    labels: List[str] = Field(default_factory=list, description="标签")
    upvotes: int = Field(default=0, description="点赞数")
    organization: str = Field(default="", description="组织")
    arxiv_url: str = Field(description="arXiv链接")
    hf_url: str = Field(description="HuggingFace链接")
    month: str = Field(description="月份")


# ==================== 统计模型 ====================

class ScrapingStats(BaseModel):
    """爬取统计"""
    month: str = Field(description="月份")
    total_papers: int = Field(default=0, description="总论文数")
    filtered_papers: int = Field(default=0, description="过滤后论文数")
    failed_papers: int = Field(default=0, description="失败数")
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = Field(default=None)
    
    @property
    def duration_seconds(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0


class ProcessingStats(BaseModel):
    """处理统计"""
    total_papers: int = Field(default=0)
    ar5iv_extracted: int = Field(default=0)
    classified: int = Field(default=0)
    keywords_extracted: int = Field(default=0)
    labels_extracted: int = Field(default=0)
    comments_generated: int = Field(default=0)
    notion_synced: int = Field(default=0)
    errors: List[Dict[str, Any]] = Field(default_factory=list)


if __name__ == "__main__":
    # 测试模型
    print("=" * 50)
    print("Models Test")
    print("=" * 50)
    
    # 测试HFPaper
    paper = HFPaper(
        paper_id="2512.02556",
        title="Test Paper",
        url="https://huggingface.co/papers/2512.02556",
        arxiv_url="https://arxiv.org/abs/2512.02556",
        ar5iv_url="https://ar5iv.labs.arxiv.org/html/2512.02556",
        month="2025-12",
        metrics=PaperMetrics(upvotes=100, comments=5)
    )
    print(f"Paper: {paper.title}")
    print(f"Safe ID: {paper.safe_id}")
    print(f"Metrics: {paper.metrics.upvotes} upvotes")
    
    # 测试序列化
    paper_json = paper.model_dump_json(indent=2)
    print(f"\nJSON length: {len(paper_json)} chars")
    
    # 测试FullPaper
    full = FullPaper(
        paper_id="2512.02556",
        title="Test Paper",
        hf_metadata=paper
    )
    print(f"\nFull Paper created: {full.paper_id}")