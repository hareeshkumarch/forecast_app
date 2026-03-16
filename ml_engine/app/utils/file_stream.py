import os
import uuid
import aiofiles
from fastapi import UploadFile
from app.core.config import settings

async def stream_upload_file(file: UploadFile) -> str:
    os.makedirs(settings.UPLOAD_DIRECTORY, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    file_id = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(settings.UPLOAD_DIRECTORY, file_id)
    
    # Secure path traversal check
    if not os.path.abspath(filepath).startswith(os.path.abspath(settings.UPLOAD_DIRECTORY)):
        raise ValueError("Invalid file path")
        
    async with aiofiles.open(filepath, 'wb') as out_file:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            await out_file.write(chunk)
            
    return filepath
