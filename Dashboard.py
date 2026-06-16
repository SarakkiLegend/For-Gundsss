import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="RM Portfolio Dashboard", layout="wide")
st.title("RM Portfolio Intelligence Dashboard")
st.caption("ICICI Prudential AMC — Decision Support Tool")

tab1, tab2, tab3 = st.tabs(["Folio Bucketing", "Tax Harvesting", "Risk-Return"])

CAT_TYPE = {
    "Large Cap":"Equity","Mid Cap":"Equity","Small Cap":"Equity",
    "Flexi Cap":"Equity","ELSS":"Equity","Index":"Equity",
    "Debt":"Debt","Hybrid":"Hybrid"
}

with tab1:
    st.subheader("Add Folio")
    with st.form("folio_form"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Fund Name")
        cat  = c2.selectbox("Category", list(CAT_TYPE.keys()))
        val  = c3.number_input("Current Value (₹)", min_value=0.0)
        submitted = st.form_submit_button("Add Folio")
    if "folios" not in st.session_state:
        st.session_state.folios = []
    if submitted and name and val:
        st.session_state.folios.append({"Fund": name, "Category": cat, "Value": val})
    if st.session_state.get("folios"):
        df = pd.DataFrame(st.session_state.folios)
        total = df["Value"].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total AUM", f"₹{total:,.0f}")
        m2.metric("No. of Folios", len(df))
        eq = df[df["Category"].map(CAT_TYPE)=="Equity"]["Value"].sum()
        dbt = df[df["Category"].map(CAT_TYPE)=="Debt"]["Value"].sum()
        m3.metric("Equity Weight", f"{eq/total*100:.1f}%")
        m4.metric("Debt Weight", f"{dbt/total*100:.1f}%")
        bucket = df.groupby("Category")["Value"].sum().reset_index()
        bucket["Weight (%)"] = (bucket["Value"]/total*100).round(1)
        col1, col2 = st.columns(2)
        with col1:
            st.dataframe(bucket, use_container_width=True)
        with col2:
            fig = px.pie(bucket, names="Category", values="Value", hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Add Holding")
    with st.form("tax_form"):
        c1, c2, c3 = st.columns(3)
        tfund  = c1.text_input("Fund Name")
        tbuy   = c2.number_input("Buy Price (₹)", min_value=0.0)
        tcurr  = c3.number_input("Current Price (₹)", min_value=0.0)
        c4, c5 = st.columns(2)
        tdays  = c4.number_input("Holding Days", min_value=0)
        tunits = c5.number_input("Units Held", min_value=0.0)
        tsub   = st.form_submit_button("Analyse")
    if "tax" not in st.session_state:
        st.session_state.tax = []
    if tsub and tfund and tbuy and tcurr and tunits:
        gain_pct = (tcurr - tbuy) / tbuy * 100
        gain_amt = (tcurr - tbuy) * tunits
        typ = "LTCG" if tdays >= 365 else "STCG"
        rate = 0.125 if typ == "LTCG" else 0.20
        st.session_state.tax.append({
            "Fund": tfund, "Days": tdays, "Gain (%)": round(gain_pct,2),
            "Gain (₹)": round(gain_amt,0), "Type": typ, "Tax Rate": f"{rate*100}%"
        })
    if st.session_state.get("tax"):
        tdf = pd.DataFrame(st.session_state.tax)
        losses = tdf[tdf["Gain (₹)"] < 0]
        opp = losses["Gain (₹)"].abs().sum()
        save = sum(abs(r["Gain (₹)"]) * (0.125 if r["Type"]=="LTCG" else 0.20) for _,r in losses.iterrows())
        m1, m2 = st.columns(2)
        m1.metric("Harvest Opportunity", f"₹{opp:,.0f}")
        m2.metric("Est. Tax Saving", f"₹{save:,.0f}")
        st.dataframe(tdf, use_container_width=True)

with tab3:
    st.subheader("Add Fund Return Data")
    with st.form("risk_form"):
        c1, c2, c3 = st.columns(3)
        rfund = c1.text_input("Fund Name")
        rret  = c2.number_input("1Y Return (%)", value=0.0)
        rstd  = c3.number_input("Std Deviation (%)", min_value=0.0)
        rsub  = st.form_submit_button("Add")
    if "risk" not in st.session_state:
        st.session_state.risk = []
    if rsub and rfund and rstd:
        sharpe = (rret - 6) / rstd if rstd > 0 else 0
        risk_tag = "Low" if rstd < 10 else "Moderate" if rstd < 18 else "High"
        st.session_state.risk.append({
            "Fund": rfund, "Return (%)": rret,
            "Std Dev (%)": rstd, "Sharpe": round(sharpe,2), "Risk": risk_tag
        })
    if st.session_state.get("risk"):
        rdf = pd.DataFrame(st.session_state.risk)
        m1, m2, m3 = st.columns(3)
        m1.metric("Mean Return", f"{rdf['Return (%)'].mean():.1f}%")
        m2.metric("Avg Std Dev", f"{rdf['Std Dev (%)'].mean():.1f}%")
        m3.metric("Best Sharpe", f"{rdf['Sharpe'].max():.2f}")
        fig = px.scatter(rdf, x="Std Dev (%)", y="Return (%)", text="Fund",
                         color="Risk", color_discrete_map={"Low":"#3B6D11","Moderate":"#854F0B","High":"#A32D2D"},
                         size_max=15)
        fig.update_traces(marker_size=12)
        st.plotly_chart(fig, use_container_width=True)
        st.subheader("Fund Ranking (by Sharpe Ratio)")
        st.dataframe(rdf.sort_values("Sharpe", ascending=False).reset_index(drop=True), use_container_width=True)
