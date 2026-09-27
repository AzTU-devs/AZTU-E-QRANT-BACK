"""One safe way to serve an uploaded file.

The content type is decided from OUR stored extension, never the uploader's
claimed one. Raster images and PDFs are served inline (previewable); everything
else — including SVG, which can carry script — is forced to download as
`application/octet-stream` and never rendered by the browser (finding B-SVG).
File responses are additionally sandboxed by the CSP in app.py.
"""

from flask import send_file

INLINE_RASTER = {
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
    'gif': 'image/gif', 'webp': 'image/webp', 'bmp': 'image/bmp',
}


def _ext(name):
    return name.rsplit('.', 1)[-1].lower() if name and '.' in name else ''


def serve_upload(path, stored_filename, download_name):
    ext = _ext(stored_filename)
    if ext in INLINE_RASTER:
        return send_file(path, as_attachment=False, download_name=download_name,
                         mimetype=INLINE_RASTER[ext])
    if ext == 'pdf':
        return send_file(path, as_attachment=False, download_name=download_name,
                         mimetype='application/pdf')
    # SVG, Office documents, archives, anything unknown: never rendered inline.
    return send_file(path, as_attachment=True, download_name=download_name,
                     mimetype='application/octet-stream')
