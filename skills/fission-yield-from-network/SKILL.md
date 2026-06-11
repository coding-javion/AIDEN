---
name: fission-yield-from-network
description: 当需要处理核裂变产额数据时使用此 skill，包括读取模型/理论数据、评价数据、实验数据和 ML 预测结果；使用 MinMaxScaler 进行归一化/反归一化；绘制质量/电荷产额分布；以及生成多模型对比图。当用户提到 fission yields、mass yield distribution、charge distribution、evaluated nuclear data、scaler files (.pkl)，或要求绘制出版质量的核数据图时触发。不要假设文件名或目录结构，始终先请用户说明哪些数据对应哪些用途。
---

# 核裂变产额数据处理

## 核心原则

这个 skill 只负责指导核裂变产额数据的处理流程。能固化的 Python 代码已经提取到 `scripts/fission_yield_tools.py`；`SKILL.md` 只保留不能自动化、必须由用户或当前项目上下文决定的部分。

使用此 skill 时，优先导入脚本中的工具函数，而不是在回答里重写大段数据处理代码：

```python
from scripts.fission_yield_tools import (
    load_result_txt,
    find_and_load_scalers,
    inverse_transform_dataframe,
    add_integer_za,
    sum_by,
)
```

如果脚本不能覆盖用户的特殊数据格式，再基于脚本扩展，而不是复制粘贴新的零散代码。

## 必须先问用户的问题

不要假设文件名、目录结构、单位、列含义，也不要假设哪个数据是“模型”或“实验”。加载数据前先确认：

| 问题 | 示例回答 |
|----------|---------------|
| 哪些文件/目录包含理论或模型数据？ | “模型数据在 `model_output/`” |
| 哪些文件/目录包含实验或评价数据？ | “实验数据在 `exfor/`，评价数据在 `endf/`” |
| 列名或列位置如何映射？ | “文件使用 `Z, A, Energy, FY, DFY`” 或 “无表头，共 6 列” |
| 哪个数据作为归一化参考？ | “用 GEF 文件拟合 scalers，再应用到 EXFOR” |
| `.pkl` scaler 文件在哪里？ | “在 `output/scalers/`” 或 “没有，请从模型数据生成” |
| ML 预测文件是哪几个？ | “`result2_44.txt`，可能是 6 或 7 列” |
| Yield 单位是什么？ | “模型是绝对产额，评价库是百分比，实验数据需要 /1000” |
| 数据是否覆盖完整裂变产物 Z/A 范围？ | “覆盖完整范围，可以做 mass yield；只是一条质量链，不要聚合” |

## 如果找不到 scaler 文件

当搜索 `*scaler*.pkl` 没有结果时，告诉用户：

> “我没有找到任何 scaler 文件。要继续有两个选择：
> 1. **提供 scaler**：请指出包含 `standard_scalerZ.pkl`、`standard_scalerA.pkl`、`standard_scalerE.pkl` 和 `yield_scaler.pkl` 的目录（命名可能不同）。
> 2. **生成 scaler**：请提供原始模型/理论数据文件，我会先执行 Phase 1 归一化，从头拟合 scalers。”

没有 scalers 时，已经归一化的数据不能可靠地转换回物理单位。Phase 2（把统一尺度应用到实验/评价数据）也需要 scalers。如果用户只有原始数据，先运行 Phase 1，生成后续步骤需要的 `.pkl` 文件。

## 数据角色与常见命名

核裂变产额数据通常是 `(Z, A, State/Energy, Yield, Uncertainty)` 形式的表格记录，但项目之间差异很大。下面只是线索，不可作为最终判断：

| 来源 | 可能叫法 | 常见文件名模式（仅示例） |
|--------|--------------|------------------------------------------|
| 理论模型 | “model”, “calculated”, “theory” | `IND_En=...`, `*-IC.csv` |
| 评价数据库 | “ENDF”, “evaluated”, “reference” | `endf.csv`, `evaluated_*.csv` |
| 实验数据库 | “EXFOR”, “experiment”, “measured” | `exfor_*.csv`, `data.csv` |
| ML 预测 | “predictions”, “result”, “output” | `result*.txt` |

常见结构线索：

- 与 `*scaler*.pkl` 位于同一目录的文件，可能已经归一化。
- `IND_` 前缀的文件通常是 GEF code 理论输出。
- `-IC.csv` 后缀的文件通常是 Zp model 输出。
- 文件名含 `endf` / `exfor`，通常对应评价/实验数据。

发现文件后，按候选类型分组展示给用户，并请用户确认哪些是理论/模型数据、实验/评价数据、ML 预测结果和 scaler 文件。

## 推荐脚本用法

脚本位置：`scripts/fission_yield_tools.py`

可复用函数：

| 需求 | 函数 |
|-----------|------------|
| 读取 6 列带 index 的空格分隔 TXT | `load_indexed_txt()` |
| 读取 CSV，包含有表头或无表头场景 | `load_csv()` |
| 读取 6/7 列 ML prediction result TXT | `load_result_txt()` |
| 批量加载并合并多个文件 | `load_many()` |
| 在参考数据上拟合 MinMaxScaler | `fit_minmax_scalers()` |
| 保存 scalers 为常见 `.pkl` 命名 | `save_scalers()` |
| 自动发现并加载 scaler 文件 | `find_and_load_scalers()` |
| 检查 scaler 的 data range 和 feature range | `scaler_summary()` |
| 对实验/评价数据应用已有 scalers | `transform_dataframe()` |
| 将归一化结果反变换到物理范围 | `inverse_transform_dataframe()` |
| 反归一化后添加整数 `Z` / `A` 列 | `add_integer_za()` |
| 聚合单个核素产额 | `nuclide_yields()` |
| 按 A 或 Z 求和 | `sum_by()` |
| 传播非对称 CI 不确定度 | `propagate_ci_uncertainty()` |
| 传播对称 error | `propagate_symmetric_error()` |
| 对关键训练点做重复加权 | `augment_training_weight()` |
| 多模型或参考数据 outer merge | `merge_on_key()` |

## 标准工作流

### Phase 1：拟合归一化参考

适用于用户提供原始理论/模型数据、且没有可用 scalers 的情况。

1. 让用户确认哪些数据是归一化参考。
2. 根据实际格式选择 `load_indexed_txt()`、`load_csv()` 或 `load_many()`。
3. 用 `fit_minmax_scalers()` 拟合 Z、A、State/Energy、Yield 的 scalers。
4. 用 `transform_dataframe()` 变换参考数据。
5. 用 `save_scalers()` 保存 `.pkl`，供后续 Phase 2 和反归一化使用。

### Phase 2：应用统一尺度

适用于实验/评价数据需要变换到参考模型尺度的情况。

1. 让用户确认 scaler 来源和目标数据来源。
2. 用 `find_and_load_scalers()` 加载 scalers。
3. 用 `scaler_summary()` 检查数据范围是否合理。
4. 用 `transform_dataframe()` 只 transform，不重新 fit。

### 反归一化 ML 预测结果

适用于 `result*.txt` 之类已经归一化的 ML 预测输出。

1. 用 `load_result_txt()` 自动处理 6/7 列结果文件。
2. 用 `find_and_load_scalers()` 加载用户确认的 scalers。
3. 用 `inverse_transform_dataframe()` 反归一化 `z`、`a`、`state`、`results` 和 CI。
4. 用 `add_integer_za()` 添加整数 `Z` / `A`。
5. 如果数据覆盖完整 Z/A 范围，再用 `sum_by(df, "A")` 或 `sum_by(df, "Z")` 做质量/电荷产额；否则只做局部核素分析。

## 文件发现策略

先问用户在哪里搜索、用什么关键词。只有用户没有明确路径时，才进行引导式搜索。可用命令模式如下：

- 模型/理论/实验候选文件：在用户指定目录下查找 `.csv` 和 `.txt`。
- Scaler 文件：查找 `*scaler*.pkl`。
- 用户提供命名模式时，直接使用该模式，不做宽泛搜索。

搜索结果必须交给用户分类确认。不要只凭文件名决定数据角色。

## Scaler 命名约定

不同项目可能命名不同，常见有两类：

| Pattern A（分离 scaler） | Pattern B（合并 scaler） | 缩放对象 |
|---|---|---|
| `*scalerZ*.pkl` | （包含在 combined 中） | Z（质子数） |
| `*scalerA*.pkl` | （包含在 combined 中） | A（质量数） |
| `*scalerE*.pkl` | — | State/Energy |
| `yield_scaler*.pkl` | `yield_scaler*.pkl` | Yield |
| — | `standard_scaler*.pkl` | 合并的 Z+A |

`find_and_load_scalers()` 支持这些常见模式。如果只有合并的 `standard_scaler.pkl`，可同时用于 Z 和 A。但仍必须确认这个 scaler 是用哪个数据集拟合的。

## 绘图指导

绘图不再在 `SKILL.md` 中保留大段固定代码。生成图时根据用户目标临时组合脚本输出的数据表，并遵守以下约定：

- 质量产额图：先确认数据覆盖完整或近完整 Z/A 范围；曲线使用 `plot()`，CI 用 `fill_between()`，实验点用 `errorbar()`。
- 能量序列图：按 `state` 或实际 incident neutron energy 分组，使用连续 colormap；参考数据可用虚线叠加。
- 电荷分布子图：先筛选有足够实验点或模型点的 Z，再按 A 展示。
- 单核素图：对指定 `(Z, A)` 展示 Yield vs State/Energy；CI band 可选。
- CI 宽度图：使用 `95%CI - 5%CI` 比较模型不确定度。
- 出版图默认建议：`figsize=(11, 6)`、`dpi=320`、Times New Roman、加粗轴标签、无边框图例、开启 minor ticks。

如果用户要求脚本化绘图，再新增专门的绘图脚本；不要把长绘图代码塞回 `SKILL.md`。

## 常见陷阱

- **State 列含义因来源而异**：理论模型数据常把 State 编码为能量索引（例如 0-14）。实验/评价数据常使用实际入射中子能量（MeV）。必须询问用户采用哪种约定。
- **Error/uncertainty 列约定不同**：有些数据有非对称 CI 边界（`5%CI`, `95%CI`），有些只有一个对称误差列。运行分析前先检查实际列。
- **7 列 result 文件**：某些模型输出中第 5 列（索引 4）是冗余列。使用 `load_result_txt()` 自动检测。
- **Scaler 来源至关重要**：在某个数据集上拟合的 scaler 如果应用到另一个数据集，会得到错误物理值。必须询问哪个 scaler 目录对应哪个数据。
- **Yield 单位**：模型输出通常是绝对产额。评价数据可能是百分比。实验数据在反归一化后有时还需要额外缩放。必须向用户确认单位。
- **局部覆盖数据不要做全局聚合**：如果数据只覆盖单条质量链或窄 Z 范围，不要计算 mass yield 或 charge yield 分布。这类求和不代表物理意义上的总产额。
- **分组前先四舍五入 Z/A**：反归一化后 Z 和 A 是浮点数。筛选或分组前使用 `add_integer_za()` 或等价的 `.round().astype(int)`。
- **工作目录很重要**：脚本函数不会猜测路径。使用用户确认的绝对路径或先切换到正确目录。
