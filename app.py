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
# ⚙️ 配置与初始化
# ==========================================

# 1. 页面设置
st.set_page_config(page_title="DFMA Check-in", page_icon="✅", layout="wide")

# 2. 获取 API Keys
# 请确保在 .streamlit/secrets.toml 中配置了 GOOGLE_API_KEY
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        HAS_AI = True
    else:
        HAS_AI = False
except:
    HAS_AI = False

# 3. 文件路径配置
SESSION_FILE = "sessions.json"
BACKUP_FILE = "local_backup_logs.csv"
LOGO_FILE = "logo.png"  # 请确保上传名为 logo.png 的图片
ADMIN_PASSWORD = "admin" 

# ==========================================
# 🛠️ 核心功能函数
# ==========================================

# --- A. Session 管理 (本地持久化) ---
def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as f:
            return json.load(f)
    return []

def save_sessions(sessions):
    with open(SESSION_FILE, 'w') as f:
        json.dump(sessions, f)

# --- B. Google Sheets 连接 ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def get_participants_data():
    try:
        df = conn.read(worksheet="Participants", usecols=[0, 1])
        # 确保列名正确
        if len(df.columns) >= 2:
            df.columns = ['Name', 'Category']
        else:
            df.columns = ['Name']
            df['Category'] = 'Pre-registered'
        # 清理数据：去空值，转字符串
        return df.dropna(subset=['Name']).astype(str)
    except:
        return pd.DataFrame(columns=['Name', 'Category'])

def get_logs_data():
    try:
        # 实时读取日志，不做缓存以便投屏实时刷新
        return conn.read(worksheet="Logs", ttl=0)
    except:
        # 如果断网，读取本地备份
        if os.path.exists(BACKUP_FILE):
            return pd.read_csv(BACKUP_FILE)
        return pd.DataFrame()

# --- C. Gemini AI 助手 ---
def ai_generate_welcome(name, session_name):
    """生成个性化欢迎语"""
    if not HAS_AI:
        return f"Welcome {name}! Enjoy the class."
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        prompt = f"Write a short, inspiring 1-sentence welcome for a student named {name} attending '{session_name}'. Append a very short (1 sentence) interesting fact about financial markets. Total under 40 words."
        response = model.generate_content(prompt)
        return response.text
    except:
        return f"Welcome {name}! Ready to master the markets?"

def ai_suggest_title(topic):
    """生成高大上的课程标题"""
    if not HAS_AI:
        return f"DFMA Session: {topic}"
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        prompt = f"Create a professional, academic session title for 'Financial Market Analysis' course about: '{topic}'. Return ONLY the title."
        response = model.generate_content(prompt)
        return response.text.strip().replace('"', '')
    except:
        return f"Advanced Analysis: {topic}"

# --- D. 写入逻辑 ---
def write_log(session_data, name, user_type, email="-", phone="-"):
    # 马来西亚时间 UTC+8
    kl_time = datetime.utcnow() + timedelta(hours=8)
    timestamp_str = kl_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 迟到判断逻辑
    start_time_str = f"{session_data['date']} {session_data['start']}"
    try:
        session_start = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")
        
        # 解析 Duration (支持 15m 或 1hr 格式)
        duration_str = session_data['duration']
        if 'hr' in duration_str:
            buffer_min = int(duration_str.replace('hr','')) * 60
        else:
            buffer_min = int(duration_str.replace('m',''))
            
        is_late = kl_time > (session_start + timedelta(minutes=buffer_min))
        status = "Late" if is_late else "On-time"
    except:
        status = "Unknown"

    new_data = pd.DataFrame([{
        "Timestamp": timestamp_str,
        "Session": session_data['name'],
        "Name": name,
        "Type": user_type,
        "Status": status,
        "Email": email,
        "Phone": phone
    }])

    # 1. 本地备份 (双重保险)
    if not os.path.exists(BACKUP_FILE):
        new_data.to_csv(BACKUP_FILE, index=False)
    else:
        new_data.to_csv(BACKUP_FILE, mode='a', header=False, index=False)

    # 2. 尝试写入 Google Sheet
    try:
        existing_data = conn.read(worksheet="Logs", ttl=0)
        updated_df = pd.concat([existing_data, new_data], ignore_index=True)
        conn.update(worksheet="Logs", data=updated_df)
        return True, status
    except:
        # 如果 Google 写入失败，返回 True (因为本地已经保存了)
        return True, status

# ==========================================
# 🖥️ 页面逻辑控制
# ==========================================

# 初始化 Session State
if 'page' not in st.session_state: st.session_state.page = 'HOME'
if 'current_user' not in st.session_state: st.session_state.current_user = None
if 'welcome_msg' not in st.session_state: st.session_state.welcome_msg = ""

# 加载 Sessions
sessions = load_sessions()
active_sessions = [s for s in sessions if s.get('active', True)]

# --- 1. 侧边栏：Admin 后台 ---
with st.sidebar:
    # 🌟 Logo 显示
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, use_container_width=True)
    
    st.title("🔐 Admin Login")
    pwd = st.text_input("Password", type="password")
    
    if pwd == ADMIN_PASSWORD:
        st.success("Admin Unlocked")
        st.divider()
        
        tab_create, tab_manage = st.tabs(["Create Session", "Manage"])
        
        with tab_create:
            st.subheader("New Session")
            c1, c2 = st.columns([2, 1])
            topic = c1.text_input("Topic Keyword", placeholder="e.g. Risk")
            if c2.button("✨ AI Suggest"):
                with st.spinner("Asking Gemini..."):
                    suggestion = ai_suggest_title(topic)
                    st.session_state.new_title = suggestion
            
            sess_name = st.text_input("Session Name", value=st.session_state.get('new_title', ''))
            sess_date = st.date_input("Date")
            sess_time = st.time_input("Start Time")
            sess_dur = st.selectbox("Late Buffer", ["5m", "10m", "15m", "30m", "1hr"])
            
            if st.button("Create & Generate Code"):
                new_code = str(random.randint(100000, 999999))
                new_sess = {
                    "id": int(time.time()),
                    "name": sess_name,
                    "code": new_code,
                    "date": str(sess_date),
                    "start": str(sess_time),
                    "duration": sess_dur,
                    "active": True
                }
                sessions.append(new_sess)
                save_sessions(sessions)
                st.success(f"Created! Code: {new_code}")
                time.sleep(1)
                st.rerun()

        with tab_manage:
            st.subheader("Active Sessions")
            for s in active_sessions:
                with st.expander(f"{s['name']} ({s['code']})"):
                    st.caption(f"Starts: {s['date']} {s['start']}")
                    c1, c2 = st.columns(2)
                    if c1.button("📽️ Project Screen", key=f"proj_{s['id']}"):
                        st.session_state.project_session = s
                        st.session_state.page = 'PROJECTION'
                        st.rerun()
                    if c2.button("🗑️ Delete", key=f"del_{s['id']}"):
                        sessions.remove(s)
                        save_sessions(sessions)
                        st.rerun()
            
            st.divider()
            if st.button("📥 Export Logs to CSV"):
                df = get_logs_data()
                st.download_button("Click to Download", df.to_csv(index=False), "attendance_logs.csv")

# --- 2. 页面路由 ---

# === A. 投屏模式 (Project Screen - 大屏幕) ===
if st.session_state.page == 'PROJECTION':
    s = st.session_state.get('project_session')
    
    # 顶部栏
    c1, c2 = st.columns([8,1])
    if c2.button("Exit Projection"):
        st.session_state.page = 'HOME'
        st.rerun()
        
    if s:
        # 🌟 投屏 Logo
        if os.path.exists(LOGO_FILE):
            col_l, col_m, col_r = st.columns([1, 2, 1])
            with col_m:
                st.image(LOGO_FILE, use_container_width=True)

        # 标题样式
        st.markdown(f"""
        <style>
            .big-font {{ font-size: 80px !important; font-weight: bold; color: #1E3A8A; }}
            .step-box {{ background-color: #F1F5F9; padding: 20px; border-radius: 15px; border: 2px solid #E2E8F0; height: 100%; }}
            .step-title {{ color: #475569; font-weight: bold; font-size: 24px; text-transform: uppercase; letter-spacing: 2px; }}
        </style>
        <h1 style='text-align: center; color: #1E3A8A; font-size: 48px; margin-bottom: 0;'>{s['name']}</h1>
        <p style='text-align: center; color: #64748B; font-size: 24px; margin-top: 0;'>Attendance Check-in System</p>
        <hr>
        """, unsafe_allow_html=True)
        
        col_left, col_right = st.columns([1.2, 1])
        
        with col_left:
            c_qr, c_code = st.columns(2)
            # Step 1: QR Code
            with c_qr:
                st.markdown('<div class="step-box">', unsafe_allow_html=True)
                st.markdown('<div class="step-title">Step 1</div>', unsafe_allow_html=True)
                st.markdown("### Scan QR Code")
                # 动态生成指向当前 App 的二维码
                # 注意：部署后请将下方 URL 换成你的真实 Streamlit 网址
                url = "https://dfma-attendance.streamlit.app" 
                qr = qrcode.make(url)
                img_bytes = io.BytesIO()
                qr.save(img_bytes, format='PNG')
                st.image(img_bytes, caption="Scan to Check-in", use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            # Step 2: Passcode
            with c_code:
                st.markdown('<div class="step-box" style="background-color: #EFF6FF; border-color: #BFDBFE;">', unsafe_allow_html=True)
                st.markdown('<div class="step-title" style="color: #1E40AF;">Step 2</div>', unsafe_allow_html=True)
                st.markdown("### Enter Passcode")
                st.markdown(f'<p class="big-font">{s["code"]}</p>', unsafe_allow_html=True)
                st.info(f"Late after: {s['duration']}")
                st.markdown('</div>', unsafe_allow_html=True)

        with col_right:
            # 实时数据
            logs = get_logs_data()
            session_logs = logs[logs['Session'] == s['name']] if not logs.empty and 'Session' in logs.columns else pd.DataFrame()
            
            # 总人数指标
            st.metric("Total Checked-in", len(session_logs))
            
            # 滚动列表
            st.subheader("🔴 Live Feed (Recent 10)")
            if not session_logs.empty:
                # 按时间倒序，取前10个
                recent = session_logs.sort_values(by="Timestamp", ascending=False).head(10)
                
                for i, row in recent.iterrows():
                    # 名字打码处理 (Ju******ng)
                    name = str(row['Name'])
                    masked_name = name[:2] + "******" + name[-2:] if len(name) > 4 else name
                    
                    st.markdown(f"""
                    <div style="background: white; padding: 10px; border-radius: 8px; margin-bottom: 8px; border-left: 5px solid #3B82F6; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">
                        <span style="font-weight: bold; font-size: 18px;">{masked_name}</span>
                        <span style="float: right; color: #64748B; font-family: monospace;">{row['Timestamp'].split(' ')[1]}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Waiting for check-ins...")
        
        # 自动刷新 (每5秒)
        time.sleep(5) 
        st.rerun()

# === B. 学生签到模式 (Home - 手机端) ===
elif st.session_state.page == 'HOME':
    # 🌟 手机端 Logo (居中)
    if os.path.exists(LOGO_FILE):
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.image(LOGO_FILE, use_container_width=True)
    else:
        st.markdown("<h1 style='text-align: center;'>🎓 DFMA Check-in</h1>", unsafe_allow_html=True)
    
    # 1. 输入 Code
    code = st.text_input("Enter 6-Digit Check-in Code", max_chars=6, placeholder="e.g. 146865").strip()
    
    target_session = None
    if len(code) == 6:
        match = next((s for s in active_sessions if s['code'] == code), None)
        if match:
            target_session = match
            st.success(f"Joined: {match['name']}")
        else:
            st.error("❌ Invalid Code")

    if target_session:
        st.divider()
        
        # 2. 搜索名字 (带添加功能)
        df_participants = get_participants_data()
        
        # 提取唯一名字
        if not df_participants.empty:
            all_names = sorted(df_participants['Name'].unique().tolist())
        else:
            all_names = []
        
        selected_name = st.selectbox("Search Your Name", [""] + all_names)
        
        final_name = ""
        final_type = ""
        
        if selected_name:
            # 找到了名字
            row = df_participants[df_participants['Name'] == selected_name].iloc[0]
            cat = row['Category']
            st.info(f"Identity: {selected_name} ({cat})")
            final_name = selected_name
            final_type = cat
            
            if st.button("Confirm Check-in", type="primary", use_container_width=True):
                success, status = write_log(target_session, final_name, final_type)
                # 无论是存入 Sheet 还是 Local，都算成功
                st.session_state.current_user = {"name": final_name, "status": status, "session": target_session['name']}
                
                # 生成 AI 欢迎语
                with st.spinner("Generating your pass..."):
                    msg = ai_generate_welcome(final_name, target_session['name'])
                    st.session_state.welcome_msg = msg
                
                st.session_state.page = 'SUCCESS'
                st.rerun()
                    
        else:
            # 没找到名字，显示 Walk-in 表单
            with st.expander("Name not in list? Register Here", expanded=True):
                wi_name = st.text_input("Full Name (as per IC)")
                wi_email = st.text_input("Email")
                wi_phone = st.text_input("Phone")
                
                if st.button("Register & Check-in", type="primary"):
                    if wi_name and wi_email:
                        write_log(target_session, wi_name, "Walk-in", wi_email, wi_phone)
                        st.session_state.current_user = {"name": wi_name, "status": "Checking...", "session": target_session['name']}
                        
                        # Walk-in 也生成欢迎语
                        with st.spinner("Generating..."):
                            msg = ai_generate_welcome(wi_name, target_session['name'])
                            st.session_state.welcome_msg = msg
                            
                        st.session_state.page = 'SUCCESS'
                        st.rerun()
                    else:
                        st.error("Name and Email are required.")

# === C. 成功界面 ===
elif st.session_state.page == 'SUCCESS':
    user = st.session_state.current_user
    st.balloons()
    
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; background-color: #F0FDF4; border-radius: 15px; border: 2px solid #4ADE80;">
        <h1 style="color: #166534; font-size: 60px;">✅</h1>
        <h2 style="color: #15803D;">Check-in Successful!</h2>
        <p style="font-size: 18px;"><b>{user['name']}</b></p>
        <p style="color: #64748B;">{user['session']}</p>
        <hr>
        <p style="font-style: italic; color: #4338CA;">✨ {st.session_state.welcome_msg}</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Done (Back to Home)", use_container_width=True):
        st.session_state.page = 'HOME'
        st.session_state.welcome_msg = ""
        st.rerun()
