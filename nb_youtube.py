#!/usr/bin/env python3
"""
YouTube 影片工廠 — 從主題到出片全自動

Usage:
    python nb_youtube.py "AI 如何改變投資"                     # 基本：research → slides + audio
    python nb_youtube.py "被動收入策略" --style cinematic       # 電影風格
    python nb_youtube.py "美股ETF入門" --format debate          # 辯論形式
    python nb_youtube.py "加密貨幣的未來" --full                 # 完整：research → report → slides → audio → video

Output:
    1. Research Report (Markdown) — 研究摘要
    2. Slide Deck (PDF) — 簡報
    3. Audio Overview (MP3) — 雙人對話 Podcast
    4. Video Overview (MP4) — 影片（可選）

Prerequisites:
    pip install "notebooklm-py[browser]"
    notebooklm login
"""

import sys
import argparse
from notebooklm import NotebookLM


def main():
    parser = argparse.ArgumentParser(
        description="YouTube 影片工廠 — 主題 → 出片"
    )
    parser.add_argument("topic", help="影片主題（中文或英文）")
    parser.add_argument("--language", default="zh-TW", help="輸出語言")
    parser.add_argument(
        "--format", default="deep-dive",
        choices=["deep-dive", "brief", "critique", "debate"],
        help="Audio 格式"
    )
    parser.add_argument(
        "--style", default="explainer",
        choices=["explainer", "brief", "cinematic"],
        help="Video 風格"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="完整流程：research → report → slides → audio → video"
    )
    parser.add_argument(
        "--deep-research", action="store_true",
        help="使用 Deep Research（較慢但更深入）"
    )
    parser.add_argument(
        "--sources", nargs="*",
        help="額外來源 URL（可多個）"
    )

    args = parser.parse_args()
    topic = args.topic

    print("🎬 YouTube 影片工廠啟動")
    print(f"   主題：{topic}")
    print(f"   語言：{args.language}")
    print(f"   Audio：{args.format}")
    print(f"   Video：{args.style}")
    if args.full:
        print(f"   模式：完整流程（含 Deep Research）")

    nlm = NotebookLM()

    # --- Step 1: Create notebook ---
    notebook = nlm.notebooks.create(f"YT: {topic[:50]}")
    print(f"\n📓 Notebook: {notebook.name}")

    # --- Step 2: Research (auto-finds and imports web sources) ---
    if args.full or args.deep_research:
        print(f"\n🔍 Deep Research：{topic}")
        research = nlm.research.start(
            notebook.id,
            topic,
            mode="deep" if args.deep_research else "fast",
        )
        print(f"   研究 ID：{research.id}")
        print("   等待研究完成（可能需要數分鐘）...")
        nlm.research.poll(research.id)
        print("   ✅ 研究完成，來源已自動匯入")

    # --- Step 3: Add manual sources ---
    if args.sources:
        print(f"\n🔗 上傳 {len(args.sources)} 個來源...")
        for url in args.sources:
            src = nlm.sources.add_url(notebook.id, url)
            nlm.sources.wait_until_ready(src.id)
            print(f"   ✅ {url[:60]}...")

    # --- Step 4: Add video production guide ---
    guide = f"""請針對以下主題製作 YouTube 影片素材：

主題：{topic}
目標觀眾：對投資理財有興趣的華語使用者
語言風格：專業但不生硬，適合 Podcast 形式
影片長度：中篇（10-15 分鐘）
關鍵要求：
- 開頭 30 秒內抓住注意力
- 使用具體數字和案例
- 結尾給出明確的下一步行動
- 適合搭配視覺化簡報"""
    src = nlm.sources.add_text(notebook.id, guide, title="影片製作指引")
    nlm.sources.wait_until_ready(src.id)

    # Wait for all sources
    all_sources = nlm.sources.list(notebook.id)
    print(f"\n⏳ 等待 {len(all_sources)} 個來源處理...")
    for s in all_sources:
        nlm.sources.wait_until_ready(s.id)
    print("✅ 所有來源就緒")

    # --- Step 5: Generate Report (if full mode) ---
    if args.full:
        print("\n📄 生成研究報告...")
        report = nlm.artifacts.generate_report(notebook.id)
        nlm.artifacts.wait_until_ready(report.id)
        report_path = f"{topic[:30]}_report.md"
        nlm.artifacts.download(report.id, report_path)
        print(f"   ✅ {report_path}")

    # --- Step 6: Generate Slide Deck ---
    print("\n📊 生成簡報...")
    slides = nlm.artifacts.generate_slides(notebook.id)
    nlm.artifacts.wait_until_ready(slides.id)
    slides_path = f"{topic[:30]}_slides.pdf"
    nlm.artifacts.download(slides.id, slides_path)
    print(f"   ✅ {slides_path}")

    # --- Step 7: Generate Audio Overview ---
    print(f"\n🎙️  生成 {args.format} Audio Overview...")
    print("   （這需要 5-10 分鐘）")
    audio = nlm.artifacts.generate_audio(
        notebook.id,
        format=args.format,
        language=args.language,
    )
    nlm.artifacts.wait_until_ready(audio.id)
    audio_path = f"{topic[:30]}_audio_{args.language}.mp3"
    nlm.artifacts.download(audio.id, audio_path)
    print(f"   ✅ {audio_path}")

    # --- Step 8: Generate Video (if full mode) ---
    if args.full:
        print(f"\n🎥 生成 {args.style} 影片...")
        print("   （這需要 10-15 分鐘）")
        video = nlm.artifacts.generate_video(
            notebook.id,
            format=args.style,
        )
        nlm.artifacts.wait_until_ready(video.id)
        video_path = f"{topic[:30]}_video.mp4"
        nlm.artifacts.download(video.id, video_path)
        print(f"   ✅ {video_path}")

    # --- Summary ---
    print(f"\n{'='*50}")
    print(f"🎬 YouTube 素材包已完成！")
    if args.full:
        print(f"   📄 研究報告：{report_path}")
    print(f"   📊 簡報：{slides_path}")
    print(f"   🎙️  音檔：{audio_path}")
    if args.full:
        print(f"   🎥 影片：{video_path}")
    print(f"   🔗 NotebookLM：https://notebooklm.google.com/notebook/{notebook.id}")
    print(f"\n💡 下一步：用音檔 + 簡報在剪輯軟體中合成最終影片")


if __name__ == "__main__":
    main()
