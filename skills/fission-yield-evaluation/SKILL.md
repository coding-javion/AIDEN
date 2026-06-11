---
name: fission-yield-evaluation
description: Use when auditing theoretical or experimental fission product yield data for physical plausibility, including FPY/IFY/CFY, mass yields, isotope yields, isomeric ratios, charge distributions, prompt-neutron effects, energy trends, covariance checks, and comparison with evaluated nuclear-data libraries.
---

# 裂变产额评价审计

用于审计理论或实验裂变产物产额数据是否物理合理。输出必须是证据支撑的检查清单，不要给出模糊判断。

## 工作原则

- 默认只读：不要修改输入数据集，不要删除、移动或重命名源文件。
- 先判定适用域，再判定对错。缺少关键元数据时，对相关检查标注 `INSUFFICIENT_METADATA`。
- 始终区分 `Y(A)`、`Y(Z)`、`Y(A,Z)`、`Y(A,Z,I)`，以及独立产额、累积产额、中子发射前一次碎片产额、中子发射后产物产额。
- 不要把累积同位素产额直接求和后要求等于 `2.0` 或 `200`，这会重复计数衰变链馈入。
- Bash 只用于安全检查、读取文件和确定性分析脚本。不要运行破坏性命令，不要安装依赖，除非用户明确要求。

## 快速流程

1. 读取数据说明、表头和少量样本行，确认文件格式与字段含义。
2. 按“元数据门槛”列出裂变体系、入射道、能量、产额阶段、产额类型、归一化、完整性和不确定度信息。
3. 运行可复现数值检查。优先使用：

```bash
python3 .agents/skills/fission-yield-evaluation/scripts/fpy_basic_audit.py <data-file>
```

4. 根据数据类型读取详细规则：
   - 物理规则、适用域、状态逻辑：`references/physics_rules.md`
   - 最终回答结构：`references/report_template.md`
5. 对每条规则给出 `PASS`、`WARN`、`FAIL`、`NA`、`INFO`、`BLOCKER` 或 `INSUFFICIENT_METADATA`。
6. 最终结论要保守：区分硬错误、强警告、适用域外规则、需要用户补充的元数据。

## 元数据门槛

审计前必须尽量识别：

- 裂变体系或复合核：`Z_F`、`A_F`，例如 U-235(n_th,f) 对应复合核 U-236。
- 入射道：自发裂变、热中子、快中子、带电粒子、光裂变、重离子或其他。
- 入射能量或激发能：`E_n`、`E*`、能量分箱或谱平均。
- 产额阶段：中子发射前一次碎片、中子发射后产物或不清楚。
- 产额类型：独立、累积、质量链、元素、同位素或同质异能态。
- 归一化：每次裂变分数、每 100 次裂变百分数、任意归一化或部分测量子集。
- 完整性：完整分布、部分质量范围、选定产物、阈值筛选产物或未知。
- 不确定度：是否有不确定度、协方差或二者皆无。

## 确定性脚本

`scripts/fpy_basic_audit.py` 是标准库 Python 脚本，可检查：

- 多种输入格式：CSV、TSV、空白分隔表、JSON、JSONL，以及轻量 ENDF-6 MF=8 MT=454/459 FPY LIST 记录；
- 产额是否有限、非负；
- 不确定度是否有限、非负；
- 主要产额的相对不确定度是否异常；
- 完整独立分布的总归一化是否接近 `2.0` 或 `200`；
- 可选协方差矩阵是否对称、对角非负，并用 Jacobi 迭代估计最小特征值。

脚本采用单入口、多 reader 的格式适配层：先把不同原始格式规范化为内部表格记录，再运行同一套数值检查。默认使用 `--input-format auto` 自动识别；识别失败或表头不标准时，显式传入 `--input-format`、`--yield-col`、`--uncertainty-col`、`--a-col`、`--z-col` 或 `--nuclide-col`。

常用示例：

```bash
python3 .agents/skills/fission-yield-evaluation/scripts/fpy_basic_audit.py yields.csv --yield-col yield --uncertainty-col dy
python3 .agents/skills/fission-yield-evaluation/scripts/fpy_basic_audit.py yields.tsv --delimiter tab --complete-independent --yield-scale percent
python3 .agents/skills/fission-yield-evaluation/scripts/fpy_basic_audit.py yields.jsonl --input-format jsonl
python3 .agents/skills/fission-yield-evaluation/scripts/fpy_basic_audit.py endfb8_fpy.endf --input-format endf6-fpy --format json
python3 .agents/skills/fission-yield-evaluation/scripts/fpy_basic_audit.py yields.csv --covariance cov.csv --format json
```

脚本结果只是数值证据，不替代物理适用域判断。

## 最终回答要求

- 先给总体判定，再给检查清单。
- 每条发现必须包含状态、依据、适用域说明和证据。
- 对 `FAIL` 和 `WARN` 给出可复查的数值、行号、质量数/电荷数范围或文件位置。
- 对无法判断的规则说明缺少哪些元数据。
- 如引用本地评价库、脚本输出或项目文件，要写明路径。
