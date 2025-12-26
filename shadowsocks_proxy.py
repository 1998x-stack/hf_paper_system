#!/usr/bin/env python3
"""
简化版 Shadowsocks 代理客户端
可直接使用现成的库，更简单实用

安装依赖:
pip install pysocks requests pyyaml aiohttp
"""

import yaml
import socks
import socket
import requests
import asyncio
import time
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class ProxyNode:
    """代理节点"""
    name: str
    server: str
    port: int
    password: str
    cipher: str
    latency: float = float('inf')


class SimpleProxyClient:
    """简化的代理客户端"""
    
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.nodes: List[ProxyNode] = []
        self.load_config()
    
    def load_config(self):
        """加载配置"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        for proxy in data.get('proxies', []):
            if proxy.get('type') == 'ss':
                node = ProxyNode(
                    name=proxy['name'],
                    server=proxy['server'],
                    port=proxy['port'],
                    password=proxy['password'],
                    cipher=proxy['cipher']
                )
                self.nodes.append(node)
        
        print(f"✅ 加载了 {len(self.nodes)} 个节点")
    
    def test_latency(self, node: ProxyNode, timeout: float = 3.0) -> float:
        """测试延迟（TCP连接）"""
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((node.server, node.port))
            latency = (time.time() - start) * 1000
            sock.close()
            node.latency = latency
            return latency
        except:
            node.latency = float('inf')
            return float('inf')
    
    def test_all_nodes(self):
        """测试所有节点"""
        print("\n🔍 测试节点延迟...")
        for i, node in enumerate(self.nodes, 1):
            latency = self.test_latency(node)
            status = "✅" if latency < float('inf') else "❌"
            latency_str = f"{latency:.0f}ms" if latency < float('inf') else "超时"
            print(f"  [{i}/{len(self.nodes)}] {status} {node.name[:40]:40s} {latency_str}")
        
        # 排序
        self.nodes.sort(key=lambda n: n.latency)
    
    def get_fastest_node(self, region: str = None) -> ProxyNode:
        """获取最快节点"""
        nodes = self.nodes
        if region:
            nodes = [n for n in nodes if region in n.name]
        
        available = [n for n in nodes if n.latency < float('inf')]
        if not available:
            raise ValueError("没有可用节点")
        
        return available[0]
    
    def create_proxy_dict(self, node: ProxyNode) -> Dict:
        """创建代理字典（用于requests）"""
        # 注意：requests不直接支持SS，这里返回SOCKS5格式
        # 实际使用需要先启动本地SS客户端
        return {
            'http': f'socks5h://127.0.0.1:1080',
            'https': f'socks5h://127.0.0.1:1080'
        }
    
    def test_proxy(self, node: ProxyNode) -> bool:
        """测试代理是否可用"""
        try:
            # 这里假设你已经启动了本地SS客户端
            proxies = self.create_proxy_dict(node)
            response = requests.get(
                'https://www.google.com',
                proxies=proxies,
                timeout=10
            )
            return response.status_code == 200
        except:
            return False
    
    def show_report(self):
        """显示测试报告"""
        print("\n" + "="*70)
        print("📊 节点测试报告")
        print("="*70)
        
        # 按地区分组
        regions = {}
        for node in self.nodes:
            for region in ['香港', '日本', '台湾', '美国', '韩国', '新加坡']:
                if region in node.name:
                    if region not in regions:
                        regions[region] = []
                    regions[region].append(node)
                    break
        
        # 显示每个地区
        for region, nodes in regions.items():
            available = [n for n in nodes if n.latency < float('inf')]
            print(f"\n🌍 {region} ({len(available)}/{len(nodes)} 可用)")
            
            if available:
                # 显示前3个最快的
                for i, node in enumerate(available[:3], 1):
                    print(f"  {i}. {node.name[:50]:50s} {node.latency:6.0f}ms")
            else:
                print("  ❌ 无可用节点")
        
        # 总体统计
        total_available = sum(1 for n in self.nodes if n.latency < float('inf'))
        print(f"\n📈 总计: {total_available}/{len(self.nodes)} 可用")
        
        # 最快的5个
        print(f"\n🏆 Top 5 最快节点:")
        fastest = [n for n in self.nodes if n.latency < float('inf')][:5]
        for i, node in enumerate(fastest, 1):
            print(f"  {i}. {node.name[:50]:50s} {node.latency:6.0f}ms")


class SSLocalStarter:
    """启动本地SS客户端"""
    
    @staticmethod
    def start_ss_local(node: ProxyNode, local_port: int = 1080):
        """
        启动SS本地客户端
        需要安装: pip install shadowsocks
        """
        try:
            import subprocess
            
            cmd = [
                'sslocal',
                '-s', node.server,
                '-p', str(node.port),
                '-k', node.password,
                '-m', node.cipher,
                '-l', str(local_port),
                '--fast-open'
            ]
            
            print(f"\n🚀 启动本地SS客户端...")
            print(f"   服务器: {node.name}")
            print(f"   本地端口: {local_port}")
            print(f"   命令: {' '.join(cmd)}")
            
            # 启动进程
            process = subprocess.Popen(cmd)
            return process
            
        except Exception as e:
            print(f"❌ 启动失败: {e}")
            print("\n💡 提示:")
            print("   1. 确保已安装shadowsocks: pip install shadowsocks")
            print("   2. 或使用Clash等客户端")
            return None


def demo_basic_usage():
    """演示基本使用"""
    print("="*70)
    print("🚀 Bityun VPN 代理客户端")
    print("="*70)
    
    # 1. 加载配置
    client = SimpleProxyClient("1766745722873_bityun_qq.yaml")
    
    # 2. 测试所有节点
    client.test_all_nodes()
    
    # 3. 显示报告
    client.show_report()
    
    # 4. 选择最快节点
    try:
        fastest = client.get_fastest_node()
        print(f"\n✨ 推荐节点: {fastest.name} ({fastest.latency:.0f}ms)")
        
        # 5. 生成配置信息
        print(f"\n📝 节点配置:")
        print(f"   服务器: {fastest.server}")
        print(f"   端口: {fastest.port}")
        print(f"   密码: {fastest.password}")
        print(f"   加密: {fastest.cipher}")
        
    except ValueError as e:
        print(f"\n❌ {e}")


def demo_region_select():
    """演示按地区选择"""
    client = SimpleProxyClient("1766745722873_bityun_qq.yaml")
    client.test_all_nodes()
    
    print("\n" + "="*70)
    print("🌏 按地区选择节点")
    print("="*70)
    
    regions = ['香港', '日本', '台湾', '美国']
    for region in regions:
        try:
            fastest = client.get_fastest_node(region)
            print(f"\n{region}最快: {fastest.name} ({fastest.latency:.0f}ms)")
        except ValueError:
            print(f"\n{region}: ❌ 无可用节点")


def demo_with_requests():
    """演示使用requests发送请求（需要本地SS客户端）"""
    print("\n" + "="*70)
    print("🌐 测试代理访问Google")
    print("="*70)
    
    # 配置代理
    proxies = {
        'http': 'socks5h://127.0.0.1:1080',
        'https': 'socks5h://127.0.0.1:1080'
    }
    
    print("\n⚠️  请确保已启动本地SS客户端（端口1080）")
    print("   可使用Clash或sslocal等客户端\n")
    
    try:
        # 测试连接
        print("🔗 正在连接Google...")
        response = requests.get(
            'https://www.google.com',
            proxies=proxies,
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ 连接成功！")
            print(f"   状态码: {response.status_code}")
            print(f"   响应大小: {len(response.content)} 字节")
        else:
            print(f"⚠️  状态码: {response.status_code}")
            
    except requests.exceptions.ProxyError:
        print("❌ 代理连接失败，请检查:")
        print("   1. 本地SS客户端是否运行")
        print("   2. 端口是否为1080")
        print("   3. 节点是否可用")
    except requests.exceptions.Timeout:
        print("❌ 连接超时")
    except Exception as e:
        print(f"❌ 错误: {e}")


def interactive_menu():
    """交互式菜单"""
    while True:
        print("\n" + "="*70)
        print("📋 菜单")
        print("="*70)
        print("1. 测试所有节点")
        print("2. 查看测试报告")
        print("3. 选择最快节点")
        print("4. 按地区选择")
        print("5. 测试代理访问")
        print("0. 退出")
        print("="*70)
        
        choice = input("\n请选择 (0-5): ").strip()
        
        if choice == '1':
            demo_basic_usage()
        elif choice == '2':
            client = SimpleProxyClient("1766745722873_bityun_qq.yaml")
            client.test_all_nodes()
            client.show_report()
        elif choice == '3':
            client = SimpleProxyClient("1766745722873_bityun_qq.yaml")
            client.test_all_nodes()
            fastest = client.get_fastest_node()
            print(f"\n✨ 最快节点: {fastest.name} ({fastest.latency:.0f}ms)")
        elif choice == '4':
            demo_region_select()
        elif choice == '5':
            demo_with_requests()
        elif choice == '0':
            print("\n👋 再见!")
            break
        else:
            print("❌ 无效选择")


if __name__ == "__main__":
    try:
        # 直接运行演示
        demo_basic_usage()
        
        # 或者使用交互式菜单
        # interactive_menu()
        
    except KeyboardInterrupt:
        print("\n\n👋 用户取消")
    except FileNotFoundError:
        print("❌ 配置文件不存在: 1766745722873_bityun_qq.yaml")
        print("   请将配置文件放在同一目录下")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()