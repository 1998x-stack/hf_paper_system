# HuggingFace Papers Aggregation System

A comprehensive system for aggregating, analyzing, and organizing academic papers from HuggingFace and ar5iv.

## Architecture

Following CleanRL design principles:
- **Single-file modules**: Each file is self-contained and focused
- **Minimal abstraction**: Clear, readable code over complex patterns
- **Explicit dependencies**: No hidden state or magic

## Project Structure

```
hf_paper_system/
├── config.py           # Configuration and settings
├── models.py           # Pydantic data models
├── scraper_hf.py       # HuggingFace papers scraper
├── scraper_ar5iv.py    # ar5iv content extractor  
├── llm_processor.py    # Ollama LLM integration
├── notion_client.py    # Notion API integration
├── utils.py            # Shared utilities
├── main.py             # Main orchestrator
├── requirements.txt    # Dependencies
└── data/               # Output directory
    ├── raw/            # Raw scraped data
    │   ├── hf_papers_{YYYY-MM}.jsonl
    │   └── ar5iv_{paper_id}.json
    ├── processed/      # Processed with LLM
    │   ├── classified_{YYYY-MM}.jsonl
    │   └── papers_full_{paper_id}.json
    ├── llm_outputs/    # Raw LLM responses
    │   ├── classification/
    │   ├── keywords/
    │   ├── labels/
    │   └── comments/
    └── logs/           # Application logs
```

## Features

1. **HuggingFace Scraper**: Fetch papers with votes > threshold
2. **ar5iv Extractor**: Extract full paper content with BeautifulSoup
3. **LLM Classification**: Categorize papers using Ollama qwen3:0.6b
4. **Keyword Extraction**: Extract keywords from title + abstract
5. **Label Generation**: Generate semantic labels
6. **Paragraph Comments**: Generate reading notes with qwen3:4b
7. **Notion Integration**: Beautiful page layouts and database

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export NOTION_TOKEN=secret_xxx
export NOTION_DATABASE_ID=xxx

# Run the system
python main.py --start-month 2024-01 --end-month 2025-12 --min-votes 50
```

## Configuration

Edit `.env` or set environment variables:
- `NOTION_TOKEN`: Notion API token
- `NOTION_DATABASE_ID`: Target database ID
- `OLLAMA_HOST`: Ollama server URL (default: http://localhost:11434)

## Design Decisions

- **asyncio**: Concurrent processing with semaphore (default: 3)
- **loguru**: Structured logging with rotation
- **JSONL**: Efficient line-by-line processing
- **Pydantic**: Type-safe data models