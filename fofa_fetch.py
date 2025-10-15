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
    "湖南卫视": ["湖南", "湖南HD", "湖南卫视高清"],
    "浙江卫视": ["浙江", "浙江HD", "浙江卫视高清"],
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
# 工具函数
def normalize_channel_name(name):
    for std, aliases in CHANNEL_MAPPING.items():
        for alias in aliases:
            if alias.lower() in name.lower():
                return std
    return name.strip()

def test_url_latency(url, timeout=5):
    try:
        start = time.time()
        r = requests.get(url, timeout=timeout, stream=True)
        if r.status_code == 200:
            return time.time() - start
    except:
        return None
    return None

# ===============================
# 第一阶段：爬取 IP
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
# 第二阶段：生成并推送 zubo.txt
def second_stage():
    print("🔔 第二阶段触发：生成 zubo.txt")
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

        # 检测第一个频道可用性
        first_rtp_line = rtp_lines[0]
        if "," not in first_rtp_line:
            continue
        ch_name, rtp_url = first_rtp_line.split(",", 1)

        def build_and_check(ip_port):
            url = f"http://{ip_port}/rtp/{rtp_url.split('rtp://')[1]}"
            try:
                r = requests.get(url, timeout=5, stream=True)
                if r.status_code == 200:
                    return ip_port
            except:
                return None
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as exe:
            valid_ips = [ip for ip in exe.map(build_and_check, ip_lines) if ip]

        for ip_port in valid_ips:
            for rtp_line in rtp_lines:
                if "," not in rtp_line:
                    continue
                ch_name, rtp_url = rtp_line.split(",", 1)
                combined_lines.append(f"{ch_name},http://{ip_port}/rtp/{rtp_url.split('rtp://')[1]}")

    # 去重
    unique = {}
    for line in combined_lines:
        url_part = line.split(",", 1)[1]
        if url_part not in unique:
            unique[url_part] = line

    # 写入 zubo.txt 并推送
    with open(ZUBO_FILE, "w", encoding="utf-8") as f:
        for line in unique.values():
            f.write(line + "\n")
    print(f"🎯 第二阶段完成，zubo.txt 共 {len(unique)} 条 URL")

    os.system('git config --global user.name "github-actions"')
    os.system('git config --global user.email "github-actions@users.noreply.github.com"')
    os.system("git add zubo.txt")
    os.system('git commit -m "自动更新 zubo.txt" || echo "⚠️ 无需提交"')
    os.system("git push origin main")
    return unique

# ===============================
# 第三阶段：湖南卫视检测生成 IPTV.txt
def third_stage(zubo_lines):
    print("🧩 第三阶段开始：湖南卫视检测生成 IPTV.txt")

    # 分组：按 IP 归类
    groups = {}
    for line in zubo_lines.values():
        ch_name, url = line.split(",", 1)
        ip = re.search(r"http://(.*?)/", url).group(1)
        groups.setdefault(ip, []).append((ch_name, url))

    print(f"共解析到 {len(groups)} 个分组。开始湖南卫视检测...")

    valid_groups = []
    for grp_name, entries in groups.items():
        hunans = [(n, u) for n, u in entries if normalize_channel_name(n) == "湖南卫视"]
        if not hunans:
            continue
        latencies = [test_url_latency(u) for _, u in hunans]
        latencies = [l for l in latencies if l is not None]
        if latencies:
            best = min(latencies)
            valid_groups.append((grp_name, best, entries))

    if not valid_groups:
        print("没有可用分组（湖南卫视检测）。退出。")
        return

    # 排序并分类
    valid_groups.sort(key=lambda x: x[1])
    categorized = {cat: [] for cat in CHANNEL_CATEGORIES}
    for _, _, entries in valid_groups:
        for ch_name, url in entries:
            std_name = normalize_channel_name(ch_name)
            for cat, names in CHANNEL_CATEGORIES.items():
                if std_name in names:
                    categorized[cat].append(f"{std_name},{url}")
                    break

    # 写入 IPTV.txt
    with open(IPTV_FILE, "w", encoding="utf-8") as f:
        for cat, lines in categorized.items():
            f.write(f"{cat},#genre#\n")
            for line in sorted(set(lines)):
                f.write(line + "\n")
            f.write("\n")

    print(f"✅ 第三阶段完成，IPTV.txt 已生成")

    # 推送
    os.system('git config --global user.name "github-actions"')
    os.system('git config --global user.email "github-actions@users.noreply.github.com"')
    os.system("git add IPTV.txt")
    os.system('git commit -m "自动更新 IPTV.txt" || echo "⚠️ 无需提交"')
    os.system("git push origin main")

# ===============================
# 主流程
if __name__ == "__main__":
    run_count = first_stage()
    if run_count in [12, 24, 36, 48, 60, 72]:
        zubo_data = second_stage()
        third_stage(zubo_data)