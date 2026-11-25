import base64
import os
import re
import tempfile
import time
import numpy as np
from google import genai
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
    vfx,
)
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

st.set_page_config(
    page_title="3D Pixar-Style All-in-One Shorts Studio",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 3D Pixar-Style All-in-One Shorts Studio (.MP4)")
st.caption(
    "Generates 4-scene 3D Pixar-style animated clips with human speech, smooth crossfades, "
    "background music mixing, and burned-in 9:16 captions."
)

# ---------------------------------------------------------------------------
# Preloaded 4-Scene Supermarket Role-Reversal Comedy Script
# ---------------------------------------------------------------------------
DEFAULT_CHARACTERS = (
    "A tired 35-year-old father with tousled dark hair, light stubble, warm brown eyes, and a casual "
    "grey-blue henley shirt; and his expressive 4-year-old daughter with chestnut brown hair in pigtails, "
    "a small red hair clip, big expressive eyes, and a cozy pastel pink knit sweater."
)

DEFAULT_SCENES = [
    {
        "title": "Scene 1 — The Cereal Callout",
        "action": (
            "In a brightly lit, colorful supermarket cereal aisle, the father pushes a metal grocery cart "
            "while his 4-year-old daughter sits in the child seat. She leans forward with wide, serious eyes, "
            "raises one tiny finger like a strict parent, and says clearly in an expressive child voice: "
            "'Dad, I told you we do not need three boxes of sugar cereal—put them back and act right!'"
        ),
        "caption": "Dad, put the sugar cereal back and act right!",
    },
    {
        "title": "Scene 2 — The Pleading Dad",
        "action": (
            "Medium close-up in the same supermarket cereal aisle: the father blinks in shock, drops his "
            "shoulders with a flustered, exhausted expression, and replies in a pleading, natural human voice: "
            "'Sweetheart, please, just one box! We have been walking in this store for forty minutes.'"
        ),
        "caption": "Sweetheart, please, just one box!",
    },
    {
        "title": "Scene 3 — Role Reversal Twist",
        "action": (
            "The 4-year-old daughter crosses her little arms like a strict parent, lets out a dramatic "
            "grown-up sigh, shakes her head, and says firmly: "
            "'Unbelievable. I am taking over the cart from here.'"
        ),
        "caption": "Unbelievable. I'm taking over the cart.",
    },
    {
        "title": "Scene 4 — Final Punchline",
        "action": (
            "Wide-to-medium shot in the supermarket aisle: the father steps aside looking defeated while the "
            "little girl grips the cart handle with a confident smirk and says: "
            "'Step aside, buddy, real management has arrived.'"
        ),
        "caption": "Step aside, buddy—real management is here.",
    },
]

# ---------------------------------------------------------------------------
# Sidebar Controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🔑 API & Video Settings")
    api_key = st.text_input(
        "Gemini API Key",
        type="password",
        value=os.environ.get("GEMINI_API_KEY", ""),
        help="Enter your Google AI Studio API key.",
    )
    aspect_ratio = st.selectbox("Aspect Ratio", ["9:16", "16:9"], index=0)
    duration = st.selectbox("Clip Duration per Scene", ["15s", "10s", "5s"], index=0)
    resolution = st.selectbox("Resolution", ["1080p", "720p"], index=0)
    num_scenes = st.slider("Number of Scenes", min_value=2, max_value=4, value=4)

    st.divider()
    st.header("✨ Post-Production (MoviePy)")
    enable_crossfade = st.checkbox("Smooth Crossfade Transitions", value=True)
    crossfade_sec = st.slider(
        "Crossfade Duration (sec)",
        min_value=0.2,
        max_value=1.0,
        value=0.4,
        step=0.1,
        disabled=not enable_crossfade,
    )

    enable_captions = st.checkbox("Burn Bold 9:16 Subtitles", value=True)
    caption_position = st.selectbox(
        "Caption Placement",
        ["Lower-Center (Shorts Safe Zone)", "Center", "Top"],
        index=0,
        disabled=not enable_captions,
    )

    st.divider()
    st.header("🎵 Background Music (Optional)")
    bg_music_file = st.file_uploader(
        "Upload Background Music (.MP3 / .WAV)",
        type=["mp3", "wav", "m4a"],
        help="Automatically looped/trimmed and lowered so character voices stay crisp.",
    )
    music_volume = st.slider(
        "Music Volume (Under Dialogue)",
        min_value=0.05,
        max_value=0.40,
        value=0.14,
        step=0.01,
    )

    st.divider()
    st.markdown("**Run locally:**")
    st.code("pip install --upgrade google-genai streamlit moviepy pillow numpy\nstreamlit run pixar_video_studio.py")


# ---------------------------------------------------------------------------
# Helper: Extract Spoken Quote Automatically if Caption Field is Empty
# ---------------------------------------------------------------------------
def extract_spoken_quote(text: str) -> str:
    matches = re.findall(r"'([^']+)'", text)
    if matches:
        return " ".join(matches)
    return text[:90]


# ---------------------------------------------------------------------------
# Helper: Render Crisp, Bold Shorts-Style Subtitle PNG Overlay via Pillow
# ---------------------------------------------------------------------------
def make_caption_overlay(
    text: str,
    video_w: int,
    video_h: int,
    clip_duration: float,
    placement: str = "Lower-Center (Shorts Safe Zone)",
) -> ImageClip:
    img = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = max(36, int(video_w * 0.052))
    font = None
    for candidate in [
        "arialbd.ttf",
        "Arial Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]:
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    # Word-wrap caption text to fit 82% of frame width
    max_text_width = int(video_w * 0.82)
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_text_width or not current_line:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = int(font_size * 0.28)
    total_text_h = sum(line_heights) + line_spacing * max(0, len(lines) - 1)
    max_line_w = max(line_widths) if line_widths else 100

    pad_x = int(font_size * 0.65)
    pad_y = int(font_size * 0.45)
    box_w = max_line_w + pad_x * 2
    box_h = total_text_h + pad_y * 2

    if placement == "Top":
        box_y = int(video_h * 0.12)
    elif placement == "Center":
        box_y = int((video_h - box_h) * 0.5)
    else:  # Lower-Center (above YouTube Shorts / TikTok bottom UI)
        box_y = int(video_h * 0.72)

    box_x = int((video_w - box_w) * 0.5)

    # Semi-transparent dark pill background for readability
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_w, box_y + box_h],
        radius=int(font_size * 0.45),
        fill=(15, 18, 28, 205),
        outline=(255, 214, 70, 235),
        width=3,
    )

    # Draw each centered line with thick black stroke + crisp white/gold text
    cursor_y = box_y + pad_y
    for idx, line in enumerate(lines):
        lx = int((video_w - line_widths[idx]) * 0.5)
        draw.text(
            (lx, cursor_y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 255),
        )
        cursor_y += line_heights[idx] + line_spacing

    overlay_np = np.array(img)
    return ImageClip(overlay_np).with_duration(clip_duration)


# ---------------------------------------------------------------------------
# Helper: Generate a Single 3D Pixar-Style Scene MP4 via Gemini Omni 1.2 Flash
# ---------------------------------------------------------------------------
def generate_scene_mp4(client: genai.Client, char_lock: str, scene_desc: str, idx: int) -> bytes:
    prompt = (
        f"High-budget 3D Pixar and Disney CGI animated film style, theatrical rendering, subsurface skin scattering, "
        f"expressive facial muscle animation, natural human blinking, realistic hand gestures, and accurate lip-syncing. "
        f"Characters: {char_lock}. "
        f"Scene {idx + 1} Action & Dialogue: {scene_desc} "
        f"Smooth cinematic camera movement, warm studio lighting, natural supermarket ambience and clear human-like character voices."
    )
    interaction = client.interactions.create(
        model="gemini-omni-1.2-flash",
        input=prompt,
        response_format={
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
        },
    )
    return base64.b64decode(interaction.output_video.data)


# ---------------------------------------------------------------------------
# Helper: Stitch Clips with Crossfades, Burned Captions & Background Music
# ---------------------------------------------------------------------------
def build_final_short(
    clip_bytes_list: list[bytes],
    captions_list: list[str],
    output_path: str,
    use_crossfade: bool,
    fade_duration: float,
    burn_captions: bool,
    caption_place: str,
    music_bytes: bytes | None,
    music_vol: float,
) -> str:
    temp_files = []
    raw_clips = []
    processed_clips = []
    music_clip = None

    try:
        for idx, data in enumerate(clip_bytes_list):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_scene_{idx + 1}.mp4")
            tmp.write(data)
            tmp.flush()
            tmp.close()
            temp_files.append(tmp.name)

            base_clip = VideoFileClip(tmp.name)
            raw_clips.append(base_clip)

            # Burn per-scene subtitle onto each clip before stitching
            if burn_captions and captions_list[idx].strip():
                sub_overlay = make_caption_overlay(
                    text=captions_list[idx].strip(),
                    video_w=base_clip.w,
                    video_h=base_clip.h,
                    clip_duration=base_clip.duration,
                    placement=caption_place,
                )
                scene_clip = CompositeVideoClip([base_clip, sub_overlay]).with_audio(base_clip.audio)
            else:
                scene_clip = base_clip

            # Apply crossfade transition on scenes after Scene 1
            if use_crossfade and idx > 0 and scene_clip.duration > fade_duration * 2:
                scene_clip = scene_clip.with_effects([vfx.CrossFadeIn(fade_duration)])

            processed_clips.append(scene_clip)

        # Concatenate with overlap when crossfade is active
        if use_crossfade and len(processed_clips) > 1:
            final_video = concatenate_videoclips(
                processed_clips,
                method="compose",
                padding=-fade_duration,
            )
        else:
            final_video = concatenate_videoclips(processed_clips, method="compose")

        # Mix background music track under character dialogue if uploaded
        if music_bytes:
            music_tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_bgm.mp3")
            music_tmp.write(music_bytes)
            music_tmp.flush()
            music_tmp.close()
            temp_files.append(music_tmp.name)

            music_clip = AudioFileClip(music_tmp.name)
            if music_clip.duration < final_video.duration:
                music_clip = music_clip.with_effects([afx.AudioLoop(duration=final_video.duration)])
            else:
                music_clip = music_clip.subclipped(0, final_video.duration)

            music_clip = music_clip.with_effects(
                [
                    afx.MultiplyVolume(music_vol),
                    afx.AudioFadeIn(0.6),
                    afx.AudioFadeOut(1.0),
                ]
            )

            if final_video.audio is not None:
                mixed_audio = CompositeAudioClip([final_video.audio, music_clip])
                final_video = final_video.with_audio(mixed_audio)
            else:
                final_video = final_video.with_audio(music_clip)

        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=24,
            logger=None,
        )
        final_video.close()

    finally:
        if music_clip is not None:
            try:
                music_clip.close()
            except Exception:
                pass
        for c in processed_clips:
            try:
                c.close()
            except Exception:
                pass
        for c in raw_clips:
            try:
                c.close()
            except Exception:
                pass
        for path in temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    return output_path


# ---------------------------------------------------------------------------
# Main Studio Workspace
# ---------------------------------------------------------------------------
col_left, col_right = st.columns([1.25, 1])

with col_left:
    st.subheader("1. Character Consistency Lock")
    characters = st.text_area(
        "Shared Character & Style Lock (applied to every scene):",
        value=DEFAULT_CHARACTERS,
        height=85,
    )

    st.subheader("2. 4-Scene Comedy Script, Dialogue & Burned Captions")
    scene_prompts = []
    scene_captions = []

    for i in range(num_scenes):
        default_title = DEFAULT_SCENES[i]["title"] if i < len(DEFAULT_SCENES) else f"Scene {i + 1}"
        default_action = DEFAULT_SCENES[i]["action"] if i < len(DEFAULT_SCENES) else ""
        default_cap = DEFAULT_SCENES[i]["caption"] if i < len(DEFAULT_SCENES) else ""

        with st.expander(default_title, expanded=(i < 4)):
            action_text = st.text_area(
                f"Scene {i + 1} Action & Spoken Dialogue (keep spoken lines in 'single quotes')",
                value=default_action,
                height=105,
                key=f"scene_action_{i}",
            )
            caption_text = st.text_input(
                f"Scene {i + 1} On-Screen Subtitle Caption",
                value=default_cap,
                key=f"scene_caption_{i}",
            )
            scene_prompts.append(action_text.strip())
            scene_captions.append(
                caption_text.strip() if caption_text.strip() else extract_spoken_quote(action_text)
            )

    generate_all_btn = st.button(
        f"🎥 Render {num_scenes} Scenes + Crossfades + Captions (.MP4)",
        type="primary",
        use_container_width=True,
    )

with col_right:
    st.subheader("3. Finished YouTube Short & Individual Scenes")
    result_box = st.container()

    if not generate_all_btn:
        with result_box:
            st.info(
                "Everything is preloaded with the **4-Scene Supermarket Role-Reversal Comedy Script**. "
                "Enter your Gemini API Key in the sidebar, optionally upload a background music track, "
                "and click **Render 4 Scenes + Crossfades + Captions (.MP4)**."
            )

if generate_all_btn:
    if not api_key:
        st.error("Please enter your Gemini API Key in the left sidebar first.")
        st.stop()

    if any(not s for s in scene_prompts):
        st.error("Please fill in the action and dialogue for every active scene.")
        st.stop()

    client = genai.Client(api_key=api_key)
    generated_clips = []
    music_data = bg_music_file.read() if bg_music_file is not None else None
    progress_bar = st.progress(0, text="Starting 3D Pixar-style video pipeline...")

    try:
        for idx, scene_desc in enumerate(scene_prompts):
            progress_bar.progress(
                idx / (num_scenes + 1),
                text=f"Rendering Scene {idx + 1} of {num_scenes} with synchronized human voice...",
            )
            clip_bytes = generate_scene_mp4(client, characters, scene_desc, idx)
            generated_clips.append(clip_bytes)

        progress_bar.progress(
            num_scenes / (num_scenes + 1),
            text="Stitching scenes, adding crossfades, burning captions & mixing audio...",
        )
        final_filename = f"pixar_complete_short_{int(time.time())}.mp4"
        build_final_short(
            clip_bytes_list=generated_clips,
            captions_list=scene_captions,
            output_path=final_filename,
            use_crossfade=enable_crossfade,
            fade_duration=crossfade_sec,
            burn_captions=enable_captions,
            caption_place=caption_position,
            music_bytes=music_data,
            music_vol=music_volume,
        )
        progress_bar.progress(1.0, text="Complete! Your finished 3D Pixar-style Short is ready.")

        with open(final_filename, "rb") as f:
            final_bytes = f.read()

        with result_box:
            st.success(f"Finished Short saved as `{final_filename}`!")
            st.video(final_bytes)
            st.download_button(
                label="⬇️ Download Complete Short with Captions & Transitions (.MP4)",
                data=final_bytes,
                file_name=final_filename,
                mime="video/mp4",
                use_container_width=True,
            )

            st.divider()
            st.markdown("**Raw Individual Scene Clips (Before Stitching):**")
            for idx, c_bytes in enumerate(generated_clips):
                with st.expander(f"Scene {idx + 1} Raw Clip"):
                    st.video(c_bytes)
                    st.download_button(
                        label=f"⬇️ Download Scene {idx + 1} (.MP4)",
                        data=c_bytes,
                        file_name=f"raw_scene_{idx + 1}_{int(time.time())}.mp4",
                        mime="video/mp4",
                        key=f"dl_raw_{idx}",
                    )

    except Exception as e:
        st.error(f"Pipeline error: {e}")
        st.info(
            "Verify that `google-genai`, `streamlit`, `moviepy`, `pillow`, and `numpy` are installed "
            "and your Google AI Studio API key has video generation enabled."
  )
