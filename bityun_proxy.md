# Python Proxy 使用指南

## 🎯 实现思路总览

### 架构设计
```
┌─────────────────┐
│   应用程序      │ (浏览器/curl等)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  本地代理服务器  │ (127.0.0.1:7890)
│  HTTP/SOCKS5    │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  节点选择器     │ (智能选择/测速)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ SS客户端        │ (加密/解密)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ SS服务器        │ (香港/日本/美国等)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  目标网站       │ (Google/YouTube等)
└─────────────────┘
```

---

## 📦 依赖安装

### 方式1: 使用pip
```bash
pip install pyyaml requests cryptography aiohttp
```

### 方式2: 使用requirements.txt
```bash
# requirements.txt
pyyaml>=6.0
requests>=2.31.0
cryptography>=41.0.0
aiohttp>=3.9.0

# 安装
pip install -r requirements.txt
```

### 方式3: 使用现成的SS客户端库
```bash
# 使用shadowsocks包（更简单）
pip install shadowsocks

# 或者使用aioshadowsocks（异步版本）
pip install aioshadowsocks
```

---

## 🚀 快速开始

### 1. 基础使用（解析配置）
```python
from clash_parser import ClashConfigParser

# 从文件加载
config = ClashConfigParser.parse_yaml_file("config.yaml")

# 查看所有节点
for node in config.nodes:
    print(f"{node.name}: {node.server}:{node.port}")

# 获取香港节点
hk_nodes = config.get_nodes_by_region("香港")
print(f"找到 {len(hk_nodes)} 个香港节点")
```

### 2. 测速选择最快节点
```python
import asyncio
from node_tester import NodeTester
from node_selector import NodeSelector

async def test_and_select():
    # 加载配置
    config = ClashConfigParser.parse_yaml_file("config.yaml")
    
    # 测试所有节点
    await NodeTester.test_all_nodes(config.nodes)
    
    # 选择最快的
    selector = NodeSelector(config)
    fastest = selector.select_fastest()
    
    print(f"最快节点: {fastest.name} - {fastest.latency:.0f}ms")
    return fastest

# 运行
asyncio.run(test_and_select())
```

### 3. 直接使用节点连接
```python
from shadowsocks_client import ShadowsocksClient

async def connect_google():
    # 创建SS客户端
    node = config.get_node_by_name("🇭🇰 香港 01 解锁线路")
    ss_client = ShadowsocksClient(node)
    
    # 连接到Google
    reader, writer = await ss_client.connect("www.google.com", 443)
    
    # 发送HTTP请求
    writer.write(b"GET / HTTP/1.1\r\nHost: www.google.com\r\n\r\n")
    await writer.drain()
    
    # 读取响应
    response = await reader.read(1024)
    print(response.decode())
    
    writer.close()

asyncio.run(connect_google())
```

### 4. 启动本地代理服务器
```python
from local_proxy_server import LocalProxyServer

async def start_proxy():
    config = ClashConfigParser.parse_yaml_file("config.yaml")
    
    # 先测速
    await NodeTester.test_all_nodes(config.nodes)
    
    # 启动代理服务器
    server = LocalProxyServer(config, listen_port=7890)
    await server.start()

asyncio.run(start_proxy())
```

---

## 🛠️ 实用工具脚本

### 工具1: 节点监控脚本
```python
#!/usr/bin/env python3
"""节点监控和自动切换"""

import asyncio
import time
from datetime import datetime

class NodeMonitor:
    def __init__(self, config, check_interval=300):
        self.config = config
        self.check_interval = check_interval
        self.selector = NodeSelector(config)
    
    async def monitor(self):
        """持续监控节点状态"""
        while True:
            print(f"\n[{datetime.now()}] 开始检测...")
            
            # 测速
            await NodeTester.test_all_nodes(self.config.nodes)
            
            # 选择最快节点
            fastest = self.selector.select_fastest()
            
            # 显示前5名
            available = self.selector.get_available_nodes()[:5]
            print("\n🏆 Top 5 节点:")
            for i, node in enumerate(available, 1):
                print(f"  {i}. {node.name:40s} {node.latency:6.0f}ms")
            
            # 等待下次检测
            await asyncio.sleep(self.check_interval)

# 使用
config = ClashConfigParser.parse_yaml_file("config.yaml")
monitor = NodeMonitor(config, check_interval=300)  # 5分钟检测一次
asyncio.run(monitor.monitor())
```

### 工具2: 批量测试工具
```python
#!/usr/bin/env python3
"""批量测试所有节点并生成报告"""

import json
from collections import defaultdict

async def generate_report():
    config = ClashConfigParser.parse_yaml_file("config.yaml")
    
    # 测速
    await NodeTester.test_all_nodes(config.nodes)
    
    # 按地区分组统计
    region_stats = defaultdict(list)
    for node in config.nodes:
        # 提取地区
        for region in ['香港', '日本', '台湾', '美国', '韩国', '新加坡']:
            if region in node.name:
                region_stats[region].append({
                    'name': node.name,
                    'latency': node.latency,
                    'server': node.server,
                    'port': node.port
                })
                break
    
    # 生成报告
    report = {
        'test_time': datetime.now().isoformat(),
        'total_nodes': len(config.nodes),
        'regions': {}
    }
    
    for region, nodes in region_stats.items():
        available = [n for n in nodes if n['latency'] < float('inf')]
        avg_latency = sum(n['latency'] for n in available) / len(available) if available else 0
        
        report['regions'][region] = {
            'total': len(nodes),
            'available': len(available),
            'avg_latency': f"{avg_latency:.2f}ms",
            'fastest': min(nodes, key=lambda x: x['latency'])
        }
    
    # 保存报告
    with open('node_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print("✅ 报告已保存到 node_report.json")
    return report

asyncio.run(generate_report())
```

### 工具3: 订阅更新器
```python
#!/usr/bin/env python3
"""自动更新订阅配置"""

import os
import shutil
from datetime import datetime

class SubscriptionUpdater:
    def __init__(self, sub_url, config_file="config.yaml"):
        self.sub_url = sub_url
        self.config_file = config_file
    
    def update(self, backup=True):
        """更新订阅"""
        try:
            # 备份旧配置
            if backup and os.path.exists(self.config_file):
                backup_file = f"{self.config_file}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
                shutil.copy(self.config_file, backup_file)
                print(f"✅ 已备份到: {backup_file}")
            
            # 下载新配置
            print(f"📥 下载订阅...")
            config = ClashConfigParser.download_subscription(self.sub_url)
            
            # 保存
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump({
                    'proxies': [vars(n) for n in config.nodes],
                    'rules': config.rules,
                    'dns': config.dns_config,
                    'proxy-groups': config.proxy_groups
                }, f, allow_unicode=True)
            
            print(f"✅ 配置已更新: {len(config.nodes)} 个节点")
            
        except Exception as e:
            print(f"❌ 更新失败: {e}")

# 使用
updater = SubscriptionUpdater(
    sub_url="https://times1766152644.subxiandan.top:9604/v2b/bityun/api/v1/client/subscribe?token=YOUR_TOKEN"
)
updater.update()
```

---

## 🔧 高级配置

### 配置1: 自定义规则匹配
```python
class RuleMatcher:
    """规则匹配器"""
    
    def __init__(self, rules):
        self.rules = rules
    
    def match(self, host: str) -> str:
        """匹配规则，返回动作（DIRECT/PROXY/REJECT）"""
        for rule in self.rules:
            rule_type, pattern, action = self._parse_rule(rule)
            
            if rule_type == "DOMAIN-SUFFIX":
                if host.endswith(pattern):
                    return action
            elif rule_type == "DOMAIN-KEYWORD":
                if pattern in host:
                    return action
            elif rule_type == "DOMAIN":
                if host == pattern:
                    return action
        
        return "DIRECT"  # 默认直连
    
    def _parse_rule(self, rule: str):
        """解析规则字符串"""
        parts = rule.split(',')
        return parts[0], parts[1], parts[2] if len(parts) > 2 else "DIRECT"

# 使用
matcher = RuleMatcher(config.rules)
action = matcher.match("www.google.com")
print(f"www.google.com -> {action}")
```

### 配置2: 智能DNS解析
```python
import socket

class SmartDNS:
    """智能DNS解析器"""
    
    def __init__(self, dns_config):
        self.nameservers = dns_config.get('nameserver', [])
        self.fallback = dns_config.get('fallback', [])
    
    async def resolve(self, host: str) -> str:
        """解析域名"""
        try:
            # 优先使用系统DNS
            ip = socket.gethostbyname(host)
            return ip
        except:
            # 使用DoH
            return await self._resolve_doh(host)
    
    async def _resolve_doh(self, host: str) -> str:
        """使用DoH解析"""
        # 实现DoH查询
        pass
```

### 配置3: 流量统计
```python
class TrafficStats:
    """流量统计"""
    
    def __init__(self):
        self.stats = defaultdict(lambda: {'upload': 0, 'download': 0})
    
    def record(self, node_name: str, upload: int, download: int):
        """记录流量"""
        self.stats[node_name]['upload'] += upload
        self.stats[node_name]['download'] += download
    
    def get_total(self):
        """获取总流量"""
        total_up = sum(s['upload'] for s in self.stats.values())
        total_down = sum(s['download'] for s in self.stats.values())
        return total_up, total_down
    
    def format_bytes(self, bytes: int) -> str:
        """格式化字节"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes < 1024:
                return f"{bytes:.2f} {unit}"
            bytes /= 1024
```

---

## 🐛 常见问题

### Q1: ImportError: No module named 'shadowsocks'
**解决方案:**
```bash
pip install shadowsocks
# 或使用我们自己实现的ShadowsocksClient类
```

### Q2: 连接超时
**可能原因:**
1. 节点失效 → 使用测速工具检测
2. 网络问题 → 检查本地网络
3. 防火墙拦截 → 关闭防火墙或添加规则

### Q3: 加密方法不支持
**解决方案:**
```python
# 添加新的加密方法支持
METHOD_SUPPORTED = {
    'aes-128-gcm': (16, 16),
    'aes-256-gcm': (32, 32),
    'chacha20-ietf-poly1305': (32, 32),
    # 添加更多...
}
```

### Q4: DNS解析失败
**解决方案:**
```python
# 使用DoH
dns_config = {
    'nameserver': ['https://dns.google/dns-query']
}
```

---

## 📊 性能优化

### 1. 连接池
```python
from asyncio import Queue

class ConnectionPool:
    def __init__(self, size=10):
        self.pool = Queue(maxsize=size)
    
    async def get_connection(self):
        """获取连接"""
        return await self.pool.get()
    
    async def return_connection(self, conn):
        """归还连接"""
        await self.pool.put(conn)
```

### 2. 缓存DNS
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def resolve_cached(host: str) -> str:
    return socket.gethostbyname(host)
```

### 3. 异步并发
```python
async def parallel_requests(urls):
    tasks = [fetch_url(url) for url in urls]
    return await asyncio.gather(*tasks)
```

---

## 🔒 安全建议

1. **保护敏感信息**
   - 不要提交包含token/密码的配置文件
   - 使用环境变量存储敏感数据

2. **加密本地数据**
   ```python
   from cryptography.fernet import Fernet
   
   key = Fernet.generate_key()
   cipher = Fernet(key)
   encrypted = cipher.encrypt(password.encode())
   ```

3. **定期更新**
   - 定期更新订阅配置
   - 定期测试节点可用性

---

## 📝 完整示例

```python
#!/usr/bin/env python3
"""完整的代理使用示例"""

import asyncio
import sys

async def main():
    # 1. 加载配置
    config = ClashConfigParser.parse_yaml_file("config.yaml")
    print(f"✅ 加载 {len(config.nodes)} 个节点")
    
    # 2. 测速
    print("\n🔍 测试节点延迟...")
    await NodeTester.test_all_nodes(config.nodes)
    
    # 3. 选择节点
    selector = NodeSelector(config)
    
    # 显示香港节点
    hk_nodes = config.get_nodes_by_region("香港")
    print(f"\n🇭🇰 香港节点 ({len(hk_nodes)}):")
    for node in sorted(hk_nodes, key=lambda n: n.latency)[:5]:
        print(f"  {node.name:40s} {node.latency:6.0f}ms")
    
    # 自动选择最快的
    fastest = selector.select_fastest()
    print(f"\n🚀 选择: {fastest.name}")
    
    # 4. 测试连接
    print(f"\n🔗 测试连接...")
    ss = ShadowsocksClient(fastest)
    try:
        reader, writer = await ss.connect("www.google.com", 443)
        print("✅ 连接成功！")
        writer.close()
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        sys.exit(1)
    
    # 5. 启动代理服务器
    print(f"\n🌐 启动代理服务器...")
    server = LocalProxyServer(config, listen_port=7890)
    await server.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 退出")
```

---

## 🌟 推荐库

| 库名 | 用途 | 安装 |
|------|------|------|
| `pysocks` | SOCKS代理 | `pip install pysocks` |
| `httpx` | 异步HTTP客户端 | `pip install httpx` |
| `uvloop` | 高性能事件循环 | `pip install uvloop` |
| `dnspython` | DNS查询 | `pip install dnspython` |

---

## 📚 参考资源

- [Shadowsocks协议文档](https://shadowsocks.org/en/spec/Protocol.html)
- [Clash配置文档](https://github.com/Dreamacro/clash/wiki/configuration)
- [Python asyncio文档](https://docs.python.org/3/library/asyncio.html)