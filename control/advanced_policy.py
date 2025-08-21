"""
高级控制策略实现
支持Swap/Sacrifice模式和Aggressive/Conservative策略
"""
from typing import List, Optional, Dict, Any
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request, SwapEvent, SacrificeEvent, RequestStatus
from core.system_state import SystemState
from .base_policy import ControlPolicy


class AdvancedPolicy(ControlPolicy):
    """
    高级策略：
    - 抢占模式：Swap 或 Sacrifice
    - 抢占策略：Aggressive 或 Conservative
    - 队列策略：FCFS
    - Victim选择：LIFO（基于进入RUNNING的时间）
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化高级策略
        
        Args:
            config: 配置字典，包含：
                - preemption_mode: "swap" 或 "sacrifice"
                - preemption_strategy: "aggressive" 或 "conservative"
                - allow_waiting_preempt: bool, WAITING是否可以触发抢占
        """
        self.preemption_mode = config.get('preemption_mode', 'swap')
        self.preemption_strategy = config.get('preemption_strategy', 'conservative')
        self.allow_waiting_preempt = config.get('allow_waiting_preempt', False)
        
        # 验证配置
        assert self.preemption_mode in ['swap', 'sacrifice'], \
            f"Invalid preemption_mode: {self.preemption_mode}"
        assert self.preemption_strategy in ['aggressive', 'conservative'], \
            f"Invalid preemption_strategy: {self.preemption_strategy}"
    
    def select_from_waiting(self, waiting: List[Request], 
                           available_memory: int) -> List[Request]:
        """
        FCFS方式从等待队列选择请求
        """
        selected = []
        for req in waiting:
            if req.memory_requirement <= available_memory:
                selected.append(req)
                available_memory -= req.memory_requirement
        return selected
    
    def select_swap_victims(self, running: List[Request], 
                          memory_needed: int) -> List[Request]:
        """
        LIFO方式选择swap victims
        """
        return self._select_victims_lifo(running, memory_needed)
    
    def select_sacrifice_victims(self, running: List[Request], 
                               memory_needed: int) -> List[Request]:
        """
        LIFO方式选择sacrifice victims
        """
        return self._select_victims_lifo(running, memory_needed)
    
    def _select_victims_lifo(self, running: List[Request], 
                            memory_needed: int) -> List[Request]:
        """
        LIFO选择victim的通用逻辑
        """
        if not running:
            return []
        
        # 按进入RUNNING的时间降序排序（最晚的在前）
        sorted_batch = sorted(
            running, 
            key=lambda r: r.enter_running_times[-1] if r.enter_running_times else 0,
            reverse=True
        )
        
        victims = []
        freed_memory = 0
        
        for req in sorted_batch:
            if freed_memory >= memory_needed:
                break
            victims.append(req)
            freed_memory += req.current_memory_usage
        
        return victims
    
    def _select_victims_by_arrival_time(self, running: List[Request], 
                                       memory_needed: int) -> List[Request]:
        """
        基于arrival_time选择victims（用于FCFS+sacrifice场景）
        选择arrival_time最晚的请求作为victims
        
        Args:
            running: 运行中的请求列表
            memory_needed: 需要释放的内存量
            
        Returns:
            可以被抢占的victims列表
        """
        if not running:
            return []
        
        # 按arrival_time降序排序（最晚到达的在前）
        sorted_running = sorted(running, 
                              key=lambda r: r.arrival_time, 
                              reverse=True)
        
        victims = []
        freed_memory = 0
        
        for req in sorted_running:
            if freed_memory >= memory_needed:
                break
            victims.append(req)
            freed_memory += req.current_memory_usage
        
        return victims
    
    def construct_next_batch(self, state: SystemState, 
                           current_time: float) -> None:
        """
        构建下一个批次 - 模拟vLLM的_schedule_default流程
        分离调度和抢占阶段，避免抢占风暴
        """
        if self.preemption_strategy == "conservative":
            # 保守策略：保持原有逻辑（不抢占）
            self._admission_control_conservative(state, current_time)
        else:
            # 激进策略：模拟vLLM的三阶段调度
            # Phase 1: 调度waiting到running（类似_schedule_prefills，不抢占）
            self._schedule_waiting_phase(state, current_time)
            
            # Phase 2: 处理running的内存增长（类似_schedule_running，可能抢占）
            preempted = self._handle_memory_growth_with_preemption(state, current_time)
            
            # Phase 3: 批量将被抢占的请求加入waiting队首
            if preempted:
                # 反向插入保持原有顺序
                for req in reversed(preempted):
                    req.status = RequestStatus.WAITING
                    state.waiting.insert(0, req)
    
    def _schedule_waiting_phase(self, state: SystemState, current_time: float):
        """
        调度阶段：类似vLLM的_schedule_prefills
        只尝试将能放下的请求加入running，不触发抢占
        """
        # 1. 处理SWAPPED队列（如果是swap模式）
        if self.preemption_mode == 'swap' and state.swapped:
            for req in list(state.swapped):
                if self._can_admit_directly(req, state):
                    state.swapped.remove(req)
                    state.admit_to_batch(req, current_time)
                    state.total_swapped_in += 1
                    if req.swap_events:
                        req.swap_events[-1].swap_in_time = current_time
        
        # 2. 处理WAITING队列
        for req in list(state.waiting):
            if self._can_admit_directly(req, state):
                state.waiting.remove(req)
                state.admit_to_batch(req, current_time)
    
    def _can_admit_directly(self, request: Request, state: SystemState) -> bool:
        """
        检查是否可以直接接纳请求（不触发抢占）
        """
        # 检查内存约束（包括下一个token生成的空间）
        required_memory = request.memory_requirement + 1
        if required_memory > state.available_memory:
            return False
        
        # 检查批次token预算
        current_batch_tokens = sum(r.current_memory_usage for r in state.running)
        if current_batch_tokens + request.memory_requirement > state.B:
            return False
        
        return True
    
    def _handle_memory_growth_with_preemption(self, state: SystemState, 
                                             current_time: float) -> List[Request]:
        """
        内存增长处理阶段：类似vLLM的_schedule_running
        检查running请求的内存增长，必要时触发抢占
        返回被抢占的请求列表（不立即加入waiting）
        """
        preempted = []
        
        # 检查是否需要抢占（模拟下一个token生成的内存需求）
        while state.running and state.gpu_memory_used + len(state.running) > state.M_total:
            memory_needed = (state.gpu_memory_used + len(state.running)) - state.M_total
            
            if self.preemption_mode == 'swap':
                # swap模式：使用LIFO选择victims
                victims = self.select_swap_victims(state.running, memory_needed)
                if not victims:
                    break
                    
                for victim in victims:
                    # 执行swap out
                    swap_event = SwapEvent(
                        swap_out_time=current_time,
                        decode_position=victim.current_decode_position,
                        memory_size=victim.current_memory_usage
                    )
                    victim.swap_events.append(swap_event)
                    state.remove_from_batch(victim, current_time)
                    victim.status = RequestStatus.SWAPPED
                    state.swapped.append(victim)
                    state.total_swapped_out += 1
                    
            else:  # sacrifice模式
                # 在FCFS场景下，基于arrival_time选择victims
                # 选择最晚到达的请求作为victims（保护早到达的请求）
                victims = self._select_victims_by_arrival_time(state.running, memory_needed)
                    
                if not victims:
                    break
                    
                for victim in victims:
                    # 记录sacrifice事件
                    sacrifice_event = SacrificeEvent(
                        time=current_time,
                        decode_position=victim.current_decode_position,
                        memory_freed=victim.current_memory_usage
                    )
                    victim.sacrifice_events.append(sacrifice_event)
                    
                    # 从running移除
                    state.remove_from_batch(victim, current_time)
                    
                    # 重置进度
                    victim.current_decode_position = 0
                    
                    # 添加到待返回列表（不立即加入waiting！）
                    preempted.append(victim)
                    state.total_sacrifices += 1
                    state.batch_sacrifices += 1
        
        return preempted
    
    def _admission_control_conservative(self, state: SystemState, current_time: float):
        """
        保守准入控制：最小化抢占
        """
        # 1. 优先处理SWAPPED队列（如果是swap模式）
        if self.preemption_mode == 'swap' and state.swapped:
            self._try_admit_without_preemption(
                state.swapped, state, current_time, is_swapped=True
            )
        
        # 2. 处理WAITING队列（包括sacrifice模式下的高优先级请求）
        self._try_admit_without_preemption(
            state.waiting, state, current_time, is_swapped=False
        )
        
        # 注意：Conservative策略下不进行任何抢占
        # 完全依赖请求自然完成来释放内存
        # 这样可以避免系统震荡，保持稳定性
    
    
    def _try_admit_without_preemption(self, queue: List[Request], 
                                     state: SystemState, 
                                     current_time: float,
                                     is_swapped: bool = False):
        """
        尝试在不抢占的情况下接纳请求
        """
        admitted = []
        for req in queue[:]:  # 使用切片避免修改时的问题
            # 检查内存（考虑执行后的增长）
            required_memory = req.memory_requirement + 1
            if required_memory <= state.available_memory:
                admitted.append(req)
                # 临时减少可用内存（用于后续请求的检查）
                state.M_total -= required_memory  # 临时修改
        
        # 恢复M_total
        for req in admitted:
            state.M_total += req.memory_requirement + 1
        
        # 执行实际的接纳
        for req in admitted:
            if is_swapped:
                # 从swapped恢复
                state.swapped.remove(req)
                state.admit_to_batch(req, current_time)
                state.total_swapped_in += 1
                if req.swap_events:
                    req.swap_events[-1].swap_in_time = current_time
            else:
                # 从waiting接纳
                state.waiting.remove(req)
                state.admit_to_batch(req, current_time)
    
    
    
    def __repr__(self) -> str:
        return f"AdvancedPolicy({self.preemption_mode}+{self.preemption_strategy})"