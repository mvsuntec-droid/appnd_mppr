import streamlit as st
import pandas as pd
import numpy as np
import io

# -------------------------------------------------
# BASIC PAGE CONFIG
# -------------------------------------------------
st.set_page_config(page_title="appen-mapper", layout="wide")

# -------------------------------------------------
# SIMPLE AUTH (USERNAME / PASSWORD)
# -------------------------------------------------
VALID_USERNAME = "matt"
VALID_PASSWORD = "Interlynx123"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("appen-mapper – Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login_btn = st.button("Login")

    if login_btn:
        if username == VALID_USERNAME and password == VALID_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.stop()

# -------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------


def normalize_customer_id(value):
    """
    Normalize Customer Number/ID so that small formatting differences
    (commas, floats) do not break the join.
    """
    if pd.isna(value):
        return None
    s = str(value).strip()
    s = s.replace(",", "")
    try:
        num = int(float(s))
        return str(num)
    except Exception:
        return s


def read_any_table(uploaded_file):
    """
    Read CSV or Excel into a DataFrame.
    CSVs are tried with UTF-8 first, then latin-1, then latin-1 with errors='ignore'
    to avoid UnicodeDecodeError.
    """
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        # Try UTF-8
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="utf-8")
        except UnicodeDecodeError:
            # Try latin-1
            try:
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, encoding="latin-1")
            except UnicodeDecodeError:
                # Last resort: ignore errors
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, encoding="latin-1", errors="ignore")
    else:
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file)


def apply_mapping(df1, df2):
    """
    Map columns from df1 -> df2 based on Customer Number/ID.

    df1 columns (source):
        Customer Number/ID, Company, Address, City, State, ZipCode, Country,
        PhoneResearched, DUNSNumber, LineOfBusiness, SIC, NAICS,
        Parent_Name, WebAddress, ContactPhone

    df2 columns (target) must include:
        Customer Number/ID, Company, Address, City, State, ZipCode, Country,
        PhoneResearched, Duns, LineOfBusiness, SIC, NAICS,
        ParentName, Webaddress, ContactPhone
    """
    df1 = df1.copy()
    df2 = df2.copy()

    # Clean column names (strip spaces)
    df1.columns = [c.strip() for c in df1.columns]
    df2.columns = [c.strip() for c in df2.columns]

    id_col = "Customer Number/ID"
    if id_col not in df1.columns or id_col not in df2.columns:
        st.error(f"Both files must contain column '{id_col}'.")
        return df2, {}

    # Normalize IDs for robust matching
    df1["_id_norm"] = df1[id_col].apply(normalize_customer_id)
    df2["_id_norm"] = df2[id_col].apply(normalize_customer_id)

    # Stats BEFORE mapping (based on df2)
    total_rows_2 = len(df2)
    unique_ids_2 = df2["_id_norm"].nunique(dropna=True)

    # Which df2 rows have a match in df1?
    id_set_1 = set(df1["_id_norm"].dropna())
    mask_mapped = df2["_id_norm"].isin(id_set_1)

    total_mapped_rows = int(mask_mapped.sum())
    total_unmapped_rows = int(total_rows_2 - total_mapped_rows)
    unique_ids_mapped = df2.loc[mask_mapped, "_id_norm"].nunique(dropna=True)
    unique_ids_unmapped = df2.loc[~mask_mapped, "_id_norm"].nunique(dropna=True)

    stats = {
        "total_rows_file2": int(total_rows_2),
        "unique_ids_file2": int(unique_ids_2),
        "total_mapped_rows": total_mapped_rows,
        "total_unmapped_rows": total_unmapped_rows,
        "unique_ids_mapped": int(unique_ids_mapped),
        "unique_ids_unmapped": int(unique_ids_unmapped),
    }

    # ---- Build df1 indexed by normalized ID, using LAST record per ID ----
    df1_dedup = df1.drop_duplicates(subset=["_id_norm"], keep="last")
    df1_indexed = df1_dedup.set_index("_id_norm")

    # Map from df1 col -> df2 col
    mapping_pairs = {
        "Company": "Company",
        "Address": "Address",
        "City": "City",
        "State": "State",
        "ZipCode": "ZipCode",
        "Country": "Country",
        "PhoneResearched": "PhoneResearched",
        "DUNSNumber": "Duns",          # different column name in file 2
        "LineOfBusiness": "LineOfBusiness",
        "SIC": "SIC",
        "NAICS": "NAICS",
        "Parent_Name": "ParentName",   # different name in file 2
        "WebAddress": "Webaddress",    # case difference in file 2
        "ContactPhone": "ContactPhone",
    }

    for src_col, tgt_col in mapping_pairs.items():
        if src_col not in df1_indexed.columns:
            continue
        if tgt_col not in df2.columns:
            continue

        series_map = df1_indexed[src_col]  # unique index thanks to dedup
        mapped = df2["_id_norm"].map(series_map)

        df2[tgt_col] = mapped.combine_first(df2[tgt_col])

    # Drop helper columns from both frames
    df1.drop(columns=["_id_norm"], inplace=True)
    df2.drop(columns=["_id_norm"], inplace=True)

    return df2, stats


# -------------------------------------------------
# MAIN APP UI
# -------------------------------------------------

st.title("appen-mapper")

col_upload1, col_upload2 = st.columns(2)

with col_upload1:
    st.subheader("Step 1 – Upload Master Customer File (File 1)")
    file1 = st.file_uploader(
        "File 1 (Customer master: Customer Number/ID, Company, Address, ...)",
        type=["xlsx", "xls", "csv"],
        key="file1",
    )

with col_upload2:
    st.subheader("Step 2 – Upload Data File (File 2)")
    file2 = st.file_uploader(
        "File 2 (Quotes/data with Customer Number/ID)",
        type=["xlsx", "xls", "csv"],
        key="file2",
    )

st.markdown("---")

run_btn = st.button("Run Mapping and Generate Updated File")

if run_btn:
    if file1 is None or file2 is None:
        st.error("Please upload both File 1 and File 2 before running the mapper.")
    else:
        # Read files only once, in memory
        df1 = read_any_table(file1)
        df2 = read_any_table(file2)

        updated_df, stats = apply_mapping(df1, df2)

        # Display statistics in a compact way
        st.subheader("Mapping Summary")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("File 2 – Total Records", stats["total_rows_file2"])
            st.metric("File 2 – Unique Customers", stats["unique_ids_file2"])
        with c2:
            st.metric("Mapped Rows", stats["total_mapped_rows"])
            st.metric("Mapped Unique Customers", stats["unique_ids_mapped"])
        with c3:
            st.metric("Unmapped Rows", stats["total_unmapped_rows"])
            st.metric("Unmapped Unique Customers", stats["unique_ids_unmapped"])

        st.subheader("Preview of Updated Data")
        st.dataframe(updated_df.head(20), use_container_width=True, height=300)

        # Prepare updated file as Excel for download (in memory only)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            updated_df.to_excel(writer, index=False, sheet_name="UpdatedData")
        buffer.seek(0)

        st.download_button(
            label="Download Updated File 2",
            data=buffer,
            file_name="appen_mapper_updated_file2.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
