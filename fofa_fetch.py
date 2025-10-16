import os
import re
import requests
import time
import concurrent.futures
import subprocess

# ===============================
# 配置区
FOFA_URLS = {
    "https://fofa.info/result?qbase64=InVkcHh5IiAmJiBjb3VudHJ5PSJDTiI%3D": "ip.txt",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

IP_DIR = "ip"
RTP_DIR = "rtp"
ZUBO_FILE = "zubo.txt"
IPTV_FILE = "IPTV.txt"
COUNTER_FILE = "计数.txt"

# ===============================
# 分类与映射配置
CHANNEL_CATEGORIES = {
    "央视频道": ["CCTV1", "CCTV2"],
    "卫视频道": ["湖南卫视", "浙江卫视"],
    "数字频道": ["CHC动作电影", "CHC家庭影院", "CHC影迷电影"],
}

CHANNEL_MAPPING = {
    "CCTV1": ["CCTV-1", "CCTV-1 HD", "CCTV1 HD", "CCTV-1综合", "CCTV1 4M1080", "CCTV1 5M1080HEVC"],
    "CCTV2": ["CCTV-2", "CCTV-2 HD", "CCTV2 HD", "CCTV-2财经", "CCTV2 720", "节目暂时不可用 1080"],
}

# ===============================
# 省份/运营商识别
def get_isp(ip):
    if re.match(r"^(1[0-9]{2}|2[0-3]{2}|42|43|58|59|60|61|110|111|112|113|114|115|116|117|118|119|120|121|122|123|124|125|126|127|175|180|182|183|184|185|186|187|188|189|223)\.", ip):
        return "电信"
    elif re.match(r"^(42|43|58|59|60|61|110|111|112|113|114|115|116|117|118|119|120|121|122|123|124|125|126|127|175|180|182|183|184|185|186|187|188|189|223)\.", ip):
        return "联通"
    elif re.match(r"^(223|36|37|38|39|100|101|102|103|104|105|106|107|108|109|134|135|136|137|138|139|150|151|152|157|158|159|170|178|182|183|184|187|188|189)\.", ip):
        return "移动"
    else:
        return "未知"

def get_province(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=5)
        return res.json().get("regionName", "未知")
    except:
        return "未知"

# ===============================
# 计数逻辑
def get_run_count():
    if os.path.exists(COUNTER_FILE):
        try:
            return int(open(COUNTER_FILE).read().strip())
        except:
            return 0
    return 0

def save_run_count(count):
    open(COUNTER_FILE, "w").write(str(count))

# ===============================
# 第一阶段：抓新 IP + 多线程检测 + 更新 ip/*.txt
def first_stage():
    print("📡 第一阶段：抓取新 IP + 多线程检测 + 更新 ip/*.txt")

    os.makedirs(IP_DIR, exist_ok=True)
    new_ips = set()
    for url, filename in FOFA_URLS.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            urls_all = re.findall(r'<a href="http://(.*?)"', r.text)
            new_ips.update(u.strip() for u in urls_all)
        except Exception as e:
            print(f"❌ 抓取失败 {filename}: {e}")
        time.sleep(1)

    print(f"✅ 抓取到 {len(new_ips)} 个新 IP")

    # ---- IP 按省份运营商分类 ----
    ip_dict = {}
    for ip_port in new_ips:
        ip = ip_port.split(":")[0]
        po = f"{get_province(ip)}{get_isp(ip)}"
        ip_dict.setdefault(po, set()).add(ip_port)

    # ---- 读取旧 IP 并合并 ----
    for fname in os.listdir(IP_DIR):
        if not fname.endswith(".txt"):
            continue
        province_operator = fname.replace(".txt", "")
        path = os.path.join(IP_DIR, fname)
        with open(path, encoding="utf-8") as f:
            for line in f:
                ip_dict.setdefault(province_operator, set()).add(line.strip())

    # ---- ffprobe 检测函数 ----
    def check_stream(url, timeout=5):
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-i", url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 2
            )
            return b"codec_type" in result.stdout
        except:
            return False

    # ---- 多线程检测 ----
    for po, ips in ip_dict.items():
        rtp_path = os.path.join(RTP_DIR, f"{po}.txt")
        if not os.path.exists(rtp_path):
            print(f"⚠️ {po} 没有 RTP 文件，跳过")
            ip_dict[po] = set()
            continue

        with open(rtp_path, encoding="utf-8") as f:
            rtp_lines = [x.strip() for x in f if x.strip()]

        cctv_lines = [line.split(",",1)[1] for line in rtp_lines if "CCTV1" in line]
        if not cctv_lines and rtp_lines:
            cctv_lines = [rtp_lines[0].split(",",1)[1]]

        valid_ips = set()
        def detect(ip_port):
            for rtp_url in cctv_lines:
                url = f"http://{ip_port}/rtp/{rtp_url.split('rtp://')[1]}"
                if check_stream(url):
                    valid_ips.add(ip_port)
                    break

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(detect, ips)

        ip_dict[po] = valid_ips

    # ---- 写回 ip/*.txt ----
    for po, ips in ip_dict.items():
        path = os.path.join(IP_DIR, f"{po}.txt")
        with open(path, "w", encoding="utf-8") as f:
            for ip in sorted(ips):
                f.write(ip + "\n")

    print("✅ 第一阶段完成，ip/*.txt 更新完毕")
    return ip_dict

# ===============================
# 第二阶段：生成 zubo.txt（每 12 轮触发）
def second_stage(ip_dict):
    print("🔔 第二阶段：生成 zubo.txt")
    combined_lines = []

    for fname in os.listdir(IP_DIR):
    