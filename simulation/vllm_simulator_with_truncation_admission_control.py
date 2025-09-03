"""
支持截断点切换和准入控制的vLLM仿真器
在截断功能基础上增加内存阈值准入控制机制
"""
import csv
import os
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from .vllm_simulator_with_truncation import VLLMSimulatorWithTruncation
from core.request import Request
from core.constants import RequestStatus
from data.input.generate_requests_using_type import generate_requests_by_type, parse_types_string


class VLLMSimulatorWithTruncationAdmissionControl(VLLMSimulatorWithTruncation):
    """
    支持截断点切换和准入控制的vLLM仿真器
    继承自VLLMSimulatorWithTruncation，增加基于内存阈值的准入控制
    """
    
    def __init__(self, 
                 config: Dict,
                 control_policy,
                 truncation_batch_id: Optional[int] = None,
                 truncation_config: Optional[Dict] = None):
        """
        初始化带截断和准入控制功能的仿真器
        
        Args:
            config: 系统配置
            control_policy: 控制策略
            truncation_batch_id: 截断点批次ID（单个值）
            truncation_config: 截断后的新配置，包含generation参数
        """
        super().__init__(config, control_policy, truncation_batch_id, truncation_config)
        
        # 准入控制配置
        admission_config = config.get('admission_control', {})
        self.admission_enabled = admission_config.get('enabled', False)
        self.admission_threshold = admission_config.get('threshold', 1.0)
        
        # 准入控制统计
        self.admission_rejected_count = 0
        self.admission_rejected_batches = []  # 记录拒绝准入的批次
        self.max_memory_usage_ratio = 0
        self.time_above_threshold = 0
        self.last_check_time = 0
        
        # 保存原始的控制策略
        self.original_control_policy = control_policy
        
        if self.admission_enabled:
            print(f"准入控制已启用，阈值: {self.admission_threshold}")
    
    def _check_admission_allowed(self) -> bool:
        """
        检查是否允许准入新请求
        
        Returns:
            是否允许准入
        """
        if not self.admission_enabled or self.admission_threshold >= 1.0:
            return True
        
        # 计算当前内存使用率
        memory_usage = self.state.gpu_memory_used
        memory_total = self.state.M_total
        memory_usage_ratio = memory_usage / memory_total if memory_total > 0 else 0
        
        # 更新最大内存使用率
        self.max_memory_usage_ratio = max(self.max_memory_usage_ratio, memory_usage_ratio)
        
        # 统计超过阈值的时间
        current_time = self.time
        if memory_usage_ratio >= self.admission_threshold and self.last_check_time > 0:
            self.time_above_threshold += (current_time - self.last_check_time)
        self.last_check_time = current_time
        
        # 判断是否允许准入
        return memory_usage_ratio < self.admission_threshold
    
    def step(self) -> bool:
        """
        执行一个批次的仿真步骤，加入准入控制逻辑
        
        Returns:
            是否继续仿真
        """
        # 检查是否有运行中的请求
        if not self.state.running and not self.state.waiting and not self.state.swapped:
            return False  # 仿真结束
        
        # 1. 如果没有运行中的批次，尝试构建新批次（带准入控制）
        if not self.state.running:
            # 检查准入控制
            if self._check_admission_allowed():
                # 允许准入，调用原有调度逻辑
                self.control_policy.perform_scheduling_cycle(self.state, self.time)
            else:
                # 拒绝准入，记录统计
                waiting_count = len(self.state.waiting)
                swapped_count = len(self.state.swapped)
                
                if waiting_count > 0 or swapped_count > 0:
                    self.admission_rejected_count += 1
                    self.admission_rejected_batches.append(self.batch_id)
                    
                    if self.batch_id % 100 == 0 or self.config['experiment'].get('verbose', False):
                        memory_usage = self.state.gpu_memory_used
                        memory_total = self.state.M_total
                        memory_ratio = memory_usage / memory_total if memory_total > 0 else 0
                        print(f"批次 {self.batch_id}: 准入控制生效 - "
                              f"拒绝WAITING→RUNNING转换 (内存使用: {memory_usage}/{memory_total} = {memory_ratio:.2%}), "
                              f"等待队列: {waiting_count}, 交换队列: {swapped_count}")
            
            # 如果仍然没有批次，可能是等待队列为空或内存不足
            if not self.state.running:
                return False
        
        # 2. 从RUNNING列表中选择执行批次（受B约束）
        execution_batch = self.select_execution_batch()
        
        # 3. 记录批次快照（在执行前）
        batch_duration = self.d_0 + self.d_1 * self.current_batch_tokens
        
        # 更新实际执行批次信息
        self.state.actual_batch_tokens = self.current_batch_tokens
        self.state.actual_batch_count = len(execution_batch)
        
        snapshot = self.state.get_snapshot(self.time, self.batch_id, batch_duration)
        self.snapshots.append(snapshot)
        
        # 4. 执行批次（推进解码位置）
        self.advance_decode_positions_for_batch(execution_batch)
        
        # 5. 更新时间
        self.time += batch_duration
        self.batch_id += 1
        
        # 6. 清理完成的请求
        completed = [req for req in self.state.running if req.is_completed]
        for req in completed:
            self.state.complete_request(req, self.time)
            self.log_event('completion', req.req_id, {
                'decode_position': req.current_decode_position,
                'total_delay': req.total_delay
            })
        
        # 7. 处理内存压力和调度（再次检查准入控制）
        if self._check_admission_allowed():
            self.control_policy.perform_scheduling_cycle(self.state, self.time)
        else:
            # 即使不允许新准入，仍需要处理内存压力（如抢占）
            # 但不从WAITING准入新请求
            if hasattr(self.control_policy, '_handle_running_memory_pressure'):
                self.control_policy._handle_running_memory_pressure(self.state, self.time)
        
        # 重置批次sacrifice计数器
        self.state.batch_sacrifices = 0
        
        return True
    
    def run(self, requests: List[Request]) -> Dict[str, Any]:
        """
        运行仿真，支持截断和准入控制
        
        Args:
            requests: 请求列表
            
        Returns:
            仿真结果字典
        """
        # 调用父类的run方法
        results = super().run(requests)
        
        # 添加准入控制统计信息
        if self.admission_enabled:
            results['admission_control'] = {
                'enabled': True,
                'threshold': self.admission_threshold,
                'rejected_count': self.admission_rejected_count,
                'rejected_batches': self.admission_rejected_batches,
                'max_memory_usage_ratio': self.max_memory_usage_ratio,
                'time_above_threshold': self.time_above_threshold,
                'rejection_rate': self.admission_rejected_count / self.batch_id if self.batch_id > 0 else 0
            }
            
            # 打印准入控制统计摘要
            print(f"\n=== 准入控制统计 ===")
            print(f"阈值: {self.admission_threshold}")
            print(f"拒绝次数: {self.admission_rejected_count}")
            print(f"拒绝率: {results['admission_control']['rejection_rate']:.2%}")
            print(f"最大内存使用率: {self.max_memory_usage_ratio:.2%}")
            print(f"超过阈值时间: {self.time_above_threshold:.2f}")
        
        return results