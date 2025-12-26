# Notion API Python 详细操作指南

## 📋 目录
1. [环境准备](#环境准备)
2. [认证与初始化](#认证与初始化)
3. [Pages 操作](#pages-操作)
4. [Databases 操作](#databases-操作)
5. [Blocks 操作](#blocks-操作)
6. [查询与过滤](#查询与过滤)
7. [高级功能](#高级功能)
8. [实战项目](#实战项目)
9. [错误处理](#错误处理)
10. [性能优化](#性能优化)
11. [完整示例项目](#完整示例项目)

---

## 环境准备

### 1.1 安装 Python SDK

```bash
# 方法1：官方推荐的 SDK
pip install notion-client

# 方法2：另一个流行的包装器
pip install notion-sdk

# 方法3：仅使用 requests（不推荐，除非特殊需求）
pip install requests
```

### 1.2 创建 Notion 集成

#### 步骤 1：创建集成
1. 访问 https://www.notion.so/my-integrations
2. 点击 "+ New integration"
3. 填写信息：
   - **Name**: 你的集成名称（如 "My Python App"）
   - **Associated workspace**: 选择工作空间
   - **Type**: Internal Integration（内部集成）
4. 设置权限：
   - ☑️ Read content
   - ☑️ Update content
   - ☑️ Insert content
5. 点击 "Submit"
6. 复制 "Internal Integration Token"（格式：`secret_xxx...`）

#### 步骤 2：分享页面/数据库给集成
1. 打开要操作的 Notion 页面或数据库
2. 点击右上角 "..." → "Add connections"
3. 选择你创建的集成
4. 点击 "Confirm"

### 1.3 项目结构设置

```bash
notion-project/
├── .env                 # 环境变量（不要提交到 Git）
├── .gitignore          # Git 忽略文件
├── requirements.txt    # 依赖列表
├── config.py          # 配置管理
├── notion_client.py   # Notion 客户端封装
├── models.py          # 数据模型
├── utils.py           # 工具函数
└── main.py            # 主程序
```

### 1.4 环境变量配置

创建 `.env` 文件：

```env
# Notion API 配置
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_PAGE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# API 版本
NOTION_VERSION=2022-06-28

# 日志级别
LOG_LEVEL=INFO
```

创建 `.gitignore` 文件：

```gitignore
# 环境变量
.env
.env.local

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/

# IDE
.vscode/
.idea/

# 日志
*.log
```

创建 `requirements.txt`：

```txt
notion-client==2.2.1
python-dotenv==1.0.0
requests==2.31.0
tenacity==8.2.3
```

安装依赖：

```bash
pip install -r requirements.txt
```

---

## 认证与初始化

### 2.1 基础初始化

```python
# config.py
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Notion 配置
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
PAGE_ID = os.getenv("NOTION_PAGE_ID")

# 验证配置
if not NOTION_TOKEN:
    raise ValueError("NOTION_TOKEN 未设置，请检查 .env 文件")
```

```python
# notion_client.py
from notion_client import Client
from config import NOTION_TOKEN
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NotionClient:
    """Notion API 客户端封装"""
    
    def __init__(self, auth_token=None):
        self.auth_token = auth_token or NOTION_TOKEN
        self.client = Client(auth=self.auth_token)
        logger.info("Notion 客户端初始化成功")
    
    def get_client(self):
        """获取原始客户端"""
        return self.client

# 创建全局客户端实例
notion = NotionClient().get_client()
```

### 2.2 异步客户端

```python
# async_notion_client.py
from notion_client import AsyncClient
from config import NOTION_TOKEN
import asyncio

class AsyncNotionClient:
    """异步 Notion 客户端"""
    
    def __init__(self, auth_token=None):
        self.auth_token = auth_token or NOTION_TOKEN
        self.client = AsyncClient(auth=self.auth_token)
    
    async def get_page(self, page_id):
        """异步获取页面"""
        return await self.client.pages.retrieve(page_id)
    
    async def batch_get_pages(self, page_ids):
        """批量异步获取页面"""
        tasks = [self.get_page(pid) for pid in page_ids]
        return await asyncio.gather(*tasks)

# 使用示例
async def main():
    client = AsyncNotionClient()
    pages = await client.batch_get_pages(['page_id_1', 'page_id_2'])
    print(pages)

# asyncio.run(main())
```

### 2.3 使用 requests 库（底层方式）

```python
# raw_client.py
import requests
from config import NOTION_TOKEN, NOTION_VERSION

class RawNotionClient:
    """使用 requests 的原始客户端"""
    
    BASE_URL = "https://api.notion.com/v1"
    
    def __init__(self, auth_token=None):
        self.auth_token = auth_token or NOTION_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION
        }
    
    def get(self, endpoint):
        """GET 请求"""
        url = f"{self.BASE_URL}/{endpoint}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def post(self, endpoint, data):
        """POST 请求"""
        url = f"{self.BASE_URL}/{endpoint}"
        response = requests.post(url, json=data, headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def patch(self, endpoint, data):
        """PATCH 请求"""
        url = f"{self.BASE_URL}/{endpoint}"
        response = requests.patch(url, json=data, headers=self.headers)
        response.raise_for_status()
        return response.json()

# 使用示例
# client = RawNotionClient()
# page = client.get(f"pages/{page_id}")
```

---

## Pages 操作

### 3.1 创建页面

#### 基础页面创建

```python
from notion_client import Client
from config import NOTION_TOKEN, PAGE_ID

notion = Client(auth=NOTION_TOKEN)

def create_simple_page(parent_page_id):
    """创建简单页面"""
    new_page = notion.pages.create(
        parent={"page_id": parent_page_id},
        properties={
            "title": {
                "title": [
                    {
                        "text": {
                            "content": "我的新页面"
                        }
                    }
                ]
            }
        }
    )
    return new_page

# 使用
page = create_simple_page(PAGE_ID)
print(f"创建页面成功，ID: {page['id']}")
```

#### 在数据库中创建页面

```python
def create_database_page(database_id, title, status="Not Started", priority="Medium"):
    """在数据库中创建页面"""
    new_page = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {  # 标题属性
                "title": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            },
            "Status": {  # 状态属性（Select）
                "select": {
                    "name": status
                }
            },
            "Priority": {  # 优先级属性（Select）
                "select": {
                    "name": priority
                }
            },
            "Due Date": {  # 截止日期
                "date": {
                    "start": "2024-12-31"
                }
            }
        }
    )
    return new_page

# 使用示例
page = create_database_page(
    database_id="your_database_id",
    title="完成项目报告",
    status="In Progress",
    priority="High"
)
```

#### 创建带内容的页面

```python
def create_page_with_content(parent_page_id, title, content_blocks):
    """创建带内容块的页面"""
    new_page = notion.pages.create(
        parent={"page_id": parent_page_id},
        properties={
            "title": {
                "title": [{"text": {"content": title}}]
            }
        },
        children=content_blocks  # 添加内容块
    )
    return new_page

# 内容块示例
content_blocks = [
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"text": {"content": "项目概述"}}]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "text": {
                        "content": "这是项目的详细描述。"
                    }
                }
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"text": {"content": "第一项任务"}}]
        }
    }
]

page = create_page_with_content(
    parent_page_id=PAGE_ID,
    title="项目计划",
    content_blocks=content_blocks
)
```

### 3.2 获取页面

```python
def get_page(page_id):
    """获取页面信息"""
    page = notion.pages.retrieve(page_id)
    return page

def extract_page_title(page):
    """提取页面标题"""
    title_property = page['properties'].get('title') or page['properties'].get('Name')
    if title_property:
        title_array = title_property.get('title', [])
        if title_array:
            return ''.join([t['text']['content'] for t in title_array])
    return "无标题"

# 使用
page = get_page(PAGE_ID)
title = extract_page_title(page)
print(f"页面标题: {title}")
```

### 3.3 更新页面

```python
def update_page_properties(page_id, properties):
    """更新页面属性"""
    updated_page = notion.pages.update(
        page_id=page_id,
        properties=properties
    )
    return updated_page

# 更新标题
update_page_properties(
    page_id="your_page_id",
    properties={
        "Name": {
            "title": [{"text": {"content": "更新后的标题"}}]
        }
    }
)

# 更新多个属性
update_page_properties(
    page_id="your_page_id",
    properties={
        "Status": {"select": {"name": "Completed"}},
        "Priority": {"select": {"name": "Low"}},
        "Checkbox": {"checkbox": True}
    }
)
```

### 3.4 归档页面

```python
def archive_page(page_id):
    """归档（软删除）页面"""
    notion.pages.update(
        page_id=page_id,
        archived=True
    )
    print(f"页面 {page_id} 已归档")

def unarchive_page(page_id):
    """恢复归档的页面"""
    notion.pages.update(
        page_id=page_id,
        archived=False
    )
    print(f"页面 {page_id} 已恢复")
```

### 3.5 获取页面属性

```python
def get_page_property(page_id, property_id):
    """获取特定属性值"""
    property_item = notion.pages.properties.retrieve(
        page_id=page_id,
        property_id=property_id
    )
    return property_item

# 辅助函数：解析不同类型的属性
def parse_property_value(prop):
    """解析属性值"""
    prop_type = prop['type']
    
    if prop_type == 'title':
        return ''.join([t['text']['content'] for t in prop['title']])
    elif prop_type == 'rich_text':
        return ''.join([t['text']['content'] for t in prop['rich_text']])
    elif prop_type == 'number':
        return prop['number']
    elif prop_type == 'select':
        return prop['select']['name'] if prop['select'] else None
    elif prop_type == 'multi_select':
        return [s['name'] for s in prop['multi_select']]
    elif prop_type == 'date':
        return prop['date']
    elif prop_type == 'checkbox':
        return prop['checkbox']
    elif prop_type == 'url':
        return prop['url']
    elif prop_type == 'email':
        return prop['email']
    elif prop_type == 'phone_number':
        return prop['phone_number']
    elif prop_type == 'people':
        return [p['name'] for p in prop['people']]
    else:
        return None

# 使用示例
def print_all_properties(page_id):
    """打印页面所有属性"""
    page = notion.pages.retrieve(page_id)
    for prop_name, prop_value in page['properties'].items():
        value = parse_property_value(prop_value)
        print(f"{prop_name}: {value}")
```

---

## Databases 操作

### 4.1 创建数据库

```python
def create_database(parent_page_id, title, properties):
    """创建新数据库"""
    new_db = notion.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[
            {
                "type": "text",
                "text": {"content": title}
            }
        ],
        properties=properties
    )
    return new_db

# 定义数据库结构
task_database_schema = {
    "Name": {"title": {}},  # 标题列
    "Status": {
        "select": {
            "options": [
                {"name": "Not Started", "color": "gray"},
                {"name": "In Progress", "color": "blue"},
                {"name": "Completed", "color": "green"},
                {"name": "Archived", "color": "red"}
            ]
        }
    },
    "Priority": {
        "select": {
            "options": [
                {"name": "High", "color": "red"},
                {"name": "Medium", "color": "yellow"},
                {"name": "Low", "color": "gray"}
            ]
        }
    },
    "Due Date": {"date": {}},
    "Assignee": {"people": {}},
    "Tags": {"multi_select": {}},
    "Progress": {"number": {"format": "percent"}},
    "URL": {"url": {}},
    "Notes": {"rich_text": {}}
}

# 创建任务数据库
db = create_database(
    parent_page_id=PAGE_ID,
    title="任务管理",
    properties=task_database_schema
)
print(f"数据库创建成功，ID: {db['id']}")
```

### 4.2 获取数据库

```python
def get_database(database_id):
    """获取数据库信息"""
    database = notion.databases.retrieve(database_id)
    return database

def get_database_schema(database_id):
    """获取数据库结构"""
    db = get_database(database_id)
    properties = db['properties']
    
    schema = {}
    for prop_name, prop_config in properties.items():
        schema[prop_name] = prop_config['type']
    
    return schema

# 使用
schema = get_database_schema("your_database_id")
print("数据库结构:")
for name, type in schema.items():
    print(f"  {name}: {type}")
```

### 4.3 更新数据库

```python
def update_database(database_id, title=None, properties=None):
    """更新数据库"""
    update_data = {}
    
    if title:
        update_data['title'] = [{"text": {"content": title}}]
    
    if properties:
        update_data['properties'] = properties
    
    updated_db = notion.databases.update(
        database_id=database_id,
        **update_data
    )
    return updated_db

# 添加新属性
update_database(
    database_id="your_database_id",
    properties={
        "Budget": {
            "number": {
                "format": "dollar"
            }
        }
    }
)

# 修改现有属性
update_database(
    database_id="your_database_id",
    properties={
        "Status": {
            "select": {
                "options": [
                    {"name": "To Do", "color": "gray"},
                    {"name": "Doing", "color": "blue"},
                    {"name": "Done", "color": "green"}
                ]
            }
        }
    }
)
```

### 4.4 查询数据库

#### 基础查询

```python
def query_database(database_id, filter=None, sorts=None, start_cursor=None, page_size=100):
    """查询数据库"""
    query_params = {
        "database_id": database_id,
        "page_size": page_size
    }
    
    if filter:
        query_params["filter"] = filter
    
    if sorts:
        query_params["sorts"] = sorts
    
    if start_cursor:
        query_params["start_cursor"] = start_cursor
    
    response = notion.databases.query(**query_params)
    return response

# 获取所有记录
all_results = query_database("your_database_id")
print(f"共有 {len(all_results['results'])} 条记录")
```

#### 分页查询

```python
def query_all_pages(database_id, filter=None, sorts=None):
    """查询所有页面（处理分页）"""
    all_results = []
    has_more = True
    start_cursor = None
    
    while has_more:
        response = query_database(
            database_id=database_id,
            filter=filter,
            sorts=sorts,
            start_cursor=start_cursor
        )
        
        all_results.extend(response['results'])
        has_more = response['has_more']
        start_cursor = response.get('next_cursor')
    
    return all_results

# 使用辅助函数（推荐）
from notion_client.helpers import iterate_paginated_api

def query_all_with_helper(database_id):
    """使用辅助函数查询所有页面"""
    all_pages = []
    for page in iterate_paginated_api(
        notion.databases.query,
        database_id=database_id
    ):
        all_pages.append(page)
    return all_pages
```

---

## Blocks 操作

### 5.1 获取块

```python
def get_block(block_id):
    """获取块信息"""
    block = notion.blocks.retrieve(block_id)
    return block

def get_block_children(block_id):
    """获取块的子块"""
    children = notion.blocks.children.list(block_id)
    return children['results']

def get_all_block_children(block_id):
    """获取所有子块（处理分页）"""
    from notion_client.helpers import iterate_paginated_api
    
    all_children = []
    for child in iterate_paginated_api(
        notion.blocks.children.list,
        block_id=block_id
    ):
        all_children.append(child)
    return all_children
```

### 5.2 添加块

```python
def append_blocks(block_id, children):
    """追加子块"""
    response = notion.blocks.children.append(
        block_id=block_id,
        children=children
    )
    return response

# 创建各种类型的块
def create_heading_block(level, text):
    """创建标题块 (1-3)"""
    heading_type = f"heading_{level}"
    return {
        "object": "block",
        "type": heading_type,
        heading_type: {
            "rich_text": [{"text": {"content": text}}]
        }
    }

def create_paragraph_block(text, bold=False, italic=False, color="default"):
    """创建段落块"""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "text": {"content": text},
                    "annotations": {
                        "bold": bold,
                        "italic": italic,
                        "color": color
                    }
                }
            ]
        }
    }

def create_list_block(text, type="bulleted"):
    """创建列表块"""
    list_type = f"{type}_list_item"
    return {
        "object": "block",
        "type": list_type,
        list_type: {
            "rich_text": [{"text": {"content": text}}]
        }
    }

def create_code_block(code, language="python"):
    """创建代码块"""
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"text": {"content": code}}],
            "language": language
        }
    }

def create_quote_block(text):
    """创建引用块"""
    return {
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [{"text": {"content": text}}]
        }
    }

def create_callout_block(text, emoji="💡", color="gray_background"):
    """创建标注块"""
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"text": {"content": text}}],
            "icon": {"emoji": emoji},
            "color": color
        }
    }

def create_divider_block():
    """创建分隔线"""
    return {
        "object": "block",
        "type": "divider",
        "divider": {}
    }

def create_to_do_block(text, checked=False):
    """创建待办事项块"""
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "rich_text": [{"text": {"content": text}}],
            "checked": checked
        }
    }

def create_toggle_block(text, children=None):
    """创建折叠块"""
    toggle = {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"text": {"content": text}}]
        }
    }
    if children:
        toggle["toggle"]["children"] = children
    return toggle

# 使用示例：创建完整的文档结构
blocks = [
    create_heading_block(1, "项目文档"),
    create_paragraph_block("这是项目的主要文档。", bold=True),
    create_divider_block(),
    create_heading_block(2, "功能列表"),
    create_list_block("功能 A", "bulleted"),
    create_list_block("功能 B", "bulleted"),
    create_list_block("功能 C", "bulleted"),
    create_heading_block(2, "代码示例"),
    create_code_block("def hello():\n    print('Hello, World!')", "python"),
    create_callout_block("注意：这是重要的提示信息", "⚠️", "yellow_background"),
    create_to_do_block("完成文档审核", False)
]

# 添加到页面
append_blocks(PAGE_ID, blocks)
```

### 5.3 更新块

```python
def update_block(block_id, block_data):
    """更新块内容"""
    updated_block = notion.blocks.update(
        block_id=block_id,
        **block_data
    )
    return updated_block

# 更新段落块
update_block(
    block_id="your_block_id",
    block_data={
        "paragraph": {
            "rich_text": [
                {
                    "text": {"content": "更新后的文本"},
                    "annotations": {"bold": True}
                }
            ]
        }
    }
)

# 更新待办事项
update_block(
    block_id="your_todo_block_id",
    block_data={
        "to_do": {
            "rich_text": [{"text": {"content": "已完成的任务"}}],
            "checked": True
        }
    }
)
```

### 5.4 删除块

```python
def delete_block(block_id):
    """删除块（归档）"""
    notion.blocks.delete(block_id)
    print(f"块 {block_id} 已删除")

# 批量删除
def delete_multiple_blocks(block_ids):
    """批量删除块"""
    for block_id in block_ids:
        try:
            delete_block(block_id)
        except Exception as e:
            print(f"删除块 {block_id} 失败: {e}")
```

---

## 查询与过滤

### 6.1 过滤器（Filters）

```python
# 基础过滤器
def filter_by_status(database_id, status):
    """按状态过滤"""
    filter_params = {
        "property": "Status",
        "select": {
            "equals": status
        }
    }
    return query_database(database_id, filter=filter_params)

# 多条件过滤（AND）
def filter_multi_and(database_id):
    """多条件 AND 过滤"""
    filter_params = {
        "and": [
            {
                "property": "Status",
                "select": {"equals": "In Progress"}
            },
            {
                "property": "Priority",
                "select": {"equals": "High"}
            }
        ]
    }
    return query_database(database_id, filter=filter_params)

# 多条件过滤（OR）
def filter_multi_or(database_id):
    """多条件 OR 过滤"""
    filter_params = {
        "or": [
            {
                "property": "Priority",
                "select": {"equals": "High"}
            },
            {
                "property": "Priority",
                "select": {"equals": "Urgent"}
            }
        ]
    }
    return query_database(database_id, filter=filter_params)

# 文本过滤
def filter_by_text_contains(database_id, property_name, text):
    """文本包含过滤"""
    filter_params = {
        "property": property_name,
        "rich_text": {
            "contains": text
        }
    }
    return query_database(database_id, filter=filter_params)

# 数字过滤
def filter_by_number_greater_than(database_id, property_name, value):
    """数字大于过滤"""
    filter_params = {
        "property": property_name,
        "number": {
            "greater_than": value
        }
    }
    return query_database(database_id, filter=filter_params)

# 日期过滤
def filter_by_date_after(database_id, property_name, date):
    """日期之后过滤"""
    filter_params = {
        "property": property_name,
        "date": {
            "after": date  # 格式: "2024-01-01"
        }
    }
    return query_database(database_id, filter=filter_params)

# 复选框过滤
def filter_by_checkbox(database_id, property_name, checked=True):
    """复选框过滤"""
    filter_params = {
        "property": property_name,
        "checkbox": {
            "equals": checked
        }
    }
    return query_database(database_id, filter=filter_params)

# 人员过滤
def filter_by_person(database_id, property_name, person_id):
    """按人员过滤"""
    filter_params = {
        "property": property_name,
        "people": {
            "contains": person_id
        }
    }
    return query_database(database_id, filter=filter_params)

# 空值过滤
def filter_empty(database_id, property_name):
    """过滤空值"""
    filter_params = {
        "property": property_name,
        "is_empty": True
    }
    return query_database(database_id, filter=filter_params)

def filter_not_empty(database_id, property_name):
    """过滤非空值"""
    filter_params = {
        "property": property_name,
        "is_not_empty": True
    }
    return query_database(database_id, filter=filter_params)
```

### 6.2 排序（Sorts）

```python
# 单字段排序
def sort_by_property(database_id, property_name, direction="ascending"):
    """按属性排序"""
    sorts = [
        {
            "property": property_name,
            "direction": direction  # "ascending" 或 "descending"
        }
    ]
    return query_database(database_id, sorts=sorts)

# 多字段排序
def sort_by_multiple_properties(database_id):
    """多字段排序"""
    sorts = [
        {
            "property": "Priority",
            "direction": "descending"
        },
        {
            "property": "Due Date",
            "direction": "ascending"
        }
    ]
    return query_database(database_id, sorts=sorts)

# 按时间戳排序
def sort_by_created_time(database_id):
    """按创建时间排序"""
    sorts = [
        {
            "timestamp": "created_time",
            "direction": "descending"
        }
    ]
    return query_database(database_id, sorts=sorts)

def sort_by_last_edited_time(database_id):
    """按最后编辑时间排序"""
    sorts = [
        {
            "timestamp": "last_edited_time",
            "direction": "descending"
        }
    ]
    return query_database(database_id, sorts=sorts)
```

### 6.3 组合查询示例

```python
def complex_query_example(database_id):
    """复杂查询示例"""
    # 查询：状态为"进行中"或"未开始"，
    # 优先级为"高"，
    # 截止日期在下周之内，
    # 按优先级降序、截止日期升序排列
    
    from datetime import datetime, timedelta
    
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    filter_params = {
        "and": [
            {
                "or": [
                    {"property": "Status", "select": {"equals": "In Progress"}},
                    {"property": "Status", "select": {"equals": "Not Started"}}
                ]
            },
            {
                "property": "Priority",
                "select": {"equals": "High"}
            },
            {
                "property": "Due Date",
                "date": {"on_or_before": next_week}
            }
        ]
    }
    
    sorts = [
        {"property": "Priority", "direction": "descending"},
        {"property": "Due Date", "direction": "ascending"}
    ]
    
    results = query_database(
        database_id=database_id,
        filter=filter_params,
        sorts=sorts
    )
    
    return results

# 实用查询函数
def get_overdue_tasks(database_id):
    """获取过期任务"""
    from datetime import datetime
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    filter_params = {
        "and": [
            {
                "property": "Due Date",
                "date": {"before": today}
            },
            {
                "property": "Status",
                "select": {"does_not_equal": "Completed"}
            }
        ]
    }
    
    return query_database(database_id, filter=filter_params)

def get_my_tasks(database_id, user_id):
    """获取我的任务"""
    filter_params = {
        "and": [
            {
                "property": "Assignee",
                "people": {"contains": user_id}
            },
            {
                "property": "Status",
                "select": {"does_not_equal": "Completed"}
            }
        ]
    }
    
    sorts = [
        {"property": "Priority", "direction": "descending"},
        {"property": "Due Date", "direction": "ascending"}
    ]
    
    return query_database(database_id, filter=filter_params, sorts=sorts)
```

---

## 高级功能

### 7.1 富文本处理

```python
def create_rich_text(text, bold=False, italic=False, strikethrough=False, 
                     underline=False, code=False, color="default", link=None):
    """创建富文本对象"""
    rich_text = {
        "text": {"content": text},
        "annotations": {
            "bold": bold,
            "italic": italic,
            "strikethrough": strikethrough,
            "underline": underline,
            "code": code,
            "color": color
        }
    }
    
    if link:
        rich_text["text"]["link"] = {"url": link}
    
    return rich_text

# 创建多样式文本
def create_mixed_style_text():
    """创建混合样式文本"""
    return [
        create_rich_text("这是普通文本。"),
        create_rich_text("这是粗体。", bold=True),
        create_rich_text("这是斜体。", italic=True),
        create_rich_text("这是链接。", link="https://example.com"),
        create_rich_text("这是代码。", code=True),
        create_rich_text("这是红色文本。", color="red")
    ]

# 使用示例
paragraph_with_styles = {
    "object": "block",
    "type": "paragraph",
    "paragraph": {
        "rich_text": create_mixed_style_text()
    }
}
```

### 7.2 文件上传

```python
def create_file_property(url, name=None):
    """创建文件属性"""
    file_obj = {
        "type": "external",
        "external": {"url": url}
    }
    if name:
        file_obj["name"] = name
    return file_obj

def add_file_to_page(page_id, file_url, file_name="附件"):
    """向页面添加文件"""
    file_block = {
        "object": "block",
        "type": "file",
        "file": create_file_property(file_url, file_name)
    }
    
    append_blocks(page_id, [file_block])

# 添加图片
def add_image_to_page(page_id, image_url, caption=None):
    """向页面添加图片"""
    image_block = {
        "object": "block",
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": image_url}
        }
    }
    
    if caption:
        image_block["image"]["caption"] = [
            {"text": {"content": caption}}
        ]
    
    append_blocks(page_id, [image_block])

# 添加 PDF
def add_pdf_to_page(page_id, pdf_url):
    """向页面添加 PDF"""
    pdf_block = {
        "object": "block",
        "type": "pdf",
        "pdf": {
            "type": "external",
            "external": {"url": pdf_url}
        }
    }
    
    append_blocks(page_id, [pdf_block])
```

### 7.3 评论功能

```python
def create_comment(page_id, text):
    """创建评论"""
    comment = notion.comments.create(
        parent={"page_id": page_id},
        rich_text=[
            {
                "text": {"content": text}
            }
        ]
    )
    return comment

def get_comments(page_id):
    """获取页面评论"""
    comments = notion.comments.list(
        block_id=page_id
    )
    return comments['results']

# 使用示例
def add_comment_with_mention(page_id, text, user_id):
    """添加带提及的评论"""
    comment = notion.comments.create(
        parent={"page_id": page_id},
        rich_text=[
            {
                "type": "mention",
                "mention": {
                    "type": "user",
                    "user": {"id": user_id}
                }
            },
            {
                "text": {"content": f" {text}"}
            }
        ]
    )
    return comment
```

### 7.4 搜索功能

```python
def search_notion(query, filter_type=None):
    """搜索 Notion"""
    search_params = {"query": query}
    
    if filter_type:
        search_params["filter"] = {
            "value": filter_type,  # "page" 或 "database"
            "property": "object"
        }
    
    results = notion.search(**search_params)
    return results['results']

# 搜索页面
def search_pages(query):
    """仅搜索页面"""
    return search_notion(query, filter_type="page")

# 搜索数据库
def search_databases(query):
    """仅搜索数据库"""
    return search_notion(query, filter_type="database")

# 使用示例
pages = search_pages("项目")
for page in pages:
    title = extract_page_title(page)
    print(f"找到页面: {title}")
```

### 7.5 用户管理

```python
def list_all_users():
    """列出所有用户"""
    users = notion.users.list()
    return users['results']

def get_user(user_id):
    """获取用户信息"""
    user = notion.users.retrieve(user_id)
    return user

def get_current_user():
    """获取当前用户（机器人用户）"""
    bot_user = notion.users.me()
    return bot_user

# 打印工作空间所有用户
def print_workspace_users():
    """打印工作空间用户"""
    users = list_all_users()
    print(f"工作空间共有 {len(users)} 个用户:")
    for user in users:
        name = user.get('name', 'Unknown')
        user_type = user.get('type', 'unknown')
        print(f"  - {name} ({user_type})")
```

---

## 实战项目

### 8.1 任务管理系统

```python
# task_manager.py
from notion_client import Client
from datetime import datetime, timedelta
from config import NOTION_TOKEN

class TaskManager:
    """任务管理系统"""
    
    def __init__(self, database_id):
        self.notion = Client(auth=NOTION_TOKEN)
        self.database_id = database_id
    
    def create_task(self, title, description="", priority="Medium", 
                   due_date=None, assignee_id=None, tags=None):
        """创建任务"""
        properties = {
            "Name": {
                "title": [{"text": {"content": title}}]
            },
            "Status": {
                "select": {"name": "Not Started"}
            },
            "Priority": {
                "select": {"name": priority}
            }
        }
        
        if due_date:
            properties["Due Date"] = {
                "date": {"start": due_date}
            }
        
        if assignee_id:
            properties["Assignee"] = {
                "people": [{"id": assignee_id}]
            }
        
        if tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in tags]
            }
        
        # 创建页面
        page = self.notion.pages.create(
            parent={"database_id": self.database_id},
            properties=properties
        )
        
        # 添加描述
        if description:
            self.notion.blocks.children.append(
                block_id=page['id'],
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": description}}]
                        }
                    }
                ]
            )
        
        return page
    
    def update_task_status(self, page_id, status):
        """更新任务状态"""
        self.notion.pages.update(
            page_id=page_id,
            properties={
                "Status": {"select": {"name": status}}
            }
        )
    
    def complete_task(self, page_id):
        """完成任务"""
        self.update_task_status(page_id, "Completed")
    
    def get_my_tasks(self, user_id, status=None):
        """获取我的任务"""
        filter_params = {
            "property": "Assignee",
            "people": {"contains": user_id}
        }
        
        if status:
            filter_params = {
                "and": [
                    filter_params,
                    {"property": "Status", "select": {"equals": status}}
                ]
            }
        
        results = self.notion.databases.query(
            database_id=self.database_id,
            filter=filter_params,
            sorts=[
                {"property": "Priority", "direction": "descending"},
                {"property": "Due Date", "direction": "ascending"}
            ]
        )
        
        return results['results']
    
    def get_overdue_tasks(self):
        """获取过期任务"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        filter_params = {
            "and": [
                {
                    "property": "Due Date",
                    "date": {"before": today}
                },
                {
                    "property": "Status",
                    "select": {"does_not_equal": "Completed"}
                }
            ]
        }
        
        results = self.notion.databases.query(
            database_id=self.database_id,
            filter=filter_params
        )
        
        return results['results']
    
    def add_comment(self, page_id, comment_text):
        """添加评论"""
        self.notion.comments.create(
            parent={"page_id": page_id},
            rich_text=[{"text": {"content": comment_text}}]
        )

# 使用示例
if __name__ == "__main__":
    tm = TaskManager(database_id="your_database_id")
    
    # 创建任务
    task = tm.create_task(
        title="完成 API 文档",
        description="编写完整的 Notion API 使用文档",
        priority="High",
        due_date="2024-12-31",
        tags=["文档", "API"]
    )
    print(f"任务创建成功: {task['id']}")
    
    # 获取过期任务
    overdue = tm.get_overdue_tasks()
    print(f"有 {len(overdue)} 个过期任务")
```

### 8.2 内容管理系统（CMS）

```python
# cms.py
from notion_client import Client
from datetime import datetime
import markdown
from config import NOTION_TOKEN

class NotionCMS:
    """Notion 作为 CMS"""
    
    def __init__(self, database_id):
        self.notion = Client(auth=NOTION_TOKEN)
        self.database_id = database_id
    
    def create_blog_post(self, title, slug, content, tags=None, 
                        published=False, author_id=None):
        """创建博客文章"""
        properties = {
            "Title": {
                "title": [{"text": {"content": title}}]
            },
            "Slug": {
                "rich_text": [{"text": {"content": slug}}]
            },
            "Status": {
                "select": {"name": "Published" if published else "Draft"}
            },
            "Published Date": {
                "date": {"start": datetime.now().strftime("%Y-%m-%d")}
            } if published else None
        }
        
        if tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in tags]
            }
        
        if author_id:
            properties["Author"] = {
                "people": [{"id": author_id}]
            }
        
        # 移除 None 值
        properties = {k: v for k, v in properties.items() if v is not None}
        
        # 创建页面
        page = self.notion.pages.create(
            parent={"database_id": self.database_id},
            properties=properties
        )
        
        # 添加内容
        if content:
            # 将内容转换为 Notion 块
            blocks = self._content_to_blocks(content)
            self.notion.blocks.children.append(
                block_id=page['id'],
                children=blocks
            )
        
        return page
    
    def _content_to_blocks(self, content):
        """将内容转换为 Notion 块"""
        # 简单示例：按段落分割
        blocks = []
        paragraphs = content.split('\n\n')
        
        for para in paragraphs:
            if para.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": para.strip()}}]
                    }
                })
        
        return blocks
    
    def get_published_posts(self):
        """获取已发布的文章"""
        results = self.notion.databases.query(
            database_id=self.database_id,
            filter={
                "property": "Status",
                "select": {"equals": "Published"}
            },
            sorts=[
                {"property": "Published Date", "direction": "descending"}
            ]
        )
        
        return results['results']
    
    def get_post_by_slug(self, slug):
        """根据 slug 获取文章"""
        results = self.notion.databases.query(
            database_id=self.database_id,
            filter={
                "property": "Slug",
                "rich_text": {"equals": slug}
            }
        )
        
        if results['results']:
            return results['results'][0]
        return None
    
    def publish_post(self, page_id):
        """发布文章"""
        self.notion.pages.update(
            page_id=page_id,
            properties={
                "Status": {"select": {"name": "Published"}},
                "Published Date": {
                    "date": {"start": datetime.now().strftime("%Y-%m-%d")}
                }
            }
        )
    
    def export_to_markdown(self, page_id):
        """导出为 Markdown"""
        # 获取页面内容
        blocks = self.notion.blocks.children.list(page_id)['results']
        
        markdown_content = []
        for block in blocks:
            block_type = block['type']
            
            if block_type == 'paragraph':
                text = self._extract_text(block['paragraph']['rich_text'])
                markdown_content.append(text + '\n')
            
            elif block_type.startswith('heading_'):
                level = block_type.split('_')[1]
                text = self._extract_text(block[block_type]['rich_text'])
                markdown_content.append('#' * int(level) + ' ' + text + '\n')
            
            elif block_type == 'bulleted_list_item':
                text = self._extract_text(block['bulleted_list_item']['rich_text'])
                markdown_content.append('- ' + text + '\n')
            
            elif block_type == 'numbered_list_item':
                text = self._extract_text(block['numbered_list_item']['rich_text'])
                markdown_content.append('1. ' + text + '\n')
        
        return '\n'.join(markdown_content)
    
    def _extract_text(self, rich_text_array):
        """提取富文本内容"""
        return ''.join([rt['text']['content'] for rt in rich_text_array])

# 使用示例
if __name__ == "__main__":
    cms = NotionCMS(database_id="your_blog_database_id")
    
    # 创建博客文章
    post = cms.create_blog_post(
        title="Notion API 入门指南",
        slug="notion-api-guide",
        content="这是一篇关于 Notion API 的完整指南...",
        tags=["技术", "API", "教程"],
        published=True
    )
    print(f"文章创建成功: {post['id']}")
    
    # 获取已发布文章
    posts = cms.get_published_posts()
    print(f"共有 {len(posts)} 篇已发布文章")
```

### 8.3 数据同步系统

```python
# data_sync.py
from notion_client import Client
import requests
from datetime import datetime
from config import NOTION_TOKEN

class DataSyncManager:
    """数据同步管理器"""
    
    def __init__(self, database_id):
        self.notion = Client(auth=NOTION_TOKEN)
        self.database_id = database_id
    
    def sync_from_api(self, api_url, mapping_config):
        """从外部 API 同步数据"""
        # 获取外部数据
        response = requests.get(api_url)
        external_data = response.json()
        
        # 获取 Notion 中的现有数据
        existing_pages = self._get_all_pages()
        existing_ids = {
            self._extract_external_id(page): page['id'] 
            for page in existing_pages
        }
        
        # 同步数据
        for item in external_data:
            external_id = str(item.get('id'))
            
            # 根据映射配置转换数据
            notion_properties = self._map_data(item, mapping_config)
            
            if external_id in existing_ids:
                # 更新现有页面
                self.notion.pages.update(
                    page_id=existing_ids[external_id],
                    properties=notion_properties
                )
                print(f"更新: {external_id}")
            else:
                # 创建新页面
                self.notion.pages.create(
                    parent={"database_id": self.database_id},
                    properties=notion_properties
                )
                print(f"创建: {external_id}")
    
    def _get_all_pages(self):
        """获取所有页面"""
        from notion_client.helpers import iterate_paginated_api
        
        all_pages = []
        for page in iterate_paginated_api(
            self.notion.databases.query,
            database_id=self.database_id
        ):
            all_pages.append(page)
        return all_pages
    
    def _extract_external_id(self, page):
        """提取外部 ID"""
        external_id_prop = page['properties'].get('External ID')
        if external_id_prop and external_id_prop['rich_text']:
            return external_id_prop['rich_text'][0]['text']['content']
        return None
    
    def _map_data(self, item, mapping_config):
        """映射数据"""
        properties = {}
        
        for notion_field, config in mapping_config.items():
            source_field = config['source']
            field_type = config['type']
            
            value = item.get(source_field)
            
            if field_type == 'title':
                properties[notion_field] = {
                    "title": [{"text": {"content": str(value)}}]
                }
            elif field_type == 'rich_text':
                properties[notion_field] = {
                    "rich_text": [{"text": {"content": str(value)}}]
                }
            elif field_type == 'number':
                properties[notion_field] = {
                    "number": float(value) if value else 0
                }
            elif field_type == 'select':
                properties[notion_field] = {
                    "select": {"name": str(value)}
                }
            elif field_type == 'date':
                properties[notion_field] = {
                    "date": {"start": str(value)}
                }
        
        return properties

# 使用示例
if __name__ == "__main__":
    # 配置映射
    mapping = {
        "Name": {"source": "name", "type": "title"},
        "External ID": {"source": "id", "type": "rich_text"},
        "Price": {"source": "price", "type": "number"},
        "Category": {"source": "category", "type": "select"},
        "Created": {"source": "created_at", "type": "date"}
    }
    
    sync_manager = DataSyncManager(database_id="your_database_id")
    sync_manager.sync_from_api(
        api_url="https://api.example.com/products",
        mapping_config=mapping
    )
```

### 8.4 自动化报告生成

```python
# report_generator.py
from notion_client import Client
from datetime import datetime, timedelta
from collections import Counter
from config import NOTION_TOKEN

class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, database_id):
        self.notion = Client(auth=NOTION_TOKEN)
        self.database_id = database_id
    
    def generate_weekly_report(self, report_page_id):
        """生成周报"""
        # 获取本周数据
        start_of_week = datetime.now() - timedelta(days=7)
        
        results = self.notion.databases.query(
            database_id=self.database_id,
            filter={
                "property": "Created",
                "date": {
                    "after": start_of_week.strftime("%Y-%m-%d")
                }
            }
        )
        
        pages = results['results']
        
        # 统计数据
        total_tasks = len(pages)
        completed_tasks = sum(
            1 for p in pages 
            if p['properties']['Status']['select']['name'] == 'Completed'
        )
        
        # 按优先级统计
        priorities = [
            p['properties']['Priority']['select']['name'] 
            for p in pages 
            if p['properties']['Priority']['select']
        ]
        priority_counts = Counter(priorities)
        
        # 生成报告内容
        report_blocks = [
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"text": {"content": "周报"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": f"报告日期: {datetime.now().strftime('%Y-%m-%d')}"}}
                    ]
                }
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "总体概况"}}]
                }
            },
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"text": {"content": f"总任务数: {total_tasks}"}}]
                }
            },
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"text": {"content": f"已完成: {completed_tasks}"}}]
                }
            },
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"text": {"content": f"完成率: {completed_tasks/total_tasks*100:.1f}%"}}
                    ]
                }
            } if total_tasks > 0 else None,
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "优先级分布"}}]
                }
            }
        ]
        
        # 添加优先级统计
        for priority, count in priority_counts.items():
            report_blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"text": {"content": f"{priority}: {count}"}}]
                }
            })
        
        # 移除 None 值
        report_blocks = [b for b in report_blocks if b is not None]
        
        # 添加到报告页面
        self.notion.blocks.children.append(
            block_id=report_page_id,
            children=report_blocks
        )
        
        print("周报生成成功!")

# 使用示例
if __name__ == "__main__":
    generator = ReportGenerator(database_id="your_database_id")
    generator.generate_weekly_report(report_page_id="your_report_page_id")
```

---

## 错误处理

### 9.1 错误类型

```python
from notion_client.errors import (
    APIResponseError,
    RequestTimeoutError,
    HTTPResponseError
)
import logging

logger = logging.getLogger(__name__)

def handle_notion_errors(func):
    """错误处理装饰器"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        
        except APIResponseError as e:
            # API 响应错误
            logger.error(f"API Error: {e.code} - {e.message}")
            if e.code == "unauthorized":
                logger.error("认证失败，请检查 Token")
            elif e.code == "object_not_found":
                logger.error("对象不存在，请检查 ID")
            elif e.code == "rate_limited":
                logger.warning("触发速率限制，请稍后重试")
            raise
        
        except RequestTimeoutError as e:
            # 请求超时
            logger.error(f"Request timeout: {e}")
            raise
        
        except HTTPResponseError as e:
            # HTTP 错误
            logger.error(f"HTTP Error: {e.status} - {e.message}")
            raise
        
        except Exception as e:
            # 其他错误
            logger.error(f"Unexpected error: {type(e).__name__} - {e}")
            raise
    
    return wrapper

# 使用示例
@handle_notion_errors
def safe_get_page(page_id):
    """安全地获取页面"""
    return notion.pages.retrieve(page_id)
```

### 9.2 重试机制

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from notion_client.errors import APIResponseError

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(APIResponseError)
)
def create_page_with_retry(database_id, properties):
    """带重试的页面创建"""
    return notion.pages.create(
        parent={"database_id": database_id},
        properties=properties
    )

# 自定义重试逻辑
import time

def retry_on_rate_limit(func, max_retries=3):
    """针对速率限制的重试"""
    def wrapper(*args, **kwargs):
        retries = 0
        while retries < max_retries:
            try:
                return func(*args, **kwargs)
            except APIResponseError as e:
                if e.code == "rate_limited":
                    wait_time = 2 ** retries  # 指数退避
                    logger.warning(f"速率限制，等待 {wait_time} 秒...")
                    time.sleep(wait_time)
                    retries += 1
                else:
                    raise
        raise Exception("超过最大重试次数")
    
    return wrapper
```

### 9.3 日志记录

```python
# logger.py
import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logger(name, log_file='notion.log', level=logging.INFO):
    """设置日志记录器"""
    # 创建 logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 创建格式器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 文件处理器
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

# 使用
logger = setup_logger('notion_app')

def log_operation(operation_name):
    """操作日志装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.info(f"开始执行: {operation_name}")
            try:
                result = func(*args, **kwargs)
                logger.info(f"成功完成: {operation_name}")
                return result
            except Exception as e:
                logger.error(f"执行失败: {operation_name} - {e}")
                raise
        return wrapper
    return decorator

# 使用示例
@log_operation("创建页面")
def create_page_logged(database_id, properties):
    return notion.pages.create(
        parent={"database_id": database_id},
        properties=properties
    )
```

---

## 性能优化

### 10.1 批量操作

```python
import asyncio
from notion_client import AsyncClient
from config import NOTION_TOKEN

async def batch_create_pages(database_id, pages_data):
    """批量创建页面（异步）"""
    async with AsyncClient(auth=NOTION_TOKEN) as client:
        tasks = [
            client.pages.create(
                parent={"database_id": database_id},
                properties=data
            )
            for data in pages_data
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

# 使用
async def main():
    pages_data = [
        {"Name": {"title": [{"text": {"content": f"Page {i}"}}]}}
        for i in range(10)
    ]
    
    results = await batch_create_pages("your_database_id", pages_data)
    print(f"创建了 {len(results)} 个页面")

# asyncio.run(main())
```

### 10.2 缓存策略

```python
from functools import lru_cache
from datetime import datetime, timedelta
import pickle
import os

class NotionCache:
    """Notion 缓存管理"""
    
    def __init__(self, cache_dir='cache', ttl=3600):
        self.cache_dir = cache_dir
        self.ttl = ttl  # 缓存过期时间（秒）
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_cache_path(self, key):
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{key}.pkl")
    
    def get(self, key):
        """获取缓存"""
        cache_path = self.get_cache_path(key)
        
        if not os.path.exists(cache_path):
            return None
        
        # 检查是否过期
        cache_time = os.path.getmtime(cache_path)
        if time.time() - cache_time > self.ttl:
            os.remove(cache_path)
            return None
        
        # 读取缓存
        with open(cache_path, 'rb') as f:
            return pickle.load(f)
    
    def set(self, key, value):
        """设置缓存"""
        cache_path = self.get_cache_path(key)
        with open(cache_path, 'wb') as f:
            pickle.dump(value, f)
    
    def clear(self, key=None):
        """清除缓存"""
        if key:
            cache_path = self.get_cache_path(key)
            if os.path.exists(cache_path):
                os.remove(cache_path)
        else:
            # 清除所有缓存
            for file in os.listdir(self.cache_dir):
                os.remove(os.path.join(self.cache_dir, file))

# 使用缓存
cache = NotionCache(ttl=3600)  # 1小时缓存

def get_database_cached(database_id):
    """带缓存的数据库获取"""
    cached = cache.get(f"db_{database_id}")
    if cached:
        logger.info("从缓存获取数据库")
        return cached
    
    logger.info("从 API 获取数据库")
    db = notion.databases.retrieve(database_id)
    cache.set(f"db_{database_id}", db)
    return db
```

### 10.3 连接池

```python
from queue import Queue
from threading import Lock

class NotionClientPool:
    """Notion 客户端连接池"""
    
    def __init__(self, token, pool_size=5):
        self.token = token
        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.lock = Lock()
        
        # 初始化连接池
        for _ in range(pool_size):
            self.pool.put(Client(auth=token))
    
    def get_client(self):
        """获取客户端"""
        return self.pool.get()
    
    def release_client(self, client):
        """释放客户端"""
        self.pool.put(client)
    
    def execute(self, func, *args, **kwargs):
        """执行操作"""
        client = self.get_client()
        try:
            # 将 client 作为第一个参数传递
            return func(client, *args, **kwargs)
        finally:
            self.release_client(client)

# 使用
pool = NotionClientPool(token=NOTION_TOKEN, pool_size=3)

def get_page_with_pool(client, page_id):
    """使用连接池获取页面"""
    return client.pages.retrieve(page_id)

# page = pool.execute(get_page_with_pool, "page_id")
```

### 10.4 请求优化

```python
import time
from collections import deque

class RateLimiter:
    """速率限制器"""
    
    def __init__(self, max_calls=3, time_window=1):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = deque()
    
    def __call__(self, func):
        def wrapper(*args, **kwargs):
            now = time.time()
            
            # 移除过期的调用记录
            while self.calls and self.calls[0] < now - self.time_window:
                self.calls.popleft()
            
            # 检查是否超过限制
            if len(self.calls) >= self.max_calls:
                sleep_time = self.time_window - (now - self.calls[0])
                if sleep_time > 0:
                    logger.warning(f"速率限制，等待 {sleep_time:.2f} 秒")
                    time.sleep(sleep_time)
                self.calls.popleft()
            
            # 记录调用
            self.calls.append(time.time())
            
            return func(*args, **kwargs)
        
        return wrapper

# 使用
@RateLimiter(max_calls=3, time_window=1)
def rate_limited_query(database_id):
    """受速率限制的查询"""
    return notion.databases.query(database_id=database_id)
```

---

## 完整示例项目

### 11.1 项目:个人知识管理系统

```python
# knowledge_management_system.py
"""
个人知识管理系统
功能:
- 创建和管理笔记
- 标签系统
- 全文搜索
- 自动备份
- 统计分析
"""

from notion_client import Client
from datetime import datetime
import json
import os
from config import NOTION_TOKEN

class KnowledgeManagementSystem:
    """知识管理系统"""
    
    def __init__(self, notes_db_id, tags_db_id=None):
        self.notion = Client(auth=NOTION_TOKEN)
        self.notes_db = notes_db_id
        self.tags_db = tags_db_id
    
    # === 笔记管理 ===
    
    def create_note(self, title, content, tags=None, category="General"):
        """创建笔记"""
        properties = {
            "Title": {
                "title": [{"text": {"content": title}}]
            },
            "Category": {
                "select": {"name": category}
            },
            "Created": {
                "date": {"start": datetime.now().isoformat()}
            }
        }
        
        if tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in tags]
            }
        
        # 创建页面
        page = self.notion.pages.create(
            parent={"database_id": self.notes_db},
            properties=properties
        )
        
        # 添加内容
        if content:
            blocks = self._parse_content_to_blocks(content)
            self.notion.blocks.children.append(
                block_id=page['id'],
                children=blocks
            )
        
        print(f"✅ 笔记创建成功: {title}")
        return page
    
    def _parse_content_to_blocks(self, content):
        """解析内容为块"""
        blocks = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 标题
            if line.startswith('# '):
                blocks.append({
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"text": {"content": line[2:]}}]
                    }
                })
            elif line.startswith('## '):
                blocks.append({
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": line[3:]}}]
                    }
                })
            elif line.startswith('### '):
                blocks.append({
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"text": {"content": line[4:]}}]
                    }
                })
            # 列表
            elif line.startswith('- '):
                blocks.append({
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"text": {"content": line[2:]}}]
                    }
                })
            # 段落
            else:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": line}}]
                    }
                })
        
        return blocks
    
    def get_note(self, note_id):
        """获取笔记详情"""
        page = self.notion.pages.retrieve(note_id)
        blocks = self.notion.blocks.children.list(note_id)['results']
        
        return {
            "page": page,
            "content": blocks
        }
    
    def search_notes(self, query):
        """搜索笔记"""
        results = self.notion.search(
            query=query,
            filter={"property": "object", "value": "page"}
        )
        return results['results']
    
    def get_notes_by_tag(self, tag):
        """按标签获取笔记"""
        results = self.notion.databases.query(
            database_id=self.notes_db,
            filter={
                "property": "Tags",
                "multi_select": {"contains": tag}
            }
        )
        return results['results']
    
    # === 统计分析 ===
    
    def get_statistics(self):
        """获取统计信息"""
        # 获取所有笔记
        all_notes = []
        results = self.notion.databases.query(database_id=self.notes_db)
        all_notes.extend(results['results'])
        
        while results['has_more']:
            results = self.notion.databases.query(
                database_id=self.notes_db,
                start_cursor=results['next_cursor']
            )
            all_notes.extend(results['results'])
        
        # 统计
        total_notes = len(all_notes)
        
        # 按类别统计
        categories = {}
        tags_count = {}
        
        for note in all_notes:
            # 类别
            category_prop = note['properties'].get('Category')
            if category_prop and category_prop.get('select'):
                cat = category_prop['select']['name']
                categories[cat] = categories.get(cat, 0) + 1
            
            # 标签
            tags_prop = note['properties'].get('Tags')
            if tags_prop and tags_prop.get('multi_select'):
                for tag in tags_prop['multi_select']:
                    tag_name = tag['name']
                    tags_count[tag_name] = tags_count.get(tag_name, 0) + 1
        
        return {
            "total_notes": total_notes,
            "categories": categories,
            "tags": tags_count,
            "top_tags": sorted(tags_count.items(), key=lambda x: x[1], reverse=True)[:10]
        }
    
    def print_statistics(self):
        """打印统计信息"""
        stats = self.get_statistics()
        
        print("\n📊 知识库统计")
        print("=" * 50)
        print(f"📝 总笔记数: {stats['total_notes']}")
        
        print("\n📁 按类别分布:")
        for category, count in stats['categories'].items():
            print(f"  - {category}: {count}")
        
        print("\n🏷️  热门标签 (Top 10):")
        for tag, count in stats['top_tags']:
            print(f"  - {tag}: {count}")
        print("=" * 50)
    
    # === 备份功能 ===
    
    def backup_to_json(self, backup_dir='backups'):
        """备份到 JSON"""
        os.makedirs(backup_dir, exist_ok=True)
        
        # 获取所有笔记
        all_notes = []
        results = self.notion.databases.query(database_id=self.notes_db)
        all_notes.extend(results['results'])
        
        while results['has_more']:
            results = self.notion.databases.query(
                database_id=self.notes_db,
                start_cursor=results['next_cursor']
            )
            all_notes.extend(results['results'])
        
        # 保存
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"notion_backup_{timestamp}.json"
        filepath = os.path.join(backup_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(all_notes, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 备份完成: {filepath}")
        return filepath

# === 主程序 ===

def main():
    """主程序"""
    # 初始化系统
    kms = KnowledgeManagementSystem(
        notes_db_id="your_notes_database_id"
    )
    
    # 创建示例笔记
    content = """# Python 学习笔记

## 基础概念
Python 是一种高级编程语言。

## 关键特性
- 简洁易读
- 丰富的库
- 跨平台

### 应用领域
数据科学、Web开发、自动化等"""
    
    note = kms.create_note(
        title="Python 基础",
        content=content,
        tags=["编程", "Python", "学习"],
        category="技术"
    )
    
    # 搜索笔记
    results = kms.search_notes("Python")
    print(f"\n🔍 搜索到 {len(results)} 条结果")
    
    # 显示统计
    kms.print_statistics()
    
    # 备份
    kms.backup_to_json()

if __name__ == "__main__":
    main()
```

### 11.2 配置文件示例

```python
# config.py (完整版)
import os
from dotenv import load_dotenv
import logging

# 加载环境变量
load_dotenv()

# Notion API 配置
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")

# 数据库 ID
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
PAGE_ID = os.getenv("NOTION_PAGE_ID")
NOTES_DATABASE_ID = os.getenv("NOTES_DATABASE_ID")
TASKS_DATABASE_ID = os.getenv("TASKS_DATABASE_ID")

# 应用配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# 验证必要配置
def validate_config():
    """验证配置"""
    if not NOTION_TOKEN:
        raise ValueError("❌ NOTION_TOKEN 未设置")
    
    print("✅ 配置验证通过")
    return True

# 日志配置
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

---

## 📚 附录

### A. 常用工具函数

```python
# utils.py
from datetime import datetime, timedelta

def format_date(date_str):
    """格式化日期"""
    if not date_str:
        return None
    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))

def get_next_week():
    """获取下周日期"""
    return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

def extract_plain_text(rich_text_array):
    """提取纯文本"""
    if not rich_text_array:
        return ""
    return ''.join([rt['text']['content'] for rt in rich_text_array])

def create_rich_text_array(text, **annotations):
    """创建富文本数组"""
    return [
        {
            "text": {"content": text},
            "annotations": annotations
        }
    ]

def paginate_results(query_func, **kwargs):
    """分页获取所有结果"""
    results = []
    has_more = True
    start_cursor = None
    
    while has_more:
        kwargs['start_cursor'] = start_cursor
        response = query_func(**kwargs)
        results.extend(response['results'])
        has_more = response['has_more']
        start_cursor = response.get('next_cursor')
    
    return results
```

### B. 测试示例

```python
# test_notion.py
import unittest
from unittest.mock import Mock, patch
from notion_client import Client

class TestNotionAPI(unittest.TestCase):
    """Notion API 测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.mock_client = Mock(spec=Client)
    
    def test_create_page(self):
        """测试创建页面"""
        # 模拟返回值
        self.mock_client.pages.create.return_value = {
            'id': 'test-page-id',
            'properties': {}
        }
        
        # 调用
        result = self.mock_client.pages.create(
            parent={"database_id": "test-db-id"},
            properties={"title": {}}
        )
        
        # 断言
        self.assertEqual(result['id'], 'test-page-id')
        self.mock_client.pages.create.assert_called_once()
    
    def test_query_database(self):
        """测试查询数据库"""
        self.mock_client.databases.query.return_value = {
            'results': [{'id': '1'}, {'id': '2'}],
            'has_more': False
        }
        
        result = self.mock_client.databases.query(
            database_id="test-db-id"
        )
        
        self.assertEqual(len(result['results']), 2)

if __name__ == '__main__':
    unittest.main()
```

### C. 参考资源

**官方文档**
- API 文档: https://developers.notion.com/
- Python SDK: https://github.com/ramnes/notion-sdk-py
- JavaScript SDK: https://github.com/makenotion/notion-sdk-js

**社区资源**
- Stack Overflow: https://stackoverflow.com/questions/tagged/notion-api
- Notion Devs Slack: https://join.slack.com/t/notiondevs/

**工具推荐**
- Postman Collection: 测试 API 请求
- VSCode Notion Extension: 代码提示
- Notion Helper: 简化 API 调用

---

**文档版本**: 1.0  
**最后更新**: 2024-12-26  
**作者**: AI 助手
