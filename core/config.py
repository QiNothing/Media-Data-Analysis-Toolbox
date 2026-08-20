"""
配置加载与字段映射
==================
职责：
  1. 读 config/*.yaml
  2. 把真实 Excel 的乱七八糟表头，翻译成程序内部的标准字段名
  3. 把 "CCTV1"/"央视一套" 这类频道别名归一

设计意图：所有"和真实数据对接"的脏活都关在这一层，
上层计算代码永远只见到干净的标准字段名。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# =============================================================================
# YAML 读取
# =============================================================================

@lru_cache(maxsize=8)
def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_field_mapping() -> dict:
    """加载字段映射配置。"""
    return _load_yaml("field_mapping.yaml")


def load_benchmarks() -> dict:
    """加载行业基准配置。"""
    return _load_yaml("benchmarks.yaml")


def clear_config_cache() -> None:
    """改完 yaml 后调用，让下次读取拿到新内容（Streamlit 里点"重载配置"用）。"""
    _load_yaml.cache_clear()


# =============================================================================
# 表头归一化
# =============================================================================

def _normalize_key(s: Any) -> str:
    """把表头压成可比较的形式：去空格/下划线/横杠/括号，转小写。

    这样 "收视率 (%)"、"收视率(%)"、"收视率_%" 都会变成同一个 key。
    """
    if s is None:
        return ""
    text = str(s).strip().lower()
    text = re.sub(r"[\s_\-—–－()（）\[\]【】%．.]", "", text)
    return text


def build_alias_index(section: dict) -> dict[str, str]:
    """由某个 section 的配置，构建 {归一化别名: 标准字段名} 的查找表。"""
    index: dict[str, str] = {}
    for std_name, spec in section.items():
        aliases = spec.get("aliases", []) if isinstance(spec, dict) else []
        # 标准字段名本身也算一个别名
        for alias in [std_name, *aliases]:
            index[_normalize_key(alias)] = std_name
    return index


def map_columns(df: pd.DataFrame, section_name: str) -> tuple[pd.DataFrame, dict, list]:
    """把 DataFrame 的表头翻译成标准字段名。

    参数
    ----
    df           : 原始读进来的表
    section_name : "placement" / "competitor" / "benchmark"

    返回
    ----
    (新df, 映射明细dict, 未能识别的原始列名list)

    未识别的列会被【保留】在结果里（原名不动），不会丢数据，
    只是在页面上提示"这几列我不认识"，你可以决定是加进 yaml 还是忽略。
    """
    mapping_cfg = load_field_mapping()
    section = mapping_cfg.get(section_name, {})
    if not section:
        raise ValueError(f"field_mapping.yaml 里没有 '{section_name}' 这一节")

    index = build_alias_index(section)

    rename: dict[str, str] = {}
    unmapped: list[str] = []
    used_std: set[str] = set()

    for col in df.columns:
        std = index.get(_normalize_key(col))
        if std and std not in used_std:
            rename[col] = std
            used_std.add(std)
        elif std and std in used_std:
            # 两列映射到同一个标准字段（比如同时有"花费"和"金额"）——保留第一个，第二个标为未识别
            unmapped.append(f"{col}（与已识别列重复映射到 {std}，已跳过）")
        else:
            unmapped.append(str(col))

    out = df.rename(columns=rename)
    return out, rename, unmapped


def check_required(df: pd.DataFrame, section_name: str) -> list[str]:
    """检查必填字段是否齐全，返回缺失的标准字段名列表（附中文标签）。"""
    section = load_field_mapping().get(section_name, {})
    missing = []
    for std_name, spec in section.items():
        if isinstance(spec, dict) and spec.get("required") and std_name not in df.columns:
            missing.append(f"{std_name}（{spec.get('label', std_name)}）")
    return missing


def coerce_dtypes(df: pd.DataFrame, section_name: str) -> tuple[pd.DataFrame, list[str]]:
    """按配置把各列转成正确的数据类型。

    转换失败的单元格变成 NaN/NaT 而不是报错，并在返回的 warnings 里记一笔，
    因为真实数据里 "-"、"待定"、"/" 这类脏值太常见了。
    """
    section = load_field_mapping().get(section_name, {})
    out = df.copy()
    warnings: list[str] = []

    for std_name, spec in section.items():
        if std_name not in out.columns or not isinstance(spec, dict):
            continue
        dtype = spec.get("dtype", "str")
        label = spec.get("label", std_name)
        before_na = out[std_name].isna().sum()

        if dtype == "float":
            # 先清掉千分位逗号、货币符号、百分号、中文单位
            cleaned = (
                out[std_name].astype(str)
                .str.replace(r"[,，¥$￥\s]", "", regex=True)
                .str.replace(r"[%％]", "", regex=True)
                .str.replace(r"^[-—/／\.]+$", "", regex=True)  # 纯占位符
            )
            out[std_name] = pd.to_numeric(cleaned, errors="coerce")
        elif dtype == "date":
            out[std_name] = pd.to_datetime(out[std_name], errors="coerce")
        else:
            out[std_name] = out[std_name].astype(str).str.strip()
            out.loc[out[std_name].isin(["nan", "None", "NaT", ""]), std_name] = pd.NA

        after_na = out[std_name].isna().sum()
        newly_na = int(after_na - before_na)
        if newly_na > 0:
            warnings.append(f"「{label}」有 {newly_na} 个值无法转换为{dtype}，已置空")

    return out, warnings


# =============================================================================
# 频道名归一
# =============================================================================

@lru_cache(maxsize=1)
def _channel_index() -> dict[str, str]:
    cfg = load_field_mapping().get("channel_normalize", {}) or {}
    index: dict[str, str] = {}
    for std, aliases in cfg.items():
        for alias in [std, *(aliases or [])]:
            index[_normalize_key(alias)] = std
    return index


def normalize_channel(name: Any) -> str:
    """把单个频道名归一到标准名。不认识的原样返回（不丢数据）。"""
    if pd.isna(name):
        return ""
    return _channel_index().get(_normalize_key(name), str(name).strip())


def normalize_channel_column(df: pd.DataFrame, col: str = "channel") -> tuple[pd.DataFrame, list[str]]:
    """归一整列频道名，并返回"没能识别、保持原样"的频道列表。

    那个列表很有用：它就是你需要往 field_mapping.yaml 的 channel_normalize 里补的条目。
    """
    if col not in df.columns:
        return df, []
    out = df.copy()
    original = out[col].astype(str)
    out[col] = original.map(normalize_channel)
    index = _channel_index()
    unknown = sorted({
        v for v in original.unique()
        if _normalize_key(v) not in index and str(v).strip() not in ("", "nan")
    })
    return out, unknown


# =============================================================================
# 基准取值助手
# =============================================================================

def get_channel_benchmark(channel: str) -> dict:
    """取某频道的基准（CPRP / 平均收视率 / 到达率上限 / rho）。

    频道不在基准表里时，用同类型均值兜底；再找不到就用全表均值。
    返回的 dict 里带 'source' 字段说明数据是精确匹配还是兜底估算——
    这个字段一定要显示在页面上，避免拿兜底值当真实数据汇报。
    """
    bm = load_benchmarks()
    channels = bm.get("channels", {})
    reach_cfg = bm.get("reach_model", {})
    rho_map = reach_cfg.get("rho_by_channel_type", {})
    default_rho = float(reach_cfg.get("default_rho", 0.20))

    std = normalize_channel(channel)
    if std in channels:
        c = dict(channels[std])
        c["rho"] = float(rho_map.get(c.get("channel_type", ""), default_rho))
        c["channel"] = std
        c["source"] = "基准表精确匹配"
        return c

    # 兜底：全表均值
    if channels:
        vals = list(channels.values())
        c = {
            "cprp": sum(float(v.get("cprp", 0)) for v in vals) / len(vals),
            "avg_rating": sum(float(v.get("avg_rating", 0)) for v in vals) / len(vals),
            "max_reach": sum(float(v.get("max_reach", 0)) for v in vals) / len(vals),
            "channel_type": "未知",
            "rho": default_rho,
            "channel": std,
            "source": "⚠️ 未在基准表中，使用全表均值估算",
        }
        return c

    return {
        "cprp": float("nan"), "avg_rating": float("nan"), "max_reach": float("nan"),
        "channel_type": "未知", "rho": default_rho, "channel": std,
        "source": "⚠️ 无基准数据",
    }


def benchmark_table() -> pd.DataFrame:
    """把频道基准配置转成 DataFrame，页面上直接展示/编辑。"""
    bm = load_benchmarks()
    channels = bm.get("channels", {})
    rho_map = bm.get("reach_model", {}).get("rho_by_channel_type", {})
    default_rho = float(bm.get("reach_model", {}).get("default_rho", 0.20))

    rows = []
    for name, spec in channels.items():
        ctype = spec.get("channel_type", "未知")
        rows.append({
            "channel": name,
            "channel_type": ctype,
            "cprp": float(spec.get("cprp", 0)),
            "avg_rating": float(spec.get("avg_rating", 0)),
            "max_reach": float(spec.get("max_reach", 0)),
            "rho": float(rho_map.get(ctype, default_rho)),
        })
    return pd.DataFrame(rows)


def is_calibrated() -> bool:
    """基准数据是否已用公司真实数据校准过。未校准时页面要挂警告。"""
    return bool(load_benchmarks().get("verified", False))
