"""
utils.py - 工具函数模块

该模块包含所有共享的工具函数。
遵循CleanRL设计原则：纯函数、无副作用、易于测试。
"""

import sys
import json
import asyncio
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, List, Dict, Optional, Generator

import aiofiles
from loguru import logger

from config import settings


# ==================== 日志配置 ====================

def setup_logging() -> None:
    """
    配置loguru日志系统
    
    输出到:
    1. 控制台 (彩色格式)
    2. 文件 (JSON格式，带轮转)
    """
    # 移除默认handler
    logger.remove()
    
    # 控制台输出
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True,
    )
    
    # 文件输出
    log_file = settings.get_log_file()
    logger.add(
        str(log_file),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        compression="zip",
        serialize=False,
    )
    
    logger.info(f"日志系统初始化完成，文件: {log_file}")


def format_exception() -> str:
    """
    格式化当前异常信息
    
    Returns:
        格式化的异常字符串
    """
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message


# ==================== 日期工具 ====================

def generate_months(start: str, end: str) -> Generator[str, None, None]:
    """
    生成月份范围
    
    Args:
        start: 起始月份 YYYY-MM
        end: 结束月份 YYYY-MM
        
    Yields:
        月份字符串 YYYY-MM
    """
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


def get_current_timestamp() -> str:
    """获取当前时间戳字符串"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ==================== 文件操作 ====================

async def save_jsonl(data: List[Dict[str, Any]], filepath: Path) -> int:
    """
    异步保存JSONL文件
    
    Args:
        data: 数据列表
        filepath: 文件路径
        
    Returns:
        保存的记录数
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            line = json.dumps(item, ensure_ascii=False, default=str)
            await f.write(line + "\n")
    
    logger.debug(f"保存JSONL: {filepath} ({len(data)} 条记录)")
    return len(data)


async def load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """
    异步加载JSONL文件
    
    Args:
        filepath: 文件路径
        
    Returns:
        数据列表
    """
    if not filepath.exists():
        logger.warning(f"文件不存在: {filepath}")
        return []
    
    data = []
    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
        async for line in f:
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析错误: {e}")
                    continue
    
    logger.debug(f"加载JSONL: {filepath} ({len(data)} 条记录)")
    return data


async def save_json(data: Dict[str, Any], filepath: Path) -> None:
    """
    异步保存JSON文件
    
    Args:
        data: 数据字典
        filepath: 文件路径
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    
    logger.debug(f"保存JSON: {filepath}")


async def load_json(filepath: Path) -> Optional[Dict[str, Any]]:
    """
    异步加载JSON文件
    
    Args:
        filepath: 文件路径
        
    Returns:
        数据字典或None
    """
    if not filepath.exists():
        logger.warning(f"文件不存在: {filepath}")
        return None
    
    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
        content = await f.read()
        return json.loads(content)


def append_jsonl_sync(data: Dict[str, Any], filepath: Path) -> None:
    """
    同步追加JSONL记录
    
    Args:
        data: 数据字典
        filepath: 文件路径
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    with open(filepath, "a", encoding="utf-8") as f:
        line = json.dumps(data, ensure_ascii=False, default=str)
        f.write(line + "\n")


# ==================== 文本处理 ====================

def clean_text(text: str) -> str:
    """
    清理文本内容
    
    Args:
        text: 原始文本
        
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    
    # 移除多余空白
    text = " ".join(text.split())
    
    # 移除控制字符
    text = "".join(char for char in text if ord(char) >= 32 or char in "\n\t")
    
    return text.strip()


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断文本
    
    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀
        
    Returns:
        截断后的文本
    """
    if not text or len(text) <= max_length:
        return text or ""
    
    return text[:max_length - len(suffix)] + suffix


def extract_paper_id(url: str) -> Optional[str]:
    """
    从URL提取论文ID
    
    Args:
        url: 包含论文ID的URL
        
    Returns:
        论文ID或None
    """
    import re
    
    patterns = [
        r"/papers/(\d{4}\.\d{4,5})",  # HuggingFace格式
        r"/abs/(\d{4}\.\d{4,5})",      # arXiv格式
        r"/html/(\d{4}\.\d{4,5})",     # ar5iv格式
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


# ==================== 异步工具 ====================

class AsyncSemaphore:
    """
    异步信号量封装，用于限制并发
    """
    
    def __init__(self, concurrency: int = 3):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.concurrency = concurrency
    
    async def __aenter__(self):
        await self.semaphore.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.semaphore.release()


async def run_with_semaphore(
    semaphore: asyncio.Semaphore,
    coro,
    delay: float = 0.0
):
    """
    使用信号量运行协程
    
    Args:
        semaphore: 信号量
        coro: 协程
        delay: 执行后延迟
        
    Returns:
        协程结果
    """
    async with semaphore:
        result = await coro
        if delay > 0:
            await asyncio.sleep(delay)
        return result


async def gather_with_concurrency(
    coros: List,
    concurrency: int = 3,
    delay: float = 0.0,
    return_exceptions: bool = True
) -> List:
    """
    带并发限制的gather
    
    Args:
        coros: 协程列表
        concurrency: 并发数
        delay: 每个请求后延迟
        return_exceptions: 是否返回异常
        
    Returns:
        结果列表
    """
    semaphore = asyncio.Semaphore(concurrency)
    
    async def bounded_coro(coro):
        async with semaphore:
            result = await coro
            if delay > 0:
                await asyncio.sleep(delay)
            return result
    
    tasks = [bounded_coro(coro) for coro in coros]
    return await asyncio.gather(*tasks, return_exceptions=return_exceptions)


# ==================== JSON处理 ====================

def safe_json_parse(text: str) -> Optional[Dict[str, Any]]:
    """
    安全解析JSON，处理可能的错误
    
    Args:
        text: JSON文本
        
    Returns:
        解析的字典或None
    """
    if not text:
        return None
    
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 尝试提取JSON块
    import re
    
    # 查找```json ... ```块
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # 查找{...}块
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    
    logger.warning(f"无法解析JSON: {truncate_text(text, 100)}")
    return None


def ensure_json_serializable(obj: Any) -> Any:
    """
    确保对象可JSON序列化
    
    Args:
        obj: 任意对象
        
    Returns:
        可序列化的对象
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Path):
        return str(obj)
    elif hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif hasattr(obj, "__dict__"):
        return {k: ensure_json_serializable(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, dict):
        return {k: ensure_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [ensure_json_serializable(item) for item in obj]
    else:
        return obj


# ==================== 进度显示 ====================

class ProgressTracker:
    """
    进度追踪器
    """
    
    def __init__(self, total: int, desc: str = "Processing"):
        self.total = total
        self.current = 0
        self.desc = desc
        self.start_time = datetime.now()
        self.errors = 0
    
    def update(self, n: int = 1, error: bool = False) -> None:
        """更新进度"""
        self.current += n
        if error:
            self.errors += 1
        
        elapsed = (datetime.now() - self.start_time).total_seconds()
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0
        
        logger.info(
            f"{self.desc}: {self.current}/{self.total} "
            f"({self.current/self.total*100:.1f}%) "
            f"[{rate:.1f}/s, ETA: {eta:.0f}s, Errors: {self.errors}]"
        )
    
    def finish(self) -> Dict[str, Any]:
        """完成并返回统计"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "total": self.total,
            "completed": self.current,
            "errors": self.errors,
            "elapsed_seconds": elapsed,
            "rate": self.current / elapsed if elapsed > 0 else 0
        }


# ==================== URL工具 ====================

def build_hf_url(paper_id: str) -> str:
    """构建HuggingFace论文URL"""
    return f"https://huggingface.co/papers/{paper_id}"


def build_arxiv_url(paper_id: str) -> str:
    """构建arXiv论文URL"""
    return f"https://arxiv.org/abs/{paper_id}"


def build_arxiv_pdf_url(paper_id: str) -> str:
    """构建arXiv PDF URL"""
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def build_ar5iv_url(paper_id: str) -> str:
    """构建ar5iv HTML URL"""
    return f"https://ar5iv.labs.arxiv.org/html/{paper_id}"


def build_hf_monthly_url(month: str) -> str:
    """构建HuggingFace月度论文URL"""
    return f"https://huggingface.co/papers/month/{month}"


if __name__ == "__main__":
    # 测试工具函数
    print("=" * 50)
    print("Utils Test")
    print("=" * 50)
    
    # 测试月份生成
    months = list(generate_months("2024-01", "2024-03"))
    print(f"Months: {months}")
    
    # 测试文本处理
    text = "This is a   very   long text that needs to be truncated"
    print(f"Clean: {clean_text(text)}")
    print(f"Truncate: {truncate_text(text, 30)}")
    
    # 测试URL提取
    url = "https://huggingface.co/papers/2512.02556"
    print(f"Paper ID: {extract_paper_id(url)}")
    
    # 测试JSON解析
    json_text = '```json\n{"key": "value"}\n```'
    print(f"Parsed: {safe_json_parse(json_text)}")
    
    # 测试URL构建
    paper_id = "2512.02556"
    print(f"HF URL: {build_hf_url(paper_id)}")
    print(f"ar5iv URL: {build_ar5iv_url(paper_id)}")