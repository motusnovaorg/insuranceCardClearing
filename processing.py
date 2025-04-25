import os
import re
import shutil
from dotenv import load_dotenv
from PIL import Image
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.api_core.client_options import ClientOptions
from google.cloud import documentai

load_dotenv()

# Config
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = os.getenv('FOLDER_ID')
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"
project_id = "insurancecardscarping"
location = "us"
processor_display_name = "insurance_card_scraper"

# Helper functions
def make_open_ai_client(api_key):
    return OpenAI(api_key=api_key)

def get_or_create_processor(client, parent, display_name):
    for processor in client.list_processors(parent=parent):
        if processor.display_name == display_name:
            return processor.name
    processor = client.create_processor(parent=parent, processor=documentai.Processor(type_="OCR_PROCESSOR", display_name=display_name))
    return processor.name

def analyze_all(text, client, max_tokens=2000):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an assistant that summarizes insurance card text."},
            {"role": "user", "content": f"Here is insurance card text:\n\n{text}\n\nExtract the Patient First Name, Last Name, Member ID, Group ID, and Insurance Company name."}
        ]
    )
    return response.choices[0].message.content.strip()

def convert_to_dictionary(text):
    data = {}
    for line in text.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            data[key.strip()] = value.strip()
    return data

def authenticate_services():
    creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def upload_file_to_drive(drive_service, file_path, file_name, folder_id):
    metadata = {'name': file_name}
    if folder_id:
        metadata['parents'] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = drive_service.files().create(body=metadata, media_body=media, fields='id').execute()
    file_id = uploaded['id']
    drive_service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

def quickstart(project_id, location, display_name, file_path):
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    parent = client.common_location_path(project_id, location)
    processor_name = get_or_create_processor(client, parent, display_name)

    with open(file_path, "rb") as image:
        content = image.read()

    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=documentai.RawDocument(content=content, mime_type="image/jpeg")
    )

    result = client.process_document(request=request)
    return result.document.text

def convert_img_to_pdf(images_path, output_path):
    imgs = []
    for file in sorted(os.listdir(images_path)):
        if file.lower().endswith(('.png', '.jpg', '.jpeg')):
            img = Image.open(os.path.join(images_path, file)).convert('RGB')
            imgs.append(img)
    if imgs:
        imgs[0].save(output_path, save_all=True, append_images=imgs[1:])
    else:
        raise ValueError("No images to convert!")

from PIL import Image, ExifTags

def auto_rotate_image(image_path):
    try:
        img = Image.open(image_path)
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break

        exif = img._getexif()
        if exif is not None:
            orientation_value = exif.get(orientation)
            if orientation_value == 3:
                img = img.rotate(180, expand=True)
            elif orientation_value == 6:
                img = img.rotate(270, expand=True)
            elif orientation_value == 8:
                img = img.rotate(90, expand=True)

        img.save(image_path)  # Overwrite original image
        img.close()

    except (AttributeError, KeyError, IndexError):
        # Image doesn't have EXIF data
        pass

def process_insurance_cards(images_folder):
    openai_client = make_open_ai_client(OPENAI_API_KEY)

    # Separate front and back images
    all_images = sorted(os.listdir(images_folder))
    front_image_path = os.path.join(images_folder, all_images[0])
    back_image_path = os.path.join(images_folder, all_images[1])

    # 🛠 Auto-rotate both images
    auto_rotate_image(front_image_path)
    auto_rotate_image(back_image_path)

    # OCR only the front image
    front_text = quickstart(project_id, location, processor_display_name, front_image_path)

    # Analyze to extract patient info
    analysis = analyze_all(front_text, openai_client, 500)
    info = convert_to_dictionary(analysis)

    # Clean patient names
    first_name = info.get('Patient First Name', 'Friend').strip().capitalize()
    last_name = info.get('Patient Last Name', 'Unknown').strip().capitalize()

    # ✨ Combine into one full name
    full_name = f"{first_name} {last_name}"

    # Create output PDF
    pdf_filename = f"{first_name}{last_name}InsuranceCard.pdf"
    pdf_path = os.path.join(images_folder, pdf_filename)
    convert_img_to_pdf(images_folder, pdf_path)

    # Upload to Drive
    drive_service = authenticate_services()
    link = upload_file_to_drive(drive_service, pdf_path, pdf_filename, FOLDER_ID)

    # 🚀 FINAL RETURN
    return link, full_name