# -*- coding: utf-8 -*-
"""按段提交 RunningHub 人物替换任务。

密钥、模式、并发都从项目根目录的 txt 读，不写死在这里：
RH_API_KEY_FILE 或 runtime.json 指定目录外私有密钥文件；ai应用.txt 写「模式 ai 或 cn」「实例 <规格>」「一采分辨率 <数值>」；
并发数.txt 一行整数。
单人段节点 137 图 / 138 提示词 / 321 视频 / 326 帧数 / 115 一采分辨率，双人段另加节点 139 第二张图。
模式只决定走哪个站点和哪一套应用，应用编号不进 txt。

源视频统一读 补齐生成用：前 44 段里需要补的已按 17n+5 用末帧补齐，
原本就符合的保持原样，002 仍是未补帧的原片。326 节点填这个目录里视频文件名上的帧数。
002 全段没有人，不提交。

安装版保留此文件作为原包配置和映射参考。执行生成统一使用 apt_runtime.py，禁止旧单run重试器重复付费。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "补齐生成用")
PROMPT = os.path.join(ROOT, "提示词")
REF = os.path.join(ROOT, "替换用参考图")
OUT = os.environ.get("RH_OUT", os.path.join(ROOT, "完成分段"))
STATE = os.environ.get("RH_STATE", os.path.join(ROOT, "rh_state.json"))
MAX_ATTEMPTS = 3

# 固定映射：文件名就是人物编号；逻辑一只使用 一号.png，逻辑二只使用 二号.png。
# 禁止根据照片外观、源片性别、服装或历史记录反向映射。002 全段没有人，不在这里。
# 008–013 的前景演唱者是二号，后景鼓手是一号，均需替换，走双人。
# 004、007、017 按用户决定用原片，不做替换，不在这里；不要加回 CAST。
CAST = {
    "001": "一二", "003": "一二", "005": "二", "006": "一二",
    "008": "一二", "009": "一二", "010": "一二", "011": "一二", "012": "一二",
    "013": "一二", "014": "一二", "015": "一二", "016": "一二", "018": "一二",
    "019": "一二", "020": "一二", "021": "一二", "022": "一二", "023": "一二", "024": "一二",
    "025": "一二", "026": "一二", "027": "一", "028": "一二", "029": "一二",
    "030": "一二", "031": "一二", "032": "一二", "033": "一二", "034": "一二",
    "035": "一二", "036": "一二", "037": "一二", "038": "一二", "039": "一二",
    "040": "一二", "041": "一二", "042": "二", "043": "一二", "044": "一二",
}
# 文件名即人物身份，不做任何反向映射：一号 -> 一号.png，二号 -> 二号.png。
IMG = {"一": os.path.join(REF, "一号.png"), "二": os.path.join(REF, "二号.png")}


def read_text(name):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        raise SystemExit(f"缺少 {name}")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def api_key():
    # Installed adapter: credentials remain outside the skill and run.
    value = os.environ.get("RH_API_KEY", "").strip()
    if value:
        return value
    key_file = os.environ.get("RH_API_KEY_FILE")
    runtime_path = os.path.join(ROOT, "runtime.json")
    if not key_file and os.path.isfile(runtime_path):
        with open(runtime_path, encoding="utf-8-sig") as stream:
            key_file = json.load(stream).get("api_key_file")
    if not key_file or not os.path.isfile(key_file):
        raise SystemExit("请使用 RH_API_KEY_FILE 或 runtime.json 指定技能/制作目录外的RH私有Key文件")
    with open(key_file, encoding="utf-8-sig") as stream:
        value = stream.read().strip()
    if not value:
        raise SystemExit("本机RH私有Key文件为空")
    return value


# 模式决定站点与应用，编号只放这里，不进 txt。两套应用的节点完全一样。
MODES = {
    "ai": {"站点": "https://www.runninghub.ai",
           "单人": "2107844752011010050", "双人": "2107845954833907713"},
    "cn": {"站点": "https://www.runninghub.cn",
           "单人": "2109234869904695297", "双人": "2109238926799101954"},
}


def app_config():
    """ai应用.txt：模式 <ai 或 cn，可省略，默认 ai> / 实例 <规格> / 一采分辨率 <数值，可省略，默认 1>。"""
    cfg = {}
    for line in read_text("ai应用.txt").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("模式", "实例", "一采分辨率"):
            cfg[parts[0]] = parts[1]
    if not cfg.get("实例"):
        raise SystemExit("ai应用.txt 缺少：实例")
    mode = cfg.setdefault("模式", "ai")
    if mode not in MODES:
        raise SystemExit(f"ai应用.txt 的模式只能是 ai 或 cn：{mode}")
    cfg["站点"] = MODES[mode]["站点"]
    cfg["单人"] = MODES[mode]["单人"]
    cfg["双人"] = MODES[mode]["双人"]
    cfg.setdefault("一采分辨率", "1")
    return cfg


def concurrency():
    text = read_text("并发数.txt").splitlines()[0].strip()
    try:
        n = int(text)
    except ValueError:
        raise SystemExit(f"并发数.txt 不是整数：{text}")
    if n < 1:
        raise SystemExit("并发数.txt 至少是 1")
    return n


def api(method, path, base, data=None, files=None, timeout=300):
    key = api_key()
    url = base + path
    if files is None:
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + key)
    else:
        import uuid
        boundary = uuid.uuid4().hex
        name, content = files
        chunks = [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        body = b"".join(chunks)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} {path}: {detail[:500]}")


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"uploads": {}, "tasks": {}}


def save_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def upload(path, state, base):
    key = os.path.abspath(path)
    cached = state["uploads"].get(key)
    if cached:
        return cached
    with open(path, "rb") as f:
        content = f.read()
    res = api("POST", "/openapi/v2/media/upload/binary", base,
              files=(os.path.basename(path), content))
    if res.get("code") != 0:
        raise RuntimeError(f"上传失败 {path}: {res}")
    name = res["data"]["fileName"]
    state["uploads"][key] = name
    save_state(state)
    print(f"uploaded {os.path.basename(path)} -> {name}", flush=True)
    return name


def video_path(num):
    hits = [f for f in os.listdir(SRC) if f.startswith(num + " ") and f.endswith(".mp4")]
    if len(hits) != 1:
        raise SystemExit(f"{num} 的源视频不唯一: {hits}")
    return os.path.join(SRC, hits[0])


def frames_of(num):
    # 326 节点填这一段要生成的帧数，用源视频文件名里的帧数
    name = os.path.basename(video_path(num))
    return name.split(" ")[1].replace(".mp4", "")


def attempts_of(state, num):
    return int(state["tasks"].get(num, {}).get("attempts") or 0)


def given_up(state, num):
    t = state["tasks"].get(num) or {}
    return t.get("status") == "FAILED" and attempts_of(state, num) >= MAX_ATTEMPTS


def is_active(state, num):
    t = state["tasks"].get(num) or {}
    st = t.get("status")
    if st == "SUCCESS" and t.get("file"):
        return False
    if given_up(state, num):
        return False
    if st == "FAILED":
        return False
    return bool(t.get("taskId"))


def needs_submit(state, num):
    t = state["tasks"].get(num)
    if t is None:
        return True
    if t.get("status") == "SUCCESS" and t.get("file"):
        return False
    if t.get("status") == "SUCCESS" and not t.get("file"):
        return False
    if given_up(state, num):
        return False
    if t.get("status") == "FAILED":
        return True
    return False


def submit(num, state, cfg):
    attempts = attempts_of(state, num) + 1
    cast = CAST[num]
    prompt = open(os.path.join(PROMPT, num + ".txt"), encoding="utf-8").read().strip()
    base = cfg["站点"]
    nodes = [
        {"nodeId": "137", "fieldName": "image",
         "fieldValue": upload(IMG[cast[0]], state, base), "description": None},
        {"nodeId": "138", "fieldName": "value", "fieldValue": prompt, "description": None},
        {"nodeId": "321", "fieldName": "video",
         "fieldValue": upload(video_path(num), state, base), "description": None},
        {"nodeId": "326", "fieldName": "value", "fieldValue": frames_of(num), "description": None},
        {"nodeId": "115", "fieldName": "megapixels",
         "fieldValue": cfg["一采分辨率"], "description": None},
    ]
    app = cfg["单人"]
    if len(cast) == 2:
        nodes.append({"nodeId": "139", "fieldName": "image",
                      "fieldValue": upload(IMG[cast[1]], state, base), "description": None})
        app = cfg["双人"]
    res = api("POST", "/openapi/v2/run/ai-app/" + app, base, {
        "nodeInfoList": nodes, "instanceType": cfg["实例"], "usePersonalQueue": "false"})
    if not res.get("taskId"):
        raise RuntimeError(f"{num} 提交失败: {res}")
    state["tasks"][num] = {
        "taskId": res["taskId"],
        "status": res.get("status"),
        "app": app,
        "base": base,
        "frames": frames_of(num),
        "attempts": attempts,
    }
    save_state(state)
    print(f"submitted {num} -> {res['taskId']} ({res.get('status')}) attempt {attempts}",
          flush=True)


def mark_failed(num, state, err):
    t = state["tasks"].setdefault(num, {})
    t["status"] = "FAILED"
    t["error"] = str(err)[:500]
    t["attempts"] = max(attempts_of(state, num), 1)
    save_state(state)
    n = t["attempts"]
    if n >= MAX_ATTEMPTS:
        print(f"{num} FAILED attempt {n}/{MAX_ATTEMPTS}, give up: {t['error']}", flush=True)
    else:
        print(f"{num} FAILED attempt {n}/{MAX_ATTEMPTS}, will retry: {t['error']}", flush=True)


def try_submit(num, state, cfg):
    try:
        submit(num, state, cfg)
        return True
    except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as e:
        mark_failed(num, state, e)
        return False


def refresh(state):
    base = app_config()["站点"]
    for num, t in list(state["tasks"].items()):
        if t.get("status") == "SUCCESS" and t.get("file"):
            continue
        if t.get("status") == "FAILED":
            continue
        if not t.get("taskId"):
            continue
        if t.get("base") and t["base"] != base:
            print(f"{num} 是在 {t['base']} 提交的，当前模式是 {base}，查不到，跳过", flush=True)
            continue
        try:
            res = api("POST", "/openapi/v2/query", base, {"taskId": t["taskId"]})
        except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"{num} query error: {e}", flush=True)
            continue
        t["status"] = res.get("status")
        if res.get("status") == "FAILED":
            t["error"] = res.get("errorMessage") or res.get("failedReason")
            n = attempts_of(state, num)
            if n >= MAX_ATTEMPTS:
                print(f"{num} FAILED attempt {n}/{MAX_ATTEMPTS}, give up: {t['error']}",
                      flush=True)
            else:
                print(f"{num} FAILED attempt {n}/{MAX_ATTEMPTS}, will retry: {t['error']}",
                      flush=True)
        elif res.get("status") == "SUCCESS":
            urls = [r for r in (res.get("results") or []) if r.get("url")]
            t["results"] = urls
            if not urls:
                t["status"] = "FAILED"
                t["error"] = "SUCCESS but no result url"
                n = attempts_of(state, num)
                if n >= MAX_ATTEMPTS:
                    print(f"{num} FAILED attempt {n}/{MAX_ATTEMPTS}, give up: no result url",
                          flush=True)
                else:
                    print(f"{num} FAILED attempt {n}/{MAX_ATTEMPTS}, will retry: no result url",
                          flush=True)
            else:
                print(f"{num} SUCCESS {len(urls)} file(s)", flush=True)
        else:
            print(f"{num} {res.get('status')}", flush=True)
    save_state(state)


def download(state):
    os.makedirs(OUT, exist_ok=True)
    for num, t in state["tasks"].items():
        if t.get("status") != "SUCCESS" or t.get("file"):
            continue
        urls = t.get("results") or []
        if not urls:
            print(f"{num} 没有结果地址", flush=True)
            continue
        url = urls[-1]["url"]
        ext = urls[-1].get("outputType") or "mp4"
        dest = os.path.join(OUT, f"{num}.{ext}")
        ok = False
        for i in range(3):
            try:
                urllib.request.urlretrieve(url, dest)
                ok = True
                break
            except (OSError, urllib.error.URLError) as e:
                print(f"{num} download error ({i + 1}/3): {e}", flush=True)
                time.sleep(5)
        if not ok:
            t["download_fails"] = int(t.get("download_fails") or 0) + 1
            nfail = t["download_fails"]
            print(f"{num} download failed ({nfail}/3)", flush=True)
            if nfail >= 3:
                t["status"] = "FAILED"
                t["error"] = "download failed 3 times"
                t.pop("file", None)
            continue
        t["file"] = dest
        t["download_fails"] = 0
        print(f"downloaded {num} -> {dest}", flush=True)
    save_state(state)


def poll_and_download(state):
    """查状态；成功的立刻下载。"""
    refresh(state)
    download(state)


def active_nums(state):
    return [n for n in state["tasks"] if is_active(state, n)]


def fill_slots(nums, state, cfg, limit):
    """在并发上限内提交还没成功、还没放弃的段。"""
    submitted = []
    active = active_nums(state)
    for num in nums:
        if not needs_submit(state, num):
            if given_up(state, num):
                print(f"skip {num}, given up after {attempts_of(state, num)} failures",
                      flush=True)
            elif state["tasks"].get(num, {}).get("status") == "SUCCESS":
                print(f"skip {num}, already SUCCESS", flush=True)
            else:
                print(f"skip {num}, already {state['tasks'][num].get('status')}",
                      flush=True)
            continue
        if given_up(state, num):
            continue
        while len(active) >= limit:
            print(f"在跑 {len(active)} 个，等 30 秒", flush=True)
            time.sleep(30)
            poll_and_download(state)
            active = active_nums(state)
            retry_now = [n for n in nums if needs_submit(state, n) and not given_up(state, n)]
            if retry_now and len(active) < limit:
                break
        if not needs_submit(state, num) or given_up(state, num):
            continue
        if try_submit(num, state, cfg):
            submitted.append(num)
        else:
            time.sleep(5)
        active = active_nums(state)
    return submitted


def wait_until_done(nums, state, cfg, limit):
    while True:
        poll_and_download(state)
        pending = [n for n in nums if needs_submit(state, n) and not given_up(state, n)]
        active = [n for n in nums if is_active(state, n)]
        if pending:
            fill_slots(pending, state, cfg, limit)
            continue
        if not active:
            break
        print(f"在跑 {len(active)} 个，等 30 秒", flush=True)
        time.sleep(30)


def report(state, nums):
    ok = []
    failed = []
    for n in nums:
        t = state["tasks"].get(n) or {}
        if t.get("status") == "SUCCESS" and t.get("file"):
            ok.append(n)
        else:
            failed.append(n)
    print(f"完成 {len(ok)}/{len(nums)}", flush=True)
    if failed:
        print("失败或未完成： " + " ".join(failed), flush=True)
        for n in failed:
            t = state["tasks"].get(n) or {}
            print(f"  {n}: {t.get('status')} attempt {attempts_of(state, n)}/{MAX_ATTEMPTS}"
                  f" {t.get('error') or ''}", flush=True)
    return failed


def main():
    raise SystemExit("旧调度入口已停用；使用 apt_runtime.py prepare/check/status/run，共享账户台账与原taskId恢复。")
    cmd = sys.argv[1]
    state = load_state()
    if cmd == "submit":
        cfg = app_config()
        limit = concurrency()
        nums = sys.argv[2:]
        fill_slots(nums, state, cfg, limit)
        wait_until_done(nums, state, cfg, limit)
        report(state, nums)
    elif cmd == "status":
        poll_and_download(state)
    elif cmd == "download":
        poll_and_download(state)
    else:
        raise SystemExit("用法: submit <段号...> | status | download")


if __name__ == "__main__":
    main()
