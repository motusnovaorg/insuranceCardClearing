from flask import Flask, request, render_template, jsonify
import tempfile
import shutil
from processing import process_insurance_cards
import os

app = Flask(__name__)

# Configure maximum file size (15MB to allow large uploads before compression)
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024  # 15MB

@app.route('/', methods=['GET'])
def upload_form():
    return render_template('upload.html')

@app.route('/', methods=['POST'])
def upload_and_process():
    try:
        files = request.files.getlist('images')
        
        # Validate number of files
        if not files or len(files) != 2:
            return jsonify({"error": "Please upload exactly two images."}), 400
        
        # Validate file types and sizes
        allowed_extensions = {'.jpg', '.jpeg', '.png'}
        for file in files:
            if not file.filename:
                return jsonify({"error": "All files must have filenames."}), 400
            
            # Check file extension
            file_ext = os.path.splitext(file.filename.lower())[1]
            if file_ext not in allowed_extensions:
                return jsonify({"error": f"File {file.filename} must be a JPG, JPEG, or PNG image."}), 400
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Save uploaded files
            saved_files = []
            for file in files:
                if file.filename:
                    file_path = os.path.join(temp_dir, file.filename)
                    file.save(file_path)
                    saved_files.append(file_path)
                    
                    # Check if file was saved successfully
                    if not os.path.exists(file_path):
                        raise Exception(f"Failed to save file: {file.filename}")
                    
                    # Log original file size
                    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    print(f"Uploaded {file.filename}: {file_size_mb:.2f}MB")
            
            # Process the insurance cards (includes compression)
            shareable_link, patient_full_name = process_insurance_cards(temp_dir)
            
            return jsonify({
                "link": shareable_link,
                "full_name": patient_full_name,
                "message": "Insurance cards processed successfully!"
            })
        
        finally:
            # Always clean up temporary directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    except Exception as e:
        error_msg = str(e)
        print(f"Error processing insurance cards: {error_msg}")
        
        # Handle specific error types
        if "413" in error_msg or "Request Entity Too Large" in error_msg:
            return jsonify({"error": "File size too large. Please upload smaller images (under 15MB each)."}), 413
        elif "No images to convert" in error_msg:
            return jsonify({"error": "No valid image files found. Please upload JPG, JPEG, or PNG files."}), 400
        elif "Need at least 2 images" in error_msg:
            return jsonify({"error": "Please upload exactly 2 images (front and back of insurance card)."}), 400
        else:
            return jsonify({"error": f"Processing failed: {error_msg}"}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File size too large. Please upload images smaller than 15MB each."}), 413

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request. Please check your file uploads."}), 400

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error. Please try again."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8004, debug=True)