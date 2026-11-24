import os
import requests
import json
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()

COMPANY_API_URL = os.getenv("COMPANY_API_URL")


if not COMPANY_API_URL:
    print("❌ ERROR: COMPANY_API_URL is missing from your .env file.")
    exit()

print("🚀 Starting standalone SAP network test...\n")

# 2. Setup the connection pool
test_session = requests.Session()

# 3. A safe, lightweight test query
#test_query = "SELECT    SUM(\"Sales\") - SUM(\"Returns\") AS \"Net Sales\" FROM (   SELECT      SUM(T1.\"GTotal\") AS \"Sales\",     0.0 AS \"Returns\"   FROM OINV T0   INNER JOIN INV1 T1 ON T0.\"DocEntry\" = T1.\"DocEntry\"   INNER JOIN OITM T2 ON T1.\"ItemCode\" = T2.\"ItemCode\"   INNER JOIN OITB T3 ON T2.\"ItmsGrpCod\" = T3.\"ItmsGrpCod\"   WHERE T0.\"DocDate\" >= '2026-04-01'      AND T0.\"DocDate\" <= '2026-04-30'     AND T0.\"CANCELED\" = 'N'     AND T3.\"U_GProp\" = 'MOBILE'      UNION ALL      SELECT      0.0 AS \"Sales\",     SUM(T1.\"GTotal\") AS \"Returns\"   FROM ORIN T0   INNER JOIN RIN1 T1 ON T0.\"DocEntry\" = T1.\"DocEntry\"   INNER JOIN OITM T2 ON T1.\"ItemCode\" = T2.\"ItemCode\"   INNER JOIN OITB T3 ON T2.\"ItmsGrpCod\" = T3.\"ItmsGrpCod\"   WHERE T0.\"DocDate\" >= '2026-04-01'      AND T0.\"DocDate\" <= '2026-04-30'     AND T0.\"CANCELED\" = 'N'     AND T3.\"U_GProp\" = 'MOBILE' ) AS S "
#test_query = """SELECT SUM(Sales) - SUM(Returns) AS TotalSales FROM ( SELECT SUM(INV1."GTotal") AS Sales, 0 AS Returns FROM OINV INNER JOIN INV1 ON OINV."DocEntry" = INV1."DocEntry" INNER JOIN OITM ON INV1."ItemCode" = OITM."ItemCode" INNER JOIN OITB ON OITM."ItmsGrpCod" = OITB."ItmsGrpCod" WHERE OITB."U_GProp" = 'MOBILE' AND OINV."DocDate" >= '2026-04-01' AND OINV."DocDate" <= '2026-04-30' AND OINV."CANCELED" = 'N' UNION ALL SELECT 0 AS Sales, SUM(RIN1."GTotal") AS Returns FROM ORIN INNER JOIN RIN1 ON ORIN."DocEntry" = RIN1."DocEntry" INNER JOIN OITM ON RIN1."ItemCode" = OITM."ItemCode" INNER JOIN OITB ON OITM."ItmsGrpCod" = OITB."ItmsGrpCod" WHERE OITB."U_GProp" = 'MOBILE' AND ORIN."DocDate" >= '2026-04-01' AND ORIN."DocDate" <= '2026-04-30' AND ORIN."CANCELED" = 'N' )"""
#test_query = """SELECT SUM(Sales) - SUM(Returns) AS TotalSales FROM (SELECT SUM(T1."GTotal") AS Sales, 0 AS Returns FROM OINV T0 INNER JOIN INV1 T1 ON T0."DocEntry" = T1."DocEntry" INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode" INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod" WHERE T3."U_GProp" = 'MOBILE' AND T0."DocDate" >= '2026-04-01' AND T0."DocDate" <= '2026-04-30' AND T0."CANCELED" = 'N' UNION ALL SELECT 0 AS Sales, SUM(T1."GTotal") AS Returns FROM ORIN T0 INNER JOIN RIN1 T1 ON T0."DocEntry" = T1."DocEntry" INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode" INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod" WHERE T3."U_GProp" = 'MOBILE' AND T0."DocDate" >= '2026-04-01' AND T0."DocDate" <= '2026-04-30' AND T0."CANCELED" = 'N') AS S"""
#test_query= """SELECT    SUM("Sales") - SUM("Returns") AS "Net Sales" FROM (   SELECT      SUM(T1."GTotal") AS "Sales",     0.0 AS "Returns"   FROM OINV T0   INNER JOIN INV1 T1 ON T0."DocEntry" = T1."DocEntry"   INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode"   INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"   WHERE T0."DocDate" >= '2026-04-01'      AND T0."DocDate" <= '2026-04-30'     AND T0."CANCELED" = 'N'     AND T3."U_GProp" = 'MOBILE'      UNION ALL      SELECT      0.0 AS "Sales",     SUM(T1."GTotal") AS "Returns"   FROM ORIN T0   INNER JOIN RIN1 T1 ON T0."DocEntry" = T1."DocEntry"   INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode"   INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"   WHERE T0."DocDate" >= '2026-04-01'      AND T0."DocDate" <= '2026-04-30'     AND T0."CANCELED" = 'N'     AND T3."U_GProp" = 'MOBILE' ) AS S """
#test_query = """SELECT SUM("Sales") - SUM("Returns") AS "Net Sales" FROM (SELECT SUM(T1."GTotal") AS "Sales", 0 AS "Returns" FROM OINV T0 INNER JOIN INV1 T1 ON T0."DocEntry" = T1."DocEntry" INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode" INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod" WHERE T3."U_GProp" = 'MOBILE' AND T0."DocDate" >= '2026-10-01' AND T0."DocDate" <= '2026-10-31' AND T0."CANCELED" = 'N' UNION ALL SELECT 0 AS "Sales", SUM(T1."GTotal") AS "Returns" FROM ORIN T0 INNER JOIN RIN1 T1 ON T0."DocEntry" = T1."DocEntry" INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode" INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod" WHERE T3."U_GProp" = 'MOBILE' AND T0."DocDate" >= '2026-10-01' AND T0."DocDate" <= '2026-10-31' AND T0."CANCELED" = 'N') AS S"""
#test_query= """SELECT SUM("Sales") - SUM("Returns") AS "Net Sales" FROM (SELECT SUM(T1."GTotal") AS "Sales", 0.0 AS "Returns" FROM OINV T0 INNER JOIN INV1 T1 ON T0."DocEntry" = T1."DocEntry" INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode" INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod" WHERE T0."CANCELED" = 'N' AND T0."DocDate" >= '2026-10-01' AND T0."DocDate" <= '2026-10-31' AND T3."U_GProp" = 'MOBILE' UNION ALL SELECT 0.0 AS "Sales", SUM(T1."GTotal") AS "Returns" FROM ORIN T0 INNER JOIN RIN1 T1 ON T0."DocEntry" = T1."DocEntry" INNER JOIN OITM T2 ON T1."ItemCode" = T2."ItemCode" INNER JOIN OITB T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod" WHERE T0."CANCELED" = 'N' AND T0."DocDate" >= '2026-10-01' AND T0."DocDate" <= '2026-10-31' AND T3."U_GProp" = 'MOBILE') AS S"""
test_query = """SELECT 
    T0."U_Brand" AS "Brand",
    SUM(T0."GTotal") AS "Total_Sales"
FROM (
    SELECT 
        T3."U_Brand",
        T1."GTotal"
    FROM "OINV" T0
    INNER JOIN "INV1" T1 ON T0."DocEntry" = T1."DocEntry"
    INNER JOIN "OITM" T2 ON T1."ItemCode" = T2."ItemCode"
    INNER JOIN "OITB" T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"
    INNER JOIN "OWHS" T4 ON T1."WhsCode" = T4."WhsCode"
    INNER JOIN "OLCT" T5 ON T4."Location" = T5."Code"
    WHERE T0."DocDate" >= '2025-01-01'
    AND T0."DocDate" <= '2025-12-31'
    AND T0."CANCELED" = 'N'
    AND T3."U_GProp" = 'PANEL'
    AND T5."Location" = 'Telangana'
    UNION ALL
    SELECT 
        T3."U_Brand",
        -T1."GTotal"
    FROM "ORIN" T0
    INNER JOIN "RIN1" T1 ON T0."DocEntry" = T1."DocEntry"
    INNER JOIN "OITM" T2 ON T1."ItemCode" = T2."ItemCode"
    INNER JOIN "OITB" T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"
    INNER JOIN "OWHS" T4 ON T1."WhsCode" = T4."WhsCode"
    INNER JOIN "OLCT" T5 ON T4."Location" = T5."Code"
    WHERE T0."DocDate" >= '2025-01-01'
    AND T0."DocDate" <= '2025-12-31'
    AND T0."CANCELED" = 'N'
    AND T3."U_GProp" = 'PANEL'
    AND T5."Location" = 'Telangana'
) T0
GROUP BY T0."U_Brand"
ORDER BY "Total_Sales" DESC
LIMIT 5"""
# 4. Apply Fix #1: The Firewall Bypass (URL Encoding)
#encoded_query = urllib.parse.quote(test_query)
#exact_url = f"{COMPANY_API_URL}?query={encoded_query}"

# 5. Apply Fix #3: The Speed Fix (Browser mimic and Gzip compression without 'br')
print("="*50)
print(f"📡 TARGET URL: {COMPANY_API_URL}")
print("="*50 + "\n")
headers = {
            "QIKCHAT-API-KEY": "YOUR_API_KEY",
            "Content-Type": "text/plain"
        }
try:
    # 6. Execute the direct network call
    response = test_session.post(
            COMPANY_API_URL,
            headers=headers,
            data=test_query,
            timeout=120
        )
    
    print(f"✅ SAP HTTP STATUS: {response.status_code}")
    response.raise_for_status()
    
    data = response.json()
    
    print("\n🎉 CONNECTION SUCCESSFUL! Here is the raw SAP data:")
    print(json.dumps(data, indent=2)[:500]) # Print first 500 characters to keep terminal clean
    print("\n(Data truncated for readability)")

except requests.exceptions.Timeout:
    print("\n❌ TEST FAILED: The connection timed out.")
    print("This means the firewall blocked the request silently, or the background dictionary thread is choking the network.")
except requests.exceptions.RequestException as e:
    print(f"\n❌ TEST FAILED: Network error - {str(e)}")
except json.JSONDecodeError:
    print("\n❌ TEST FAILED: SAP did not return valid JSON. The firewall might be sending an HTML block page.")
    print(f"Raw Response: {response.text[:200]}")