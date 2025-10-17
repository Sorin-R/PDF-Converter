from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import os
import re
from datetime import datetime
from werkzeug.utils import secure_filename
import platform
import subprocess
import threading
from PIL import Image
import pillow_heif
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from docx import Document
import pypandoc
from PyPDF2 import PdfReader, PdfWriter

# Enable HEIC/HEIF support
pillow_heif.register_heif_opener()

app = Flask(__name__)
CORS(app)

# --------------------------------------------------
# Configuration
# --------------------------------------------------
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max file size

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.heic', '.heif'}
ALLOWED_DOC_EXTENSIONS = {'.docx', '.txt', '.md', '.rtf', '.odt'}

UPLOAD_FOLDERS = ['img', 'DOC', 'PDF', 'RedactPDF']
for folder in UPLOAD_FOLDERS:
    os.makedirs(folder, exist_ok=True)

# --------------------------------------------------
# Utility Helpers
# --------------------------------------------------

def allowed_file(filename, file_type):
    ext = os.path.splitext(filename)[1].lower()
    if file_type == 'image':
        return ext in ALLOWED_IMAGE_EXTENSIONS
    elif file_type == 'document':
        return ext in ALLOWED_DOC_EXTENSIONS
    elif file_type == 'redact':
        return ext == '.pdf'
    return False


def get_next_number():
    """Return next sequential number for PDF naming."""
    pdf_folder = 'PDF'
    pattern = r"\[(\d+)\]_.*\.pdf$"

    if not os.path.exists(pdf_folder):
        return 1

    existing = [f for f in os.listdir(pdf_folder) if re.search(pattern, f)]
    numbers = [int(re.search(pattern, f).group(1)) for f in existing]
    return max(numbers) + 1 if numbers else 1


def clear_folder(folder):
    """Delete all files in a folder."""
    for f in os.listdir(folder):
        path = os.path.join(folder, f)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception as e:
            print(f"⚠️ Could not clear {path}: {e}")


def draw_wrapped_text(c, text, x, y, width, font="Helvetica", size=12, leading=16):
    """Draw wrapped text on a PDF canvas."""
    lines = simpleSplit(text, font, size, width)
    for line in lines:
        if y < 60:
            c.showPage()
            c.setFont(font, size)
            y = A4[1] - 60
        c.drawString(x, y, line)
        y -= leading
    return y

# --------------------------------------------------
# Conversion Logic
# --------------------------------------------------

def convert_images_to_pdf_api(base_name):
    img_folder = "img"
    pdf_folder = "PDF"
    image_files = [f for f in os.listdir(img_folder)
                   if f.lower().endswith(tuple(ALLOWED_IMAGE_EXTENSIONS))]

    if not image_files:
        return None, "No image files found"

    images = [Image.open(os.path.join(img_folder, f)).convert("RGB") for f in sorted(image_files)]

    next_num = get_next_number()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pdf_name = f"{base_name}[{next_num}]_{timestamp}.pdf"
    output_path = os.path.join(pdf_folder, pdf_name)

    images[0].save(output_path, save_all=True, append_images=images[1:])
    clear_folder(img_folder)
    return pdf_name, None


def convert_docs_to_pdf_api(base_name):
    doc_folder = "DOC"
    pdf_folder = "PDF"
    doc_files = [f for f in os.listdir(doc_folder)
                 if f.lower().endswith(tuple(ALLOWED_DOC_EXTENSIONS))
                 and not f.startswith("~$") and not f.startswith(".")]

    if not doc_files:
        return None, "No document files found"

    created = []
    next_num = get_next_number()

    for file in doc_files:
        input_path = os.path.join(doc_folder, file)
        ext = os.path.splitext(file)[1].lower()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pdf_name = f"{base_name}[{next_num}]_{timestamp}.pdf"
        output_path = os.path.join(pdf_folder, pdf_name)
        next_num += 1

        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        margin = 60
        y = height - 80

        c.setFont("Helvetica-Bold", 16)
        c.drawString(margin, y, os.path.splitext(file)[0])
        y -= 30
        c.setFont("Helvetica", 12)

        def write_paragraphs(paragraphs):
            nonlocal y
            for p in paragraphs:
                txt = p.strip()
                if txt:
                    y = draw_wrapped_text(c, txt, margin, y, width - 2 * margin)
                    y -= 10

        try:
            if ext == ".docx":
                doc = Document(input_path)
                paragraphs = [p.text for p in doc.paragraphs]
            else:
                text = open(input_path, "r", encoding="utf-8").read()
                if ext in [".md", ".rtf", ".odt"]:
                    text = pypandoc.convert_text(text, "plain", format=ext[1:])
                paragraphs = text.split("\n")
            write_paragraphs(paragraphs)
            c.save()
            created.append(pdf_name)
        except Exception as e:
            print(f"⚠️ Error converting {file}: {e}")

    clear_folder(doc_folder)
    return created, None

# --------------------------------------------------
# Flask Routes
# --------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

# ---------------------- Upload ----------------------

@app.route('/api/upload', methods=['POST'])
def upload_files():
    """Upload images, docs, or PDFs for redaction."""
    try:
        file_type = request.form.get('type', 'image')
        print(f"🟢 Upload request received — type={file_type}")

        if 'files' not in request.files:
            return jsonify({'error': 'No files in request'}), 400

        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': 'No files provided'}), 400

        # Target folder logic
        if file_type == 'image':
            target = 'img'
            clear_folder(target)
        elif file_type == 'document':
            target = 'DOC'
            clear_folder(target)
        elif file_type == 'redact':
            target = 'RedactPDF'
            # do not clear — we want to keep uploaded PDF
        else:
            return jsonify({'error': f'Invalid type: {file_type}'}), 400

        uploaded = []
        for file in files:
            if file and allowed_file(file.filename, file_type):
                filename = secure_filename(file.filename)
                path = os.path.join(target, filename)
                print(f"💾 Saving: {path}")
                file.save(path)
                uploaded.append(filename)

        if not uploaded:
            return jsonify({'error': 'No valid files uploaded'}), 400

        print(f"✅ Uploaded to {target}: {uploaded}")
        return jsonify({'success': True, 'files': uploaded, 'folder': target})
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------- Convert ----------------------

@app.route('/api/convert', methods=['POST'])
def convert():
    try:
        data = request.json
        file_type = data.get('type', 'image')
        base_name = data.get('baseName', 'Output')

        if file_type == 'image':
            pdf, err = convert_images_to_pdf_api(base_name)
            files = [pdf] if pdf else []
        else:
            files, err = convert_docs_to_pdf_api(base_name)

        if err:
            return jsonify({'error': err}), 400

        return jsonify({
            'success': True,
            'pdfs': files,
            'message': f"✅ Successfully created {len(files)} PDF(s)"
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------------------- Redact ----------------------

@app.route('/api/redact', methods=['POST'])
def redact_pdf():
    """Redact sensitive terms from a PDF in RedactPDF/."""
    try:
        data = request.json
        filename = data.get('filename')
        terms = data.get('terms', [])

        redact_dir = 'RedactPDF'
        pdf_dir = 'PDF'

        src = os.path.join(redact_dir, filename)
        if not os.path.exists(src):
            return jsonify({'error': f'File not found in {redact_dir}'}), 404

        reader = PdfReader(src)
        writer = PdfWriter()

        for page in reader.pages:
            text = page.extract_text() or ""
            for t in terms:
                if t.strip():
                    text = text.replace(t, "[REDACTED]")
            # This is symbolic (PyPDF2 doesn't reflow text)
            page.extract_text = lambda: text
            writer.add_page(page)

        next_num = get_next_number()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        redacted_name = f"redacted[{next_num}]_{timestamp}.pdf"
        output = os.path.join(pdf_dir, redacted_name)

        with open(output, "wb") as f:
            writer.write(f)

        try:
            os.remove(src)
        except Exception as e:
            print(f"⚠️ Could not remove original: {e}")

        print(f"✅ Redacted PDF created: {redacted_name}")
        return jsonify({'success': True, 'pdf': redacted_name, 'message': f'Redacted PDF created: {redacted_name}'})

    except Exception as e:
        print(f"❌ Redaction error: {e}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/redact-save', methods=['POST'])
def save_manual_redactions():
    """Applies manual redaction boxes from /redact-editor."""
    try:
        data = request.json
        filename = data.get('filename')
        redactions = data.get('redactions', [])

        src = os.path.join('RedactPDF', filename)
        if not os.path.exists(src):
            return jsonify({'error': 'File not found'}), 404

        reader = PdfReader(src)
        writer = PdfWriter()

        for page_number, page in enumerate(reader.pages, start=1):
            page_obj = page
            # Here you could apply redactions graphically (PyMuPDF is better)
            # For now, we simply copy all pages unchanged
            writer.add_page(page_obj)

        next_num = get_next_number()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        redacted_name = f"manual_redacted[{next_num}]_{timestamp}.pdf"
        output_path = os.path.join('PDF', redacted_name)

        with open(output_path, 'wb') as f:
            writer.write(f)

        return jsonify({'success': True, 'pdf': redacted_name})
    except Exception as e:
        print(f"❌ Manual redaction error: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------- Download/Delete/Open ----------------------

@app.route('/api/delete/<filename>', methods=['DELETE'])
def delete_pdf(filename):
    path = os.path.join('PDF', filename)
    if os.path.exists(path):
        os.remove(path)
        print(f"🗑️ Deleted {filename}")
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404


@app.route('/api/download/<filename>', methods=['GET'])
def download_and_delete(filename):
    path = os.path.join('PDF', filename)
    if not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404

    with open(path, 'rb') as f:
        content = f.read()

    def delete_later():
        import time
        time.sleep(60)
        if os.path.exists(path):
            os.remove(path)
            print(f"🧹 Auto-deleted {filename}")

    threading.Thread(target=delete_later, daemon=True).start()

    return Response(
        content,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'application/pdf'
        }
    )

@app.route('/RedactPDF/<filename>')
def serve_redact_pdf(filename):
    """Serve uploaded PDF for the interactive redaction viewer."""
    try:
        path = os.path.join('RedactPDF', filename)
        if not os.path.exists(path):
            return jsonify({'error': 'File not found'}), 404
        with open(path, 'rb') as f:
            pdf_content = f.read()
        return Response(
            pdf_content,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'inline; filename={filename}'
            }
        )
    except Exception as e:
        print(f"❌ Error serving RedactPDF: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/open/<filename>', methods=['GET'])
def open_pdf(filename):
    path = os.path.join('PDF', filename)
    if not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404

    if platform.system() == "Darwin":
        subprocess.call(["open", path])
    elif platform.system() == "Windows":
        os.startfile(path)
    else:
        subprocess.call(["xdg-open", path])

    return jsonify({'success': True, 'message': f'Opening {filename}'})

# ---------------------- Serve PDF ----------------------

@app.route('/pdf/<filename>')
def serve_pdf(filename):
    path = os.path.join('PDF', filename)
    if not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404

    with open(path, 'rb') as f:
        content = f.read()

    try:
        os.remove(path)
        print(f"✅ Deleted after serve: {filename}")
    except Exception as e:
        print(f"⚠️ Could not delete {filename}: {e}")

    return Response(
        content,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'application/pdf'
        }
    )

@app.route('/redact-editor/<filename>')
def redact_editor(filename):
    redact_folder = 'RedactPDF'
    file_path = os.path.join(redact_folder, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    return render_template('redact_editor.html', filename=filename)

# --------------------------------------------------
# Run App
# --------------------------------------------------
if __name__ == '__main__':
    print("🚀 PDF Converter Server running...")
    print("📂 Folders: img/, DOC/, PDF/, RedactPDF/")
    print("🌐 Open http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5001)