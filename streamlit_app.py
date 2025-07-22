import streamlit as st
from cli_scanner.core import scanner

st.title("📈 Earnings Edge Detection")

ticker = st.text_input("Enter a stock ticker (e.g. AAPL):")
if st.button("Run Analysis") and ticker:
    try:
        st.write("Running earnings edge analysis...")
        scanner.run([ticker])
        st.success("Analysis completed. Check the generated charts.")
        st.image(f"{ticker}_candle.png")
        st.image(f"{ticker}_strategy_returns.png")
        st.image(f"{ticker}_returns_histogram.png")
    except Exception as e:
        st.error(f"Error running analysis: {e}")
