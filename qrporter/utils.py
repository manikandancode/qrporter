# qrporter/utils.py

def allowed_file(filename: str) -> bool:
    allowed = {
        # Documents
        "txt", "pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "rtf", "csv",
        # Images
        "png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff",
        # Audio
        "mp3", "wav", "m4a", "aac", "flac", "ogg",
        # Video
        "mp4", "mov", "avi", "mkv", "webm", "m4v",
        # Archives
        "zip", "7z", "tar", "gz", "bz2",
    }
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed
