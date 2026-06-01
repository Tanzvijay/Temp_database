import pandas as pd
from psycopg2 import sql
import os
import psycopg2
import requests
import xml.etree.ElementTree as ET



import numpy as np

import re


TALLY_URL = "http://168.144.119.48/"



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

        # Remove timezone strings
        s = re.sub(
            r'\s+(UTC|GMT|EST|PST|CST|MST|EDT|PDT|IST|BST|CET)\s*$',
            '', s, flags=re.IGNORECASE
        )
        s = re.sub(r'Z\s*$', '', s)
        s = re.sub(r'[+-]\d{2}:?\d{2}\s*$', '', s)

        # Normalize ISO 8601 T separator
        s = s.replace('T', ' ')

        return s.strip()

    cleaned = series.map(clean_date_string)

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d.%m.%Y",
        "%Y.%m.%d",
        "%Y%m%d",
        "%d%m%Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%a %b %d %H:%M:%S %Y",
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

    # Final fallback
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
    """
    Automatically detect and convert column data types:
    - YYYYMMDD integers → datetime
    - YYYY-MM strings → Period[M]
    - Numeric strings → int/float
    - Boolean strings → bool
    - Date strings → datetime
    - Keep rest as string
    """

    def try_convert_column(series: pd.Series, col_name: str = "") -> pd.Series:

        # ✅ Skip if already datetime
        if pd.api.types.is_datetime64_any_dtype(series):
            return series
        if pd.api.types.is_bool_dtype(series):
            return series

        non_null = series.dropna()
        if len(non_null) == 0:
            return series

        # ============================
        # 1️⃣ Integer Column - Check YYYYMMDD
        # ============================
        if pd.api.types.is_integer_dtype(series):
            sample = non_null.head(50)

            is_yyyymmdd = (
                (sample >= 19000101) &
                (sample <= 21001231) &
                ((sample // 100 % 100).between(1, 12)) &
                ((sample % 100).between(1, 31))
            ).all()

            if is_yyyymmdd:
                try:
                    return pd.to_datetime(
                        series.astype(str),
                        format="%Y%m%d",
                        errors="coerce"
                    )
                except Exception:
                    pass

            # Not a date, keep as numeric
            return series

        col_str = non_null.astype(str).str.strip()

        # ============================
        # 2️⃣ Boolean Detection
        # ============================
        bool_map = {
            "true": True, "false": False,
            "yes": True, "no": False,
            "1": True, "0": False,
            "y": True, "n": False,
        }
        bool_vals = col_str.str.lower().unique()
        if all(v in bool_map for v in bool_vals):
            return series.map(
                lambda x: bool_map.get(str(x).strip().lower())
                if pd.notna(x) else None
            )

        # ============================
        # 3️⃣ Integer Detection
        # ============================
        try:
            converted = pd.to_numeric(col_str, errors="raise")
            if (converted == converted.astype(int)).all():

                # Check if string YYYYMMDD (e.g., "20240411")
                if col_str.str.match(r"^\d{8}$").all():
                    sample_vals = converted.head(50)
                    is_yyyymmdd = (
                        (sample_vals >= 19000101) &
                        (sample_vals <= 21001231) &
                        ((sample_vals // 100 % 100).between(1, 12)) &
                        ((sample_vals % 100).between(1, 31))
                    ).all()
                    if is_yyyymmdd:
                        return pd.to_datetime(
                            series,
                            format="%Y%m%d",
                            errors="coerce"
                        )

                return pd.to_numeric(series, errors="coerce").astype("Int64")

        except Exception:
            pass

        # ============================
        # 4️⃣ Float Detection
        # ============================
        try:
            pd.to_numeric(col_str, errors="raise")
            return pd.to_numeric(series, errors="coerce").astype(float)
        except Exception:
            pass

        # ============================
        # 5️⃣ YYYY-MM Period Detection
        #    e.g., "2024-04", "2024-12"
        # ============================
        yyyy_mm_pattern = r"^\d{4}-(0[1-9]|1[0-2])$"
        if col_str.str.match(yyyy_mm_pattern).all():
            try:
                return pd.to_datetime(
                    series + "-01",
                    format="%Y-%m-%d",
                    errors="coerce"
                ).dt.to_period("M")
            except Exception:
                pass

        # ============================
        # 6️⃣ Date/Datetime Detection
        # ============================
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
            match_count = sum(
                1 for val in sample
                if re.match(pattern, str(val).strip())
            )

            if len(sample) > 0 and match_count / len(sample) >= 0.7:
                try:
                    # Special handling for YYYY-MM
                    if fmt == "%Y-%m":
                        converted = pd.to_datetime(
                            series + "-01",
                            format="%Y-%m-%d",
                            errors="coerce"
                        ).dt.to_period("M")
                        if converted.notna().sum() > series.notna().sum() * 0.5:
                            return converted
                    else:
                        converted = robust_to_datetime_pandas(series)
                        if converted.notna().sum() > series.notna().sum() * 0.5:
                            return converted
                except Exception:
                    pass

        # ✅ Keep as string
        return series

    # Apply to all columns
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
    """
    Convert Period dtype columns to string before JSON serialization.
    Prevents {} output for Period values.
    """
    for col in df.columns:
        if str(df[col].dtype).startswith("period"):
            df[col] = df[col].astype(str)
    return df


# =============================================
# JSON Safe Converter
# =============================================
def make_json_safe(val):
    """
    Convert all non-JSON-safe types to safe equivalents.
    """
    try:
        if val is None:
            return None

        # ✅ Handle pd.Period → "2024-04"
        if isinstance(val, pd.Period):
            return str(val)

        # ✅ Handle pd.Timestamp → ISO format
        if isinstance(val, pd.Timestamp):
            return val.isoformat()

        # ✅ Handle NaT
        if val is pd.NaT:
            return None

        # ✅ Handle NaN / None
        try:
            if pd.isna(val):
                return None
        except Exception:
            pass

        # ✅ Handle numpy types
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
            return {
                "total_tables": len(tables),
                "tables": tables
            }
    finally:
        conn.close()


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
    group_by=None,
    agg_func: str = "sum"       # ✅ NEW: sum, count, avg, min, max
):
    conn = get_connection()

    try:
        # ✅ Step 1: Read full table
        df = pd.read_sql(f'SELECT * FROM "{table_name}"', conn)

        # ✅ Step 2: Auto convert data types
        df = auto_convert_dtypes(df)

        # ✅ Step 3: Select Columns
        if columns:
            selected_cols = [c.strip() for c in columns.split(",")]
            valid_cols = [c for c in selected_cols if c in df.columns]
            if valid_cols:
                df = df[valid_cols]

        # ✅ Step 4: Value Filter
        if filter_column and filter_value:
            if filter_column in df.columns:
                values = [v.strip() for v in filter_value.split(",")]
                df = df[df[filter_column].astype(str).isin(values)]

        # ✅ Step 5: Date Filter
        if date_column and from_date and to_date:
            if date_column in df.columns:
                if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                    df[date_column] = robust_to_datetime_pandas(df[date_column])
                from_dt = pd.to_datetime(from_date)
                to_dt = pd.to_datetime(to_date)
                df = df[
                    (df[date_column] >= from_dt) &
                    (df[date_column] <= to_dt)
                ]

        # ✅ Step 6: Group By with aggregation
        if group_by:
            group_cols = [c.strip() for c in group_by.split(",")]
            valid_group_cols = [c for c in group_cols if c in df.columns]

            if valid_group_cols:
                numeric_cols = [
                    c for c in df.select_dtypes(include="number").columns
                    if c not in valid_group_cols
                ]

                if numeric_cols:
                    agg_map = {
                        "sum":   "sum",
                        "count": "count",
                        "avg":   "mean",
                        "mean":  "mean",
                        "min":   "min",
                        "max":   "max",
                    }
                    agg = agg_map.get(agg_func.lower(), "sum")

                    df = (
                        df.groupby(valid_group_cols)[numeric_cols]
                        .agg(agg)
                        .reset_index()
                    )
                else:
                    # No numeric columns - just count
                    df = (
                        df.groupby(valid_group_cols)
                        .size()
                        .reset_index(name="count")
                    )

        # ✅ Step 7: Apply limit LAST
        total_rows = len(df)
        df_limited = df.head(limit).copy()

        # ✅ Step 8: Convert Period columns
        df_limited = convert_period_columns(df_limited)

        # ✅ Step 9: JSON safe records
        records = [
            {k: make_json_safe(v) for k, v in row.items()}
            for row in df_limited.to_dict("records")
        ]

        # ✅ Step 10: Dtype info
        dtype_info = {
            col: str(df[col].dtype)
            for col in df.columns
        }

        return {
            "table_name": table_name,
            "total_rows": total_rows,
            "returned_rows": len(records),
            "columns": list(df.columns),
            "dtypes": dtype_info,
            "data": records
        }

    finally:
        conn.close()


# =============================================
# Tally: Monthly Provision XML
# =============================================
def get_monthly_provision_xml(ledger_name, from_date, to_date, period):
    return f"""
    <ENVELOPE>
        <HEADER>
            <TALLYREQUEST>Export Data</TALLYREQUEST>
        </HEADER>
        <BODY>
            <EXPORTDATA>
                <REQUESTDESC>
                    <REPORTNAME>Ledger Monthly Summary</REPORTNAME>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                        <SVFROMDATE>{from_date}</SVFROMDATE>
                        <SVTODATE>{to_date}</SVTODATE>
                        <LEDGERNAME>{ledger_name}</LEDGERNAME>
                        <SVPERIODICITY>{period}</SVPERIODICITY>
                    </STATICVARIABLES>
                </REQUESTDESC>
            </EXPORTDATA>
        </BODY>
    </ENVELOPE>
    """


def fetch_monthly_provision_data(ledger_name, from_date, to_date, period):
    xml_data = get_monthly_provision_xml(ledger_name, from_date, to_date, period)
    response = requests.post(
        TALLY_URL,
        data=xml_data,
        headers={"Content-Type": "application/xml"}
    )
    response.raise_for_status()
    return parse_xml(response.text)


def parse_xml(xml_response):
    root = ET.fromstring(xml_response)
    rows = []
    children = list(root)

    for i in range(0, len(children), 2):
        try:
            if children[i].tag != "DSPPERIOD":
                continue

            period = children[i].text.strip()
            acc_info = children[i + 1]

            debit   = acc_info.findtext("./DSPDRAMT/DSPDRAMTA", default="")
            credit  = acc_info.findtext("./DSPCRAMT/DSPCRAMTA", default="")
            closing = acc_info.findtext("./DSPCLAMT/DSPCLAMTA", default="")

            rows.append({
                "Period": period,
                "DebitAmount": debit,
                "CreditAmount": credit,
                "ClosingAmount": closing
            })
        except Exception:
            continue

    return rows


# =============================================
# Tally: Outstanding Report XML
# =============================================
def get_Outstanding_report(ledger_name, from_date, to_date):
    return f"""
    <ENVELOPE>
        <HEADER>
            <TALLYREQUEST>Export Data</TALLYREQUEST>
        </HEADER>
        <BODY>
            <EXPORTDATA>
                <REQUESTDESC>
                    <REPORTNAME>Ledger Outstandings</REPORTNAME>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                        <SVFROMDATE>{from_date}</SVFROMDATE>
                        <SVTODATE>{to_date}</SVTODATE>
                        <LEDGERNAME>{ledger_name}</LEDGERNAME>
                    </STATICVARIABLES>
                </REQUESTDESC>
            </EXPORTDATA>
        </BODY>
    </ENVELOPE>
    """


def fetch_Outstanding_data(ledger_name, from_date, to_date):
    xml_data = get_Outstanding_report(ledger_name, from_date, to_date)
    response = requests.post(
        TALLY_URL,
        data=xml_data,
        headers={"Content-Type": "application/xml"}
    )
    response.raise_for_status()
    return parse_outstanding_report(response.text)


def parse_outstanding_report(response):
    root = ET.fromstring(response)
    records = []

    bill_fixed_list = root.findall(".//BILLFIXED")
    bill_ops        = root.findall(".//BILLOP")
    bill_cls        = root.findall(".//BILLCL")
    bill_dues       = root.findall(".//BILLDUE")
    bill_overdues   = root.findall(".//BILLOVERDUE")

    for i, bill in enumerate(bill_fixed_list):
        bill_date     = bill.findtext("BILLDATE", "")
        bill_ref      = bill.findtext("BILLREF", "")
        bill_op       = bill_ops[i].text      if i < len(bill_ops)      else ""
        bill_cl       = bill_cls[i].text      if i < len(bill_cls)      else ""
        bill_due      = bill_dues[i].text     if i < len(bill_dues)     else ""
        overdue_days  = bill_overdues[i].text if i < len(bill_overdues) else ""

        records.append({
            "Bill Date":       bill_date,
            "Bill Ref":        bill_ref,
            "Opening Amount":  bill_op,
            "Closing Amount":  bill_cl,
            "Due Date":        bill_due,
            "Overdue Days":    overdue_days
        })

    return records