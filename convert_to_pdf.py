from PIL import Image
import os
import re
from datetime import datetime
import pillow_heif
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from docx import Document
import pypandoc

# Enable HEIC/HEIF support
pillow_heif.register_heif_opener()


def images_to_pdf(img_folder="img", pdf_folder="PDF", base_name=None):
    """Convert all images in img_folder into a single PDF"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(script_dir, img_folder)
    pdf_path = os.path.join(script_dir, pdf_folder)
    os.makedirs(pdf_path, exist_ok=True)

    # If called from command line, ask for input
    if base_name is None:
        base_name = input("Enter a name for your PDF file (e.g. vacation, report): ").strip() or "output"

    image_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".heic", ".heif")

    if not os.path.exists(img_path):
        print(f"❌ Folder '{img_path}' not found.")
        return None  # Return None for Flask to handle

    image_files = [f for f in os.listdir(img_path) if f.lower().endswith(image_extensions)]
    if not image_files:
        print(f"❌ No image files found in '{img_path}'.")
        return None  # Return None for Flask to handle

    image_files.sort()
    images = [Image.open(os.path.join(img_path, img)).convert("RGB") for img in image_files]

    # Find next available number for PDF naming
    pattern = r"\[(\d+)\]_.*\.pdf$"
    existing_files = [f for f in os.listdir(pdf_path) if re.search(pattern, f)]
    numbers = [int(re.search(pattern, f).group(1)) for f in existing_files]
    next_number = max(numbers) + 1 if numbers else 1

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_pdf = f"{base_name}[{next_number}]_{timestamp}.pdf"
    output_path = os.path.join(pdf_path, output_pdf)

    images[0].save(output_path, save_all=True, append_images=images[1:])
    print(f"✅ PDF created successfully: {output_path}")

    # Automatically open PDF only if running standalone
    if base_name is None or __name__ == "__main__":
        import platform
        if platform.system() == "Darwin":
            os.system(f"open '{output_path}'")
        elif platform.system() == "Windows":
            os.startfile(output_path)
        else:
            os.system(f"xdg-open '{output_path}'")
    
    return output_pdf  # Return filename for Flask


def draw_wrapped_text(c, text, x, y, width, font_name="Helvetica", font_size=12, leading=16):
    """Draw text with word wrapping"""
    lines = simpleSplit(text, font_name, font_size, width)
    for line in lines:
        if y < 60:  # bottom margin
            c.showPage()
            c.setFont(font_name, font_size)
            y = A4[1] - 60
        c.drawString(x, y, line)
        y -= leading
    return y


def docs_to_pdf(doc_folder="DOC", pdf_folder="PDF", base_name=None):
    """Convert text and document files to well-structured PDFs"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    doc_path = os.path.join(script_dir, doc_folder)
    pdf_path = os.path.join(script_dir, pdf_folder)
    os.makedirs(pdf_path, exist_ok=True)

    if not os.path.exists(doc_path):
        print(f"❌ Folder '{doc_path}' not found.")
        return []  # Return empty list for Flask

    # ✅ Collect only valid document files and ignore temporary/hidden ones
    doc_files = [
        f for f in os.listdir(doc_path)
        if f.lower().endswith((".docx", ".txt", ".md", ".rtf", ".odt"))
        and not f.startswith("~$")    # skip temporary Word lock files
        and not f.startswith(".")     # skip hidden files like .DS_Store
    ]

    # ✅ Stop if no valid documents found
    if not doc_files:
        print(f"❌ No valid document files found in '{doc_path}'.")
        return []  # Return empty list for Flask

    # Ask for base name for all document conversions (if not provided)
    if base_name is None:
        base_name = input("Enter a base name for your document PDF(s) (e.g. report, notes): ").strip() or "document"

    # Find the next available number
    pattern = r"\[(\d+)\]_.*\.pdf$"
    existing_files = [f for f in os.listdir(pdf_path) if re.search(pattern, f)]
    numbers = [int(re.search(pattern, f).group(1)) for f in existing_files]
    next_number = max(numbers) + 1 if numbers else 1

    created_pdfs = []  # Track created PDFs for Flask

    for file_name in doc_files:
        input_file = os.path.join(doc_path, file_name)
        ext = os.path.splitext(file_name)[1].lower()

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_pdf = f"{base_name}[{next_number}]_{timestamp}.pdf"
        output_path = os.path.join(pdf_path, output_pdf)
        next_number += 1

        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        margin_x = 60
        y = height - 80
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margin_x, y, os.path.splitext(file_name)[0])
        y -= 30
        c.setFont("Helvetica", 12)

        def write_paragraphs(paragraphs):
            nonlocal y
            for para in paragraphs:
                text = para.strip()
                if text:
                    y = draw_wrapped_text(c, text, margin_x, y, width - 2 * margin_x)
                    y -= 10

        try:
            if ext == ".docx":
                doc = Document(input_file)
                paragraphs = [p.text for p in doc.paragraphs]
                write_paragraphs(paragraphs)
            elif ext in [".txt", ".md", ".rtf", ".odt"]:
                text = open(input_file, "r", encoding="utf-8").read()
                if ext in [".md", ".rtf", ".odt"]:
                    text = pypandoc.convert_text(text, "plain", format=ext[1:])
                paragraphs = text.split("\n")
                write_paragraphs(paragraphs)
            else:
                print(f"⚠️ Unsupported file type: {ext}")
                continue

        except Exception as e:
            print(f"⚠️ Could not convert {file_name}: {e}")
            continue

        c.save()
        print(f"✅ Structured PDF created: {output_path}")
        created_pdfs.append(output_pdf)  # Add to list for Flask

        # Auto-open only if running standalone
        if base_name is None or __name__ == "__main__":
            import platform
            if platform.system() == "Darwin":
                os.system(f"open '{output_path}'")
            elif platform.system() == "Windows":
                os.startfile(output_path)
            else:
                os.system(f"xdg-open '{output_path}'")
    
    return created_pdfs  # Return list for Flask


if __name__ == "__main__":
    print("Choose conversion type:")
    print("1️⃣  Images to PDF")
    print("2️⃣  Documents to PDF")
    choice = input("Enter 1 or 2: ").strip()

    if choice == "1":
        images_to_pdf()
    elif choice == "2":
        docs_to_pdf()
    else:
        print("❌ Invalid choice.")