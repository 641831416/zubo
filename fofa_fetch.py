import os
import re
import requests
import time
import concurrent.futures

# ===============================
# 配置区
FOFA_URLS = {
    "https://fofa.info/result?qbase64=InVkcHh5IiAmJiBjb3VudHJ5PSJDTiI%3D": "ip.txt",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

COUNTER_FILE = "计数.txt"
IP_DIR = "ip"
RTP_DIR = "rtp"
ZUBO_FILE = "zubo.txt"
IPTV_FILE = "IPTV.txt"

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

def check_and_clear_files_by_run_count():
    os.makedirs(IP_DIR, exist_ok=True)
    count = get_run_count() + 1
    if count >= 73:
        print(f"🧹 第 {count} 次运行，清空 {IP_DIR} 下所有 .txt 文件")
        for f in os.listdir(IP_DIR):
            if f.endswith(".txt"):
                os.remove(os.path.join(IP_DIR, f))
        save_run_count(1)
        return "w", 1
    else:
        save_run_count(count)
        return "a", count

# ===============================
# IP 运营商判断
def get_isp(ip):
    if ip.startswith(("113.", "116.", "117.", "118.", "119.")):
        return "电信"
    elif ip.startswith(("36.", "39.", "42.", "43.", "58.")):
        return "联通"
    elif ip.startswith(("100.", "101.", "102.", "103.", "104.", "223.")):
        return "移动"
    return "未知"

# ===============================
# 第一阶段：爬取 + 分类写入
def first_stage():
    all_ips = set()
    for url, filename in FOFA_URLS.items():
        print(f"📡 正在爬取 {filename} ...")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            urls_all = re.findall(r'<a href="http://(.*?)"', r.text)
            all_ips.update(u.strip() for u in urls_all)
        except Exception as e:
            print(f"❌ 爬取失败：{e}")
        time.sleep(3)

    province_isp_dict = {}
    for ip_port in all_ips:
        try:
            ip = ip_port.split(":")[0]
            res = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=10)
            data = res.json()
            province = data.get("regionName", "未知")
            isp = get_isp(ip)
            if isp == "未知":
                continue
            fname = f"{province}{isp}.txt"
            province_isp_dict.setdefault(fname, set()).add(ip_port)
        except Exception:
            continue

    mode, run_count = check_and_clear_files_by_run_count()
    for filename, ip_set in province_isp_dict.items():
        path = os.path.join(IP_DIR, filename)
        with open(path, mode, encoding="utf-8") as f:
            for ip_port in sorted(ip_set):
                f.write(ip_port + "\n")
        print(f"{path} 已{'覆盖' if mode=='w' else '追加'}写入 {len(ip_set)} 个 IP")
    print(f"✅ 第一阶段完成，当前轮次：{run_count}")
    return run_count

# ===============================
# 第二阶段：检测并生成 zubo.txt（严格模式）
def second_stage():
    print("🔔 第二阶段触发：生成 zubo.txt（严格检测模式）")
    combined_lines = []
    for ip_file in os.listdir(IP_DIR):
        if not ip_file.endswith(".txt"):
            continue
        ip_path = os.path.join(IP_DIR, ip_file)
        rtp_path = os.path.join(RTP_DIR, ip_file)
        if not os.path.exists(rtp_path):
            continue

        province_operator = ip_file.replace(".txt", "")
        with open(ip_path, encoding="utf-8") as f1, open(rtp_path, encoding="utf-8") as f2:
            ip_lines = [x.strip() for x in f1 if x.strip()]
            rtp_lines = [x.strip() for x in f2 if x.strip()]

        if not ip_lines or not rtp_lines:
            continue

        first_rtp_line = rtp_lines[0]
        channel_name, rtp_url = first_rtp_line.split(",", 1)

        def build_and_check(ip_port):
            url = f"http://{ip_port}/rtp/{rtp_url.split('rtp://')[1]}"
            try:
                r = requests.get(url, timeout=5, stream=True)
                if r.status_code == 200:
                    return ip_port
            except Exception:
                return None
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as exe:
            valid_ips = [ip for ip in exe.map(build_and_check, ip_lines) if ip]

        for idx, ip_port in enumerate(valid_ips, start=1):
            suffix = f"${province_operator}{idx if len(valid_ips)>1 else ''}"
            for rtp_line in rtp_lines:
                ch_name, rtp_url = rtp_line.split(",", 1)
                combined_lines.append(f"{ch_name},http://{ip_port}/rtp/{rtp_url.split('rtp://')[1]}{suffix}")

    # 去重
    unique = {}
    for line in combined_lines:
        url_part = line.split(",", 1)[1].split("$")[0]
        if url_part not in unique:
            unique[url_part] = line

    with open(ZUBO_FILE, "w", encoding="utf-8") as f:
        for line in unique.values():
            f.write(line + "\n")
    print(f"🎯 第二阶段完成，共 {len(unique)} 条有效 URL（未推送）")

# ===============================
# 第三阶段：检测 CCTV1，有效则保留整组频道并推送 IPTV.txt
def third_stage():
    print("🧩 第三阶段开始：检测 CCTV1 并分类生成 IPTV.txt")
    if not os.path.exists(ZUBO_FILE):
        print("⚠️ 未找到 zubo.txt，跳过第三阶段")
        return

    with open(ZUBO_FILE, encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip()]

    # 建立频道映射反查表
    reverse_map = {}
    for std, aliases in CHANNEL_MAPPING.items():
        for name in aliases:
            reverse_map[name] = std

    # 映射标准频道名
    mapped_lines = []
    for line in lines:
        ch_name, url = line.split(",", 1)
        ch_std = reverse_map.get(ch_name, ch_name)
        mapped_lines.append((ch_std, url))

    # 分组：按 IP 归类
    ip_groups = {}
    for ch, url in mapped_lines:
        ip_match = re.search(r"http://(.*?)/", url)
        if ip_match:
            ip = ip_match.group(1)
            ip_groups.setdefault(ip, []).append((ch, url))

    # 检测 CCTV1 是否可播放
    def test_url(url):
        try:
            r = requests.get(url, timeout=5, stream=True)
            return r.status_code == 200
        except:
            return False

    valid_lines = []
    for ip, entries in ip_groups.items():
        cctv1_urls = [u for c, u in entries if c == "CCTV1"]
        playable = any(test_url(u.split("$")[0]) for u in cctv1_urls)
        if playable:
            valid_lines.extend([f"{c},{u}" for c, u in entries])

    # 分类排序输出
    ordered_lines = []
    for category, names in CHANNEL_CATEGORIES.items():
        for ch in names:
            ordered_lines.extend([line for line in valid_lines if line.startswith(ch + ",")])

    with open(IPTV_FILE, "w", encoding="utf-8") as f:
        for line in ordered_lines:
            f.write(line + "\n")

    print(f"✅ 第三阶段完成，生成 IPTV.txt 共 {len(ordered_lines)} 条")
    os.system('git config --global user.name "github-actions"')
    os.system('git config --global user.email "github-actions@users.noreply.github.com"')
    os.system("git add IPTV.txt")
    os.system('git commit -m "自动更新 IPTV.txt" || echo "⚠️ 无需提交"')
    os.system("git push origin main")

# ===============================
# 主执行逻辑
if __name__ == "__main__":
    run_count = first_stage()
    if run_count in [12, 24, 36, 48, 60, 72]:
        second_stage()
        third_stage()