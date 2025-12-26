"""
proxy_manager.py - 代理管理模块

整合Clash配置解析、节点测速、智能选择功能。
为aiohttp提供SOCKS5/HTTP代理连接器。

Features:
- 解析Clash YAML配置文件或订阅URL
- 异步测试节点延迟
- 智能选择最快节点
- 自动故障转移和节点轮换
- 支持aiohttp-socks集成
"""

import os
import re
import yaml
import socket
import asyncio
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import aiohttp
from loguru import logger

# 可选依赖：aiohttp-socks
try:
    from aiohttp_socks import ProxyConnector, ProxyType
    HAS_AIOHTTP_SOCKS = True
except ImportError:
    HAS_AIOHTTP_SOCKS = False
    logger.warning("aiohttp-socks 未安装，将使用HTTP代理模式")


class ProxyProtocol(str, Enum):
    """代理协议类型"""
    SS = "ss"           # Shadowsocks
    SSR = "ssr"         # ShadowsocksR
    VMESS = "vmess"     # VMess
    TROJAN = "trojan"   # Trojan
    HTTP = "http"       # HTTP代理
    SOCKS5 = "socks5"   # SOCKS5代理
    DIRECT = "direct"   # 直连


@dataclass
class ProxyNode:
    """代理节点配置"""
    name: str
    server: str
    port: int
    password: str = ""
    cipher: str = ""
    protocol: ProxyProtocol = ProxyProtocol.SS
    udp: bool = True
    
    # 运行时状态
    latency: float = float('inf')
    is_available: bool = False
    last_test_time: float = 0
    fail_count: int = 0
    
    def __repr__(self):
        status = "✓" if self.is_available else "✗"
        lat = f"{self.latency:.0f}ms" if self.latency < float('inf') else "N/A"
        return f"<ProxyNode [{status}] {self.name} - {self.server}:{self.port} ({lat})>"
    
    @property
    def proxy_url(self) -> str:
        """生成代理URL（用于HTTP代理模式）"""
        if self.protocol == ProxyProtocol.HTTP:
            return f"http://{self.server}:{self.port}"
        elif self.protocol == ProxyProtocol.SOCKS5:
            return f"socks5://{self.server}:{self.port}"
        else:
            # SS/SSR等需要通过本地代理转发
            return ""


@dataclass
class ProxyConfig:
    """完整代理配置"""
    nodes: List[ProxyNode] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    dns_config: Dict = field(default_factory=dict)
    proxy_groups: List[Dict] = field(default_factory=list)
    
    # 本地代理服务器配置（Clash运行时）
    local_http_port: int = 7890
    local_socks_port: int = 7891
    local_host: str = "127.0.0.1"
    
    def get_node_by_name(self, name: str) -> Optional[ProxyNode]:
        """通过名称获取节点"""
        for node in self.nodes:
            if node.name == name:
                return node
        return None
    
    def get_nodes_by_region(self, region: str) -> List[ProxyNode]:
        """获取指定地区的节点（支持正则）"""
        pattern = re.compile(region, re.IGNORECASE)
        return [n for n in self.nodes if pattern.search(n.name)]
    
    def get_available_nodes(self, max_latency: float = 1000) -> List[ProxyNode]:
        """获取可用节点"""
        return [
            n for n in self.nodes 
            if n.is_available and n.latency < max_latency
        ]
    
    @property
    def local_http_proxy(self) -> str:
        """本地HTTP代理地址"""
        return f"http://{self.local_host}:{self.local_http_port}"
    
    @property
    def local_socks_proxy(self) -> str:
        """本地SOCKS5代理地址"""
        return f"socks5://{self.local_host}:{self.local_socks_port}"


class ClashConfigParser:
    """
    Clash配置文件解析器
    
    支持:
    - 本地YAML文件
    - 订阅URL（支持base64编码）
    - 自动检测节点类型
    """
    
    SUPPORTED_TYPES = {"ss", "ssr", "vmess", "trojan", "http", "socks5"}
    
    @classmethod
    def parse_yaml_file(cls, file_path: str) -> ProxyConfig:
        """解析本地YAML配置文件"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {file_path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls._parse_dict(data)
    
    @classmethod
    async def download_subscription(
        cls, 
        url: str, 
        timeout: int = 30
    ) -> ProxyConfig:
        """
        从订阅URL下载配置
        
        Args:
            url: 订阅URL
            timeout: 超时时间
        """
        import base64
        
        logger.info(f"📥 下载订阅配置: {url[:50]}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout) as response:
                    response.raise_for_status()
                    content = await response.text()
            
            # 尝试base64解码
            try:
                decoded = base64.b64decode(content).decode('utf-8')
                content = decoded
                logger.debug("订阅内容为base64编码，已解码")
            except Exception:
                pass  # 非base64，使用原始内容
            
            data = yaml.safe_load(content)
            config = cls._parse_dict(data)
            logger.info(f"✅ 订阅解析完成: {len(config.nodes)} 个节点")
            return config
            
        except Exception as e:
            logger.error(f"❌ 下载订阅失败: {e}")
            raise
    
    @classmethod
    def _parse_dict(cls, data: Dict) -> ProxyConfig:
        """解析配置字典"""
        nodes = []
        
        for proxy in data.get('proxies', []):
            node = cls._parse_proxy(proxy)
            if node:
                nodes.append(node)
        
        config = ProxyConfig(
            nodes=nodes,
            rules=data.get('rules', []),
            dns_config=data.get('dns', {}),
            proxy_groups=data.get('proxy-groups', []),
        )
        
        # 解析端口配置
        if 'port' in data:
            config.local_http_port = data['port']
        if 'socks-port' in data:
            config.local_socks_port = data['socks-port']
        if 'mixed-port' in data:
            config.local_http_port = data['mixed-port']
            config.local_socks_port = data['mixed-port']
        
        logger.info(f"✅ 配置解析完成: {len(nodes)} 个节点")
        return config
    
    @classmethod
    def _parse_proxy(cls, proxy: Dict) -> Optional[ProxyNode]:
        """解析单个代理节点"""
        proxy_type = proxy.get('type', '').lower()
        
        if proxy_type not in cls.SUPPORTED_TYPES:
            return None
        
        try:
            return ProxyNode(
                name=proxy['name'],
                server=proxy['server'],
                port=int(proxy['port']),
                password=proxy.get('password', ''),
                cipher=proxy.get('cipher', ''),
                protocol=ProxyProtocol(proxy_type),
                udp=proxy.get('udp', True),
            )
        except (KeyError, ValueError) as e:
            logger.debug(f"解析节点失败: {e}")
            return None


class NodeTester:
    """
    节点延迟测试器
    
    支持:
    - TCP连接测试
    - HTTP请求测试
    - 并发批量测试
    """
    
    # 测试目标URL列表
    TEST_URLS = [
        "http://www.gstatic.com/generate_204",
        "http://cp.cloudflare.com/generate_204",
        "http://connectivitycheck.gstatic.com/generate_204",
    ]
    
    @staticmethod
    async def test_tcp_latency(
        node: ProxyNode, 
        timeout: float = 5.0
    ) -> float:
        """
        测试TCP连接延迟
        
        直接测试到代理服务器的TCP连接时间。
        """
        try:
            start = time.time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(node.server, node.port),
                timeout=timeout
            )
            latency = (time.time() - start) * 1000
            
            writer.close()
            await writer.wait_closed()
            
            node.latency = latency
            node.is_available = True
            node.last_test_time = time.time()
            
            return latency
            
        except asyncio.TimeoutError:
            node.latency = float('inf')
            node.is_available = False
            node.fail_count += 1
            return float('inf')
            
        except Exception as e:
            logger.debug(f"TCP测试失败 {node.name}: {e}")
            node.latency = float('inf')
            node.is_available = False
            node.fail_count += 1
            return float('inf')
    
    @staticmethod
    async def test_http_latency(
        proxy_url: str,
        test_url: str = None,
        timeout: float = 10.0
    ) -> float:
        """
        通过代理测试HTTP延迟
        
        Args:
            proxy_url: 代理URL (http://host:port 或 socks5://host:port)
            test_url: 测试目标URL
            timeout: 超时时间
        """
        test_url = test_url or NodeTester.TEST_URLS[0]
        
        try:
            connector = None
            
            if proxy_url.startswith('socks'):
                if HAS_AIOHTTP_SOCKS:
                    connector = ProxyConnector.from_url(proxy_url)
                else:
                    logger.warning("SOCKS代理需要aiohttp-socks库")
                    return float('inf')
            
            start = time.time()
            
            async with aiohttp.ClientSession(connector=connector) as session:
                proxy = proxy_url if proxy_url.startswith('http') else None
                async with session.get(
                    test_url, 
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status in (200, 204):
                        return (time.time() - start) * 1000
            
            return float('inf')
            
        except Exception as e:
            logger.debug(f"HTTP测试失败: {e}")
            return float('inf')
    
    @classmethod
    async def test_all_nodes(
        cls,
        nodes: List[ProxyNode],
        concurrency: int = 20,
        timeout: float = 5.0
    ) -> List[ProxyNode]:
        """
        批量测试所有节点
        
        Args:
            nodes: 节点列表
            concurrency: 并发数
            timeout: 单个测试超时
        """
        logger.info(f"🔍 开始测试 {len(nodes)} 个节点 (并发: {concurrency})...")
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def bounded_test(node: ProxyNode):
            async with semaphore:
                latency = await cls.test_tcp_latency(node, timeout)
                status = "✓" if node.is_available else "✗"
                lat_str = f"{latency:.0f}ms" if latency < float('inf') else "超时"
                logger.debug(f"  [{status}] {node.name}: {lat_str}")
                return node
        
        tasks = [bounded_test(node) for node in nodes]
        await asyncio.gather(*tasks)
        
        # 按延迟排序
        nodes.sort(key=lambda n: (not n.is_available, n.latency))
        
        available = sum(1 for n in nodes if n.is_available)
        logger.info(f"✅ 测试完成: {available}/{len(nodes)} 个节点可用")
        
        return nodes


class ProxyManager:
    """
    代理管理器
    
    整合配置加载、节点测试、智能选择功能。
    提供aiohttp连接器和会话工厂。
    
    Usage:
        manager = ProxyManager()
        await manager.load_config("config.yaml")
        await manager.test_nodes()
        
        # 获取带代理的aiohttp会话
        async with manager.create_session() as session:
            async with session.get("https://example.com") as resp:
                ...
    """
    
    def __init__(
        self,
        prefer_local_proxy: bool = True,
        local_http_port: int = 7890,
        local_socks_port: int = 7891,
        auto_rotate: bool = True,
        max_fail_count: int = 3,
    ):
        """
        Args:
            prefer_local_proxy: 优先使用本地代理（假设Clash已运行）
            local_http_port: 本地HTTP代理端口
            local_socks_port: 本地SOCKS5代理端口
            auto_rotate: 失败时自动切换节点
            max_fail_count: 最大失败次数后切换节点
        """
        self.config: Optional[ProxyConfig] = None
        self.current_node: Optional[ProxyNode] = None
        
        self.prefer_local_proxy = prefer_local_proxy
        self.local_http_port = local_http_port
        self.local_socks_port = local_socks_port
        self.auto_rotate = auto_rotate
        self.max_fail_count = max_fail_count
        
        self._node_index = 0
        self._local_proxy_available = False
    
    async def load_config(
        self, 
        source: str,
        is_subscription: bool = False
    ) -> ProxyConfig:
        """
        加载代理配置
        
        Args:
            source: 配置文件路径或订阅URL
            is_subscription: 是否为订阅URL
        """
        if is_subscription or source.startswith(('http://', 'https://')):
            self.config = await ClashConfigParser.download_subscription(source)
        else:
            self.config = ClashConfigParser.parse_yaml_file(source)
        
        # 更新本地代理端口
        self.local_http_port = self.config.local_http_port
        self.local_socks_port = self.config.local_socks_port
        
        return self.config
    
    async def test_nodes(
        self, 
        concurrency: int = 20,
        timeout: float = 5.0
    ) -> List[ProxyNode]:
        """测试所有节点"""
        if not self.config:
            raise RuntimeError("请先加载配置")
        
        await NodeTester.test_all_nodes(
            self.config.nodes, 
            concurrency=concurrency,
            timeout=timeout
        )
        
        return self.config.nodes
    
    async def check_local_proxy(self) -> bool:
        """检查本地代理是否可用"""
        proxy_url = f"http://127.0.0.1:{self.local_http_port}"
        
        try:
            latency = await NodeTester.test_http_latency(proxy_url, timeout=5.0)
            self._local_proxy_available = latency < float('inf')
            
            if self._local_proxy_available:
                logger.info(f"✅ 本地代理可用: {proxy_url} ({latency:.0f}ms)")
            else:
                logger.warning(f"⚠️ 本地代理不可用: {proxy_url}")
            
            return self._local_proxy_available
            
        except Exception as e:
            logger.warning(f"检查本地代理失败: {e}")
            self._local_proxy_available = False
            return False
    
    def select_fastest(self, region: Optional[str] = None) -> ProxyNode:
        """选择最快的节点"""
        if not self.config:
            raise RuntimeError("请先加载配置")
        
        nodes = self.config.nodes
        if region:
            nodes = self.config.get_nodes_by_region(region)
        
        available = [n for n in nodes if n.is_available]
        if not available:
            raise RuntimeError("没有可用的代理节点")
        
        self.current_node = min(available, key=lambda n: n.latency)
        self._node_index = self.config.nodes.index(self.current_node)
        
        logger.info(f"🚀 选择节点: {self.current_node.name} ({self.current_node.latency:.0f}ms)")
        return self.current_node
    
    def select_by_name(self, name: str) -> ProxyNode:
        """通过名称选择节点"""
        if not self.config:
            raise RuntimeError("请先加载配置")
        
        node = self.config.get_node_by_name(name)
        if not node:
            raise ValueError(f"未找到节点: {name}")
        
        self.current_node = node
        self._node_index = self.config.nodes.index(node)
        return node
    
    def rotate_node(self) -> Optional[ProxyNode]:
        """切换到下一个可用节点"""
        if not self.config:
            return None
        
        available = self.config.get_available_nodes()
        if not available:
            return None
        
        self._node_index = (self._node_index + 1) % len(available)
        self.current_node = available[self._node_index]
        
        logger.info(f"🔄 切换节点: {self.current_node.name}")
        return self.current_node
    
    def get_proxy_url(self, prefer_socks: bool = True) -> Optional[str]:
        """
        获取当前代理URL
        
        Args:
            prefer_socks: 优先使用SOCKS5代理
        """
        # 优先使用本地代理
        if self.prefer_local_proxy and self._local_proxy_available:
            if prefer_socks and HAS_AIOHTTP_SOCKS:
                return f"socks5://127.0.0.1:{self.local_socks_port}"
            return f"http://127.0.0.1:{self.local_http_port}"
        
        # 直接使用节点（仅HTTP/SOCKS5类型）
        if self.current_node:
            return self.current_node.proxy_url or None
        
        return None
    
    def create_connector(self) -> Optional[Any]:
        """
        创建aiohttp连接器
        
        Returns:
            ProxyConnector（SOCKS5）或 None（HTTP代理不需要特殊连接器）
        """
        proxy_url = self.get_proxy_url(prefer_socks=True)
        
        if proxy_url and proxy_url.startswith('socks') and HAS_AIOHTTP_SOCKS:
            return ProxyConnector.from_url(proxy_url)
        
        return None
    
    def create_session(
        self,
        timeout: int = 30,
        **kwargs
    ) -> aiohttp.ClientSession:
        """
        创建带代理的aiohttp会话
        
        Args:
            timeout: 请求超时
            **kwargs: 传递给ClientSession的其他参数
        """
        connector = self.create_connector()
        
        session_kwargs = {
            'timeout': aiohttp.ClientTimeout(total=timeout),
            **kwargs
        }
        
        if connector:
            session_kwargs['connector'] = connector
        
        return aiohttp.ClientSession(**session_kwargs)
    
    def get_request_kwargs(self) -> Dict[str, Any]:
        """
        获取请求参数（用于HTTP代理模式）
        
        在使用session.get()等方法时传入proxy参数。
        """
        proxy_url = self.get_proxy_url(prefer_socks=False)
        
        if proxy_url and proxy_url.startswith('http'):
            return {'proxy': proxy_url}
        
        return {}
    
    def report_failure(self):
        """报告当前节点失败"""
        if self.current_node:
            self.current_node.fail_count += 1
            
            if self.auto_rotate and self.current_node.fail_count >= self.max_fail_count:
                logger.warning(f"节点 {self.current_node.name} 失败次数过多，自动切换")
                self.current_node.is_available = False
                self.rotate_node()
    
    def report_success(self):
        """报告当前节点成功"""
        if self.current_node:
            self.current_node.fail_count = 0
    
    def get_status(self) -> Dict[str, Any]:
        """获取代理状态"""
        return {
            'local_proxy_available': self._local_proxy_available,
            'local_http_port': self.local_http_port,
            'local_socks_port': self.local_socks_port,
            'current_node': str(self.current_node) if self.current_node else None,
            'total_nodes': len(self.config.nodes) if self.config else 0,
            'available_nodes': len(self.config.get_available_nodes()) if self.config else 0,
            'proxy_url': self.get_proxy_url(),
        }


# ============================================
# 便捷函数
# ============================================

async def create_proxy_manager(
    config_source: str,
    test_nodes: bool = True,
    check_local: bool = True,
) -> ProxyManager:
    """
    创建并初始化代理管理器的便捷函数
    
    Args:
        config_source: 配置文件路径或订阅URL
        test_nodes: 是否测试节点
        check_local: 是否检查本地代理
    """
    manager = ProxyManager()
    
    await manager.load_config(config_source)
    
    if check_local:
        await manager.check_local_proxy()
    
    if test_nodes:
        await manager.test_nodes()
        manager.select_fastest()
    
    return manager


# ============================================
# 测试入口
# ============================================

async def main():
    """测试代理管理器"""
    import sys
    
    # 配置日志
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="DEBUG"
    )
    
    print("=" * 60)
    print("🚀 代理管理器测试")
    print("=" * 60)
    
    # 测试配置文件路径
    config_file = "config.yaml"
    
    if not os.path.exists(config_file):
        logger.error(f"配置文件不存在: {config_file}")
        logger.info("请提供Clash配置文件或订阅URL")
        return
    
    manager = await create_proxy_manager(config_file)
    
    # 显示状态
    status = manager.get_status()
    print(f"\n📊 代理状态:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    # 测试HTTP请求
    print(f"\n🔗 测试HTTP请求...")
    
    async with manager.create_session() as session:
        request_kwargs = manager.get_request_kwargs()
        
        try:
            async with session.get(
                "https://httpbin.org/ip",
                **request_kwargs
            ) as response:
                data = await response.json()
                print(f"✅ 请求成功! IP: {data.get('origin', 'N/A')}")
                manager.report_success()
                
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            manager.report_failure()


if __name__ == "__main__":
    asyncio.run(main())