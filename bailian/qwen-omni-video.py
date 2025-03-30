import base64
import os
import re
import subprocess
import wave
import threading
import tkinter as tk
from tkinter import messagebox

import pyaudio
from openai import OpenAI

# ==== 配置 ====
TEMP_VIDEO = "tmp/temp_video.mp4"
AUDIO_FILENAME = "tmp/output.wav"
ffmpeg_process = None

if not os.path.exists("tmp"):
    os.makedirs("tmp")


def detect_ffmpeg_devices():
    print("[INFO] 正在自动检测系统音视频设备...")
    try:
        result = subprocess.run(
            ['ffmpeg', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            encoding='utf-8',
            errors='ignore'
        )

        output = result.stderr or ""
        video_matches = re.findall(r'\[dshow @ .*?\] "(.*?)" \(video\)', output)
        audio_matches = re.findall(r'\[dshow @ .*?\] "(.*?)" \(audio\)', output)

        video_device = next((v for v in video_matches if "Virtual" not in v),
                            video_matches[0]) if video_matches else None
        audio_device = audio_matches[0] if audio_matches else None

        if not video_device:
            raise RuntimeError("未检测到视频设备")
        if not audio_device:
            raise RuntimeError("未检测到音频设备")

        print(f"[INFO] 使用视频设备: {video_device}")
        print(f"[INFO] 使用音频设备: {audio_device}")
        return video_device, audio_device

    except Exception as e:
        print(f"[ERROR] 自动检测设备失败: {e}")
        exit(1)


def start_recording():
    global ffmpeg_process

    try:
        if os.name == "nt":
            video_device, audio_device = detect_ffmpeg_devices()
            input_arg = f"video={video_device}:audio={audio_device}"
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "dshow",
                "-i", input_arg,
                "-vcodec", "libx264",
                "-af", "volume=4.0",
                "-acodec", "aac",
                TEMP_VIDEO
            ]
        elif os.name == "posix":
            input_arg = "0:0"
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "avfoundation",
                "-i", input_arg,
                "-vcodec", "libx264",
                "-af", "volume=4.0",
                "-acodec", "aac",
                TEMP_VIDEO
            ]
        else:
            raise NotImplementedError("Unsupported OS")

        ffmpeg_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("[INFO] 正在录制中...")

    except Exception as e:
        print(f"[ERROR] 启动录制失败: {e}")
        messagebox.showerror("录制错误", str(e))


def stop_recording():
    global ffmpeg_process

    if ffmpeg_process:
        try:
            ffmpeg_process.communicate(input=b"q\n")
            print("[INFO] 录制已停止")
        except Exception as e:
            print(f"[WARNING] 无法优雅终止，尝试强制终止: {e}")
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
        ffmpeg_process = None


def encode_video_to_base64(filepath):
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def init_openai_client():
    return OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def ask_video_question(client, base64_video):
    return client.chat.completions.create(
        # model="qwen-omni-turbo",
        model="qwen2.5-omni-7b",
        messages=[
            {
                "role": "system",
                "content": [
                    {"type": "text",
                     "text": "You are a precise and concise assistant. Only respond to explicit audio instructions in the video. Do not provide any suggestions, summaries, or ask follow-up questions."}
                ]
            },
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": f"data:;base64,{base64_video}"}},
                    {"type": "text", "text": "理解视频的内容，并回答语音里的问题。 "},
                ]
            }
        ],
        modalities=["text", "audio"],
        audio={"voice": "Chelsie", "format": "wav"},
        stream=True,
        stream_options={"include_usage": True}
    )


def process_response(completion, output_file):
    audio_data = b""
    for chunk in completion:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if hasattr(delta, "content") and delta.content:
                print("[Text]", delta.content, end="", flush=True)
            if hasattr(delta, "audio") and delta.audio and "transcript" in delta.audio:
                print(delta.audio["transcript"], end="")
            if hasattr(delta, "audio") and delta.audio and "data" in delta.audio:
                b64_data = delta.audio["data"]
                audio_data += base64.b64decode(b64_data)
        elif chunk.usage:
            print("\n[Usage]", chunk.usage)

    with wave.open(output_file, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio_data)


def play_audio(file_path):
    wf = wave.open(file_path, 'rb')
    p = pyaudio.PyAudio()
    stream = p.open(
        format=p.get_format_from_width(wf.getsampwidth()),
        channels=wf.getnchannels(),
        rate=wf.getframerate(),
        output=True
    )
    data = wf.readframes(1024)
    while data:
        stream.write(data)
        data = wf.readframes(1024)
    stream.stop_stream()
    stream.close()
    p.terminate()


def post_recording_process(callback=None):
    try:
        base64_video = encode_video_to_base64(TEMP_VIDEO)
        client = init_openai_client()
        completion = ask_video_question(client, base64_video)
        process_response(completion, AUDIO_FILENAME)
        print(f"\n[INFO] 语音回答已保存至 {AUDIO_FILENAME}")
        play_audio(AUDIO_FILENAME)
    except Exception as e:
        print(f"[ERROR] 处理视频失败: {e}")
        messagebox.showerror("处理错误", str(e))
    finally:
        if callback:
            callback()


# ==== GUI 部分 ====
def launch_gui():
    recording_seconds = 0
    timer_running = False

    root = tk.Tk()
    root.title("音视频录制工具")
    window_width, window_height = 320, 240

    # 设置窗口大小并居中显示
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = int((screen_width - window_width) / 2)
    y = int((screen_height - window_height) / 2)
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    # 主容器，垂直水平居中
    main_frame = tk.Frame(root)
    main_frame.pack(expand=True)

    # 控件
    start_button = tk.Button(main_frame, text="开始录制", font=("Arial", 14), width=15)
    stop_button = tk.Button(main_frame, text="停止录制", font=("Arial", 14), width=15)
    status_label = tk.Label(main_frame, text="", font=("Arial", 12))
    timer_label = tk.Label(main_frame, text="录制时长: 0 秒", font=("Arial", 12))

    def update_timer():
        nonlocal recording_seconds, timer_running
        if timer_running:
            recording_seconds += 1
            timer_label.config(text=f"录制时长: {recording_seconds} 秒")
            root.after(1000, update_timer)

    def reset_timer():
        nonlocal recording_seconds, timer_running
        recording_seconds = 0
        timer_running = False
        timer_label.config(text="录制时长: 0 秒")

    def start_timer():
        nonlocal timer_running
        timer_running = True
        update_timer()

    def stop_timer():
        nonlocal timer_running
        timer_running = False

    def on_start():
        start_button.pack_forget()
        stop_button.config(state=tk.NORMAL)
        stop_button.pack(pady=10)
        timer_label.pack(pady=5)
        status_label.config(text="")
        start_recording()
        start_timer()

    def on_stop():
        stop_button.config(state=tk.DISABLED)
        status_label.config(text="处理中，请稍候...")
        stop_timer()
        threading.Thread(target=stop_and_process).start()

    def stop_and_process():
        stop_recording()
        post_recording_process(callback=restore_ui)

    def restore_ui():
        root.after(100, lambda: (
            stop_button.pack_forget(),
            start_button.pack(pady=10),
            timer_label.pack_forget(),
            reset_timer(),
            status_label.config(text="")
        ))

    start_button.config(command=on_start)
    stop_button.config(command=on_stop)

    # 初始界面布局
    start_button.pack(pady=10)
    status_label.pack(pady=5)

    root.mainloop()


if __name__ == "__main__":
    launch_gui()
