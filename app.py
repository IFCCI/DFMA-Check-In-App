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

st.set_page_config(page_title="DFMA Check-in", page_icon="✅", layout="wide")

# 获取 API Keys
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        HAS_AI = True
    else:
        HAS_AI = False
except:
    HAS_AI = False

# 文件路径配置
SESSION_FILE = "sessions.json"
BACKUP_FILE = "local_backup_logs.csv"     # 签到记录备份
LOCAL_NAMELIST = "local_namelist.csv"     # 名单备份 (上传的文件)
LOGO_FILE = "logo.png"
ADMIN_PASSWORD = "admin" 

# ==========================================
# 🛠️ 核心功能函数
# ==========================================

# --- A. Session 管理 ---
def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as f:
            return json.load(f)
    return []

def save_sessions(sessions):
    with open(SESSION_FILE, 'w') as f:
        json.dump(sessions, f)

# --- B. 数据读取 (双重保险: Google Sheet -> 本地文件) ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def get_participants_data():
    # 1. 优先尝试连接 Google Sheets
    try:
        # 读取前3列：Name, Email, Category
        df = conn.read(worksheet="Participants", usecols=[0, 1, 2])
        
        # 强制重命名列以匹配逻辑
        if len(df.columns) >= 3:
            df.columns = ['Name', 'Email', 'Category']
        elif len(df.columns) == 2:
            df.columns = ['Name', 'Email']
            df['Category'] = 'Pre-registered'
        else:
            df.columns = ['Name']
            df['Email'] = '-'
            df['Category'] = 'Pre-registered'
            
        return df.dropna(subset=['Name']).astype(str)
    except Exception:
        # 2. 如果 Google 失败 (没配 API 或断网)，读取本地上传的备份文件
        if os.path.exists(LOCAL_NAMELIST):
            try:
                df = pd.read_csv(LOCAL_NAMELIST)
                # 确保列名匹配
                required_cols = ['Name', 'Email', 'Category']
                for col in required_cols:
                    if col not in df.columns:
                        df[col] = '-' # 缺失列补全
                return df.astype(str)
            except:
                pass
        return pd.DataFrame(columns=['Name', 'Email', 'Category'])

def get_logs_data():
    # 读取日志也是同样的逻辑：先云端，后本地
    try:
        return conn.read(worksheet="Logs", ttl=0)
    except:
        if os.path.exists(BACKUP_FILE):
            return pd.read_csv(BACKUP_FILE)
        return pd.DataFrame()

# --- C. Gemini AI (仅保留欢迎语功能) ---
def ai_generate_welcome(name, session_name):
    if not HAS_AI:
        return f"Welcome {name}! Enjoy the class."
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        prompt = f"Write a short, inspiring 1-sentence welcome for a student named {name} attending '{session_name}'. Total under 30 words."
        response = model.generate_content(prompt)
        return response.text
    except:
        return f"Welcome {name}! Ready to master the markets?"

# --- D. 写入逻辑 (双写模式) ---
def write_log(session_data, name, user_type, email="-", phone="-"):
    kl_time = datetime.utcnow() + timedelta(hours=8)
    timestamp_str = kl_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 迟到判断
    start_time_str = f"{session_data['date']} {session_data['start']}"
    try:
        session_start = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")
        duration_str = session_data['duration']
        buffer_min = int(duration_str.replace('hr','')) * 60 if 'hr' in duration_str else int(duration_str.replace('m',''))
        is_late = kl_time > (session_start + timedelta(minutes=buffer_min))
        status = "Late" if is_late else "On-time"
    except:
        status = "Unknown"

    new_data = pd.DataFrame([{
        "Timestamp": timestamp_str,
        "Session": session_data['name'],
        "Name": name,
        "Type": user_type, # Category
        "Status": status,
        "Email": email,
        "Phone": phone
    }])

    # 1. 必写：本地备份 CSV (保底)
    if not os.path.exists(BACKUP_FILE):
        new_data.to_csv(BACKUP_FILE, index=False)
    else:
        new_data.to_csv(BACKUP_FILE, mode='a', header=False, index=False)

    # 2. 选写：尝试同步 Google Sheet (Logs 分页)
    try:
        existing_data = conn.read(worksheet="Logs", ttl=0)
        updated_df = pd.concat([existing_data, new_data], ignore_index=True)
        conn.update(worksheet="Logs", data=updated_df)
        return True, status
    except:
        # 只要本地写成功了，就算成功
        return True, status

# ==========================================
# 🖥️ 页面逻辑
# ==========================================

if 'page' not in st.session_state: st.session_state.page = 'HOME'
if 'current_user' not in st.session_state: st.session_state.current_user = None
if 'welcome_msg' not in st.session_state: st.session_state.welcome_msg = ""

sessions = load_sessions()
active_sessions = [s for s in sessions if s.get('active', True)]

# --- 1. 侧边栏：Admin 后台 ---
with st.sidebar:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, use_container_width=True)
    
    st.title("🔐 Admin Login")
    pwd = st.text_input("Password", type="password")
    
    if pwd == ADMIN_PASSWORD:
        st.success("Admin Unlocked")
        st.divider()
        
        tab_create, tab_manage, tab_backup = st.tabs(["Create", "Manage", "Backup/Import"])
        
        with tab_create:
            st.subheader("New Session")
            # 移除了 AI 建议标题功能
            sess_name = st.text_input("Session Name", placeholder="e.g. DFMA Module 1")
            sess_date = st.date_input("Date")
            sess_time = st.time_input("Start Time")
            sess_dur = st.selectbox("Late Buffer", ["5m", "10m", "15m", "30m", "1hr"])
            
            if st.button("Create"):
                if not sess_name:
                    st.error("Please enter a Session Name")
                else:
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
                    st.success(f"Code: {new_code}")
                    time.sleep(1)
                    st.rerun()

        with tab_manage:
            for s in active_sessions:
                with st.expander(f"{s['name']} ({s['code']})"):
                    if st.button("📽️ Project", key=f"p_{s['id']}"):
                        st.session_state.project_session = s
                        st.session_state.page = 'PROJECTION'
                        st.rerun()
                    if st.button("🗑️ Delete", key=f"d_{s['id']}"):
                        sessions.remove(s)
                        save_sessions(sessions)
                        st.rerun()

        # === 🌟 新增：灾备管理 ===
        with tab_backup:
            st.subheader("📂 Backup & Restore")
            st.caption("如果 Google Sheets 连不上，请在这里上传名单。")
            
            # 1. 导出签到记录
            if os.path.exists(BACKUP_FILE):
                with open(BACKUP_FILE, "rb") as f:
                    st.download_button("📥 Download Logs (Local CSV)", f, "backup_logs.csv")
            else:
                st.info("No local logs yet.")

            # 2. 导入名单 (覆盖 Google Sheet 逻辑)
            uploaded_file = st.file_uploader("Upload Namelist (Excel/CSV)", type=['csv', 'xlsx'])
            if uploaded_file:
                try:
                    if uploaded_file.name.endswith('.csv'):
                        df_up = pd.read_csv(uploaded_file)
                    else:
                        df_up = pd.read_excel(uploaded_file)
                    
                    # 保存为标准 CSV 供程序读取
                    df_up.to_csv(LOCAL_NAMELIST, index=False)
                    st.success(f"✅ Loaded {len(df_up)} names locally!")
                except Exception as e:
                    st.error(f"Error: {e}")

# --- 2. 页面路由 (保持原有逻辑) ---

# A. 投屏模式
if st.session_state.page == 'PROJECTION':
    s = st.session_state.get('project_session')
    c1, c2 = st.columns([8,1])
    if c2.button("Exit"):
        st.session_state.page = 'HOME'
        st.rerun()
        
    if s:
        if os.path.exists(LOGO_FILE):
            col_l, col_m, col_r = st.columns([1, 2, 1])
            with col_m: st.image(LOGO_FILE, use_container_width=True)

        st.markdown(f"<h1 style='text-align: center; color: #1E3A8A;'>{s['name']}</h1>", unsafe_allow_html=True)
        
        col_left, col_right = st.columns([1.2, 1])
        with col_left:
            st.info(f"### Passcode: {s['code']}")
            # QR Code
            url = "https://dfma-checkin-app-2026.streamlit.app" 
            qr = qrcode.make(url)
            img_bytes = io.BytesIO()
            qr.save(img_bytes, format='PNG')
            st.image(img_bytes, caption="Scan to Check-in", width=300)

        with col_right:
            logs = get_logs_data()
            if not logs.empty and 'Session' in logs.columns:
                session_logs = logs[logs['Session'] == s['name']]
                st.metric("Total Checked-in", len(session_logs))
                st.subheader("Live Feed")
                # 显示最近 5 个
                st.dataframe(session_logs.sort_values("Timestamp", ascending=False).head(5)[['Name', 'Timestamp']], hide_index=True)
            else:
                st.info("Waiting for check-ins...")
        
        time.sleep(5)
        st.rerun()

# B. 学生签到模式
elif st.session_state.page == 'HOME':
    if os.path.exists(LOGO_FILE):
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2: st.image(LOGO_FILE, use_container_width=True)
    else:
        st.title("🎓 DFMA Check-in")
    
    code = st.text_input("Check-in Code", max_chars=6).strip()
    
    target_session = next((s for s in active_sessions if s['code'] == code), None)
    
    if target_session:
        st.success(f"Joined: {target_session['name']}")
        df_participants = get_participants_data() # 这里会尝试读 Google，失败读本地上传的
        
        all_names = sorted(df_participants['Name'].unique().tolist()) if not df_participants.empty else []
        selected_name = st.selectbox("Search Name", [""] + all_names)
        
        if selected_name:
            if st.button("Confirm Check-in", type="primary"):
                # 获取用户信息
                try:
                    user_row = df_participants[df_participants['Name'] == selected_name].iloc[0]
                    cat = user_row['Category']
                    email = user_row['Email']
                except:
                    cat = "Unknown"
                    email = "-"
                    
                success, status = write_log(target_session, selected_name, cat, email=email)
                st.session_state.current_user = {"name": selected_name, "status": status, "session": target_session['name']}
                
                with st.spinner("Generating pass..."):
                    msg = ai_generate_welcome(selected_name, target_session['name'])
                    st.session_state.welcome_msg = msg
                st.session_state.page = 'SUCCESS'
                st.rerun()
        else:
            with st.expander("Name not in list?"):
                wi_name = st.text_input("Name")
                wi_email = st.text_input("Email")
                wi_phone = st.text_input("Phone")
                if st.button("Register Walk-in"):
                    write_log(target_session, wi_name, "Walk-in", wi_email, wi_phone)
                    st.session_state.current_user = {"name": wi_name, "status": "Checked", "session": target_session['name']}
                    st.session_state.welcome_msg = ai_generate_welcome(wi_name, target_session['name'])
                    st.session_state.page = 'SUCCESS'
                    st.rerun()

# C. 成功页
elif st.session_state.page == 'SUCCESS':
    user = st.session_state.current_user
    st.balloons()
    st.success(f"Check-in Successful for {user['name']}!")
    st.info(f"✨ {st.session_state.welcome_msg}")
    if st.button("Done"):
        st.session_state.page = 'HOME'
        st.rerun()
