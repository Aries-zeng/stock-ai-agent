import os
import time
import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd

# Try to import akshare, but don't crash the whole app if it's missing
ak = None
ak_import_error = None
try:
    import akshare as ak  # type: ignore
except Exception as e:
    ak = None
    ak_import_error = e

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
            if ak is None:
                return (
                    "❌ A股数据接口未能导入 (akshare 未安装或导入失败)。\n"
                    f"导入错误: {ak_import_error}\n"
                    "解决方法: 在运行环境中执行 `pip install akshare`，然后重启应用。\n"
                )
            try:
                stock_spot = ak.stock_zh_a_spot_em()
                target = stock_spot[stock_spot['代码'].astype(str) == str(symbol)]
                if target.empty:
                    return f"❌ 错误：未找到A股代码 {symbol}。请检查是否输入正确（如 600519）。"
                row = target.iloc[0]
                name = row.get('名称', 'N/A') if hasattr(row, 'get') else row.get('名称', 'N/A')
                latest_price = row.get('最新价', 'N/A')
                pct_chg = row.get('涨跌幅', 'N/A')
                pe_dynamic = row.get('市盈率-动态', 'N/A')
                market_cap = row.get('总市值', 'N/A')
                context += (
                    f"【实时行情】\n名称：{name}\n价格：{latest_price}\n涨跌幅：{pct_chg}%\n"
                    f"PE(动)：{pe_dynamic}\n市值：{market_cap}\n"
                )
                context += "【财务概况】\n(注：A股详细财务数据调用耗时较长，此处仅提供行情驱动分析)\n"
            except Exception as e:
                return f"A股数据接口报错: {e}"

        else:
            yf_symbol = symbol
            if market == "HK" and not symbol.endswith(".HK"):
                yf_symbol = f"{symbol}.HK"
            elif market == "JP" and not symbol.endswith(".T"):
                yf_symbol = f"{symbol}.T"

            ticker = yf.Ticker(yf_symbol)
            try:
                info = ticker.info or {}
            except Exception:
                info = {}

            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if not current_price:
                 return f"❌ 错误：未找到代码 {yf_symbol} 的数据。请检查代码是否正确（例如日股需确认是否退市或代码变更）。"

            currency = info.get('currency', 'USD')
            long_name = info.get('longName', symbol)

            context += f"【Basic Info】\nName: {long_name}\nPrice: {current_price} {currency}\n"
            context += f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            context += f"Trailing PE: {info.get('trailingPE', 'N/A')}\n"
            context += f"Forward PE: {info.get('forwardPE', 'N/A')}\n"
            context += f"PB Ratio: {info.get('priceToBook', 'N/A')}\n"
            try:
                roe = info.get('returnOnEquity', 0)
                context += f"ROE: {roe*100:.2f}%\n"
            except Exception:
                context += f"ROE: {info.get('returnOnEquity', 'N/A')}\n"
            try:
                rev_growth = info.get('revenueGrowth', 0)
                context += f"Revenue Growth: {rev_growth*100:.2f}%\n"
            except Exception:
                context += f"Revenue Growth: {info.get('revenueGrowth', 'N/A')}\n"
            context += f"52 Week High: {info.get('fiftyTwoWeekHigh')}\n"
            context += f"Business Summary: {info.get('longBusinessSummary', 'N/A')[:500]}...\n"

    except Exception as e:
        return f"数据获取发生未知错误: {str(e)}"

    return context

# ============================
# Helper: call Gemini compatibly across SDK versions
def extract_text_from_response(resp):
    """
    尝试以多种常见结构提取文本内容（兼容不同版本返回结构）
    """
    try:
        # direct text attribute
        if hasattr(resp, "text"):
            return getattr(resp, "text")
        # resp.output_text (some helpers)
        if hasattr(resp, "output_text"):
            return getattr(resp, "output_text")
        # resp.last.candidates[*].content / .text
        last = getattr(resp, "last", None)
        if isinstance(last, dict):
            candidates = last.get("candidates", [])
            if candidates:
                cand = candidates[0]
                if isinstance(cand, dict):
                    # candidate content may be text or nested
                    if "content" in cand and isinstance(cand["content"], list):
                        parts = []
                        for p in cand["content"]:
                            if isinstance(p, dict) and p.get("type") == "output_text":
                                parts.append(p.get("text", ""))
                            elif isinstance(p, dict) and "text" in p:
                                parts.append(p.get("text", ""))
                        if parts:
                            return "\n".join(parts)
                    if "text" in cand:
                        return cand.get("text")
                    if "content" in cand and isinstance(cand["content"], str):
                        return cand["content"]
        # resp.output -> list of blocks with content list
        output = getattr(resp, "output", None)
        if isinstance(output, list):
            texts = []
            for o in output:
                if isinstance(o, dict):
                    for c in o.get("content", []):
                        if isinstance(c, dict):
                            if "text" in c:
                                texts.append(c.get("text", ""))
                            elif c.get("type") == "text":
                                texts.append(c.get("text", ""))
            if texts:
                return "\n".join(texts)
        # resp.choices (openai-like)
        choices = getattr(resp, "choices", None)
        if isinstance(choices, (list, tuple)) and len(choices) > 0:
            c0 = choices[0]
            if isinstance(c0, dict):
                # c0 may have message.content
                msg = c0.get("message") or c0.get("text") or c0.get("output")
                if isinstance(msg, dict):
                    # try message.content as string or list
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        # flatten
                        pieces = []
                        for it in content:
                            if isinstance(it, dict) and "text" in it:
                                pieces.append(it["text"])
                            elif isinstance(it, str):
                                pieces.append(it)
                        if pieces:
                            return "\n".join(pieces)
                elif isinstance(msg, str):
                    return msg
            else:
                # choices items may be objects with message
                msg = getattr(c0, "message", None)
                if msg:
                    content = getattr(msg, "content", None)
                    if isinstance(content, str):
                        return content
        # fallback to string representation
        return str(resp)
    except Exception:
        try:
            return str(resp)
        except Exception:
            return "<无法解析的响应>"

def call_gemini_compat(genai, model_name, system_prompt, prompt, max_output_tokens=800, temperature=0.2):
    """
    逐个尝试多种可能的 SDK 调用方式，返回 (method_used, text_or_error)
    """
    errors = []
    # 1) genai.generate(...)
    try:
        if hasattr(genai, "generate"):
            resp = genai.generate(model=model_name, prompt=prompt, max_output_tokens=max_output_tokens)
            return ("genai.generate", extract_text_from_response(resp))
    except Exception as e:
        errors.append(("genai.generate", str(e)))
    # 2) genai.chat.completions.create(...)
    try:
        chat_attr = getattr(genai, "chat", None)
        if chat_attr is not None:
            comps = getattr(chat_attr, "completions", None)
            if comps is not None and hasattr(comps, "create"):
                resp = comps.create(
                    model=model_name,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                return ("genai.chat.completions.create", extract_text_from_response(resp))
    except Exception as e:
        errors.append(("genai.chat.completions.create", str(e)))
    # 3) genai.text.generate(...)
    try:
        textmod = getattr(genai, "text", None)
        if textmod is not None and hasattr(textmod, "generate"):
            resp = textmod.generate(model=model_name, input=prompt, max_output_tokens=max_output_tokens, temperature=temperature)
            return ("genai.text.generate", extract_text_from_response(resp))
    except Exception as e:
        errors.append(("genai.text.generate", str(e)))
    # 4) genai.responses.create(...)
    try:
        respmod = getattr(genai, "responses", None)
        if respmod is not None and hasattr(respmod, "create"):
            resp = respmod.create(model=model_name, input=prompt, temperature=temperature)
            return ("genai.responses.create", extract_text_from_response(resp))
    except Exception as e:
        errors.append(("genai.responses.create", str(e)))
    # 5) genai.completions.create(...)
    try:
        compmod = getattr(genai, "completions", None)
        if compmod is not None and hasattr(compmod, "create"):
            resp = compmod.create(model=model_name, prompt=prompt, max_tokens=max_output_tokens, temperature=temperature)
            return ("genai.completions.create", extract_text_from_response(resp))
    except Exception as e:
        errors.append(("genai.completions.create", str(e)))

    # If we reach here, nothing worked
    err_msg = " / ".join([f"{m}: {e}" for m, e in errors])
    return ("none", f"All attempts failed. Details: {err_msg}")

# ============================

# 2. 页面配置
st.set_page_config(page_title="Global AI Stock Analyst", page_icon="🌏", layout="centered")

# -------------------------
password_input = st.sidebar.text_input("请输入访问密码 (Password)", type="password", help="请输入访问应用的密码")
if password_input != "zhizunbao":
    if password_input:
        st.sidebar.error("密码错误。若忘记密码，请联系管理员。")
    else:
        st.sidebar.info("请输入密码以访问应用。")
    st.stop()

# 3. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 设置")

    default_key = "AIzaSyAzgQk7lEfNcsRoCBxRRbjbQR4remrFztM"
    api_key = "AIzaSyAzgQk7lEfNcsRoCBxRRbjbQR4remrFztM" #st.text_input("Gemini API Key", value=default_key, type="password")

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

    if 'search_history' not in st.session_state:
        st.session_state['search_history'] = []

    history_display = list(reversed(st.session_state['search_history']))
    history_options = [""] + history_display
    selected_history = st.selectbox("搜索历史（点击以填充）", options=history_options, index=0)

    if st.button("清除搜索历史"):
        st.session_state['search_history'] = []
        st.experimental_rerun()

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
            "🇯賀 日股 (JP)",
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
    prefill = selected_history if selected_history else def_val
    symbol = st.text_input("输入股票代码", value=prefill)

SYSTEM_PROMPT = """
你是一位精通全球资本市场的首席分析师。请针对用户提供的股票，结合其所在市场的特性生成逻辑清晰的个股研报，包含基本面分析、逻辑验证、投资建议、风险提示等。
"""

# 6. 执行逻辑
if st.button("🚀 生成全球研报", use_container_width=True):
    try:
        if 'search_history' not in st.session_state:
            st.session_state['search_history'] = []

        sym = (symbol or "").strip()
        if sym:
            if sym not in st.session_state['search_history']:
                st.session_state['search_history'].append(sym)
            if len(st.session_state['search_history']) > 50:
                st.session_state['search_history'] = st.session_state['search_history'][-50:]

        with st.spinner("正在获取市场与财务数据..."):
            data_context = get_global_financial_data(market_code, sym)

        st.subheader("原始数据 / Data Context")
        st.text_area("数据上下文（供AI分析使用）", value=str(data_context), height=260)

        if api_key:
            try:
                # 配置 API key
                genai.configure(api_key=api_key)

                # 构建 prompt
                prompt = SYSTEM_PROMPT + f"\n\n股票代码: {sym}\n市场: {market_code}\n\n数据:\n{data_context}\n\n请基于上述数据撰写一份结构化研报：基本面分析、驱动因素、估值判断、风险提示。"

                # 使用兼容调用层
                method_used, result = call_gemini_compat(genai, model_name, SYSTEM_PROMPT, prompt, max_output_tokens=800, temperature=0.2)

                if method_used == "none":
                    st.error("调用 Gemini 失败：" + result)
                    # 额外输出诊断建议
                    st.info("建议：升级 google-generativeai（pip install --upgrade google-generativeai），并检查 genai 模块支持的属性。")
                    st.write("详细错误信息：", result)
                else:
                    st.success(f"调用方式：{method_used}")
                    st.subheader("AI 研报")
                    st.markdown(result)
            except Exception as e:
                st.error(f"调用 Gemini 生成研报时出错: {e}")
        else:
            st.info("未配置 Gemini API Key，已展示原始数据。")

    except Exception as e:
        st.error(f"发生错误: {e}")
