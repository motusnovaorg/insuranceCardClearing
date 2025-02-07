import os
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_credentials.json"
project_id = "faxclearing"
location = "us" 
processor_display_name = "fax_automation"
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
                                    Insurance Company Name\nPatient's Name\nMember ID\nGroup ID/ Group Number\nInsurance Plan\n
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
    os.makedirs("./Output", exist_ok=True)
    write_to_text_file('./Output/OCR_results.txt', combined_text)
    write_to_text_file('./Output/Chatgpt_results.txt', analysis_results)

if __name__ == "__main__":
    main()