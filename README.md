# 媒介数据分析工具箱

> 电视 / OTT 媒介投放的日常分析工具：GRP·CPRP 测算、预算分配优化、
> 数据质量检查、竞品声量分析、日周月报生成。
>
> 面向媒介方向的数据分析师、媒介策划、广告投放岗。
> 内置行业知识手册 —— 没有媒介背景也能上手。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/tests-262%20passing-brightgreen)

---

## 它解决什么问题

电视广告效果的量化，建立在一套自成体系的指标上（GRP、CPRP、到达率、
频次、有效到达）。这套体系有三个特点：**概念不直观、计算不简单、
容易算错还看不出来**。

这个工具箱做三件事：

1. **把指标算对** —— 到达率曲线、跨媒体去重、有效频次分布，
   都用行业标准方法实现，并有 84 项数学性质测试保证正确性
2. **把错误挡住** —— 9 类数据质检规则，抓单位错误、勾稽不符、重复记录
3. **把黑话讲明白** —— 每个指标都有「人话解释 + 工作里怎么用 + 有什么坑」

---

## 快速开始

```bash
git clone <repo-url>
cd 媒介数据分析工具箱
pip install -r requirements.txt
python -m core.sample_data          # 生成样例数据
streamlit run "app/主页.py"
```

Windows 用户直接双击 `启动.bat`，会自动装依赖并打开浏览器。

首次使用建议先选「使用样例数据」把功能点一遍 ——
样例里**故意埋了 9 个真实工作中常见的数据错误**，
正好看看质检能抓出什么。

---

## 三种使用形态

| 形态 | 怎么用 | 适合什么场景 |
|---|---|---|
| **网页版** | `streamlit run "app/主页.py"` | 日常主力：探索、测算、出报告 |
| **Excel 模板** | `python -m tools.build_excel` | 没有 Python 的机器；要发给客户/同事；开会投屏当场改 |
| **绿色便携版** | `python -m tools.build_portable` | 不能装软件、没有管理员权限的电脑 |

**Excel 模板**（5 个文件，带活公式，不需要 Python）：

| 文件 | 能力 |
|---|---|
| GRP 预算测算模板 | 改预算/频道 → 各项指标自动变，带响应曲线图；含反算 |
| 跨媒体组合与边际分析 | Sainsbury 去重；追加预算加哪个频道最划算 |
| 数据质检清单 | 粘上数据自动标红问题行 + 交付前自查 |
| 媒介指标速查卡 | A4 单页，可打印 |
| 周报模板 | 填数字自动出环比、KPI 达成、结论草稿 |

Excel 版覆盖了大部分能力，唯一做不到的是**自动预算优化器**
（需要迭代计算，纯公式实现不了）。

**绿色便携版**自带 Python 运行时，解压即用：不需要安装、不需要管理员权限、
不写注册表，删掉文件夹即卸载干净。详见
[docs/04_没有Python环境怎么办.md](docs/04_没有Python环境怎么办.md)
（含可直接提交的 IT 审批申请模板）。

---

## 功能页

| 页面 | 干什么 |
|---|---|
| 📖 媒介知识速查 | 8 个核心指标的人话解释、数据源口径对比、5 组客户应答话术、30 天上手计划 |
| 🧮 指标计算器 | GRP/CPRP/CPM、到达率与频次、反算所需预算、刊例折扣、跨媒体合并 |
| 🔍 数据质量检查 | 9 类规则一键查错，输出可交付的质检报告 |
| 💰 预算分配优化 | 三种目标下的最优分配、边际收益曲线、追加预算建议 |
| ⚔️ 竞品声量分析 | SOV 排名与走势、ESOV 诊断、频道重合度、自动结论 |
| 📊 日报周报月报 | 一键生成，含 KPI 达成判定与自动洞察，导出 Excel/Markdown |
| 🎯 排期方案对比 | 多方案横向对比、雷达图、单位预算效率、提案话术生成 |

---

## 接入真实数据（不用改代码）

### `config/field_mapping.yaml` —— 表头对不上时改这里

每个标准字段都预置了大量别名，实际表头加一行即可：

```yaml
placement:
  cost:
    aliases: [花费, 费用, 金额, 结算金额, <实际列名>]
```

还能归一频道别名，解决 `CCTV1` / `CCTV-1` / `央视一套` 混用：

```yaml
channel_normalize:
  CCTV-1: [CCTV1, CCTV-1, 央视一套, 中央一套]
```

### `config/benchmarks.yaml` —— 填真实基准

把占位的 CPRP、收视率、人口基数换成实际数据，
并把 `verified: false` 改成 `true`（页面顶部的警告会消失）。

拿不到完整基准时，可以用历史投放数据反算：
`某频道 CPRP = 该频道历史总花费 ÷ 该频道历史总 GRP`。

改完在侧边栏点「🔄 重载配置文件」即可生效，不用重启。

---

## 计算方法

**到达率模型**（负指数族 / Beta-Binomial 简化式）：

```
Reach = MaxReach × (1 − exp(−k × GRP / MaxReach))，k = 1 − ρ
```

- GRP = 0 → 到达率 0；GRP → ∞ → 收敛到覆盖天花板
- ρ 为内部重复系数（观众忠诚度），越大到达率增长越慢
- 单调递增且凹 —— 即边际到达递减

**跨媒体去重**：Sainsbury 公式 `A + B − A×B/100`

**预算优化**：贪心边际分配。因到达率为凹函数，贪心解满足
边际效用相等条件，为全局最优。

**频次分布**：截断泊松近似，用于计算 n+ 有效到达率。

---

## 测试

```bash
python tests/test_metrics.py    # 数学正确性，84 项
python tests/test_pages.py      # 页面无头冒烟，8 个页面
python tests/test_excel.py      # Excel 公式验证，140 项（需本机装 Excel）
python tests/test_portable.py   # 便携版验证，30 项（需先打包）
```

两个测试设计上值得一提：

- `test_excel.py` 用 COM 真的打开 Excel 重算每个公式，再跟 Python 内核
  逐项比对 —— 因为 xlsxwriter 只负责**写**公式不负责**算**，
  不真跑一遍没法确认公式对不对
- `test_portable.py` 会**清空所有 Python 相关环境变量**再运行，
  模拟一台从未装过 Python 的机器 —— 否则可能偷偷用了打包机上的
  Python 而不自知（这个测试确实抓到过一个 `._pth` 配置的真 bug）

---

## 项目结构

```
├── config/
│   ├── field_mapping.yaml   字段映射 + 频道别名归一
│   └── benchmarks.yaml      CPRP / 收视 / 人口基准
├── core/                    计算内核（纯 Python，可独立调用）
│   ├── metrics.py           GRP/CPRP/CPM/到达率/频次/有效到达/跨媒体去重
│   ├── budget.py            预算分配优化器（贪心边际分配 + 约束）
│   ├── quality.py           9 类数据质检规则
│   ├── competitor.py        SOV / ESOV / 频道重合度
│   ├── report.py            日周月报生成（Excel + Markdown）
│   ├── config.py            配置加载与字段映射
│   └── sample_data.py       样例数据生成
├── app/                     Streamlit 界面（7 个功能页）
├── tools/
│   ├── build_excel.py       Excel 模板生成器
│   └── build_portable.py    绿色便携版打包器
├── docs/                    知识手册
└── tests/                   四套测试
```

`core/` 不依赖任何界面代码，可以直接在脚本或 Notebook 里调用：

```python
from core.metrics import reach_from_grp, effective_reach, cprp

grp = 3_000_000 / 42_000              # 预算 ÷ CPRP
reach = reach_from_grp(grp, max_reach_pct=62, rho=0.16)
print(f"净到达率 {reach:.1f}%，3+ 有效到达 {effective_reach(grp, reach, 3):.1f}%")
```

---

## ⚠️ 重要提醒

1. **内置的 CPRP / 收视率 / 人口基数都是行业量级的占位估算值**，
   不代表任何真实媒体的报价或收视表现。**校准前不要用于对外汇报。**

2. **到达率模型是业界通用近似方法**，与 CSM / 尼尔森官方软件的测算存在差异。
   模型不考虑排期节奏、素材损耗、季节性、竞品干扰。
   适合做方案的**相对比较**，不适合作为对客户的**承诺数字**。

3. **自动生成的分析结论是初稿不是终稿。**
   工具只能看到数据，看不到业务背景。

4. **Sainsbury 公式假设各媒体受众独立**，实际存在正相关，
   因此净到达率会**略微高估**。保守汇报可乘 0.9~0.95 系数并说明。

5. **不要把工具部署到公网。** 投放数据、采买折扣、CPRP 通常属于商业机密。
   本工具设计为纯本地运行、不联网、不上传任何数据 —— 请保持这一点。
   `.gitignore` 已默认屏蔽所有数据文件格式。

---

## License

[MIT](LICENSE)
