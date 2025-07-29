import os
import shutil
import uuid
import json
from dotenv import load_dotenv
from PIL import Image, ExifTags
import boto3
import psycopg2

load_dotenv()

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")

# Image compression settings
MAX_FILE_SIZE_MB = 2  # Target max file size in MB
MAX_DIMENSION = 2000  # Max width or height in pixels
JPEG_QUALITY = 85     # JPEG quality (1-100, higher = better quality)

def load_db_credentials():
    """Load database credentials from game_db_credentials.json"""
    with open('game_db_credentials.json', 'r') as f:
        return json.load(f)

def get_db_connection():
    """Create and return a PostgreSQL database connection"""
    try:
        credentials = load_db_credentials()
        connection = psycopg2.connect(
            host=credentials['host'],
            database=credentials['database'],
            user=credentials['user'],
            password=credentials['password'],
            port=credentials.get('port', 5432)
        )
        return connection
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

def update_insurance_card_in_db(insurance_id, s3_url, insurance_type='primary'):
    """Update the insurance_fresh table and insert into insurance table with the S3 URL"""
    if not insurance_id:
        print("No insurance_id provided, skipping database update")
        return
    
    # Determine column name based on insurance type
    column_name = f"{insurance_type}_insurance_card"
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Start transaction
        connection.autocommit = False
        
        # 1. Update the appropriate column in insurance_fresh table
        update_query = f"""
            UPDATE insurance_fresh 
            SET {column_name} = %s 
            WHERE insurance_id = %s
        """
        
        cursor.execute(update_query, (s3_url, insurance_id))
        
        if cursor.rowcount > 0:
            print(f"Successfully updated insurance_fresh table for insurance_id {insurance_id} ({insurance_type})")
        else:
            print(f"Warning: No records found in insurance_fresh for insurance_id {insurance_id}")
        
        # 2. Insert into insurance table with the appropriate column
        insert_query = f"""
            INSERT INTO insurance (insurance_id, {column_name}) 
            VALUES (%s, %s)
        """
        
        cursor.execute(insert_query, (insurance_id, s3_url))
        print(f"Successfully inserted/updated insurance table for insurance_id {insurance_id} ({insurance_type})")
        
        # Commit both operations
        connection.commit()
        print(f"Database operations completed successfully for insurance_id {insurance_id} with S3 URL: {s3_url} ({insurance_type})")
        
        cursor.close()
        connection.close()
        
    except Exception as e:
        # Rollback in case of error
        if connection:
            connection.rollback()
            print(f"Database transaction rolled back due to error: {e}")
        print(f"Error updating database: {e}")
        raise

def create_s3_client():
    """Create and return an S3 client"""
    return boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )

def upload_to_s3(file_path, file_name):
    """Upload a file to S3 and return the URL"""
    try:
        s3_client = create_s3_client()
        
        # Generate unique key for S3
        file_ext = os.path.splitext(file_name)[1]
        new_file_id = str(uuid.uuid4())
        new_file_name = f"{new_file_id}{file_ext}"
        new_file_key = f"uploads/{new_file_name}"
        
        # Upload to S3
        with open(file_path, 'rb') as file_data:
            s3_client.upload_fileobj(
                file_data,
                S3_BUCKET,
                new_file_key,
                ExtraArgs={
                    'ContentType': 'application/pdf',
                }
            )
        
        # Generate S3 URL
        s3_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{new_file_key}"
        print(f"Successfully uploaded to S3: {s3_url}")
        
        return s3_url
        
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        raise

# ORIGINAL WORKING IMAGE FUNCTIONS - UNCHANGED
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

def convert_img_to_pdf(images_paths, output_path):
    """
    Convert images to PDF in the correct order (front first, back second).
    
    Args:
        images_paths: List of image file paths in the correct order
        output_path: Path where the PDF will be saved
    """
    imgs = []
    
    # Process images in the order they were provided
    for img_path in images_paths:
        if os.path.exists(img_path) and img_path.lower().endswith(('.png', '.jpg', '.jpeg')):
            img = Image.open(img_path).convert('RGB')  # ORIGINAL SIMPLE METHOD THAT WORKS
            imgs.append(img)
            print(f"Added to PDF: {os.path.basename(img_path)}")
    
    if len(imgs) == 0:
        raise ValueError("No images to convert!")
    
    if len(imgs) < 2:
        raise ValueError("Need at least 2 images for front and back of insurance card")
    
    # Save with first image as base, append the rest
    imgs[0].save(output_path, save_all=True, append_images=imgs[1:])
    print(f"PDF created with {len(imgs)} images in correct order")

def process_insurance_cards(images_folder, insurance_id=None, insurance_type='primary'):
    """
    Process insurance card images and upload to S3, optionally update database
    
    Args:
        images_folder: Path to folder containing images
        insurance_id: Optional insurance ID for database update
        insurance_type: Type of insurance ('primary' or 'secondary')
    
    Returns:
        str: S3 URL of uploaded PDF
    """
    # Validate AWS credentials
    if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET]):
        raise ValueError("Missing AWS credentials or S3 bucket configuration")
    
    # Validate database credentials file exists if insurance_id is provided
    if insurance_id and not os.path.exists('game_db_credentials.json'):
        raise ValueError("game_db_credentials.json file not found")
    
    all_files = os.listdir(images_folder)
    image_files = [f for f in all_files if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    
    # Sort by file modification time (which preserves upload order)
    image_files.sort(key=lambda x: os.path.getmtime(os.path.join(images_folder, x)))
    
    processed_images = []
    
    for img_file in image_files:
        img_path = os.path.join(images_folder, img_file)
        
        # Step 1: Auto-rotate based on EXIF
        auto_rotate_image(img_path)
        
        # Step 2: Compress the image
        compress_image(img_path)
        
        processed_images.append(img_path)
        print(f"Processed image {len(processed_images)}: {img_file}")
    
    if len(processed_images) < 2:
        raise ValueError("Need at least 2 images for front and back of insurance card")
    
    # Generate unique PDF filename using UUID
    pdf_filename = f"{str(uuid.uuid4())}.pdf"
    pdf_path = os.path.join(images_folder, pdf_filename)
    
    # Create PDF from processed images in correct order (front first, back second)
    convert_img_to_pdf(processed_images, pdf_path)
    
    # Upload to S3
    s3_url = upload_to_s3(pdf_path, pdf_filename)
    
    # Update database if insurance_id is provided
    if insurance_id:
        update_insurance_card_in_db(insurance_id, s3_url, insurance_type)
    
    return s3_url