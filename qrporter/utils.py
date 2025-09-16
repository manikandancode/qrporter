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
        # Installers - Windows
        "exe", "msi", "bat", "cmd",
        # Installers - Linux
        "deb", "rpm", "appimage", "flatpakref", "flatpakrepo", "flatpak", "snap", "assert", "apk", "aab",
        # Installers - macOS
        "dmg", "pkg", "app",
        # Additional Archives (for installers)
        "xz"  # for .tar.xz support
    }
    
    if '.' not in filename:
        return False
    
    # Handle special cases for compound extensions
    filename_lower = filename.lower()
    
    # Check for compound extensions first
    compound_extensions = [
        ".tar.gz", ".tar.xz", ".tar.bz2"
    ]
    
    for compound_ext in compound_extensions:
        if filename_lower.endswith(compound_ext):
            return True
    
    # Check single extensions
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in allowed
