from flask import Flask, request, render_template, jsonify
import tempfile
import shutil
from processing import process_insurance_cards
import os
from flask_cors import CORS
import logging

app = Flask(__name__)
CORS(app)

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

@app.route('/', methods=['GET', 'POST'])
def upload_form_or_process():
    return handle_upload(None)

@app.route('/<insurance_id>', methods=['GET', 'POST'])
def upload_form_or_process_with_id(insurance_id):
    return handle_upload(insurance_id)

def handle_upload(insurance_id):
    if request.method == 'GET':
        try:
            return render_template('upload.html')
        except Exception as e:
            print(f"Template error: {e}")
            return jsonify({"error": "Template not found"}), 500
    
    try:
        files = request.files.getlist('images')
        
        # ✅ EXTRACT INSURANCE TYPE FROM REQUEST
        insurance_type = request.form.get('insurance_type', 'primary')
        print(f"DEBUG: received {len(files)} files for insurance_id: {insurance_id}, type: {insurance_type}")
        
        for f in files:
            print(f" - filename: {f.filename}")
        
        files = [f for f in files if f and f.filename]
        
        if len(files) != 2:
            return jsonify({"error": "Please upload exactly two images (front and back of insurance card)."}), 400
        
        allowed_extensions = {'.jpg', '.jpeg', '.png'}
        for file in files:
            if not file.filename:
                return jsonify({"error": "All files must have filenames."}), 400
            
            file_ext = os.path.splitext(file.filename.lower())[1]
            print(f"Received file: {file.filename}, extension: {file_ext}")
            
            if file_ext not in allowed_extensions:
                return jsonify({"error": f"File {file.filename} must be a JPG, JPEG, or PNG image."}), 400
        
        temp_dir = tempfile.mkdtemp()
        
        try:
            saved_files = []
            for file in files:
                file_path = os.path.join(temp_dir, file.filename)
                file.save(file_path)
                saved_files.append(file_path)
                
                if not os.path.exists(file_path):
                    raise Exception(f"Failed to save file: {file.filename}")
                
                file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                print(f"Uploaded {file.filename}: {file_size_mb:.2f}MB")
            
            # ✅ PASS BOTH insurance_id AND insurance_type
            s3_url = process_insurance_cards(temp_dir, insurance_id, insurance_type)
            
            return jsonify({
                "link": s3_url,
                "message": f"{insurance_type.capitalize()} insurance cards processed successfully!",
                "insurance_id": insurance_id,
                "insurance_type": insurance_type  # ✅ Include in response for debugging
            })
            
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
    except Exception as e:
        error_msg = str(e)
        print(f"Error processing insurance cards: {error_msg}")
        
        if "413" in error_msg or "Request Entity Too Large" in error_msg:
            return jsonify({"error": "File size too large. Please upload smaller images (under 10MB each)."}), 413
        elif "No images to convert" in error_msg:
            return jsonify({"error": "No valid image files found. Please upload JPG, JPEG, or PNG files."}), 400
        elif "Need at least 2 images" in error_msg:
            return jsonify({"error": "Please upload exactly 2 images (front and back of insurance card)."}), 400
        else:
            return jsonify({"error": f"Processing failed: {error_msg}"}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File size too large. Please upload images smaller than 10MB each."}), 413

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request. Please check your file uploads."}), 400

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error. Please try again."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8004, debug=True)