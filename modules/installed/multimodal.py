# -*- coding: utf-8 -*-
"""多模态 v3.0 - 图片 + 音频 + 视频 + 摄像头"""
import os, time
from core.safe import safe
from modules.base import BaseModule


# ── 缺依赖时给用户的安装提示（统一走 core.error_text，别各写各的）──
# 为什么改：实测全项目 17 处 "pip install" 提示里**只有 1 处**带国内镜像，
# 其余都让用户直接跑 `pip install xxx` —— 那会走 PyPI 官方源，
# 国内经常慢到以为卡死。现在统一从这里出。
def _ih(pkg):
    try:
        from core.error_text import install_hint
        return install_hint(pkg)
    except Exception:
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)



class Multimodal(BaseModule):
    NAME = "multimodal"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        # v2.1: 临时产物必须落在 data/plugin_data/<插件名>/ 内
        self.sandbox = os.path.join(self.base, "data", "plugin_data", "multimodal")
        os.makedirs(self.sandbox, exist_ok=True)
        self.history = []
        self.describe_count = 0
        self.audio_count = 0
        self.video_count = 0

    # ===== 图片 =====
    @safe
    def describe_image(self, image_path):
        """描述图片（完整版：图片 base64 传给多模态模型）"""
        if not os.path.exists(image_path):
            return {"错误": "图片不存在"}
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}
        try:
            # 读图片成 base64
            import base64
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            # 如果 LLM 支持多模态（chat_with_image 方法），就真的传图片
            if hasattr(llm, "chat_with_image"):
                r = llm.chat_with_image("描述这张图片", image_base64=img_b64)
            else:
                # 降级：只传路径
                r = llm.chat(f"描述这张图片（路径: {image_path}）")

            self.describe_count += 1
            self.history.append({
                "类型": "图片",
                "路径": image_path,
                "描述": r[:100],
                "时间": time.strftime("%m-%d %H:%M")
            })
            if len(self.history) > 20:
                self.history = self.history[-20:]
            return {"图片": image_path, "描述": r}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def batch_describe(self, image_paths):
        """批量描述图片"""
        results = []
        for p in image_paths[:5]:
            r = self.describe_image(p)
            results.append(r)
        return {"处理数": len(results), "结果": results}

    # ===== 音频 =====
    @safe
    def transcribe_audio(self, audio_path):
        """听音频转文字（语音识别）"""
        if not os.path.exists(audio_path):
            return {"错误": "音频文件不存在"}
        # 检查whisper是否可用
        try:
            import whisper
        except ImportError:
            return {"错误": "需要装 whisper。\n" + _ih("openai-whisper")}
        try:
            model = whisper.load_model("base")
            result = model.transcribe(audio_path)
            text = result["text"]
            self.audio_count += 1
            self.history.append({
                "类型": "音频",
                "路径": audio_path,
                "文字": text[:100],
                "时间": time.strftime("%m-%d %H:%M")
            })
            return {"音频": audio_path, "文字": text}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def audio_summary(self, audio_path):
        """听音频并总结"""
        r = self.transcribe_audio(audio_path)
        if "错误" in r:
            return r
        text = r["文字"]
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"文字": text, "总结": "（LLM未加载，无法总结）"}
        summary = llm.chat(f"总结下面这段音频的内容，用一两句话:\n{text[:1000]}")
        return {"音频": audio_path, "文字": text, "总结": summary}

    # ===== 视频 =====
    @safe
    def describe_video(self, video_path, fps=1):
        """看视频：抽帧 + 图片描述"""
        if not os.path.exists(video_path):
            return {"错误": "视频文件不存在"}
        try:
            import cv2
        except ImportError:
            return {"错误": "需要装 opencv。\n" + _ih("opencv-python")}
        try:
            cap = cv2.VideoCapture(video_path)
            frames = []
            count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if count % (30 // fps) == 0:
                    frame_path = os.path.join(self.sandbox, "temp_frame.jpg")
                    cv2.imwrite(frame_path, frame)
                    frames.append(frame_path)
                count += 1
            cap.release()
            self.video_count += 1
            # 描述前3帧
            descriptions = []
            for f in frames[:3]:
                r = self.describe_image(f)
                descriptions.append(r.get("描述", ""))
            # 总结
            llm = self.trunk.modules.get("llm")
            if llm:
                summary = llm.chat("根据这几帧画面，总结这个视频讲了什么:\n" + "\n".join(descriptions))
            else:
                summary = "（LLM未加载）"
            return {
                "视频": video_path,
                "总帧数": count,
                "抽帧数": len(frames),
                "各帧描述": descriptions,
                "总结": summary
            }
        except Exception as e:
            return {"错误": str(e)[:80]}

    # ===== 摄像头 =====
    @safe
    def capture_camera(self, save_path=None):
        """拍一张摄像头照片"""
        try:
            import cv2
        except ImportError:
            return {"错误": "需要装 opencv。\n" + _ih("opencv-python")}
        try:
            cap = cv2.VideoCapture(0)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                return {"错误": "打不开摄像头"}
            if not save_path:
                save_path = os.path.join(self.sandbox, "camera.jpg")
            cv2.imwrite(save_path, frame)
            # 描述这张照片
            r = self.describe_image(save_path)
            return {
                "照片": save_path,
                "描述": r.get("描述", ""),
                "尺寸": f"{frame.shape[1]}x{frame.shape[0]}"
            }
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def find_object(self, object_name):
        """摄像头找东西：拍一张，问AI有没有"""
        r = self.capture_camera()
        if "错误" in r:
            return r
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}
        ans = llm.chat(f"这张照片里有没有{object_name}？有就说在哪，没有就说没看到。照片: {r['照片']}")
        return {"找": object_name, "结果": ans}

    # ===== 统计 =====
    def stats(self):
        return {
            "图片描述次数": self.describe_count,
            "音频识别次数": self.audio_count,
            "视频理解次数": self.video_count,
            "历史记录数": len(self.history)
        }

    def get_history(self):
        return self.history

    def clear_history(self):
        self.history = []
        return {"成功": True}

    def run(self, *args):
        if args and args[0] == "stats":
            return self.stats()
        if args and args[0] == "history":
            return self.get_history()
        return self.stats()