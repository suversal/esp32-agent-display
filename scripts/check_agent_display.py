"""Compile the real device renderer/protocol on the host, test, and render a preview."""
import json
from pathlib import Path
import subprocess
import struct
import zlib
root = Path(__file__).resolve().parents[1]
main = root / "firmware-status-display/main"
tests = root / "firmware-status-display/tests"
preview = root / "firmware-status-display/preview"
preview.mkdir(exist_ok=True)
u8g = root / "vendor/waveshare/02_Example/ESP-IDF/11_U8G2_Test/components/u8g2/csrc"
cjson = root / ".tools/esp-idf/components/json/cJSON"
sources = sorted(p for p in u8g.glob("*.c")
                 if (p.name.startswith("u8g2_") or p.name.startswith("u8x8_"))
                 and p.name != "u8g2_d_setup.c" and not p.name.startswith("u8x8_d_"))
base = ["clang", "-Wno-deprecated-declarations", "-DU8X8_WITH_USER_PTR", "-DU8G2_USE_LARGE_FONTS", "-O1", "-g", "-fsanitize=address,undefined",
        "-I", str(u8g), "-I", str(main), "-I", str(cjson),
        str(main / "protocol.c"), str(main / "tone.c"), str(cjson / "cJSON.c")]
subprocess.run(base + [str(tests / "protocol_test.c"), "-o", str(preview / "protocol_test")], check=True)
subprocess.run([str(preview / "protocol_test")], check=True)
subprocess.run(base + [str(tests / "tone_test.c"), "-o", str(preview / "tone_test")], check=True)
subprocess.run([str(preview / "tone_test")], check=True)
subprocess.run(base + [str(main / "button.c"), str(tests / "button_test.c"), "-o", str(preview / "button_test")], check=True)
subprocess.run([str(preview / "button_test")], check=True)
subprocess.run(base + [str(main / "ui.c"), str(tests / "render.c")] +
               [str(p) for p in sources] + ["-o", str(preview / "render")], check=True)
sessions = [
    dict(key="cc", agent="claude-code", project="api-server", state="waiting", label="需要授权", detail="检查网络连接", elapsed=42, turn_duration_seconds=None, stale=False,
         title="定位接口超时", user_preview="请检查接口偶发超时的原因，先核对请求日志和网络连接，确认后再给出修复建议。",
         assistant_preview="已发现超时集中在上游连接阶段。下一步需要执行一次网络检查，确认目标服务是否可以访问。", current_tool="Bash"),
    dict(key="cx", agent="codex", project="ESP32", state="running", label="运行中", detail="读取 ui.c", elapsed=134, turn_duration_seconds=None, stale=False,
         title="重新设计状态屏界面", user_preview="改成白底黑字，把仓库和标题放在一起，让下面的提问和回复多显示一点。",
         assistant_preview="已压缩顶部状态栏。对话会根据屏幕宽度换行，会话较少时自动展开，保留工具状态、耗时和声音开关。", current_tool="Read"),
    dict(key="gm", agent="gemini", project="notes", state="done", label="完成", detail="", elapsed=300, turn_duration_seconds=83, stale=False,
         title="整理服务端教程大纲", user_preview="帮我整理服务端教程的提纲，读者没有相关经验，需要从网络结构开始讲清楚。",
         assistant_preview="建议依次介绍网络结构、安装配置、连接验证与常见故障。每一步都配一个可核对的实际结果，方便读者跟着完成。"),
    dict(key="cc2", agent="claude-code", project="tools", state="done", label="完成", detail="等待下一轮", elapsed=3600, turn_duration_seconds=94, stale=False,
         title="检查工具输出",user_preview="帮我整理命令输出，保留错误原因和下一步操作。",assistant_preview="已把重复输出合并，保留关键错误与对应修复步骤。"),
    dict(key="extra", agent="codex", project="blog", state="idle", label="等待输入", detail="", elapsed=0, turn_duration_seconds=None, stale=False,
         title="下一篇教程选题",user_preview="整理几个适合新手的教程选题。",assistant_preview="可以从安装、连接验证和常见故障三个方向挑选，每篇只解决一个具体问题。"),
]
snapshot = dict(type="snapshot", v=2, server_time=1800000000, tz_offset=28800,
                current_sound_seq=10, sessions=sessions,
                alert=dict(alert_id="a-preview", session_key="cc", sound="none", sound_seq=10))
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
def render(name, data, age=0, mode=None):
    path=preview / (name + ".json")
    path.write_text(json.dumps(data, ensure_ascii=False))
    command=[str(preview / "render"), str(path), str(preview / (name + ".pgm")), str(age)]
    if mode: command.append(mode)
    subprocess.run(command, check=True)
    pixels=(preview / (name + ".pgm")).read_bytes().split(b"\n", 3)[3]
    assert len(pixels) == 400 * 300
    assert pixels.count(255) > len(pixels) * .75, "The physical display must have a light background"
    assert pixels.count(0) > 100, "Foreground text is missing"
    assert all(pixels[y * 400 + 399] == 255 for y in range(300)), "Right-edge overflow"
    assert pixels[-400:] == bytes([255]) * 400, "Footer overflow"
    rows=b"".join(b"\0" + pixels[y * 400:(y + 1) * 400] for y in range(300))
    (preview / (name + ".png")).write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 400, 300, 8, 0, 0, 0, 0)) +
        chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return pixels
first_page=dict(snapshot,sessions=sessions[:3],total_sessions=5,alert=None,
                page=dict(index=0,count=2,size=3,auto=True,waiting=False,hold_seconds=0))
pixels=render("cards",first_page)
# All four dialogue lines in the first card must contain actual wrapped text.
for baseline in (64,77,90,103):
    assert sum(pixels[y * 400 + x] == 0 for y in range(baseline-9,baseline+2) for x in range(30,390)) > 20
expanded=dict(snapshot, sessions=[dict(sessions[1], user_preview="请保留仓库名称、Agent 类型、状态和工具信息。旧版标题占了很大空间，希望把更多地方留给正在进行的对话。只有一个会话时，还应该充分利用屏幕。", assistant_preview="新版改为纸张一样的浅色阅读布局。仓库和会话标题合并，状态、工具和耗时集中在第二行。下面的提问与回复自动换行，并按会话数量分配空间。三个会话同屏时显示四行对话，只有一两个会话时显示更长的内容。声音和提醒确认的操作保持原样。")], alert=None)
render("expanded", expanded)
render("two", dict(snapshot,sessions=sessions[:2],alert=None))
render("offline",first_page,mode="offline")
render("muted",first_page,mode="muted")
render("empty",dict(snapshot,sessions=[],alert=None))
legacy=[{k:v for k,v in c.items() if k not in {"title","user_preview","assistant_preview","current_tool"}} for c in sessions[:4]]
render("legacy",dict(snapshot,sessions=legacy,total_sessions=5,alert=None,
                      page=dict(index=0,count=2,size=4,auto=True,waiting=False,hold_seconds=0)))
# Real clock/timing behavior: done duration freezes; active duration advances.
done=dict(snapshot,sessions=[dict(sessions[2],activity_age=False)],alert=None)
assert render("done",done)==render("done-tick",done,age=1)
running=dict(snapshot,sessions=[sessions[1]],alert=None)
assert render("running",running)!=render("running-tick",running,age=1)
# Worst-case bounded multilingual input exercises UTF-8 wrapping under sanitizers.
stress=dict(snapshot,sessions=[dict(sessions[0],project="a"*90,title="中"*100,
    user_preview="中"*240,assistant_preview="word-without-breaks"*40),sessions[1],sessions[2]],alert=None)
render("stress",stress)
next_page=dict(first_page,sessions=sessions[3:],page=dict(first_page['page'],index=1,hold_seconds=60))
render('page-next',next_page)
render('page-paused',dict(first_page,page=dict(first_page['page'],auto=False)))
render('page-alert',dict(first_page,alert=snapshot['alert'],page=dict(first_page['page'],waiting=True)))
render('page-offline',first_page,mode='offline')
render('page-hold-tick',next_page,age=1)
print("PROTOCOL_TONE_UI_BUTTON_OK; 17 renderer scenarios, paging/hold/pause/alert/UTF-8/timing/gesture checks; preview: firmware-status-display/preview/cards.png")
