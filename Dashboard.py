import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import pdfplumber
import requests
import re
from datetime import datetime, date
from io import BytesIO

st.set_page_config(page_title="RM Portfolio Dashboard", layout="wide", page_icon="📊")

st.markdown("""
<style>
.main-header {font-size:2rem; font-weight:700; color:#1A3C6E; margin-bottom:0}
.sub-header {font-size:0.9rem; color:#888; margin-bottom:1.5rem}
.stTabs [data-baseweb="tab-list"] {gap: 8px}
.stTabs [data-baseweb="tab"] {padding: 8px 20px; border-radius: 8px}
.badge-ltcg {background:#EAF3DE; color:#3B6D11; padding:2px 8px; border-radius:6px; font-size:12px}
.badge-stcg {background:#FAEEDA; color:#854F0B; padding:2px 8px; border-radius:6px; font-size:12px}
.badge-gain {background:#EAF3DE; color:#3B6D11; padding:2px 8px; border-radius:6px; font-size:12px}
.badge-loss {background:#FCEBEB; color:#A32D2D; padding:2px 8px; border-radius:6px; font-size:12px}
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">RM Portfolio Intelligence Dashboard</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">ICICI Prudential AMC — Decision Support Tool</p>', unsafe_allow_html=True)

CAT_TYPE = {
    "Large Cap":"Equity","Mid Cap":"Equity","Small Cap":"Equity",
    "Flexi Cap":"Equity","ELSS":"Equity","Index":"Equity",
    "Large & Mid Cap":"Equity","Multi Cap":"Equity","Value Fund":"Equity",
    "Focused Fund":"Equity","Sectoral/Thematic":"Equity",
    "Debt":"Debt","Liquid":"Debt","Ultra Short":"Debt","Short Duration":"Debt",
    "Medium Duration":"Debt","Long Duration":"Debt","Gilt":"Debt","Credit Risk":"Debt",
    "Hybrid":"Hybrid","Balanced Advantage":"Hybrid","Aggressive Hybrid":"Hybrid",
    "Conservative Hybrid":"Hybrid","Arbitrage":"Hybrid","Other":"Other"
}

STCG_RATE = 0.20
LTCG_RATE = 0.125
LTCG_EXEMPT = 125000

# ── SESSION STATE ──
for key in ["folios","tax_entries","risk_entries","parsed_data"]:
    if key not in st.session_state:
        st.session_state[key] = []

# ── PDF PARSER ──
def parse_cams_ecas(pdf_file):
    entries = []
    try:
        with pdfplumber.open(pdf_file) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() or ""

        lines = full_text.split('\n')
        current_fund = None
        current_cat = "Other"
        isin = None

        fund_pattern = re.compile(r'^([A-Z][A-Za-z\s\-&]+(?:Fund|Scheme|Plan|Growth|Dividend|Direct|Regular).*?)(?:\s+\(|$)', re.IGNORECASE)
        isin_pattern = re.compile(r'ISIN\s*[:\-]?\s*([A-Z]{2}[A-Z0-9]{10})', re.IGNORECASE)
        nav_pattern = re.compile(r'NAV\s+(?:on\s+\d{2}[-/]\w+[-/]\d{4})?\s*[:\-]?\s*(?:INR\s*)?(\d+\.?\d*)', re.IGNORECASE)
        units_pattern = re.compile(r'(?:Closing\s+)?(?:Balance\s+)?Units?\s*[:\-]?\s*(\d[\d,]*\.?\d*)', re.IGNORECASE)
        invested_pattern = re.compile(r'(?:Cost\s+Value|Invested\s+Value|Purchase\s+Value|Amount\s+Invested)\s*[:\-]?\s*(?:INR\s*)?(\d[\d,]*\.?\d*)', re.IGNORECASE)
        current_val_pattern = re.compile(r'(?:Market\s+Value|Current\s+Value|Valuation)\s*[:\-]?\s*(?:INR\s*)?(\d[\d,]*\.?\d*)', re.IGNORECASE)
        date_pattern = re.compile(r'(\d{2}[-/]\w{3}[-/]\d{4}|\d{2}[-/]\d{2}[-/]\d{4})')

        # Try table extraction first
        for page in pdfplumber.open(pdf_file).pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row:
                        continue
                    row_clean = [str(c).strip() if c else "" for c in row]
                    row_text = " ".join(row_clean)
                    if len(row_clean) >= 4:
                        # Try to detect fund rows with values
                        nums = [c for c in row_clean if re.match(r'^\d[\d,]*\.?\d*$', c.replace(',',''))]
                        if len(nums) >= 2 and row_clean[0] and len(row_clean[0]) > 5:
                            fund_name = row_clean[0]
                            try:
                                vals = [float(n.replace(',','')) for n in nums]
                                entries.append({
                                    "Fund Name": fund_name,
                                    "Category": detect_category(fund_name),
                                    "Invested (₹)": vals[0] if len(vals) > 1 else 0,
                                    "Current Value (₹)": vals[-1],
                                    "ISIN": "",
                                    "Purchase Date": "",
                                    "Units": vals[1] if len(vals) > 2 else 0,
                                    "NAV": 0,
                                    "Source": "table"
                                })
                            except:
                                pass

        # Text-based fallback extraction
        if not entries:
            i = 0
            while i < len(lines):
                line = lines[i].strip()

                isin_match = isin_pattern.search(line)
                if isin_match:
                    isin = isin_match.group(1)

                if any(kw in line.upper() for kw in ['FUND', 'SCHEME', 'PLAN']) and len(line) > 20:
                    potential_fund = line.split('(')[0].strip()
                    if len(potential_fund) > 10:
                        current_fund = potential_fund
                        current_cat = detect_category(current_fund)

                if current_fund:
                    invested_match = invested_pattern.search(line)
                    curr_match = current_val_pattern.search(line)
                    units_match = units_pattern.search(line)
                    nav_match = nav_pattern.search(line)

                    if invested_match and curr_match:
                        invested = float(invested_match.group(1).replace(',',''))
                        curr_val = float(curr_match.group(1).replace(',',''))
                        units_val = float(units_match.group(1).replace(',','')) if units_match else 0
                        nav_val = float(nav_match.group(1).replace(',','')) if nav_match else 0

                        # Look for purchase date
                        pdate = ""
                        for nearby_line in lines[max(0,i-5):i+5]:
                            dm = date_pattern.search(nearby_line)
                            if dm:
                                pdate = dm.group(1)
                                break

                        entries.append({
                            "Fund Name": current_fund,
                            "Category": current_cat,
                            "Invested (₹)": invested,
                            "Current Value (₹)": curr_val,
                            "ISIN": isin or "",
                            "Purchase Date": pdate,
                            "Units": units_val,
                            "NAV": nav_val,
                            "Source": "text"
                        })
                        current_fund = None
                        isin = None

                i += 1

    except Exception as e:
        st.error(f"PDF parsing error: {e}")

    return entries

def detect_category(fund_name):
    name_upper = fund_name.upper()
    if any(k in name_upper for k in ['LIQUID','OVERNIGHT','MONEY MARKET']): return 'Liquid'
    if any(k in name_upper for k in ['GILT','GSEC','G-SEC']): return 'Gilt'
    if any(k in name_upper for k in ['DEBT','BOND','INCOME','CREDIT','DURATION','BANKING AND PSU']): return 'Debt'
    if any(k in name_upper for k in ['HYBRID','BALANCED','EQUITY SAVINGS','ARBITRAGE']): return 'Hybrid'
    if any(k in name_upper for k in ['ELSS','TAX','80C']): return 'ELSS'
    if any(k in name_upper for k in ['INDEX','NIFTY','SENSEX','ETF','NASDAQ','S&P']): return 'Index'
    if 'SMALL' in name_upper and 'CAP' in name_upper: return 'Small Cap'
    if 'MID' in name_upper and 'CAP' in name_upper: return 'Mid Cap'
    if 'LARGE' in name_upper and 'MID' in name_upper: return 'Large & Mid Cap'
    if 'LARGE' in name_upper and 'CAP' in name_upper: return 'Large Cap'
    if any(k in name_upper for k in ['FLEXI','MULTI','DIVERSIFIED']): return 'Flexi Cap'
    if 'SECTORAL' in name_upper or 'THEMATIC' in name_upper: return 'Sectoral/Thematic'
    return 'Flexi Cap'

# ── MFAPI FUNCTIONS ──
@st.cache_data(ttl=3600)
def get_fund_nav_history(isin):
    try:
        r = requests.get("https://api.mfapi.in/mf/search", params={"q": isin}, timeout=10)
        if r.status_code == 200:
            results = r.json()
            if results:
                scheme_code = results[0]['schemeCode']
                nav_url = f"https://api.mfapi.in/mf/{scheme_code}"
                nr = requests.get(nav_url, timeout=10)
                if nr.status_code == 200:
                    data = nr.json()
                    navs = data.get('data', [])
                    return navs, data.get('meta', {}).get('scheme_name', '')
    except:
        pass
    return [], ""

@st.cache_data(ttl=3600)
def get_fund_by_name(fund_name):
    try:
        r = requests.get("https://api.mfapi.in/mf/search", params={"q": fund_name[:30]}, timeout=10)
        if r.status_code == 200:
            results = r.json()
            if results:
                scheme_code = results[0]['schemeCode']
                nr = requests.get(f"https://api.mfapi.in/mf/{scheme_code}", timeout=10)
                if nr.status_code == 200:
                    data = nr.json()
                    return data.get('data', []), data.get('meta', {}).get('scheme_name',''), scheme_code
    except:
        pass
    return [], "", None

def calculate_returns_and_std(nav_history):
    if len(nav_history) < 30:
        return None, None, None
    try:
        df = pd.DataFrame(nav_history)
        df['nav'] = pd.to_numeric(df['nav'], errors='coerce')
        df['date'] = pd.to_datetime(df['date'], format='%d-%m-%Y', errors='coerce')
        df = df.dropna().sort_values('date')
        df['daily_return'] = df['nav'].pct_change()
        df = df.dropna()
        std_annual = df['daily_return'].std() * np.sqrt(252) * 100
        current_nav = df['nav'].iloc[-1]
        nav_1y_ago = df[df['date'] <= df['date'].iloc[-1] - pd.DateOffset(years=1)]
        if len(nav_1y_ago) > 0:
            return_1y = (current_nav / nav_1y_ago['nav'].iloc[-1] - 1) * 100
        else:
            return_1y = (current_nav / df['nav'].iloc[0] - 1) * 100
        sharpe = (return_1y - 6) / std_annual if std_annual > 0 else 0
        return round(return_1y, 2), round(std_annual, 2), round(sharpe, 2)
    except:
        return None, None, None

def calculate_tax(invested, current_value, purchase_date_str, units):
    gain = current_value - invested
    if gain <= 0:
        gain_type = "Loss"
        tax_amount = 0
        tax_type = "STCG" if is_short_term(purchase_date_str) else "LTCG"
        action = "🟢 Harvest loss to offset gains"
        return gain, gain_type, tax_amount, tax_type, action

    short_term = is_short_term(purchase_date_str)
    if short_term:
        tax_amount = gain * STCG_RATE
        tax_type = "STCG 20%"
        action = "⏳ Hold 1 year to convert to LTCG"
    else:
        taxable_gain = max(0, gain - LTCG_EXEMPT)
        tax_amount = taxable_gain * LTCG_RATE
        tax_type = "LTCG 12.5%"
        action = "✅ Optimal — LTCG applicable"
        if gain < LTCG_EXEMPT:
            action = "✅ Within ₹1.25L exempt limit"

    return gain, "Gain", round(tax_amount, 0), tax_type, action

def is_short_term(date_str):
    if not date_str:
        return True
    try:
        for fmt in ['%d-%m-%Y','%d/%m/%Y','%d-%b-%Y','%Y-%m-%d']:
            try:
                purchase = datetime.strptime(date_str, fmt).date()
                holding_days = (date.today() - purchase).days
                return holding_days < 365
            except:
                continue
    except:
        pass
    return True

# ── TABS ──
tab1, tab2, tab3, tab4 = st.tabs(["📄 Upload ECAS", "📊 Folio Bucketing", "💰 Tax Harvesting", "📈 Risk-Return"])

# ── TAB 1: UPLOAD ECAS ──
with tab1:
    st.subheader("Upload ECAS or Valuation Report")
    st.info("Supported: CAMS ECAS PDF. The tool will auto-extract fund details. Review and edit before confirming.")

    uploaded = st.file_uploader("Upload PDF", type=["pdf"])

    if uploaded:
        with st.spinner("Extracting data from PDF..."):
            pdf_bytes = BytesIO(uploaded.read())
            parsed = parse_cams_ecas(pdf_bytes)

        if parsed:
            st.success(f"Extracted {len(parsed)} entries. Review and edit below before confirming.")
            df_parsed = pd.DataFrame(parsed)
            display_cols = ["Fund Name","Category","Invested (₹)","Current Value (₹)","Purchase Date","ISIN"]
            df_display = df_parsed[[c for c in display_cols if c in df_parsed.columns]]

            edited = st.data_editor(
                df_display,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "Category": st.column_config.SelectboxColumn(
                        "Category", options=list(CAT_TYPE.keys())
                    ),
                    "Invested (₹)": st.column_config.NumberColumn("Invested (₹)", format="₹%.0f"),
                    "Current Value (₹)": st.column_config.NumberColumn("Current Value (₹)", format="₹%.0f"),
                }
            )

            col1, col2 = st.columns(2)
            if col1.button("✅ Confirm & Send to Dashboard", type="primary"):
                st.session_state.folios = []
                st.session_state.tax_entries = []
                for _, row in edited.iterrows():
                    folio = {
                        "Fund": row.get("Fund Name",""),
                        "Category": row.get("Category","Other"),
                        "Value": float(row.get("Current Value (₹)",0) or 0),
                        "Invested": float(row.get("Invested (₹)",0) or 0),
                        "Purchase Date": str(row.get("Purchase Date","")),
                        "ISIN": str(row.get("ISIN",""))
                    }
                    st.session_state.folios.append(folio)
                    gain = folio["Value"] - folio["Invested"]
                    short_term = is_short_term(folio["Purchase Date"])
                    gain_val, gain_type, tax_amt, tax_type, action = calculate_tax(
                        folio["Invested"], folio["Value"], folio["Purchase Date"], 0)
                    st.session_state.tax_entries.append({
                        "Fund Name": folio["Fund"],
                        "Category": folio["Category"],
                        "Invested (₹)": folio["Invested"],
                        "Current Value (₹)": folio["Value"],
                        "Gain/Loss (₹)": round(gain_val, 0),
                        "Taxed on": "Gain" if gain > 0 else "Loss",
                        "Tax (₹)": tax_amt,
                        "Tax Type": tax_type,
                        "Recommended Action": action
                    })
                st.success(f"✅ {len(st.session_state.folios)} folios loaded into dashboard!")
                st.balloons()
        else:
            st.warning("Could not auto-extract data from this PDF. Please use the manual entry in Folio Bucketing tab.")
            st.markdown("**Tip:** Make sure the PDF is not scanned/image-based. CAMS ECAS PDFs are usually text-based.")

    st.divider()
    st.markdown("**Don't have an ECAS?** You can manually add folios in the Folio Bucketing tab.")

# ── TAB 2: FOLIO BUCKETING ──
with tab2:
    st.subheader("Folio Bucketing")

    with st.expander("➕ Add folio manually"):
        with st.form("folio_form"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Fund Name")
            cat  = c2.selectbox("Category", list(CAT_TYPE.keys()))
            val  = c3.number_input("Current Value (₹)", min_value=0.0)
            c4, c5 = st.columns(2)
            invested = c4.number_input("Invested (₹)", min_value=0.0)
            pdate = c5.text_input("Purchase Date (DD-MM-YYYY)")
            isin_in = st.text_input("ISIN (optional)")
            submitted = st.form_submit_button("Add Folio")
        if submitted and name and val:
            st.session_state.folios.append({
                "Fund": name, "Category": cat, "Value": val,
                "Invested": invested, "Purchase Date": pdate, "ISIN": isin_in
            })
            st.success(f"Added {name}")

    if st.session_state.folios:
        df = pd.DataFrame(st.session_state.folios)
        total = df["Value"].sum()
        total_inv = df["Invested"].sum() if "Invested" in df.columns else 0
        overall_gain = total - total_inv if total_inv > 0 else 0
        overall_ret = (overall_gain / total_inv * 100) if total_inv > 0 else 0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total AUM", f"₹{total:,.0f}")
        m2.metric("Total Invested", f"₹{total_inv:,.0f}")
        m3.metric("Overall Gain", f"₹{overall_gain:,.0f}", f"{overall_ret:.1f}%")
        m4.metric("No. of Folios", len(df))
        eq = df[df["Category"].map(lambda x: CAT_TYPE.get(x,"Other"))=="Equity"]["Value"].sum()
        m5.metric("Equity Weight", f"{(eq/total*100) if total > 0 else 0:.1f}%")

        bucket = df.groupby("Category")["Value"].sum().reset_index()
        bucket["Weight (%)"] = (bucket["Value"]/total*100).round(1)
        bucket["Invested (₹)"] = df.groupby("Category")["Invested"].sum().values if "Invested" in df.columns else 0
        bucket = bucket.sort_values("Value", ascending=False)

        col1, col2 = st.columns([1,1])
        with col1:
            st.markdown("**Category breakdown**")
            st.dataframe(bucket[["Category","Value","Weight (%)"]].rename(
                columns={"Value":"Current Value (₹)"}), use_container_width=True)
        with col2:
            fig = px.pie(bucket, names="Category", values="Value", hole=0.45,
                        color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(margin=dict(t=20,b=20,l=20,r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("**All folios**")
        st.dataframe(df.rename(columns={"Fund":"Fund Name","Value":"Current Value (₹)"}),
                    use_container_width=True)

        if st.button("🗑️ Clear all folios"):
            st.session_state.folios = []
            st.rerun()
    else:
        st.info("Upload an ECAS in the Upload tab or add folios manually above.")

# ── TAB 3: TAX HARVESTING ──
with tab3:
    st.subheader("Tax Harvesting Analysis")
    st.caption("FY2025-26 rates: STCG (Equity) = 20% | LTCG (Equity) = 12.5% above ₹1.25L exemption")

    if st.session_state.tax_entries:
        tdf = pd.DataFrame(st.session_state.tax_entries)

        total_gain = tdf[tdf["Gain/Loss (₹)"] > 0]["Gain/Loss (₹)"].sum()
        total_loss = tdf[tdf["Gain/Loss (₹)"] < 0]["Gain/Loss (₹)"].abs().sum()
        total_tax = tdf["Tax (₹)"].sum()
        harvest_opp = total_loss
        net_tax_after_harvest = max(0, total_tax - total_loss * STCG_RATE)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Gains", f"₹{total_gain:,.0f}")
        m2.metric("Total Losses", f"₹{total_loss:,.0f}")
        m3.metric("Tax Liability", f"₹{total_tax:,.0f}")
        m4.metric("Harvest Opportunity", f"₹{harvest_opp:,.0f}")

        st.markdown("**Fund-wise tax analysis**")
        st.dataframe(
            tdf[["Fund Name","Category","Invested (₹)","Current Value (₹)",
                 "Gain/Loss (₹)","Taxed on","Tax (₹)","Tax Type","Recommended Action"]],
            use_container_width=True,
            column_config={
                "Invested (₹)": st.column_config.NumberColumn(format="₹%.0f"),
                "Current Value (₹)": st.column_config.NumberColumn(format="₹%.0f"),
                "Gain/Loss (₹)": st.column_config.NumberColumn(format="₹%.0f"),
                "Tax (₹)": st.column_config.NumberColumn(format="₹%.0f"),
            }
        )

        loss_funds = tdf[tdf["Gain/Loss (₹)"] < 0]
        if len(loss_funds) > 0:
            st.warning(f"⚠️ {len(loss_funds)} fund(s) in loss — consider harvesting to offset gains before March 31.")

        gain_funds = tdf[tdf["Taxed on"] == "Gain"]
        if len(gain_funds) > 0:
            fig = px.bar(gain_funds, x="Fund Name", y="Gain/Loss (₹)", color="Tax Type",
                        title="Gains by Fund", color_discrete_map={"STCG 20%":"#EF9F27","LTCG 12.5%":"#1D9E75"})
            fig.update_layout(height=300, margin=dict(t=40,b=20))
            st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("Upload an ECAS in the Upload tab to auto-populate tax analysis, or use the manual entry below.")

    with st.expander("➕ Add holding manually"):
        with st.form("tax_form"):
            c1, c2 = st.columns(2)
            tfund = c1.text_input("Fund Name")
            tcat  = c2.selectbox("Category", list(CAT_TYPE.keys()))
            c3, c4, c5 = st.columns(3)
            tinv   = c3.number_input("Invested (₹)", min_value=0.0)
            tcurr  = c4.number_input("Current Value (₹)", min_value=0.0)
            tdate  = c5.text_input("Purchase Date (DD-MM-YYYY)")
            tsub   = st.form_submit_button("Add & Analyse")
        if tsub and tfund:
            gain_val, gain_type, tax_amt, tax_type, action = calculate_tax(tinv, tcurr, tdate, 0)
            st.session_state.tax_entries.append({
                "Fund Name": tfund, "Category": tcat,
                "Invested (₹)": tinv, "Current Value (₹)": tcurr,
                "Gain/Loss (₹)": round(gain_val,0),
                "Taxed on": gain_type, "Tax (₹)": tax_amt,
                "Tax Type": tax_type, "Recommended Action": action
            })
            st.success("Added!")
            st.rerun()

# ── TAB 4: RISK-RETURN ──
with tab4:
    st.subheader("Risk-Return Analysis")
    st.caption("Data fetched live from mfapi.in — AMFI-sourced NAV history")

    with st.expander("➕ Fetch fund data from mfapi.in"):
        with st.form("risk_form"):
            c1, c2 = st.columns(2)
            rfund = c1.text_input("Fund Name or keyword")
            rsub  = st.form_submit_button("🔍 Fetch & Analyse")
        if rsub and rfund:
            with st.spinner(f"Fetching data for '{rfund}'..."):
                nav_data, scheme_name, scheme_code = get_fund_by_name(rfund)
                if nav_data:
                    ret_1y, std, sharpe = calculate_returns_and_std(nav_data)
                    if ret_1y is not None:
                        risk_tag = "Low" if std < 10 else "Moderate" if std < 18 else "High"
                        st.session_state.risk_entries.append({
                            "Fund": scheme_name or rfund,
                            "1Y Return (%)": ret_1y,
                            "Std Dev (%)": std,
                            "Sharpe": sharpe,
                            "Risk": risk_tag,
                            "Scheme Code": scheme_code
                        })
                        st.success(f"✅ {scheme_name} — Return: {ret_1y}% | Std Dev: {std}% | Sharpe: {sharpe}")
                    else:
                        st.warning("Not enough NAV history to calculate metrics.")
                else:
                    st.error("Fund not found on mfapi.in. Try a shorter keyword.")

    if st.session_state.folios and not st.session_state.risk_entries:
        if st.button("🔄 Auto-fetch metrics for all uploaded folios"):
            progress = st.progress(0)
            total_f = len(st.session_state.folios)
            found = 0
            for idx, f in enumerate(st.session_state.folios):
                progress.progress((idx+1)/total_f, text=f"Fetching {f['Fund']}...")
                nav_data, scheme_name, scheme_code = get_fund_by_name(f['Fund'])
                if nav_data:
                    ret_1y, std, sharpe = calculate_returns_and_std(nav_data)
                    if ret_1y is not None:
                        risk_tag = "Low" if std < 10 else "Moderate" if std < 18 else "High"
                        st.session_state.risk_entries.append({
                            "Fund": scheme_name or f['Fund'],
                            "1Y Return (%)": ret_1y,
                            "Std Dev (%)": std,
                            "Sharpe": sharpe,
                            "Risk": risk_tag,
                            "Scheme Code": scheme_code
                        })
                        found += 1
            progress.empty()
            st.success(f"Fetched metrics for {found}/{total_f} funds.")
            st.rerun()

    if st.session_state.risk_entries:
        rdf = pd.DataFrame(st.session_state.risk_entries)

        mean_ret = rdf["1Y Return (%)"].mean()
        avg_std  = rdf["Std Dev (%)"].mean()
        best_sh  = rdf["Sharpe"].max()
        port_risk = "Low" if avg_std < 10 else "Moderate" if avg_std < 18 else "High"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Portfolio Mean Return", f"{mean_ret:.1f}%")
        m2.metric("Avg Std Deviation", f"{avg_std:.1f}%")
        m3.metric("Best Sharpe Ratio", f"{best_sh:.2f}")
        m4.metric("Overall Risk Level", port_risk)

        col1, col2 = st.columns(2)
        with col1:
            fig = px.scatter(rdf, x="Std Dev (%)", y="1Y Return (%)", text="Fund",
                            color="Risk", size_max=15,
                            color_discrete_map={"Low":"#3B6D11","Moderate":"#854F0B","High":"#A32D2D"},
                            title="Risk vs Return")
            fig.update_traces(marker_size=14, textposition='top center')
            fig.update_layout(height=350, margin=dict(t=40,b=20))
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            sorted_rdf = rdf.sort_values("Sharpe", ascending=False).reset_index(drop=True)
            sorted_rdf.index += 1
            sorted_rdf.index.name = "Rank"
            st.markdown("**Fund ranking by Sharpe ratio**")
            st.dataframe(sorted_rdf[["Fund","1Y Return (%)","Std Dev (%)","Sharpe","Risk"]],
                        use_container_width=True)

        if st.button("🗑️ Clear risk data"):
            st.session_state.risk_entries = []
            st.rerun()
    else:
        st.info("Search for a fund above or upload an ECAS and click Auto-fetch.")
