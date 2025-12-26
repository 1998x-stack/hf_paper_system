"""
Bityun VPN Python Proxy 实现
支持解析Clash配置、连接SS服务器、智能选择节点
"""

import yaml
import socket
import struct
import hashlib
import requests
import asyncio
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================
# 1. 数据结构定义
# ============================================

@dataclass
class ProxyNode:
    """代理节点配置"""
    name: str
    server: str
    port: int
    password: str
    cipher: str
    protocol: str = "ss"
    udp: bool = True
    latency: float = float('inf')
    
    def __repr__(self):
        return f"<ProxyNode {self.name} - {self.server}:{self.port}>"


@dataclass
class ProxyConfig:
    """完整代理配置"""
    nodes: List[ProxyNode]
    rules: List[Dict]
    dns_config: Dict
    proxy_groups: List[Dict]
    
    def get_node_by_name(self, name: str) -> Optional[ProxyNode]:
        """通过名称获取节点"""
        for node in self.nodes:
            if node.name == name:
                return node
        return None
    
    def get_nodes_by_region(self, region: str) -> List[ProxyNode]:
        """获取指定地区的节点"""
        return [n for n in self.nodes if region in n.name]


# ============================================
# 2. 配置解析器
# ============================================

class ClashConfigParser:
    """Clash配置文件解析器"""
    
    @staticmethod
    def parse_yaml_file(file_path: str) -> ProxyConfig:
        """解析YAML配置文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return ClashConfigParser.parse_dict(data)
    
    @staticmethod
    def parse_dict(data: Dict) -> ProxyConfig:
        """解析配置字典"""
        # 解析节点
        nodes = []
        for proxy in data.get('proxies', []):
            if proxy.get('type') == 'ss':
                node = ProxyNode(
                    name=proxy['name'],
                    server=proxy['server'],
                    port=proxy['port'],
                    password=proxy['password'],
                    cipher=proxy['cipher'],
                    udp=proxy.get('udp', True)
                )
                nodes.append(node)
        
        config = ProxyConfig(
            nodes=nodes,
            rules=data.get('rules', []),
            dns_config=data.get('dns', {}),
            proxy_groups=data.get('proxy-groups', [])
        )
        
        logger.info(f"✅ 解析完成：{len(nodes)} 个节点")
        return config
    
    @staticmethod
    def download_subscription(url: str) -> ProxyConfig:
        """从订阅URL下载配置"""
        try:
            logger.info(f"📥 下载订阅: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            # 可能是base64编码
            try:
                import base64
                content = base64.b64decode(response.text).decode('utf-8')
            except:
                content = response.text
            
            data = yaml.safe_load(content)
            return ClashConfigParser.parse_dict(data)
        except Exception as e:
            logger.error(f"❌ 下载订阅失败: {e}")
            raise


# ============================================
# 3. Shadowsocks 实现
# ============================================

class ShadowsocksClient:
    """Shadowsocks客户端（简化版）"""
    
    METHOD_SUPPORTED = {
        'aes-128-gcm': (16, 16),  # (key_len, iv_len)
        'aes-256-gcm': (32, 32),
        'chacha20-ietf-poly1305': (32, 32),
    }
    
    def __init__(self, node: ProxyNode):
        self.node = node
        self.cipher = node.cipher
        
        if self.cipher not in self.METHOD_SUPPORTED:
            raise ValueError(f"不支持的加密方法: {self.cipher}")
        
        self.key_len, self.iv_len = self.METHOD_SUPPORTED[self.cipher]
        self.key = self._evp_bytes_to_key(node.password.encode(), self.key_len)
    
    def _evp_bytes_to_key(self, password: bytes, key_len: int) -> bytes:
        """密码派生密钥（EVP_BytesToKey）"""
        m = []
        i = 0
        while len(b''.join(m)) < key_len:
            md = hashlib.md5()
            data = password
            if i > 0:
                data = m[i - 1] + password
            md.update(data)
            m.append(md.digest())
            i += 1
        return b''.join(m)[:key_len]
    
    def _create_cipher(self, iv: bytes, encrypt: bool = True):
        """创建加密器"""
        if 'gcm' in self.cipher:
            cipher = Cipher(
                algorithms.AES(self.key),
                modes.GCM(iv),
                backend=default_backend()
            )
        elif 'chacha20' in self.cipher:
            from cryptography.hazmat.primitives.ciphers import algorithms as algo
            cipher = Cipher(
                algo.ChaCha20(self.key, iv),
                mode=None,
                backend=default_backend()
            )
        else:
            raise ValueError(f"不支持的密码: {self.cipher}")
        
        return cipher.encryptor() if encrypt else cipher.decryptor()
    
    async def connect(self, target_host: str, target_port: int):
        """连接到目标主机（通过SS服务器）"""
        try:
            # 1. 连接到SS服务器
            reader, writer = await asyncio.open_connection(
                self.node.server, 
                self.node.port
            )
            
            logger.info(f"🔗 已连接到 {self.node.name}")
            
            # 2. 发送SOCKS5请求
            # 构造请求数据：[地址类型][地址][端口]
            request = self._build_request(target_host, target_port)
            
            # 3. 加密并发送
            iv = os.urandom(self.iv_len)
            encryptor = self._create_cipher(iv, encrypt=True)
            encrypted = iv + encryptor.update(request)
            
            writer.write(encrypted)
            await writer.drain()
            
            return reader, writer
            
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            raise
    
    def _build_request(self, host: str, port: int) -> bytes:
        """构造SOCKS5请求"""
        # 地址类型
        if self._is_ip(host):
            atyp = b'\x01'  # IPv4
            addr = socket.inet_aton(host)
        else:
            atyp = b'\x03'  # 域名
            addr = len(host).to_bytes(1, 'big') + host.encode()
        
        # 端口（大端序）
        port_bytes = struct.pack('>H', port)
        
        return atyp + addr + port_bytes
    
    @staticmethod
    def _is_ip(host: str) -> bool:
        """检查是否是IP地址"""
        try:
            socket.inet_aton(host)
            return True
        except:
            return False


# ============================================
# 4. 节点测速器
# ============================================

class NodeTester:
    """节点延迟测试"""
    
    @staticmethod
    async def test_latency(node: ProxyNode, timeout: float = 5.0) -> float:
        """测试节点延迟（TCP连接）"""
        try:
            start = time.time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(node.server, node.port),
                timeout=timeout
            )
            latency = (time.time() - start) * 1000  # 毫秒
            writer.close()
            await writer.wait_closed()
            
            node.latency = latency
            logger.info(f"✅ {node.name}: {latency:.0f}ms")
            return latency
        except asyncio.TimeoutError:
            node.latency = float('inf')
            logger.warning(f"⏱️ {node.name}: 超时")
            return float('inf')
        except Exception as e:
            node.latency = float('inf')
            logger.error(f"❌ {node.name}: {e}")
            return float('inf')
    
    @staticmethod
    async def test_all_nodes(nodes: List[ProxyNode]) -> List[ProxyNode]:
        """测试所有节点"""
        logger.info(f"🔍 开始测试 {len(nodes)} 个节点...")
        tasks = [NodeTester.test_latency(node) for node in nodes]
        await asyncio.gather(*tasks)
        
        # 按延迟排序
        nodes.sort(key=lambda n: n.latency)
        return nodes


# ============================================
# 5. 智能选择器
# ============================================

class NodeSelector:
    """智能节点选择器"""
    
    def __init__(self, config: ProxyConfig):
        self.config = config
        self.current_node = None
    
    def select_fastest(self, region: Optional[str] = None) -> ProxyNode:
        """选择最快的节点"""
        nodes = self.config.nodes
        if region:
            nodes = self.config.get_nodes_by_region(region)
        
        if not nodes:
            raise ValueError("没有可用节点")
        
        # 找到延迟最低的
        fastest = min(nodes, key=lambda n: n.latency)
        self.current_node = fastest
        logger.info(f"🚀 选择节点: {fastest.name} ({fastest.latency:.0f}ms)")
        return fastest
    
    def select_by_name(self, name: str) -> ProxyNode:
        """通过名称选择节点"""
        node = self.config.get_node_by_name(name)
        if not node:
            raise ValueError(f"未找到节点: {name}")
        self.current_node = node
        return node
    
    def get_available_nodes(self, max_latency: float = 500) -> List[ProxyNode]:
        """获取可用节点（延迟小于阈值）"""
        return [n for n in self.config.nodes if n.latency < max_latency]


# ============================================
# 6. 本地HTTP代理服务器
# ============================================

class LocalProxyServer:
    """本地HTTP/SOCKS5代理服务器"""
    
    def __init__(self, config: ProxyConfig, listen_host='127.0.0.1', listen_port=7890):
        self.config = config
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.selector = NodeSelector(config)
        
    async def start(self):
        """启动代理服务器"""
        server = await asyncio.start_server(
            self.handle_client,
            self.listen_host,
            self.listen_port
        )
        
        addr = server.sockets[0].getsockname()
        logger.info(f"🌐 代理服务器运行在 {addr[0]}:{addr[1]}")
        
        async with server:
            await server.serve_forever()
    
    async def handle_client(self, client_reader, client_writer):
        """处理客户端连接"""
        try:
            # 读取第一个字节判断协议
            first_byte = await client_reader.read(1)
            
            if first_byte == b'\x05':
                # SOCKS5协议
                await self.handle_socks5(client_reader, client_writer, first_byte)
            else:
                # HTTP协议
                await self.handle_http(client_reader, client_writer, first_byte)
                
        except Exception as e:
            logger.error(f"❌ 处理客户端失败: {e}")
        finally:
            client_writer.close()
            await client_writer.wait_closed()
    
    async def handle_socks5(self, reader, writer, first_byte):
        """处理SOCKS5请求"""
        # 实现SOCKS5协议...
        logger.info("🔌 SOCKS5请求")
        pass
    
    async def handle_http(self, reader, writer, first_byte):
        """处理HTTP代理请求"""
        logger.info("🌐 HTTP请求")
        # 实现HTTP CONNECT方法...
        pass


# ============================================
# 7. 主程序
# ============================================

import os

async def main():
    """主函数"""
    
    print("=" * 60)
    print("🚀 Bityun VPN Python Proxy")
    print("=" * 60)
    
    # 1. 加载配置
    config_file = "1766745722873_bityun_qq.yaml"
    
    # 方式1: 从本地文件加载
    if os.path.exists(config_file):
        logger.info("📂 从本地文件加载配置...")
        config = ClashConfigParser.parse_yaml_file(config_file)
    else:
        # 方式2: 从订阅URL下载
        subscription_url = "https://times1766152644.subxiandan.top:9604/v2b/bityun/api/v1/client/subscribe?token=34bc20bef5fc9212539fb413b596c3af"
        config = ClashConfigParser.download_subscription(subscription_url)
    
    print(f"✅ 加载了 {len(config.nodes)} 个节点\n")
    
    # 2. 测试节点延迟
    logger.info("🔍 开始测试节点延迟...")
    await NodeTester.test_all_nodes(config.nodes)
    
    # 3. 选择最快节点
    selector = NodeSelector(config)
    
    # 显示可用节点
    available = selector.get_available_nodes(max_latency=500)
    print(f"\n📊 可用节点 ({len(available)}):")
    for i, node in enumerate(available[:10], 1):
        print(f"  {i}. {node.name:40s} {node.latency:6.0f}ms")
    
    fastest = selector.select_fastest()
    print(f"\n🚀 自动选择: {fastest.name} ({fastest.latency:.0f}ms)")
    
    # 4. 测试连接
    print(f"\n🔗 测试连接到Google...")
    ss_client = ShadowsocksClient(fastest)
    try:
        reader, writer = await ss_client.connect("www.google.com", 443)
        print("✅ 连接成功！")
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        print(f"❌ 连接失败: {e}")
    
    # 5. 启动本地代理服务器（可选）
    # proxy_server = LocalProxyServer(config)
    # await proxy_server.start()


if __name__ == "__main__":
    asyncio.run(main())
