import io
from datetime import datetime


def settlement_pdf_bytes(settlement: dict, user_name: str) -> bytes:
    """Minimal PDF without reportlab dependency — plain text PDF."""
    lines = [
        f"GEMINI AI · 双子星AI量化 - Settlement #{settlement.get('id')}",
        f"User: {user_name}",
        f"Period: {settlement.get('period_start')} - {settlement.get('period_end')}",
        f"Gross Profit: ${settlement.get('gross_profit', 0):.2f}",
        f"High-Water Mark: ${settlement.get('high_water_mark', 0):.2f}",
        f"Net Profit (above HWM): ${settlement.get('net_profit', 0):.2f}",
        f"Platform Fee (25%): ${settlement.get('platform_fee', 0):.2f}",
        f"Payable: ${settlement.get('user_payable', 0):.2f}",
        f"Status: {settlement.get('payment_status')}",
        f"Generated: {datetime.utcnow().isoformat()}Z",
    ]
    content = "\\n".join(lines)
    escaped = content.replace("(", "\\(").replace(")", "\\)")
    # Simple PDF structure
    pdf = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length {len(content)+50}>>stream
BT /F1 12 Tf 50 750 Td ({escaped}) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
400
%%EOF"""
    return pdf.encode("latin-1", errors="replace")
