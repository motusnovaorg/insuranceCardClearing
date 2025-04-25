from flask import Flask, request, render_template
import tempfile
import shutil
from processing import process_insurance_cards
import os

app = Flask(__name__)

@app.route('/', methods=['GET'])
def upload_form():
    return render_template('upload.html')

@app.route('/', methods=['POST'])
def upload_and_process():
    try:
        files = request.files.getlist('images')
        if not files or len(files) != 2:
            return {"error": "Please upload exactly two images."}, 400

        temp_dir = tempfile.mkdtemp()

        for file in files:
            if file.filename:
                file.save(os.path.join(temp_dir, file.filename))

        shareable_link, patient_full_name = process_insurance_cards(temp_dir)

        shutil.rmtree(temp_dir)

        return {
            "link": shareable_link,
            "full_name": patient_full_name
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"error": str(e)}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)