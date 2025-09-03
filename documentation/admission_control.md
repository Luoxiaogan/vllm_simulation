# 准入控制功能详解

## 一、概述

### 1.1 什么是准入控制

准入控制（Admission Control）是一种预防性的资源管理机制，通过限制新请求进入系统来维持系统稳定性。在LLM服务的流体ODE仿真系统中，准入控制基于GPU内存使用率阈值，当内存使用接近饱和时，暂停接纳新请求到RUNNING状态，防止系统过载。

### 1.2 设计动机

在实际的LLM服务系统中，无限制地接纳请求会导致：
- **内存溢出（OOM）**：GPU内存耗尽导致系统崩溃
- **性能退化**：过度的内存压力触发频繁抢占，降低整体效率
- **延迟不可控**：队列无界增长，请求延迟难以预测
- **系统震荡**：在高负载下系统行为不稳定

准入控制通过设置内存使用阈值，在问题发生前就预防它，保证系统在可控范围内运行。

### 1.3 与截断仿真的关系

准入控制功能构建在截断仿真基础之上，两者完美互补：
- **截断仿真**：研究系统对负载变化的动态响应
- **准入控制**：限制系统负载，维持稳定运行
- **组合使用**：可以研究在受限条件下的负载切换行为

## 二、工作原理

### 2.1 核心机制

准入控制的核心逻辑非常简单但有效：

```
如果 (GPU内存使用率 >= 阈值):
    拒绝从WAITING队列准入新请求
否则:
    允许正常准入
```

具体实现：
```python
memory_usage_ratio = state.gpu_memory_used / state.M_total
if memory_usage_ratio >= admission_threshold:
    # 拒绝准入
    return False
```

### 2.2 控制点

准入控制只在特定的调度点生效：
1. **WAITING → RUNNING**：阻止新请求进入GPU内存
2. **SWAPPED → RUNNING**：阻止被交换的请求恢复（如果启用swap模式）

重要的是，准入控制**不影响**：
- 已在RUNNING中的请求继续执行
- 内存压力触发的抢占机制
- 请求的到达和排队
- 批次执行和decode推进

### 2.3 阈值含义

阈值（threshold）是一个0到1之间的浮点数，表示触发准入控制的内存使用率：
- `threshold = 0.7`：当内存使用达到70%时开始拒绝准入
- `threshold = 0.8`：当内存使用达到80%时开始拒绝准入
- `threshold = 1.0`：不启用准入控制（默认值）

### 2.4 与抢占的交互

准入控制和抢占机制协同工作：
1. **准入控制是预防性的**：阻止问题发生
2. **抢占是响应性的**：解决已发生的问题
3. **两者互补**：准入控制减少抢占频率，抢占释放内存允许新准入

## 三、实现架构

### 3.1 类层次结构

```
VLLMSimulator
    ↑ 继承
VLLMSimulatorWithTruncation
    ↑ 继承
VLLMSimulatorWithTruncationAdmissionControl
```

通过继承链，准入控制功能自然地扩展了现有系统，保持了所有原有功能。

### 3.2 关键组件

#### VLLMSimulatorWithTruncationAdmissionControl类

主要职责：
- 从配置读取准入控制参数
- 在调度时检查内存阈值
- 记录准入拒绝统计
- 生成准入控制报告

关键方法：
```python
def _check_admission_allowed(self) -> bool:
    """检查是否允许准入"""
    
def step(self) -> bool:
    """执行批次步骤，加入准入控制"""
    
def run(self, requests) -> Dict:
    """运行仿真并收集统计"""
```

### 3.3 配置参数

在YAML配置文件中添加：
```yaml
admission_control:
  enabled: true      # 是否启用准入控制
  threshold: 0.8     # 内存使用率阈值
```

### 3.4 统计指标

系统收集以下准入控制相关指标：
- `rejected_count`：拒绝准入的次数
- `rejected_batches`：发生拒绝的批次列表
- `max_memory_usage_ratio`：观察到的最大内存使用率
- `time_above_threshold`：内存使用超过阈值的总时间
- `rejection_rate`：拒绝率（拒绝次数/总批次数）

## 四、使用指南

### 4.1 基本配置

#### 探索模式配置（explore_truncation_admission_control.yaml）
```yaml
# 初始请求生成
generation:
  enabled: true
  types: "{(20,20,5.1)}"
  num_requests: 22000
  
# 准入控制
admission_control:
  enabled: true
  threshold: 0.8  # 80%阈值
  
# 系统参数
system:
  M_total: 10000  # GPU总内存
  B: 10000        # 批次预算
```

#### 截断模式配置（apply_truncation_admission_control.yaml）
```yaml
# 截断配置
truncation:
  batch_id: 3400
  new_generation:
    types: "{(20,20,5.1)}"
    rate_list: [5.9]  # 提高到达率
    num_requests: 12000
    
# 准入控制（更严格）
admission_control:
  enabled: true
  threshold: 0.75  # 75%阈值
```

### 4.2 运行命令

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

### 4.3 参数选择建议

#### 阈值设置原则

| 阈值范围 | 适用场景 | 特点 |
|---------|---------|------|
| 0.6-0.7 | 保守策略 | 系统非常稳定，但利用率较低 |
| 0.7-0.8 | 平衡策略 | 兼顾稳定性和利用率（推荐） |
| 0.8-0.9 | 激进策略 | 高利用率，偶尔触发抢占 |
| 0.9-1.0 | 极限策略 | 最大化利用率，频繁抢占 |

#### 与抢占策略的搭配

1. **Conservative + 高阈值（0.85）**
   - 最大化内存利用
   - 依赖自然完成释放内存

2. **Aggressive + 中阈值（0.75）**
   - 平衡的配置
   - 准入控制为主，抢占为辅

3. **Sacrifice + 低阈值（0.7）**
   - 极度稳定
   - 适合对延迟敏感的场景

### 4.4 监控和调试

观察以下指标判断准入控制效果：

1. **内存使用模式**
   - 查看 `batch_snapshots.csv` 中的 `memory_utilization`
   - 应该在阈值附近形成"平台"

2. **队列长度变化**
   - WAITING队列可能显著增长
   - RUNNING队列保持相对稳定

3. **拒绝统计**
   - 拒绝率过高（>50%）说明阈值可能过低
   - 拒绝率为0说明阈值未生效

## 五、实验分析

### 5.1 典型实验场景

#### 场景1：稳态负载测试
```yaml
generation:
  types: "{(20,20,3.0)}"  # 中等负载
  num_requests: 10000
admission_control:
  threshold: 0.8
```
预期：系统稳定运行，偶尔触发准入控制

#### 场景2：过载保护测试
```yaml
generation:
  types: "{(20,20,10.0)}"  # 高负载
  num_requests: 10000
admission_control:
  threshold: 0.7
```
预期：频繁拒绝准入，WAITING队列增长，但系统不崩溃

#### 场景3：负载突变测试
```yaml
truncation:
  batch_id: 2000
  new_generation:
    rate_list: [15.0]  # 突然增加负载
admission_control:
  threshold: 0.75
```
预期：截断后立即触发准入控制，系统逐渐适应

### 5.2 性能影响分析

准入控制对系统性能的影响：

| 指标 | 影响 | 说明 |
|-----|------|------|
| 吞吐量 | ↓ | 限制并发导致吞吐量下降 |
| 平均延迟 | ↑ | 请求在WAITING队列等待更久 |
| 延迟方差 | ↓ | 延迟更可预测 |
| 内存利用率 | 稳定 | 维持在阈值附近 |
| 抢占频率 | ↓ | 减少内存压力事件 |
| 系统稳定性 | ↑ | 避免过载崩溃 |

### 5.3 可视化解读

在生成的图表中观察：

1. **queue_dynamics.png**
   - 内存使用线在阈值处"削平"
   - WAITING队列呈现阶梯状增长
   - RUNNING队列相对平稳

2. **arrival_dynamics.png**
   - 完成率（绿线）斜率可能降低
   - 外部到达和完成之间的差距增大

## 六、理论分析

### 6.1 流体模型扩展

准入控制修改了流体ODE模型的边界条件：

原始模型：
```
dX/dt = S_q(t) - completion_rate
```

带准入控制：
```
dX/dt = min(S_q(t), S_max) - completion_rate
其中 S_max = 0 when memory_usage >= threshold
```

### 6.2 稳定性分析

准入控制保证了系统的Lyapunov稳定性：
- **有界性**：内存使用有上界 M × threshold
- **收敛性**：系统状态收敛到稳定工作点
- **鲁棒性**：对负载扰动的抵抗能力增强

### 6.3 排队论视角

从排队论角度，准入控制将系统从：
- **M/M/c/∞** 队列（无限缓冲）
- 转变为 **M/M/c/N** 队列（有限缓冲）

其中 N 由内存阈值动态确定。

## 七、最佳实践

### 7.1 阈值调优流程

1. **基准测试**：不启用准入控制，观察最大内存使用
2. **初始设置**：设置阈值为最大使用率的80%
3. **逐步调整**：根据性能指标微调±5%
4. **验证稳定性**：运行长时间测试确认

### 7.2 生产环境建议

1. **渐进式部署**
   - 先在测试环境验证
   - 从高阈值（0.9）开始
   - 逐步降低到目标值

2. **监控告警**
   - 监控拒绝率
   - 设置队列长度告警
   - 跟踪内存使用趋势

3. **动态调整**
   - 根据时段调整阈值
   - 高峰期使用较低阈值
   - 低谷期放松限制

### 7.3 常见问题

**Q1: 阈值设置多少合适？**
A: 建议从0.8开始，根据实际负载和SLA要求调整。

**Q2: 准入控制会饿死某些请求吗？**
A: 不会。准入控制只是延迟准入，不会永久拒绝。当内存使用下降后会恢复准入。

**Q3: 与抢占机制冲突吗？**
A: 不冲突。准入控制是预防性的，抢占是纠正性的，两者互补。

**Q4: 如何判断准入控制是否生效？**
A: 查看输出中的"准入控制统计"，如果rejected_count > 0说明已生效。

## 八、总结

准入控制是保证LLM服务系统稳定性的关键机制。通过设置合理的内存使用阈值，系统可以：

1. **预防过载**：在问题发生前阻止它
2. **保持稳定**：维持可预测的性能
3. **优化资源**：在安全范围内最大化利用率
4. **提升体验**：减少极端延迟情况

准入控制与截断仿真的结合，为研究LLM服务系统在各种负载条件下的行为提供了强大工具。通过仔细的参数调优和策略选择，可以找到性能和稳定性的最佳平衡点。

## 附录：配置示例集

### A.1 轻负载场景
```yaml
admission_control:
  enabled: true
  threshold: 0.9  # 宽松阈值
```

### A.2 重负载场景
```yaml
admission_control:
  enabled: true
  threshold: 0.7  # 严格阈值
```

### A.3 突发负载场景
```yaml
admission_control:
  enabled: true
  threshold: 0.75  # 平衡阈值
```

### A.4 测试场景
```yaml
admission_control:
  enabled: true
  threshold: 0.5  # 极限测试
```