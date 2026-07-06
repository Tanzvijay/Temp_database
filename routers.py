from fastapi import APIRouter
from typing import Optional

from repo import (
 
    list_database_tables_agent,
    get_table_data,
  
    get_unique_column_values,
)

router = APIRouter()


@router.get("/tables/")
def list_tables():
    return list_database_tables_agent()




@router.get("/tables/{table_name}/data/")
def get_table_data_endpoint(
    table_name: str,
    limit: int = 100,
    columns: Optional[str] = None,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    date_column: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
  
    # ── NEW ─────────────────────────────────────────────────────────────
    filename: Optional[str] = None,         # saves filtered result as CSV
    save_to_db: bool = False,               # saves filtered result to PostgreSQL
    save_table_name: Optional[str] = None,  # target table (required if save_to_db=True)
    if_exists: Optional[str] = "replace",   # "replace" | "append" | "fail"
):
    """
    Fetch (and optionally filter/aggregate) data from a PostgreSQL table.

    Extra parameters
    ----------------
    filename        : str  – If provided, the *full filtered* dataset (before `limit`)
                             is saved as a CSV file at this path on the server.
                             A `.csv` extension is appended automatically if missing.
                             Example: `filename=sales_2024`

    save_to_db      : bool – If true, the *full filtered* dataset is written back
                             to PostgreSQL as a new (or existing) table.
                             Requires `save_table_name`.

    save_table_name : str  – Name of the destination PostgreSQL table.
                             Required when `save_to_db=true`.

    if_exists       : str  – What to do if the destination table already exists.
                             One of: "replace" (default), "append", "fail".
    """
    return get_table_data(
        table_name=table_name,
        limit=limit,
        columns=columns,
        filter_column=filter_column,
        filter_value=filter_value,
        date_column=date_column,
        from_date=from_date,
        to_date=to_date,

        # ── NEW ──────────────────
        filename=filename,
        save_to_db=save_to_db,
        save_table_name=save_table_name,
        if_exists=if_exists,
    )



@router.get("/tables/{table_name}/unique-values/")
def get_unique_values_endpoint(
    table_name: str,
    column: str,
):
    """
    Returns all unique (distinct) values for a given column in a table.

    Parameters
    ----------
    table_name : str – Name of the PostgreSQL table.
    column     : str – Column name to get unique values from.
    """
    return get_unique_column_values(table_name=table_name, column=column)