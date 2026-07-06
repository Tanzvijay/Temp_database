import pandas as pd
from psycopg2 import sql
import os
import psycopg2

import xml.etree.ElementTree as ET


import numpy as np
import re




def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# =============================================
# Robust Datetime Parser (Pandas)
# =============================================
def robust_to_datetime_pandas(series: pd.Series) -> pd.Series:
    """
    Robust datetime parser supporting multiple formats.
    """
    def clean_date_string(s):
        if s is None or (isinstance(s, float) and np.isnan(s)):
            return None
        s = str(s).strip()
        s = re.sub(
            r'\s+(UTC|GMT|EST|PST|CST|MST|EDT|PDT|IST|BST|CET)\s*$',
            '', s, flags=re.IGNORECASE
        )
        s = re.sub(r'Z\s*$', '', s)
        s = re.sub(r'[+-]\d{2}:?\d{2}\s*$', '', s)
        s = s.replace('T', ' ')
        return s.strip()

    cleaned = series.map(clean_date_string)

    formats = [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M", "%d-%m-%Y", "%m-%d-%Y", "%Y/%m/%d",
        "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y.%m.%d", "%Y%m%d",
        "%d%m%Y", "%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%B %d, %Y",
        "%d %b %Y", "%d %B %Y", "%a %b %d %H:%M:%S %Y",
    ]

    best = None
    best_count = 0

    for fmt in formats:
        try:
            parsed = pd.to_datetime(cleaned, format=fmt, errors="coerce")
            count = parsed.notna().sum()
            if count > best_count:
                best_count = count
                best = parsed
            if best_count == cleaned.notna().sum():
                break
        except Exception:
            continue

    if best is None or best_count == 0:
        try:
            best = pd.to_datetime(cleaned, errors="coerce", dayfirst=True)
        except Exception:
            pass

    return best if best is not None else series


# =============================================
# Auto Data Type Converter
# =============================================
def auto_convert_dtypes(df: pd.DataFrame) -> pd.DataFrame:

    def try_convert_column(series: pd.Series, col_name: str = "") -> pd.Series:

        if pd.api.types.is_datetime64_any_dtype(series):
            return series
        if pd.api.types.is_bool_dtype(series):
            return series

        non_null = series.dropna()
        if len(non_null) == 0:
            return series

        if pd.api.types.is_integer_dtype(series):
            sample = non_null.head(50)
            is_yyyymmdd = (
                (sample >= 19000101) & (sample <= 21001231) &
                ((sample // 100 % 100).between(1, 12)) &
                ((sample % 100).between(1, 31))
            ).all()
            if is_yyyymmdd:
                try:
                    return pd.to_datetime(series.astype(str), format="%Y%m%d", errors="coerce")
                except Exception:
                    pass
            return series

        col_str = non_null.astype(str).str.strip()

        bool_map = {
            "true": True, "false": False, "yes": True, "no": False,
            "1": True, "0": False, "y": True, "n": False,
        }
        bool_vals = col_str.str.lower().unique()
        if all(v in bool_map for v in bool_vals):
            return series.map(
                lambda x: bool_map.get(str(x).strip().lower()) if pd.notna(x) else None
            )

        try:
            converted = pd.to_numeric(col_str, errors="raise")
            if (converted == converted.astype(int)).all():
                if col_str.str.match(r"^\d{8}$").all():
                    sample_vals = converted.head(50)
                    is_yyyymmdd = (
                        (sample_vals >= 19000101) & (sample_vals <= 21001231) &
                        ((sample_vals // 100 % 100).between(1, 12)) &
                        ((sample_vals % 100).between(1, 31))
                    ).all()
                    if is_yyyymmdd:
                        return pd.to_datetime(series, format="%Y%m%d", errors="coerce")
                return pd.to_numeric(series, errors="coerce").astype("Int64")
        except Exception:
            pass

        try:
            pd.to_numeric(col_str, errors="raise")
            return pd.to_numeric(series, errors="coerce").astype(float)
        except Exception:
            pass

        yyyy_mm_pattern = r"^\d{4}-(0[1-9]|1[0-2])$"
        if col_str.str.match(yyyy_mm_pattern).all():
            try:
                return pd.to_datetime(
                    series + "-01", format="%Y-%m-%d", errors="coerce"
                ).dt.to_period("M")
            except Exception:
                pass

        date_patterns = [
            (r"^\d{4}-(0[1-9]|1[0-2])$",               "%Y-%m"),
            (r"^\d{4}-\d{2}-\d{2}$",                    "%Y-%m-%d"),
            (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", "%Y-%m-%d %H:%M:%S"),
            (r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",  "%Y-%m-%dT%H:%M:%S"),
            (r"^\d{2}-\d{2}-\d{4}$",                    "%d-%m-%Y"),
            (r"^\d{2}/\d{2}/\d{4}$",                    "%d/%m/%Y"),
            (r"^\d{2}\.\d{2}\.\d{4}$",                  "%d.%m.%Y"),
            (r"^\d{8}$",                                 "%Y%m%d"),
            (r"^\d{4}\.\d{2}\.\d{2}$",                  "%Y.%m.%d"),
            (r"^\d{2}-[A-Za-z]{3}-\d{2,4}$",            "%d-%b-%Y"),
            (r"^[A-Za-z]+ \d{1,2},? \d{4}$",            "%B %d, %Y"),
            (r"^[A-Za-z]{3} \d{1,2},? \d{4}$",          "%b %d, %Y"),
            (r"^\d{2} [A-Za-z]+ \d{4}$",                "%d %B %Y"),
            (r"^[A-Za-z]{3} [A-Za-z]{3} \d{2} [\d:]+",  "%a %b %d %H:%M:%S %Y"),
            (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$", "%Y-%m-%d %H:%M:%S"),
        ]

        sample = col_str.head(30)
        for pattern, fmt in date_patterns:
            match_count = sum(1 for val in sample if re.match(pattern, str(val).strip()))
            if len(sample) > 0 and match_count / len(sample) >= 0.7:
                try:
                    if fmt == "%Y-%m":
                        converted = pd.to_datetime(
                            series + "-01", format="%Y-%m-%d", errors="coerce"
                        ).dt.to_period("M")
                        if converted.notna().sum() > series.notna().sum() * 0.5:
                            return converted
                    else:
                        converted = robust_to_datetime_pandas(series)
                        if converted.notna().sum() > series.notna().sum() * 0.5:
                            return converted
                except Exception:
                    pass

        return series

    for col in df.columns:
        try:
            df[col] = try_convert_column(df[col], col_name=col)
        except Exception:
            pass

    return df


# =============================================
# Convert Period Columns to String
# =============================================
def convert_period_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if str(df[col].dtype).startswith("period"):
            df[col] = df[col].astype(str)
    return df


# =============================================
# JSON Safe Converter
# =============================================
def make_json_safe(val):
    try:
        if val is None:
            return None
        if isinstance(val, pd.Period):
            return str(val)
        if isinstance(val, pd.Timestamp):
            return val.isoformat()
        if val is pd.NaT:
            return None
        try:
            if pd.isna(val):
                return None
        except Exception:
            pass
        if isinstance(val, np.integer):
            return int(val)
        if isinstance(val, np.floating):
            return float(val)
        if isinstance(val, np.bool_):
            return bool(val)
        if isinstance(val, np.ndarray):
            return val.tolist()
        return val
    except Exception:
        return str(val)


# =============================================
# List Database Tables
# =============================================
def list_database_tables_agent():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
                """
            )
            rows = cur.fetchall()
            tables = [row[0] for row in rows]
            return {"total_tables": len(tables), "tables": tables}
    finally:
        conn.close()


# =============================================
# Prepare DataFrame for DB Save
# (convert Period/Timestamp cols to plain types)
# =============================================
def _prepare_df_for_db(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert Period, Timestamp, numpy types to Python-native types
    so SQLAlchemy / psycopg2 can insert them without errors.
    """
    df = df.copy()
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        if dtype_str.startswith("period"):
            df[col] = df[col].astype(str)
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            # keep as datetime — psycopg2 handles it fine
            pass
        elif dtype_str == "Int64":
            df[col] = df[col].astype(object).where(df[col].notna(), other=None)
    return df


# =============================================
# Get Table Data with Filters
# =============================================
def get_table_data(
    table_name: str,
    limit: int = 100,
    columns=None,
    filter_column=None,
    filter_value=None,
    date_column=None,
    from_date=None,
    to_date=None,
    
    # ── NEW ──────────────────────────────────
    filename: str = None,          # e.g. "output.csv" → saves filtered data as CSV
    save_to_db: bool = False,      # True → saves filtered data back to PostgreSQL
    save_table_name: str = None,   # target table name (required when save_to_db=True)
    if_exists: str = "replace",    # "replace" | "append" | "fail"
):
    conn = get_connection()

    try:
        # ── Step 1: Read full table ──────────────────────────────────────
        df = pd.read_sql(f'SELECT * FROM "{table_name}"', conn)

        # ── Step 2: Auto convert data types ─────────────────────────────
        df = auto_convert_dtypes(df)

        # ── Step 3: Select Columns ──────────────────────────────────────
        if columns:
            selected_cols = [c.strip() for c in columns.split(",")]
            valid_cols = [c for c in selected_cols if c in df.columns]
            if valid_cols:
                df = df[valid_cols]

        # ── Step 4: Value Filter ────────────────────────────────────────
        if filter_column and filter_value:
            if filter_column in df.columns:
                values = [v.strip() for v in filter_value.split(",")]
                df = df[df[filter_column].astype(str).isin(values)]

        # ── Step 5: Date Filter ─────────────────────────────────────────
        if date_column and from_date and to_date:
            if date_column in df.columns:
                if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                    df[date_column] = robust_to_datetime_pandas(df[date_column])
                from_dt = pd.to_datetime(from_date)
                to_dt   = pd.to_datetime(to_date)
                df = df[(df[date_column] >= from_dt) & (df[date_column] <= to_dt)]

        # ── Step 6: Group By with aggregation ───────────────────────────
    

        # ── Step 7 (NEW): Save filtered data to CSV ──────────────────────
        csv_saved = None
        if filename:
            # Ensure .csv extension
            if not filename.lower().endswith(".csv"):
                filename = filename + ".csv"

            save_path = os.path.abspath(filename)
            df_for_csv = convert_period_columns(df.copy())
            df_for_csv.to_csv(save_path, index=False)
            csv_saved = save_path

        # ── Step 8 (NEW): Save filtered data to PostgreSQL ───────────────
        db_saved = None
        if save_to_db:
            if not save_table_name:
                raise ValueError(
                    "`save_table_name` is required when `save_to_db=True`."
                )

            from sqlalchemy import create_engine

            db_url = (
                f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
                f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
            )
            engine = create_engine(db_url)

            df_for_db = _prepare_df_for_db(df)
            df_for_db.to_sql(
                save_table_name,
                engine,
                if_exists=if_exists,   # "replace" | "append" | "fail"
                index=False,
            )
            engine.dispose()
            db_saved = save_table_name

        # ── Step 9: Apply limit LAST ─────────────────────────────────────
        total_rows = len(df)
        df_limited = df.head(limit).copy()

        # ── Step 10: Convert Period columns for JSON ─────────────────────
        df_limited = convert_period_columns(df_limited)

        # ── Step 11: JSON-safe records ────────────────────────────────────
        records = [
            {k: make_json_safe(v) for k, v in row.items()}
            for row in df_limited.to_dict("records")
        ]

        # ── Step 12: Dtype info ───────────────────────────────────────────
        dtype_info = {col: str(df[col].dtype) for col in df.columns}

        return {
            "table_name":    table_name,
            "total_rows":    total_rows,
            "returned_rows": len(records),
            "columns":       list(df.columns),
            "dtypes":        dtype_info,
            "data":          records,
            # ── NEW fields ──────────────────────────────
            "csv_saved":     csv_saved,      # path if saved, else None
            "db_saved":      db_saved,       # table name if saved, else None
        }

    finally:
        conn.close()






# =============================================
# Get Unique Values for a Column
# =============================================
def get_unique_column_values(table_name: str, column: str):
    conn = get_connection()
    try:
        df = pd.read_sql(
            f'SELECT DISTINCT "{column}" FROM "{table_name}" ORDER BY "{column}"',
            conn
        )
        values = [make_json_safe(v) for v in df[column].tolist()]
        return {
            "table_name": table_name,
            "column": column,
            "total_unique": len(values),
            "values": values,
        }
    finally:
        conn.close()