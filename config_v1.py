"""
config.py - 配置管理模块

该模块包含所有系统配置，使用pydantic-settings进行类型安全的配置管理。
遵循CleanRL设计原则：单文件、自包含、显式配置。
"""

import os
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    系统配置类
    
    配置优先级: 环境变量 > .env文件 > 默认值
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # ==================== Notion API 配置 ====================
    notion_token: str = Field(
        default="xxx",
        description="Notion API Token"
    )
    notion_database_id: str = Field(
        default="xxx",
        description="Notion Database ID for papers"
    )
    notion_page_id: Optional[str] = Field(
        default=None,
        description="Notion Parent Page ID (optional)"
    )
    
    # ==================== Ollama 配置 ====================
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL"
    )
    ollama_model_small: str = Field(
        default="qwen3:0.6b",
        description="小模型用于分类、关键词、标签"
    )
    ollama_model_large: str = Field(
        default="qwen3:4b",
        description="大模型用于段落评论"
    )
    ollama_timeout: int = Field(
        default=120,
        description="Ollama API 超时时间（秒）"
    )
    
    # ==================== 爬虫配置 ====================
    start_month: str = Field(
        default="2025-11",
        description="起始月份 (YYYY-MM)"
    )
    end_month: str = Field(
        default="2025-12",
        description="结束月份 (YYYY-MM)"
    )
    min_votes: int = Field(
        default=50,
        description="最小投票数阈值"
    )
    
    # ==================== 并发配置 ====================
    concurrency: int = Field(
        default=3,
        description="异步并发数"
    )
    request_delay: float = Field(
        default=1.0,
        description="请求间隔（秒）"
    )
    max_retries: int = Field(
        default=3,
        description="最大重试次数"
    )
    
    # ==================== 文件路径配置 ====================
    data_dir: Path = Field(
        default=Path("data"),
        description="数据根目录"
    )
    
    @property
    def raw_dir(self) -> Path:
        """原始数据目录"""
        return self.data_dir / "raw"
    
    @property
    def processed_dir(self) -> Path:
        """处理后数据目录"""
        return self.data_dir / "processed"
    
    @property
    def llm_outputs_dir(self) -> Path:
        """LLM输出目录"""
        return self.data_dir / "llm_outputs"
    
    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return self.data_dir / "logs"
    
    # ==================== 日志配置 ====================
    log_level: str = Field(
        default="INFO",
        description="日志级别"
    )
    log_rotation: str = Field(
        default="10 MB",
        description="日志轮转大小"
    )
    log_retention: str = Field(
        default="7 days",
        description="日志保留时间"
    )
    
    # ==================== User-Agent 配置 ====================
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36",
        description="HTTP请求User-Agent"
    )
    
    @field_validator("start_month", "end_month")
    @classmethod
    def validate_month_format(cls, v: str) -> str:
        """验证月份格式"""
        try:
            datetime.strptime(v, "%Y-%m")
            return v
        except ValueError:
            raise ValueError(f"月份格式错误，应为YYYY-MM: {v}")
    
    def ensure_directories(self) -> None:
        """创建所有必要的目录"""
        directories = [
            self.raw_dir,
            self.processed_dir,
            self.llm_outputs_dir / "classification",
            self.llm_outputs_dir / "keywords",
            self.llm_outputs_dir / "labels",
            self.llm_outputs_dir / "comments",
            self.logs_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_hf_papers_file(self, month: str) -> Path:
        """获取HuggingFace论文文件路径"""
        return self.raw_dir / f"hf_papers_{month}.jsonl"
    
    def get_ar5iv_file(self, paper_id: str) -> Path:
        """获取ar5iv内容文件路径"""
        # 将paper_id中的.替换为_避免文件系统问题
        safe_id = paper_id.replace(".", "_")
        return self.raw_dir / f"ar5iv_{safe_id}.json"
    
    def get_processed_file(self, paper_id: str) -> Path:
        """获取处理后的完整论文文件路径"""
        safe_id = paper_id.replace(".", "_")
        return self.processed_dir / f"paper_full_{safe_id}.json"
    
    def get_llm_output_file(self, category: str, paper_id: str) -> Path:
        """获取LLM输出文件路径"""
        safe_id = paper_id.replace(".", "_")
        return self.llm_outputs_dir / category / f"{safe_id}.json"
    
    def get_log_file(self) -> Path:
        """获取日志文件路径"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.logs_dir / f"hf_papers_{timestamp}.log"


# ==================== 分类系统配置 ====================
PAPER_CATEGORIES = {
    "language_models": {
        "name": "Language Models",
        "name_zh": "语言模型",
        "keywords": ["llm", "gpt", "bert", "transformer", "language model", "nlp"],
    },
    "computer_vision": {
        "name": "Computer Vision",
        "name_zh": "计算机视觉",
        "keywords": ["vision", "image", "video", "cnn", "detection", "segmentation"],
    },
    "multimodal": {
        "name": "Multimodal",
        "name_zh": "多模态",
        "keywords": ["multimodal", "vision-language", "clip", "dalle", "text-to-image"],
    },
    "reinforcement_learning": {
        "name": "Reinforcement Learning",
        "name_zh": "强化学习",
        "keywords": ["reinforcement", "rl", "policy", "reward", "agent"],
    },
    "generative_models": {
        "name": "Generative Models",
        "name_zh": "生成模型",
        "keywords": ["diffusion", "gan", "vae", "generation", "synthesis"],
    },
    "alignment": {
        "name": "Alignment & Safety",
        "name_zh": "对齐与安全",
        "keywords": ["alignment", "rlhf", "safety", "harmless", "helpful"],
    },
    "efficiency": {
        "name": "Efficiency",
        "name_zh": "效率优化",
        "keywords": ["quantization", "pruning", "distillation", "efficient", "compression"],
    },
    "robotics": {
        "name": "Robotics",
        "name_zh": "机器人",
        "keywords": ["robot", "manipulation", "navigation", "embodied"],
    },
    "speech_audio": {
        "name": "Speech & Audio",
        "name_zh": "语音与音频",
        "keywords": ["speech", "audio", "tts", "asr", "voice"],
    },
    "graphs_knowledge": {
        "name": "Graphs & Knowledge",
        "name_zh": "图与知识",
        "keywords": ["graph", "knowledge", "reasoning", "retrieval", "rag"],
    },
    "other": {
        "name": "Other",
        "name_zh": "其他",
        "keywords": [],
    },
}


# ==================== 全局配置实例 ====================
def get_settings() -> Settings:
    """获取配置实例"""
    return Settings()


# 模块级别配置实例
settings = get_settings()


if __name__ == "__main__":
    # 测试配置
    print("=" * 50)
    print("Configuration Test")
    print("=" * 50)
    
    cfg = get_settings()
    cfg.ensure_directories()
    
    print(f"Notion Token: {'*' * 10 if cfg.notion_token else 'NOT SET'}")
    print(f"Ollama Host: {cfg.ollama_host}")
    print(f"Date Range: {cfg.start_month} to {cfg.end_month}")
    print(f"Min Votes: {cfg.min_votes}")
    print(f"Concurrency: {cfg.concurrency}")
    print(f"Data Dir: {cfg.data_dir.absolute()}")
    print(f"Categories: {len(PAPER_CATEGORIES)}")