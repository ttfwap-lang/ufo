"""
测试 Constellation Client 注册时的设备验证机制
"""
import asyncio
import logging
import sys
import os
sys.path.insert(0, os.path.abspath('.'))
import pytest
from ufo.galaxy.client.config_loader import ConstellationConfig, DeviceConfig
from ufo.galaxy.client.constellation_client import ConstellationClient
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_device_validation():
    """测试设备验证机制"""
    print('=' * 80)
    print('🔍 测试 Constellation Client 设备验证机制')
    print('=' * 80)
    print('\n[1] 测试连接到不存在的设备...')
    try:
        invalid_config = ConstellationConfig(task_name='test_validation', devices=[DeviceConfig(device_id='nonexistent_device', server_url='ws://localhost:5000/ws', capabilities=['testing'], metadata={'test': 'invalid_device'})], heartbeat_interval=30.0, max_concurrent_tasks=2)
        constellation_client = ConstellationClient(invalid_config)
        print('🚀 正在尝试初始化并连接到不存在的设备...')
        try:
            await constellation_client.initialize()
            print('❌ 意外成功：客户端应该无法连接到不存在的设备')
        except Exception as e:
            print(f'✅ 预期失败：无法连接到不存在的设备 - {e}')
        await constellation_client.shutdown()
    except Exception as e:
        print(f'✅ 测试按预期失败：{e}')
    print('\n[2] 测试完整的设备验证流程...')
    try:
        valid_config = ConstellationConfig.from_yaml('config/constellation_sample.yaml')
        print(f'📋 加载配置成功，设备数量: {len(valid_config.devices)}')
        for device_id in valid_config.devices:
            print(f'   设备: {device_id}')
        constellation_client = ConstellationClient(valid_config)
        print('🚀 正在初始化 constellation client...')
        await constellation_client.initialize()
        connected_devices = constellation_client.get_connected_devices()
        print(f'✅ 成功连接的设备: {connected_devices}')
        print('⏳ 等待 5 秒测试连接稳定性...')
        await asyncio.sleep(5)
        final_devices = constellation_client.get_connected_devices()
        print(f'📊 最终连接状态: {final_devices}')
        await constellation_client.shutdown()
        print('✅ 客户端已正常关闭')
    except Exception as e:
        print(f'❌ 有效配置测试失败: {e}')
        import traceback
        traceback.print_exc()
    print('\n' + '=' * 80)
    print('🎯 设备验证机制测试完成')
    print('   请检查服务器日志确认验证逻辑是否正确执行')
    print('=' * 80)

async def main():
    """主函数"""
    try:
        await test_device_validation()
    except KeyboardInterrupt:
        print('\n测试被用户中断')
    except Exception as e:
        print(f'测试失败: {e}')
        import traceback
        traceback.print_exc()
if __name__ == '__main__':
    asyncio.run(main())