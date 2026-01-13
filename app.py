import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import time
import json
import os
import qrcode
from PIL import Image
import io
import google.generativeai as genai
import random

# ==========================================
# 🎨 1. 样式与配置 (Custom CSS)
# ==========================================

st.set_page_config(page_title="DFMA Check-in", page_icon="📈", layout="wide")

# 加载自定义 CSS 以实现 "App" 风格
st.markdown("""
<style>
    /* 全局字体 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* 手机端模拟容器 (Mobile Container) */
    .mobile-container {
        max-width: 420px;
        margin: 0 auto;
        background-color: #ffffff;
        padding: 30px;
        border-radius: 25px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        border: 1px solid #f0f0f0;
    }

    /* 输入框美化 */
    .stTextInput input {
        border-radius: 12px;
        padding: 12px;
        border: 2px solid #e2e8f0;
        text-align: center;
        font-size: 18px;
        letter-spacing: 2px;
        transition: all 0.3s;
    }
    .stTextInput input:focus {
        border-color: #1e3a8a;
        box-shadow: 0 0 0 3px rgba(30, 58, 138, 0.1);
    }

    /* 按钮美化 */
    .stButton button {
        border-radius: 12px;
        height: 50px;
        font-weight: 600;
        font-size: 16px;
        transition: transform 0.1s;
    }
    .stButton button:active {
        transform: scale(0.98);
    }

    /* 成功页样式 */
    .success-card {
        background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
        border: 2px solid #3b82f6;
        border-radius: 20px;
        padding: 30px;
        text-align: center;
        animation: fadeIn 0.5s ease-out;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Logo 样式 */
    .logo-img {
        display: block;
        margin-left: auto;
        margin-right: auto;
        width: 80px; /* Logo 小一点 */
        margin-bottom: 20px;
    }

    /* Admin 后台优化 */
    .admin-card {
        background: white;
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        margin-bottom: 15px;
        border: 1px solid #eee;
    }
</style>
""", unsafe_allow_html=True)

# API 配置
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        HAS_AI = True
    else:
        HAS_AI = False
except:
    HAS_AI = False

# 路径配置
SESSION_FILE = "sessions.json"
BACKUP_FILE = "local_backup_logs.csv"
LOCAL_NAMELIST = "local_namelist.csv"
LOGO_FILE = "logo.png"
ADMIN_PASSWORD = "admin" 
APP_URL = "https://dfma-checkin-app-2026.streamlit.app" 

# ==========================================
# 🛠️ 2. 核心逻辑函数
# ==========================================

# --- Session 管理 ---
def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as f: return json.load(f)
    return []

def save_sessions(sessions):
    with open(SESSION_FILE, 'w') as f: json.dump(sessions, f)

# --- 数据读取 (IC 验证核心) ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def get_participants_data():
    """读取 Name, Email, Category, IC"""
    try:
        # 尝试读 4 列
        df = conn.read(worksheet="Participants", usecols=[0, 1, 2, 3])
        
        # 自动补全列名
        expected_cols = ['Name', 'Email', 'Category', 'IC']
        current_cols = df.columns.tolist()
        
        # 简单的列名映射，防止 Excel 表头不一样
        mapping = {}
        for i, col in enumerate(current_cols):
            if i < 4: mapping[col] = expected_cols[i]
        
        df = df.rename(columns=mapping)
        
        # 补全缺失列
        for col in expected_cols:
            if col not in df.columns: df[col] = '-'
            
        # 强转字符串并去空
        return df.dropna(subset=['Name']).astype(str)
    except Exception:
        # 灾备模式：读本地 CSV
        if os.path.exists(LOCAL_NAMELIST):
            try:
                df = pd.read_csv(LOCAL_NAMELIST)
                # 假设本地文件也有 IC 列
                if 'IC' not in df.columns: df['IC'] = '0000' 
                return df.astype(str)
            except: pass
        return pd.DataFrame(columns=['Name', 'Email', 'Category', 'IC'])

def get_logs_data():
    if os.path.exists(BACKUP_FILE): return pd.read_csv(BACKUP_FILE)
    try: return conn.read(worksheet="Logs", ttl=0)
    except: return pd.DataFrame()

# --- AI ---
def ai_generate_welcome(name, session_name):
    if not HAS_AI: return f"Welcome {name}! Ready for the market?"
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        prompt = f"Write a 1-sentence welcome for student {name} at '{session_name}' with a super short trading fact."
        response = model.generate_content(prompt)
        return response.text
    except: return f"Welcome {name}!"

# --- 状态判断与写入 ---
def calculate_status(session_data):
    """独立的状态计算函数"""
    kl_time = datetime.utcnow() + timedelta(hours=8)
    
    try:
        start_str = f"{session_data['date']} {session_data['start']}"
        session_start = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        
        # 解析 Duration
        dur_str = str(session_data.get('duration', '1hr'))
        if 'hr' in dur_str:
            mins = int(float(dur_str.replace('hr','')) * 60)
        else:
            mins = int(dur_str.replace('m',''))
            
        late_threshold = session_start + timedelta(minutes=mins)
        
        if kl_time > late_threshold:
            return "Late"
        return "On-time"
    except:
        return "Unknown" # 如果日期格式不对

def write_log(session_data, name, user_type, email="-", phone="-"):
    kl_time = datetime.utcnow() + timedelta(hours=8)
    timestamp_str = kl_time.strftime("%Y-%m-%d %H:%M:%S")
    
    status = calculate_status(session_data)

    new_data = pd.DataFrame([{
        "Timestamp": timestamp_str,
        "Session": session_data['name'],
        "Name": name,
        "Type": user_type,
        "Status": status,
        "Email": email,
        "Phone": phone
    }])

    # 1. 本地写入
    if not os.path.exists(BACKUP_FILE):
        new_data.to_csv(BACKUP_FILE, index=False)
    else:
        new_data.to_csv(BACKUP_FILE, mode='a', header=False, index=False)

    # 2. 如果开启高峰模式，跳过 Google
    if st.session_state.get('high_traffic_mode', True):
        return True, status

    # 3. 尝试 Google 写入
    try:
        existing_data = conn.read(worksheet="Logs", ttl=0)
        updated_df = pd.concat([existing_data, new_data], ignore_index=True)
        conn.update(worksheet="Logs", data=updated_df)
    except:
        pass

    return True, status

def sync_local_to_cloud():
    if not os.path.exists(BACKUP_FILE): return "No local data."
    try:
        local = pd.read_csv(BACKUP_FILE)
        cloud = conn.read(worksheet="Logs", ttl=0)
        combined = pd.concat([cloud, local]).drop_duplicates(subset=['Timestamp', 'Name'], keep='last')
        conn.update(worksheet="Logs", data=combined)
        return f"✅ Synced {len(local)} records!"
    except Exception as e: return f"❌ Error: {e}"

# ==========================================
# 🖥️ 3. 页面渲染逻辑
# ==========================================

if 'page' not in st.session_state: st.session_state.page = 'HOME'
if 'current_user' not in st.session_state: st.session_state.current_user = None
if 'welcome_msg' not in st.session_state: st.session_state.welcome_msg = ""
if 'high_traffic_mode' not in st.session_state: st.session_state.high_traffic_mode = True 

sessions = load_sessions()
active_sessions = [s for s in sessions if s.get('active', True)]

# --- Admin Sidebar (简化版) ---
with st.sidebar:
    st.title("🔐 Admin")
    
    # 模式开关
    mode = st.toggle("🚀 High Traffic Mode", value=st.session_state.high_traffic_mode)
    st.session_state.high_traffic_mode = mode
    
    if st.text_input("Password", type="password") == ADMIN_PASSWORD:
        st.success("Unlocked")
        
        tab1, tab2 = st.tabs(["Manage", "Data"])
        
        with tab1:
            st.subheader("Create Session")
            s_name = st.text_input("Name", placeholder="DFMA Class 1")
            c1, c2 = st.columns(2)
            s_date = c1.date_input("Date")
            s_time = c2.time_input("Start")
            s_dur = st.selectbox("Late Buffer", ["15m", "30m", "1hr"])
            
            if st.button("Create"):
                new_s = {
                    "id": int(time.time()),
                    "name": s_name,
                    "code": str(random.randint(100000, 999999)),
                    "date": str(s_date),
                    "start": str(s_time),
                    "duration": s_dur,
                    "active": True
                }
                sessions.append(new_s)
                save_sessions(sessions)
                st.rerun()
            
            st.divider()
            for s in active_sessions:
                with st.container(border=True):
                    st.write(f"**{s['name']}**")
                    c_a, c_b = st.columns(2)
                    if c_a.button("📽️ Project", key=f"p{s['id']}"):
                        st.session_state.project_session = s
                        st.session_state.page = 'PROJECTION'
                        st.rerun()
                    if c_b.button("🗑️ Del", key=f"d{s['id']}"):
                        sessions.remove(s)
                        save_sessions(sessions)
                        st.rerun()

        with tab2:
            if st.button("☁️ Sync to Google"):
                res = sync_local_to_cloud()
                st.info(res)
            
            if os.path.exists(BACKUP_FILE):
                with open(BACKUP_FILE, "rb") as f:
                    st.download_button("📥 Download CSV", f, "logs.csv")

# --- 页面路由 ---

# A. 投屏页面 (Project Screen)
if st.session_state.page == 'PROJECTION':
    s = st.session_state.get('project_session')
    
    # 全屏布局
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; }
            h1 { font-size: 3.5rem; color: #1e3a8a; margin-bottom: 0.5rem; }
            .stat-box { background: #f8fafc; padding: 20px; border-radius: 15px; text-align: center; border: 1px solid #e2e8f0; }
            .live-row { 
                background: white; padding: 15px; border-radius: 12px; margin-bottom: 10px; 
                box-shadow: 0 2px 5px rgba(0,0,0,0.05); border-left: 6px solid #3b82f6; 
                display: flex; justify-content: space-between; align-items: center;
                font-size: 20px; font-weight: 600; color: #334155;
            }
        </style>
    """, unsafe_allow_html=True)

    # 顶部栏
    c1, c2, c3 = st.columns([1, 8, 1])
    with c1:
        if st.button("⬅️ Exit"):
            st.session_state.page = 'HOME'
            st.rerun()
    with c2:
        if os.path.exists(LOGO_FILE):
            st.image(LOGO_FILE, width=100) # 投屏 Logo
        st.markdown(f"<h1 style='text-align: center;'>{s['name']}</h1>", unsafe_allow_html=True)

    col_L, col_R = st.columns([1, 1])

    with col_L:
        # 二维码 & Code
        st.markdown("### 📲 Scan to Check-in")
        qr = qrcode.make(APP_URL)
        img = io.BytesIO()
        qr.save(img, format='PNG')
        st.image(img, width=400)
        
        st.markdown("---")
        st.markdown(f"<p style='font-size: 24px; color: #64748b;'>Check In Code:</p>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-size: 90px; font-weight: 800; color: #1e3a8a; line-height: 1;'>{s['code']}</p>", unsafe_allow_html=True)

    with col_R:
        # 实时列表
        logs = get_logs_data()
        count = 0
        display_logs = pd.DataFrame()
        
        if not logs.empty and 'Session' in logs.columns:
            # 过滤当前 Session
            current_logs = logs[logs['Session'] == s['name']]
            count = len(current_logs)
            display_logs = current_logs.sort_values("Timestamp", ascending=False).head(8)

        # 统计卡片
        st.markdown(f"""
            <div class="stat-box">
                <div style="font-size: 16px; text-transform: uppercase; letter-spacing: 1px; color: #64748b;">Total Checked In</div>
                <div style="font-size: 60px; font-weight: 800; color: #10b981;">{count}</div>
            </div>
            <br>
        """, unsafe_allow_html=True)

        st.markdown("### 🟢 Live Feed")
        if not display_logs.empty:
            for _, row in display_logs.iterrows():
                name = str(row['Name'])
                # Masking: Show last 5 chars (excluding space logic is tricky, simple slice is cleaner for feed)
                # Example: "Yeoh Sin Ni" -> "****in Ni"
                if len(name) > 5:
                    masked = "****" + name[-5:]
                else:
                    masked = name
                
                time_only = row['Timestamp'].split(' ')[1][:5] # HH:MM
                
                st.markdown(f"""
                <div class="live-row">
                    <span>{masked}</span>
                    <span style="font-family: monospace; color: #94a3b8; font-size: 16px;">{time_only}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("Waiting for check-ins...")

    time.sleep(5)
    st.rerun()

# B. 手机端 (Home)
elif st.session_state.page == 'HOME':
    # 模拟手机容器
    st.markdown('<div class="mobile-container">', unsafe_allow_html=True)
    
    # Logo
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=80) # 缩小 Logo
    
    st.markdown("<h3 style='text-align: center; color: #1e293b; margin-top: 0;'>DFMA Check-in</h3>", unsafe_allow_html=True)
    
    # 1. 输入 Code
    st.markdown("<label style='font-size: 14px; color: #64748b; font-weight: 600;'>Enter 6-Digit Check In Code</label>", unsafe_allow_html=True)
    code = st.text_input("code_input", label_visibility="collapsed", max_chars=6, placeholder="______").strip()
    
    target_session = next((s for s in active_sessions if s['code'] == code), None)
    
    if target_session:
        st.success(f"📍 {target_session['name']}")
        
        # 2. 搜索名字
        df_participants = get_participants_data()
        
        if not df_participants.empty:
            all_names = sorted(df_participants['Name'].unique().tolist())
            # 搜索框代替 Selectbox
            search_query = st.selectbox("Search Your Name", [""] + all_names, placeholder="Type to search...")
            
            if search_query:
                # 3. IC 验证 (新逻辑)
                st.markdown("---")
                st.markdown("**🔐 Security Verification**")
                ic_input = st.text_input("Enter Last 4 Digits of IC", max_chars=4, type="password")
                
                if st.button("Verify & Check-in", type="primary", use_container_width=True):
                    # 获取该用户的真实 IC
                    try:
                        user_row = df_participants[df_participants['Name'] == search_query].iloc[0]
                        real_ic = str(user_row['IC']).strip() # 从 Google Sheet 读来的 IC
                        
                        # 验证逻辑
                        if len(ic_input) == 4 and real_ic.endswith(ic_input):
                            # 验证通过
                            cat = user_row['Category']
                            email = user_row['Email']
                            
                            success, status = write_log(target_session, search_query, cat, email=email)
                            
                            st.session_state.current_user = {"name": search_query, "status": status, "session": target_session['name']}
                            
                            with st.spinner("Verifying..."):
                                msg = ai_generate_welcome(search_query, target_session['name'])
                                st.session_state.welcome_msg = msg
                            
                            st.session_state.page = 'SUCCESS'
                            st.rerun()
                        else:
                            st.error("❌ IC Verification Failed. Please try again.")
                    except Exception as e:
                        st.error(f"System Error: Could not verify IC. {e}")

        # Walk-in 区域
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("⚠️ Name not in list? (Walk-in)"):
            wi_name = st.text_input("Full Name")
            wi_email = st.text_input("Email")
            wi_phone = st.text_input("Phone")
            
            if st.button("Register Walk-in", use_container_width=True):
                # Walk-in 不需要 IC 验证，或者你可以加上
                success, status = write_log(target_session, wi_name, "Walk-in", wi_email, wi_phone)
                st.session_state.current_user = {"name": wi_name, "status": status, "session": target_session['name']}
                st.session_state.welcome_msg = ai_generate_welcome(wi_name, target_session['name'])
                st.session_state.page = 'SUCCESS'
                st.rerun()
    
    st.markdown('</div>', unsafe_allow_html=True)

# C. 成功页
elif st.session_state.page == 'SUCCESS':
    user = st.session_state.current_user
    
    st.markdown('<div class="mobile-container">', unsafe_allow_html=True)
    
    # 金融风图标 (Candlestick)
    st.markdown("""
        <div style="text-align: center; margin-bottom: 20px;">
            <svg width="100" height="100" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17 3v18"/><path d="M7 3v18"/><path d="M13 8h8v8h-8z"/><path d="M3 8h8v8H3z"/>
            </svg>
        </div>
    """, unsafe_allow_html=True)
    
    # 状态显示
    status_text = "On-Time" if user['status'] == 'On-time' else "Late Check-in"
    status_color = "#16a34a" if user['status'] == 'On-time' else "#ca8a04" # Green vs Yellow
    
    st.markdown(f"""
    <div class="success-card">
        <h2 style="color: #1e3a8a; margin: 0;">Check-in Successful</h2>
        <p style="color: #64748b; font-size: 14px;">{user['session']}</p>
        <h3 style="font-size: 22px; color: #0f172a; margin-top: 15px;">{user['name']}</h3>
        <span style="background-color: {status_color}; color: white; padding: 5px 15px; border-radius: 20px; font-size: 12px; font-weight: bold;">{status_text}</span>
        <hr style="margin: 20px 0; border-top: 1px dashed #cbd5e1;">
        <p style="color: #475569; font-style: italic; font-size: 14px;">"{st.session_state.welcome_msg}"</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Done", use_container_width=True):
        st.session_state.page = 'HOME'
        st.rerun()
        
    st.markdown('</div>', unsafe_allow_html=True)
