# Fluid ODE Simulation for LLM Serving

## 项目目标
在运筹学(Operations Research)框架下，对LLM服务的流体模型ODE进行仿真，验证流体极限(Fluid Limit)理论。

## 系统架构

### PD分离（Prefill-Decode Disaggregation）
- **Prefill阶段**：完全忽略，假设已在专用Prefill服务器完成
- **Decode阶段**：本仿真的核心关注点
- **到达过程**：请求直接以"准备decode"状态到达，带有prefill_length信息

### 请求状态定义
1. **WAITING（等待中）**: 
   - 预填充已完成，元数据已到达解码节点
   - 不占用GPU内存，仅在调度队列中
   - 对应流体模型中的Q(t)

2. **RUNNING（运行中）**: 
   - 调度器已分配GPU内存
   - KV缓存物理存在于GPU显存中
   - 对应流体模型中的X_i(t)，i为已解码步数

3. **SWAPPED（已交换）**: 
   - 因内存压力被抢占
   - KV缓存已复制到CPU，GPU内存已释放
   - 对应流体模型中的Z_i(t)

4. **COMPLETED（已完成）**: 
   - 解码完成，请求离开系统

### 内存模型
- **GPU内存占用** = Σ(所有RUNNING请求的(prefill_length + current_decode_position))
- **内存约束**：当GPU内存超过M_total时触发swap-out
- **Swap策略**：LIFO - 最晚进入RUNNING的请求优先被交换
- **批次构建优先级**：RUNNING（保持） > SWAPPED（恢复） > WAITING（新增）

## 仿真设计

### 时间模型
- **离散批次时间**：每批次执行完成为一个时间单位
- **批次执行时间**：`duration = d_0 + d_1 * B(t)`
  - B(t)：当前批次的总token数
  - d_0：基础执行时间
  - d_1：每token的边际执行时间
- **累积时间**：`t_{n+1} = t_n + duration_n`
- **无额外开销假设**：
  - 批次构建：瞬时完成
  - CPU-GPU交换：无延迟

### 输入数据格式
```csv
# requests.csv
arrival_time, prefill_length, decode_length
0.0, 50, 20
0.5, 100, 30
1.2, 75, 25
...
```
- arrival_time: 请求到达解码节点的时间（批次时间单位）
- prefill_length: 预填充KV缓存大小
- decode_length: 需要解码生成的token数

### 输出数据
系统生成多个CSV文件，使用统一的批次时间戳：
1. **batch_snapshots.csv**: 每批次的系统状态快照
2. **request_traces.csv**: 每个请求的完整轨迹
3. **memory_events.csv**: 内存管理事件日志
4. **queue_timeline.csv**: 队列状态时间序列

### 控制策略
- **队列策略**：FCFS（First-Come-First-Served）
- **Swap victim选择**：LIFO（基于进入RUNNING的时间）
- **批次构建**：严格优先级调度

## 流体ODE模型

### Swapping模式方程组
根据fluid_modeling.tex，系统演化遵循以下ODE：

```
dQ/dt = λ(t) - S_q(t)
dZ_i/dt = X_i(t)r_i(t)/(d_0+d_1*B(t)) - S_{Z,i}(t)  
dX_i/dt = [X_{i-1}(t)(1-r_{i-1}-q_{i-1}) - X_i(t)]/(d_0+d_1*B(t)) + S_q(t)p_i(t) + S_{Z,i}(t)
```

其中：
- **状态变量**：
  - Q(t): WAITING队列长度
  - X_i(t): RUNNING中解码位置为i的请求数
  - Z_i(t): SWAPPED中解码位置为i的请求数
- **控制变量**：
  - S_q(t): 从WAITING进入批次的速率
  - S_{Z,i}(t): 从SWAPPED恢复的速率
- **观测参数**：
  - p_i(t): 队列请求的解码位置分布
  - q_i(t): 完成概率
  - r_i(t): swap概率

### 参数估计
从离散仿真数据中提取：
- **p_i(t)**: 分析WAITING→RUNNING转换的请求分布
- **q_i(t)**: 统计各解码位置的完成事件
- **r_i(t)**: 统计各解码位置的swap事件

### 流体极限验证
通过缩放到达率λ，验证：
```
lim_{n→∞} X^(n)(t)/n → X(t)
```
其中X^(n)是缩放后的离散系统，X(t)是ODE解。

## 性能指标

### 请求级指标
- **端到端延迟**：completion_time - arrival_time
- **等待时间**：first_enter_running_time - arrival_time
- **执行时间**：completion_time - first_enter_running_time
- **Swap次数**：len(swap_events)
- **中断服务时间**：总的swapped状态时间

### 系统级指标
- **吞吐量**：
  - 请求吞吐：完成请求数/时间
  - Token吞吐：完成token数/时间
- **GPU内存利用率**：avg(gpu_memory_used/M_total)
- **队列长度统计**：mean, max, std
- **Swap频率**：swap事件数/时间

### 稳定性分析
- **队列稳定性**：队列长度是否有界
- **系统稳态**：各状态变量是否收敛
- **Little's Law验证**：L = λW

## 实验设计

### 基础实验
1. **单次仿真运行**：验证系统正确性
2. **指标收集**：生成性能报告

### 参数敏感性分析
1. **系统参数扫描**：
   - d_0, d_1: 计算能力
   - B: 批次预算
   - M_total: 系统内存
2. **负载变化**：
   - λ: 到达率
   - 请求长度分布

### 流体极限验证
1. **多尺度仿真**：λ × [1, 10, 100, 1000]
2. **ODE求解**：使用估计参数
3. **收敛性分析**：比较关键指标

### 控制策略比较
1. **不同队列策略**：FCFS vs Priority
2. **不同Swap策略**：LIFO vs LRU vs Random
3. **动态vs静态策略**

## 代码结构

### 核心模块
- **core/**: 基础数据结构（Request, SystemState）
- **simulation/**: 仿真引擎（VLLMSimulator）
- **control/**: 控制策略（Policy接口及实现）
- **fluid_model/**: ODE系统（方程、参数估计、求解）

### 分析工具
- **analysis/**: 性能指标计算、统计分析
- **visualization/**: 可视化（动态图、对比图）

### 实验脚本
- **experiments/**: 各类实验的执行脚本
- **data/**: 输入数据生成、输出数据存储

## 使用方法

### 快速开始
```bash
# 生成测试数据
python data/input/generate_requests.py

# 运行Swapping模式仿真
python experiments/run_swapping.py

# 验证流体极限
python experiments/validate_fluid_limit.py

# 生成可视化报告
python visualization/plot_dynamics.py
```

### 配置文件
编辑 `config/config.yaml` 调整系统参数：
```yaml
system:
  mode: "swapping"
  M_total: 10000
  B: 2000
  d_0: 1.0
  d_1: 0.001
```

## 扩展计划

### Sacrifice模式
当前为Sacrifice模式预留了接口，未来实现时需要：
1. 处理请求重置（decode_position归零）
2. 处理分布偏移问题
3. 实现对应的ODE系统

### 高级功能
1. 多节点仿真
2. 异构请求类型
3. 自适应控制策略
4. 在线学习优化

## 参考文献
- fluid_modeling.tex: 流体模型理论推导
- PagedAttention论文: 内存管理机制
- vLLM/SGLang: 实际系统实现参考

## 文档语言要求
- 所有 .md 文档必须使用中文编写
- 代码注释使用中文
- 可视化图表的标签、标题、图例使用英文（已在代码中实现）
- 日志输出和用户交互文本使用中文
- to memorize 回答问题使用中文