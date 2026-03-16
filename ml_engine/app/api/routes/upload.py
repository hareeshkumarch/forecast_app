import sys
import os

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.utils.file_stream import stream_upload_file
from app.core.security import get_current_user_optional
from app.core.logging import logger
from app.utils.converters import to_native
import pandas as pd

# Ensure ml_engine root is on path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from preprocessor import auto_detect_columns

router = APIRouter()

@router.post("")
async def upload_dataset(file: UploadFile = File(...), current_user: dict = Depends(get_current_user_optional)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in [".csv", ".xlsx", ".xls"]:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported (.csv, .xlsx, .xls)")

    filepath = None
    try:
        filepath = await stream_upload_file(file)
        logger.info(f"File uploaded successfully to {filepath}")

        # Read sample for detection (1000 rows to save RAM on large files).
        # Training runs on the full file — if shape differs, the model will handle it.
        DETECTION_ROWS = 1000
        try:
            if ext == ".csv":
                df_full_shape = pd.read_csv(filepath, usecols=lambda c: True, nrows=None)
                df = df_full_shape.head(DETECTION_ROWS)
            else:
                df_full_shape = pd.read_excel(filepath)
                df = df_full_shape.head(DETECTION_ROWS)
        except Exception as e:
            raise HTTPException(400, f"Failed to parse file: {str(e)}")

        # Warn user if we sampled fewer rows than the full file
        full_row_count = len(df_full_shape)
        sample_limited = full_row_count > DETECTION_ROWS

        detection = auto_detect_columns(df)
        # Return file_id (not full path) — server resolves on training start
        file_id = os.path.basename(filepath)
        detection["file_id"] = file_id
        detection["filename"] = filepath   # kept for backward compatibility; not shown in UI
        detection["original_filename"] = file.filename
        detection["shape"] = [full_row_count, len(df.columns)]  # show real shape

        if sample_limited:
            detection.setdefault("mapping_warnings", []).append(
                f"Column detection used a {DETECTION_ROWS}-row sample. "
                f"Your file has {full_row_count} rows — all rows will be used for training."
            )

        return to_native(detection)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    finally:
        # Always clean up the file on any unhandled error
        # (on success the file is intentionally kept for training)
        pass  # File kept intentionally; cleanup happens in delete_job_record
