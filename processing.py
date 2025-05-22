import os
import re
import shutil
from dotenv import load_dotenv
from PIL import Image, ExifTags
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
import datetime

load_dotenv()

# Config
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = os.getenv('FOLDER_ID')
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"
project_id = "insurancecardscarping"
location = "us"
processor_display_name = "insurance_card_scraper"

# Image compression settings
MAX_FILE_SIZE_MB = 2  # Target max file size in MB
MAX_DIMENSION = 2000  # Max width or height in pixels
JPEG_QUALITY = 85     # JPEG quality (1-100, higher = better quality)

def compress_image(image_path, max_size_mb=MAX_FILE_SIZE_MB, max_dimension=MAX_DIMENSION, quality=JPEG_QUALITY):
    """
    Compress an image to reduce file size while maintaining OCR readability.
    
    Args:
        image_path: Path to the image file
        max_size_mb: Maximum file size in MB
        max_dimension: Maximum width or height in pixels
        quality: JPEG quality (1-100)
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (for JPEG compatibility)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Get original dimensions
            width, height = img.size
            
            # Calculate new dimensions while maintaining aspect ratio
            if width > max_dimension or height > max_dimension:
                if width > height:
                    new_width = max_dimension
                    new_height = int((height * max_dimension) / width)
                else:
                    new_height = max_dimension
                    new_width = int((width * max_dimension) / height)
                
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save with compression
            temp_path = image_path + "_temp"
            img.save(temp_path, "JPEG", quality=quality, optimize=True)
            
            # Check file size and adjust quality if needed
            file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
            
            # If still too large, reduce quality further
            while file_size_mb > max_size_mb and quality > 30:
                quality -= 10
                img.save(temp_path, "JPEG", quality=quality, optimize=True)
                file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
            
            # Replace original with compressed version
            shutil.move(temp_path, image_path)
            
            print(f"Compressed {os.path.basename(image_path)}: {file_size_mb:.2f}MB (quality: {quality})")
            
    except Exception as e:
        print(f"Error compressing image {image_path}: {str(e)}")
        # If compression fails, keep original file
        if os.path.exists(image_path + "_temp"):
            os.remove(image_path + "_temp")

def auto_rotate_image(image_path):
    """Auto-rotate image based on EXIF orientation data."""
    try:
        img = Image.open(image_path)
        
        # Handle EXIF orientation
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
        
        img.save(image_path)
        img.close()
    except (AttributeError, KeyError, IndexError, TypeError):
        # Image doesn't have EXIF data or other issues
        pass

def make_open_ai_client(api_key):
    return OpenAI(api_key=api_key)

def get_or_create_processor(client, parent, display_name):
    for processor in client.list_processors(parent=parent):
        if processor.display_name == display_name:
            return processor.name
    processor = client.create_processor(
        parent=parent, 
        processor=documentai.Processor(type_="OCR_PROCESSOR", display_name=display_name)
    )
    return processor.name

def analyze_all(text, client, max_tokens=2000):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an assistant that extracts specific information from insurance card text. Always respond in the exact format requested."},
            {"role": "user", "content": f"""Here is insurance card text:\n\n{text}\n\nPlease extract the following information and format your response EXACTLY as shown below. If any information is not found, use the specified default values:

Patient First Name: [first name or "Friend" if not found]
Patient Last Name: [last name or "Unknown" if not found]
Member ID: [member ID or "Not Found" if not found]
Group ID: [group ID or "Not Found" if not found]
Insurance Company: [company name or "Not Found" if not found]

Important: Use this exact format with colons and the exact field names shown above."""}
        ]
    )
    return response.choices[0].message.content.strip()

def convert_to_dictionary(text):
    """Convert the OpenAI response to a dictionary with better error handling."""
    data = {}
    
    # Add some debug logging
    print(f"Raw OpenAI response:\n{text}\n")
    
    for line in text.splitlines():
        line = line.strip()
        if ": " in line:
            key, value = line.split(": ", 1)
            data[key.strip()] = value.strip()
    
    # Ensure we have the required keys with defaults
    required_fields = {
        'Patient First Name': 'Friend',
        'Patient Last Name': 'Unknown',
        'Member ID': 'Not Found',
        'Group ID': 'Not Found',
        'Insurance Company': 'Not Found'
    }
    
    for field, default in required_fields.items():
        if field not in data or not data[field] or data[field].lower() in ['not found', 'not provided', 'not available', 'n/a', '']:
            data[field] = default
    
    print(f"Parsed data: {data}")
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
    drive_service.permissions().create(
        fileId=file_id, 
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()
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
            img_path = os.path.join(images_path, file)
            img = Image.open(img_path).convert('RGB')
            imgs.append(img)
    
    if imgs:
        imgs[0].save(output_path, save_all=True, append_images=imgs[1:])
    else:
        raise ValueError("No images to convert!")

def log_to_google_sheet(first_name, last_name, link):
    sheet_id = os.getenv("WORKBOOK_ID")
    sheet_name = os.getenv("SHEET_NAME")
    creds = service_account.Credentials.from_service_account_file(
        'credentials.json', 
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [[timestamp, first_name, last_name, link]]
    
    request = sheet.values().append(
        spreadsheetId=sheet_id,
        range=f"{sheet_name}!A:D",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": row}
    )
    request.execute()

def process_insurance_cards(images_folder):
    openai_client = make_open_ai_client(OPENAI_API_KEY)
    
    # Get all images and process them
    all_images = sorted(os.listdir(images_folder))
    processed_images = []
    
    for img_file in all_images:
        if img_file.lower().endswith(('.png', '.jpg', '.jpeg')):
            img_path = os.path.join(images_folder, img_file)
            
            # Step 1: Auto-rotate based on EXIF
            auto_rotate_image(img_path)
            
            # Step 2: Compress the image
            compress_image(img_path)
            
            processed_images.append(img_path)
    
    if len(processed_images) < 2:
        raise ValueError("Need at least 2 images for front and back of insurance card")
    
    # Process the front image for OCR
    front_image_path = processed_images[0]
    front_text = quickstart(project_id, location, processor_display_name, front_image_path)
    
    # Analyze with OpenAI
    analysis = analyze_all(front_text, openai_client, 500)
    info = convert_to_dictionary(analysis)
    
    # Extract patient information with better error handling
    first_name = info.get('Patient First Name', 'Friend')
    last_name = info.get('Patient Last Name', 'Unknown')
    
    # Clean up the names
    if isinstance(first_name, str):
        first_name = first_name.strip().capitalize()
        if first_name.lower() in ['not found', 'not provided', 'not available', 'n/a', '']:
            first_name = 'Friend'
    else:
        first_name = 'Friend'
        
    if isinstance(last_name, str):
        last_name = last_name.strip().capitalize()
        if last_name.lower() in ['not found', 'not provided', 'not available', 'n/a', '']:
            last_name = 'Unknown'
    else:
        last_name = 'Unknown'
    
    full_name = f"{first_name} {last_name}"
    
    # Create PDF from processed images
    pdf_filename = f"{first_name}{last_name}InsuranceCard.pdf"
    pdf_path = os.path.join(images_folder, pdf_filename)
    convert_img_to_pdf(images_folder, pdf_path)
    
    # Upload to Google Drive
    drive_service = authenticate_services()
    link = upload_file_to_drive(drive_service, pdf_path, pdf_filename, FOLDER_ID)
    
    # Log to Google Sheets
    log_to_google_sheet(first_name, last_name, link)
    
    return link, full_name