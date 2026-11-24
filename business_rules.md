# SAP Business One – Business Rules for AI Assistant
> These rules are authoritative. Follow them literally. Apply a rule ONLY when the user's question needs it.

---

## 1. JOIN MAP (Mandatory – No Other Paths Allowed)

**Header → Line joins** (always T0 = header, T1 = line):
- `T0."DocEntry" = T1."DocEntry"`

| Document Type      | Header Table | Line Table |
|--------------------|-------------|------------|
| Sales Invoice      | OINV        | INV1       |
| Sales Return       | ORIN        | RIN1       |
| Purchase Invoice   | OPCH        | PCH1       |
| Purchase Return    | ORPC        | RPC1       |

**Standard joins from line tables:**

| Step | Purpose              | SQL Join                                                        |
|------|----------------------|-----------------------------------------------------------------|
| 1    | Line → Item Master   | `INNER JOIN "OITM" T2 ON T1."ItemCode" = T2."ItemCode"`        |
| 2    | Item → Item Group    | `INNER JOIN "OITB" T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"`   |
| 3    | Line → Warehouse     | `INNER JOIN "OWHS" T4 ON T1."WhsCode" = T4."WhsCode"`         |
| 4    | Warehouse → Location | `INNER JOIN "OLCT" T5 ON T4."Location" = T5."Code"`           |

> **Rule:** OITB is reachable ONLY through OITM. Never join OITB directly to a line table or OIVL.
> **Rule:** Always use OWHS for warehouse, never OBPL.

**Stock (Inventory) joins:**
- `FROM "OIVL" T0 INNER JOIN "OWHS" T1 ON T0."LocCode" = T1."WhsCode"`
- OIVL → Item: `T0."ItemCode" = OITM."ItemCode"`, then OITM → OITB per Step 2.

---

## 2. Field Locations (Custom UDFs)

| Field             | Table | Purpose                                             |
|-------------------|-------|-----------------------------------------------------|
| `"U_GC"`          | OITM  | Group Category (Level 1)                            |
| `"U_HC"`          | OITM  | Head Category (Level 2)                             |
| `"U_SubCategory"` | OITM  | Sub Category (Level 4)                              |
| `"U_SIZE"`        | OITM  | Models / Sizes of Products                          |
| `"U_GProp"`       | OITB  | Main Category (Level 3) – **DEFAULT for "category"**|
| `"U_Brand"`       | OITB  | Brand                                               |
| `"U_IsCenWhs"`    | OWHS  | Central warehouse flag ('Y' / 'N')                  |
| `"U_TranWhs"`     | OWHS  | Transit warehouse identifier                        |
| `"Location"`      | OLCT  | State / Location name                               |

**Category hierarchy:** Level 1 `U_GC` → Level 2 `U_HC` → Level 3 `U_GProp` → Level 4 `U_SubCategory`

- If the user says "category" without specifying a level → use `"U_GProp"` (Level 3).
- If the user names a specific level (e.g., "sub category", "group category") → use that level's field.
- Use these fields ONLY for category, brand, or classification questions. Do not add them to unrelated queries.

---

## 3. Sales and Purchase Logic

- **Sales** = Sales Invoices (OINV/INV1) **minus** Sales Returns (ORIN/RIN1).
- **Purchases** = Purchase Invoices (OPCH/PCH1) **minus** Purchase Returns (ORPC/RPC1).
- Unqualified "sales" or "purchases" always means invoices minus returns.
- Show invoices or returns alone ONLY when the user explicitly asks.

**Amount fields:**
- `"GTotal"` = row-level with-tax amount (on INV1, RIN1, PCH1, RPC1). **Use this by default.**
- `"LineTotal"` = use ONLY if the user asks for "without tax", "pre-tax", "excluding GST", or "taxable value".
- **Never use** `"DocTotal"` (header-level). Never sum header amounts after joining lines.
- **Never** add `"LineTotal"` + `"VatSum"`. Use the same field on both invoice and return parts.

**UNION ALL pattern (mandatory for net calculations):**
- Stack invoices (positive) and returns (negative with minus sign) in a derived table using `UNION ALL`.
- Aggregate ONCE in the outer query.
- Apply identical `"DocDate"`, `"CANCELED" = 'N'`, and all other filters to BOTH parts.
- For breakdowns, include the same dimension column in BOTH inner SELECTs with the same alias.
- Alias scope: T0, T1, T2... exist only inside each inner SELECT. The outer query uses only the derived table alias `T`.
- For sales queries, add `"DocType" = 'I'` on BOTH parts.
- Credit memos are stored positive → subtract them. Never add a return or subtract an already-negative one.

---

## 4. Inventory (Stock)

- Use **OIVL** for all stock quantity and value questions.
- Quantity = `SUM("InQty" - "OutQty")`
- Value = `SUM("SumStock")` — Never use `"TransValue"`.
- "As of" date: `"DocDate" <= 'YYYYMMDD'` (the as-of date).
- By branch or warehouse: use the Stock join (OIVL → OWHS).

---

## 5. Branch and Warehouse

- Warehouses are in **OWHS**; state comes from **OLCT** via `"Location"` (Join Step 4).
- Branch/warehouse names from the dictionary are always `OWHS."WhsName"`, never `"WhsCode"`.
- `"U_IsCenWhs"` ('Y'/'N'): use ONLY for central vs. non-central warehouse questions.
- `"U_TranWhs"`: use ONLY when transit warehouses must be included or excluded.

---

## 6. Synonyms

| User may say                             | Means the same entity |
|------------------------------------------|-----------------------|
| "television", "TV", "pannel", "panel"    | Same category – resolve via dictionary tool |
| "AIR COND", "AC", "air conditioner", "AIRCONDITIONER" | Same category – resolve via dictionary tool |

Always resolve the exact database value through the `search_dictionary` tool. Never hardcode or guess.

---

## 7. Reference SQL Patterns

### Pattern A: Net Sales for a Category in a Date Range
```sql
SELECT
  SUM(T."Amount") AS "Sales"
FROM (
  SELECT T1."GTotal" AS "Amount"
  FROM "OINV" T0
  INNER JOIN "INV1" T1 ON T0."DocEntry" = T1."DocEntry"
  INNER JOIN "OITM" T2 ON T1."ItemCode" = T2."ItemCode"
  INNER JOIN "OITB" T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"
  WHERE T0."CANCELED" = 'N' AND T0."DocType" = 'I'
    AND T3."U_GProp" = 'X'
    AND T0."DocDate" >= '20261001' AND T0."DocDate" <= '20261031'
  UNION ALL
  SELECT -T1."GTotal" AS "Amount"
  FROM "ORIN" T0
  INNER JOIN "RIN1" T1 ON T0."DocEntry" = T1."DocEntry"
  INNER JOIN "OITM" T2 ON T1."ItemCode" = T2."ItemCode"
  INNER JOIN "OITB" T3 ON T2."ItmsGrpCod" = T3."ItmsGrpCod"
  WHERE T0."CANCELED" = 'N' AND T0."DocType" = 'I'
    AND T3."U_GProp" = 'X'
    AND T0."DocDate" >= '20261001' AND T0."DocDate" <= '20261031'
) T
```
For "sales by category": remove the `'X'` filter, add `T3."U_GProp" AS "Category"` to BOTH inner SELECTs, then `SELECT T."Category", SUM(T."Amount") ... GROUP BY T."Category"` in the outer query.

Purchases: same pattern with OPCH/PCH1 (positive) and ORPC/RPC1 (negated), without the DocType condition.

### Pattern B: Stock Quantity and Value by Warehouse (As-of Date)
```sql
SELECT
  T1."WhsName" AS "Warehouse",
  SUM(T0."InQty" - T0."OutQty") AS "StockQty",
  SUM(T0."SumStock") AS "StockValue"
FROM "OIVL" T0
INNER JOIN "OWHS" T1 ON T0."LocCode" = T1."WhsCode"
WHERE T0."DocDate" <= '20261120'
GROUP BY T1."WhsName"
```
