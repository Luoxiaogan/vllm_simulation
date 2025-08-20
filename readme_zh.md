# LLM服务流体ODE仿真系统

在运筹学框架下对LLM服务进行流体ODE建模的仿真系统。

## 快速开始

```bash
# 1. 生成测试数据
python data/input/generate_requests.py

# 2. 运行swapping模式仿真
python experiments/run_swapping.py  

# 3. 生成可视化图表
python visualization/plot_dynamics.py

# 或使用一键脚本
bash scripts/run_basic.sh
```

## 系统参数

### 核心系统配置（`config/config.yaml`）

#### 系统参数
- **`mode`** (字符串): 服务器模式 - `"swapping"` 或 `"sacrifice"`（目前仅实现swapping）
- **`M_total`** (整数): GPU总内存（token数）（默认：10000）
  - 控制何时触发交换
  - 更大的值减少交换但可能影响批次大小
- **`B`** (整数): 最大批次token预算（默认：2000）
  - 单个批次处理的token上限
  - 影响吞吐量与延迟的权衡
- **`d_0`** (浮点数): 批次基础执行时间（默认：1.0）
  - 每批次固定开销，与大小无关
- **`d_1`** (浮点数): 每token执行时间系数（默认：0.001）
  - 每个token的边际时间成本
  - 总批次时间 = d_0 + d_1 * 批次大小

#### 控制策略参数
- **`queue_policy`** (字符串): 队列调度策略
  - `"FCFS"`: 先来先服务（默认）
  - `"priority"`: 基于优先级的调度（未来）
- **`victim_policy`** (字符串): 交换牺牲者选择策略
  - `"LIFO"`: 基于enter_running_time的后进先出（默认）
  - `"FIFO"`: 先进先出
  - `"random"`: 随机选择
  - `"LRU"`: 最近最少使用（未来）
- **`batch_priority`** (字符串): 批次构建优先级
  - `"standard"`: RUNNING > SWAPPED > WAITING（默认）

#### 数据配置
- **`request_file`** (字符串): 输入请求CSV文件路径
- **`output_dir`** (字符串): 结果输出目录
- **`L_filter`** (整数/null): 最大解码长度过滤器（null = 不过滤）

#### 实验配置
- **`seed`** (整数): 随机种子用于可重现性（默认：42）
- **`verbose`** (布尔值): 启用详细日志（默认：true）
- **`progress_interval`** (整数): 进度报告间隔（批次数）（默认：100）

### 请求生成参数

使用 `data/input/generate_requests.py` 时：

- **`--num_requests`** (整数): 生成的请求数量（默认：100）
- **`--arrival_rate`** (浮点数): 平均到达率（请求/时间单位）（默认：0.5）
- **`--scenario`** (字符串): 负载场景类型
  - `"normal"`: 标准负载，混合请求长度
  - `"heavy"`: 高到达率（2.0），更长的请求
  - `"bursty"`: 突发模式，有密集负载期
- **`--output`** (字符串): 输出文件名（默认："requests.csv"）

#### 请求分布（Normal场景）
- 80% 短请求：
  - prefill_length: 10-60 tokens
  - decode_length: 10-40 tokens
- 20% 长请求：
  - prefill_length: 150-200 tokens
  - decode_length: 80-100 tokens

## 输出文件

所有输出文件保存在 `data/output/` 目录：

### 1. **batch_snapshots.csv**
每次批次执行后的系统状态：
- `time`: 累积仿真时间
- `batch_id`: 唯一批次标识符
- `batch_size`: 批次中的请求数
- `batch_tokens`: 批次中的总token数
- `batch_duration`: 该批次的执行时间
- `waiting_count`: 等待队列中的请求
- `running_count`: 当前运行的请求
- `swapped_count`: 交换到CPU的请求
- `completed_count`: 总完成请求数
- `gpu_memory_used`: 当前GPU内存使用
- `memory_utilization`: GPU内存利用率

### 2. **request_traces.csv**
每个请求的完整生命周期轨迹：
- `req_id`: 唯一请求标识符
- `arrival_time`: 请求到达解码节点的时间
- `prefill_length`: 预填充KV缓存大小
- `decode_length`: 要解码的token数
- `completion_time`: 请求完成时间（未完成则为NaN）
- `first_enter_running_time`: 首次进入RUNNING状态时间
- `waiting_time`: 在WAITING状态花费的时间
- `execution_time`: 在RUNNING状态的总时间
- `swap_count`: 被交换出的次数
- `total_delay`: 端到端延迟

### 3. **events.csv**
详细事件日志：
- `time`: 事件时间戳
- `event_type`: 事件类型（admit, swap_out, swap_in, complete）
- `req_id`: 涉及的请求
- `details`: 额外事件信息

### 4. **memory_events.csv**
内存管理事件：
- `time`: 事件时间戳
- `event_type`: swap_out 或 swap_in
- `req_id`: 被交换的请求
- `memory_before`: 事件前的GPU内存
- `memory_after`: 事件后的GPU内存
- `reason`: 交换发生的原因

### 5. **summary.txt**
人类可读的汇总报告，包括：
- 基本统计（总时间、批次、完成数）
- 系统统计（队列长度、交换次数）
- 性能指标（吞吐量、延迟、利用率）

## 使用示例

### 基础仿真
```bash
# 生成标准负载并运行仿真
python data/input/generate_requests.py --num_requests 100
python experiments/run_swapping.py
python visualization/plot_dynamics.py
```

### 高负载测试
```bash
# 生成高负载场景
python data/input/generate_requests.py --scenario heavy --num_requests 200
python experiments/run_swapping.py --requests data/input/requests.csv
```

### 参数调优
```bash
# 编辑 config/config.yaml 修改参数，然后运行：
python experiments/run_swapping.py --config config/config.yaml
```

### 批量实验
```bash
# 运行不同参数的实验
bash scripts/run_experiments.sh

# 比较不同场景
bash scripts/run_scenarios.sh

# 完整流程与清理
bash scripts/run_full_pipeline.sh
```

## Shell脚本

位于 `scripts/` 目录：

- **`run_basic.sh`**: 标准工作流（生成 → 仿真 → 可视化）
- **`run_experiments.sh`**: 参数扫描实验
- **`run_scenarios.sh`**: 比较normal/heavy/bursty场景
- **`run_full_pipeline.sh`**: 完整流程与所有分析
- **`clean.sh`**: 清理输出目录

所有脚本支持通过直接编辑脚本文件修改参数。

## 可视化

`visualization/plot_dynamics.py` 脚本生成两个主要图表：

1. **system_dynamics.png**: 6面板系统指标随时间变化
   - 队列状态（等待/运行/交换）
   - GPU内存使用
   - 内存利用率百分比
   - 批次执行时间
   - 累积完成数
   - 吞吐量（移动平均）

2. **request_timeline.png**: 甘特图样式显示：
   - 请求生命周期（蓝色为等待时间，绿色为执行）
   - 交换事件标记为"S:n"标签
   - 为清晰起见采样20个请求

## 高级配置

### 自定义请求模式
创建具有特定模式的自定义请求文件：
```python
# 在Python脚本或notebook中
import csv

requests = [
    {"arrival_time": 0.0, "prefill_length": 100, "decode_length": 50},
    {"arrival_time": 0.5, "prefill_length": 150, "decode_length": 30},
    # ... 更多请求
]

with open("custom_requests.csv", "w") as f:
    writer = csv.DictWriter(f, fieldnames=["arrival_time", "prefill_length", "decode_length"])
    writer.writeheader()
    writer.writerows(requests)
```

### 修改控制策略
编辑 `control/default_policy.py` 实现自定义调度或交换策略。

### 分析结果
使用pandas分析CSV输出：
```python
import pandas as pd

# 找到最新的实验目录
import glob
import os

exp_dirs = glob.glob("data/experiments/experiment_*")
latest_exp = max(exp_dirs, key=os.path.getmtime)

# 加载并分析结果
traces = pd.read_csv(f"{latest_exp}/request_traces.csv")
print(f"平均延迟: {traces['total_delay'].mean():.2f}")
print(f"P95延迟: {traces['total_delay'].quantile(0.95):.2f}")
print(f"交换率: {(traces['swap_count'] > 0).mean():.2%}")
```

### 实验管理
使用实验管理工具：
```bash
# 列出所有实验
./scripts/manage_experiments.sh list

# 查看实验详情
./scripts/manage_experiments.sh details experiment_20241215_143022_1234

# 比较两个实验
./scripts/manage_experiments.sh compare experiment_1 experiment_2

# 归档旧实验（超过7天）
./scripts/manage_experiments.sh archive 7

# 导出实验数据
./scripts/manage_experiments.sh export experiment_name output.tar.gz
```

## 项目结构

```
fluid_ode_simulation/
├── config/              # 配置文件
│   └── config.yaml     # 主配置
├── core/               # 核心数据结构
│   ├── request.py      # Request类
│   └── system_state.py # 系统状态管理
├── simulation/         # 仿真引擎
│   ├── vllm_simulator.py      # 主仿真器（支持swap和sacrifice模式）
│   └── event_logger.py        # 事件日志
├── control/            # 控制策略
│   └── default_policy.py      # FCFS + LIFO策略
├── data/              
│   ├── input/         # 输入数据生成
│   │   └── generate_requests.py
│   ├── experiments/   # 实验结果目录
│   │   └── experiment_*  # 带时间戳的实验目录
│   └── output/        # 旧输出目录（已废弃）
├── experiments/        # 实验脚本
│   └── run_swapping.py
├── visualization/      # 绘图工具
│   └── plot_dynamics.py
├── scripts/           # 自动化Shell脚本
│   ├── run_basic.sh   # 基础运行脚本
│   ├── run_experiments.sh  # 参数扫描实验
│   ├── run_scenarios.sh    # 场景比较
│   ├── run_full_pipeline.sh # 完整流水线
│   ├── manage_experiments.sh # 实验管理工具
│   └── clean.sh        # 清理脚本
└── CLAUDE.md          # 详细技术文档
```

## 故障排除

### 常见问题

1. **负等待时间**: 当前版本已修复 - 请求现在正确等待其到达时间

2. **无swap_in事件**: 已修复 - swap恢复机制现已正常工作

3. **内存溢出**: 减少配置中的`B`参数或增加`M_total`

4. **仿真缓慢**: 减少请求数量或增加到达间隔

### 性能提示

- 对于大规模实验，禁用verbose输出
- 使用二分搜索进行参数调优
- 监控`data/experiments/*/summary.txt`获取快速指标
- 使用`manage_experiments.sh stats`查看总体统计
- 调整`progress_interval`减少更新频率

## 参考文献

- **CLAUDE.md**: 完整技术文档与ODE方程
- **fluid_modeling.tex**: 理论流体模型推导
- 相关论文: PagedAttention, vLLM, SGLang

## 许可证

本项目用于研究和教育目的。