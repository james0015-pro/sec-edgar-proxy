#!/usr/bin/env python3
"""
Treehole — 照顧者心理教育內容自動化

Usage:
    python nb_treehole.py stress-management.pdf              # 單一 PDF
    python nb_treehole.py --folder ./psychology-books/      # 整個資料夾
    python nb_treehole.py --url "https://..." --title "焦慮管理"  # URL

Output:
    1. Study Guide (Markdown) — 給照顧者閱讀的簡化版
    2. Audio Overview (MP3) — 照顧者可以聽的 Podcast
    3. Mind Map — 視覺化知識結構

Prerequisites:
    pip install "notebooklm-py[browser]"
    notebooklm login
"""

import sys
import os
import argparse
from pathlib import Path
from notebooklm import NotebookLM


def main():
    parser = argparse.ArgumentParser(
        description="Treehole — 心理教育內容自動化"
    )
    parser.add_argument("pdf", nargs="?", help="PDF file path")
    parser.add_argument("--folder", help="Folder of PDFs/text files")
    parser.add_argument("--url", help="URL to use as source")
    parser.add_argument("--title", default="照顧者心理指南", help="Notebook title")
    parser.add_argument("--language", default="zh-TW", help="Output language")
    parser.add_argument("--topic", default="照顧者情緒支持與壓力管理", help="Focus topic for study guide")

    args = parser.parse_args()

    if not args.pdf and not args.folder and not args.url:
        parser.print_help()
        return

    print("🌳 Treehole 內容工場啟動")
    print(f"   主題：{args.topic}")
    print(f"   語言：{args.language}")

    nlm = NotebookLM()
    notebook = nlm.notebooks.create(args.title)
    print(f"\n📓 Notebook: {notebook.name}")

    # --- Step 1: Add sources ---
    sources_added = []

    if args.pdf:
        path = Path(args.pdf)
        if not path.exists():
            print(f"❌ 找不到：{args.pdf}")
            return
        print(f"\n📄 上傳：{path.name}")
        src = nlm.sources.add_file(notebook.id, str(path))
        sources_added.append(src.id)

    if args.folder:
        folder = Path(args.folder)
        files = list(folder.glob("*"))
        pdfs = [f for f in files if f.suffix.lower() in ('.pdf', '.txt', '.md', '.epub')]
        print(f"\n📚 資料夾：{len(pdfs)} 個檔案")
        for f in pdfs[:5]:  # Max 5 files
            print(f"   上傳：{f.name}")
            src = nlm.sources.add_file(notebook.id, str(f))
            sources_added.append(src.id)

    if args.url:
        print(f"\n🔗 上傳 URL：{args.url}")
        src = nlm.sources.add_url(notebook.id, args.url)
        sources_added.append(src.id)

    # Add text instruction as a source (guides the AI)
    instruction = f"""請針對以下主題生成照顧者專用內容：
    
主題：{args.topic}
目標讀者：家庭照顧者（非專業人士）
語言風格：溫暖、簡單、不學術
關鍵原則：
- 每段落不超過 3 句話
- 避免專業術語，或用括號解釋
- 加入具體的日常練習建議
- 強調「你已經做得很好」的同理心
"""
    src_guide = nlm.sources.add_text(notebook.id, instruction, title="內容指引")
    sources_added.append(src_guide.id)

    # Wait for all sources
    print("\n⏳ 等待來源處理...")
    for sid in sources_added:
        nlm.sources.wait_until_ready(sid)
    print("✅ 所有來源就緒")

    # --- Step 2: Generate Study Guide ---
    print("\n📖 生成學習指南...")
    study_guide = nlm.artifacts.generate_study_guide(notebook.id)
    nlm.artifacts.wait_until_ready(study_guide.id)
    guide_path = f"{args.title}_study_guide.md"
    nlm.artifacts.download(study_guide.id, guide_path)
    print(f"   ✅ {guide_path}")

    # --- Step 3: Generate Audio Overview ---
    print("\n🎙️  生成 Audio Overview（照顧者專用）...")
    # Use custom voice personas for caregiver context
    audio = nlm.artifacts.generate_audio(
        notebook.id,
        format="deep-dive",
        language=args.language,
    )
    nlm.artifacts.wait_until_ready(audio.id)
    audio_path = f"{args.title}_audio_{args.language}.mp3"
    nlm.artifacts.download(audio.id, audio_path)
    print(f"   ✅ {audio_path}")

    # --- Step 4: Generate Mind Map ---
    print("\n🧠 生成心智圖...")
    mind_map = nlm.artifacts.generate_mind_map(notebook.id)
    nlm.artifacts.wait_until_ready(mind_map.id)
    map_path = f"{args.title}_mindmap.png"
    nlm.artifacts.download(mind_map.id, map_path)
    print(f"   ✅ {map_path}")

    print(f"\n{'='*50}")
    print(f"🌳 Treehole 內容包已完成！")
    print(f"   📖 學習指南：{guide_path}")
    print(f"   🎙️  Podcast：{audio_path}")
    print(f"   🧠 心智圖：{map_path}")
    print(f"   🔗 NotebookLM：https://notebooklm.google.com/notebook/{notebook.id}")


if __name__ == "__main__":
    main()
