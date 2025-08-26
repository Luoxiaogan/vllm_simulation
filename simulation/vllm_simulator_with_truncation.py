"""
支持截断点切换的vLLM仿真器
在指定批次截断，丢弃未到达请求，切换到新的请求生成参数
"""
import csv
import os
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from .vllm_simulator import VLLMSimulator
from core.request import Request
from core.constants import RequestStatus
from data.input.generate_requests_using_type import generate_requests_by_type, parse_types_string


class VLLMSimulatorWithTruncation(VLLMSimulator):
    """
    支持截断点切换的vLLM仿真器
    继承自VLLMSimulator，在指定批次截断并切换请求生成参数
    """
    
    def __init__(self, 
                 config: Dict,
                 control_policy,
                 truncation_batch_id: Optional[int] = None,
                 truncation_config: Optional[Dict] = None):
        """
        初始化带截断功能的仿真器
        
        Args:
            config: 系统配置
            control_policy: 控制策略
            truncation_batch_id: 截断点批次ID（单个值）
            truncation_config: 截断后的新配置，包含generation参数
        """
        super().__init__(config, control_policy)
        self.truncation_batch_id = truncation_batch_id
        self.truncation_config = truncation_config
        self.truncation_applied = False
        self.truncation_time = None
        self.new_requests_start_time = None  # 新请求的起始时间
        self.new_requests_end_time = None    # 新请求的结束时间
        self.all_requests = []  # 保存所有请求引用
        
    def run(self, requests: List[Request]) -> Dict[str, Any]:
        """
        运行仿真，支持在截断点切换参数
        覆盖父类方法，在主循环中加入截断检查
        
        Args:
            requests: 请求列表
            
        Returns:
            仿真结果字典
        """
        # 保存所有请求的引用
        self.all_requests = list(requests)
        
        # 按到达时间排序请求
        pending_requests = sorted(requests, key=lambda r: r.arrival_time)
        
        print(f"\n开始仿真...")
        print(f"策略组合: {self.control_policy}")
        
        if self.truncation_batch_id:
            print(f"截断点设置: batch_{self.truncation_batch_id}")
        
        # 运行仿真主循环
        while pending_requests or self.state.running or self.state.waiting or self.state.swapped:
            # 处理到达的请求
            while pending_requests and pending_requests[0].arrival_time <= self.time:
                req = pending_requests.pop(0)
                self.state.add_to_waiting(req)
                self.log_event('arrival', req.req_id, {
                    'prefill_length': req.prefill_length,
                    'decode_length': req.decode_length
                })
            
            # 检查是否到达截断点
            if (self.truncation_batch_id is not None and 
                self.batch_id == self.truncation_batch_id and 
                not self.truncation_applied):
                
                print(f"\n=== 到达截断点: batch_{self.batch_id} at time {self.time:.2f} ===")
                self.truncation_time = self.time
                
                # 应用截断：修改pending_requests列表
                new_requests = self._apply_truncation_and_get_new_requests(pending_requests)
                
                # 替换待处理请求列表
                pending_requests = sorted(new_requests, key=lambda r: r.arrival_time)
                
                self.truncation_applied = True
                print(f"截断完成，继续仿真...")
            
            # 如果没有任何活动，推进时间到下一个请求到达
            if not self.state.running and not self.state.waiting and not self.state.swapped:
                if pending_requests:
                    self.time = pending_requests[0].arrival_time
                    continue
                else:
                    break  # 仿真结束
            
            # 执行一个批次步骤（使用父类方法）
            if not self.step():
                break
            
            # 进度报告
            if self.batch_id % 100 == 0:
                print(f"批次 {self.batch_id}: 时间={self.time:.2f}, "
                      f"运行={len(self.state.running)}, "
                      f"等待={len(self.state.waiting)}, "
                      f"交换={len(self.state.swapped)}, "
                      f"完成={len(self.state.completed_requests)}")
        
        # 收集最终统计信息（使用父类格式）
        results = {
            'total_time': self.time,
            'total_batches': self.batch_id,
            'completed_requests': len(self.state.completed_requests),
            'snapshots': self.snapshots,
            'events': self.events,
            'requests': self.state.completed_requests,
            'statistics': self.state.get_statistics()
        }
        
        # 计算性能指标
        if self.state.completed_requests:
            delays = [req.total_delay for req in self.state.completed_requests if req.total_delay]
            waiting_times = [req.waiting_time for req in self.state.completed_requests if req.waiting_time]
            swap_counts = [req.swap_count for req in self.state.completed_requests]
            
            results['metrics'] = {
                'avg_delay': sum(delays) / len(delays) if delays else 0,
                'max_delay': max(delays) if delays else 0,
                'avg_waiting_time': sum(waiting_times) / len(waiting_times) if waiting_times else 0,
                'avg_swap_count': sum(swap_counts) / len(swap_counts) if swap_counts else 0,
                'throughput_requests': len(self.state.completed_requests) / self.time if self.time > 0 else 0,
                'throughput_tokens': sum(req.decode_length for req in self.state.completed_requests) / self.time if self.time > 0 else 0
            }
        
        # 添加截断信息到结果中
        if self.truncation_applied:
            results['truncation_info'] = {
                'truncation_batch_id': self.truncation_batch_id,
                'truncation_time': self.truncation_time,
                'new_requests_start_time': self.new_requests_start_time,
                'new_requests_end_time': self.new_requests_end_time,
                'new_requests_duration': (self.new_requests_end_time - self.truncation_time) if self.new_requests_end_time else 0
            }
        
        return results
    
    def _apply_truncation_and_get_new_requests(self, pending_requests: List[Request]) -> List[Request]:
        """
        应用截断：丢弃未到达的请求，生成新请求
        
        Args:
            pending_requests: 当前待处理的请求列表
            
        Returns:
            新的待处理请求列表
        """
        # 1. 统计当前状态
        not_arrived_count = len(pending_requests)
        arrived_count = len(self.all_requests) - not_arrived_count
        
        print(f"截断前统计:")
        print(f"  已到达: {arrived_count} 请求")
        print(f"  未到达: {not_arrived_count} 请求（将被丢弃）")
        print(f"  系统状态: WAITING={len(self.state.waiting)}, RUNNING={len(self.state.running)}")
        
        # 2. 记录已到达的请求（用于统计）
        self.all_requests = [r for r in self.all_requests if r not in pending_requests]
        
        # 3. 如果有新的生成配置，生成新请求
        new_pending_requests = []
        if self.truncation_config and 'generation' in self.truncation_config:
            gen_config = self.truncation_config['generation']
            
            print(f"\n生成新请求:")
            print(f"  类型: {gen_config['types']}")
            print(f"  数量: {gen_config['num_requests']}")
            print(f"  种子: {gen_config.get('seed', 42)}")
            
            # 生成新请求
            new_requests = self._generate_new_requests(gen_config)
            
            # 调整新请求的到达时间（加上当前时间偏移）
            for i, req in enumerate(new_requests):
                req.arrival_time += self.time
                req.req_id = len(self.all_requests) + i  # 确保ID唯一
            
            # 记录新请求的时间范围
            if new_requests:
                self.new_requests_start_time = new_requests[0].arrival_time
                self.new_requests_end_time = new_requests[-1].arrival_time
                print(f"  生成了 {len(new_requests)} 个新请求")
                print(f"  新请求时间范围: {self.new_requests_start_time:.2f} - {self.new_requests_end_time:.2f}")
            
            # 更新全局请求列表
            self.all_requests.extend(new_requests)
            new_pending_requests = new_requests
        
        print(f"\n截断后统计:")
        print(f"  总请求数: {len(self.all_requests)}")
        print(f"  新的待处理请求数: {len(new_pending_requests)}")
        
        return new_pending_requests
    
    
    def _generate_new_requests(self, gen_config: Dict) -> List[Request]:
        """
        生成新的请求
        
        Args:
            gen_config: 生成配置，支持rate_list覆盖原有到达率
            
        Returns:
            新生成的请求列表
        """
        # 解析请求类型
        request_types = parse_types_string(gen_config['types'])
        
        # 如果提供了rate_list，覆盖原有的到达率
        if 'rate_list' in gen_config:
            rate_list = gen_config['rate_list']
            if len(rate_list) != len(request_types):
                raise ValueError(f"rate_list长度({len(rate_list)})必须与types数量({len(request_types)})匹配")
            
            # 覆盖到达率
            new_types = []
            for i, (prefill, decode, _) in enumerate(request_types):
                new_types.append((prefill, decode, rate_list[i]))
            request_types = new_types
            
            print(f"  使用rate_list覆盖到达率: {rate_list}")
        
        # 生成请求数据（使用临时文件）
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp_file:
            tmp_path = tmp_file.name
        
        raw_requests = generate_requests_by_type(
            request_types=request_types,
            num_requests=gen_config['num_requests'],
            seed=gen_config.get('seed', 42),
            output_file=tmp_path
        )
        
        # 清理临时文件
        import os
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        
        # 转换为Request对象
        new_requests = []
        for i, req_data in enumerate(raw_requests):
            req = Request(
                req_id=i,
                arrival_time=req_data['arrival_time'],
                prefill_length=req_data['prefill_length'],
                decode_length=req_data['decode_length']
            )
            new_requests.append(req)
        
        return new_requests