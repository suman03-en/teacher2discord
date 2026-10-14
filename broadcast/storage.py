"""
Custom storage backends for media uploads.
"""

import os

import cloudinary.uploader
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.core.files.uploadedfile import UploadedFile


class AdaptiveCloudinaryStorage(MediaCloudinaryStorage):
    """Cloudinary storage backend that automatically detects the proper
    resource_type ('image', 'video', or 'raw') based on the file extension.

    This ensures images, videos, and raw documents (PDF, zip, docx, etc.)
    are stored and served from their respective Cloudinary endpoints.
    """

    IMAGE_EXTENSIONS = {
        "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "tiff", "tif", "avif"
    }
    VIDEO_EXTENSIONS = {
        "mp4", "webm", "mov", "avi", "mkv", "ogv", "3gp", "flv", "wmv", "m4v"
    }
    RAW_EXTENSIONS = {
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv",
        "zip", "tar", "gz", "7z", "rar", "json", "xml", "md", "rtf", "odt",
        "ods", "odp"
    }

    def _get_resource_type(self, name):
        base = os.path.basename(name)
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if ext in self.VIDEO_EXTENSIONS:
            return "video"
        if ext in self.RAW_EXTENSIONS:
            return "raw"
        if ext in self.IMAGE_EXTENSIONS:
            return "image"
        # If the file has no recognized extension, or the format extension was
        # stripped by Cloudinary upon saving (e.g. "...com_lzbiog"), default to "image"
        # which matches standard MediaCloudinaryStorage behavior.
        return "image"

    def _save(self, name, content):
        name = self._normalise_name(name)
        name = self._prepend_prefix(name)
        content = UploadedFile(content, name)
        response = self._upload(name, content)
        public_id = response["public_id"]
        resource_type = response.get("resource_type", "image")
        # Ensure video files retain their extension so url() recognizes them as video
        if resource_type == "video":
            fmt = response.get("format", "mp4")
            if not public_id.lower().endswith(f".{fmt.lower()}"):
                public_id = f"{public_id}.{fmt}"
        return public_id

    def delete(self, name):
        resource_type = self._get_resource_type(name)
        public_id = name
        # Strip extension for image/video format if present so destroy finds it
        if resource_type in ("image", "video") and "." in public_id:
            ext = public_id.rsplit(".", 1)[-1].lower()
            if ext in self.IMAGE_EXTENSIONS or ext in self.VIDEO_EXTENSIONS:
                public_id = public_id.rsplit(".", 1)[0]
        response = cloudinary.uploader.destroy(
            public_id, invalidate=True, resource_type=resource_type
        )
        return response.get("result") == "ok"
