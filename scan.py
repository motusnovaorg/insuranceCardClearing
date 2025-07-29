import os
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from dotenv import load_dotenv
from openai import OpenAI
import re
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.http import MediaFileUpload
from googleapiclient.discovery import build

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_ID = os.getenv('FOLDER_ID')

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"
project_id = "insurancecardscarping"
location = "us" 
processor_display_name = "insurance_card_scraper"
output_json_path = "ocr_output.json"

def make_open_ai_client(openai_api_key):
    return OpenAI(api_key = openai_api_key)

def get_or_create_processor(client, parent, processor_display_name):
    for processor in client.list_processors(parent=parent):
        if processor.display_name == processor_display_name:
            print(f"Found existing processor: {processor.name}")
            return processor.name
    processor = client.create_processor(
        parent=parent,
        processor=documentai.Processor(
            type_="OCR_PROCESSOR",
            display_name=processor_display_name,
        ),
    )
    print(f"Created new processor: {processor.name}")
    return processor.name

def analyze_all(data, client, max_tokens=2000):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an assistant that summarizes, analyzes text, and presents text in a given format."},
                {
                    "role": "user",
                    "content": f"""Here is the text data from a patient's insurance card: \n\n{data}\n\n
                                    Please extract the following information:\n
                                    Insurance Company Name\nPatient First Name\nPatient Last Name\nMember ID\nGroup ID/ Group Number\nInsurance Plan\n
                                    DO NOT ADD ANY FORMATTING TO THE INFORMATION THAT YOU GIVE ME.
                                """
                }
            ]
        )
        analysis = response.choices[0].message.content.strip()
        return analysis
    except Exception as e:
        print(f"Error analyzing text with OpenAI: {e}")
        return ["Analysis failed for one or more chunks."]

def write_to_text_file(file_path, text):
    with open(file_path, "a") as text_file:
        text_file.write(text)

def quickstart(project_id, location, processor_display_name, output_json_path, client_openai, file_path):
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    parent = client.common_location_path(project_id, location)
    processor_name = get_or_create_processor(client, parent, processor_display_name)
    combined_text = ""
    with open(file_path, "rb") as image:
        image_content = image.read()
    raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
    request = documentai.ProcessRequest(name=processor_name, raw_document=raw_document)
    result = client.process_document(request=request)
    document = result.document
    print(f"Processed Image: {file_path}")
    return document.text

def delete_folder(folder_path):
    if os.path.exists(folder_path):
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                delete_folder(item_path)
        os.rmdir(folder_path)
    else:
        print("The folder does not exist")

def convert_to_dictionary(analysis_results):
    insurance_dict = {}
    for line in analysis_results.split("\n"):
        if ": " in line:
            key, value = line.split(": ", 1)
            clean_key = re.sub(r"\*\*", "", key).strip()
            insurance_dict[clean_key] = value.strip()
    return insurance_dict

def make_output_path(first_name, last_name):
    file_path_name_dict = {}
    file_path_name_dict['File Path'] = f"./Output/{first_name}{last_name}InsuranceCard.pdf"
    file_path_name_dict['File Name'] = f"{first_name}{last_name}InsuranceCard.pdf"
    return file_path_name_dict

def convert_img_to_pdf(images_path, output_path):
    if not os.path.isdir(images_path):
        raise ValueError("Provided path is not a valid directory.")
    image_list = []
    valid_extensions = (".jpg", ".jpeg", ".png")  # Allowed image types
    for img_file in sorted(os.listdir(images_path)):  # Sorting ensures order
        img_path = os.path.join(images_path, img_file)
        if img_file.lower().endswith(valid_extensions):  # Check if it's an image
            try:
                image = Image.open(img_path).convert("RGB")  # Convert to RGB mode
                image_list.append(image)
            except Exception as e:
                print(f"Error processing {img_path}: {e}")
    if not image_list:
        raise ValueError("No valid images found to process.")
    first_image = image_list.pop(0)
    first_image.save(output_path, save_all=True, append_images=image_list)
    print(f"PDF saved successfully as: {output_path}")

def authenticate_services():
    credentials = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=credentials)
    return drive_service

def upload_file_to_drive(drive_service, file_path, file_name, folder_id):
    file_metadata = {'name': file_name}
    if folder_id:
        file_metadata['parents'] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = uploaded_file.get('id')
    drive_service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
    shareable_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    return shareable_link

def main():
    delete_folder("Output")
    client_openai = make_open_ai_client(OPENAI_API_KEY)
    faxes_file_path = "./insuranceCardImages"
    combined_text = ""
    for file in os.listdir(faxes_file_path):
        file_path = os.path.join("./insuranceCardImages", file)
        text = quickstart(project_id, location, processor_display_name, output_json_path, client_openai, file_path)
        combined_text += text + "\n"
    analysis_results = analyze_all(combined_text, client_openai, 500)
    output_dict = convert_to_dictionary(analysis_results)
    os.makedirs("./Output", exist_ok=True)
    write_to_text_file('./Output/OCR_results.txt', combined_text)
    write_to_text_file('./Output/Chatgpt_results.txt', analysis_results)
    output_dict = make_output_path(output_dict['Patient First Name'], output_dict['Patient Last Name'])
    convert_img_to_pdf("./insuranceCardImages", output_dict['File Path'])
    drive_service = authenticate_services()
    shareable_link = upload_file_to_drive(drive_service, output_dict['File Path'], output_dict['File Name'], FOLDER_ID)
    print(f"Final Shareable Link: {shareable_link}")
    
if __name__ == "__main__":
    main()