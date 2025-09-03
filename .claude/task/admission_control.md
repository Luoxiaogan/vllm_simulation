# 准入控制功能实现计划

## 一、需求分析

### 1.1 功能目标
在截断仿真的基础上，添加准入控制（Admission Control）机制，通过设置内存使用阈值来限制系统负载，防止过载并研究系统在受限条件下的行为。

### 1.2 核心需求
- **阈值控制**：当 `gpu_memory_used >= M_total * threshold` 时，停止从WAITING队列准入新请求
- **兼容性**：完全兼容现有的截断功能（explore和truncate模式）
- **透明性**：不影响其他系统逻辑（调度、抢占、执行等）
- **可观测性**：记录准入拒绝事件，提供统计信息

### 1.3 使用场景
1. **容量规划**：确定系统在不同负载水平下的最优阈值
2. **稳定性研究**：观察系统在准入控制下的队列动态
3. **性能优化**：平衡内存利用率和响应延迟
4. **过载保护**：防止系统因过度准入而崩溃

## 二、设计方案

### 2.1 架构设计

```
VLLMSimulator (基类)
    ↑
VLLMSimulatorWithTruncation (截断功能)
    ↑
VLLMSimulatorWithTruncationAdmissionControl (准入控制)
```

继承关系确保了功能的层次化和代码复用。

### 2.2 核心机制

#### 2.2.1 准入检查逻辑
```python
def can_admit_with_threshold(self, state, threshold):
    """
    检查是否可以准入新请求（考虑阈值）
    """
    # 计算内存使用率
    memory_usage_ratio = state.gpu_memory_used / state.M_total
    
    # 如果已达到阈值，拒绝准入
    if memory_usage_ratio >= threshold:
        return False
    
    # 否则使用原有逻辑
    return True
```

#### 2.2.2 修改准入流程
在 `_schedule_waiting_no_preemption` 或相关方法中加入阈值检查：
```python
# 在准入前检查阈值
if not self.can_admit_with_threshold(state, self.admission_threshold):
    self.admission_rejected_count += 1
    break  # 停止准入
```

### 2.3 配置参数

新增配置节：
```yaml
admission_control:
  enabled: true
  threshold: 0.8  # 内存使用率阈值 (0.0-1.0)
```

### 2.4 统计指标

新增统计信息：
- `admission_rejected_count`: 因阈值而拒绝的准入次数
- `admission_rejected_requests`: 被拒绝的请求列表
- `time_above_threshold`: 内存使用率超过阈值的时间
- `max_memory_usage_ratio`: 最大内存使用率

## 三、实现步骤

### 3.1 Step 1: 修改仿真器类

文件：`simulation/vllm_simulator_with_truncation_admission_control.py`

```python
class VLLMSimulatorWithTruncationAdmissionControl(VLLMSimulatorWithTruncation):
    def __init__(self, config, control_policy, 
                 truncation_batch_id=None, 
                 truncation_config=None,
                 admission_threshold=1.0):  # 默认无限制
        super().__init__(config, control_policy, 
                        truncation_batch_id, truncation_config)
        self.admission_threshold = admission_threshold
        self.admission_rejected_count = 0
        self.admission_rejected_requests = []
        self.time_above_threshold = 0
        self.max_memory_usage_ratio = 0
        
    def _check_admission_allowed(self):
        """检查是否允许准入"""
        memory_usage_ratio = self.state.gpu_memory_used / self.state.M_total
        self.max_memory_usage_ratio = max(self.max_memory_usage_ratio, 
                                         memory_usage_ratio)
        return memory_usage_ratio < self.admission_threshold
```

### 3.2 Step 2: 重写调度方法

重写或扩展准入相关方法：
```python
def perform_admission_with_control(self, state, current_time):
    """带准入控制的调度"""
    if not self._check_admission_allowed():
        # 记录拒绝
        waiting_count = len(state.waiting)
        if waiting_count > 0:
            self.admission_rejected_count += waiting_count
            print(f"准入控制：拒绝 {waiting_count} 个请求 "
                  f"(内存使用: {state.gpu_memory_used}/{state.M_total})")
        return []
    
    # 调用原有准入逻辑
    return super()._schedule_waiting_no_preemption(state, current_time)
```

### 3.3 Step 3: 创建配置文件

#### explore_truncation_admission_control.yaml
```yaml
# 探索模式 + 准入控制
generation:
  enabled: true
  types: "{(20,20,5.1)}"
  num_requests: 22000
  output: "data/input/explore_admission.csv"
  seed: 42

explore:
  candidate_batches: [2950, 3030, 3100, 3150]

# 准入控制配置
admission_control:
  enabled: true
  threshold: 0.8  # 当内存使用达到80%时停止准入

regression_interval: [2500, 4000]

system:
  M_total: 10000
  B: 10000
  d_0: 0.003
  d_1: 0.00032

control:
  queue_policy: FCFS
  preemption_mode: sacrifice
  preemption_strategy: aggressive
  allow_waiting_preempt: false
  victim_policy: LIFO

data:
  request_file: data/input/explore_admission.csv
  experiments_dir: data/experiments
  L_filter: null

experiment:
  seed: 42
  verbose: true
  progress_interval: 100
```

#### apply_truncation_admission_control.yaml
```yaml
# 截断模式 + 准入控制
truncation:
  batch_id: 3400
  new_generation:
    types: "{(20,20,5.1)}"
    rate_list: [5.9]
    num_requests: 12000
    seed: 123

# 准入控制配置
admission_control:
  enabled: true
  threshold: 0.75  # 更严格的阈值

regression_interval: [3200, 4000]

system:
  M_total: 10000
  B: 10000
  d_0: 0.003
  d_1: 0.00032

control:
  queue_policy: FCFS
  preemption_mode: sacrifice
  preemption_strategy: aggressive
  allow_waiting_preempt: false
  victim_policy: LIFO

data:
  request_file: data/input/explore.csv
  experiments_dir: data/experiments
  L_filter: null

experiment:
  seed: 42
  verbose: true
  progress_interval: 100
```

### 3.4 Step 4: 修改实验脚本（可选）

如果需要，修改 `experiments/run_with_truncation.py` 以支持准入控制：
```python
# 读取准入控制配置
admission_config = config.get('admission_control', {})
if admission_config.get('enabled', False):
    admission_threshold = admission_config.get('threshold', 1.0)
    print(f"准入控制已启用，阈值: {admission_threshold}")
    
    # 使用准入控制仿真器
    from simulation.vllm_simulator_with_truncation_admission_control import \
        VLLMSimulatorWithTruncationAdmissionControl
    
    simulator = VLLMSimulatorWithTruncationAdmissionControl(
        config=config,
        control_policy=control_policy,
        truncation_batch_id=truncation_batch_id,
        truncation_config=truncation_config,
        admission_threshold=admission_threshold
    )
```

### 3.5 Step 5: 增强统计输出

在结果中添加准入控制统计：
```python
# 在 run() 方法的结果字典中添加
if self.admission_threshold < 1.0:
    results['admission_control'] = {
        'threshold': self.admission_threshold,
        'rejected_count': self.admission_rejected_count,
        'max_memory_usage_ratio': self.max_memory_usage_ratio,
        'time_above_threshold': self.time_above_threshold
    }
```

## 四、测试方案

### 4.1 功能测试

1. **基本功能测试**
   - 验证阈值控制是否生效
   - 检查准入拒绝计数是否正确
   - 确认内存使用率不超过阈值

2. **兼容性测试**
   - 测试与探索模式的兼容性
   - 测试与截断模式的兼容性
   - 验证不影响其他系统功能

### 4.2 性能测试

1. **不同阈值测试**
   - threshold = 0.5, 0.6, 0.7, 0.8, 0.9, 1.0
   - 观察系统行为变化
   - 分析队列长度和延迟

2. **负载测试**
   - 低负载（λ=2.0）
   - 中负载（λ=5.0）
   - 高负载（λ=10.0）

### 4.3 测试命令

```bash
# 探索模式 + 准入控制
python experiments/run_with_truncation.py \
    --config config/explore_truncation_admission_control.yaml \
    --mode explore

# 截断模式 + 准入控制
python experiments/run_with_truncation.py \
    --config config/apply_truncation_admission_control.yaml \
    --mode truncate
```

## 五、预期效果

### 5.1 系统行为变化

1. **队列动态**
   - WAITING队列可能增长更快
   - RUNNING队列保持在阈值以下
   - 系统更稳定但吞吐量可能降低

2. **内存使用**
   - 内存使用率稳定在阈值附近
   - 避免内存溢出
   - 更可预测的性能

### 5.2 可视化增强

在 `queue_dynamics.png` 中可以看到：
- 内存使用率的"平顶"效应
- WAITING队列的积累
- 准入拒绝事件的标记

### 5.3 理论意义

1. **稳定性分析**
   - 研究受限系统的流体极限
   - 分析准入控制对稳态的影响

2. **优化问题**
   - 寻找最优阈值
   - 平衡利用率和延迟

3. **控制理论**
   - 准入控制作为反馈机制
   - 系统的可控性和可观测性

## 六、实现注意事项

### 6.1 边界条件
- threshold = 0: 完全拒绝准入
- threshold = 1: 等同于无准入控制
- threshold 应在 (0, 1] 范围内

### 6.2 性能影响
- 准入检查的开销很小（O(1)）
- 不影响已在运行的请求
- 可能导致WAITING队列增长

### 6.3 与抢占的交互
- 准入控制与抢占机制独立
- 抢占可以释放内存，允许新的准入
- 两者共同维护系统稳定性

## 七、扩展可能

### 7.1 动态阈值
```python
# 根据队列长度动态调整阈值
if len(state.waiting) > 100:
    dynamic_threshold = max(0.6, self.admission_threshold - 0.1)
else:
    dynamic_threshold = self.admission_threshold
```

### 7.2 多级阈值
```python
# 不同优先级使用不同阈值
thresholds = {
    'high_priority': 0.9,
    'normal': 0.8,
    'low_priority': 0.7
}
```

### 7.3 预测性准入
基于请求特征和系统状态预测是否应该准入。

## 八、总结

准入控制机制为截断仿真系统增加了一个重要的控制维度。通过设置内存使用阈值，系统可以：
1. 防止过载，保持稳定运行
2. 研究受限条件下的系统行为
3. 优化资源利用和性能平衡

该功能与现有的截断功能完全兼容，为研究LLM服务系统的动态行为提供了更丰富的工具。