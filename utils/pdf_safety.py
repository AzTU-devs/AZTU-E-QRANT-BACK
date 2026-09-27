"""Safe ReportLab helpers.

ReportLab's Paragraph parses an XML-like mini-markup, so any user-controlled
value put into one must be escaped or a stray `<`/`&` corrupts the PDF and
`<img src=...>`/`<font>` tags could be injected. And ReportLab will happily
fetch a remote `<img src="http://...">`, a blind SSRF from the server. Both are
finding B-M1.

Use `rl_text()` for every dynamic value passed to Paragraph, and call
`harden_reportlab()` once at startup to forbid remote image fetches.
"""

from xml.sax.saxutils import escape


def rl_text(value):
    """Escaped text for a ReportLab Paragraph. None/empty renders as an em dash."""
    if value is None:
        return "—"
    text = str(value)
    if text == "":
        return "—"
    return escape(text)


def harden_reportlab():
    """Forbid ReportLab from resolving remote hosts/schemes in markup, so a
    `<img src="http://internal/...">` in user text cannot trigger a fetch."""
    try:
        import reportlab.rl_config as rl_config
        rl_config.trustedHosts = []
        # Only allow inline data URIs and on-disk files (our own assets); never
        # http/https/ftp.
        rl_config.trustedSchemes = ['file', 'data']
    except Exception:
        # PDF generation is optional; never let hardening break app startup.
        pass
