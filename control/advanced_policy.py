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
    
    def _select_victims_lifo_by_running_time(self, running: List[Request], 
                                            memory_needed: int,
                                            exclude_current: Request = None) -> List[Request]:
        """
        使用严格的LIFO策略选择victims
        基于进入running的时间，而不是arrival_time
        
        这对应vLLM中running_queue.pop()的行为
        
        Args:
            running: 当前running的请求列表
            memory_needed: 需要释放的内存量
            exclude_current: 需要排除的请求（可能是当前正在处理的）
        
        Returns:
            选中的victims列表
        """
        if not running:
            return []
        
        # 关键修正：基于enter_running_times而不是arrival_time
        # 这确保我们选择"最晚进入running"的请求作为victims
        candidates = [r for r in running if r != exclude_current]
        
        # 按进入running的时间降序排序（最晚的在前）
        sorted_candidates = sorted(
            candidates,
            key=lambda r: r.enter_running_times[-1] if r.enter_running_times else 0,
            reverse=True
        )
        
        victims = []
        freed_memory = 0
        
        for req in sorted_candidates:
            if freed_memory >= memory_needed:
                break
            victims.append(req)
            freed_memory += req.current_memory_usage
        
        return victims
    
    def _perform_sacrifice(self, victim: Request, state: SystemState, 
                          current_time: float) -> None:
        """
        执行sacrifice操作
        对应vLLM的_preempt_by_recompute
        
        Args:
            victim: 要sacrifice的请求
            state: 系统状态
            current_time: 当前时间
        """
        from core.request import SacrificeEvent
        
        # 统计running队列中同decode位置的请求数
        same_position_count = sum(
            1 for req in state.running 
            if req.current_decode_position == victim.current_decode_position
        )
        total_running = len(state.running)
        
        # 记录sacrifice事件（包含上下文信息）
        sacrifice_event = SacrificeEvent(
            time=current_time,
            decode_position=victim.current_decode_position,
            memory_freed=victim.current_memory_usage,
            running_count_same_position=same_position_count,
            total_running_count=total_running
        )
        victim.sacrifice_events.append(sacrifice_event)
        
        # 从running中移除
        state.remove_from_batch(victim, current_time)
        
        # 关键：重置decode进度（sacrifice的核心特征）
        victim.current_decode_position = 0
        
        # 注意：不要在这里将victim加入waiting！
        # 这会在Phase 3中统一处理
        
        # 更新统计
        state.total_sacrifices += 1
        state.batch_sacrifices += 1
    
    def perform_scheduling_cycle(self, state: SystemState, 
                               current_time: float) -> None:
        """
        执行完整的调度周期，对应vLLM的_schedule_default方法
        
        在sacrifice+aggressive模式下，这个方法执行三个关键阶段：
        1. Prefill阶段：尝试将waiting请求调度到running（不触发抢占）
        2. Running阶段：处理running请求的内存增长，必要时触发抢占
        3. 队列更新阶段：将被抢占的请求批量加入waiting队首
        
        Args:
            state: 系统状态
            current_time: 当前时间
        """
        if self.preemption_strategy == "conservative":
            # Conservative策略保持原有逻辑
            self._admission_control_conservative(state, current_time)
        else:
            # Aggressive策略：严格遵循vLLM的三阶段调度
            
            # ========== Phase 1: Schedule Prefills (对应 _schedule_prefills) ==========
            # 关键点：只尝试调度，不触发抢占，遇到内存不足立即停止
            admitted_from_waiting = self._schedule_waiting_no_preemption(state, current_time)
            
            # ========== Phase 2: Schedule Running (对应 _schedule_running) ==========
            # 关键点：检查内存增长，使用LIFO选择victims，收集但不立即放回
            preempted_requests = self._handle_running_memory_pressure(state, current_time)
            
            # ========== Phase 3: Update Queues (对应 waiting.extendleft) ==========
            # 关键点：批量将被抢占的请求加入waiting队首，保持原有顺序
            if preempted_requests:
                # 注意：使用reverse确保被抢占请求的相对顺序保持不变
                # 这对应vLLM的extendleft操作
                for req in reversed(preempted_requests):
                    req.status = RequestStatus.WAITING
                    state.waiting.insert(0, req)
    
    def _schedule_waiting_no_preemption(self, state: SystemState, 
                                       current_time: float) -> List[Request]:
        """
        Phase 1: 调度waiting请求，不触发抢占
        对应vLLM的_schedule_prefills方法
        
        关键行为：
        1. 按FCFS顺序遍历waiting队列
        2. 遇到第一个无法调度的请求就停止（不跳过）
        3. 不触发任何抢占
        
        Returns:
            成功调度的请求列表
        """
        admitted = []
        
        # 1. 处理SWAPPED队列（如果是swap模式）
        if self.preemption_mode == 'swap' and state.swapped:
            for req in list(state.swapped):
                # 检查是否可以准入（对应vLLM的can_allocate检查）
                # 注意：需要为decode预留一个token的空间
                required_memory = req.memory_requirement + 1
                
                # 检查内存约束
                if required_memory > state.available_memory:
                    # 关键：遇到第一个无法调度的请求就停止
                    break
                
                # 注意：在vLLM中，B约束不在这里检查
                # B约束只在选择执行批次时（select_execution_batch）起作用
                # 这允许running队列包含超过B限制的请求，提供更大的调度灵活性
                #
                # 原代码（已注释）：
                # current_batch_tokens = sum(r.current_memory_usage for r in state.running)
                # if current_batch_tokens + req.memory_requirement > state.B:
                #     break
                
                # 可以调度：从swapped移除并加入running
                state.swapped.remove(req)
                state.admit_to_batch(req, current_time)
                state.total_swapped_in += 1
                if req.swap_events:
                    req.swap_events[-1].swap_in_time = current_time
                admitted.append(req)
        
        # 2. 处理WAITING队列
        # 重要：使用list(state.waiting)创建副本，避免在遍历时修改
        for req in list(state.waiting):
            # 检查是否可以准入（对应vLLM的can_allocate检查）
            # 注意：需要为decode预留一个token的空间
            required_memory = req.memory_requirement + 1
            
            # 检查内存约束
            if required_memory > state.available_memory:
                # 关键：遇到第一个无法调度的请求就停止
                # 这对应vLLM中的break逻辑
                break
            
            # 注意：在vLLM中，B约束不在这里检查
            # B约束只在选择执行批次时（select_execution_batch）起作用
            # 这允许running队列包含超过B限制的请求，提供更大的调度灵活性
            #
            # 原代码（已注释）：
            # current_batch_tokens = sum(r.current_memory_usage for r in state.running)
            # if current_batch_tokens + req.memory_requirement > state.B:
            #     break
            
            # 可以调度：从waiting移除并加入running
            state.waiting.remove(req)
            state.admit_to_batch(req, current_time)
            admitted.append(req)
        
        return admitted
    
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
    
    def _handle_running_memory_pressure(self, state: SystemState, 
                                       current_time: float) -> List[Request]:
        """
        Phase 2: 处理running请求的内存压力（批量优化版本）
        
        在PD分离的decode端，所有请求统一推进，因此可以批量处理
        这种实现在效果上等价于逐个处理，但效率更高
        
        Returns:
            被抢占的请求列表
        """
        preempted = []
        
        # 批量检查内存压力
        # 所有running请求都会增长1个token
        total_memory_after_growth = state.gpu_memory_used + len(state.running)
        
        # 如果不会超出内存限制，直接返回
        if total_memory_after_growth <= state.M_total:
            return preempted
        
        # 需要抢占，计算需要释放的内存量
        memory_to_free = total_memory_after_growth - state.M_total
        
        # 使用LIFO策略选择victims
        # 注意：这里的关键是保持选择顺序与vLLM一致
        running_copy = list(state.running)
        
        while memory_to_free > 0 and running_copy:
            # 选择最晚进入running的请求作为victim
            # 这等价于vLLM的running_queue.pop()
            victim = max(
                running_copy,
                key=lambda r: r.enter_running_times[-1] if r.enter_running_times else 0
            )
            
            # 执行抢占
            running_copy.remove(victim)
            memory_to_free -= victim.current_memory_usage
            
            if self.preemption_mode == 'sacrifice':
                self._perform_sacrifice(victim, state, current_time)
                preempted.append(victim)
            elif self.preemption_mode == 'swap':
                # swap模式处理
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
        
        return preempted
    
    def _check_memory_for_growth(self, request: Request, 
                                state: SystemState,
                                already_processed: List[Request]) -> bool:
        """
        检查是否有足够的内存为请求分配新的token空间
        对应vLLM的_can_append_slots功能
        
        Args:
            request: 要检查的请求
            state: 系统状态
            already_processed: 已经处理过的请求列表
        
        Returns:
            是否可以为请求分配内存
        """
        # 计算当前的内存使用
        # 包括已处理的请求和这个请求的内存需求
        total_memory_needed = 0
        
        # 已处理请求的内存（包括增长）
        for req in already_processed:
            total_memory_needed += req.current_memory_usage + 1  # +1 for growth
        
        # 当前请求的内存（包括增长）
        total_memory_needed += request.current_memory_usage + 1
        
        # 还在队列中等待处理的请求的当前内存
        for req in state.running:
            if req not in already_processed and req != request:
                total_memory_needed += req.current_memory_usage
        
        return total_memory_needed <= state.M_total
    
    def _select_single_victim_lifo(self, candidates: List[Request],
                                  exclude_current: Request = None) -> Optional[Request]:
        """
        从候选列表中选择一个victim（LIFO策略）
        对应vLLM的running_queue.pop()
        
        Args:
            candidates: 候选请求列表
            exclude_current: 要排除的请求（通常是当前正在处理的）
        
        Returns:
            选中的victim，如果没有合适的则返回None
        """
        # 过滤掉要排除的请求
        filtered = [r for r in candidates if r != exclude_current]
        
        if not filtered:
            return None
        
        # 选择最晚进入running的请求
        # 这对应vLLM的LIFO策略
        victim = max(
            filtered,
            key=lambda r: r.enter_running_times[-1] if r.enter_running_times else 0
        )
        
        return victim
    
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
    
    
    
    def should_use_swap_mode(self) -> bool:
        """
        判断是否应该使用swap模式
        在PD分离的decode端，通常使用sacrifice模式
        
        Returns:
            是否使用swap模式
        """
        return self.preemption_mode == 'swap'
    
    def get_queue_order_key(self, request: Request) -> tuple:
        """
        获取队列排序的key
        在FCFS模式下基于arrival_time
        
        Args:
            request: 请求对象
            
        Returns:
            排序用的元组
        """
        # 对应vLLM的_get_priority方法
        # 在没有用户定义优先级时，使用arrival_time
        return (None, request.arrival_time)  # None表示没有用户优先级
    
    def __repr__(self) -> str:
        return f"AdvancedPolicy({self.preemption_mode}+{self.preemption_strategy})"