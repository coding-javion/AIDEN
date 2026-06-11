# Fission Yield Demo

这个目录是一个用于演示 **BNN 裂变产额结果处理与评价** 的小型示例。内容包括一份归一化后的模型输出、对应的 scaler 文件、可复用的数据处理/审计 skill，以及已经生成好的示例图和评价报告。

## 目录内容

```text
demo/
├─ data/
│  └─ result2_1044.txt        # BNN 预测结果，包含归一化后的 Z、A、能量、产额和置信区间
├─ scalers/
│  ├─ standard_scalerZ.pkl    # Z 反归一化 scaler
│  ├─ standard_scalerA.pkl    # A 反归一化 scaler
│  ├─ standard_scalerE.pkl    # 能量/状态反归一化 scaler
│  └─ yield_scaler.pkl        # 产额反归一化 scaler
├─ skills/
│  ├─ fission-yield-from-network/
│  │  └─ scripts/fission_yield_tools.py
│  └─ fission-yield-evaluation/
│     ├─ scripts/fpy_basic_audit.py
│     └─ references/
└─ example/
   ├─ result_1044.png
   ├─ result_1032.png
   ├─ BNN_评价报告_result2_1044.md
   └─ BNN_评价报告_result2_1032.md
```

## 功能概览

- `skills/fission-yield-from-network/`：用于读取 BNN/ML 预测结果、加载 scaler、反归一化数据，并按质量数或电荷数汇总裂变产额。
- `skills/fission-yield-evaluation/`：用于对裂变产额数据做基础数值审计和物理合理性检查，例如负产额、不确定度、归一化、质量分布和能量趋势等。
- `data/result2_1044.txt`：示例输入数据。
- `example/`：已经生成的对比图、评价报告和一次命令记录，可作为输出格式参考。`example/BNN_评价报告_result2_1044.md` 给出了 `result2_1044.txt` 的审计结论和物理检查摘要；`example/result_1044.png` 是对应的可视化结果。`1032` 文件用于与另一版 BNN 结果进行对比。


## 依赖

主要 Python 依赖：

- `numpy`
- `pandas`
- `scikit-learn`
- `joblib`

其中 `fpy_basic_audit.py` 只依赖 Python 标准库；`fission_yield_tools.py` 需要上述科学计算库。