
from logging import root
from turtle import pd
from urllib import response
import pandas as pd
from psycopg2 import sql
import os
import psycopg2
from dotenv import load_dotenv

import requests
import xml.etree.ElementTree as ET
import csv
load_dotenv()
TALLY_URL="https://obeyable-celina-provisorily.ngrok-free.dev"

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )




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

            tables = [

                row[0]

                for row in rows
            ]

            return {

                "total_tables": len(tables),

                "tables": tables
            }

    finally:

        conn.close()


def get_table_data(table_name: str, limit: int = 100):

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            query = sql.SQL("""
                SELECT *
                FROM {}
                LIMIT %s;
            """).format(sql.Identifier(table_name))

            cur.execute(query, (limit,))

            rows = cur.fetchall()

            columns = [desc[0] for desc in cur.description]

            data = [
                dict(zip(columns, row))
                for row in rows
            ]

            return {
                "table_name": table_name,
                "total_rows": len(data),
                "columns": columns,
                "data": data
            }

    finally:

        conn.close()

def get_monthly_provision_xml(
    ledger_name,
    from_date,
    to_date,
    period
):

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


def fetch_monthly_provision_data(
    ledger_name,
    from_date,
    to_date,
    period
):

    xml_data = get_monthly_provision_xml(
        ledger_name,
        from_date,
        to_date,
        period
    )

    response = requests.post(
        TALLY_URL,
        data=xml_data,
        headers={
            "Content-Type": "application/xml"
        }
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

            debit = acc_info.findtext(
                "./DSPDRAMT/DSPDRAMTA",
                default=""
            )

            credit = acc_info.findtext(
                "./DSPCRAMT/DSPCRAMTA",
                default=""
            )

            closing = acc_info.findtext(
                "./DSPCLAMT/DSPCLAMTA",
                default=""
            )

            rows.append({
                "Period": period,
                "DebitAmount": debit,
                "CreditAmount": credit,
                "ClosingAmount": closing
            })

        except Exception:
            continue

    return rows





def get_Outstanding_report(
    ledger_name,
    from_date,
    to_date,

):

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

def fetch_Outstanding_data(
    ledger_name,
    from_date,
    to_date,

):

    xml_data = get_Outstanding_report(
        ledger_name,
        from_date,
        to_date,

    )

    response = requests.post(
        TALLY_URL,
        data=xml_data,
        headers={
            "Content-Type": "application/xml"
        }
    )

    response.raise_for_status()

    return parse_outstanding_report(response.text)

def parse_outstanding_report(response):
    root = ET.fromstring(response)
    records = []

    # Get all BILLFIXED nodes
    bill_fixed_list = root.findall(".//BILLFIXED")

    # Get parallel fields
    bill_ops = root.findall(".//BILLOP")
    bill_cls = root.findall(".//BILLCL")
    bill_dues = root.findall(".//BILLDUE")
    bill_overdues = root.findall(".//BILLOVERDUE")

    # Loop through all bills
    for i, bill in enumerate(bill_fixed_list):

        bill_date = bill.findtext("BILLDATE", "")
        bill_ref = bill.findtext("BILLREF", "")

        bill_op = bill_ops[i].text if i < len(bill_ops) else ""
        bill_cl = bill_cls[i].text if i < len(bill_cls) else ""
        bill_due = bill_dues[i].text if i < len(bill_dues) else ""
        overdue_days = bill_overdues[i].text if i < len(bill_overdues) else ""

        records.append({
            "Bill Date": bill_date,
            "Bill Ref": bill_ref,
            "Opening Amount": bill_op,
            "Closing Amount": bill_cl,
            "Due Date": bill_due,
            "Overdue Days": overdue_days
        })

    return records