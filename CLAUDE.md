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
- **内存约束**：当GPU内存超过M_total时触发抢占
- **执行批次**：从RUNNING中选择子集，受B（token预算）约束
- **RUNNING ≠ 执行中**：RUNNING表示占用GPU内存，执行批次是其子集

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

### 输出数据文件

系统生成8个文件，保存在带时间戳的实验目录中：

#### 1. batch_snapshots.csv - 批次级快照
| 列名 | 含义 |
|------|------|
| time | 批次执行开始时间 |
| batch_id | 批次编号 |
| batch_count | 实际执行的请求数（受B约束） |
| batch_tokens | 执行批次的总token数 |
| running_count | GPU内存中的所有请求数 |
| waiting_count | 等待队列大小 |
| swapped_count | 被交换到CPU的请求数 |
| gpu_memory_used | GPU内存使用量 |
| memory_utilization | 内存利用率 |
| batch_duration | 批次执行时间 |
| completed_count | 累计完成数 |
| batch_sacrifice_count | 本批次sacrifice数量 |

#### 2. request_traces.csv - 请求级轨迹
| 列名 | 含义 |
|------|------|
| req_id | 请求ID |
| arrival_time | 到达时间 |
| prefill_length | 预填充长度 |
| decode_length | 解码长度 |
| completion_time | 完成时间 |
| total_delay | 端到端延迟 |
| waiting_time | 等待时间 |
| execution_time | 执行时间 |
| swap_count | 交换次数 |
| total_swapped_time | 总交换时间 |
| sacrifice_count | 牺牲次数 |

#### 3. events.csv - 事件日志
记录arrival、completion、swap_out、swap_in等所有事件

#### 4. queue_timeline.csv - 队列时间线
记录各队列在每个时间点的成员

#### 5. memory_events.csv - 内存事件
专门追踪内存相关的变化和抢占事件

#### 6. summary.txt - 汇总报告
包含基本信息、系统统计、性能指标等

#### 7. config_used.yaml - 配置快照
保存实验使用的完整配置

#### 8. experiment_meta.yaml - 实验元数据
记录实验时间、路径、策略等元信息

#### 9. sacrifice_snapshot.csv - Sacrifice事件详情（仅sacrifice模式）
| 列名 | 含义 |
|------|------|
| time | sacrifice发生时间 |
| req_id | 被sacrifice的请求ID |
| current_decode_position | sacrifice时的解码位置 |
| memory_freed | 释放的内存量 |
| running_count_same_position | 同位置的running请求数 |
| total_running_count | running队列总请求数 |

#### 10. sacrifice_distribution.csv - Sacrifice概率分布（仅sacrifice模式）
宽格式矩阵，每行代表一个sacrifice事件，列为各decode_position的累积概率分布

#### 11. sacrifice_conditional_prob_timeline.csv - 条件概率时间序列（仅sacrifice模式）
宽格式矩阵，记录P(sacrifice|position,time)的时间演化

### 控制策略组合

系统支持4种策略组合：(swap/sacrifice) × (conservative/aggressive)

#### 抢占模式（Preemption Mode）
- **swap**: 保留KV缓存和解码进度，交换到CPU内存
- **sacrifice**: 清除KV缓存，重置解码进度到0

#### 抢占策略（Preemption Strategy）
- **conservative**: 保守策略，仅在内存增长阶段必要时抢占
- **aggressive**: 激进策略，为高优先级请求主动抢占

#### 4种组合特点
1. **swap + conservative**: 最稳定，适合长请求和稳定负载
2. **swap + aggressive**: vLLM默认，平衡性能和公平性  
3. **sacrifice + conservative**: 简单高效，适合短请求
4. **sacrifice + aggressive**: 最激进，优先级严格，适合突发负载

#### 调度器实现（vLLM对齐）
系统实现了与vLLM一致的三阶段调度：
1. **Phase 1 - Prefill（准入）**: 从WAITING/SWAPPED队列准入请求，不触发抢占
2. **Phase 2 - Running（内存压力处理）**: 批量处理内存压力，选择victims进行抢占
3. **Phase 3 - Queue Update（队列更新）**: 将被抢占的请求批量加入相应队列

关键设计决策：
- **B约束仅在执行时应用**：准入阶段不检查B约束，只在select_execution_batch时应用
- **批量内存压力处理**：PD分离场景下，批量处理效率更高
- **LIFO victim选择**：基于enter_running_times选择最晚进入的请求

#### 其他策略参数
- **队列调度**: FCFS（First-Come-First-Served）
- **Victim选择**: LIFO（基于enter_running_times，最晚进入RUNNING的优先被抢占）
- **准入优先级**: 
  - Aggressive模式：SWAPPED > WAITING（严格优先级）
  - Conservative模式：优先恢复但不抢占

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
- **Sacrifice次数**：len(sacrifice_events)
- **中断服务时间**：总的swapped状态时间

### 系统级指标
- **吞吐量**：
  - 请求吞吐：完成请求数/时间
  - Token吞吐：完成token数/时间
- **GPU内存利用率**：avg(gpu_memory_used/M_total)
- **队列长度统计**：mean, max, std
- **Swap频率**：swap事件数/时间
- **Sacrifice频率**：sacrifice事件数/时间

### Sacrifice模式专有指标
- **条件概率P(sacrifice|position)**：给定decode位置被sacrifice的概率
- **位置分布**：各decode位置被sacrifice的频次
- **浪费token数**：因sacrifice而重新计算的token总量

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
- **core/**: 基础数据结构
  - request.py: Request类，包含SwapEvent和SacrificeEvent
  - system_state.py: 系统状态，管理WAITING/RUNNING/SWAPPED三个队列
  - constants.py: 系统常量定义
- **simulation/**: 仿真引擎
  - vllm_simulator.py: 统一仿真器，支持所有策略组合
  - base_simulator.py: 仿真器基类
  - event_logger.py: 事件记录和CSV输出，生成11种CSV文件
- **control/**: 控制策略
  - advanced_policy.py: vLLM对齐的三阶段调度器，实现4种策略组合
  - base_policy.py: 策略基类
- **fluid_model/**: ODE系统（方程、参数估计、求解）

### 分析工具
- **analysis/**: 性能指标计算、统计分析
- **visualization/**: 可视化工具
  - draw.py: 绘制队列动态、sacrifice动态、条件概率等图表

### 实验脚本
- **experiments/**: 各类实验的执行脚本
  - run_advanced.py: 运行单次仿真并生成可视化
  - test_all_strategies.py: 测试所有4种策略组合
- **data/**: 数据目录
  - input/: 输入数据和生成脚本
    - generate.sh: 一键生成测试数据
    - generate_requests.py: 请求生成器
  - experiments/: 实验结果存储（带时间戳目录）

## 使用方法

### 快速开始
```bash
# 生成测试数据（一键生成所有配置）
bash data/input/generate.sh

# 运行高级策略仿真（使用默认配置）
python experiments/run_advanced.py

# 使用特定配置
python experiments/run_advanced.py --config config/config.yaml

# 命令行指定策略组合
python experiments/run_advanced.py --mode swap --strategy aggressive

# 测试所有4种策略组合
python experiments/test_all_strategies.py

# 直接查看生成的PNG图片（在实验目录下）
# - queue_dynamics.png: 队列动态和内存使用
# - sacrifice_dynamics.png: sacrifice事件分析（仅sacrifice模式）
```

### 配置文件
编辑 `config/config.yaml` 调整系统参数：
```yaml
system:
  M_total: 10000        # GPU内存容量
  B: 2000              # 批次token预算
  d_0: 1.0             # 基础执行时间
  d_1: 0.001           # 每token边际时间

control:
  preemption_mode: swap          # swap或sacrifice
  preemption_strategy: conservative  # conservative或aggressive
  allow_waiting_preempt: false   # WAITING是否可触发抢占
  queue_policy: FCFS
  victim_policy: LIFO

data:
  request_file: data/input/requests.csv
  experiments_dir: data/experiments
  L_filter: null       # 最大解码长度过滤

experiment:
  seed: 42
  verbose: true
  progress_interval: 100
```

## 可视化输出

系统自动生成两种主要可视化图表：

### 1. queue_dynamics.png - 队列动态图（2子图）
- **上图**：队列大小变化（WAITING、RUNNING、Sacrifice事件）
- **下图**：内存和Token使用情况（GPU Memory、Batch Tokens）

### 2. sacrifice_dynamics.png - Sacrifice分析图（3子图，仅sacrifice模式）
- **上图**：双轴图 - Sacrifice事件频次和累计浪费tokens
- **中图**：各decode位置的累积概率分布随时间演化
- **下图**：条件概率P(sacrifice|position,time)的时间序列

### 3. arrival_dynamics.png - 到达动态图（2子图）
- **上图**：累积到达 - External Arrival、Internal Arrival (Sacrifice)、Completion
- **下图**：增量到达率（每个时间窗口）- 显示三条线的速率变化
- **时间间隔**：基于系统批次时间 interval = ws×(d_0 + d_1×B_max)，统一时间窗口便于对比
- **标记线**：
  - 红色虚线：候选截断点（explore模式）或截断点（truncate模式）
  - 黑色虚线：Arrival End（外部到达结束）
  - 绿色虚线：Simulation End（仿真结束）

## 截断仿真模式

### 探索模式（Explore Mode）
用于完整运行仿真并标记候选截断点：
```bash
python experiments/run_with_truncation.py --config config/explore_truncation.yaml --mode explore
```
- 生成初始请求（高到达率）
- 完整运行仿真
- 在图上用红色虚线标记候选截断点
- 保存完整的CSV文件和可视化

### 截断模式（Truncate Mode）
在指定批次截断并注入新请求：
```bash
python experiments/run_with_truncation.py --config config/apply_truncation.yaml --mode truncate
```
- 运行到截断点（如batch_3350）
- 丢弃未到达的请求
- 生成新请求（不同到达率）
- 继续仿真至完成
- 在arrival_dynamics图中清楚显示到达率变化

### 关键实现细节

#### 1. VLLMSimulatorWithTruncation
- 继承自VLLMSimulator，不完全重写run方法
- 在指定batch_id执行截断
- 保存phase1和phase2的统计信息
- 使用EventLogger保存完整CSV输出

#### 2. 可视化标题增强
- **探索模式**：显示理论和实际到达率
- **截断模式**：分phase显示统计信息
  - Phase 1 (t=0-截断时间): 原始请求统计
  - Phase 2 (t=截断时间-结束): 新请求统计
  - Overall Stats: 总体统计

#### 3. Arrival Dynamics可视化
- **External Arrival**：从request_traces.csv读取，显示实际外部到达
- **Internal Arrival**：从sacrifice_snapshot.csv读取，显示sacrifice产生的内部到达
- **Completion**：显示请求完成率，最终与external arrival相等
- **固定时间窗口**：使用系统批次时间的倍数，确保两条线可比
- **时间范围**：延续到仿真结束，不在arrival_end停止

## 扩展计划

### 已实现功能
1. **完整的Sacrifice模式**：重置进度、高优先级重新调度
2. **vLLM对齐的三阶段调度器**：Prefill、Running、Queue Update
3. **详细的sacrifice事件追踪**：包含上下文信息的条件概率分析
4. **批量内存压力处理**：优化PD分离场景

### 待实现功能
1. 多节点仿真
2. 异构请求类型
3. 自适应控制策略
4. 在线学习优化
5. 流体ODE求解器集成

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
- GIT_SSH_COMMAND="ssh -i ~/.ssh/github_key" git push.