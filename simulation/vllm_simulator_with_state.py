"""
vLLM风格内存管理仿真器（支持状态保存和加载）
支持swap和sacrifice两种抢占模式
支持从非空初始状态开始仿真
支持在指定批次保存系统状态
"""
from typing import List, Dict, Any, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request, SwapEvent
from core.constants import RequestStatus
from core.state_manager import save_state_to_csv
from .base_simulator import BaseSimulator


class VLLMSimulatorWithState(BaseSimulator):
    """
    vLLM风格内存管理仿真器（支持状态保存和加载）
    支持swap（CPU-GPU交换）和sacrifice（重置进度）两种抢占模式
    支持从非空初始状态开始仿真
    支持在指定批次保存系统状态
    """
    
    def __init__(self, config: Dict[str, Any], control_policy, 
                 initial_time: float = 0.0,
                 initial_requests: List[Request] = None,
                 state_save_config: Dict[str, Any] = None,
                 output_dir: str = None):
        """
        初始化仿真器
        
        Args:
            config: 系统配置
            control_policy: 控制策略
            initial_time: 初始时间（从状态文件加载时使用）
            initial_requests: 初始请求列表（包含在队列中的请求）
            state_save_config: 状态保存配置
            output_dir: 输出目录（用于保存状态）
        """
        super().__init__(config, control_policy)
        
        # 设置初始时间
        self.time = initial_time
        self.initial_time = initial_time
        
        # 状态保存配置
        self.state_save_config = state_save_config or {}
        self.output_dir = output_dir
        
        # 保存所有请求的引用（用于状态保存）
        self.all_requests = []
        
        # 如果提供了初始请求，设置初始状态
        if initial_requests:
            self._setup_initial_state(initial_requests)
    
    def _setup_initial_state(self, initial_requests: List[Request]):
        """
        设置初始状态
        
        Args:
            initial_requests: 初始请求列表
        """
        # 清空当前队列
        self.state.waiting.clear()
        self.state.running.clear()
        self.state.swapped.clear()
        
        # 根据状态分配请求到相应队列
        for req in initial_requests:
            if req.status == RequestStatus.WAITING:
                self.state.waiting.append(req)
            elif req.status == RequestStatus.RUNNING:
                self.state.running.append(req)
            elif req.status == RequestStatus.SWAPPED:
                self.state.swapped.append(req)
        
        print(f"初始状态设置完成:")
        print(f"  WAITING: {len(self.state.waiting)}")
        print(f"  RUNNING: {len(self.state.running)}")
        print(f"  SWAPPED: {len(self.state.swapped)}")
        print(f"  GPU内存使用: {self.state.gpu_memory_used}/{self.state.M_total}")
    
    def handle_memory_pressure(self):
        """
        处理内存压力 - Swapping策略
        当GPU内存超限时，将请求交换到CPU
        """
        while self.state.is_memory_overloaded:
            # 计算需要释放的内存
            memory_needed = self.state.gpu_memory_used - self.state.M_total
            
            # 选择要交换的请求
            victims = self.control_policy.select_swap_victims(
                self.state.running, 
                memory_needed
            )
            
            if not victims:
                # 无法选择victim，可能是因为批次为空
                break
            
            # 执行交换
            for victim in victims:
                self.swap_out_request(victim)
    
    def select_execution_batch(self) -> List[Request]:
        """
        从RUNNING列表中选择执行批次（受B约束）
        按FCFS顺序选择，直到达到B约束
        
        Returns:
            要执行的请求列表
        """
        execution_batch = []
        total_tokens = 0
        
        # 按照RUNNING列表的顺序（FCFS）选择请求
        for req in self.state.running:
            # 计算添加这个请求后的token数
            req_tokens = req.memory_requirement + 1  # +1是因为即将执行
            
            # 检查是否超过B约束
            if total_tokens + req_tokens > self.state.B:
                # 如果第一个请求就超过B，至少要执行它
                if not execution_batch:
                    execution_batch.append(req)
                    total_tokens += req_tokens
                break
            
            execution_batch.append(req)
            total_tokens += req_tokens
        
        # 保存执行批次信息（用于记录）
        self.current_execution_batch = execution_batch
        self.current_batch_tokens = total_tokens
        
        return execution_batch
    
    def calculate_batch_duration_for_requests(self, requests: List[Request]) -> float:
        """
        计算特定请求集合的批次执行时间
        
        Args:
            requests: 要执行的请求列表
            
        Returns:
            批次执行时间
        """
        # 计算这些请求的总token数
        total_tokens = sum(
            req.memory_requirement + 1 
            for req in requests
        )
        return self.d_0 + self.d_1 * total_tokens
    
    def advance_decode_positions_for_batch(self, requests: List[Request]):
        """
        推进指定请求的解码位置
        
        Args:
            requests: 要推进的请求列表
        """
        for req in requests:
            req.current_decode_position += 1
    
    def swap_out_request(self, request: Request):
        """
        将请求交换到CPU
        
        Args:
            request: 要交换的请求
        """
        # 记录swap事件
        swap_event = SwapEvent(
            swap_out_time=self.time,
            decode_position=request.current_decode_position,
            memory_size=request.current_memory_usage
        )
        request.swap_events.append(swap_event)
        
        # 更新系统状态
        self.state.swap_out(request, self.time)
        
        # 记录事件
        self.log_event('swap_out', request.req_id, {
            'decode_position': request.current_decode_position,
            'memory_freed': request.current_memory_usage
        })
    
    def step(self) -> bool:
        """
        执行一个批次的仿真步骤
        
        Returns:
            是否继续仿真
        """
        # 检查是否有运行中的请求
        if not self.state.running and not self.state.waiting and not self.state.swapped:
            return False  # 仿真结束
        
        # 1. 如果没有运行中的批次，立即构建新批次
        if not self.state.running:
            self.control_policy.perform_scheduling_cycle(self.state, self.time)
            if not self.state.running:
                # 仍然没有批次，可能是等待队列为空或内存不足
                return False
        
        # 2. 从RUNNING列表中选择执行批次（受B约束）
        execution_batch = self.select_execution_batch()
        
        # 保存实际执行批次信息到状态（用于快照记录）
        self.state.actual_batch_count = len(execution_batch)
        self.state.actual_batch_tokens = self.current_batch_tokens
        
        # 3. 记录批次快照（包含了实际执行批次的信息）
        self.record_snapshot()
        
        # 重置批次sacrifice计数器（快照已记录了上个批次的sacrifice数量）
        self.state.batch_sacrifices = 0
        
        # 4. 计算批次执行时间（基于实际执行的批次）
        duration = self.calculate_batch_duration_for_requests(execution_batch)
        
        # 5. 推进执行批次中请求的解码位置
        self.advance_decode_positions_for_batch(execution_batch)
        
        # 6. 更新时间（在提取完成请求之前）
        self.time += duration
        self.batch_id += 1
        
        # 7. 提取完成的请求
        completed = self.extract_completed_requests()
        
        # 8. 构建下一批次（内存检查已移至构建阶段）
        self.control_policy.perform_scheduling_cycle(self.state, self.time)
        
        return True
    
    def run(self, requests: List[Request]) -> Dict[str, Any]:
        """
        运行完整的仿真
        
        Args:
            requests: 请求列表
            
        Returns:
            仿真结果
        """
        # 保存所有请求的引用（用于状态保存）
        self.all_requests = requests
        
        # 分离初始状态中的请求和待到达的请求
        pending_requests = []
        for req in requests:
            # 只有状态为WAITING且arrival_time > self.time的请求才是待到达的
            # 其他的应该已经在初始状态中了
            if req.status == RequestStatus.WAITING and req not in self.state.waiting:
                if req.arrival_time > self.time:
                    pending_requests.append(req)
        
        # 按到达时间排序待处理请求
        pending_requests.sort(key=lambda r: r.arrival_time)
        
        if self.initial_time > 0:
            print(f"从时间 {self.initial_time:.2f} 开始仿真")
            if pending_requests:
                print(f"待到达请求: {len(pending_requests)}, 首个到达时间: {pending_requests[0].arrival_time:.2f}")
        
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
            
            # 如果没有任何活动，推进时间到下一个请求到达
            if not self.state.running and not self.state.waiting and not self.state.swapped:
                if pending_requests:
                    self.time = pending_requests[0].arrival_time
                    continue
                else:
                    break  # 仿真结束
            
            # 执行一个批次步骤
            if not self.step():
                break
            
            # 检查是否需要保存状态
            if self.state_save_config.get('enabled', False):
                if self.batch_id in self.state_save_config.get('batch_ids', []):
                    self._save_state()
            
            # 进度报告
            if self.batch_id % 100 == 0:
                print(f"批次 {self.batch_id}: 时间={self.time:.2f}, "
                      f"运行={len(self.state.running)}, "
                      f"等待={len(self.state.waiting)}, "
                      f"交换={len(self.state.swapped)}, "
                      f"完成={len(self.state.completed_requests)}")
        
        # 收集最终统计信息
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
        
        return results
        
    def _save_state(self):
        """
        保存当前系统状态
        """
        if not self.output_dir:
            print(f"警告：未指定输出目录，跳过状态保存")
            return
        
        try:
            filepath = save_state_to_csv(
                all_requests=self.all_requests,
                state=self.state,
                batch_id=self.batch_id,
                current_time=self.time,
                output_dir=self.output_dir
            )
            print(f"状态已保存: batch_{self.batch_id} at time {self.time:.2f}")
        except Exception as e:
            print(f"保存状态失败: {e}")
    
    def __repr__(self) -> str:
        return f"VLLMSimulator(time={self.time:.2f}, batch={self.batch_id})"