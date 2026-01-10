import os
import time
import streamlit as st
#import google.generativeai as genai
#import yfinance as yf
#import akshare as ak
#import pandas as pd

# ⚠️ 1. 强制走本地代理 (解决国内连接 Google 的问题)
# os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
# os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

# === 🔑 配置 API Key (硬编码) ===
# 为了不显示在侧边栏，我们将 Key 定义在这里
GEMINI_API_KEY = "AIzaSyAzgQk7lEfNcsRoCBxRRbjbQR4remrFztM"

# === 核心数据引擎 (整合版) ===
@st.cache_data(ttl=3600)
def get_global_financial_data(market, symbol):
    """
    全能数据获取函数：支持 A股(AkShare) 和 美/港/日股(YFinance)
    """
    context = ""
    try:
        # --- A股逻辑 (AkShare) ---
        if market == "CN":
            try:
                stock_spot = ak.stock_zh_a_spot_em()
                target = stock_spot[stock_spot['代码'].astype(str) == str(symbol)]
                if target.empty:
                    return f"❌ 错误：未找到A股代码 {symbol}。请检查是否输入正确（如 600519）。"
                
                row = target.iloc[0]
                context += f"【实时行情】\n名称：{row['名称']}\n价格：{row['最新价']}\n涨跌幅：{row['涨跌幅']}%\nPE(动)：{row['市盈率-动态']}\n市值：{row['总市值']}\n\n"
                
                context += "【财务概况】\n(注：A股详细财务数据调用耗时较长，此处仅提供行情驱动分析)\n"
            except Exception as e:
                return f"A股数据接口报错: {e}"

        # --- 全球市场逻辑 (YFinance) ---
        else:
            yf_symbol = symbol
            if market == "HK" and not symbol.endswith(".HK"):
                yf_symbol = f"{symbol}.HK"
            elif market == "JP" and not symbol.endswith(".T"):
                yf_symbol = f"{symbol}.T"
            
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info
            
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if not current_price:
                 return f"❌ 错误：未找到代码 {yf_symbol} 的数据。请检查代码是否正确。"

            currency = info.get('currency', 'USD')
            long_name = info.get('longName', symbol)
            
            context += f"【Basic Info】\nName: {long_name}\nPrice: {current_price} {currency}\n"
            context += f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            context += f"Trailing PE: {info.get('trailingPE', 'N/A')}\n"
            context += f"Forward PE: {info.get('forwardPE', 'N/A')}\n"
            context += f"PB Ratio: {info.get('priceToBook', 'N/A')}\n"
            context += f"ROE: {info.get('returnOnEquity', 0)*100:.2f}%\n"
            context += f"Revenue Growth: {info.get('revenueGrowth', 0)*100:.2f}%\n"
            context += f"52 Week High: {info.get('fiftyTwoWeekHigh')}\n"
            context += f"Business Summary: {info.get('longBusinessSummary', 'N/A')[:500]}...\n"

    except Exception as e:
        return f"数据获取发生未知错误: {str(e)}"

    return context

# ============================

# 2. 页面配置
st.set_page_config(page_title="Global AI Stock Analyst", page_icon="🌏", layout="centered")

# 3. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 设置")
    
    # ❌ 原来的输入框已删除
    
    st.divider()
    st.success("🤖 当前模型：gemini-2.5-flash")
    model_name = "gemini-2.5-flash" 
    
    st.divider()
    st.markdown("""
    **代码输入指南：**
    * 🇺🇸 **美股**：直接输代码 (如 `AAPL`, `NVDA`)
    * 🇭🇰 **港股**：输数字 (如 `9988`, `0700`)
    * 🇯🇵 **日股**：输数字 (如 `7203`, `8058`)
    * 🇨🇳 **A股**：输数字 (如 `600519`)
    """)

# 4. 主界面
st.title("🌏 全球股市 AI 研报系统")
st.caption("支持：🇺🇸 美股 (Nasdaq/NYSE) | 🇭🇰 港股 | 🇯🇵 日股 | 🇨🇳 A股")

col1, col2 = st.columns([1, 2])
with col1:
    market_label = st.selectbox(
        "选择市场", 
        [
            "🇺🇸 美股 (US)", 
            "🇭🇰 港股 (HK)", 
            "🇯🇵 日股 (JP)", 
            "🇨🇳 A股 (CN)"
        ], 
        index=0
    )
    market_code = market_label.split("(")[1].split(")")[0]

with col2:
    if market_code == "US":
        def_val = "NVDA"
    elif market_code == "HK":
        def_val = "9988"
    elif market_code == "JP":
        def_val = "7203"
    else:
        def_val = "600519"
        
    symbol = st.text_input("输入股票代码", value=def_val)

# 5. Prompt 策略
SYSTEM_PROMPT = """
你是一位精通全球资本市场的首席分析师。请针对用户提供的股票，结合其所在市场的特性（如美股关注创新与回购、日股关注巴菲特与治理改革、港股关注流动性与地缘、A股关注政策与题材），生成一份深度研报。

请按以下结构生成一份逻辑清晰、论证严密的个股研报：
1. 基本面分析
- 分析营收增长、毛利率与净利率趋势、以及自由现金流状况
- 对比同业估值指标（P/E, EV/EBITDA 等）
- 审查内部持股比例及近期的内部交易（Insider Trades）
2. 逻辑验证
- 提出 3 个支持投资逻辑的核心论据
- 指出 2 个反面论据或关键风险点
- 给出最终定性：看多 (Bullish) / 看空 (Bearish) / 中性 (Neutral)，并说明理由
3. 行业与宏观视角
- 简述行业概况
- 概述相关的宏观经济趋势
- 阐述公司的市场竞争地位
- 对比行业平均PE水平
4. 催化剂观察
- 列出即将发生的关键事件（财报发布、新产品发布、监管动向等）
- 识别短期和长期的股价催化剂
5. 投资总结
- 用 5 个要点总结核心投资逻辑
- 最终评级：买入 / 持有 / 卖出
- 确信度：高 / 中 / 低
- 预期持仓周期：（如 6–12 个月，或者更长期的投资周期）
"""

# 6. 执行逻辑
if st.button("🚀 生成全球研报", use_container_width=True):
    # 初始化
    start_time = time.time()
    progress_bar = st.progress(0, text="正在初始化...")
    status_box = st.status(f"🚀 正在启动 {market_code} 市场分析引擎...", expanded=True)
    
    # A. 获取数据
    progress_bar.progress(20, text=f"📡 正在连接 {market_label} 交易所接口...")
    status_box.write("📡 正在抓取实时行情与财务数据...")
    
    data_context = get_global_financial_data(market_code, symbol)
    
    if "错误" in data_context or "报错" in data_context:
        status_box.update(label="❌ 数据获取失败", state="error")
        progress_bar.empty()
        st.error(data_context)
    else:
        # B. AI 推理
        progress_bar.progress(50, text="🧠 数据就绪，正在请求 Gemini 进行跨市场分析...")
        status_box.write(f"🧠 数据获取成功，正在请求 Gemini 1.5 Flash...")
        
        try:
            # ✅ 修复：使用顶部定义的变量，并加上了引号
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(model_name)
            
            full_prompt = f"""
            {SYSTEM_PROMPT}
            ---
            【目标股票】：{market_label} - 代码 {symbol}
            【交易所实时数据】：
            {data_context}
            ---
            请开始分析：
            """
            
            response = model.generate_content(full_prompt)
            
            # C. 完成
            progress_bar.progress(100, text="✅ 生成完成！")
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            status_box.update(label=f"✅ 分析完成！(耗时 {elapsed_time:.2f}s)", state="complete", expanded=False)
            st.success(f"研报已生成！耗时：{elapsed_time:.2f} 秒")
            
            st.divider()
            st.markdown(response.text)
            
            time.sleep(2)
            progress_bar.empty()
            
        except Exception as e:
            status_box.update(label="API 调用出错", state="error")
            progress_bar.empty()
            if "429" in str(e):
                st.error("⚠️ 触发限流 (429)，请稍等30秒再试。")
            else:
                st.error(f"Gemini 报错: {e}")
