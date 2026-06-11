"""Reusable utilities for fission-yield data workflows.

These helpers intentionally avoid project-specific file names and scientific
assumptions. Callers should confirm data provenance, units, column mappings,
and coverage with the user before applying them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler


STANDARD_COLUMNS = ["Z", "A", "State", "Yield", "Error"]
RESULT_COLUMNS = ["z", "a", "state", "results", "5%CI", "95%CI"]


def load_indexed_txt(path: str | Path, columns: Sequence[str] = STANDARD_COLUMNS) -> pd.DataFrame:
    """Load a 6-column whitespace TXT file: index, Z, A, State, Yield, Error."""
    data = np.loadtxt(path)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 6:
        raise ValueError(f"{path} has {data.shape[1]} columns; expected at least 6.")
    return pd.DataFrame(data[:, 1:6], columns=list(columns))


def load_csv(
    path: str | Path,
    columns: Sequence[str] = STANDARD_COLUMNS,
    header: int | None = 0,
    usecols: Sequence[str | int] | None = None,
) -> pd.DataFrame:
    """Load a CSV and normalize its column names when requested."""
    df = pd.read_csv(path, header=header, usecols=usecols)
    if header is None:
        if len(columns) != df.shape[1]:
            raise ValueError(f"{path} has {df.shape[1]} columns; got {len(columns)} names.")
        df.columns = list(columns)
    return df


def load_result_txt(path: str | Path) -> pd.DataFrame:
    """Load ML prediction TXT with automatic 6-vs-7-column detection."""
    with open(path, "r", encoding="utf-8") as f:
        first_line = f.readline()
    num_columns = len(first_line.strip().split())

    if num_columns == 7:
        usecols = [0, 1, 2, 3, 5, 6]
    elif num_columns == 6:
        usecols = [0, 1, 2, 3, 4, 5]
    else:
        raise ValueError(f"{path} has {num_columns} columns; expected 6 or 7.")

    df = pd.read_csv(path, sep=r"\s+", header=None, usecols=usecols)
    df.columns = RESULT_COLUMNS
    return df


def load_many(paths: Iterable[str | Path], loader=load_csv, **kwargs) -> pd.DataFrame:
    """Load multiple files with the same loader and concatenate them."""
    frames = [loader(path, **kwargs) for path in sorted(map(Path, paths))]
    if not frames:
        raise ValueError("No input files were provided.")
    return pd.concat(frames, ignore_index=True)


def fit_minmax_scalers(
    df: pd.DataFrame,
    feature_ranges: Mapping[str, tuple[float, float]] | None = None,
    columns: Mapping[str, str] | None = None,
) -> dict[str, MinMaxScaler]:
    """Fit Z, A, State, and Yield MinMaxScaler objects on reference data."""
    columns = {
        "z": "Z",
        "a": "A",
        "state": "State",
        "yield": "Yield",
        **(columns or {}),
    }
    feature_ranges = {
        "z": (-0.9, 0.9),
        "a": (-0.9, 0.9),
        "state": (0.2, 0.4),
        "yield": (0.0, 0.9),
        **(feature_ranges or {}),
    }

    scalers: dict[str, MinMaxScaler] = {}
    for key, column in columns.items():
        scaler = MinMaxScaler(feature_range=feature_ranges[key])
        scaler.fit(df[[column]])
        scalers[key] = scaler
    return scalers


def save_scalers(scalers: Mapping[str, MinMaxScaler], out_dir: str | Path) -> dict[str, Path]:
    """Save scalers using the common project naming convention."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = {
        "z": "standard_scalerZ.pkl",
        "a": "standard_scalerA.pkl",
        "state": "standard_scalerE.pkl",
        "yield": "yield_scaler.pkl",
    }
    saved: dict[str, Path] = {}
    for key, scaler in scalers.items():
        path = out / names.get(key, f"{key}_scaler.pkl")
        joblib.dump(scaler, path)
        saved[key] = path
    return saved


def find_and_load_scalers(search_dir: str | Path = ".") -> dict[str, MinMaxScaler]:
    """Auto-detect and load scaler files from a directory."""
    search_dir = Path(search_dir)
    scalers: dict[str, MinMaxScaler] = {}

    patterns = {
        "z": "*scalerZ*.pkl",
        "a": "*scalerA*.pkl",
        "state": "*scalerE*.pkl",
        "yield": "yield_scaler*.pkl",
    }
    for key, pattern in patterns.items():
        matches = sorted(search_dir.glob(pattern))
        if matches:
            scalers[key] = joblib.load(matches[0])

    if "z" not in scalers or "a" not in scalers:
        combined = sorted(search_dir.glob("standard_scaler.pkl"))
        if combined:
            scaler = joblib.load(combined[0])
            scalers["z"] = scaler
            scalers["a"] = scaler

    if "yield" not in scalers:
        raise FileNotFoundError(
            f"No yield_scaler.pkl found in {search_dir}. "
            "Run Phase 1 normalization first to generate scaler files."
        )
    return scalers


def scaler_summary(scaler: MinMaxScaler) -> dict[str, object]:
    """Return a compact sanity-check summary for one fitted scaler."""
    return {
        "data_min": scaler.data_min_.tolist(),
        "data_max": scaler.data_max_.tolist(),
        "feature_range": scaler.feature_range,
    }


def transform_dataframe(
    df: pd.DataFrame,
    scalers: Mapping[str, MinMaxScaler],
    columns: Mapping[str, str] | None = None,
    error_column: str | None = "Error",
) -> pd.DataFrame:
    """Apply fitted scalers to a dataframe. This does not fit new scalers."""
    columns = {
        "z": "Z",
        "a": "A",
        "state": "State",
        "yield": "Yield",
        **(columns or {}),
    }
    out = df.copy()
    for key, column in columns.items():
        if key in scalers and column in out.columns:
            out[column] = scalers[key].transform(out[[column]])
    if error_column and error_column in out.columns and "yield" in scalers:
        out[error_column] = out[error_column] * scalers["yield"].scale_[0]
    return out


def inverse_transform_dataframe(
    df: pd.DataFrame,
    scalers: Mapping[str, MinMaxScaler],
    columns: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Convert normalized dataframe columns back to physical ranges."""
    columns = {
        "z": "z",
        "a": "a",
        "state": "state",
        "yield": "results",
        **(columns or {}),
    }
    out = df.copy()
    for key, column in columns.items():
        if key in scalers and column in out.columns:
            out[column] = scalers[key].inverse_transform(out[[column]])

    if "yield" in scalers:
        for column in ("5%CI", "95%CI"):
            if column in out.columns:
                out[column] = scalers["yield"].inverse_transform(out[[column]])
    return out


def add_integer_za(df: pd.DataFrame, z_col: str = "z", a_col: str = "a") -> pd.DataFrame:
    """Add rounded integer Z/A columns after inverse normalization."""
    out = df.copy()
    out["Z"] = out[z_col].round().astype(int)
    out["A"] = out[a_col].round().astype(int)
    return out


def nuclide_yields(
    df: pd.DataFrame,
    z_col: str = "Z",
    a_col: str = "A",
    yield_col: str = "results",
    agg: str = "mean",
) -> pd.DataFrame:
    """Aggregate per-nuclide yields."""
    return df.groupby([z_col, a_col], as_index=False)[yield_col].agg(agg)


def sum_by(
    df: pd.DataFrame,
    group_col: str,
    yield_col: str = "results",
    sort: bool = True,
) -> pd.DataFrame:
    """Sum yields by mass number, charge number, or another grouping column."""
    out = df.groupby(group_col, as_index=False)[yield_col].sum()
    return out.sort_values(group_col) if sort else out


def propagate_ci_uncertainty(
    df: pd.DataFrame,
    group_col: str,
    yield_col: str = "results",
    low_col: str = "5%CI",
    high_col: str = "95%CI",
) -> pd.DataFrame:
    """Sum grouped yields and propagate asymmetric CI bounds by quadrature."""
    def _one_group(group: pd.DataFrame) -> pd.Series:
        result_sum = group[yield_col].sum()
        low_error = np.sqrt(((group[yield_col] - group[low_col]) ** 2).sum())
        high_error = np.sqrt(((group[high_col] - group[yield_col]) ** 2).sum())
        return pd.Series({
            yield_col: result_sum,
            low_col: result_sum - low_error,
            high_col: result_sum + high_error,
        })

    return df.groupby(group_col).apply(_one_group).reset_index()


def propagate_symmetric_error(
    df: pd.DataFrame,
    group_col: str,
    yield_col: str = "results",
    error_col: str = "error",
) -> pd.DataFrame:
    """Sum grouped yields and propagate symmetric errors by quadrature."""
    return df.groupby(group_col).agg({
        yield_col: "sum",
        error_col: lambda x: np.sqrt((x ** 2).sum()),
    }).reset_index()


def augment_training_weight(
    df: pd.DataFrame,
    state_col: str = "State",
    a_col: str = "A",
    yield_col: str = "Yield",
    repeat: int = 3,
) -> pd.DataFrame:
    """Repeat high-yield rows within each state to increase training weight."""
    top_rows_all = []
    for _, group in df.groupby(state_col):
        group_pos = group[group[a_col] > 0]
        group_neg = group[group[a_col] < 0]

        top_pos_a = group_pos.groupby(a_col)[yield_col].sum().sort_values(ascending=False).head(3).index
        top_neg_a = group_neg.groupby(a_col)[yield_col].sum().sort_values(ascending=False)
        top_neg_a = top_neg_a.iloc[[0, 1, 4]].index if len(top_neg_a) >= 5 else top_neg_a.index

        top_rows = group[group[a_col].isin(top_pos_a.union(top_neg_a))]
        top_rows_all.append(pd.concat([top_rows] * repeat, ignore_index=True))

    if not top_rows_all:
        return df.copy()
    return pd.concat([df] + top_rows_all, ignore_index=True)


def merge_on_key(frames: Sequence[pd.DataFrame], key: str, how: str = "outer") -> pd.DataFrame:
    """Merge multiple model/reference dataframes on a shared key."""
    if not frames:
        raise ValueError("No dataframes were provided.")
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=key, how=how)
    return merged.sort_values(key)
