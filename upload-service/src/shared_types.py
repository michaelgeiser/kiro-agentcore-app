ACCEPTED_CONTENT_TYPES: dict[str, list[str]] = {
    "audio": ["audio/mpeg", "audio/wav", "audio/x-m4a", "audio/aac"],
    "video": ["video/mp4", "video/quicktime", "video/webm"],
}

ACCEPTED_EXTENSIONS: list[str] = [".mp3", ".wav", ".m4a", ".aac", ".mp4", ".mov", ".webm"]

MAX_FILE_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 MB

CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "https://kiro.geiserai.com",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}
