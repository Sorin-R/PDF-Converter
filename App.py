from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import json
from datetime import datetime
import re
from werkzeug.utils import secure_filename
import shutil
import platform
import subprocess

# Import your existing converter functions
from convert_to_pdf import images_to_pdf, docs_to_pdf
from PIL import Image
import pillow_heif
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from docx import Document
import pypandoc

# Enable HEIC/HEIF support
pillow_heif.register_heif_opener()

app = Flask(__name__)
@app.route('/test')
def test():
    return '<h1>Server is working!</h1>'
CORS(app)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.heic', '.heif'}
ALLOWED_DOC_EXTENSIONS = {'.docx', '.txt', '.md', '.rtf', '.odt'}

# Ensure folders exist
UPLOAD_FOLDERS = ['img', 'DOC', 'PDF']
for folder in UPLOAD_FOLDERS:
    os.makedirs(folder, exist_ok=True)

def allowed_file(filename, file_type):
    ext = os.path.splitext(filename)[1].lower()
    if file_type == 'image':
        return ext in ALLOWED_IMAGE_EXTENSIONS
    elif file_type == 'document':
        return ext in ALLOWED_DOC_EXTENSIONS
    return False

def get_next_number():
    """Get the next available number for PDF naming"""
    pdf_folder = 'PDF'
    pattern = r"\[(\d+)\]_.*\.pdf$"
    
    if not os.path.exists(pdf_folder):
        return 1
    
    existing_files = [f for f in os.listdir(pdf_folder) if re.search(pattern, f)]
    numbers = [int(re.search(pattern, f).group(1)) for f in existing_files]
    return max(numbers) + 1 if numbers else 1

def clear_folder(folder_path):
    """Clear all files in a folder"""
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")

def convert_images_to_pdf_api(base_name):
    """Modified version of images_to_pdf that returns the file path"""
    img_folder = "img"
    pdf_folder = "PDF"
    
    image_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".heic", ".heif")
    image_files = [f for f in os.listdir(img_folder) if f.lower().endswith(image_extensions)]
    
    if not image_files:
        return None, "No image files found"
    
    image_files.sort()
    images = [Image.open(os.path.join(img_folder, img)).convert("RGB") for img in image_files]
    
    # Find next available number
    next_number = get_next_number()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_pdf = f"{base_name}[{next_number}]_{timestamp}.pdf"
    output_path = os.path.join(pdf_folder, output_pdf)
    
    images[0].save(output_path, save_all=True, append_images=images[1:])
    
    # Clear the img folder after conversion
    clear_folder(img_folder)
    
    return output_pdf, None

def draw_wrapped_text(c, text, x, y, width, font_name="Helvetica", font_size=12, leading=16):
    """Helper function for text wrapping in PDFs"""
    lines = simpleSplit(text, font_name, font_size, width)
    for line in lines:
        if y < 60:  # bottom margin
            c.showPage()
            c.setFont(font_name, font_size)
            y = A4[1] - 60
        c.drawString(x, y, line)
        y -= leading
    return y

def convert_docs_to_pdf_api(base_name):
    """Modified version of docs_to_pdf that returns file paths"""
    doc_folder = "DOC"
    pdf_folder = "PDF"
    
    doc_files = [
        f for f in os.listdir(doc_folder)
        if f.lower().endswith((".docx", ".txt", ".md", ".rtf", ".odt"))
        and not f.startswith("~$")
        and not f.startswith(".")
    ]
    
    if not doc_files:
        return None, "No document files found"
    
    created_pdfs = []
    next_number = get_next_number()
    
    for file_name in doc_files:
        input_file = os.path.join(doc_folder, file_name)
        ext = os.path.splitext(file_name)[1].lower()
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_pdf = f"{base_name}[{next_number}]_{timestamp}.pdf"
        output_path = os.path.join(pdf_folder, output_pdf)
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
            
            c.save()
            created_pdfs.append(output_pdf)
            
        except Exception as e:
            print(f"Error converting {file_name}: {e}")
            continue
    
    # Clear the DOC folder after conversion
    clear_folder(doc_folder)
    
    return created_pdfs, None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_files():
    """Handle file upload"""
    try:
        file_type = request.form.get('type', 'image')
        
        if 'files' not in request.files:
            return jsonify({'error': 'No files in request'}), 400
            
        files = request.files.getlist('files')
        
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': 'No files provided'}), 400
        
        uploaded_files = []
        target_folder = 'img' if file_type == 'image' else 'DOC'
        
        # Clear the target folder first
        clear_folder(target_folder)
        
        for file in files:
            if file and file.filename and allowed_file(file.filename, file_type):
                filename = secure_filename(file.filename)
                # Ensure the filename keeps its extension
                if '.' not in filename:
                    original_ext = os.path.splitext(file.filename)[1]
                    filename = filename + original_ext
                    
                filepath = os.path.join(target_folder, filename)
                file.save(filepath)
                uploaded_files.append(filename)
        
        if not uploaded_files:
            return jsonify({'error': 'No valid files uploaded'}), 400
        
        return jsonify({
            'success': True,
            'files': uploaded_files,
            'count': len(uploaded_files)
        })
    
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/convert', methods=['POST'])
def convert():
    """Handle PDF conversion"""
    try:
        data = request.json
        file_type = data.get('type', 'image')
        base_name = data.get('baseName', 'output')
        
        if file_type == 'image':
            pdf_file, error = convert_images_to_pdf_api(base_name)
            if error:
                return jsonify({'error': error}), 400
            pdf_files = [pdf_file]
        else:
            pdf_files, error = convert_docs_to_pdf_api(base_name)
            if error:
                return jsonify({'error': error}), 400
        
        return jsonify({
            'success': True,
            'pdfs': pdf_files,
            'message': f'Successfully created {len(pdf_files)} PDF(s)'
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pdfs', methods=['GET'])
def list_pdfs():
    """Get list of existing PDFs"""
    try:
        pdf_folder = 'PDF'
        if not os.path.exists(pdf_folder):
            return jsonify({'pdfs': []})
        
        pdf_files = []
        for filename in os.listdir(pdf_folder):
            if filename.endswith('.pdf'):
                filepath = os.path.join(pdf_folder, filename)
                pdf_files.append({
                    'name': filename,
                    'size': os.path.getsize(filepath),
                    'created': os.path.getctime(filepath)
                })
        
        # Sort by creation time (newest first)
        pdf_files.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({'pdfs': pdf_files})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/open/<filename>', methods=['GET'])
def open_pdf(filename):
    """Open a PDF file"""
    try:
        filepath = os.path.join('PDF', filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        # Open the PDF based on the platform
        if platform.system() == "Darwin":  # macOS
            subprocess.call(["open", filepath])
        elif platform.system() == "Windows":
            os.startfile(filepath)
        else:  # Linux
            subprocess.call(["xdg-open", filepath])
        
        return jsonify({'success': True, 'message': f'Opening {filename}'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete/<filename>', methods=['DELETE'])
def delete_pdf(filename):
    """Delete a PDF file"""
    try:
        filepath = os.path.join('PDF', filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'error': 'File not found'}), 404
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pdf/<filename>')
def serve_pdf(filename):
    """Serve PDF files for download"""
    return send_from_directory('PDF', filename)

if __name__ == '__main__':
    print("🚀 PDF Converter Server starting...")
    print("📂 Make sure you have the following folders: img/, DOC/, PDF/")
    print("🌐 Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)